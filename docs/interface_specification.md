# Interface Specification

> **쑈삥끼 (ShopPinkki)** — 모듈 간 통신 규칙 전체 명세
> 채널 레이블(A~H)은 `docs/system_architecture.md` 기준

---

## 채널 구성도

```
Browser (Customer UI)
    │  WebSocket (채널 A)
    ▼
customer_web :8501 ──[REST :8000]──▶ LLM AI (채널 D)
    │  TCP :8080 (채널 C)
    ▼
control_service :8080/:8081
    ├── [TCP :5432]  ──▶ PostgreSQL   (채널 E)
    ├── [TCP :5005]  ──▶ YOLO AI      (채널 F)
    └── [ROS2 DDS]  ◀▶  Pi (shoppinkki_core) (채널 G)
                              │
Admin UI ──[TCP :8080]──▶ control_service (채널 B)
                              Pi ◀▶ pinky_pro  (채널 H, ROS2 + UDP :9000)
```

---

## 1. Python 내부 프로토콜

**위치:** `src/shoppinkki/shoppinkki_interfaces/shoppinkki_interfaces/protocols.py`

### 공유 데이터 타입

```python
@dataclass
class Detection:
    cx: float          # bbox 중심 X (픽셀)
    cy: float          # bbox 중심 Y (픽셀)
    area: float        # bbox 면적 (픽셀²) — P-Control 선속도 계산용
    confidence: float  # YOLO 감지 신뢰도 (0.0 ~ 1.0)
    class_name: str = 'doll'

@dataclass
class CartItem:
    item_id: int
    product_name: str
    price: int
    is_paid: bool
    scanned_at: str    # ISO-8601 datetime

class BTStatus(Enum):
    RUNNING = 'RUNNING'
    SUCCESS = 'SUCCESS'
    FAILURE = 'FAILURE'
```

### 인터페이스 프로토콜

```python
class DollDetectorInterface(Protocol):
    def register(self, frame) -> None: ...
    # IDLE 단계: 프레임에서 인형 감지 후 ReID + 색상 템플릿 등록

    def run(self, frame) -> None: ...
    # TRACKING 단계: YOLO 감지 → ReID + 색상 매칭 → 내부 버퍼 갱신

    def get_latest(self) -> Optional[Detection]: ...
    # 최근 프레임의 주인 인형 감지 결과. 미감지·임계값 미달 시 None

    def is_ready(self) -> bool: ...
    # register() 성공 후 True — SM IDLE → TRACKING 전환 조건

    def reset(self) -> None: ...
    # 등록된 템플릿과 감지 버퍼 초기화


class QRScannerInterface(Protocol):
    def start(self, on_scanned: Callable[[str], None], on_timeout: Callable[[], None]) -> None: ...
    # on_scanned(data) — 스캔 성공마다 호출
    # on_timeout()     — 마지막 스캔으로부터 30초 무활동 시 호출

    def stop(self) -> None: ...


class NavBTInterface(Protocol):
    def start(self) -> None: ...   # SM 상태 진입 시 활성화
    def stop(self)  -> None: ...   # SM 상태 이탈 시 비활성화
    def tick(self)  -> BTStatus: ...  # RUNNING | SUCCESS | FAILURE


class BoundaryMonitorInterface(Protocol):
    def start(self) -> None: ...
    def stop(self)  -> None: ...
    def set_active(self, active: bool) -> None: ...
    # TRACKING 계열 상태에서만 경계 체크 활성화


class RobotPublisherInterface(Protocol):
    def publish_cmd_vel(self, linear_x: float, angular_z: float) -> None: ...
    # /cmd_vel 발행 (geometry_msgs/Twist)

    def publish_status(self, mode: str, pos_x: float, pos_y: float,
                       battery: float, is_locked_return: bool) -> None: ...
    # /robot_<id>/status 발행

    def publish_alarm(self, event: str) -> None: ...
    # /robot_<id>/alarm 발행 — event: 'LOCKED' | 'HALTED'

    def publish_cart(self, items: List[CartItem]) -> None: ...
    # /robot_<id>/cart 발행
```

---

## 2. 채널 A — Customer UI ↔ customer_web (SocketIO :8501)

### Browser → Web (SocketIO 이벤트)

| 이벤트 | 페이로드 | 설명 |
|---|---|---|
| `mode` | `{value: "WAITING"\|"RETURNING"}` | 대기 / 보내주기 |
| `resume_tracking` | `{}` | [따라가기] / 도착 팝업 [확인] |
| `return` | `{}` | [쇼핑 종료] → RETURNING 전환 |
| `navigate_to` | `{zone_id: int}` | 상품 안내 요청 |
| `payment` | `{}` | 결제 처리 요청 |
| `delete_item` | `{item_id: int}` | 장바구니 항목 삭제 |
| `qr_scan` | `{data: "QR_TEXT"}` | 시뮬레이션 모드 QR 스캔 |
| `update_quantity` | `{item_id: int, quantity: int}` | 수량 변경 |
| `enter_simulation` | `{}` | 시뮬레이션 모드 진입 |
| `find_product` | `{name: "상품명"}` | 자연어 상품 검색 |

### Web → Browser (SocketIO emit)

| 이벤트 | 페이로드 | 발생 시점 |
|---|---|---|
| `control_connected` | `{connected: bool}` | control_service TCP 연결 상태 변화 |
| `status` | [status 객체](#status-객체) | 1~2Hz heartbeat |
| `cart` | `{type: "cart", items: [장바구니 항목...]}` | QR 스캔 / 수량 변경 후 |
| `registration_done` | `{type: "registration_done", robot_id: "54"}` | IDLE → TRACKING 전환 감지 |
| `payment_done` | `{type: "payment_done"}` | 결제 완료 |
| `find_product_result` | `{zone_id: int, zone_name: "음료"}` 또는 `{error: "..."}` | LLM 검색 결과 (web에서 직접 처리) |

---

## 3. 채널 B — Admin UI ↔ control_service (TCP :8080)

JSON 개행 구분. 연결 후 반드시 등록 메시지 먼저 전송.

### 연결 등록

```json
// 요청
{"type": "register", "role": "admin"}

// 응답
{"type": "registered", "role": "admin"}
```

### Admin → control_service (명령)

| cmd | 추가 필드 | 제약 조건 | 설명 |
|---|---|---|---|
| `admin_goto` | `x, y, theta` | IDLE 상태에서만 | Nav2 직접 목표 전송 |
| `init_pose` | — | CHARGING / IDLE 상태에서만 | AMCL 초기 위치 설정 |
| `start_session` | `user_id` | — | 세션 시작 → Pi에 relay |
| `mode` | `value: "WAITING"\|"RETURNING"` | — | 모드 전환 |
| `resume_tracking` | — | — | 추종 재개 |
| `navigate_to` | `x, y, theta, zone_id` | — | 안내 목표 전송 |
| `force_terminate` | — | — | 강제 세션 종료 |
| `staff_resolved` | — | — | 잠금 해제 / 초기화 |

모든 명령 공통 필드: `{"cmd": "<cmd>", "robot_id": "54", ...}`

### control_service → Admin (push)

| type | 페이로드 | 설명 |
|---|---|---|
| `status` | [status 객체](#status-객체) | 1~2Hz heartbeat |
| `alarm` | `{robot_id, event: "LOCKED"\|"HALTED"}` | 로봇 알람 이벤트 |
| `admin_goto_rejected` | `{robot_id, reason: "..."}` | IDLE 아닌 상태에서 admin_goto 거부 |
| `init_pose_rejected` | `{robot_id, reason: "..."}` | CHARGING/IDLE 아닌 상태에서 init_pose 거부 |

---

## 4. 채널 C — customer_web ↔ control_service (TCP :8080)

JSON 개행 구분. 연결 후 반드시 등록 메시지 먼저 전송.

### 연결 등록

```json
// 요청
{"type": "register", "role": "web", "robot_id": "54"}

// 응답
{"type": "registered", "role": "web", "robot_id": "54"}
```

### customer_web → control_service (명령)

| cmd | 추가 필드 | 설명 |
|---|---|---|
| `start_session` | `user_id` | 세션 시작 → Pi relay |
| `mode` | `value: "WAITING"\|"RETURNING"` | 모드 전환 |
| `resume_tracking` | — | 추종 재개 |
| `return` | — | RETURNING 전환 (mode=RETURNING relay) |
| `navigate_to` | `zone_id` | zone_id로 DB 조회 후 x/y/theta 보완하여 Pi relay |
| `process_payment` | — | DB 결제 처리 + `payment_success` Pi relay |
| `delete_item` | `item_id` | 장바구니 항목 삭제 Pi relay |
| `qr_scan` | `qr_data` | 시뮬레이션 QR 스캔 → DB 항목 추가 + cart push |
| `update_quantity` | `item_id, quantity` | 수량 변경 → DB 업데이트 + cart push |
| `enter_simulation` | — | 시뮬레이션 모드 진입 Pi relay |

모든 명령 공통 필드: `{"cmd": "<cmd>", "robot_id": "54", ...}`

### control_service → customer_web (push)

채널 B admin push와 동일한 `status` 외에 web 전용 push:

| type | 페이로드 | 설명 |
|---|---|---|
| `status` | [status 객체](#status-객체) | 1~2Hz heartbeat |
| `registration_done` | `{robot_id}` | IDLE → TRACKING 전환 감지 |
| `cart` | `{items: [장바구니 항목...]}` | QR 스캔 / 수량 변경 후 갱신 |
| `payment_success` | `{}` | 결제 완료 |
| `alarm` | `{event: "LOCKED"\|"HALTED"}` | 로봇 알람 이벤트 |
| `cart_update` | `{items: [...]}` | Pi `/robot_<id>/cart` 수신 시 갱신 |

---

## 5. 채널 D — customer_web ↔ LLM (REST :8000)

`find_product` SocketIO 이벤트를 customer_web이 직접 처리. TCP 채널 미경유.

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
| GET | `/query` | `?name=콜라` | `{"zone_id": 3, "zone_name": "음료 코너"}` |
| GET | `/query` | `?name=없는상품` | `{"error": "not_found", "name": "없는상품"}` (404) |
| GET | `/query` | (name 미포함) | `{"error": "name 파라미터 필요"}` (400) |

---

## 6. 채널 E — control_service ↔ PostgreSQL (:5432)

PostgreSQL 독립 프로세스. `psycopg2` 커넥션 풀로 접속.

환경 변수: `PG_HOST` / `PG_PORT` / `PG_USER` / `PG_PASSWORD` / `PG_DATABASE`

플레이스홀더: `%s`. dict row는 `RealDictCursor` 사용.

스키마 상세: `docs/erd.md`

---

## 7. 채널 F — control_service ↔ YOLO AI (TCP :5005)

Pi에서 수신한 카메라 UDP 스트림을 YOLO 추론 서버(Docker)로 전달.

| 방향 | 프로토콜 | 포맷 |
|---|---|---|
| control → YOLO | **TCP binary** | `[4byte 길이 (big-endian)][JPEG bytes]` |
| YOLO → control | **TCP** (same conn) | `{"cx": 320.5, "cy": 240.3, "area": 12000.0, "confidence": 0.92, "x1": ..., "y1": ..., "x2": ..., "y2": ...}` 또는 `{}` (미감지) |

> **주의:** 구 문서에는 control → YOLO가 UDP라고 명시되어 있으나, 실제 구현은 TCP binary 프로토콜(`yolo_server.py`).

---

## 8. 채널 G — Pi ↔ control_service (ROS 2 DDS, `ROS_DOMAIN_ID=14`)

### Pi → control_service

| 토픽 | 타입 | 주기 | 페이로드 |
|---|---|---|---|
| `/robot_<id>/status` | `std_msgs/String` | 1 Hz | [status JSON](#ros-status-페이로드) |
| `/robot_<id>/alarm` | `std_msgs/String` | 이벤트 | `{"event": "LOCKED"\|"HALTED"}` |
| `/robot_<id>/cart` | `std_msgs/String` | 변경 시 | `{"items": [{id, name, price, quantity, is_paid}...]}` |

#### ROS status 페이로드

```json
{
  "mode": "IDLE|TRACKING|TRACKING_CHECKOUT|WAITING|GUIDING|RETURNING|CHARGING|HALTED",
  "pos_x": 1.2,
  "pos_y": 0.8,
  "yaw": 0.0,
  "battery": 72.0,
  "is_locked_return": false,
  "follow_disabled": false
}
```

### control_service → Pi (`/robot_<id>/cmd`)

| cmd | 페이로드 | Pi 동작 |
|---|---|---|
| `start_session` | `{cmd, user_id}` | CHARGING → IDLE |
| `mode` | `{cmd, value: "WAITING"\|"RETURNING"}` | SM 전환 |
| `resume_tracking` | `{cmd}` | `sm.resume_tracking()` |
| `navigate_to` | `{cmd, zone_id, x, y, theta}` | SM → GUIDING + Nav2 목표 |
| `payment_success` | `{cmd}` | `sm.enter_tracking_checkout()` + `mark_items_paid()` |
| `delete_item` | `{cmd, item_id}` | 장바구니 항목 삭제 |
| `force_terminate` | `{cmd}` | 세션 종료 → CHARGING |
| `staff_resolved` | `{cmd}` | `is_locked_return=False` + 세션 종료 → CHARGING |
| `admin_goto` | `{cmd, x, y, theta}` | IDLE 상태에서 Nav2 직접 목표 |
| `enter_simulation` | `{cmd}` | `follow_disabled=True` + SM → TRACKING |

### Nav2 Action Client (Pi 내부)

- 액션명: `robot_{ROBOT_ID}/navigate_to_pose`
- 타입: `nav2_msgs/action/NavigateToPose`
- Goal: `PoseStamped` — position(x, y), orientation(z = sin(θ/2), w = cos(θ/2))
- QoS: `/amcl_pose` 구독 — `RELIABLE + TRANSIENT_LOCAL`

---

## 9. 채널 H — Pi ↔ pinky_pro (ROS 2 + UDP :9000)

| 방향 | 프로토콜 | 데이터 |
|---|---|---|
| Pi → control | **UDP :9000** | `[2byte robot_id 길이][robot_id bytes][JPEG bytes]` |
| control → Pi | ROS 2 DDS | `/cmd_vel` (`geometry_msgs/Twist`) |
| Pi → control | ROS 2 DDS | `/robot_<id>/amcl_pose` (`PoseWithCovarianceStamped`), `/odom`, `/scan` |

수신된 UDP 카메라 프레임은 control_service에서 채널 F (YOLO TCP)로 포워딩.

---

## 10. REST API — control_service (:8081)

모든 응답: `Content-Type: application/json`. 에러: `{"error": "message"}`.

### 로봇 상태

| 메서드 | 경로 | 응답 | 설명 |
|---|---|---|---|
| GET | `/robots` | `{robot_id: {mode, pos_x, pos_y, battery, is_locked_return, active_user_id}}` | 전체 로봇 상태 |

### 존 / 경계

| 메서드 | 경로 | 응답 |
|---|---|---|
| GET | `/zones` | `[{zone_id, zone_name, zone_type, x, y, theta}, ...]` (전체 존 목록) |
| GET | `/zone/parking/available` | `{zone_id, zone_name, zone_type, x, y, theta}` (빈 슬롯 1개) |
| GET | `/boundary` | 경계 설정 배열 |

### 세션

| 메서드 | 경로 | 요청 / 응답 |
|---|---|---|
| POST | `/session` | 요청: `{robot_id, user_id, password}` / 응답: `{session_id, cart_id}` (201) |
| GET | `/session/robot/<robot_id>` | 응답: `{session_id, cart_id}` |
| GET | `/session/<id>` | 응답: 세션 객체 |
| PATCH | `/session/<id>` | 요청: `{is_active: 0}` / 응답: `{ok: true}` |

### 장바구니

| 메서드 | 경로 | 요청 / 응답 |
|---|---|---|
| GET | `/cart/<cart_id>` | 응답: 장바구니 항목 배열 |
| POST | `/cart/<cart_id>/item` | 요청: `{product_name, price}` / 응답: `{item_id}` (201) |
| DELETE | `/item/<item_id>` | 응답: `{ok: true}` |
| PATCH | `/cart/<cart_id>/items/mark_paid` | 응답: `{ok: true}` |
| GET | `/cart/<cart_id>/has_unpaid` | 응답: `{has_unpaid: bool}` |

### 기타

| 메서드 | 경로 | 응답 |
|---|---|---|
| GET | `/events?limit=<n>` | 이벤트 로그 배열 (기본 limit=100) |
| GET | `/camera/<robot_id>` | MJPEG 스트림 (`multipart/x-mixed-replace`). 오프라인 시 503 |
| GET | `/health` | `{ok: true}` |

> **`/zone/parking/available`:** 메모리 캐시 기반 — ROBOT 상태에서 슬롯 140/141 waypoint 반경 0.15m 이내 로봇 유무 확인. 두 슬롯 모두 점유 시 슬롯 140 반환.

---

## 공유 객체 포맷

### status 객체

```json
{
  "type": "status",
  "robot_id": "54",
  "mode": "TRACKING",
  "pos_x": 1.2,
  "pos_y": 0.8,
  "yaw": 0.0,
  "battery": 72.0,
  "is_locked_return": false,
  "follow_disabled": false,
  "bbox": {
    "cx": 320.5,
    "cy": 240.3,
    "area": 12000.0,
    "confidence": 0.92,
    "x1": 200.0, "y1": 100.0, "x2": 440.0, "y2": 380.0
  }
}
```

- `bbox`: TRACKING / TRACKING_CHECKOUT 중 YOLO 감지 시 포함, 미감지 시 `null`

### 장바구니 항목

```json
{"id": 1, "name": "콜라", "price": 1500, "quantity": 2, "is_paid": false}
```

> **주의:** 브라우저 전달 포맷은 `id` / `name` (DB 컬럼명 `item_id` / `product_name`과 다름)


# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**쑈삥끼 (ShopPinkki)** — Pinky Pro 로봇을 활용한 미니어처 마트 스마트 카트 데모 프로젝트.
- Robot platform: Pinky Pro (110×120×142mm), Raspberry Pi 5 (8GB)
- Demo environment: 1.4×1.8m miniature shopping mall
- ROS 2 Jazzy / Ubuntu 24.04
- Two robots: Pinky #54 (`192.168.102.54`), Pinky #18 (`192.168.102.18`)

## Build

```bash
# Full build
cd ~/ros_ws
colcon build

# Build specific packages
colcon build --packages-select <pkg_name>

# Source workspace after build
source install/setup.zsh
```

**Architecture restriction:** `pinky_lamp_control` and `pinky_led` only build on ARM64 (aarch64/Raspberry Pi). They will be skipped automatically on x86 PC.

### Python Dependencies (pip)

```bash
pip install transitions          # SM 라이브러리 (shoppinkki_core)
pip install PyQt6                # 관제 앱 (admin_app, PC 전용)
pip install flask flask-socketio # customer_web
```

**macOS + conda 환경 주의:** `ros2 run admin_app admin_app` 실행 시 Qt cocoa 플러그인을 못 찾는 문제가 발생할 수 있음.
`admin_app/main.py`의 `_ensure_qt_platform_plugin()`이 자동으로 경로를 잡아줌 — 별도 설정 불필요.

## Testing & Linting

```bash
# Run tests for a package
colcon test --packages-select <pkg_name>
colcon test-result --verbose

# Python linting (flake8, pep257) is run via ament_lint_auto
```

Python packages use pytest. Test files are in `test/` subdirectories of each package.

## Running the Robot

### Map Building (Real Robot)
```bash
# [On Pinky]
ros2 launch pinky_bringup bringup_robot.launch.xml
ros2 launch pinky_navigation map_building.launch.xml

# [On PC]
ros2 launch pinky_navigation map_view.launch.xml
ros2 run teleop_twist_keyboard teleop_twist_keyboard  # manual driving
ros2 run nav2_map_server map_saver_cli -f "<map_name>"
```

### Navigation (Real Robot)
```bash
# [On Pinky]
ros2 launch pinky_bringup bringup_robot.launch.xml
ros2 launch shoppinkki_nav navigation.launch.py

# [On PC]
ros2 launch pinky_navigation nav2_view.launch.xml
# Use RViz: "2D Pose Estimate" to localize, then "Nav2 Goal" to navigate
```

### ShopPinkki 전체 스택 실행
```bash
# [On Pinky]
ros2 launch pinky_bringup bringup_robot.launch.xml
ros2 launch shoppinkki_nav navigation.launch.py
ros2 run shoppinkki_core main_node

# [On PC — 관제 앱 (control_service 포함)]
ros2 run admin_app admin_app

# [On PC — 고객 웹앱]
python services/customer_web/app.py   # → http://localhost:8501

# [On PC — AI 서버]
cd services/ai_server && docker compose up
```

### DB 관리
```bash
# 중앙 서버 DB 시딩 (대화형: reset / replace / 기본 선택)
~/ros_ws/scripts/seed.sh

# Pi 5 로컬 DB 초기화
python -c "from shoppinkki_core.db import init_db; init_db()"
```

### Simulation (Gazebo)
```bash
# Map building in sim
ros2 launch pinky_gz_sim launch_sim_shop.launch.xml
ros2 launch pinky_navigation gz_map_building.launch.xml
ros2 run teleop_twist_keyboard teleop_twist_keyboard

# Navigation in sim
ros2 launch pinky_gz_sim launch_sim_shop.launch.xml
ros2 launch pinky_navigation gz_bringup_launch.xml map:=src/pinky_pro/pinky_navigation/map/shop.yaml
ros2 launch pinky_navigation gz_nav2_view.launch.xml
```

### Get map coordinates
```bash
ros2 topic echo /clicked_point   # then use RViz "Publish Point"
ros2 topic echo /amcl_pose       # current robot pose
```

## Architecture

### Two-Layer Structure

```
ros_ws/
├── src/
│   ├── pinky_pro/          ← 하드웨어 플랫폼 패키지 (git submodule, 수정 금지)
│   ├── shoppinkki/         ← Pi 5 실행 ROS2 패키지
│   │   ├── shoppinkki_interfaces/   ← ABC 인터페이스 + Mock 구현체
│   │   ├── shoppinkki_core/         ← 메인 노드 (SM + BT + HW + Pi DB)
│   │   ├── shoppinkki_nav/          ← Nav2 BT + BoundaryMonitor + shop 맵
│   │   └── shoppinkki_perception/   ← YOLO/ArUco/QR/Pose
│   └── control_center/     ← 서버 PC 실행 ROS2 패키지
│       ├── control_service/         ← ROS2 노드 + TCP + REST + 중앙 DB
│       └── admin_app/               ← PyQt6 관제 대시보드
├── services/
│   ├── customer_web/        ← Flask + SocketIO 고객 웹앱 (포트 8501)
│   └── ai_server/           ← Docker: YOLO(TCP:5005) + LLM(REST:8000)
└── scripts/
    └── seed.sh              ← 중앙 DB 시딩 대화형 스크립트
```

```
src/pinky_pro/      ← Hardware platform packages (git submodule)
src/shoppinkki/     ← ShopPinkki application packages
src/control_center/ ← Server-side packages
```

**`src/pinky_pro/`** provides foundational drivers:
- `pinky_bringup` — Dynamixel XL330 motor init, odometry publisher, TF broadcaster. Serial: `/dev/ttyAMA4` @ 1Mbps
- `pinky_description` — URDF/XACRO robot model (wheel radius: 28mm, wheelbase: 96.1mm)
- `pinky_navigation` — Nav2 + slam_toolbox stack. Pre-built shop map: `pinky_navigation/map/shop.yaml`
- `pinky_gz_sim` — Gazebo simulation with miniature shop world
- `pinky_interfaces` — Custom ROS2 service definitions (Emotion, SetLed, SetLamp, SetBrightness)
- `pinky_emotion` — LCD ST7789 GIF emotion display (8 emotions: hello, basic, angry, bored, fun, happy, interest, sad)
- `pinky_lamp_control` — Top lamp control (ARM64 only, uses libws2811)
- `pinky_led` — WS2812B LED strip control (ARM64 only)
- `pinky_imu_bno055` — BNO055 9-axis IMU driver (I2C)

**`src/shoppinkki/`** provides application logic (Pi 5 실행):
- `shoppinkki_interfaces` — Python Protocol 인터페이스 + Mock 구현체 (`protocols.py`, `mocks.py`)
- `shoppinkki_core` — 메인 노드. SM(9개 상태) + BT Runner + HW 제어(LED, LCD, 부저) + Pi SQLite DB
- `shoppinkki_nav` — Nav2 기반 BT (BTWaiting, BTGuiding, BTReturning) + BoundaryMonitor. shop 맵 포함
- `shoppinkki_perception` — YOLO+ReID / ArUco 추종 / QR 스캔 / 포즈 스캔

**`src/control_center/`** provides server-side logic (서버 PC 실행):
- `control_service` — ROS2 노드 + TCP 서버(8080) + REST API(8080) + 중앙 SQLite DB. Pi ↔ customer_web 중계. `QueueManager` 포함
- `admin_app` — PyQt6 + rclpy 관제 대시보드. control_service와 **동일 프로세스**(직접 참조, 채널 D). `AdminAppBridge(QObject)`가 ROS 스레드 → Qt 메인 스레드 신호 중계

**`services/`** provides non-ROS services:
- `customer_web` — Flask + SocketIO 고객 웹앱 (**포트 8501**). 스마트폰 브라우저용
- `ai_server` — Docker Compose. YOLO 추론 서버(TCP:5005) + LLM 자연어 검색(REST:8000)

### Application Architecture

- **Two demo modes**: `TRACKING_MODE = "PERSON"` (YOLO+ReID, 책상 위) / `"ARUCO"` (ArUco 마커, 마트 바닥)
- **State Machine (SM)**: 9 states — IDLE, REGISTERING, TRACKING, SEARCHING, WAITING, ITEM_ADDING, GUIDING, RETURNING, ALARM
- **Behavior Trees**: BT1=TRACKING(P-Control), BT2=SEARCHING(회전 탐색), BT3=WAITING(통행 회피), BT4=GUIDING(Nav2), BT5=RETURNING(Nav2 + `/queue/assign` 대기열 배정)
- **Communication**: Pi ↔ control_service via ROS DDS (`ROS_DOMAIN_ID=14`). customer_web ↔ control_service via TCP(8080). 브라우저 ↔ customer_web via WebSocket. admin_app ↔ control_service 직접 참조(채널 D)

### Key SM Transitions (주요 상태 전환)

| Trigger | From → To | 발생 조건 |
|---|---|---|
| `start_session` | IDLE → REGISTERING | 로그인 완료, Pi가 `/cmd` 수신 |
| `registration_done` | REGISTERING → TRACKING | 포즈 스캔(4방향) 또는 ArUco 마커 등록 완료 |
| `owner_lost` | TRACKING → SEARCHING | N프레임 연속 미감지 (BT1) |
| `to_waiting` | TRACKING/SEARCHING → WAITING | 앱 명령 / 탐색 타임아웃 / 결제 구역 진입 |
| `battery_low` | ANY → ALARM | 배터리 ≤ 20% (`_battery_alarm_fired` 플래그로 중복 방지) |
| `zone_out` | ANY → ALARM | shop_boundary 이탈 (THEFT) |
| `payment_error` | WAITING → ALARM | 가상 결제 실패 |
| `dismiss_to_idle` | ALARM → IDLE | THEFT 알람 해제 (세션 강제 종료) |
| `dismiss_to_waiting` | ALARM → WAITING | BATTERY_LOW/TIMEOUT/PAYMENT_ERROR 해제 (세션 유지) |
| `session_ended` | RETURNING → IDLE | Nav2 카트 출구(zone 140) 도착 + 세션 종료 |
| `admin_force_idle` | **ANY** → IDLE | 관제 강제 종료. `machine.add_transition('admin_force_idle', source='*', dest='IDLE')` |

### Key Topics (Pi ↔ control_service, ROS DDS)

| Topic | Type | Purpose |
|---|---|---|
| `/cmd_vel` | `geometry_msgs/Twist` | Motor velocity commands |
| `/odom` | `nav_msgs/Odometry` | Wheel encoder odometry |
| `/scan` | `sensor_msgs/LaserScan` | RPLiDAR C1 scans |
| `/amcl_pose` | `geometry_msgs/PoseWithCovarianceStamped` | AMCL localization |
| `/robot_<id>/status` | `std_msgs/String` | Pi→control: `{"mode":..., "pos_x":..., "pos_y":..., "battery":...}` (1~2Hz) |
| `/robot_<id>/alarm` | `std_msgs/String` | Pi→control: `{"event": "THEFT"\|"BATTERY_LOW"\|"TIMEOUT"\|"PAYMENT_ERROR", "user_id": "..."}` |
| `/robot_<id>/cart` | `std_msgs/String` | Pi→control: `{"items": [...]}` |
| `/robot_<id>/cmd` | `std_msgs/String` | control→Pi: 아래 cmd 목록 참고 |

**`/robot_<id>/cmd` 페이로드 목록:**

| cmd | 페이로드 | 동작 |
|---|---|---|
| `start_session` | `{"cmd": "start_session", "user_id": "..."}` | SM: IDLE → REGISTERING |
| `mode` | `{"cmd": "mode", "value": "WAITING"\|"TRACKING"\|"RETURNING"\|"ITEM_ADDING"}` | SM 전환 |
| `navigate_to` | `{"cmd": "navigate_to", "zone_id": 6}` | SM → GUIDING (zone_id 기반) |
| `dismiss_alarm` | `{"cmd": "dismiss_alarm"}` | ALARM → IDLE(THEFT) 또는 WAITING(기타) |
| `payment_error` | `{"cmd": "payment_error"}` | WAITING → ALARM |
| `delete_item` | `{"cmd": "delete_item", "item_id": 3}` | 장바구니 항목 삭제 |
| `force_terminate` | `{"cmd": "force_terminate"}` | ANY → IDLE (관제 강제 종료, `admin_force_idle` 트리거) |
| `admin_goto` | `{"cmd": "admin_goto", "x": 1.2, "y": 0.8, "theta": 0.0}` | IDLE 상태에서 Nav2 직접 목표 전송 (SM 전환 없음) |

### Key Services (pinky_interfaces)
- `/set_emotion` — LCD emotion (hello, happy, angry, etc.)
- `/set_led` — WS2812B LED colors
- `/set_lamp` — Top lamp color/mode/duration
- `/set_brightness` — LCD brightness

### Communication Channels Summary

| 채널 | 연결 | 프로토콜 |
|---|---|---|
| A | Customer UI ↔ customer_web | WebSocket (SocketIO) |
| B | customer_web ↔ control_service | TCP (localhost:8080, JSON 개행 구분) |
| C | Pi 5 ↔ control_service | ROS DDS (`ROS_DOMAIN_ID=14`) |
| D | admin_app ↔ control_service | 직접 참조 (동일 프로세스, PyQt Signal/Slot 필수) |
| E | Pi 5 → control_service | REST HTTP (포트 8080) |

**채널 D 주요 메서드 (admin_app ↔ control_service):**
- `control → admin`: `on_robot_status_update(robot_id, status)`, `on_alarm(robot_id, event_type, occurred_at)`, `on_alarm_dismissed(robot_id)`, `on_robot_offline(robot_id)`, `on_robot_online(robot_id)`, `on_event(event_dict)`
- `admin → control`: `dismiss_alarm(robot_id)`, `force_terminate(robot_id)`, `admin_goto(robot_id, x, y, theta)`
- **⚠️ 중요:** 위 콜백은 ROS 스레드에서 호출됨 → PyQt UI 갱신은 반드시 `pyqtSignal.emit()` 경유

**채널 E REST 엔드포인트 (Pi → control_service):**

| 경로 | 설명 |
|---|---|
| `GET /zone/<zone_id>/waypoint` | Nav2 목표 좌표 조회 |
| `GET /boundary` | BOUNDARY_CONFIG 전체 조회 |
| `GET /find_product?query=<str>` | 상품명 검색 |
| `GET /queue/assign?robot_id=<id>` | BTReturning 대기열 position 배정 → zone_id 반환 |
| `GET /events?robot_id=<id>&limit=<n>` | EVENT_LOG 조회 |

## DB Schema Summary

### 중앙 서버 DB (`control_service/data/control.db`)

| 테이블 | 주요 컬럼 | 용도 |
|---|---|---|
| `USER` | user_id, password_hash | 사용자 계정 |
| `CARD` | card_id, user_id | 결제 카드 정보 |
| `ZONE` | zone_id, zone_name, zone_type, waypoint_x/y/theta | 구역 Waypoint. zone_type: `product`(1~8) / `special`(100~) |
| `PRODUCT` | product_id, product_name, price, zone_id | 상품명 → 구역 매핑 |
| `BOUNDARY_CONFIG` | description, x_min/max, y_min/max | 도난 경계 + 결제 구역 좌표 |
| `ROBOT` | robot_id, ip_address, current_mode, pos_x/y, battery_level, last_seen, active_user_id | 로봇 실시간 상태 |
| `ALARM_LOG` | robot_id, user_id, event_type, occurred_at, resolved_at | 알람 이벤트 (resolved_at=NULL이면 미처리) |
| `EVENT_LOG` | robot_id, user_id, event_type, event_detail, occurred_at | 전체 운용 이벤트 타임라인 (scenario_17) |

**ROBOT.current_mode 값:** `IDLE` / `REGISTERING` / `TRACKING` / `SEARCHING` / `WAITING` / `ITEM_ADDING` / `GUIDING` / `RETURNING` / `ALARM` / `OFFLINE`

**ALARM_LOG.event_type 값:** `THEFT` / `BATTERY_LOW` / `TIMEOUT` / `PAYMENT_ERROR`

**EVENT_LOG.event_type 값:** `SESSION_START` / `SESSION_END` / `FORCE_TERMINATE` / `ALARM_RAISED` / `ALARM_DISMISSED` / `PAYMENT_SUCCESS` / `PAYMENT_FAIL` / `MODE_CHANGE` / `OFFLINE` / `ONLINE` / `QUEUE_ADVANCE`

### Pi 5 로컬 DB (`shoppinkki_core/data/pi.db`)

| 테이블 | 용도 |
|---|---|
| `SESSION` | session_id, robot_id, user_id, is_active, expires_at. 유효 조건: `is_active=1 AND expires_at > now()` |
| `POSE_DATA` | session_id, direction, hsv_top_json, hsv_bottom_json. 세션 종료 시 삭제 |
| `CART` | 세션당 1개. SESSION과 1:1 |
| `CART_ITEM` | item_id, cart_id, product_name, price(데모용 QR값), added_at |

### 특수 구역 (ZONE 테이블 주요 ID)

| zone_id | 구역명 | 용도 |
|---|---|---|
| 130 | 카트 입구 | special | 로봇 대기 구역 시작점 |
| 140 | 카트 출구 (대기열 1번) | special | RETURNING 목적지. 사용자 QR 스캔 위치 |
| 141 | 카트 출구 (대기열 2번) | special | 2번째 로봇 대기 위치 (scenario_18) |
| 150 | 결제 구역 | special | BoundaryMonitor 결제 트리거 구역 |

## Key Parameters (`config.py`)

| 파라미터 | 값 | 설명 |
|---|---|---|
| `TRACKING_MODE` | `"PERSON"` / `"ARUCO"` | 데모 모드 선택 |
| `KP_DIST_PERSON` | `0.0001` | PERSON 모드 P-Control 거리 게인 (px² 단위) |
| `KP_DIST_ARUCO` | `0.5` | ARUCO 모드 P-Control 거리 게인 (m 단위) |
| `TARGET_DIST_M` | `0.8` | 목표 추종 거리 (m) |
| `IMAGE_WIDTH` | `640` | 카메라 해상도 (px) |
| `BATTERY_THRESHOLD` | `20` | 배터리 알람 임계값 (%). 테스트 시 90으로 임시 상향 |
| `ROBOT_TIMEOUT_SEC` | `30` | offline 판정 기준 (마지막 status 수신 후 초) |
| `ALARM_DISMISS_PIN` | `"1234"` | 현장 알람 해제 4자리 PIN (데모용) |
| `SEARCH_TIMEOUT` | `30.0` | SEARCHING 상태 타임아웃 (초) |
| `WAITING_TIMEOUT` | `300` | WAITING 상태 타임아웃 (초) |
| `LINEAR_X_MAX` | `0.3` | 최대 선속도 (m/s) |
| `ANGULAR_Z_MAX` | `1.0` | 최대 각속도 (rad/s) |

## control_service 주요 구현 사항

- **cleanup 스레드** (10s 주기): `last_seen < now - 30s` → `current_mode='OFFLINE'`, `active_user_id=NULL`
- **QueueManager**: BTReturning이 `/queue/assign` 호출 시 zone 140 또는 141 배정. 1번 로봇 REGISTERING 감지 시 2번 로봇에 `admin_goto` 전송
- **DB Lock**: `threading.Lock()` (`_lock`) — ROS 스레드 + cleanup 스레드 + Flask 스레드 동시 접근 보호
- **SQLite UPDATE 주의**: `UPDATE ... ORDER BY ... LIMIT 1` — SQLite 미지원. 서브쿼리로 `log_id` 먼저 조회 필요
- **admin_app 연동**: `ControlServiceNode(app_bridge=AdminAppBridge)` 로 주입. `app_bridge=None` 이면 standalone 동작

## Scenario Implementation Order (우선순위)

> 복잡도 낮음 / 의존도 낮음 / 시뮬레이션 가능 순서로 구현

| 순위 | 시나리오 | 핵심 구현 |
|---|---|---|
| 1 | scenario_13: 관제 모니터링 | control_service status 수신 → admin_app PyQt Signal |
| 2 | scenario_16: Offline 감지 | cleanup 스레드 + `_offline_robots` 집합 |
| 3 | scenario_17: 이벤트 로깅 | `log_event()` 헬퍼 + EVENT_LOG 테이블 |
| 4 | scenario_12: 중복 사용 차단 | `session_check` → blocked.html |
| 5 | scenario_01: 세션 시작 | login → `start_session` cmd 발행 |
| 6 | scenario_14: 관제 알람 | ALARM_LOG INSERT + admin_app 패널 |
| 7 | scenario_06: 물건 추가 | QR 스캔 → CART_ITEM INSERT |
| 8 | scenario_11: 배터리 알람 | `_battery_alarm_fired` 플래그 + BATTERY_THRESHOLD mock |
| 9 | scenario_15: 강제 종료/위치 호출 | `admin_force_idle` + Nav2 직접 goal |
| 10 | scenario_02: 주인 등록 | ArUco/포즈 스캔 |
| 11~17 | scenario_04,09,10,05,03,07,08 | Nav2/인식 필요 (Gazebo 검증 가능) |
| 18 | scenario_18: 대기열 | QueueManager + BTReturning `/queue/assign` |

## Key Documentation

| File | Content |
|---|---|
| `docs/user_requirements.md` | 사용자 요구사항 (UR) 테이블 |
| `docs/system_requirements.md` | 시스템 요구사항 (SR) 테이블. UR→SR 매핑 |
| `docs/system_architecture.md` | 전체 구성도, 컴포넌트 목록, 통신 채널 개요 |
| `docs/interface_specification.md` | Python 인터페이스 명세 + 채널별 메시지 포맷 (채널 A~E) |
| `docs/state_machine.md` | SM 9개 상태 정의, 전환 테이블 (`admin_force_idle` 와일드카드 포함) |
| `docs/behavior_tree.md` | 5개 BT flowchart + SM↔BT 역할 분담 |
| `docs/erd.md` | DB 스키마 (중앙 서버 DB + Pi5 로컬 DB). EVENT_LOG 포함 |
| `docs/map.md` | 미니어처 마트 맵 레이아웃, 구역 ID (140/141 대기열 포함) |
| `docs/scaffold_plan.md` | 패키지 뼈대 구현 계획 + 체크리스트 |
| `docs/scenarios/index.md` | 시나리오 목록 (우선순위 순, 총 18개) |
| `docs/scenarios/scenario_NN.md` | 시나리오별 테스트 플랜 (예제코드 + 모순점 + UI 검토 포함) |
| `cheatsheet.md` | SLAM and navigation command reference |

> **Note:** 스캐폴딩 완료. 각 패키지의 클래스/함수 스텁이 Mock으로 와이어링되어 있으며, 시나리오 구현 순서(`docs/scaffold_plan.md`)에 따라 실제 로직을 채워 나간다.

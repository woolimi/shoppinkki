# Admin UI 명세

> **기술 스택:** PyQt5 데스크톱 앱. 별도 프로세스 또는 별도 기기에서 실행.
> **통신:** 채널 B (TCP, admin_ui ↔ control_service:8080)
> **실행:** `ros2 run admin_ui admin_ui` 또는 `python3 ui/admin_ui/admin_ui/main.py`

---

## 구현 기능 목록

| # | 기능 | 연관 UR | 트리거 |
|---|---|---|---|
| 1 | 실시간 로봇 모니터링 (카드 + 맵) | UR-50 | control_service TCP push (1~2Hz) |
| 2 | 로봇 상태 변경 (모드 전환) | UR-50 | 관제자 상태 버튼 클릭 |
| 3 | LOCKED / HALTED 스태프 처리 | UR-53 | 관제자 [잠금 해제] / [초기화] 클릭 |
| 4 | 세션 강제 종료 | UR-52 | 관제자 [강제 종료] 클릭 |
| 5 | 위치 호출 (admin_goto) | UR-50 | 맵 클릭 → [이동 명령] |
| 6 | 오프라인 감지 / 재연결 표시 | UR-50 | cleanup 스레드 → TCP push |
| 7 | 이벤트 로그 패널 | UR-51 | 모든 운용 이벤트 TCP push |
| 8 | 스태프 호출 패널 (LOCKED / HALTED) | UR-51, UR-53 | LOCKED·HALTED 이벤트 TCP push |
| 9 | 카메라 디버그 패널 (추종 바운딩박스) | UR-10 | 관제자 패널 토글 |

---

## 화면 구성

전체 레이아웃은 단일 메인 윈도우(`QMainWindow`)로 구성된다.

```
┌──────────────────────────────────────────────────────────────────┐
│  ShopPinkki 관제 대시보드                            [연결 상태]  │
├──────────────────┬───────────────────────────────────────────────┤
│                  │  로봇 카드 패널                               │
│   맵 오버레이       │  ┌──────────────┐  ┌──────────────┐          │
│   (MapWidget)    │  │  Robot #54   │  │  Robot #18   │          │
│                  │  │  [카드 내용] │  │  [카드 내용] │          │
│                  │  └──────────────┘  └──────────────┘          │
│                  ├───────────────────────────────────────────────┤
│                  │  카메라 디버그 패널 [Robot #54 ▾] [■ 닫기]   │
│                  │  ┌─────────────────────────────────────────┐  │
│                  │  │  [카메라 영상 + 추종 바운딩박스 오버레이] │  │
│                  │  └─────────────────────────────────────────┘  │
├──────────────────┴───────────────────────────────────────────────┤
│  스태프 호출 패널         │  이벤트 로그 패널                     │
│  [LOCKED / HALTED 목록]  │  [전체] [스태프호출] [세션] [이벤트]  │
│                           │  [이벤트 로그 목록]                   │
└───────────────────────────┴──────────────────────────────────────┘
```

---

### 1. 맵 오버레이 (`MapWidget`)

**역할:** `shop_map.png` 위에 로봇 위치 실시간 표시. 맵 클릭으로 위치 호출 좌표 선택.

**UI 요소:**
- 맵 이미지 (QLabel + QPixmap)
- 로봇 아이콘 (robot_id별 색상 구분, yaw 방향 표시)
  - 온라인: 색상 원형 아이콘
  - `is_locked_return=True`: 빨간 점멸 테두리 추가
  - HALTED: 흰색 점멸 테두리 추가
  - 오프라인: × 표시, 마지막 위치 유지
- 맵 클릭 시 목표 마커 (파란 십자+원) 표시 → 이동 명령 전송 후 제거

**좌표 변환:**
```python
# 월드 좌표 → 픽셀
px = int((x - origin_x) / resolution)
py = int(img_height - (y - origin_y) / resolution)  # y축 반전

# 픽셀 → 월드 좌표 (맵 클릭)
x = px * resolution + origin_x
y = (img_height - py) * resolution + origin_y
```

---

### 2. 로봇 카드 패널

**역할:** 각 로봇(#54, #18)의 현재 상태를 1~2Hz로 갱신하고, 관제자가 상태를 직접 변경할 수 있다.

**카드 구성 (로봇 1개당):**

```
┌──────────────────────────────────┐
│  Robot #54          [TRACKING]   │  ← 모드 뱃지 (색상 구분)
│  👤 hong123                      │  ← 활성 사용자 ID (없으면 "-")
│  🔋 [████████░░] 72%             │  ← 배터리 바 (20% 이하 → 빨강)
│  📍 (1.20, 0.80)                 │  ← 좌표
│  ─────────────────────────────── │
│  상태 전환                        │
│  [대기]  [추종]  [복귀]           │  ← 현재 상태에 따라 활성/비활성
│  ─────────────────────────────── │
│  관제 명령                        │
│  [강제 종료]  [이동 명령]         │
│  [잠금 해제]                      │  ← LOCKED/HALTED 상태일 때만 활성
└──────────────────────────────────┘
```

**모드 뱃지 색상:**

| 모드 | 색상 |
|---|---|
| `CHARGING` | 회색 |
| `IDLE` | 파랑 |
| `TRACKING` | 초록 |
| `TRACKING_CHECKOUT` | 청록 |
| `GUIDING` | 노랑 |
| `SEARCHING` | 주황 |
| `WAITING` | 하늘 |
| `LOCKED` | 빨강 |
| `RETURNING` | 보라 |
| `HALTED` | 흰색 (카드 전체 빨간 테두리) |
| `OFFLINE` | 회색 (카드 전체 회색 처리) |

**상태 전환 버튼 — 현재 모드별 활성화 규칙:**

| 버튼 | 전송 명령 | 활성 조건 |
|---|---|---|
| [대기] | `{"cmd": "mode", "value": "WAITING"}` | TRACKING, TRACKING_CHECKOUT, SEARCHING |
| [추종] | `{"cmd": "resume_tracking"}` | WAITING, SEARCHING |
| [복귀] | `{"cmd": "mode", "value": "RETURNING"}` | TRACKING, TRACKING_CHECKOUT, WAITING, SEARCHING |

> [추종] 명령은 control_service가 `/robot_<id>/cmd`로 relay한다. Pi SM은 `previous_tracking_state` 기반으로 TRACKING 또는 TRACKING_CHECKOUT으로 복귀한다.

**관제 명령 버튼:**
- **[강제 종료]** — 확인 다이얼로그 후 `{"cmd": "force_terminate", "robot_id": N}` 전송. CHARGING·OFFLINE·HALTED·LOCKED 상태에서는 비활성화. (HALTED·LOCKED는 `staff_resolved` 절차로 처리; CHARGING·OFFLINE은 활성 세션 없음)
- **[이동 명령]** — 맵에서 위치 클릭 후 활성화 → `{"cmd": "admin_goto", "robot_id": N, "x": x, "y": y, "theta": 0.0}` 전송. IDLE 상태에서만 활성화.
  - 거부 응답(`admin_goto_rejected`) 수신 시 오류 토스트 표시.
- **[잠금 해제]** — `{"cmd": "staff_resolved", "robot_id": N}` 전송. `is_locked_return=True` 또는 HALTED 상태에서만 활성화. 확인 다이얼로그 후 전송.

---

### 3. 스태프 호출 패널

**역할:** LOCKED / HALTED 이벤트 수신 시 직원 즉시 확인 및 처리. 기존 알람 패널 대체.

**패널 구성:**

```
┌──────────────────────────────────────┐
│  🔔 스태프 호출                       │
│  ┌───────────────────────────────┐   │
│  │ Robot#54  LOCKED   12:34:05   │   │  ← 빨강 (충전소 귀환 중/도착)
│  │ 미결제 물건 있음  [잠금 해제] │   │
│  ├───────────────────────────────┤   │
│  │ Robot#18  HALTED   12:30:00   │   │  ← 흰색/주황
│  │ 배터리 부족, 현장 처리 필요   │   │
│  │ [초기화]                      │   │
│  ├───────────────────────────────┤   │
│  │ Robot#54  LOCKED ✓ 처리됨    │   │  ← 회색 (처리 완료)
│  └───────────────────────────────┘   │
└──────────────────────────────────────┘
```

**이벤트별 색상 및 처리:**

| event_type | 색상 | 버튼 | 처리 후 상태 |
|---|---|---|---|
| `LOCKED` | 빨강 | [잠금 해제] → `staff_resolved` | CHARGING (세션 종료) |
| `HALTED` | 주황 | [초기화] → `staff_resolved` | CHARGING |

**동작:**
- TCP `{"type": "staff_call", "event": "LOCKED"/"HALTED", ...}` 수신 → 항목 추가 + 해당 로봇 카드 테두리 강조
- [잠금 해제] / [초기화] 클릭 → `{"cmd": "staff_resolved", "robot_id": N}` 전송
- TCP `{"type": "staff_resolved", ...}` 수신 → 항목 "✓ 처리됨" 회색 처리 + 카드 테두리 복구
- 다중 호출: 독립 항목으로 각각 표시/처리 가능

---

### 4. 이벤트 로그 패널

**역할:** 운용 중 발생한 모든 이벤트 실시간 표시. 최신 이벤트가 상단.

**패널 구성:**

```
┌──────────────────────────────────────────────────────┐
│  이벤트 로그   [전체] [스태프호출] [세션] [이벤트]   │
├──────────────────────────────────────────────────────┤
│ [12:35:01] Robot#54  SESSION_START   | hong123       │  ← 초록
│ [12:34:05] Robot#54  LOCKED         | 미결제 물건    │  ← 빨강
│ [12:33:00] Robot#18  HALTED         | 배터리 부족    │  ← 주황
│ [12:20:00] Robot#54  OFFLINE                         │  ← 회색
│ ...                                                  │
└──────────────────────────────────────────────────────┘
```

**이벤트 색상:**

| event_type | 배경색 |
|---|---|
| `SESSION_START` | `#d4edda` (초록) |
| `SESSION_END` | `#cce5ff` (파랑) |
| `FORCE_TERMINATE` | `#fff3cd` (노랑) |
| `LOCKED` | `#f8d7da` (빨강) |
| `HALTED` | `#ffe5d0` (주황) |
| `STAFF_RESOLVED` | `#e2e3e5` (회색) |
| `PAYMENT_SUCCESS` | `#d4edda` (초록) |
| `OFFLINE` | `#888888` (회색) |
| `ONLINE` | `#d4edda` (초록) |

**동작:**
- TCP `{"type": "event", ...}` 수신 → 최상단에 행 추가
- 필터 버튼: [전체] / [스태프호출] (LOCKED·HALTED·STAFF_RESOLVED) / [세션] (SESSION_*·FORCE_TERMINATE) / [이벤트] (나머지)
- 최대 200건 유지. 행 클릭 시 해당 robot_id 카드 하이라이트.

---

### 5. 카메라 디버그 패널

**역할:** 선택한 로봇의 카메라 영상을 실시간으로 표시하고, AI Server에서 수신한 주인 인형 바운딩박스를 오버레이하여 추종 동작을 시각적으로 확인한다.

**패널 구성:**

```
┌────────────────────────────────────────────────────┐
│  📷 카메라 디버그     [Robot #54 ▾]  [■ 패널 닫기]  │
├────────────────────────────────────────────────────┤
│                                                    │
│   ┌──────────────────────────────────────────┐    │
│   │                                          │    │
│   │   [MJPEG 스트림 영상]                     │    │
│   │         ┌─────────┐                      │    │
│   │         │  인형   │  ← 바운딩박스 오버레이  │    │
│   │         └─────────┘  (초록선 + 신뢰도 %)  │    │
│   │                                          │    │
│   └──────────────────────────────────────────┘    │
│   해상도: 640×480  |  bbox: (220, 150, 400, 380)  │
└────────────────────────────────────────────────────┘
```

**UI 요소:**
- **로봇 선택 드롭다운** — 모니터링할 로봇 선택 (Robot #54 / #18)
- **영상 표시 영역** — `QLabel` + `QPixmap`. MJPEG 스트림을 30fps 목표로 표시
- **바운딩박스 오버레이** — control_service에서 수신한 최신 bbox를 영상 위에 직접 그림
  - 주인 인형 bbox: 초록색 사각형 + 상단에 신뢰도(%) 표시
  - ReID 실패 또는 미감지 시 박스 없음 (영상만 표시)
- **[패널 닫기]** — 패널 숨기기 + 스트림 요청 중단

**데이터 소스:**
- **영상 프레임:** `GET /camera/<robot_id>` MJPEG 스트림 (control_service REST API). QThread에서 별도 수신.
- **바운딩박스:** TCP 채널 B `{"type": "status", "bbox": {"cx": N, "cy": N, "w": N, "h": N, "conf": 0.92}}` 포함. `status` push 수신 시 bbox 필드 파싱하여 오버레이 갱신.

**동작 조건:**
- 패널은 기본 닫힘 상태. 로봇 카드의 [카메라] 버튼 또는 메뉴에서 열기.
- 선택한 로봇이 OFFLINE이면 "오프라인 — 영상 없음" 표시.
- 선택한 로봇이 TRACKING / TRACKING_CHECKOUT 이외 상태이면 영상은 표시하되 bbox 없음.

---

## TCP 메시지 요약

### 수신 (control_service → admin_ui)

| type | 처리 |
|---|---|
| `status` | 로봇 카드 갱신 (모드·배터리·좌표·`is_locked_return`), 맵 오버레이 위치 갱신, 버튼 활성화 재계산. `bbox` 필드 포함 시 카메라 디버그 패널 오버레이 갱신 |
| `staff_call` | 스태프 호출 패널 항목 추가, 로봇 카드 테두리 강조 |
| `staff_resolved` | 스태프 호출 항목 "처리됨", 카드 테두리 복구 |
| `offline` | 카드 전체 회색, "오프라인" 뱃지, 맵 아이콘 × |
| `online` | 카드 정상 복구, 맵 아이콘 정상 |
| `event` | 이벤트 로그 패널 상단에 행 추가 |
| `admin_goto_rejected` | 오류 토스트 메시지 표시 |

### 송신 (admin_ui → control_service)

| 명령 | 페이로드 | 활성 조건 |
|---|---|---|
| 모드 전환 (대기/복귀) | `{"cmd": "mode", "robot_id": N, "value": "WAITING"\|"RETURNING"}` | 상태별 활성 조건 참고 |
| 추종 재개 | `{"cmd": "resume_tracking", "robot_id": N}` | WAITING, SEARCHING |
| 강제 종료 | `{"cmd": "force_terminate", "robot_id": N}` | CHARGING·OFFLINE·HALTED·LOCKED 제외 |
| 위치 호출 | `{"cmd": "admin_goto", "robot_id": N, "x": x, "y": y, "theta": 0.0}` | IDLE만 |
| 잠금 해제 | `{"cmd": "staff_resolved", "robot_id": N}` | `is_locked_return=True` 또는 HALTED |

> 모든 TCP 수신은 별도 스레드에서 처리 후 `pyqtSignal.emit()`으로 Qt 메인 스레드에 전달.

---

## 유저 플로우

```
[admin_ui 기동]
    → TCP 연결: control_service:8080
    → 맵 이미지 로드, 로봇 카드 초기화, DB 이벤트 초기 50건 로드
        ↓
[실시간 모니터링]
    → 로봇 카드 / 맵 오버레이 1~2Hz 자동 갱신
    → 배터리 20% 이하 → 배터리 바 빨강 강조
    → 30s 무응답 → "오프라인" 뱃지 (cleanup 스레드)

[스태프 호출 수신 시]
    LOCKED:
    → 스태프 호출 패널 항목 추가 + 로봇 카드 빨간 테두리
    → 로봇이 충전 스테이션으로 자동 귀환 (맵에서 이동 확인)
    → 도착 후 [잠금 해제] 클릭 → staff_resolved 전송
    → "처리됨" 표시 + 세션 종료 + 카드 복구

    HALTED:
    → 스태프 호출 패널 항목 추가 + 카드 흰색/주황 테두리
    → 직원이 현장으로 이동하여 로봇을 충전소로 수동 이동
    → [초기화] 클릭 → staff_resolved 전송
    → "처리됨" 표시 + 세션 종료 + 카드 복구

[상태 변경]
    → [대기] 클릭 (TRACKING/TRACKING_CHECKOUT/SEARCHING) → WAITING 전환
    → [추종] 클릭 (WAITING/SEARCHING) → 이전 TRACKING 상태로 복귀
    → [복귀] 클릭 (TRACKING/TRACKING_CHECKOUT/WAITING/SEARCHING) → RETURNING 전환
    → control_service가 /robot_<id>/cmd 로 relay → Pi SM 전환
    → status push 수신 → 카드 모드 뱃지 + 버튼 활성화 자동 갱신

[세션 강제 종료]
    → 로봇 카드 [강제 종료] 클릭 (활성 상태일 때)
    → 확인 다이얼로그
    → control_service → Pi force_terminate 전달
    → 로봇 CHARGING 복귀 (status push로 카드 갱신)

[위치 호출]
    → 로봇이 IDLE 상태일 때 맵 클릭 → 목표 마커 표시
    → [이동 명령] 클릭
    → control_service → Pi admin_goto 전달
    → 이동 완료 (IDLE status 수신) → 목표 마커 제거

[이벤트 로그 조회]
    → 필터 버튼으로 이벤트 유형 필터링
    → 행 클릭 시 해당 로봇 카드 하이라이트
```

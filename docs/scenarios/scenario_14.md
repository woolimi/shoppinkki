# 시나리오 14: 관제 — 알람 수신 및 해제

**SM 전환:** `ALARM → IDLE` (도난) / `ALARM → WAITING` (기타) — 관제 관점
**모드:** PERSON/ARUCO 공통
**관련 패키지:** admin_app, control_service, shoppinkki_core

---

## 개요

로봇에서 알람 이벤트가 발생하면 관제 대시보드가 알람 패널에 이를 표시하고,
관제자가 [해제] 버튼을 눌러 처리한다. 알람 타입(도난/배터리/타임아웃/결제오류)에
따라 해제 후 IDLE 또는 WAITING으로 복귀 경로가 다르다. 두 로봇이 동시에 알람을
발생시키면 각각 독립 패널로 처리한다.

---

## 기능 체크리스트

| 완료 | 기능 |
|:---:|---|
| [ ] | control_service: `/robot_<id>/alarm` 수신 → ALARM_LOG 생성 |
| [ ] | control_service → admin_app 직접 참조로 알람 이벤트 전달 (채널 D) |
| [ ] | admin_app: 알람 패널에 이벤트 추가 (robot_id, event_type, occurred_at) |
| [ ] | 알람 타입별 아이콘/색상 구분 표시 (THEFT=빨강, BATTERY_LOW=노랑, TIMEOUT=주황, PAYMENT_ERROR=보라) |
| [ ] | 해당 로봇 카드에 빨간 테두리 강조 표시 |
| [ ] | [해제] 버튼 → `control_service.dismiss_alarm(robot_id)` 직접 호출 (채널 D) |
| [ ] | control_service → `/robot_<id>/cmd`: `{"cmd": "dismiss_alarm"}` ROS publish |
| [ ] | ALARM_LOG `resolved_at = now` 갱신 |
| [ ] | 해제 후 알람 패널에서 해당 항목 제거 또는 "처리됨" 표시 |
| [ ] | 다중 알람 (두 로봇 동시): 각각 독립 패널 항목으로 표시, 각각 해제 가능 |
| [ ] | THEFT 해제 → Pi SM: IDLE (세션 종료). 알람 패널 IDLE 복귀 확인 |
| [ ] | BATTERY_LOW/TIMEOUT/PAYMENT_ERROR 해제 → Pi SM: WAITING (세션 유지). 알람 패널 WAITING 복귀 확인 |

---

## 전제조건

- admin_app + control_service 기동 중
- 로봇이 ALARM 상태 (도난/배터리/타임아웃/결제오류 중 하나)
- `/robot_<id>/alarm` 토픽 수신됨

---

## 흐름

```
Pi: /robot_<id>/alarm publish
    {"event": "THEFT"|"BATTERY_LOW"|"TIMEOUT"|"PAYMENT_ERROR", "user_id": "..."}
    ↓
control_service: on_alarm_received(robot_id, event)
    → ALARM_LOG INSERT (event_type, robot_id, user_id, occurred_at=now, resolved_at=NULL)
    → admin_app.on_alarm(robot_id, event) 직접 호출 (채널 D)
    → customer_web TCP push: {"type": "alarm", "event": "THEFT"}  ← 고객 앱에도 전달
    ↓
admin_app: 알람 패널 갱신
    → 알람 항목 추가 (robot_id, event_type, 발생 시각)
    → 해당 로봇 카드 빨간 테두리
    → [해제] 버튼 활성화

────── 관제자 알람 해제 ──────
admin_app: [해제] 버튼 클릭 (robot_id)
    → control_service.dismiss_alarm(robot_id) 직접 호출 (채널 D)
    ↓
control_service: dismiss_alarm(robot_id)
    → ALARM_LOG UPDATE resolved_at = now
    → ROS publish: /robot_<id>/cmd: {"cmd": "dismiss_alarm"}
    ↓
shoppinkki_core: on_cmd dismiss_alarm()
    → current_alarm == "THEFT"  → terminate_session() + sm.trigger('dismiss_to_idle')
    → current_alarm != "THEFT"  → sm.trigger('dismiss_to_waiting')
    → current_alarm = None
    ↓
admin_app: 알람 패널 항목 "처리됨" 표시 + 로봇 카드 테두리 복구
```

### 알람 타입별 해제 결과

| event_type | Pi 복귀 상태 | 세션 |
|---|---|---|
| THEFT | IDLE | 강제 종료 |
| BATTERY_LOW | WAITING | 유지 |
| TIMEOUT | WAITING | 유지 |
| PAYMENT_ERROR | WAITING | 유지 |

---

## 기대 결과

| 상황 | admin_app |
|---|---|
| 알람 수신 | 패널 추가, 로봇 카드 빨간 테두리 |
| [해제] 클릭 | 패널 "처리됨", 로봇 카드 복구 |
| 다중 알람 | 각각 독립 패널 항목, 개별 해제 가능 |
| Pi 복귀 상태 | ROBOT 테이블 current_mode 갱신으로 확인 |

---

## UI 검토

| 요소 | 내용 |
|---|---|
| 알람 패널 위치 | 대시보드 우측 사이드바 또는 하단 영역 |
| 알람 항목 | 로봇 ID, 알람 타입 아이콘, 발생 시각, [해제] 버튼 |
| 미처리 알람 강조 | 빨간색 배경. 처리 후 회색 처리 또는 자동 제거 (5초 후) |
| 다중 알람 | 리스트 형태로 쌓임. 가장 최신 알람이 상단 |
| 알람 이력 | 처리된 알람도 일정 시간 표시 유지 (ALARM_LOG 기반) |

---

## 예제 코드 및 모순 점검

### control_service: 알람 수신 및 ALARM_LOG 기록

```python
# control_service/main_node.py
from datetime import datetime

class ControlServiceNode(rclpy.node.Node):
    def _on_alarm(self, robot_id: int, msg):
        data = json.loads(msg.data)
        event_type = data.get('event')  # "THEFT" | "BATTERY_LOW" | "TIMEOUT" | "PAYMENT_ERROR"
        user_id = data.get('user_id', '')
        now = datetime.now().isoformat()

        # ALARM_LOG INSERT
        self.db.execute("""
            INSERT INTO alarm_log (robot_id, user_id, event_type, occurred_at, resolved_at)
            VALUES (?, ?, ?, ?, NULL)
        """, (robot_id, user_id, event_type, now))

        # Channel D: admin_app 알람 패널 갱신 (Signal 필수 — thread safety)
        if self.admin_app:
            self.admin_app.on_alarm(robot_id, event_type, now)

        # TCP push → customer_web → 브라우저
        self._tcp_push(robot_id, {"type": "alarm", "event": event_type})

    def dismiss_alarm(self, robot_id: int, pin: str = None) -> dict:
        if pin and pin != ALARM_DISMISS_PIN:
            return {"error": "invalid_pin"}

        now = datetime.now().isoformat()

        # ⚠️ 모순 #1: SQLite는 UPDATE에서 ORDER BY + LIMIT 미지원
        # 틀린 쿼리: UPDATE alarm_log SET resolved_at=? WHERE robot_id=? AND resolved_at IS NULL ORDER BY occurred_at DESC LIMIT 1
        # 올바른 쿼리: 서브쿼리로 log_id 먼저 조회
        self.db.execute("""
            UPDATE alarm_log SET resolved_at=?
            WHERE log_id = (
                SELECT log_id FROM alarm_log
                WHERE robot_id=? AND resolved_at IS NULL
                ORDER BY occurred_at DESC LIMIT 1
            )
        """, (now, robot_id))

        # Pi에 dismiss_alarm 전달
        self._ros_publish(robot_id, json.dumps({"cmd": "dismiss_alarm"}))

        if self.admin_app:
            self.admin_app.on_alarm_dismissed(robot_id)

        return {"status": "ok"}
```

### admin_app: 알람 패널 Qt Signal 갱신

```python
# admin_app/main_window.py
class AdminMainWindow(QMainWindow):
    alarm_signal = pyqtSignal(int, str, str)       # (robot_id, event_type, occurred_at)
    alarm_dismiss_signal = pyqtSignal(int)          # (robot_id,)

    def __init__(self, control_service):
        super().__init__()
        self.alarm_signal.connect(self._add_alarm_panel)
        self.alarm_dismiss_signal.connect(self._dismiss_alarm_panel)

    def on_alarm(self, robot_id: int, event_type: str, occurred_at: str):
        # ROS 스레드 → Qt 메인 스레드
        self.alarm_signal.emit(robot_id, event_type, occurred_at)

    def on_alarm_dismissed(self, robot_id: int):
        self.alarm_dismiss_signal.emit(robot_id)

    def _add_alarm_panel(self, robot_id: int, event_type: str, occurred_at: str):
        COLORS = {"THEFT": "red", "BATTERY_LOW": "gold", "TIMEOUT": "orange", "PAYMENT_ERROR": "purple"}
        color = COLORS.get(event_type, "gray")
        item = AlarmPanelItem(robot_id, event_type, occurred_at, color)
        item.dismiss_btn.clicked.connect(lambda: self._on_dismiss_clicked(robot_id))
        self.alarm_list.insertItem(0, item)  # 최신 알람이 상단
        self.robot_cards[robot_id].setStyleSheet("border: 3px solid red;")  # 빨간 테두리

    def _on_dismiss_clicked(self, robot_id: int):
        result = self.control_service.dismiss_alarm(robot_id)
        if result.get("error"):
            QMessageBox.warning(self, "오류", result["error"])

    def _dismiss_alarm_panel(self, robot_id: int):
        # 패널 "처리됨" 표시 및 로봇 카드 테두리 복구
        for i in range(self.alarm_list.count()):
            item = self.alarm_list.item(i)
            if item.robot_id == robot_id and not item.resolved:
                item.mark_resolved()  # 회색 처리 + "처리됨" 뱃지
                break
        self.robot_cards[robot_id].setStyleSheet("")  # 테두리 복구
```

### Pi: dismiss_alarm 처리 (shoppinkki_core)

```python
# shoppinkki_core/main_node.py
def on_cmd(self, msg):
    data = json.loads(msg.data)
    if data.get('cmd') == 'dismiss_alarm':
        if self.current_alarm == "THEFT":
            self.terminate_session()
            self.sm.trigger('dismiss_to_idle')    # → IDLE
        else:
            self.sm.trigger('dismiss_to_waiting') # → WAITING (세션 유지)
        self.current_alarm = None
```

### 모순 및 검토 사항

| # | 항목 | 내용 | 처리 |
|---|---|---|---|
| 1 | **SQLite UPDATE ORDER BY** | `UPDATE ... ORDER BY ... LIMIT 1` — SQLite 미지원 | 서브쿼리로 `log_id` 먼저 조회 후 UPDATE |
| 2 | **다중 미해결 ALARM_LOG** | 같은 robot_id에 `resolved_at IS NULL` 행이 여러 개일 수 있음 (재기동 없이 여러 알람 발생) | dismiss_alarm은 가장 최근 발생 알람 1개만 해제. Pi의 `current_alarm`이 실제 현재 알람의 authoritative source |
| 3 | **admin_app Thread Safety** | `on_alarm()` / `on_alarm_dismissed()`도 ROS 스레드에서 호출됨 | `pyqtSignal.emit()` 패턴 필수 (scenario_13과 동일) |
| 4 | **customer_web push 누락** | scenario_11 체크리스트에서 `customer_web TCP push: {"type": "alarm", "event": ...}` 포함인데, scenario_14 흐름 코드에는 누락됨 | `dismiss_alarm` 후에도 customer_web에 `{"type": "alarm_dismissed"}` push 필요 |
| 5 | **ALARM_LOG event_type** | ERD에는 `BATTERY` 표기가 있었음 | ✅ 해결 — `BATTERY_LOW`로 ERD 통일 완료 |

---

## 검증 방법

```bash
# 알람 강제 발생 (도난 시뮬레이션)
ros2 topic pub --once /robot_54/alarm std_msgs/String \
  '{"data": "{\"event\": \"THEFT\", \"user_id\": \"test_user\"}"}'

# ALARM_LOG 확인
sqlite3 src/control_center/control_service/data/control.db \
  "SELECT * FROM alarm_log ORDER BY occurred_at DESC LIMIT 5;"

# 해제 후 resolved_at 갱신 확인
sqlite3 src/control_center/control_service/data/control.db \
  "SELECT log_id, event_type, resolved_at FROM alarm_log ORDER BY occurred_at DESC LIMIT 1;"

# Pi SM 상태 확인
ros2 topic echo /robot_54/status
```

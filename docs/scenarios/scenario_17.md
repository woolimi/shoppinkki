# 시나리오 17: 관제 — 이벤트 로깅

**SM 전환:** 없음 (로깅 전용)
**모드:** PERSON/ARUCO 공통
**관련 패키지:** control_service, admin_app

---

## 개요

관제 서버는 로봇 운용 중 발생하는 주요 이벤트를 중앙 DB의 `EVENT_LOG` 테이블에 기록한다.
admin_app은 실시간 이벤트 로그 패널을 통해 최근 이벤트를 표시하고, 이벤트 타입별 필터링을 제공한다.
알람 이벤트는 기존 `ALARM_LOG`와 중복 기록하지 않으며, `ALARM_LOG`를 `EVENT_LOG` 뷰로 조회한다.

---

## 기능 체크리스트

| 완료 | 기능 |
|:---:|---|
| [ ] | 중앙 서버 DB에 `EVENT_LOG` 테이블 추가 (DDL 아래 정의) |
| [ ] | control_service: `log_event(robot_id, user_id, event_type, detail)` 헬퍼 구현 |
| [ ] | SESSION_START 이벤트: 로그인 성공 시 기록 |
| [ ] | SESSION_END 이벤트: 정상 세션 종료 (`session_ended`) 시 기록 |
| [ ] | FORCE_TERMINATE 이벤트: 관제 강제 종료 시 기록 (scenario_15) |
| [ ] | PAYMENT_SUCCESS / PAYMENT_FAIL 이벤트: 결제 처리 결과 기록 |
| [ ] | MODE_CHANGE 이벤트: 주요 SM 전환(TRACKING, SEARCHING, WAITING, ALARM 등) 기록 |
| [ ] | OFFLINE / ONLINE 이벤트: 오프라인 감지 및 재연결 기록 (scenario_16) |
| [ ] | QUEUE_ADVANCE 이벤트: 대기열 전진 기록 (scenario_18 연계) |
| [ ] | admin_app: 이벤트 로그 패널 (최신 50건 자동 스크롤) |
| [ ] | admin_app: 이벤트 타입별 필터 버튼 (ALARM / SESSION / QUEUE / ALL) |
| [ ] | admin_app: 이벤트 패널 `channel D` Signal로 실시간 갱신 |
| [ ] | control_service: REST `GET /events?robot_id=<id>&limit=50` 엔드포인트 |

---

## 이벤트 타입 정의

| event_type | 발생 시점 | detail 예시 |
|---|---|---|
| `SESSION_START` | login 성공 → start_session 발행 | `{"user_id": "hong123"}` |
| `SESSION_END` | RETURNING → IDLE (세션 정상 종료) | `{"user_id": "hong123", "items": 3}` |
| `FORCE_TERMINATE` | admin_app [강제 종료] | `{"user_id": "hong123", "state": "TRACKING"}` |
| `ALARM_RAISED` | /robot_<id>/alarm 수신 | `{"event": "THEFT"}` (ALARM_LOG와 연계) |
| `ALARM_DISMISSED` | dismiss_alarm 처리 | `{"event": "THEFT", "by": "admin"}` |
| `PAYMENT_SUCCESS` | 결제 성공 | `{"amount": 4500}` |
| `PAYMENT_FAIL` | 결제 실패 → ALARM | `{"reason": "card_error"}` |
| `MODE_CHANGE` | 주요 SM 전환 | `{"from": "TRACKING", "to": "ALARM"}` |
| `OFFLINE` | last_seen > 30s | `{"last_seen": "2026-04-01T12:00:00"}` |
| `ONLINE` | status 재수신 | `{"mode": "IDLE"}` |
| `QUEUE_ADVANCE` | 대기열 전진 | `{"from_pos": 1, "to_pos": 0}` |

---

## DB 스키마 (신규: EVENT_LOG)

```sql
CREATE TABLE event_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    robot_id    INTEGER REFERENCES robot(robot_id),  -- NULL 가능 (시스템 이벤트)
    user_id     TEXT,                                -- NULL 가능 (IDLE 중 이벤트)
    event_type  TEXT    NOT NULL,
    event_detail TEXT,                               -- JSON 문자열
    occurred_at DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_event_log_robot ON event_log(robot_id, occurred_at DESC);
CREATE INDEX idx_event_log_type  ON event_log(event_type, occurred_at DESC);
```

---

## 흐름

```
control_service: 이벤트 발생 감지
    (예: TCP login 성공, /robot_<id>/status 수신으로 SM 전환 감지,
         /robot_<id>/alarm 수신, cleanup 스레드 offline 감지, ...)
    ↓
control_service: log_event(robot_id, user_id, event_type, detail)
    → EVENT_LOG INSERT
    ↓
admin_app: on_event(event_dict) 직접 호출 (채널 D)
    → event_panel_signal.emit(event_dict)  ← Qt Signal
    ↓
admin_app: 이벤트 패널에 새 행 추가
    → 최신 이벤트가 상단 (역순 정렬)
    → 이벤트 타입별 색상 구분
```

---

## 예제 코드 및 모순 점검

### control_service: log_event 헬퍼

```python
# control_service/main_node.py
import json
from datetime import datetime

class ControlServiceNode(rclpy.node.Node):

    def log_event(self, event_type: str, robot_id: int = None,
                  user_id: str = None, detail: dict = None):
        now = datetime.now().isoformat()
        detail_json = json.dumps(detail, ensure_ascii=False) if detail else None

        # ⚠️ 모순 #2: cleanup 스레드에서도 log_event() 호출 가능
        # → DB Lock 필요 (scenario_16 모순 #2와 동일 문제)
        with self._db_lock:
            self.db.execute("""
                INSERT INTO event_log (robot_id, user_id, event_type, event_detail, occurred_at)
                VALUES (?, ?, ?, ?, ?)
            """, (robot_id, user_id, event_type, detail_json, now))

        if self.admin_app:
            self.admin_app.on_event({
                'robot_id': robot_id, 'user_id': user_id,
                'event_type': event_type, 'detail': detail, 'occurred_at': now
            })

    # --- 기존 핸들러에 log_event 삽입 ---

    def _on_login_success(self, robot_id: int, user_id: str):
        # 기존 로그인 처리 ...
        self.log_event('SESSION_START', robot_id=robot_id, user_id=user_id,
                       detail={'user_id': user_id})

    def _on_alarm(self, robot_id: int, msg):
        data = json.loads(msg.data)
        # 기존 ALARM_LOG INSERT ...
        self.log_event('ALARM_RAISED', robot_id=robot_id,
                       user_id=data.get('user_id'),
                       detail={'event': data.get('event')})

    def _run_cleanup(self):
        # 기존 offline 감지 ...
        for robot_id, _ in offline_rows:
            self.log_event('OFFLINE', robot_id=robot_id,
                           detail={'last_seen': str(last_seen)})

    def _on_status(self, robot_id: int, msg):
        was_offline = robot_id in self._offline_robots
        # 기존 처리 ...
        if was_offline:
            self.log_event('ONLINE', robot_id=robot_id,
                           detail={'mode': data.get('mode')})

    # REST 엔드포인트
    def get_events(self, robot_id: int = None, limit: int = 50) -> list:
        if robot_id:
            rows = self.db.execute("""
                SELECT * FROM event_log WHERE robot_id=?
                ORDER BY occurred_at DESC LIMIT ?
            """, (robot_id, limit)).fetchall()
        else:
            rows = self.db.execute("""
                SELECT * FROM event_log ORDER BY occurred_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
```

### admin_app: 이벤트 로그 패널

```python
# admin_app/main_window.py
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QPushButton, QHBoxLayout
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor

EVENT_COLORS = {
    'SESSION_START':    '#d4edda',  # 초록
    'SESSION_END':      '#cce5ff',  # 파랑
    'FORCE_TERMINATE':  '#fff3cd',  # 노랑
    'ALARM_RAISED':     '#f8d7da',  # 빨강
    'ALARM_DISMISSED':  '#e2e3e5',  # 회색
    'PAYMENT_SUCCESS':  '#d4edda',
    'PAYMENT_FAIL':     '#f8d7da',
    'MODE_CHANGE':      '#ffffff',
    'OFFLINE':          '#888888',
    'ONLINE':           '#d4edda',
    'QUEUE_ADVANCE':    '#e8f4f8',
}

class AdminMainWindow(QMainWindow):
    event_signal = pyqtSignal(dict)  # (event_dict,)

    def __init__(self, control_service):
        super().__init__()
        self.event_signal.connect(self._add_event_row)
        self._event_filter = 'ALL'  # 현재 필터

    def on_event(self, event: dict):
        # 모든 스레드 → Qt 메인 스레드
        self.event_signal.emit(event)

    def _add_event_row(self, event: dict):
        etype = event['event_type']

        # 필터 체크
        if self._event_filter != 'ALL':
            if self._event_filter == 'ALARM' and 'ALARM' not in etype:
                return
            if self._event_filter == 'SESSION' and 'SESSION' not in etype and 'FORCE' not in etype:
                return
            if self._event_filter == 'QUEUE' and 'QUEUE' not in etype:
                return

        label = (f"[{event['occurred_at'][11:19]}] "
                 f"Robot#{event['robot_id'] or '-'} "
                 f"{etype}"
                 f"{' | ' + str(event['detail']) if event['detail'] else ''}")

        item = QListWidgetItem(label)
        color = EVENT_COLORS.get(etype, '#ffffff')
        item.setBackground(QColor(color))

        self.event_list.insertItem(0, item)  # 최신 이벤트 상단
        if self.event_list.count() > 200:    # 최대 200건 유지
            self.event_list.takeItem(self.event_list.count() - 1)
```

### 모순 및 검토 사항

| # | 항목 | 내용 | 처리 |
|---|---|---|---|
| 1 | **ALARM_LOG 중복** | ALARM_RAISED/DISMISSED를 EVENT_LOG에 기록하면 ALARM_LOG와 이중 저장됨 | EVENT_LOG의 ALARM 이벤트는 참조용 요약 기록. ALARM_LOG가 원본(resolved_at 포함). 조회 시 ALARM_LOG 우선 |
| 2 | **DB Lock 필요** | log_event()는 ROS 스레드, cleanup 스레드 등 여러 스레드에서 호출됨 | `threading.Lock()` (`self._db_lock`) 으로 모든 DB 접근 보호 (scenario_16 모순 #2 통합) |
| 3 | **MODE_CHANGE 로깅 시점** | control_service는 Pi SM 전환을 `/robot_<id>/status`의 `mode` 필드 변경으로만 감지함. 50ms 이하 짧은 상태는 누락 가능 | demo 용도로 1~2Hz 갱신 주기 내 변경만 기록. 중요 이벤트(ALARM, SESSION)는 즉시 토픽으로 별도 수신하므로 누락 없음 |
| 4 | **EVENT_LOG ERD** | `docs/erd.md`에 EVENT_LOG 테이블 없었음 | ✅ 해결 — erd.md에 EVENT_LOG 테이블 추가 완료 |
| 5 | **REST `/events` 채널 미정의** | `interface_specification.md` 채널 E에 `/events` 엔드포인트 없음 | interface_specification.md 채널 E 추가 필요 |

---

## 기대 결과

| 이벤트 | EVENT_LOG 확인 | admin_app 패널 |
|---|---|---|
| 로그인 성공 | SESSION_START 행 추가 | 녹색 행 상단 표시 |
| 세션 정상 종료 | SESSION_END 행 추가 | 파란 행 상단 표시 |
| 도난 알람 발생 | ALARM_RAISED 행 추가 | 빨간 행 상단 표시 |
| 강제 종료 | FORCE_TERMINATE 행 추가 | 노란 행 상단 표시 |
| 오프라인 감지 | OFFLINE 행 추가 | 회색 행 표시 |

---

## UI 검토

| 요소 | 내용 |
|---|---|
| 패널 위치 | 대시보드 하단 또는 우측 — 로봇 카드와 구분 |
| 행 형식 | `[시각] Robot#<id> <event_type> | <detail>` |
| 색상 구분 | 이벤트 타입별 배경색 (위 EVENT_COLORS 참고) |
| 필터 버튼 | [전체] [알람] [세션] [대기열] — 1개 활성 |
| 자동 스크롤 | 새 이벤트 추가 시 목록 상단으로 자동 이동 |
| 최대 표시 | 200건 유지. 오래된 이벤트는 자동 제거 (DB는 유지) |
| 이벤트 클릭 | 클릭 시 해당 robot_id 카드 하이라이트 |

---

## 검증 방법

```bash
# EVENT_LOG 실시간 확인
watch -n 1 'sqlite3 src/control_center/control_service/data/control.db \
  "SELECT log_id, robot_id, event_type, event_detail, occurred_at FROM event_log ORDER BY occurred_at DESC LIMIT 10;"'

# SESSION_START 이벤트 확인 (로그인 후)
sqlite3 src/control_center/control_service/data/control.db \
  "SELECT * FROM event_log WHERE event_type='SESSION_START' ORDER BY occurred_at DESC LIMIT 3;"

# REST API 확인
curl "http://localhost:8080/events?robot_id=54&limit=10"
```

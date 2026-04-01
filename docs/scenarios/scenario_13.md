# 시나리오 13: 관제 — 실시간 로봇 모니터링

**SM 전환:** 없음 (모니터링 전용)
**모드:** PERSON/ARUCO 공통
**관련 패키지:** admin_app, control_service

---

## 개요

관제 대시보드(admin_app)가 기동되어 두 로봇(#54, #18)의 현재 상태를 실시간으로 표시한다.
모드, 위치(맵 오버레이), 배터리, 활성 사용자를 1~2Hz로 갱신하며 로봇이 오프라인이면
별도 상태로 표시한다. admin_app과 control_service는 동일 프로세스이므로 ROS DDS를
거치지 않고 채널 D 직접 참조로 데이터를 전달받는다.

---

## 기능 체크리스트

| 완료 | 기능 |
|:---:|---|
| [ ] | admin_app 기동 시 control_service와 동일 프로세스에서 초기화 |
| [ ] | control_service: `/robot_<id>/status` 수신마다 내부 상태 dict 갱신 |
| [ ] | control_service → admin_app 직접 참조로 상태 dict 전달 (채널 D) |
| [ ] | admin_app PyQt UI: 로봇 카드 2개 (#54, #18) 표시 |
| [ ] | 로봇 카드: 현재 모드, 배터리 %, 활성 사용자 ID, 좌표 표시 |
| [ ] | 지도 이미지(`shop_map.png`) 위에 로봇 위치 오버레이 (dot 또는 화살표 아이콘) |
| [ ] | 배터리 20% 이하 → 배터리 표시 빨간색 강조 |
| [ ] | 로봇 `last_seen` 기준 OFFLINE 감지 → 로봇 카드 회색 처리 + "오프라인" 뱃지 |
| [ ] | 1~2Hz 갱신 (control_service heartbeat 수신 주기와 동기) |

---

## 전제조건

- admin_app + control_service 동일 프로세스로 기동
- `/robot_54/status`, `/robot_18/status` 토픽 수신 중
- `shop_map.png` 맵 이미지 로드됨
- ZONE 테이블 및 ROBOT 테이블 초기화됨

---

## 흐름

```
admin_app 기동
    → control_service와 동일 프로세스 초기화
    → 맵 이미지 로드, 로봇 카드 UI 초기화
    ↓
control_service: /robot_<id>/status 수신 (1~2Hz)
    → ROBOT 테이블 갱신 (current_mode, pos_x, pos_y, battery_level, last_seen)
    → 내부 상태 dict → admin_app 직접 참조로 전달 (채널 D 콜백)
    ↓
admin_app: UI 갱신 (PyQt main thread, QTimer 또는 Signal)
    → 로봇 카드: 모드 뱃지, 배터리 바, 사용자 ID
    → 지도 오버레이: pos_x, pos_y → 픽셀 좌표 변환 후 dot 갱신
```

### 좌표 → 픽셀 변환

```python
# 맵 yaml에서 resolution, origin을 읽어 변환
def world_to_pixel(x, y, origin_x, origin_y, resolution, img_height):
    px = int((x - origin_x) / resolution)
    py = int(img_height - (y - origin_y) / resolution)  # y축 반전
    return px, py
```

---

## 기대 결과

| 항목 | 기대값 |
|---|---|
| 로봇 카드 갱신 주기 | 1~2Hz (status 수신 주기와 동기) |
| 위치 오버레이 | 실제 AMCL 위치와 시각적으로 일치 |
| 배터리 경고 | 20% 이하 시 빨간색 강조 |
| 오프라인 감지 | last_seen > ROBOT_TIMEOUT_SEC(30s) 시 "오프라인" 뱃지 |

---

## UI 검토

| 요소 | 내용 |
|---|---|
| 로봇 카드 레이아웃 | 로봇 ID(#54/18), 모드 뱃지(색상 구분), 배터리 바, 사용자 ID, 좌표 |
| 맵 오버레이 | shop_map.png 위에 로봇별 아이콘(색상 구분). 아이콘 방향은 yaw 기반 회전 |
| 오프라인 상태 | 카드 전체 회색 처리, 위치 아이콘 X 표시 |
| 다중 알람 알림 | 알람 발생 시 해당 로봇 카드 빨간 테두리 (Scenario 14 연계) |

---

## 예제 코드 및 모순 점검

### control_service: 상태 수신 및 admin_app 갱신

```python
# control_service/main_node.py
from datetime import datetime

class ControlServiceNode(rclpy.node.Node):
    def __init__(self, admin_app=None):
        super().__init__('control_service')
        self.admin_app = admin_app  # Channel D: 직접 참조
        self.status_sub_54 = self.create_subscription(
            String, '/robot_54/status', lambda m: self._on_status(54, m), 10)
        self.status_sub_18 = self.create_subscription(
            String, '/robot_18/status', lambda m: self._on_status(18, m), 10)

    def _on_status(self, robot_id: int, msg):
        data = json.loads(msg.data)
        now = datetime.now().isoformat()
        self.db.execute("""
            UPDATE robot
            SET current_mode=?, pos_x=?, pos_y=?, battery_level=?, last_seen=?
            WHERE robot_id=?
        """, (data['mode'], data['pos_x'], data['pos_y'], data['battery'], now, robot_id))

        # ⚠️ 모순 #1: admin_app.on_robot_status_update()는 ROS 서브스크라이버 스레드에서
        # 호출됨. PyQt UI를 직접 수정하면 Qt thread-safety 위반 → Signal/Slot 필수
        if self.admin_app:
            self.admin_app.on_robot_status_update(robot_id, {
                'mode': data['mode'],
                'pos_x': data['pos_x'], 'pos_y': data['pos_y'],
                'battery': data['battery'], 'last_seen': now
            })
```

### admin_app: Qt Signal로 UI 갱신

```python
# admin_app/main_window.py
from PyQt6.QtCore import pyqtSignal, QTimer
from PyQt6.QtWidgets import QMainWindow

MAP_ORIGIN_X = -0.1   # shop.yaml origin[0]
MAP_ORIGIN_Y = -0.1   # shop.yaml origin[1]
MAP_RESOLUTION = 0.05 # shop.yaml resolution (m/pixel)

def world_to_pixel(x, y, img_height):
    px = int((x - MAP_ORIGIN_X) / MAP_RESOLUTION)
    py = int(img_height - (y - MAP_ORIGIN_Y) / MAP_RESOLUTION)  # y축 반전
    return px, py

class AdminMainWindow(QMainWindow):
    # Signal: (robot_id, status_dict) — ROS 스레드 → Qt 메인 스레드
    robot_status_signal = pyqtSignal(int, dict)

    def __init__(self, control_service):
        super().__init__()
        self.robot_status_signal.connect(self._update_robot_card)

    def on_robot_status_update(self, robot_id: int, status: dict):
        # ROS 스레드에서 호출 → emit으로 Qt 메인 스레드에 위임
        self.robot_status_signal.emit(robot_id, status)

    def _update_robot_card(self, robot_id: int, status: dict):
        # Qt 메인 스레드: UI 안전하게 갱신
        card = self.robot_cards[robot_id]
        card.mode_label.setText(status['mode'])
        card.battery_bar.setValue(status['battery'])
        if status['battery'] <= 20:
            card.battery_bar.setStyleSheet("QProgressBar::chunk { background: red; }")

        # 지도 오버레이 갱신
        img_height = self.map_pixmap.height()
        px, py = world_to_pixel(status['pos_x'], status['pos_y'], img_height)
        card.map_dot.move(px - 5, py - 5)  # 중심 정렬
```

### 모순 및 검토 사항

| # | 항목 | 내용 | 처리 |
|---|---|---|---|
| 1 | **PyQt Thread Safety** | `on_robot_status_update()`는 ROS 서브스크라이버 스레드에서 호출됨. Qt 위젯을 직접 수정하면 크래시 발생 | `pyqtSignal` + `emit()` 패턴 필수 |
| 2 | **맵 yaml 미로드** | `world_to_pixel()`에 `MAP_ORIGIN_X`, `MAP_RESOLUTION` 필요. 하드코딩 시 맵 변경에 취약 | admin_app 기동 시 `shop.yaml` 파싱하여 초기화 |
| 3 | **오프라인 감지 누락** | 시나리오 흐름에 offline 처리가 없음. `last_seen` 기반 offline 감지는 → **시나리오 16** 참조 | scenario_16.md에서 전담 |
| 4 | **배터리 표시 기준** | 체크리스트에는 20% 이하 빨간색이지만, 흐름에서 명시 안 됨 | `battery <= 20` 시 빨간색 적용 |

---

## 검증 방법

```bash
# 두 로봇 status 발행 확인
ros2 topic hz /robot_54/status
ros2 topic hz /robot_18/status

# ROBOT 테이블 실시간 상태 확인
watch -n 1 'sqlite3 src/control_center/control_service/data/control.db \
  "SELECT robot_id, current_mode, pos_x, pos_y, battery_level, last_seen FROM robot;"'

# admin_app 기동
ros2 run control_service admin_app
```

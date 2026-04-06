# ShopPinkki Open-RMF Fleet Adapter

ShopPinkki 프로젝트의 Open-RMF Fleet Adapter 구현 문서.  
두 Pinky 로봇(#54, #18)을 RMF EasyFullControl에 등록하고 경로 충돌을 자동 조정한다.

---

## 1. 개발 환경

| 항목 | 값 |
|---|---|
| OS | Ubuntu 24.04 (Noble) |
| ROS | ROS 2 Jazzy Jalisco |
| Python | 3.12 (시스템 `/usr/bin/python3`) |
| rmf_fleet_adapter | 2.7.2 |
| NumPy | **1.x 필수** (2.x 비호환 — 아래 섹션 참고) |

---

## 2. 패키지 구조

```
src/control_center/shoppinkki_rmf/
├── config/
│   └── fleet_config.yaml        ← 플릿 설정 (속도, 배터리, 로봇 목록)
├── maps/
│   ├── shop_nav_graph.yaml      ← RMF 네비게이션 그래프 (28 waypoints)
│   └── shop.building.yaml       ← building_map_generator 입력 포맷 (nav graph와 동기화)
├── launch/
│   └── rmf_fleet.launch.py
└── shoppinkki_rmf/
    └── fleet_adapter.py         ← 메인 Fleet Adapter 코드

scripts/
├── visualize_nav_graph.py       ← Nav graph 시각화 스크립트
└── db/seed_data.sql             ← ZONE 테이블 waypoint 좌표 (nav graph와 동기화)

docs/
└── nav_graph_viz.png            ← 최신 nav graph 시각화 이미지
```

---

## 3. 맵 정보

### 3.1 물리 맵

| 항목 | 값 |
|---|---|
| 맵 파일 | `shop.pgm` |
| 해상도 | 0.01 m/px |
| 크기 | **1.88m × 1.41m** (안쪽 벽 기준 실측 — 로봇이 실제로 주행하는 공간) |
| origin | `[-0.183, -1.773]` |
| 좌표계 | ROS 2 맵 월드 좌표 (`amcl_pose` 기준) |

### 3.2 그리드 정렬 기준

노드 좌표는 아래 기준으로 그리드 정렬되어 있다.

| 라인 | 기준값 | 해당 노드 |
|---|---|---|
| 왼쪽 복도 (x) | -0.056 | 0,1,2,3,4,5 |
| 위쪽 복도 (y) | -0.007 | 0,6,7,8,9 |
| 내부 1열 (y) | -0.300 | 1,18,19,10 |
| 내부 2열 (y) | -0.606 | 2,21,20,11 |
| 내부 3열 (y) | -0.899 | 3,22,12 |
| 오른쪽 복도 (x) | 1.151 | 9,10,11,12,13,14 |

### 3.3 Waypoint 목록 (28개)

| idx | 이름 | x (m) | y (m) | 속성 |
|---|---|---|---|---|
| 0 | 입구1 | -0.056 | -0.007 | — |
| 1 | 입구2 | -0.056 | -0.300 | — |
| 2 | P1 | -0.056 | -0.606 | charger, parking |
| 3 | P2 | -0.056 | -0.899 | charger, parking |
| 4 | 출구2 | -0.056 | -1.402 | — |
| 5 | 출구1 | -0.056 | -1.617 | — |
| 6 | 가전제품1 | 0.489 | -0.007 | pickup_zone |
| 7 | 가전제품2 | 0.749 | -0.007 | pickup_zone |
| 8 | 과자1 | 0.950 | -0.007 | pickup_zone |
| 9 | 과자_해산물 | 1.151 | -0.007 | — |
| 10 | 해산물2 | 1.151 | -0.300 | pickup_zone |
| 11 | 육류1 | 1.151 | -0.606 | pickup_zone |
| 12 | 육류2 | 1.151 | -0.899 | pickup_zone |
| 13 | 채소1 | 1.151 | -1.224 | pickup_zone |
| 14 | 채소_화장실 | 1.151 | -1.606 | — |
| 15 | 화장실2 | 0.812 | -1.606 | pickup_zone |
| 16 | 결제구역1 | 0.186 | -1.614 | holding_point |
| 17 | 결제구역2 | 0.183 | -1.402 | holding_point |
| 18 | 빵1 | 0.494 | -0.300 | pickup_zone |
| 19 | 빵2 | 0.749 | -0.300 | pickup_zone |
| 20 | 가공식품1 | 0.774 | -0.606 | pickup_zone |
| 21 | 가공식품2 | 0.473 | -0.606 | pickup_zone |
| 22 | 음료1 | 0.704 | -0.899 | pickup_zone |
| 23 | 음료2 | 0.715 | -1.197 | pickup_zone |
| 24 | 진열대1_좌측우회 | 0.300 | -0.450 | detour |
| 25 | 진열대1_우측우회 | 0.920 | -0.440 | detour |
| 26 | 진열대2_우측우회 | 0.960 | -1.050 | detour |
| 27 | 진열대2_좌측우회 | 0.460 | -1.050 | detour (26번 대칭) |

충전소: **P1 (idx=2)** → pinky_54, **P2 (idx=3)** → pinky_18

> 시각화: `docs/nav_graph_viz.png` / 생성 스크립트: `scripts/visualize_nav_graph.py`

### 3.4 우회 경로 (Detour)

진열대를 관통하는 직선 경로를 제거하고 우회 waypoint를 추가.

| 관통 구간 | 우회 경로 | 우회 방향 |
|---|---|---|
| 18↔21 (진열대1) | 18 ↔ 24 ↔ 21 | 좌측 |
| 19↔20 (진열대1) | 19 ↔ 25 ↔ 20 | 우측 |
| 22↔23 (진열대2) | 22 ↔ 26 ↔ 23 | 우측 |
| 22↔23 (진열대2) | 22 ↔ 27 ↔ 23 | 좌측 (26 대칭) |

---

## 4. RMF Fleet Adapter 구조

### 4.1 핵심 클래스

**`RobotAdapter`** — 로봇 1대 담당
- 로봇 위치/배터리/모드 상태 관리
- `navigate` 콜백: `control_service` REST API로 `navigate_to` 명령 전달 후 도착 폴링
- `stop` 콜백: `WAITING` 모드 명령
- `_wait_arrive()`: 500ms 간격 폴링, dist ≤ 0.15m && dyaw ≤ 0.30 rad → `done_cb()` 호출

**`PinkyFleetAdapter(Node)`** — ROS2 노드
- `/robot_<id>/status` 토픽 구독 (JSON `pos_x/pos_y/yaw/battery/mode`)
- `efc.FleetConfiguration.from_config_files()` 로 플릿 설정 로드
- `adpt.Adapter.make(fleet_name)` → `add_easy_fleet()` → `start()`
- 각 로봇을 `add_robot()` 으로 등록

### 4.2 초기화 순서 (중요)

```python
adpt.init_rclcpp()   # 1. rclcpp 먼저 초기화 (없으면 RuntimeError)
rclpy.init()         # 2. rclpy 초기화
```

`adpt.init_rclcpp()` 를 먼저 호출하지 않으면 `adpt.Adapter.make()` 에서 오류 발생.

### 4.3 Fleet Adapter ↔ 시스템 통신

```
RMF Core
  ↕ (RMF DDS)
FleetAdapter (fleet_adapter.py)
  ↕ REST API (HTTP :8081)
control_service
  ↕ ROS DDS (/robot_<id>/cmd, /robot_<id>/status)
Pi 5 (shoppinkki_core)
  ↕ Hardware
Pinky 로봇
```

---

## 5. 실행 방법

### 5.1 사전 준비

```bash
# RMF 패키지 설치
sudo apt install ros-jazzy-rmf-fleet-adapter ros-jazzy-rmf-traffic ros-jazzy-rmf-task

# NumPy 1.x 설치 (2.x 비호환 — 반드시 필요)
pip install "numpy<2.0"

# 빌드
cd ~/ros_ws
colcon build --packages-select shoppinkki_rmf --symlink-install
source install/setup.zsh
```

### 5.2 실행 순서

**터미널 1** — RMF Traffic Scheduler (필수, fleet adapter보다 먼저 실행)
```bash
source /opt/ros/jazzy/setup.zsh
ros2 run rmf_traffic_ros2 rmf_traffic_schedule
```

**터미널 2** — Fleet Adapter
```bash
source ~/ros_ws/install/setup.zsh
ros2 launch shoppinkki_rmf rmf_fleet.launch.py
```

> `control_service` 가 실행 중이지 않아도 Fleet Adapter 자체는 기동됨.  
> `Connection refused :8081` 경고가 떠도 RMF 로봇 등록은 정상 완료.

### 5.3 정상 기동 로그 예시

```
[fleet_adapter]: PinkyFleetAdapter 준비: ['54', '18']
[fleet_adapter]: RMF Adapter 시작: pinky_fleet
[fleet_adapter]: 로봇 등록: pinky_54 (charger=P1)
[fleet_adapter]: 로봇 등록: pinky_18 (charger=P2)
[rmf_traffic_schedule]: ... negotiation resolved ...
```

---

## 6. 주요 설정 파일

### 6.1 `config/fleet_config.yaml` — 핵심 포맷

```yaml
rmf_fleet:
  name: "pinky_fleet"          # 키 이름은 반드시 "name" (fleet_name 아님)
  profile:
    footprint: 0.060            # 로봇 반지름 (m) — 필수
    vicinity: 0.200             # 충돌 판정 반경 (m) — 필수 (없으면 오류)
  limits:
    linear:  [0.30, 0.50]      # 반드시 시퀀스 [vel, accel] (dict 형식 사용 불가)
    angular: [1.00, 1.50]
  ...
```

### 6.2 `maps/shop_nav_graph.yaml` — 핵심 포맷

`building_map_generator` 출력과 동일한 구조를 사용해야 `from_config_files()` 에서 로드됨.

```yaml
building_name: "..."
levels:
  L1:
    vertices:
      - [x, y, {name: "P1", is_charger: true, is_parking_spot: true}]
    lanes:
      - [from_idx, to_idx, {is_bidirectional: false}]
lifts: {}
doors: {}
```

---

## 7. 트러블슈팅

### 7.1 Segfault (exit code -11 / -139) — NumPy ABI 비호환

**증상:** `fleet_adapter` 가 즉시 종료, exit code -11 또는 -139.

**원인:** `rmf_adapter` Python 바인딩이 NumPy 1.x ABI로 컴파일됨.  
시스템에 NumPy 2.x가 설치되어 있으면 `add_waypoint()` 등 Eigen 행렬 인수를 받는 함수에서 segfault 발생.

**해결:**
```bash
pip install "numpy<2.0"
```

### 7.2 `RuntimeError: rclcpp must be initialized`

**원인:** `rclpy.init()` 은 rclcpp를 초기화하지 않음.  
`adpt.Adapter.make()` 는 내부적으로 rclcpp를 사용하므로 별도 초기화 필요.

**해결:** `main()` 에서 `adpt.init_rclcpp()` 를 `rclpy.init()` 보다 먼저 호출.

### 7.3 `RuntimeError: invalid node; first invalid key "0"`

**원인:** `fleet_config.yaml` 의 `limits.linear` 가 dict 형식으로 작성됨.

```yaml
# 잘못된 형식
limits:
  linear:
    velocity: 0.30
    acceleration: 0.50

# 올바른 형식
limits:
  linear: [0.30, 0.50]
```

### 7.4 `Fleet profile is not provided`

**원인:** `profile.vicinity` 누락. `footprint` 와 `vicinity` 둘 다 필수.

### 7.5 `Fleet name is not provided`

**원인:** 최상위 키가 `fleet_name` 이 아니라 `rmf_fleet.name` 이어야 함.

### 7.6 Traffic Scheduler 충돌

**원인:** `rmf_traffic_schedule` 을 launch 파일에서도 실행하고 터미널에서도 실행하면 두 번째 인스턴스가 즉시 종료.

**해결:** `rmf_fleet.launch.py` 에서 `rmf_traffic_schedule` 을 제거하고 별도 터미널에서 단독 실행.

---

## 8. 의존 패키지

| 패키지 | 설치 방법 | 비고 |
|---|---|---|
| `ros-jazzy-rmf-fleet-adapter` | `apt` | C++ 라이브러리 + Python 바인딩 |
| `ros-jazzy-rmf-traffic` | `apt` | Traffic negotiation 엔진 |
| `ros-jazzy-rmf-traffic-ros2` | `apt` | `rmf_traffic_schedule` 실행 파일 포함 |
| `ros-jazzy-rmf-task` | `apt` | Task 메시지 타입 |
| `numpy < 2.0` | `pip` | ABI 비호환으로 1.x 필수 |
| `requests` | `pip` | REST API 호출 (`control_service`) |
| `pyyaml` | 시스템 기본 포함 | config 로드 |

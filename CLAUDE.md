# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
## 🤖 AI Coding Guidelines for Open-RMF Project

이 프로젝트는 다수의 로봇(스마트 쇼핑 카트 등)을 제어하고 인프라와 연동하는 시스템입니다. AI는 코드를 작성하거나 디버깅을 도울 때 아래 규칙을 절대적으로 준수해야 합니다.

### 1. 🛑 절대 엄수: 개발 환경 (Strict Environment Rules)
* **OS & ROS Version:** Ubuntu 24.04 (Noble) / ROS 2 Jazzy Jalisco
* **Python Environment:** 무조건 시스템 순정 파이썬(`/usr/bin/python3`, Python 3.12)만 사용합니다.
* **[PROHIBITED]** Conda, venv 등 가상환경을 사용하는 명령어, 경로 설정, 패키지 설치 방법은 **절대 제안하지 마세요.** (의존성 설치는 오직 `rosdep`과 `apt`만 사용합니다.)

### 2. 🗺️ Open-RMF 아키텍처 규칙 (Open-RMF Architecture)
* **지도 및 경로 생성:** 구형 도구인 `traffic_editor` 대신, 최신 규격인 **`rmf_site_editor`**를 기준으로 맵 파일(`.site`)과 네비게이션 그래프를 생성하는 방법을 제안하세요.
* **Fleet Adapter 구현:** * 로봇 하드웨어를 직접 제어하는 코드와 RMF Core와 통신하는 `fleet_adapter` 코드를 명확히 분리하세요.
  * Python 기반의 `rmf_fleet_adapter_python` (Full Control 또는 Read Only 모드) API를 활용하여 작성하세요.
* **메시지 타입:** 상태 보고 및 명령 하달 시 임의의 메시지 타입을 만들지 말고, 반드시 공식 `rmf_fleet_msgs`, `rmf_task_msgs`, `rmf_building_map_msgs` 패키지에 정의된 표준 인터페이스를 사용하세요.

### 3. 🧑‍💻 ROS 2 Jazzy 코딩 컨벤션 (ROS 2 Coding Standards)
* **Node 작성:** 파이썬(`rclpy`)과 C++(`rclcpp`) 모두 객체 지향적(OOP)으로 Class 기반의 Node를 작성하세요.
* **로깅 (Logging):** 파이썬의 기본 `print()` 함수 사용을 엄격히 금지합니다. 무조건 ROS 표준 로거(`self.get_logger().info()`, `RCLCPP_INFO()`)를 사용하세요.
* **QoS (Quality of Service):** 센서 데이터(IMU, LiDAR 등)는 `SensorDataQoS`, 제어 및 상태 메시지(RMF 통신)는 `Reliable` 정책을 명시적으로 설정하여 통신 유실을 방지하세요.

### 4. 🛠️ 빌드 및 디버깅 지침 (Build & Debugging)
* 빌드 명령어는 항상 `colcon build --symlink-install`을 기준으로 안내하세요.
* C++ 컴파일 에러나 Python 모듈 에러 발생 시, 시스템 경로 꼬임(환경 변수) 문제를 가장 먼저 의심하고 해결책을 제시하세요.
* 새로운 패키지나 의존성이 추가될 경우, 반드시 `package.xml`과 `CMakeLists.txt` (또는 `setup.py`) 양쪽에 누락 없이 추가하도록 코드를 제공하세요.

### 5. 🏗️ 프로젝트 진행 순서 및 마일스톤 (Development Workflow)
* **[CRITICAL] 현재 최우선 과제는 SLAM을 이용한 새로운 지도(Map) 생성입니다.** * RMF 연동이나 Fleet Adapter 개발을 논의하기 전에, 반드시 `slam_toolbox`와 Nav2를 활용하여 Gazebo/실제 환경의 2D Occupancy Grid Map(`.yaml`, `.pgm`)을 완벽하게 새로 뽑아내는 작업부터 먼저 제안하고 집중하세요.
* 지도가 완성된 후에야 해당 지도를 `rmf_site_editor`에 올려서 RMF용 그래프(경로)를 그리는 다음 단계로 넘어갑니다.

### 6. 🚫 레거시(기존) 코드 참조 금지 (Ignore Legacy RMF Code)
* 기존에 작업되어 있던 Open-RMF 관련 코드나 파일들은 구조적 결함이 있을 수 있으므로 **절대 참조하거나 재사용하려고 시도하지 마세요.**
* 기존 코드를 억지로 수정(Fix)하려 하지 말고, 완전히 새로운 아키텍처를 기반으로 **처음부터 새로(From Scratch) 구축**하는 코드를 제안하세요.

### 7. 🗺️ Nav2 및 SLAM 가이드라인 (Nav2 & SLAM Toolbox)
* SLAM을 수행할 때는 오래된 `gmapping` 등을 사용하지 말고, ROS 2 Jazzy의 표준인 **`slam_toolbox` (비동기 매핑 모드)**를 사용하도록 안내하세요.
* 로봇의 자율주행(네비게이션) 파트는 반드시 **Nav2 (Navigation2)** 프레임워크를 기반으로 작성하며, Behavior Tree(`.xml`) 설정이나 파라미터 튜닝 시 Jazzy 버전에 맞는 최신 문법을 사용하세요.

## Project Overview

**쑈삥끼 (ShopPinkki)** — Pinky Pro 로봇을 활용한 미니어처 마트 스마트 카트 데모 프로젝트.
- Robot platform: Pinky Pro (110×120×142mm), Raspberry Pi 5 (8GB)
- Demo environment: 1.88×1.4m miniature shopping mall
- ROS 2 Jazzy / Ubuntu 24.04
- Two robots: Pinky #54 (`192.168.102.54`), Pinky #18 (`192.168.102.18`)
- **추종 방식:** 인형 전용 custom-trained YOLOv8(AI Server)로 인형 클래스 감지 후, Pi 5 로컬에서 ReID 특징 벡터 + HSV 색상 히스토그램 매칭으로 주인 인형 식별, P-Control 추종

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
pip install transitions              # SM 라이브러리 (shoppinkki_core)
pip install flask flask-socketio     # customer_web
pip install ultralytics              # YOLO (ai_server)
pip install mysql-connector-python   # control_service DB 접속
```

**Open-RMF 의존 패키지 (shoppinkki_rmf 빌드 시):**
```bash
sudo apt install ros-jazzy-rmf-fleet-adapter ros-jazzy-rmf-traffic ros-jazzy-rmf-task
pip install rmf-adapter              # Python binding
```

## Testing & Linting

```bash
# Run tests for a package
colcon test --packages-select <pkg_name>
colcon test-result --verbose

# Python linting (flake8, pep257) is run via ament_lint_auto
```

Python packages use pytest. Test files are in `test/` subdirectories of each package.

### customer_web 인증 플로우 테스트

- 테스트 파일: `services/customer_web/tests/test_auth_flow.py` (22개 케이스)
- 픽스처: `services/customer_web/tests/conftest.py` — ControlClient TCP mock, _ctrl_rest mock
- 수동 실행: `cd services/customer_web && python3 -m pytest tests/ -v`
- **pre-commit hook** (`.git/hooks/pre-commit`): `services/customer_web/` 파일이 스테이징되면 자동 실행, 실패 시 커밋 차단

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

> 상세 사용법 → `scripts/index.md`

#### 시뮬레이션 (실물 없을 때)

```bash
bash scripts/run_server.sh   # 터미널 A — control_service + AI Docker
bash scripts/run_ui.sh       # 터미널 B — admin_ui + customer_web
bash scripts/run_sim.sh      # 터미널 C — Gazebo + Nav2 x2 + shoppinkki_core x2
```

Gazebo 로딩 완료(~60초) 후:
1. **admin_ui** 각 로봇 카드 → **[위치 초기화]** 클릭 (AMCL 초기 위치 설정)
2. **customer_web** `http://localhost:8501/?robot_id=54` 로그인 → CHARGING → IDLE 전환

> customer_web IDLE 패널의 **[시뮬레이션 모드]** 버튼으로 추종 없이 쇼핑 테스트 가능.

#### 실물 로봇

```bash
bash scripts/run_server.sh          # [노트북] 서버
bash scripts/run_ui.sh              # [노트북] UI
bash scripts/run_robot.sh 54        # [Pi 5] 로봇 54번
bash scripts/run_robot.sh 18        # [Pi 5] 로봇 18번
```

```bash
bash scripts/run_server.sh --no-ai   # AI 서버 없이 실행
bash scripts/seed.sh                  # DB 시딩 (대화형)
```

> tmux 세션 구성 상세 → `scripts/index.md`

### Simulation (Gazebo) — 맵 빌딩 / 단독 Nav2

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

```bash
ros2 topic echo /clicked_point   # 맵 좌표 확인 (RViz "Publish Point" 연계)
ros2 topic echo /amcl_pose       # 현재 로봇 pose
```

### Open-RMF Fleet Adapter 실행
```bash
ros2 launch shoppinkki_rmf rmf_fleet.launch.py
```

## Directory Structure

```
ros_ws/
├── src/
│   ├── pinky_pro/          ← 하드웨어 플랫폼 패키지 (git submodule, 수정 금지)
│   ├── shoppinkki/         ← Pi 5 실행 ROS2 패키지
│   │   ├── shoppinkki_interfaces/   ← 인터페이스 + Mock 구현체
│   │   ├── shoppinkki_core/         ← 메인 노드 (SM + BT + HW)
│   │   ├── shoppinkki_nav/          ← Nav2 BT + BoundaryMonitor + shop 맵
│   │   └── shoppinkki_perception/   ← YOLO bbox 수신 + ReID/QR 스캔
│   └── control_center/     ← 서버 PC 실행 ROS2 패키지
│       ├── control_service/         ← ROS2 노드 + TCP(8080) + REST API + 중앙 MySQL DB
│       ├── admin_ui/                ← TCP 관제 클라이언트
│       └── shoppinkki_rmf/          ← Open-RMF Fleet Adapter
├── services/
│   ├── customer_web/        ← Flask + SocketIO 고객 웹앱 (포트 8501)
│   └── ai_server/           ← Docker: 커스텀 YOLO(TCP:5005) + LLM(REST:8000)
└── scripts/
    ├── seed.sh / run_server.sh / run_ui.sh / run_sim.sh / run_robot.sh / run_ai.sh
```

> 컴포넌트별 상세 설명 → `docs/system_architecture.md`

## Coding Conventions

**control_service DB (mysql-connector-python):**
- 플레이스홀더: `%s`
- 항상 명시적 cursor 사용, `cursor(dictionary=True)`로 dict row 반환
- 연결 설정은 환경 변수 `MYSQL_HOST/PORT/USER/PASSWORD/DATABASE`로 관리

## Key Documentation

> 아래 문서들이 각 영역의 **source of truth**다. 설계·구현 판단이 필요할 때 먼저 확인한다.

| 문서 | 참고 시점 |
|---|---|
| `docs/system_architecture.md` | 전체 구성도, 컴포넌트 역할, 통신 채널 A~H |
| `docs/state_machine.md` | SM 10개 상태 정의, 전환 테이블, `is_locked_return` / `previous_tracking_state` 구현 |
| `docs/behavior_tree.md` | BT 1~5 flowchart, SM↔BT 역할 분담, Keepout Filter 활성화 조건 |
| `docs/interface_specification.md` | ROS 토픽·서비스, `/robot_<id>/cmd` 페이로드, REST API, 채널별 메시지 포맷 |
| `docs/erd.md` | DB 스키마 (MySQL DDL), 특수 zone ID (충전소 140/141, 결제구역 150) |
| `docs/map.md` | 맵 레이아웃, 구역 ID, 맵 좌표계 |
| `docs/customer_ui.md` | Customer UI 화면 구성, 유저 플로우 |
| `docs/admin_ui.md` | Admin UI 화면 구성, TCP 명령, 카메라 디버그 패널 |
| `docs/user_requirements.md` | UR 테이블 (LCD 표시 정책 UR-21 포함) |
| `docs/scenarios/index.md` | 시나리오 목록 SC-01~SC-82 — 상태 전환 단위 테스트 |
| `cheatsheet.md` | SLAM·Navigation 빠른 명령 참조 |
| `src/shoppinkki/shoppinkki_core/shoppinkki_core/config.py` | 전체 파라미터 값 (KP_ANGLE, BATTERY_THRESHOLD 등) |

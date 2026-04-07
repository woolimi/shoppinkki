# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
pip install qrcode[pil]              # Pi LCD QR 코드 표시 (shoppinkki_core)
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

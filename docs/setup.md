# 환경 셋업 (Setup)

> **프로젝트:** 쑈삥끼 (ShopPinkki)
> ROS 2 Jazzy 기준. 본인 환경에 맞는 트랙 하나만 따라가면 됨.
> 의존성 SSOT는 매니페스트 파일이고 (`environment*.yml`, `requirements*.txt`, `robot.requirements.txt`),
> 실제 설치 순서는 아래 트랙별 명령을 따른다. 패키지 추가/제거 시 매니페스트만 수정.

## 0. 공통 사전 단계

```bash
git clone --recurse-submodules git@github.com:addinedu-physicalai-1st/ros-repo-2.git ~/shoppinkki
cd ~/shoppinkki
# submodule 확인 (sllidar_ros2 + py_trees_ros 등 device/ 아래 외부 ROS 패키지)
ls device/sllidar_ros2/package.xml device/py_trees_ros/package.xml
```

> 만약 submodule이 비어 있으면: `git submodule update --init --recursive`

트랙 선택:
- **A. macOS** — 코드 편집·디버깅, Gazebo 시뮬, control_service / admin_ui / customer_web 모두 로컬 실행 가능
- **B. Ubuntu 24.04 노트북 (x86_64)** — 동일하게 서버 / UI / 시뮬 전부 실행 (배포 타겟)
- **C. Raspberry Pi 5 (ARM64)** — 실물 로봇

## A. macOS (RoboStack / conda)

> RoboStack의 ros-jazzy-* 의존성 그래프가 매우 커서 단일 `mamba env create`로 모든 패키지를
> 한 번에 resolve 시 호환 조합을 못 찾는 경우가 잦다. 부트스트랩 env를 먼저 만들고
> 단계별로 `mamba install`하는 것이 안전하다.

```bash
# A.1 prereq — Homebrew 가 깔려 있다고 가정
brew install --cask miniforge
conda init zsh                        # 새 터미널 열기 필요
conda install -n base -c conda-forge mamba

# A.2 부트스트랩 env 생성 (python + pip + mamba 만)
cd ~/shoppinkki
mamba env create -f environment.yml -n jazzy
mamba activate jazzy

# A.3 채널 우선순위 strict (RoboStack 호환)
conda config --env --set channel_priority strict

# A.4 ROS 2 Jazzy — distro mutex 먼저 핀 (호환 빌드 세트 anchor)
mamba install -y ros2-distro-mutex=0.14.0
mamba install -y ros-jazzy-desktop
mamba install -y \
    ros-jazzy-nav2-bringup \
    ros-jazzy-slam-toolbox \
    ros-jazzy-tf-transformations \
    ros-jazzy-rmw-cyclonedds-cpp

# A.5 Gazebo Harmonic
mamba install -y ros-jazzy-ros-gz ros-jazzy-gz-ros2-control

# A.6 GUI / DB / 빌드 도구
mamba install -y psycopg2 colcon-common-extensions cmake pkg-config
# PyQt5는 ros-jazzy-python-qt-binding / ros-jazzy-qt-gui (rqt 등)의 의존성으로 자동 설치됨

# A.7 비-ROS Python (pip)
pip install transitions flask flask-socketio "qrcode[pil]"

# A.8 (옵션) AI 의존성 추가 — torch/ultralytics 등 ~5GB
mamba env update -n jazzy -f environment-ai.yml

# A.9 워크스페이스 빌드 (py_trees_ros 등 submodule도 함께 빌드됨)
colcon build --symlink-install
source install/setup.zsh

# A.10 검증
ros2 run demo_nodes_cpp talker        # "Hello World: N" 출력 확인 후 Ctrl+C
```

> 한계: ROS 2 Jazzy는 macOS 공식 지원이 아님. 미해결 의존성 만나면 `mamba install <패키지>`로 보충. 시뮬은 conda-forge `gz-sim8` (Gazebo Harmonic) 기반으로 동작 검증됨.

## B. Ubuntu 24.04 노트북 (서버/UI/시뮬용, x86_64)

```bash
# B.1 locale
sudo apt update && sudo apt install -y locales
sudo locale-gen en_US en_US.UTF-8
sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8

# B.2 ROS 2 Jazzy apt 저장소 추가
sudo apt install -y software-properties-common curl
sudo add-apt-repository universe
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
     -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" \
   | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null

# B.3 ROS 설치 + 도구
sudo apt update
sudo apt install -y \
    ros-jazzy-desktop \
    python3-rosdep \
    python3-colcon-common-extensions \
    python3-pip

# B.4 rosdep 초기화 (1회만)
sudo rosdep init
rosdep update

# B.5 워크스페이스 ROS 의존성
cd ~/shoppinkki
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y

# B.6 비-ROS pip 의존성
pip install -r requirements.txt

# B.7 (옵션) AI 직접 실행 시 (보통은 scripts/run_ai.sh의 Docker 사용)
pip install -r requirements-ai.txt

# B.8 워크스페이스 빌드 (py_trees_ros 등 submodule도 함께 빌드됨)
colcon build --symlink-install
source install/setup.bash

# B.9 검증
bash scripts/run_server.sh           # tmux 세션 정상 기동 확인
```

## C. Raspberry Pi 5 (실물 로봇, ARM64)

```bash
# C.1 prereq — Pinky Pro 위키 "초기설정"을 따라 OS 이미지 + 기본 환경 셋업
#     https://github.com/pinklab-art/pinky_study/wiki

# C.2 ROS 2 Jazzy 설치 — B.1 ~ B.4 동일

# C.3 LiDAR udev 규칙 (RPLiDAR 인식)
cd ~/shoppinkki
bash device/sllidar_ros2/scripts/create_udev_rules.sh
sudo udevadm control --reload-rules && sudo udevadm trigger

# C.4 ROS 의존성 (B.5와 동일)
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y

# C.5 Pi 전용 Python 의존성 — robot.requirements.txt 사용
pip install -r robot.requirements.txt

# C.6 워크스페이스 빌드
#     pinky_lamp_control, pinky_led 는 ARM64에서 자동 빌드됨
colcon build --symlink-install
source install/setup.bash

# C.7 ROBOT_ID 영구화
echo 'export ROBOT_ID=54' >> ~/.zshrc    # 18번 로봇이면 18로

# C.8 검증
bash scripts/run_robot.sh 54
```

## 트러블슈팅 (공통)

| 증상 | 원인 / 해결 |
|---|---|
| `rosdep: cannot resolve [<key>]` | OS-specific 매핑 누락 → 직접 설치 (Ubuntu: `apt install python3-<key>`, macOS: `mamba install <key>`) |
| macOS Qt 플러그인 에러 (`could not find QPA platform plugin`) | `_ros_env.sh`가 자동 처리 — 항상 `scripts/run_*.sh`로 실행 |
| DDS discovery 실패 (다른 머신/노드에서 토픽 안 보임) | 모든 노드의 `ROS_DOMAIN_ID` 동일한지(`echo $ROS_DOMAIN_ID`), `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`인지 확인 |
| `py_trees_ros` 모듈 못 찾음 | submodule 초기화 누락 — `git submodule update --init --recursive` 후 `colcon build` 재실행 |
| macOS에서 `mamba install ros-jazzy-X` resolution 실패 | `ros2-distro-mutex=0.14.0`을 먼저 핀했는지 확인. 그래도 실패 시 `--strict-channel-priority` 추가 |

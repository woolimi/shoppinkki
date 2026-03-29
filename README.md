# 🛒 Smart Cart Pro (Pinky) - Decoupled Offload Tracking Architecture

## 📌 프로젝트 소개 (Overview)
본 프로젝트는 **자율 로봇 '핑키(Pinky)'가 주인을 빠르고 안전하게 따라가도록 설계된 AI 비전 트래킹 오프로딩 시스템**입니다. 

초소형 컴퓨터(라즈베리파이)가 무거운 AI 모델을 직접 계산하느라 발열이나 끊김 현상이 발생하던 구조를 타파하고, 무거운 **딥러닝 AI 계산(YOLO, MediaPipe, ReID)**을 사양이 좋은 **PC 서버로 100% 오프로딩(Offloading)**하여 로봇 자체의 수명을 보호하는 동시에 추적 성능을 비약적으로 끌어올렸습니다.

## ✨ 핵심 파이프라인 (ROS 2 패키지 구조)
이 거대한 저장소는 철저한 분업 철학을 바탕으로 **2개의 핵심 패키지**로 완벽하게 쪼개져 있습니다.

### 1. `pinky_vision_streamer` (로봇/핑키에만 설치)
* **역할:** 카메라 렌즈의 원본 영상을 초고속(15FPS)으로 가볍게 압축해 PC로 쏘고, PC가 역으로 보내준 "목표 좌표"를 찰떡같이 받아들여 실제 바퀴 모터를 굴립니다. AI 연산을 `1`도 하지 않으므로 라즈베리파이에 부담이 "0%"입니다.
* **노드:** `camera_publisher`, `motor_controller`
   
### 2. `pinky_offload_vision` (서버/데스크탑 PC에만 설치)
* **역할:** 로봇이 보내준 영상을 분석하여 사람을 찾고(`YOLOv8 BoT-SORT`), 특정 주인을 뼈대 수준으로 정밀하게 등록/식별(`MediaPipe` & `Color ReID`)한 뒤, 거리를 추정하여 로봇에게 "돌아라/가까이 와라" 좌표 정보(`/tracker/target_position`)를 다시 보냅니다. 더불어 실시간 웹 브라우저 대시보드를 제공합니다.
* **노드:** `server_tracker_node`, `web_viewer_node`

---

## 🚀 빠른 시작 가이드 (Quick Start)

> **[필수 세팅 체크]**
> 로봇(핑키)과 노트북(PC)은 **같은 와이파이(동일 네트워크)**에 연결되어 있어야 하며, 서로 무전을 치기 위해 터미널에 `export ROS_DOMAIN_ID=14` 값이 양쪽 모두 동일하게 맞춰져 있어야 합니다!

### 1️⃣ 서버 (PC/노트북) 세팅
PC의 빵빵한 그래픽/연산 성능을 이용해 핑키 대신 뇌(AI) 역할을 전담합니다.

```bash
# 1. 필수 AI 라이브러리 설치
pip install mediapipe ultralytics

# 2. 패키지 다운로드 및 빌드
cd ~/ros_ws/src
git clone https://github.com/Minssuung/pinky_project.git shoppinkki
cd ~/ros_ws
colcon build --packages-select pinky_offload_vision

# 3. AI 서버 실행 및 대기! (웹 뷰어 활성화)
source install/local_setup.bash
ros2 launch pinky_offload_vision offload.launch.py
```

### 2️⃣ 로봇 (핑키/라즈베리파이) 세팅
핑키는 오직 영상 송출과 모터 회전(몸 쓰기)만 맡습니다.

```bash
# 1. 패키지 다운로드 및 빌드
cd ~/ros_ws/src
git clone https://github.com/Minssuung/pinky_project.git shoppinkki
cd ~/ros_ws
colcon build --packages-select pinky_vision_streamer
source install/local_setup.bash

# 2. 로봇의 기본 바퀴 전원 및 모터 통신망 켜기 (터미널 창 1)
ros2 launch pinky_bringup bringup_robot.launch.xml

# 3. 카메라 방송국 및 행동대장(모터 제어기) 가동 (터미널 창 2)
ros2 run pinky_vision_streamer camera_publisher &
ros2 run pinky_vision_streamer motor_controller
```

---

## 📸 주인을 외우는 방법 (Calibration)

PC(서버)에서 AI 런치 파일을 켜셨다면, 같은 와이파이를 쓰는 노트북이나 스마트폰에서 **웹 브라우저(크롬, 사파리 등)**를 열고 아래 주소로 접속하세요!
> 보통 `http://localhost:5002` 또는 핑키 주소가 보입니다.

1. 화면 왼쪽 위 **`📸 캘리브레이션 시작`** 버튼을 클릭합니다.
2. 초록색 바가 뜨면서 카메라 앞에 선 사람의 뼈대(미디어파이프)를 스캔하기 시작합니다.
3. 안내 순서에 따라 **정면 👉 (살짝 턴) 우측면 👉 후면 👉 좌측면**을 차례대로 딱 멈춰서 바라봐 주시면, 로봇이 현재 입고 있는 **상/하의 옷의 색감(ReID)**과 뼈대의 깊이값(`z`)을 매칭하여 로봇 두뇌 하드디스크(`owner_server_template.pkl`)에 영구 저장합니다.
4. 이제 화면 밖으로 완전히 피했다가 다시 나타나도 로봇이 주인을 `OWNER` 라고 알아보며 반갑게 고개를 돌릴 것입니다! (기억을 잃어버리게 하려면 빨간 `Clear` 버튼을 누르시면 됩니다)

---

## ⚠️ 자율주행 안전 설정 (거리 조절 파라미터)

**안전 제일주의**를 위해 첫 설치 시에는 "제자리 양옆 회전(Rotation)" 기능만 켜져 있고, 물건을 부딪히거나 위험하게 다가올 수 있는 **직진/후진(Follow) 빙의 모드는 잠금(Disabled)** 처리되어 있습니다.

넓고 통제된 안전한 곳에서 로봇이 주인을 완벽히 쫓아오게 만들고 싶다면:
1. 로봇(핑키)의 코드를 엽니다: `src/shoppinkki/pinky_vision_streamer/pinky_vision_streamer/motor_controller.py`
2. `self.declare_parameter('enable_follow', False)` 항목을 찾아 **`True`**로 바꿉니다.
3. 거리 조정이 필요하다면 `target_ratio` (화면에 주인이 50%를 꽉 채울 때 대기) 및 `kp_x` (전/후진 민감도)를 조정합니다.
4. 다시 `colcon build` 해주시면 로봇이 주인이 도망가면 쫓아가고, 너무 다가오면 알아서 멈추거나 슬금슬금 뒤로 물러나는 완벽한 스마트 카트로 변신합니다. 🚀
 
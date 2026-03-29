# ShopPinkki

## 1. 개요 (Overview)

## 2. 아키텍처 및 패키지 구성
네트워크 도메인을 통해 분할된 2개의 ROS 2 패키지로 구성됩니다.

### 2.1 `pinky_vision_streamer` (로봇 / 라즈베리파이 전용)
- **`camera_publisher_node`**: V4L2 카메라 프레임을 JPEG 압축하여 15 FPS로 스트리밍합니다.
- **`motor_controller_node`**: `/tracker/target_position` 좌표를 받아 비례 제어(P-Control)로 `cmd_vel`을 발행합니다. 통신 단절 시 자동 정지 타임아웃이 내장되어 있습니다.

### 2.2 `pinky_offload_vision` (PC / 서버 전용)
- **`server_tracker_node`**: YOLOv8 BoT-SORT 인물 추적 및 색상 기반 ReID로 주인을 식별하고 좌표를 발행합니다.
- **`web_viewer_node`**: Flask 기반 웹 대시보드를 호스팅하여 실시간 영상 피드와 캘리브레이션 UI를 제공합니다.

## 3. 설치 및 환경 구성 (Installation)
**요구 사항:** Ubuntu 24.04, ROS 2 Jazzy, Python 3.12+

PC에 AI 라이브러리를 먼저 설치합니다.
```bash
pip install ultralytics mediapipe
```

PC와 라즈베리파이 **양측 모두** 동일한 ROS 도메인을 사용해야 합니다. `.zshrc`에 추가하거나 실행 전 매번 입력합니다.
```bash
export ROS_DOMAIN_ID=14
```

양측 워크스페이스에 저장소를 클론합니다.
```zsh
cd ~/ros_ws/src
git clone https://github.com/woolimi/shoppinkki.git
cd ~/ros_ws
```

## 4. 구동 방법 (Usage)

> **실행 순서**: PC 서버 → 핑키(라즈베리파이) 순으로 실행합니다.

### 4.1 PC (서버) 실행
```zsh
cd ~/ros_ws
colcon build --packages-select pinky_offload_vision --base-paths src/shoppinkki
source install/local_setup.zsh

ros2 launch pinky_offload_vision offload.launch.py
```
성공하면 터미널에 `🌐 WEB VIEWER READY`가 출력됩니다.
브라우저에서 `http://localhost:5002` 접속하면 웹 대시보드가 나타납니다.

### 4.2 라즈베리파이 (로봇) 실행
**터미널 1** - 로봇 하드웨어 초기화:
```zsh
cd ~/ros_ws
colcon build --packages-select pinky_vision_streamer --base-paths src/shoppinkki
source install/local_setup.zsh

ros2 launch pinky_bringup bringup_robot.launch.xml
```

**터미널 2** - 카메라 스트리머 및 모터 제어기 구동:
```zsh
cd ~/ros_ws && source install/local_setup.zsh

ros2 run pinky_vision_streamer camera_publisher &
ros2 run pinky_vision_streamer motor_controller
```

## 5. 주인 등록 캘리브레이션 (Calibration)
추적을 시작하려면 먼저 주인의 외형을 시스템에 등록해야 합니다.

1. PC 웹 브라우저에서 `http://localhost:5002` 접속
2. **`📸 캘리브레이션 시작`** 버튼 클릭
3. 화면 안내에 따라 **정면 → 우측면 → 후면 → 좌측면** 순서로 멈춰 서서 스캔 대기
4. 완료 후 `[OWNER]` 초록색 박스가 표시되며 추적이 시작됩니다

> 등록된 주인 정보는 `owner_server_template.pkl`로 저장되어, 다음 실행 시 재캘리브레이션 없이 바로 추적을 시작합니다.
> 초기화하려면 🗑️ **`소유자 초기화`** 버튼을 클릭합니다.

## 6. 파라미터 튜닝 (Parameters)
`motor_controller.py`의 파라미터를 수정하여 동작을 조정할 수 있습니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `enable_follow` | bool | `False` | 전진/후진 거리 추적 활성화. `True`로 변경 시 주인과의 거리를 유지하며 따라옵니다. |
| `target_ratio` | float | `0.5` | 주인의 바운딩 박스가 화면 높이 대비 차지할 목표 비율 (거리 기준값) |
| `deadzone_x` | float | `0.07` | 수평 방향 오차 허용 범위 (작을수록 민감하게 회전) |
| `kp_z` | float | `1.5` | 회전 비례 제어 상수 (Yaw) |
| `kp_x` | float | `0.5` | 전/후진 비례 제어 상수 (Linear) |
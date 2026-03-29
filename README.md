# ShopPinkki

## 1. 개요 (Overview)
ShopPinkki

## 2. 아키텍처 및 패키지 구성
네트워크 도메인을 통해 분할된 2개의 ROS 2 패키지로 구성되어 있습니다.

### 2.1 `pinky_vision_streamer` (로봇 / 엣지 디바이스)
로봇 하드웨어에 네이티브로 실행되어 영상 획득, 영상 압축 및 모터 제어를 담당합니다.
- **`camera_publisher_node`**: V4L2 기반 카메라 프레임을 읽어와 페이로드 최적화 후 초당 15프레임(FPS)으로 스트리밍합니다.
- **`motor_controller_node`**: 수신된 `/tracker/target_position` 목표 좌표를 기반으로 비례 제어(P-Control)를 수행하여 `geometry_msgs/msg/Twist` 명령을 생성합니다. 모터 런어웨이를 방지하는 하드웨어 안전 핑, 타임아웃 방어 로직이 포함되어 있습니다.

### 2.2 `pinky_offload_vision` (PC / 원격 서버)
수신된 카메라 스트림을 멀티스레드 기반의 딥러닝 엔진을 거쳐 분석합니다.
- **`server_tracker_node`**: 프레임 단위의 BoT-SORT 인물 탐지 및 상관관계(Correlation) 기반 ReID 검증을 수행합니다. 타겟 식별 시, 로봇 조향을 위한 2D 데카르트 상대 좌표 및 거리 지표(`Point`)를 발행합니다.
- **`web_viewer_node`**: 임베디드 Flask 애플리케이션을 호스팅하여 원격 영상 피드, Bounding Box 렌더링, 캘리브레이션 API 엔드포인트를 제공합니다.

## 3. 설치 및 환경 구성 (Installation)
**요구 사항:** Ubuntu 24.04, ROS 2 Jazzy, Python 3.12+, `ultralytics`, `mediapipe`

아키텍처 통합을 위해 PC와 라즈베리파이가 동일한 네트워크 도메인 위에 구성되어야 합니다.
```zsh
export ROS_DOMAIN_ID=14
```

양측(PC, 로봇)의 워크스페이스에 저장소를 동기화합니다.
```zsh
cd ~/ros_ws/src
git clone https://github.com/woolimi/shoppinkki.git
cd ~/ros_ws
```

## 4. 구동 방식 (Usage)

### 4.1 서버 노드 실행 (PC)
```zsh
colcon build --symlink-install --packages-select pinky_offload_vision --base-paths src/shoppinkki
source install/local_setup.zsh

ros2 launch pinky_offload_vision offload.launch.py
```

### 4.2 엣지 노드 실행 (Raspberry Pi)
```zsh
colcon build --symlink-install --packages-select pinky_vision_streamer --base-paths src/shoppinkki
source install/local_setup.zsh

# 1. 로봇 하드웨어 시스템 제어 권한 획득
ros2 launch pinky_bringup bringup_robot.launch.xml

# 2. 비전 스트리머 및 모터 제어 백그라운드 노드 구동
ros2 run pinky_vision_streamer camera_publisher &
ros2 run pinky_vision_streamer motor_controller
```

## 5. 타겟 캘리브레이션 (Calibration)
추적 알고리즘 활성화를 위해 사전에 오너(Owner)의 공간적 / 색상적 지표가 메모리에 인젝션되어야 합니다.
1. 웹 브라우저를 통해 `http://<SERVER_IP>:5002` 포트에 접속합니다.
2. 대시보드의 `/calibrate` (캘리브레이션 시작) 버튼을 요청합니다.
3. 랜드마크 추출 모드가 활성화 시, 화상 GUI가 요구하는 시퀀스(전면, 우측면, 후면, 좌측면)으로 대기를 유지하여 상/하체의 HSV 특징 지표(Color Extraction)를 저장합니다.
4. 타겟 인식이 완료되면 데이터 직렬화 페이로드(`owner_server_template.pkl`)를 통해 프로그램 재가동 시에도 항구적 식별이 보장됩니다.

## 6. 제어 파라미터 튜닝 (Parameters)
모션 알고리즘의 동작 한계선은 `motor_controller.py`의 파라미터를 통해 직접 제어가 가능합니다.
- `enable_follow` (bool): 선속도(Linear X) 기반 주행 추적 및 거리 유지 활성화 플래그. False 세팅 시 '시야 조향 전용(Rotation Only)' 모드로 가동. 기본값: `False`.
- `target_ratio` (float): 목표 BBox가 화면 전체 높이 대비 차지해야 할 임계 비율 (Z축 거리 유지용 기준값). 기본값: `0.5`.
- `deadzone_x / deadzone_z` (float): 노이즈가 반영되지 않는 오차 한계값.
- `kp_z` (float): 조향각 오차 보정 비례 제어 상수 (Yaw).
- `kp_x` (float): 전/후진 거리 오차 보정 비례 제어 상수 (Linear).
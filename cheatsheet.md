## 맵만들기

시뮬레이션의 경우

```bash
ros2 launch pinky_gz_sim launch_sim_shop.launch.xml
ros2 launch pinky_navigation gz_map_building.launch.xml
# teleop keyboard
ros2 run teleop_twist_keyboard teleop_twist_keyboard
# rviz
ros2 launch pinky_navigation gz_map_view.launch.xml
```

실물 로봇의 경우

```bash
# [Pinky]
## 로봇 설명(URDF), 라이다, 베이스 컨트롤러, 오도메트리 등 실제 로봇에 필요한 노드들을 띄웁니다
ros2 launch pinky_bringup bringup_robot.launch.xml
## slam_toolbox를 켜서 /scan과 TF로 맵을 만들고 /map을 퍼블리시합니다.
ros2 launch pinky_navigation map_building.launch.xml

# [PC]
## RViz를 실행해 SLAM으로 생성되는 /map 토픽을 실시간으로 확인합니다.
ros2 launch pinky_navigation map_view.launch.xml
# 키보드로 로봇을 수동 조종해 지도에 미탐색 구역을 채웁니다.
ros2 run teleop_twist_keyboard teleop_twist_keyboard
# 현재 /map 토픽을 파일로 저장합니다. (예: my_map -> my_map.yaml, my_map.pgm)
ros2 run nav2_map_server map_saver_cli -f "<저장할 맵이름>"
```

[맵을 수정해주는 웹앱](https://gyropalm.github.io/ROS-SLAM-Map-Editor/editor.html)

```bash
## 생성한 월드로 시뮬 실행
ros2 launch pinky_gz_sim launch_sim_shop.launch.xml
```

## 네비게이션

시뮬레이션의 경우
```bash
ros2 launch pinky_gz_sim launch_sim_shop.launch.xml
ros2 launch pinky_navigation gz_bringup_launch.xml map:=src/pinky_pro/pinky_navigation/map/shop.yaml
ros2 launch pinky_navigation gz_nav2_view.launch.xml
```

실물 로봇의 경우

```bash
# [Pinky]
## 로봇 설명(URDF), 라이다, 베이스 컨트롤러, 오도메트리 등 실제 로봇에 필요한 노드들을 띄웁니다
ros2 launch pinky_bringup bringup_robot.launch.xml

# 저장한 정적 맵(yaml)을 로드해 localization + navigation(Nav2) 스택을 실행합니다.
ros2 launch pinky_navigation bringup_launch.xml map:=src/pinky_pro/pinky_navigation/map/shop.yaml

# [PC]
# RViz를 실행해 로봇 위치, 코스트맵, 계획 경로를 시각화하고 목표를 줄 수 있습니다.
ros2 launch pinky_navigation nav2_view.launch.xml

# 2D Pose Estimate 버튼을 눌러 라이다와 맵 일치 시켜주기
# Nav2 Goal을 클릭하고 이동
```

## 멀티로봇 시뮬레이션 (Gazebo)

```bash
# 전체 스택 실행 (서버 + UI + Gazebo + Nav2 x2 + core x2)
bash scripts/run_server.sh      # 터미널 A
bash scripts/run_ui.sh          # 터미널 B
bash scripts/run_sim.sh         # 터미널 C
```

Gazebo 로딩 완료(~60초) 후:
1. admin_ui에서 각 로봇 **[위치 초기화]** 클릭
2. customer_web `http://localhost:8501/?robot_id=54` 로그인

```bash
# 멀티로봇 launch 단독 실행 (디버깅용)
ros2 launch shoppinkki_nav gz_multi_robot.launch.py

# RViz 멀티로봇 뷰
ros2 launch shoppinkki_nav multi_robot_rviz.launch.py

# 네임스페이스별 토픽 확인
ros2 topic echo /robot_54/scan
ros2 topic echo /robot_18/odom
ros2 topic echo /robot_54/amcl_pose
```

### 시뮬 트러블슈팅

```bash
# 좀비 프로세스 정리 (run_sim.sh가 자동으로 하지만 수동 필요 시)
pkill -f "gz sim"; pkill -f "gz_sim"; sleep 2; pkill -9 -f "gz sim"

# Gazebo clock 확인 (use_sim_time 동작 여부)
ros2 topic echo /clock --once

# Nav2 lifecycle 상태 확인
ros2 lifecycle get /robot_54/controller_server
ros2 lifecycle get /robot_54/amcl
```

## 맵상의 좌표 얻기

###  클릭한 부분의 좌표를 얻는법

```bash
# clicked_point 토픽을 구독
ros2 topic echo /clicked_point
# 이후 rviz의 publish point 이용, rviz 상 좌표 클릭
```

### 로봇의 현재 좌표를 얻는 법

```bash 
ros2 topic echo /amcl_pose
```

## Waypoint

1. waypoint 클릭
2. nav2 goal 을 이용해서 waypoint 추가
3. start waypoint following

## Pinky 와이파이 접속 설정 안될때

```bash
nmcli device wifi list

# 원하는 와이파이가 안 뜰 경우
sudo nmcli device wifi rescan 
nmcli device wifi list

# 특정 와이파이를 지워버리고 싶을때
sudo nmcli connection delete "addinedu_201class_2-5G"
```

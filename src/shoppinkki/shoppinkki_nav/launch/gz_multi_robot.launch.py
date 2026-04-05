"""멀티로봇 Gazebo 통합 launch — 로봇 54, 18번 동시 시뮬레이션.

구성:
    - Gazebo world (server + GUI): shop.world 1회 실행
    - 로봇 54: 스폰(0.939, 0.120, yaw=90°) + 브리지 + Nav2(namespace=robot_54)
    - 로봇 18: 스폰(0.699, 0.120, yaw=90°) + 브리지 + Nav2(namespace=robot_18)

사용법:
    ros2 launch shoppinkki_nav gz_multi_robot.launch.py
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    IncludeLaunchDescription,
    SetEnvironmentVariable,
    TimerAction,
)
from launch.launch_description_sources import (
    AnyLaunchDescriptionSource,
    PythonLaunchDescriptionSource,
)
from launch_ros.actions import Node


# ── 패키지 경로 ────────────────────────────────────────────────────────────────
PINKY_GZ = get_package_share_directory('pinky_gz_sim')
PINKY_NAV = get_package_share_directory('pinky_navigation')
PINKY_DESC = get_package_share_directory('pinky_description')
SHOPPINKKI_NAV = get_package_share_directory('shoppinkki_nav')

MAP_YAML = os.path.join(
    get_package_share_directory('pinky_navigation'), 'map', 'shop.yaml'
)
WORLD_FILE = os.path.join(PINKY_GZ, 'worlds', 'shop.world')

# ── 로봇 설정 ──────────────────────────────────────────────────────────────────
ROBOTS = [
    {
        'id': '54',
        'ns': 'robot_54',
        'model': 'pinky_54',
        # Gazebo 스폰 좌표 (Gazebo world frame)
        'x': '0.939', 'y': '0.120', 'z': '0.0',
        'yaw': '1.570796',
        # 맵 프레임 좌표 (static TF + AMCL 초기 pose용)
        'map_x': '0.020', 'map_y': '-0.282', 'map_yaw': '0.0',
    },
    {
        'id': '18',
        'ns': 'robot_18',
        'model': 'pinky_18',
        # Gazebo 스폰 좌표 (Gazebo world frame)
        'x': '0.699', 'y': '0.120', 'z': '0.0',
        'yaw': '1.570796',
        # 맵 프레임 좌표 (static TF + AMCL 초기 pose용)
        'map_x': '0.023', 'map_y': '-0.042', 'map_yaw': '0.0',
    },
]


def make_robot_actions(robot: dict, delay: float) -> list:
    """한 로봇에 대한 launch action 목록 생성 (스폰 + 브리지 + Nav2)."""
    ns = robot['ns']
    bridge_yaml = os.path.join(SHOPPINKKI_NAV, 'config', f'bridge_{ns}.yaml')
    nav2_params = os.path.join(SHOPPINKKI_NAV, 'config', f'nav2_params_{ns}.yaml')

    # 1) 로봇 description 업로드 (robot_state_publisher 포함)
    upload = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(PINKY_DESC, 'launch', 'upload_robot.launch.py')
        ),
        launch_arguments={
            'namespace': ns,
            'use_sim_time': 'True',
            'is_sim': 'True',
            'cam_tilt_deg': '0',
        }.items(),
    )

    # 2) Gazebo에 로봇 스폰
    spawn = Node(
        package='ros_gz_sim',
        executable='create',
        name=f'spawn_{ns}',
        arguments=[
            '-name', robot['model'],
            '-topic', f'{ns}/robot_description',
            '-x', robot['x'],
            '-y', robot['y'],
            '-z', robot['z'],
            '-Y', robot['yaw'],
        ],
        parameters=[{'use_sim_time': True}],
        output='screen',
    )

    # 3) ROS-Gazebo 브리지 (토픽 네임스페이스 매핑)
    bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        name=f'bridge_{ns}',
        arguments=['--ros-args', '-p', f'config_file:={bridge_yaml}'],
        parameters=[{'use_sim_time': True}],
        output='screen',
    )

    # 3.5) map → <ns>/odom 초기 static TF (AMCL 부트스트랩용)
    #      Gazebo world frame ≠ map frame 이므로 맵 좌표(map_x/y/yaw) 사용
    #      AMCL이 초기화되면 동적 TF로 자동 대체됨
    map_to_odom = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name=f'map_odom_{ns}',
        arguments=[
            '--x', robot['map_x'],
            '--y', robot['map_y'],
            '--z', '0',
            '--yaw', robot['map_yaw'],
            '--pitch', '0',
            '--roll', '0',
            '--frame-id', 'map',
            '--child-frame-id', f'{ns}/odom',
        ],
        parameters=[{'use_sim_time': True}],
        output='screen',
    )

    # 4) Nav2 스택 (gz_bringup_launch.xml 내부에서 namespace 처리됨)
    nav2 = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            os.path.join(PINKY_NAV, 'launch', 'gz_bringup_launch.xml')
        ),
        launch_arguments={
            'namespace': ns,
            'map': MAP_YAML,
            'params_file': nav2_params,
            'container_name': f'nav2_container_{ns}',
            'use_sim_time': 'True',
        }.items(),
    )

    # delay 적용 (두 번째 로봇은 첫 번째 이후에 스폰)
    actions = [upload, spawn, bridge, map_to_odom, nav2]
    if delay > 0:
        return [TimerAction(period=delay, actions=actions)]
    return actions


def generate_launch_description():
    # GZ_SIM_RESOURCE_PATH 설정 (모델 파일 탐색)
    set_gz_path = SetEnvironmentVariable(
        name='GZ_SIM_RESOURCE_PATH',
        value=(
            os.path.join(PINKY_DESC, '..') + ':'
            + os.path.join(PINKY_GZ, 'models') + ':'
            + os.path.expanduser('~/.gazebo/models')
        ),
    )

    # Gazebo 서버 (world 로드, GUI 없음)
    gz_server = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory('ros_gz_sim'),
                'launch', 'gz_sim.launch.py',
            )
        ),
        launch_arguments={'gz_args': f'-r -s -v4 {WORLD_FILE}'}.items(),
    )

    # Gazebo GUI (서버에 연결)
    gz_gui = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory('ros_gz_sim'),
                'launch', 'gz_sim.launch.py',
            )
        ),
        launch_arguments={'gz_args': '-g -v4'}.items(),
    )

    # 각 로봇 액션 생성 (로봇 18은 15초 딜레이 — 54번 Nav2 초기화 후 시작)
    robot_54_actions = make_robot_actions(ROBOTS[0], delay=0.0)
    robot_18_actions = make_robot_actions(ROBOTS[1], delay=15.0)

    return LaunchDescription([
        set_gz_path,
        gz_server,
        gz_gui,
        *robot_54_actions,
        *robot_18_actions,
    ])

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
    GroupAction,
    IncludeLaunchDescription,
    SetEnvironmentVariable,
    TimerAction,
)
from launch.launch_description_sources import (
    AnyLaunchDescriptionSource,
    PythonLaunchDescriptionSource,
)
from launch.substitutions import Command
from launch_ros.actions import Node, PushRosNamespace
from nav2_common.launch import RewrittenYaml


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
        # 맵 프레임 좌표 (static TF + AMCL 초기 pose용) — AMCL 수렴값으로 설정
        'map_x': '-0.056', 'map_y': '-0.899', 'map_yaw': '0.0',
    },
    {
        'id': '18',
        'ns': 'robot_18',
        'model': 'pinky_18',
        # Gazebo 스폰 좌표 (Gazebo world frame)
        'x': '0.699', 'y': '0.120', 'z': '0.0',
        'yaw': '1.570796',
        # 맵 프레임 좌표 (static TF + AMCL 초기 pose용)
        'map_x': '-0.056', 'map_y': '-0.606', 'map_yaw': '0.0',
    },
]


def make_robot_actions(robot: dict, delay: float) -> list:
    """한 로봇에 대한 launch action 목록 생성 (스폰 + 브리지 + Nav2)."""
    ns = robot['ns']
    bridge_yaml = os.path.join(SHOPPINKKI_NAV, 'config', f'bridge_{ns}.yaml')
    nav2_params_raw = os.path.join(SHOPPINKKI_NAV, 'config', f'nav2_params_{ns}.yaml')
    # YAML 키에 namespace prefix 추가 (controller_server → robot_XX/controller_server)
    # multi-robot 환경에서 /robot_XX/controller_server 노드가 params를 올바르게 매칭하도록
    nav2_params = RewrittenYaml(
        source_file=nav2_params_raw,
        root_key=ns,
        param_rewrites={},
        convert_types=True,
    )

    # 1) 로봇 description 업로드 (robot_state_publisher 포함)
    #    xacro_patch.sh: type="lidar" → type="gpu_lidar" 패치
    #    (Gazebo Harmonic 에서 type="lidar" 는 sensors system 에서 발행이 안 되는 버그)
    ns_slash = ns + '/'
    xacro_patch = os.path.join(SHOPPINKKI_NAV, '..', '..', '..', '..',
                               'src', 'shoppinkki', 'shoppinkki_nav',
                               'scripts', 'xacro_patch.sh')
    xacro_patch = os.path.normpath(xacro_patch)
    rsp_cmd = Command([
        xacro_patch + ' ',
        os.path.join(PINKY_DESC, 'urdf', 'robot.urdf.xacro'),
        f' namespace:={ns_slash} is_sim:=true cam_tilt_deg:=0',
    ])
    rsp = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        namespace=ns,
        parameters=[{
            'use_sim_time': True,
            'robot_description': rsp_cmd,
            'frame_prefix': ns_slash,
        }],
        output='screen',
    )
    jsp = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        name='joint_state_publisher',
        namespace=ns,
        parameters=[{
            'source_list': ['joint_states'],
            'rate': 20.0,
            'use_sim_time': True,
        }],
        output='screen',
    )
    upload = GroupAction([rsp, jsp])

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

    # 4) Nav2 스택 — localization + navigation 직접 호출 (component container 제거)
    #    gz_bringup_launch.xml 우회: component_container_isolated가 params를 먼저 로드해
    #    controller_server의 plugin 파라미터 매칭을 방해하는 문제 수정
    nav2 = GroupAction([
        PushRosNamespace(ns),
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(
                os.path.join(PINKY_NAV, 'launch', 'localization_launch.xml')
            ),
            launch_arguments={
                'namespace': ns,
                'map': MAP_YAML,
                'params_file': nav2_params,
                'use_sim_time': 'True',
            }.items(),
        ),
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(
                os.path.join(PINKY_NAV, 'launch', 'navigation_launch.xml')
            ),
            launch_arguments={
                'params_file': nav2_params,
                'use_sim_time': 'True',
                # lifecycle_manager_navigation이 localization 노드(map_server, amcl)를
                # 관리하려는 충돌 방지 — navigation 전용 노드만 명시
                'lifecycle_nodes': (
                    "['controller_server', 'smoother_server', 'planner_server',"
                    " 'behavior_server', 'bt_navigator',"
                    " 'waypoint_follower', 'velocity_smoother']"
                ),
            }.items(),
        ),
    ])

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

    # Gazebo (server + GUI 통합 — 분리 실행 시 서버 프로세스에 ogre2 렌더링 컨텍스트가
    # 없어 Sensors System이 초기화되지 않아 LIDAR/카메라 데이터가 발행되지 않는 문제 수정)
    gz = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory('ros_gz_sim'),
                'launch', 'gz_sim.launch.py',
            )
        ),
        launch_arguments={'gz_args': f'-r -v4 {WORLD_FILE}'}.items(),
    )

    # 각 로봇 액션 생성 (로봇 18은 15초 딜레이 — 54번 Nav2 초기화 후 시작)
    robot_54_actions = make_robot_actions(ROBOTS[0], delay=0.0)
    robot_18_actions = make_robot_actions(ROBOTS[1], delay=15.0)

    return LaunchDescription([
        set_gz_path,
        gz,
        *robot_54_actions,
        *robot_18_actions,
    ])

"""멀티로봇 Gazebo 통합 launch — 로봇 54, 18번 동시 시뮬레이션.

구성:
    - Gazebo world (server + GUI): shop.world 1회 실행
    - 로봇 54: 스폰(0.939, 0.120, yaw=90°) + 브리지 + Nav2(namespace=robot_54)
    - 로봇 18: 스폰(0.699, 0.120, yaw=90°) + 브리지 + Nav2(namespace=robot_18)

사용법:
    ros2 launch shoppinkki_nav gz_multi_robot.launch.py
"""

import os
import platform

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    ExecuteProcess,
    GroupAction,
    IncludeLaunchDescription,
    SetEnvironmentVariable,
    TimerAction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command
from launch_ros.actions import Node, PushRosNamespace
from nav2_common.launch import RewrittenYaml
from shoppinkki_nav.launch_utils import resolve_nav2_params, get_charger_pose, map_to_gazebo


# ── 패키지 경로 ────────────────────────────────────────────────────────────────
PINKY_GZ = get_package_share_directory('pinky_gz_sim')
PINKY_NAV = get_package_share_directory('pinky_navigation')
PINKY_DESC = get_package_share_directory('pinky_description')
SHOPPINKKI_NAV = get_package_share_directory('shoppinkki_nav')

MAP_YAML = os.path.join(SHOPPINKKI_NAV, 'maps', 'shop.yaml')
WORLD_FILE = os.path.join(PINKY_GZ, 'worlds', 'shop.world')

# ── 로봇 설정 (충전소 좌표는 DB/fallback에서 자동 취득) ─────────────────────
def _build_robots() -> list[dict]:
    robots = []
    for rid, model_name in [('54', 'pinky_54'), ('18', 'pinky_18')]:
        ns = f'robot_{rid}'
        pose = get_charger_pose(rid)
        gz = map_to_gazebo(pose['x'], pose['y'], pose['yaw'])
        robots.append({
            'id': rid,
            'ns': ns,
            'model': model_name,
            'x': str(round(gz['x'], 4)),
            'y': str(round(gz['y'], 4)),
            'z': '0.0',
            'yaw': str(round(gz['yaw'], 6)),
            'map_x': str(pose['x']),
            'map_y': str(pose['y']),
            'map_yaw': str(pose['yaw']),
        })
    return robots


ROBOTS = _build_robots()


def make_robot_actions(robot: dict, delay: float) -> list:
    """한 로봇에 대한 launch action 목록 생성 (스폰 + 브리지 + Nav2)."""
    ns = robot['ns']
    bridge_yaml = os.path.join(SHOPPINKKI_NAV, 'config', f'bridge_{ns}.yaml')
    template = os.path.join(SHOPPINKKI_NAV, 'config', 'nav2_params.yaml')
    resolved = resolve_nav2_params(template, ns, robot['id'])
    nav2_params = RewrittenYaml(
        source_file=resolved,
        root_key=ns,
        param_rewrites={},
        convert_types=True,
    )

    # 1) 로봇 description 업로드 (robot_state_publisher 포함)
    #    xacro_patch.sh: type="lidar" → type="gpu_lidar" 패치
    #    (Gazebo Harmonic 에서 type="lidar" 는 sensors system 에서 발행이 안 되는 버그)
    ns_slash = ns + '/'
    xacro_patch = os.path.join(SHOPPINKKI_NAV, '..', '..', '..', '..',
                               'device', 'shoppinkki', 'shoppinkki_nav',
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
    # joint_state_publisher 불필요 — Gazebo bridge가 /<ns>/joint_states 발행,
    # robot_state_publisher가 구독하여 바퀴 TF 발행.
    # JSP를 같이 쓰면 타이밍 불일치로 TF_OLD_DATA 경고 대량 발생.
    upload = GroupAction([rsp])

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

    # 4) Nav2 전체 스택 — 단일 lifecycle_manager 로 순차 activate
    #    localization(map_server, amcl) → navigation(controller, planner, ...) 순서 보장
    sim_params = [nav2_params, {'use_sim_time': True}]
    bt_xml_dir = os.path.join(PINKY_NAV, 'behavior_trees')

    nav2 = GroupAction([
        PushRosNamespace(ns),

        # ── Localization ──
        Node(package='nav2_map_server', executable='map_server', name='map_server',
             output='screen', parameters=[*sim_params, {'yaml_filename': MAP_YAML}]),
        Node(package='nav2_amcl', executable='amcl', name='amcl',
             output='screen', parameters=sim_params),

        # ── Navigation ──
        Node(package='nav2_controller', executable='controller_server', output='screen',
             parameters=sim_params, remappings=[('cmd_vel', 'cmd_vel_nav')]),
        Node(package='nav2_smoother', executable='smoother_server', name='smoother_server',
             output='screen', parameters=sim_params),
        Node(package='nav2_planner', executable='planner_server', name='planner_server',
             output='screen', parameters=sim_params),
        Node(package='nav2_behaviors', executable='behavior_server', name='behavior_server',
             output='screen', parameters=sim_params),
        Node(package='nav2_bt_navigator', executable='bt_navigator', name='bt_navigator',
             output='screen', parameters=[*sim_params, {
                 'default_nav_to_pose_bt_xml':
                     os.path.join(bt_xml_dir, 'navigate_to_pose_no_backup.xml'),
                 'default_nav_through_poses_bt_xml':
                     os.path.join(bt_xml_dir, 'navigate_through_poses_no_backup.xml'),
             }]),
        Node(package='nav2_waypoint_follower', executable='waypoint_follower',
             name='waypoint_follower', output='screen', parameters=sim_params),
        Node(package='nav2_velocity_smoother', executable='velocity_smoother',
             name='velocity_smoother', output='screen', parameters=sim_params,
             remappings=[('cmd_vel', 'cmd_vel_nav'), ('cmd_vel_smoothed', 'cmd_vel_smoothed')]),
        Node(package='nav2_collision_monitor', executable='collision_monitor',
             name='collision_monitor', output='screen', parameters=sim_params),

        # ── 단일 lifecycle_manager: 리스트 순서대로 순차 activate ──
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
             name='lifecycle_manager', output='screen',
             parameters=[{
                 'use_sim_time': True,
                 'autostart': True,
                 'node_names': [
                     'map_server', 'amcl',                    # localization 먼저
                     'controller_server', 'smoother_server',  # navigation 이후
                     'planner_server', 'behavior_server',
                     'bt_navigator', 'waypoint_follower',
                     'velocity_smoother', 'collision_monitor',
                 ],
             }]),
    ])

    # delay 적용 (두 번째 로봇은 첫 번째 이후에 스폰)
    actions = [upload, spawn, bridge, nav2]
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

    # Gazebo 실행
    # macOS: server + GUI 동시 실행 불가 (gz-sim#44)
    #   → server(-s --headless-rendering) + GUI(-g) 분리
    # Linux: 통합 실행 (Sensors System이 ogre2 렌더링 컨텍스트 필요)
    _is_macos = platform.system() == 'Darwin'
    if _is_macos:
        gz_server = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(
                    get_package_share_directory('ros_gz_sim'),
                    'launch', 'gz_sim.launch.py',
                )
            ),
            launch_arguments={
                'gz_args': f'-s -r --headless-rendering -v4 {WORLD_FILE}',
                'on_exit_shutdown': 'true',
            }.items(),
        )
        gz_gui = ExecuteProcess(
            cmd=['gz', 'sim', '-g', '-v4'],
            output='screen',
        )
        gz_actions = [gz_server, gz_gui]
    else:
        gz = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(
                    get_package_share_directory('ros_gz_sim'),
                    'launch', 'gz_sim.launch.py',
                )
            ),
            launch_arguments={'gz_args': f'-r -v4 {WORLD_FILE}'}.items(),
        )
        gz_actions = [gz]

    # 각 로봇 액션 생성 (로봇 18은 15초 딜레이 — 54번 Nav2 초기화 후 시작)
    robot_54_actions = make_robot_actions(ROBOTS[0], delay=0.0)
    robot_18_actions = make_robot_actions(ROBOTS[1], delay=15.0)
    position_adjustment_bridge_yaml = os.path.join(
        SHOPPINKKI_NAV, 'config', 'bridge_position_adjustment.yaml'
    )
    position_adjustment_bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        name='bridge_position_adjustment',
        arguments=['--ros-args', '-p', f'config_file:={position_adjustment_bridge_yaml}'],
        parameters=[{'use_sim_time': True}],
        output='screen',
    )

    return LaunchDescription([
        set_gz_path,
        *gz_actions,
        position_adjustment_bridge,
        *robot_54_actions,
        *robot_18_actions,
    ])

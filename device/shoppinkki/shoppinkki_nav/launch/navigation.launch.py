"""Navigation launch file for ShopPinkki.

단일 lifecycle_manager 로 localization → navigation 순차 activate.

Starts:
    - map_server + amcl (localization)
    - controller_server, planner_server, ... (navigation)
    - lifecycle_manager (전체 순차 관리)

결제 구역 감지는 shoppinkki_core main_node 의 BoundaryMonitor 가 담당한다.

Namespace isolation:
    ROBOT_ID env var → robot_<id> namespace.
    Action server: /robot_<id>/navigate_to_pose

Usage:
    ROBOT_ID=54 ros2 launch shoppinkki_nav navigation.launch.py
    ROBOT_ID=18 ros2 launch shoppinkki_nav navigation.launch.py
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, PushRosNamespace
from nav2_common.launch import RewrittenYaml
from shoppinkki_nav.launch_utils import resolve_nav2_params


def generate_launch_description():
    pkg_share = get_package_share_directory('shoppinkki_nav')
    pinky_nav_dir = get_package_share_directory('pinky_navigation')

    robot_id = os.environ.get('ROBOT_ID', '')
    namespace = f'robot_{robot_id}' if robot_id else ''
    template = os.path.join(pkg_share, 'config', 'nav2_params.yaml')

    # 템플릿 __NS__ 치환 → RewrittenYaml(root_key) 로 노드 키 래핑
    resolved = resolve_nav2_params(template, namespace, robot_id) if namespace else template
    nav2_params = RewrittenYaml(
        source_file=resolved,
        root_key=namespace,
        param_rewrites={},
        convert_types=True,
    ) if namespace else resolved

    # ── Launch arguments ──────────────────────
    map_arg = DeclareLaunchArgument(
        'map',
        default_value=os.path.join(pkg_share, 'maps', 'shop.yaml'),
        description='Path to map yaml file',
    )
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Use simulation clock',
    )

    bt_xml_dir = os.path.join(pinky_nav_dir, 'behavior_trees')
    params = [nav2_params, {'use_sim_time': LaunchConfiguration('use_sim_time')}]

    # ── Nav2 전체 스택 + 단일 lifecycle_manager ──────────────────────────
    nav2 = GroupAction([
        PushRosNamespace(namespace),

        # Localization
        Node(package='nav2_map_server', executable='map_server', name='map_server',
             output='screen',
             parameters=[*params, {'yaml_filename': LaunchConfiguration('map')}]),
        Node(package='nav2_amcl', executable='amcl', name='amcl',
             output='screen', parameters=params),

        # Navigation
        Node(package='nav2_controller', executable='controller_server', output='screen',
             parameters=params, remappings=[('cmd_vel', 'cmd_vel_nav')]),
        Node(package='nav2_smoother', executable='smoother_server', name='smoother_server',
             output='screen', parameters=params),
        Node(package='nav2_planner', executable='planner_server', name='planner_server',
             output='screen', parameters=params),
        Node(package='nav2_behaviors', executable='behavior_server', name='behavior_server',
             output='screen', parameters=params),
        Node(package='nav2_bt_navigator', executable='bt_navigator', name='bt_navigator',
             output='screen', parameters=[*params, {
                 'default_nav_to_pose_bt_xml':
                     os.path.join(bt_xml_dir, 'navigate_to_pose_no_backup.xml'),
                 'default_nav_through_poses_bt_xml':
                     os.path.join(bt_xml_dir, 'navigate_through_poses_no_backup.xml'),
             }]),
        Node(package='nav2_waypoint_follower', executable='waypoint_follower',
             name='waypoint_follower', output='screen', parameters=params),
        Node(package='nav2_velocity_smoother', executable='velocity_smoother',
             name='velocity_smoother', output='screen', parameters=params,
             remappings=[('cmd_vel', 'cmd_vel_nav'), ('cmd_vel_smoothed', 'cmd_vel')]),

        # 단일 lifecycle_manager: localization → navigation 순차 activate
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
             name='lifecycle_manager', output='screen',
             parameters=[{
                 'use_sim_time': LaunchConfiguration('use_sim_time'),
                 'autostart': True,
                 'bond_timeout': 20.0,
                 'node_names': [
                     'map_server', 'amcl',
                     'controller_server', 'smoother_server',
                     'planner_server', 'behavior_server',
                     'bt_navigator', 'waypoint_follower',
                     'velocity_smoother',
                 ],
             }]),
    ])

    return LaunchDescription([
        map_arg,
        use_sim_time_arg,
        nav2,
    ])

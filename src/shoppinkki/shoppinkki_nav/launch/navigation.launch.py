"""Navigation launch file for ShopPinkki.

Starts:
    - map_server (with pre-built shop.yaml map)
    - nav2 full stack (AMCL + planners + controller + BT navigator)
    - lifecycle_manager_navigation (autostart=true)
    - lifecycle_manager_filter  (autostart=false — activated by BT5)
    - boundary_monitor node

Usage:
    ros2 launch shoppinkki_nav navigation.launch.py
    ros2 launch shoppinkki_nav navigation.launch.py map:=/path/to/map.yaml
"""

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    pkg_share = get_package_share_directory('shoppinkki_nav')
    nav2_bringup_dir = get_package_share_directory('nav2_bringup')

    robot_id = os.environ.get('ROBOT_ID', '')
    namespace = f'robot_{robot_id}' if robot_id else ''
    default_params = (
        os.path.join(pkg_share, 'config', f'nav2_params_robot_{robot_id}.yaml')
        if robot_id else
        os.path.join(pkg_share, 'config', 'nav2_params.yaml')
    )

    # ── Launch arguments ──────────────────────
    map_arg = DeclareLaunchArgument(
        'map',
        default_value=os.path.join(pkg_share, 'maps', 'shop.yaml'),
        description='Path to map yaml file',
    )
    params_arg = DeclareLaunchArgument(
        'params_file',
        default_value=default_params,
        description='Path to Nav2 params yaml',
    )
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Use simulation clock',
    )

    # ── Nav2 bringup ──────────────────────────
    nav2_bringup = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_bringup_dir, 'launch', 'bringup_launch.py')
        ),
        launch_arguments={
            'map': LaunchConfiguration('map'),
            'params_file': LaunchConfiguration('params_file'),
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'namespace': namespace,
            'use_namespace': 'true' if namespace else 'false',
            'use_composition': 'False',
        }.items(),
    )

    # ── BoundaryMonitor node ──────────────────
    boundary_monitor_node = Node(
        package='shoppinkki_nav',
        executable='boundary_monitor',
        name='boundary_monitor',
        output='screen',
        parameters=[{
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }],
        additional_env={
            'CONTROL_SERVICE_HOST': os.environ.get('CONTROL_SERVICE_HOST', '127.0.0.1'),
            'CONTROL_SERVICE_PORT': os.environ.get('CONTROL_SERVICE_PORT', '8081'),
        },
    )

    return LaunchDescription([
        map_arg,
        params_arg,
        use_sim_time_arg,
        nav2_bringup,
        boundary_monitor_node,
    ])

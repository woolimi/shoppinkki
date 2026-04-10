"""Namespace-aware bringup launch — pinky_bringup 대체.

기존 bringup_robot.launch.xml 과 동일한 구성이되,
모든 노드를 robot_<id> namespace 아래에서 실행하고
frame_prefix 를 적용한다.

구성:
    - upload_robot.launch.py (robot_state_publisher + JSP, frame_prefix 적용)
    - LiDAR (sllidar_c1, frame_id=<ns>/rplidar_link)
    - ns_bringup (모터 + namespace odom TF)
    - battery_publisher

Usage:
    ROBOT_ID=54 ros2 launch shoppinkki_nav bringup.launch.py
    ROBOT_ID=18 ros2 launch shoppinkki_nav bringup.launch.py
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():
    robot_id = os.environ.get('ROBOT_ID', '54')
    ns = f'robot_{robot_id}'
    ns_slash = ns + '/'

    pinky_desc_dir = get_package_share_directory('pinky_description')
    pinky_bringup_dir = get_package_share_directory('pinky_bringup')

    # ── 1. robot_state_publisher + JSP (frame_prefix 적용) ────────────────────
    upload_robot = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pinky_desc_dir, 'launch', 'upload_robot.launch.py')
        ),
        launch_arguments={
            'namespace': ns,
            'is_sim': 'false',
        }.items(),
    )

    # ── 2. LiDAR — namespace 직접 지정 ──────────────────────────────────────
    #   PushRosNamespace + IncludeLaunchDescription 는 전파가 안 되므로
    #   sllidar_node 를 직접 선언하여 /robot_<id>/scan 으로 발행
    lidar = Node(
        package='sllidar_ros2',
        executable='sllidar_node',
        name='sllidar_node',
        namespace=ns,
        parameters=[{
            'channel_type': 'serial',
            'serial_port': '/dev/ttyAMA0',
            'serial_baudrate': 460800,
            'frame_id': ns_slash + 'rplidar_link',
            'inverted': False,
            'angle_compensate': True,
            'scan_mode': 'DenseBoost',
        }],
        output='screen',
    )

    # ── 3. ns_bringup (모터 + namespace odom TF) ─────────────────────────────
    ns_bringup = Node(
        package='shoppinkki_core',
        executable='ns_bringup',
        name='pinky_bringup',
        namespace=ns,
        parameters=[
            os.path.join(pinky_bringup_dir, 'config', 'pinky_params.yaml'),
            {'frame_prefix': ns_slash},
        ],
        output='screen',
    )

    # ── 4. battery_publisher ─────────────────────────────────────────────────
    battery = Node(
        package='pinky_bringup',
        executable='battery_publisher',
        name='battery_publisher',
        namespace=ns,
        output='screen',
    )

    return LaunchDescription([
        upload_robot,
        lidar,
        ns_bringup,
        battery,
    ])

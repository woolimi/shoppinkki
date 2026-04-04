"""ShopPinkki Open-RMF Fleet Adapter 통합 launch.

구성:
  - rmf_traffic_schedule_node   : 교통 스케줄러 (경로 충돌 협상)
  - rmf_traffic_blockade_node   : 교통 봉쇄 관리자
  - PinkyFleetAdapter 노드      : 로봇 54, 18 RMF 등록

사용법:
    ros2 launch shoppinkki_rmf rmf_fleet.launch.py

전제 조건:
    ros2 launch shoppinkki_nav gz_multi_robot.launch.py  (또는 실물 로봇)
    ros2 run control_service main
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


PKG = get_package_share_directory('shoppinkki_rmf')
CONFIG_FILE = os.path.join(PKG, 'config', 'fleet_config.yaml')


def generate_launch_description() -> LaunchDescription:
    # ── 파라미터 선언 ──────────────────────────────────────────────────────────
    config_file_arg = DeclareLaunchArgument(
        'config_file',
        default_value=CONFIG_FILE,
        description='fleet_config.yaml 경로',
    )

    # ── rmf_traffic_schedule_node ─────────────────────────────────────────────
    # RMF 교통 스케줄러: 각 로봇의 경로를 받아 충돌 협상 수행
    traffic_schedule = Node(
        package='rmf_traffic_ros2',
        executable='rmf_traffic_schedule_node',
        name='rmf_traffic_schedule',
        output='screen',
        parameters=[{'use_sim_time': False}],
    )

    # ── rmf_traffic_blockade_node ─────────────────────────────────────────────
    traffic_blockade = Node(
        package='rmf_traffic_ros2',
        executable='rmf_traffic_blockade_node',
        name='rmf_traffic_blockade',
        output='screen',
        parameters=[{'use_sim_time': False}],
    )

    # ── PinkyFleetAdapter ─────────────────────────────────────────────────────
    fleet_adapter = Node(
        package='shoppinkki_rmf',
        executable='fleet_adapter',
        name='pinky_fleet_adapter',
        output='screen',
        parameters=[{
            'use_sim_time': False,
            'config_file': LaunchConfiguration('config_file'),
        }],
    )

    return LaunchDescription([
        config_file_arg,
        traffic_schedule,
        traffic_blockade,
        fleet_adapter,
    ])

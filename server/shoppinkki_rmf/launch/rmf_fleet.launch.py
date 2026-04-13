"""ShopPinkki Open-RMF Fleet Adapter 통합 launch.

구성:
  - rmf_traffic_schedule        : 교통 스케줄러 (경로 충돌 협상)
  - rmf_traffic_blockade        : 교통 봉쇄 관리자
  - rmf_task_dispatcher         : 태스크 디스패처 (bid 기반 할당)
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
from launch.actions import DeclareLaunchArgument, TimerAction
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
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Gazebo 시뮬레이션 시 true 설정',
    )
    sim_time = LaunchConfiguration('use_sim_time')

    # ── rmf_traffic_schedule_node ─────────────────────────────────────────────
    # Adapter.make() 가 이 노드에 연결해야 하므로 fleet_adapter 보다 먼저 기동
    traffic_schedule = Node(
        package='rmf_traffic_ros2',
        executable='rmf_traffic_schedule',
        name='rmf_traffic_schedule',
        output='screen',
        parameters=[{'use_sim_time': sim_time}],
    )

    # ── rmf_traffic_blockade_node ─────────────────────────────────────────────
    traffic_blockade = Node(
        package='rmf_traffic_ros2',
        executable='rmf_traffic_blockade',
        name='rmf_traffic_blockade',
        output='screen',
        parameters=[{'use_sim_time': sim_time}],
    )

    # ── rmf_task_dispatcher ─────────────────────────────────────────────────
    task_dispatcher = Node(
        package='rmf_task_ros2',
        executable='rmf_task_dispatcher',
        name='rmf_task_dispatcher',
        output='screen',
        parameters=[{'use_sim_time': sim_time}],
    )

    # ── PinkyFleetAdapter (3초 지연 — traffic_schedule 준비 대기) ─────────────
    fleet_adapter = TimerAction(
        period=15.0,
        actions=[Node(
            package='shoppinkki_rmf',
            executable='fleet_adapter',
            name='pinky_fleet_adapter',
            output='screen',
            parameters=[{
                'use_sim_time': sim_time,
                'config_file': LaunchConfiguration('config_file'),
            }],
        )],
    )

    return LaunchDescription([
        config_file_arg,
        use_sim_time_arg,
        traffic_schedule,
        traffic_blockade,
        task_dispatcher,
        fleet_adapter,
    ])

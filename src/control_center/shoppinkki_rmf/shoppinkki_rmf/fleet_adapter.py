"""ShopPinkki Open-RMF Fleet Adapter 진입점.

RMF Traffic Negotiation + Task Dispatcher 를 통해
두 Pinky 로봇(#54, #18)의 경로 충돌을 자동 조정.

실행:
    ros2 run shoppinkki_rmf fleet_adapter \\
        --ros-args -p config_file:=<path>/fleet_config.yaml

의존 패키지 (설치 확인):
    sudo apt install ros-jazzy-rmf-fleet-adapter ros-jazzy-rmf-traffic ros-jazzy-rmf-task
    pip install rmf-adapter

⚠️  rmf_fleet_adapter Python API 는 버전에 따라 달라집니다.
    `python3 -c "import rmf_fleet_adapter; print(dir(rmf_fleet_adapter))"` 로
    사용 가능한 심볼을 확인한 후 아래 코드를 조정하세요.
    easy_full_control 은 rmf_fleet_adapter 2.x 기준.

아키텍처:
    [RMF Traffic Schedule]
            │
            ▼
    [PinkyFleetAdapter]  ←── StatusBridge (pose 업데이트 1~2Hz)
            │ navigate/stop/dock
            ▼
    [control_service]    ←── 기존 그대로
            │ /robot_<id>/cmd
            ▼
    [Pi 5: shoppinkki_core SM + BT]
"""

from __future__ import annotations

import logging
import math
import os
import sys
from typing import Dict

import rclpy
from rclpy.node import Node

logger = logging.getLogger(__name__)

# ── 패키지 경로 ────────────────────────────────────────────────────────────────
try:
    from ament_index_python.packages import get_package_share_directory
    _PKG_SHARE = get_package_share_directory('shoppinkki_rmf')
except Exception:
    _PKG_SHARE = os.path.join(os.path.dirname(__file__), '..', '..')


def _load_config(path: str) -> dict:
    """fleet_config.yaml 로드."""
    import yaml
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def _load_nav_graph(path: str):
    """shop_nav_graph.yaml → rmf_traffic.agv.Graph 변환.

    rmf_traffic Python binding 이 설치된 경우 실제 Graph 객체 반환.
    없으면 dict 원본 반환 (fallback 모드).
    """
    import yaml
    with open(path, 'r') as f:
        data = yaml.safe_load(f)

    try:
        import rmf_traffic
        from rmf_traffic.agv import Graph as RmfGraph

        graph = RmfGraph()
        levels = data.get('levels', [])
        if not levels:
            return data

        level = levels[0]
        for i, v in enumerate(level.get('vertices', [])):
            graph.add_waypoint(level['name'], [v['x'], v['y']])

        for edge in level.get('edges', []):
            v1 = edge['v1_idx']
            v2 = edge['v2_idx']
            bidir = edge.get('bidirectional', True)
            props = rmf_traffic.agv.Graph.Lane.Properties()
            graph.add_lane(v1, v2, props)
            if bidir:
                graph.add_lane(v2, v1, props)

        logger.info('Nav graph 로드 완료: %d 웨이포인트, %d 레인',
                    graph.num_waypoints, graph.num_lanes)
        return graph

    except ImportError:
        logger.warning('rmf_traffic 미설치 — nav graph dict 반환 (fallback)')
        return data


# ── Fleet Adapter 노드 ────────────────────────────────────────────────────────

class PinkyFleetAdapterNode(Node):
    """두 Pinky 로봇을 RMF에 등록하는 Fleet Adapter 노드."""

    def __init__(self, config: dict, nav_graph) -> None:
        super().__init__('pinky_fleet_adapter')

        self._config = config
        self._nav_graph = nav_graph
        self._bridges: Dict[str, object] = {}
        self._handles: Dict[str, object] = {}

        fleet_cfg = config.get('fleet', {})
        ctrl_cfg = config.get('control_service', {})
        ctrl_host = ctrl_cfg.get('host', '127.0.0.1')
        ctrl_port = int(ctrl_cfg.get('http_port', 8081))

        from .status_bridge import RobotStatusBridge
        from .robot_command_handle import PinkyCommandHandle
        from .task_dispatcher import TaskDispatcher

        self._dispatcher = TaskDispatcher(ctrl_host, ctrl_port)

        # RMF Adapter 초기화 시도
        self._rmf_adapter = self._init_rmf_adapter(fleet_cfg, nav_graph)

        # 각 로봇 등록
        for robot_cfg in fleet_cfg.get('robots', []):
            rid = str(robot_cfg['id'])
            bridge = RobotStatusBridge(rid, self)
            bridge.on_mode_change = self._on_mode_change
            self._bridges[rid] = bridge

            handle = PinkyCommandHandle(rid, bridge, ctrl_host, ctrl_port)
            self._handles[rid] = handle

            # RMF 핸들 등록
            rmf_handle = self._register_robot(rid, robot_cfg, handle)
            if rmf_handle is not None:
                bridge.register_handle(rmf_handle)

        self.get_logger().info(
            'PinkyFleetAdapterNode 준비 완료 (로봇: %s)',
            list(self._bridges.keys()),
        )

    def _init_rmf_adapter(self, fleet_cfg: dict, nav_graph):
        """RMF FleetAdapter 초기화 (rmf_fleet_adapter 2.x easy_full_control API).

        패키지 미설치 시 None 반환 (degraded 모드로 계속 동작).
        """
        try:
            import rmf_fleet_adapter as rmf
            fleet_name = fleet_cfg.get('name', 'pinky_fleet')
            profile_cfg = fleet_cfg.get('profile', {})
            limits_cfg = fleet_cfg.get('limits', {})

            footprint = profile_cfg.get('footprint', 0.060)
            vicinity = profile_cfg.get('vicinity', 0.20)

            lin = limits_cfg.get('linear', {})
            ang = limits_cfg.get('angular', {})

            # rmf_fleet_adapter.easy_full_control (2.x)
            if hasattr(rmf, 'easy_full_control'):
                efc = rmf.easy_full_control

                config = efc.FleetUpdateHandle.make(
                    fleet_name,
                    nav_graph,
                    rmf.agv.VehicleTraits(
                        limits=rmf.agv.VehicleTraits.Limits(
                            nominal_velocity=lin.get('velocity', 0.3),
                            nominal_acceleration=lin.get('acceleration', 0.5),
                        ),
                        rotational=rmf.agv.VehicleTraits.Limits(
                            nominal_velocity=ang.get('velocity', 1.0),
                            nominal_acceleration=ang.get('acceleration', 1.5),
                        ),
                        profile=rmf.geometry.SimpleCircle(footprint),
                    ),
                )
                self.get_logger().info('RMF easy_full_control 초기화 완료')
                return config

            self.get_logger().warning('rmf.easy_full_control 심볼 없음 — degraded 모드')
            return None

        except ImportError:
            self.get_logger().warning(
                'rmf_fleet_adapter 미설치. degraded 모드로 실행 중.\n'
                '  sudo apt install ros-jazzy-rmf-fleet-adapter\n'
                '  pip install rmf-adapter'
            )
            return None
        except Exception as e:
            self.get_logger().error('RMF 초기화 오류: %s', e)
            return None

    def _register_robot(self, robot_id: str, robot_cfg: dict, cmd_handle) -> object:
        """로봇을 RMF fleet 에 등록하고 RobotUpdateHandle 반환."""
        if self._rmf_adapter is None:
            return None
        try:
            init_x, init_y, init_yaw = 0.20, 0.20, 1.5708
            waypoint_name = robot_cfg.get('initial_waypoint', 'P1')
            init_yaw = float(robot_cfg.get('initial_orientation', init_yaw))

            # easy_full_control 에서 로봇 등록
            rmf_handle = self._rmf_adapter.add_robot(
                name=f'pinky_{robot_id}',
                cmd_handle=cmd_handle,
                initial_location=waypoint_name,
                initial_battery_soc=1.0,
            )
            self.get_logger().info('RMF 로봇 등록: pinky_%s @ %s', robot_id, waypoint_name)
            return rmf_handle

        except Exception as e:
            self.get_logger().warning('로봇 등록 실패 robot_%s: %s', robot_id, e)
            return None

    def _on_mode_change(self, robot_id: str, prev: str, curr: str) -> None:
        """모드 변화 시 RMF 레인 개폐 등 정책 적용."""
        self.get_logger().info(
            'robot_%s 모드 변화: %s → %s', robot_id, prev, curr
        )
        # 예: TRACKING 진입 시 결제 구역 레인 차단 (lane close_lanes)
        # 실제 lane close/open 은 rmf_fleet_adapter API 버전에 따라 구현
        #
        # if curr == 'TRACKING' and self._rmf_adapter:
        #     checkout_lanes = [13, 14]  # Checkout 관련 레인 인덱스
        #     self._rmf_adapter.close_lanes(checkout_lanes)
        # elif prev == 'TRACKING' and self._rmf_adapter:
        #     self._rmf_adapter.open_lanes(checkout_lanes)


# ── 진입점 ────────────────────────────────────────────────────────────────────

def main(args=None) -> None:
    rclpy.init(args=args)

    # config 파일 경로 파라미터
    node_tmp = rclpy.create_node('_rmf_param_reader')
    node_tmp.declare_parameter('config_file', '')
    config_file = node_tmp.get_parameter('config_file').get_parameter_value().string_value
    node_tmp.destroy_node()

    if not config_file:
        config_file = os.path.join(_PKG_SHARE, 'config', 'fleet_config.yaml')

    logger.info('config 파일: %s', config_file)

    try:
        config = _load_config(config_file)
    except Exception as e:
        logger.error('config 로드 실패: %s', e)
        rclpy.shutdown()
        return

    # nav graph 로드
    graph_rel = config.get('fleet', {}).get('nav_graph', 'shop_nav_graph.yaml')
    graph_path = os.path.join(_PKG_SHARE, 'maps', graph_rel)
    try:
        nav_graph = _load_nav_graph(graph_path)
    except Exception as e:
        logger.warning('nav graph 로드 실패: %s — None 사용', e)
        nav_graph = None

    adapter_node = PinkyFleetAdapterNode(config, nav_graph)

    try:
        rclpy.spin(adapter_node)
    except KeyboardInterrupt:
        pass
    finally:
        adapter_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    main()

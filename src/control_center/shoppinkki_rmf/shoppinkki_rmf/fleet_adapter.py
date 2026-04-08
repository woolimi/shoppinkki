"""ShopPinkki Open-RMF Fleet Adapter.

rmf_adapter Python API (Jazzy / rmf_fleet_adapter 2.7.2) 기반.
두 Pinky 로봇(#54, #18)을 RMF EasyFullControl에 등록하고
경로 충돌을 자동 조정.

실행:
    ros2 launch shoppinkki_rmf rmf_fleet.launch.py

의존:
    sudo apt install ros-jazzy-rmf-fleet-adapter ros-jazzy-rmf-fleet-adapter-python
    numpy < 2.0 필수 (pip install "numpy<2.0")
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from typing import Dict, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

import rmf_adapter as adpt
import rmf_adapter.easy_full_control as efc
import requests

logger = logging.getLogger(__name__)


# ── 헬퍼 ───────────────────────────────────────────────────────────────────────

def _parse_waypoint_coords(nav_graph_path: str) -> dict[str, tuple[float, float]]:
    """nav_graph YAML에서 waypoint 이름 → (x, y) 좌표 사전을 반환."""
    try:
        import yaml
        with open(nav_graph_path, 'r') as f:
            data = yaml.safe_load(f)
        coords: dict[str, tuple[float, float]] = {}
        for level in data.get('levels', {}).values():
            for v in level.get('vertices', []):
                if len(v) >= 3 and isinstance(v[2], dict):
                    name = v[2].get('name')
                    if name:
                        coords[name] = (float(v[0]), float(v[1]))
        return coords
    except Exception as e:
        logger.warning('nav_graph 파싱 실패: %s', e)
        return {}


# ── 단일 로봇 어댑터 ────────────────────────────────────────────────────────────

class RobotAdapter:
    """한 로봇의 상태 추적 + RMF ↔ control_service 명령 중계."""

    ARRIVE_DIST_M = 0.15
    ARRIVE_YAW_RAD = 0.30

    def __init__(self, robot_id: str, ctrl_host: str, ctrl_port: int) -> None:
        self.robot_id = robot_id
        self._rest_base = f'http://{ctrl_host}:{ctrl_port}'

        self._x = 0.0
        self._y = 0.0
        self._yaw = 0.0
        self._battery = 1.0
        self._mode = 'CHARGING'

        self._handle: Optional[efc.EasyRobotUpdateHandle] = None
        self._handle_lock = threading.Lock()

        self._nav_cancel = threading.Event()
        self._nav_thread: Optional[threading.Thread] = None

    # ── 상태 수신 ──────────────────────────────────────────────────────────────

    def on_status(self, data: dict) -> None:
        """/robot_<id>/status JSON 수신 시 호출."""
        self._x = float(data.get('pos_x', self._x))
        self._y = float(data.get('pos_y', self._y))
        self._yaw = float(data.get('yaw', self._yaw))
        batt_pct = float(data.get('battery', self._battery * 100))
        self._battery = max(0.0, min(1.0, batt_pct / 100.0))
        self._mode = data.get('mode', self._mode)

        with self._handle_lock:
            if self._handle is not None:
                import numpy as np
                state = efc.RobotState(
                    map='L1',
                    position=np.array([self._x, self._y, self._yaw]),
                    battery_soc=self._battery,
                )
                try:
                    self._handle.update(state, None)
                except Exception as e:
                    logger.debug('[%s] handle.update 오류: %s', self.robot_id, e)

    def set_handle(self, handle) -> None:
        with self._handle_lock:
            self._handle = handle

    @property
    def position(self):
        return (self._x, self._y, self._yaw)

    # ── RMF 콜백 생성 ──────────────────────────────────────────────────────────

    def make_callbacks(self) -> efc.RobotCallbacks:

        def navigate(dest: efc.Destination, execution: efc.CommandExecution) -> None:
            self._cancel_nav()
            x, y = dest.xy
            yaw = dest.yaw
            zone_idx = dest.graph_index

            logger.info('[%s] navigate → (%.3f, %.3f, yaw=%.2f) idx=%s',
                        self.robot_id, x, y, yaw, zone_idx)

            self._send_cmd({
                'cmd': 'navigate_to',
                'zone_id': int(zone_idx) if zone_idx is not None else 0,
                'x': round(float(x), 4),
                'y': round(float(y), 4),
                'theta': round(float(yaw), 4),
            })

            self._nav_cancel.clear()
            self._nav_thread = threading.Thread(
                target=self._wait_arrive,
                args=(float(x), float(y), float(yaw), execution.finished),
                daemon=True,
            )
            self._nav_thread.start()

        def stop(activity) -> None:
            self._cancel_nav()
            logger.info('[%s] stop → WAITING', self.robot_id)
            self._send_cmd({'cmd': 'mode', 'value': 'WAITING'})

        def action_executor(category: str, desc, execution) -> None:
            logger.info('[%s] action: %s', self.robot_id, category)
            execution.finished()

        return efc.RobotCallbacks(
            navigate=navigate,
            stop=stop,
            action_executor=action_executor,
        )

    # ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

    def _send_cmd(self, payload: dict) -> None:
        url = f'{self._rest_base}/robot/{self.robot_id}/cmd'
        try:
            resp = requests.post(url, json=payload, timeout=3.0)
            if resp.status_code != 200:
                logger.warning('[%s] cmd 응답 %d: %s',
                               self.robot_id, resp.status_code, resp.text[:80])
        except Exception as e:
            logger.error('[%s] cmd 전송 실패: %s', self.robot_id, e)

    def _cancel_nav(self) -> None:
        self._nav_cancel.set()
        if self._nav_thread and self._nav_thread.is_alive():
            self._nav_thread.join(timeout=2.0)

    def _wait_arrive(
        self, gx: float, gy: float, gyaw: float,
        done_cb, timeout_s: float = 120.0
    ) -> None:
        deadline = time.monotonic() + timeout_s
        while not self._nav_cancel.is_set():
            dx = self._x - gx
            dy = self._y - gy
            dist = math.sqrt(dx * dx + dy * dy)
            dyaw = abs(((self._yaw - gyaw + math.pi) % (2 * math.pi)) - math.pi)

            if dist <= self.ARRIVE_DIST_M and dyaw <= self.ARRIVE_YAW_RAD:
                logger.info('[%s] 도착 (dist=%.3f, dyaw=%.3f)',
                            self.robot_id, dist, dyaw)
                done_cb()
                return

            if time.monotonic() >= deadline:
                logger.warning('[%s] navigate timeout', self.robot_id)
                done_cb()
                return

            time.sleep(0.5)


# ── Fleet Adapter ROS 노드 ──────────────────────────────────────────────────────

class PinkyFleetAdapter(Node):
    """두 Pinky 로봇을 RMF에 등록하는 메인 노드."""

    def __init__(self, config: dict, config_file: str, nav_graph_path: str) -> None:
        super().__init__('pinky_fleet_adapter')

        fleet_cfg = config.get('rmf_fleet', {})
        ctrl_cfg = config.get('control_service', {})
        ctrl_host = ctrl_cfg.get('host', '127.0.0.1')
        ctrl_port = int(ctrl_cfg.get('http_port', 8081))

        # 로봇 어댑터 + status 구독
        self._robots: Dict[str, RobotAdapter] = {}
        for robot_name, robot_cfg in fleet_cfg.get('robots', {}).items():
            # robot_name 포맷: "pinky_54" → id = "54"
            rid = robot_name.replace('pinky_', '')
            robot = RobotAdapter(rid, ctrl_host, ctrl_port)
            self._robots[rid] = robot
            self.create_subscription(
                String, f'/robot_{rid}/status',
                lambda msg, rid=rid: self._on_status(rid, msg),
                10,
            )

        # RMF Adapter + EasyFleet 초기화
        self._adapter = None
        self._easy_fleet = None
        self._init_rmf(fleet_cfg, config_file, nav_graph_path)

        self.get_logger().info(
            f'PinkyFleetAdapter 준비: {list(self._robots.keys())}'
        )

    # ── RMF 초기화 ─────────────────────────────────────────────────────────────

    def _init_rmf(self, fleet_cfg: dict, config_file: str, nav_graph_path: str) -> None:
        try:
            fleet_name = fleet_cfg.get('name', 'pinky_fleet')

            # nav_graph에서 waypoint 이름 → 좌표 사전 구축
            self._waypoint_coords = _parse_waypoint_coords(nav_graph_path)

            # FleetConfiguration — from_config_files 방식 (NumPy 호환)
            fleet_config = efc.FleetConfiguration.from_config_files(
                config_file, nav_graph_path
            )
            if fleet_config is None:
                self.get_logger().error('FleetConfiguration 로드 실패')
                return

            # Adapter 생성 (rmf_traffic_schedule 필요)
            self._adapter = adpt.Adapter.make(fleet_name)
            if self._adapter is None:
                self.get_logger().error(
                    'Adapter.make 실패 — rmf_traffic_schedule 실행 여부 확인')
                return

            self._easy_fleet = self._adapter.add_easy_fleet(fleet_config)
            self._adapter.start()
            self.get_logger().info(f'RMF Adapter 시작: {fleet_name}')

            # 로봇 등록
            for rid, robot in self._robots.items():
                robot_name = f'pinky_{rid}'
                robot_cfg = fleet_cfg.get('robots', {}).get(robot_name, {})
                charger = robot_cfg.get('charger', 'P1')
                yaw = float(robot_cfg.get('initial_orientation', 1.5708))
                self._register_robot(rid, robot_name, charger, yaw)

        except Exception as e:
            self.get_logger().error(f'RMF 초기화 실패: {e}')

    # ── 로봇 등록 ───────────────────────────────────────────────────────────────

    def _register_robot(
        self, robot_id: str, robot_name: str, charger: str, initial_yaw: float
    ) -> None:
        import numpy as np
        robot = self._robots[robot_id]

        # nav_graph에서 충전소 waypoint 좌표 조회
        coords = self._waypoint_coords.get(charger)
        if coords is None:
            self.get_logger().warning(
                f'충전소 waypoint "{charger}" 를 nav_graph에서 찾지 못함 — (0,0) 사용')
            init_x, init_y = 0.0, 0.0
        else:
            init_x, init_y = coords
            self.get_logger().info(
                f'[{robot_name}] 초기 위치: {charger} = ({init_x:.3f}, {init_y:.3f})')

        state = efc.RobotState(
            map='L1',
            position=np.array([init_x, init_y, initial_yaw]),
            battery_soc=1.0,
        )
        robot_config = efc.RobotConfiguration(compatible_chargers=[charger])
        callbacks = robot.make_callbacks()

        handle = self._easy_fleet.add_robot(
            robot_name, state, robot_config, callbacks
        )
        robot.set_handle(handle)

        self.get_logger().info(f'로봇 등록: {robot_name} (charger={charger})')

    # ── ROS 콜백 ────────────────────────────────────────────────────────────────

    def _on_status(self, robot_id: str, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            self._robots[robot_id].on_status(data)
        except Exception as e:
            self.get_logger().warning(f'status 파싱 오류: {e}')


# ── 진입점 ─────────────────────────────────────────────────────────────────────

def main(args=None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )

    # rclcpp를 먼저 초기화해야 adpt.Adapter.make()가 동작함
    adpt.init_rclcpp()
    rclpy.init(args=args)

    # config_file 파라미터
    tmp = rclpy.create_node('_rmf_param_reader')
    tmp.declare_parameter('config_file', '')
    config_file = tmp.get_parameter('config_file').get_parameter_value().string_value
    tmp.destroy_node()

    if not config_file:
        try:
            from ament_index_python.packages import get_package_share_directory
            pkg = get_package_share_directory('shoppinkki_rmf')
        except Exception:
            pkg = os.path.join(os.path.dirname(__file__), '..', '..')
        config_file = os.path.join(pkg, 'config', 'fleet_config.yaml')

    # config 로드
    import yaml
    try:
        with open(config_file) as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.error('config 로드 실패: %s', e)
        rclpy.shutdown()
        return

    # nav graph 경로
    try:
        from ament_index_python.packages import get_package_share_directory
        pkg = get_package_share_directory('shoppinkki_rmf')
    except Exception:
        pkg = os.path.join(os.path.dirname(__file__), '..', '..')
    nav_graph_path = os.path.join(pkg, 'maps', 'shop_nav_graph.yaml')

    node = PinkyFleetAdapter(config, config_file, nav_graph_path)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

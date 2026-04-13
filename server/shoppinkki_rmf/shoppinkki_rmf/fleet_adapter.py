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
from tf2_ros import Buffer, TransformListener

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


def _parse_waypoint_orientations(nav_graph_path: str) -> dict[int, float]:
    """nav_graph YAML에서 waypoint idx → orientation 사전을 반환."""
    try:
        import yaml
        with open(nav_graph_path, 'r') as f:
            data = yaml.safe_load(f)
        orientations: dict[int, float] = {}
        for level in data.get('levels', {}).values():
            for idx, v in enumerate(level.get('vertices', [])):
                if len(v) >= 3 and isinstance(v[2], dict):
                    orient = v[2].get('orientation')
                    if orient is not None:
                        orientations[idx] = float(orient)
        return orientations
    except Exception as e:
        logger.warning('nav_graph orientation 파싱 실패: %s', e)
        return {}


# ── 단일 로봇 어댑터 ────────────────────────────────────────────────────────────

class RobotAdapter:
    """한 로봇의 상태 추적 + RMF ↔ control_service 명령 중계."""

    ARRIVE_DIST_M = 0.15
    ARRIVE_YAW_RAD = 0.30

    def __init__(self, robot_id: str, ctrl_host: str, ctrl_port: int,
                 waypoint_orientations: dict[int, float] = None) -> None:
        self.robot_id = robot_id
        self._rest_base = f'http://{ctrl_host}:{ctrl_port}'
        self._wp_orientations = waypoint_orientations or {}
        self._all_robots: dict[str, 'RobotAdapter'] = {}  # set after init

        self._x = 0.0
        self._y = 0.0
        self._yaw = 0.0
        self._battery = 0.95
        self._mode = 'CHARGING'

        self._handle: Optional[efc.EasyRobotUpdateHandle] = None

        # 모든 nav 관련 상태를 하나의 lock으로 보호
        self._lock = threading.Lock()
        self._nav_cancel = threading.Event()
        self._nav_thread: Optional[threading.Thread] = None
        self._activity_id = None
        self._nav_execution = None
        self._nav_executing = False
        self._nav_goal = None

    # ── 상태 수신 ──────────────────────────────────────────────────────────────

    def on_status(self, data: dict) -> None:
        """/robot_<id>/status JSON 수신 시 호출."""
        old_x, old_y = self._x, self._y
        self._x = float(data.get('pos_x', self._x))
        self._y = float(data.get('pos_y', self._y))
        self._yaw = float(data.get('yaw', self._yaw))
        if abs(self._x - old_x) > 0.01 or abs(self._y - old_y) > 0.01:
            logger.info('[%s] 위치 업데이트: (%.3f,%.3f) → (%.3f,%.3f)',
                        self.robot_id, old_x, old_y, self._x, self._y)
        batt_pct = float(data.get('battery', self._battery * 100))
        self._battery = max(0.0, min(1.0, batt_pct / 100.0))
        old_mode = self._mode
        self._mode = data.get('mode', self._mode)

        # 모드 기반 도착 감지: GUIDING → WAITING 전이 = Nav2 goal 완료
        with self._lock:
            if (self._nav_executing
                    and old_mode == 'GUIDING' and self._mode == 'WAITING'):
                logger.info('[%s] 모드 전이 감지: GUIDING→WAITING → 도착 완료',
                            self.robot_id)
                execution = self._nav_execution
                self._nav_executing = False
                self._nav_execution = None
                self._activity_id = None
                self._nav_cancel.set()  # _wait_arrive 스레드 종료
        # lock 밖에서 finished 호출 (deadlock 방지)
        if old_mode == 'GUIDING' and self._mode == 'WAITING' and 'execution' in dir():
            if execution is not None:
                execution.finished()

        self._update_handle()

    def _update_handle(self) -> None:
        """RMF handle에 현재 상태 보고."""
        if self._handle is None:
            return
        try:
            import numpy as np
            state = efc.RobotState(
                map='L1',
                position=np.array([self._x, self._y, self._yaw]),
                battery_soc=self._battery,
            )
            with self._lock:
                activity = self._activity_id
            self._handle.update(state, activity)
        except Exception as e:
            logger.debug('[%s] handle.update 오류: %s', self.robot_id, e)

    def set_handle(self, handle) -> None:
        self._handle = handle
        logger.info('[%s] RMF handle 등록 완료', self.robot_id)

    @property
    def position(self):
        return (self._x, self._y, self._yaw)

    # ── RMF 콜백 생성 ──────────────────────────────────────────────────────────

    def make_callbacks(self) -> efc.RobotCallbacks:

        def navigate(dest: efc.Destination, execution: efc.CommandExecution) -> None:
            x, y = dest.xy
            yaw = dest.yaw
            zone_idx = dest.graph_index
            # nav_graph에 orientation이 있으면 항상 적용
            if zone_idx is not None:
                wp_yaw = self._wp_orientations.get(int(zone_idx))
                if wp_yaw is not None:
                    yaw = wp_yaw
                    logger.info('[%s] orientation: idx=%s → yaw=%.4f',
                                self.robot_id, zone_idx, yaw)

            self._refresh_position()

            dx = self._x - float(x)
            dy = self._y - float(y)
            dist = math.sqrt(dx * dx + dy * dy)
            logger.info('[%s] navigate: 현재(%.3f,%.3f) → 목표(%.3f,%.3f) dist=%.3f',
                        self.robot_id, self._x, self._y, float(x), float(y), dist)

            if dist <= self.ARRIVE_DIST_M:
                logger.info('[%s] 이미 도착 (dist=%.3f) → 즉시 완료',
                            self.robot_id, dist)
                execution.finished()
                return

            # 이전 navigate 취소
            self._cancel_nav()

            logger.info('[%s] navigate → (%.3f, %.3f, yaw=%.2f) idx=%s',
                        self.robot_id, x, y, yaw, zone_idx)

            with self._lock:
                self._activity_id = execution.identifier
                self._nav_execution = execution
                self._nav_executing = True
                self._nav_goal = (float(x), float(y))

            self._send_cmd({
                'cmd': 'navigate_to',
                'zone_id': int(zone_idx) if zone_idx is not None else 0,
                'x': round(float(x), 4),
                'y': round(float(y), 4),
                'theta': round(float(yaw), 4),
            })

            # 타임아웃 백업 스레드
            self._nav_cancel.clear()
            self._nav_thread = threading.Thread(
                target=self._wait_arrive,
                args=(float(x), float(y), float(yaw), execution),
                daemon=True,
            )
            self._nav_thread.start()

        def stop(activity) -> None:
            logger.debug('[%s] stop 호출 (무시 — navigate에서 처리)',
                         self.robot_id)

        def action_executor(category: str, desc, execution) -> None:
            logger.info('[%s] action: %s', self.robot_id, category)
            execution.finished()

        return efc.RobotCallbacks(
            navigate=navigate,
            stop=stop,
            action_executor=action_executor,
        )

    # ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

    def _refresh_position(self) -> None:
        """control_service REST API로 현재 위치 조회."""
        try:
            resp = requests.get(
                f'{self._rest_base}/robots', timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                robot_data = data.get(self.robot_id)
                if robot_data:
                    self._x = float(robot_data.get('pos_x', self._x))
                    self._y = float(robot_data.get('pos_y', self._y))
                    self._mode = robot_data.get('mode', self._mode)
        except Exception:
            pass

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
        """진행 중인 navigate 취소."""
        self._nav_cancel.set()
        if self._nav_thread and self._nav_thread.is_alive():
            self._nav_thread.join(timeout=3.0)
        with self._lock:
            self._nav_executing = False
            self._nav_execution = None
            self._activity_id = None

    def _wait_arrive(
        self, gx: float, gy: float, gyaw: float,
        execution, timeout_s: float = 120.0
    ) -> None:
        """타임아웃 백업. 주 감지는 on_status의 모드 전이."""
        deadline = time.monotonic() + timeout_s

        while not self._nav_cancel.is_set():
            with self._lock:
                if not self._nav_executing:
                    return
                # execution이 바뀌었으면 이 스레드는 종료
                if self._nav_execution is not execution:
                    return

            if not execution.okay():
                logger.info('[%s] RMF execution 취소됨 — 중단', self.robot_id)
                self._send_cmd({'cmd': 'navigate_cancel'})
                with self._lock:
                    self._nav_executing = False
                    self._nav_execution = None
                    self._activity_id = None
                return

            self._refresh_position()
            dx = self._x - gx
            dy = self._y - gy
            dist = math.sqrt(dx * dx + dy * dy)
            dyaw = abs(((self._yaw - gyaw + math.pi) % (2 * math.pi)) - math.pi)

            if dist <= self.ARRIVE_DIST_M and dyaw <= self.ARRIVE_YAW_RAD:
                logger.info('[%s] 위치 기반 도착 (dist=%.3f, dyaw=%.3f)',
                            self.robot_id, dist, dyaw)
                with self._lock:
                    self._nav_executing = False
                    self._nav_execution = None
                    self._activity_id = None
                execution.finished()
                return

            if time.monotonic() >= deadline:
                logger.warning('[%s] navigate timeout', self.robot_id)
                with self._lock:
                    self._nav_executing = False
                    self._nav_execution = None
                    self._activity_id = None
                execution.finished()
                return

            self._nav_cancel.wait(timeout=1.0)


# ── Status Bridge ROS 노드 ──────────────────────────────────────────────────────

class StatusBridgeNode(Node):
    """robot status 토픽을 구독해서 RobotAdapter로 전달하는 ROS 노드."""

    def __init__(self, robots: Dict[str, RobotAdapter]) -> None:
        super().__init__('pinky_fleet_adapter')
        self._robots = robots
        for rid in robots:
            self.create_subscription(
                String, f'/robot_{rid}/status',
                lambda msg, rid=rid: self._on_status(rid, msg),
                10,
            )
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self.create_timer(0.5, self._periodic_update)
        self.get_logger().info(
            f'StatusBridge 구독: status + TF for {list(robots.keys())}'
        )

    def _on_status(self, robot_id: str, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            self._robots[robot_id].on_status(data)
        except Exception as e:
            self.get_logger().warning(f'[{robot_id}] status 파싱 오류: {e}')

    def _periodic_update(self) -> None:
        """TF lookup + RMF handle 업데이트 (2Hz)."""
        import numpy as np
        from rclpy.time import Time

        for rid, robot in self._robots.items():
            try:
                t = self._tf_buffer.lookup_transform(
                    'map', f'robot_{rid}/base_footprint', Time())
                robot._x = t.transform.translation.x
                robot._y = t.transform.translation.y
                qz = t.transform.rotation.z
                qw = t.transform.rotation.w
                robot._yaw = 2.0 * math.atan2(qz, qw)
            except Exception:
                pass

            # 충전 시뮬레이션
            if robot._battery < 1.0:
                old = robot._battery
                robot._battery = min(1.0, robot._battery + 0.005)
                if int(old * 100) != int(robot._battery * 100):
                    self.get_logger().info(
                        f'[{rid}] battery: {old:.1%} → {robot._battery:.1%}')

            robot._update_handle()


# ── 진입점 ─────────────────────────────────────────────────────────────────────

def main(args=None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )

    adpt.init_rclcpp()
    rclpy.init(args=args)

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

    import yaml
    try:
        with open(config_file) as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.error('config 로드 실패: %s', e)
        rclpy.shutdown()
        return

    fleet_cfg = config.get('rmf_fleet', {})
    ctrl_cfg = config.get('control_service', {})
    ctrl_host = ctrl_cfg.get('host', '127.0.0.1')
    ctrl_port = int(ctrl_cfg.get('http_port', 8081))

    try:
        from ament_index_python.packages import get_package_share_directory
        pkg = get_package_share_directory('shoppinkki_rmf')
    except Exception:
        pkg = os.path.join(os.path.dirname(__file__), '..', '..')
    nav_graph_path = os.path.join(pkg, 'maps', 'shop_nav_graph.yaml')
    waypoint_coords = _parse_waypoint_coords(nav_graph_path)
    waypoint_orientations = _parse_waypoint_orientations(nav_graph_path)

    robots: Dict[str, RobotAdapter] = {}
    for robot_name, robot_cfg in fleet_cfg.get('robots', {}).items():
        rid = robot_name.replace('pinky_', '')
        robots[rid] = RobotAdapter(rid, ctrl_host, ctrl_port, waypoint_orientations)
    # 각 로봇이 다른 로봇 위치를 조회할 수 있도록 참조 설정
    for robot in robots.values():
        robot._all_robots = robots

    bridge_node = StatusBridgeNode(robots)

    fleet_name = fleet_cfg.get('name', 'pinky_fleet')
    fleet_config = efc.FleetConfiguration.from_config_files(
        config_file, nav_graph_path
    )
    if fleet_config is None:
        logger.error('FleetConfiguration 로드 실패')
        rclpy.shutdown()
        return

    adapter = adpt.Adapter.make(fleet_name)
    if adapter is None:
        logger.error('Adapter.make 실패 — rmf_traffic_schedule 실행 여부 확인')
        rclpy.shutdown()
        return

    easy_fleet = adapter.add_easy_fleet(fleet_config)

    for robot_name, robot_cfg in fleet_cfg.get('robots', {}).items():
        rid = robot_name.replace('pinky_', '')
        robot = robots[rid]
        charger = robot_cfg.get('charger', 'P1')
        yaw = float(robot_cfg.get('initial_orientation', 0.0))

        coords = waypoint_coords.get(charger, (0.0, 0.0))
        init_x, init_y = coords
        robot._x = init_x
        robot._y = init_y
        robot._yaw = yaw
        logger.info('[%s] 초기 위치: %s = (%.3f, %.3f)',
                    robot_name, charger, init_x, init_y)

        import numpy as np
        state = efc.RobotState(
            map='L1',
            position=np.array([init_x, init_y, yaw]),
            battery_soc=0.95,
        )
        robot_config = efc.RobotConfiguration(compatible_chargers=[charger])
        callbacks = robot.make_callbacks()

        handle = easy_fleet.add_robot(robot_name, state, robot_config, callbacks)
        robots[rid].set_handle(handle)

    adapter.start()
    logger.info('RMF Adapter 시작: %s (로봇: %s)', fleet_name, list(robots.keys()))

    spin_thread = threading.Thread(
        target=rclpy.spin, args=(bridge_node,), daemon=True
    )
    spin_thread.start()

    try:
        while rclpy.ok():
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        adapter.stop()
        bridge_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

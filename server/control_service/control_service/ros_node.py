"""ROS 2 node for control_service (channel G).

Subscribes:
    /robot_<id>/status    (std_msgs/String JSON)
    /robot_<id>/alarm     (std_msgs/String JSON)
    /robot_<id>/cart      (std_msgs/String JSON)
    /robot_<id>/snapshot  (std_msgs/String JSON) — 인형 감지 스냅샷
    /robot_<id>/customer_event (std_msgs/String JSON) — 결제 구역 진입 등

Publishes:
    /robot_<id>/cmd         (std_msgs/String JSON)
    /robot_<id>/initialpose (geometry_msgs/PoseWithCovarianceStamped)

Falls back gracefully if rclpy is not available
(so the REST-only server boots even on non-ROS machines).
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import threading
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

ROBOT_IDS = os.environ.get('ROBOT_IDS', '11,18,54').split(',')
DOMAIN_ID = int(os.environ.get('ROS_DOMAIN_ID', '14'))

# 로봇별 AMCL 초기 위치 — 맵 프레임 좌표 (Gazebo world 좌표 아님!)
# SLAM 수렴 후 측정값. DB zone 테이블(충전소 waypoint)과 동기화 필요.
_INIT_POSES: dict[str, tuple[float, float, float]] = {
    '11': (0.0, -0.606, 0.0),  # P1 충전소
    '54': (0.0, -0.606, 0.0),  # P1 충전소, 동쪽(+x, 선반 방향)
    '18': (0.0, -0.899, 0.0),  # P2 충전소, 동쪽(+x, 선반 방향)
}

if TYPE_CHECKING:
    from .robot_manager import RobotManager


class ControlServiceNode:
    """ROS 2 node wrapper. Instantiate only when rclpy is available."""

    def __init__(self, robot_manager: 'RobotManager') -> None:
        import rclpy
        from rclpy.node import Node
        from std_msgs.msg import String

        self._rm = robot_manager
        self._publishers: dict = {}
        self._gz_world = os.environ.get('GZ_WORLD_NAME', 'shop')
        self._set_pose_client = None
        self._SetEntityPose = None

        from geometry_msgs.msg import PoseWithCovarianceStamped
        try:
            from rmf_fleet_msgs.msg import FleetState
        except ImportError:
            FleetState = None
        
        class _Node(Node):
            def __init__(inner_self):
                super().__init__('control_service_node')
                for rid in ROBOT_IDS:
                    rid = rid.strip()
                    # Subscribe
                    inner_self.create_subscription(
                        String, f'/robot_{rid}/status',
                        lambda msg, r=rid: self._on_status(r, msg.data), 10)
                    inner_self.create_subscription(
                        String, f'/robot_{rid}/alarm',
                        lambda msg, r=rid: self._on_alarm(r, msg.data), 10)
                    inner_self.create_subscription(
                        String, f'/robot_{rid}/cart',
                        lambda msg, r=rid: self._on_cart(r, msg.data), 10)
                    inner_self.create_subscription(
                        String, f'/robot_{rid}/snapshot',
                        lambda msg, r=rid: self._on_snapshot(r, msg.data), 10)
                    inner_self.create_subscription(
                        String, f'/robot_{rid}/customer_event',
                        lambda msg, r=rid: self._on_customer_event(r, msg.data), 10)
                    # Publish cmd
                    self._publishers[rid] = inner_self.create_publisher(
                        String, f'/robot_{rid}/cmd', 10)
                    # Publish initialpose
                    self._init_pose_publishers[rid] = inner_self.create_publisher(
                        PoseWithCovarianceStamped, f'/robot_{rid}/initialpose', 10)
                # RMF Path Monitoring
                if FleetState:
                    inner_self.create_subscription(
                        FleetState, '/fleet_states', self._on_fleet_states, 10)
                inner_self.get_logger().info('ControlServiceNode ready')

        self._init_pose_publishers: dict = {}
        self._node = _Node()
        # Wire callbacks into robot_manager
        robot_manager.publish_cmd = self.publish_cmd
        robot_manager.publish_init_pose = self.publish_init_pose
        robot_manager.publish_initialpose_at = self.publish_initialpose_at
        robot_manager.adjust_position_in_sim = self.adjust_position_in_sim

        try:
            from ros_gz_interfaces.srv import SetEntityPose
            self._SetEntityPose = SetEntityPose
            self._set_pose_client = self._node.create_client(
                SetEntityPose, f'/world/{self._gz_world}/set_pose'
            )
        except Exception as e:
            logger.warning('Gazebo SetEntityPose unavailable: %s', e)

    def publish_cmd(self, robot_id: str, payload: dict) -> None:
        from std_msgs.msg import String
        pub = self._publishers.get(robot_id.strip())
        if pub is None:
            logger.warning('No publisher for robot_id=%s', robot_id)
            return
        msg = String()
        msg.data = json.dumps(payload)
        pub.publish(msg)
        logger.debug('→ Pi robot=%s  %s', robot_id, payload)

    def publish_init_pose(self, robot_id: str) -> None:
        """AMCL 초기 위치를 /robot_<id>/initialpose 토픽으로 발행."""
        rid = robot_id.strip()
        pose_data = _INIT_POSES.get(rid)
        if pose_data is None:
            logger.warning('No init pose defined for robot_id=%s — using (0,0,0)', robot_id)
            pose_data = (0.0, 0.0, 0.0)

        x, y, yaw = pose_data
        self._publish_initialpose(rid, x, y, yaw)

    def publish_initialpose_at(self, robot_id: str, x: float, y: float, yaw: float) -> None:
        """Publish map-frame initialpose at explicit pose (real/sim common path)."""
        rid = robot_id.strip()
        self._publish_initialpose(rid, float(x), float(y), float(yaw))

    def _publish_initialpose(self, robot_id: str, x: float, y: float, yaw: float) -> None:
        """Publish /robot_<id>/initialpose with explicit map-frame pose."""
        from geometry_msgs.msg import PoseWithCovarianceStamped

        rid = robot_id.strip()
        pub = self._init_pose_publishers.get(rid)
        if pub is None:
            logger.warning('No initialpose publisher for robot_id=%s', robot_id)
            return

        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = 'map'
        # stamp을 0으로 두면 최신 시각으로 처리됨
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.pose.pose.position.z = 0.0
        # yaw → quaternion (z, w 만 필요)
        msg.pose.pose.orientation.x = 0.0
        msg.pose.pose.orientation.y = 0.0
        msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        # 공분산 (6x6 diagonal — x, y, yaw 에 적당한 불확실성)
        cov = [0.0] * 36
        cov[0]  = 0.25   # x variance
        cov[7]  = 0.25   # y variance
        cov[35] = 0.0685  # yaw variance (~15°)
        msg.pose.covariance = cov

        pub.publish(msg)
        logger.info('→ initialpose robot=%s  x=%.2f y=%.2f yaw=%.4f', rid, x, y, yaw)

    def get_node(self):
        return self._node

    def adjust_position_in_sim(self, robot_id: str, x: float, y: float, theta: float) -> bool:
        """Adjust Gazebo entity position (simulation only).

        Input x,y,theta are map-frame coordinates from Admin UI MapWidget.
        They are converted to Gazebo world coordinates when possible.
        """
        if self._set_pose_client is None or self._SetEntityPose is None:
            return False

        model_name = f'pinky_{robot_id.strip()}'

        # map → gazebo 변환 (가능할 때만). 실패 시 identity로 진행.
        gx, gy, gyaw = x, y, theta
        try:
            from shoppinkki_nav.launch_utils import map_to_gazebo
            gz = map_to_gazebo(x, y, theta)
            gx, gy, gyaw = float(gz['x']), float(gz['y']), float(gz['yaw'])
        except Exception:
            logger.debug('position_adjustment: map_to_gazebo unavailable; using identity')

        try:
            from geometry_msgs.msg import Pose
            from ros_gz_interfaces.msg import Entity
        except Exception as e:
            logger.warning('position_adjustment: missing message types: %s', e)
            return False

        # NOTE:
        # 실환경에서 ros2 CLI로는 서비스가 보이는데, 멀티스레드에서 호출되는
        # rclpy Client.wait_for_service()가 보수적으로 False를 반환하는 경우가 있다.
        # 따라서 wait_for_service에만 의존하지 않고 "호출 시도 + spin_until_future_complete"
        # 로 성공 여부를 판정한다.
        svc_name = f'/world/{self._gz_world}/set_pose'
        if not self._set_pose_client.wait_for_service(timeout_sec=0.2):
            logger.warning('position_adjustment: %s not ready (will try call anyway)', svc_name)

        req = self._SetEntityPose.Request()
        req.entity = Entity(name=model_name, type=Entity.MODEL)
        req.pose = Pose()
        req.pose.position.x = gx
        req.pose.position.y = gy
        req.pose.position.z = 0.05
        req.pose.orientation.z = math.sin(gyaw / 2.0)
        req.pose.orientation.w = math.cos(gyaw / 2.0)

        future = self._set_pose_client.call_async(req)
        try:
            # rclpy.spin()이 이미 별도 스레드에서 돌고 있으므로 여기서 다시 spin하면
            # "Executor is already spinning" 예외가 난다. Future 완료만 기다린다.
            done_evt = threading.Event()
            out: dict[str, object] = {'ok': False, 'err': None}

            def _done_cb(fut) -> None:
                try:
                    resp = fut.result()
                    out['ok'] = bool(getattr(resp, 'success', False))
                except Exception as e:
                    out['err'] = e
                finally:
                    done_evt.set()

            future.add_done_callback(_done_cb)

            if not done_evt.wait(timeout=1.5):
                logger.warning(
                    'position_adjustment: timeout waiting for service response (%s)',
                    svc_name,
                )
                return False

            if out.get('err') is not None:
                logger.exception(
                    'position_adjustment: service call failed',
                    exc_info=out['err'],
                )
                return False

            ok = bool(out.get('ok', False))
            logger.info('position_adjustment: %s → (%.3f, %.3f, %.3f) success=%s',
                        model_name, gx, gy, gyaw, ok)
            if ok:
                # Gazebo pose 이동 후 AMCL도 같은 map pose로 즉시 동기화한다.
                # 그렇지 않으면 /status가 기존 위치로 되돌아오는 현상이 발생할 수 있다.
                self._publish_initialpose(robot_id, x, y, theta)
            return ok
        except Exception:
            logger.exception('position_adjustment: unexpected error')
            return False


    def _on_status(self, robot_id: str, raw: str) -> None:
        try:
            payload = json.loads(raw)
            logger.debug('← status robot=%s mode=%s pos=(%.2f,%.2f)',
                         robot_id, payload.get('mode'), payload.get('pos_x', 0), payload.get('pos_y', 0))
            self._rm.on_status(robot_id, payload)
        except Exception as e:
            logger.error('on_status error: %s', e)

    def _on_alarm(self, robot_id: str, raw: str) -> None:
        try:
            self._rm.on_alarm(robot_id, json.loads(raw))
        except Exception as e:
            logger.error('on_alarm error: %s', e)

    def _on_cart(self, robot_id: str, raw: str) -> None:
        try:
            self._rm.on_cart(robot_id, json.loads(raw))
        except Exception as e:
            logger.error('on_cart error: %s', e)

    def _on_snapshot(self, robot_id: str, raw: str) -> None:
        try:
            self._rm.on_snapshot(robot_id, json.loads(raw))
        except Exception as e:
            logger.error('on_snapshot error: %s', e)

    def _on_customer_event(self, robot_id: str, raw: str) -> None:
        try:
            self._rm.on_customer_event(robot_id, json.loads(raw))
        except Exception as e:
            logger.error('on_customer_event error: %s', e)

    def _on_fleet_states(self, msg) -> None:
        """RMF /fleet_states에서 로봇별 전체 예상 경로 추출."""
        for rs in msg.robots:
            # pinky_54 -> 54
            name = rs.name
            if name.startswith('pinky_'):
                rid = name.replace('pinky_', '')
                path_points = [{'x': float(loc.x), 'y': float(loc.y)} for loc in rs.path]
                if path_points:
                    logger.info(f"[RMF Path] Received {len(path_points)} waypoints for robot {rid}")
                self._rm.on_rmf_path(rid, path_points)

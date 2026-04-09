"""ROS 2 node for control_service (channel G).

Subscribes:
    /robot_<id>/status    (std_msgs/String JSON)
    /robot_<id>/alarm     (std_msgs/String JSON)
    /robot_<id>/cart      (std_msgs/String JSON)
    /robot_<id>/snapshot  (std_msgs/String JSON) — 인형 감지 스냅샷

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
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

ROBOT_IDS = os.environ.get('ROBOT_IDS', '18,54').split(',')
DOMAIN_ID = int(os.environ.get('ROS_DOMAIN_ID', '14'))

# 로봇별 AMCL 초기 위치 — 맵 프레임 좌표 (Gazebo world 좌표 아님!)
# SLAM 수렴 후 측정값. DB zone 테이블(충전소 waypoint)과 동기화 필요.
_INIT_POSES: dict[str, tuple[float, float, float]] = {
    '54': (-0.056, -0.899, math.pi / 2),  # P2 충전소, map frame
    '18': (-0.056, -0.606, math.pi / 2),  # P1 충전소, map frame
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

        from geometry_msgs.msg import PoseWithCovarianceStamped

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
                    # Publish cmd
                    self._publishers[rid] = inner_self.create_publisher(
                        String, f'/robot_{rid}/cmd', 10)
                    # Publish initialpose
                    self._init_pose_publishers[rid] = inner_self.create_publisher(
                        PoseWithCovarianceStamped, f'/robot_{rid}/initialpose', 10)
                inner_self.get_logger().info('ControlServiceNode ready')

        self._init_pose_publishers: dict = {}
        self._node = _Node()
        # Wire callbacks into robot_manager
        robot_manager.publish_cmd = self.publish_cmd
        robot_manager.publish_init_pose = self.publish_init_pose

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
        from geometry_msgs.msg import PoseWithCovarianceStamped
        from builtin_interfaces.msg import Time

        rid = robot_id.strip()
        pub = self._init_pose_publishers.get(rid)
        if pub is None:
            logger.warning('No initialpose publisher for robot_id=%s', robot_id)
            return

        pose_data = _INIT_POSES.get(rid)
        if pose_data is None:
            logger.warning('No init pose defined for robot_id=%s — using (0,0,0)', robot_id)
            pose_data = (0.0, 0.0, 0.0)

        x, y, yaw = pose_data

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
        logger.info('→ initialpose robot=%s  x=%.2f y=%.2f yaw=%.4f', robot_id, x, y, yaw)

    def get_node(self):
        return self._node

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

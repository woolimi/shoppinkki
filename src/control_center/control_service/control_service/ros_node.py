"""ROS 2 node for control_service (channel G).

Subscribes:
    /robot_<id>/status  (std_msgs/String JSON)
    /robot_<id>/alarm   (std_msgs/String JSON)
    /robot_<id>/cart    (std_msgs/String JSON)

Publishes:
    /robot_<id>/cmd     (std_msgs/String JSON)

Falls back gracefully if rclpy is not available
(so the REST-only server boots even on non-ROS machines).
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

ROBOT_IDS = os.environ.get('ROBOT_IDS', '54,18').split(',')
DOMAIN_ID = int(os.environ.get('ROS_DOMAIN_ID', '14'))

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
                    # Publish
                    self._publishers[rid] = inner_self.create_publisher(
                        String, f'/robot_{rid}/cmd', 10)
                inner_self.get_logger().info('ControlServiceNode ready')

        self._node = _Node()
        # Wire publish_cmd into robot_manager
        robot_manager.publish_cmd = self.publish_cmd

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

    def get_node(self):
        return self._node

    def _on_status(self, robot_id: str, raw: str) -> None:
        try:
            self._rm.on_status(robot_id, json.loads(raw))
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

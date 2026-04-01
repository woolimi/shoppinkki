"""control_service main ROS2 node stub."""

import json
import logging
import threading
import time
from datetime import datetime, timezone

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from control_service import db
from control_service.tcp_server import TCPServer

logger = logging.getLogger(__name__)

ROBOT_IDS = ['54', '18']
ROBOT_TIMEOUT_SEC = 30
CLEANUP_INTERVAL_SEC = 10


class ControlServiceNode(Node):
    """Central control service node."""

    def __init__(self, app_bridge=None):
        super().__init__('control_service')
        self._app_bridge = app_bridge

        db.init_db()
        logger.info('[ControlService] DB initialized')

        self._tcp = TCPServer()
        self._tcp.start()

        self._status_subs = {}
        self._alarm_subs = {}
        self._cart_subs = {}
        self._cmd_pubs = {}

        for robot_id in ROBOT_IDS:
            self._status_subs[robot_id] = self.create_subscription(
                String,
                f'/robot_{robot_id}/status',
                lambda msg, rid=robot_id: self._on_status(msg, rid),
                10,
            )
            self._alarm_subs[robot_id] = self.create_subscription(
                String,
                f'/robot_{robot_id}/alarm',
                lambda msg, rid=robot_id: self._on_alarm(msg, rid),
                10,
            )
            self._cart_subs[robot_id] = self.create_subscription(
                String,
                f'/robot_{robot_id}/cart',
                lambda msg, rid=robot_id: self._on_cart(msg, rid),
                10,
            )
            self._cmd_pubs[robot_id] = self.create_publisher(
                String,
                f'/robot_{robot_id}/cmd',
                10,
            )

        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True,
        )
        self._cleanup_thread.start()

        self.get_logger().info('[ControlService] node started')

    def _on_status(self, msg: String, robot_id: str) -> None:
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        now = datetime.now(timezone.utc).isoformat()
        db.upsert_robot_status(
            robot_id=robot_id,
            mode=data.get('mode', 'UNKNOWN'),
            pos_x=data.get('pos_x', 0.0),
            pos_y=data.get('pos_y', 0.0),
            battery=data.get('battery', 0),
            last_seen=now,
        )
        if self._app_bridge:
            self._app_bridge.on_robot_status_update(robot_id, data)

    def _on_alarm(self, msg: String, robot_id: str) -> None:
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        db.insert_alarm(robot_id, data.get('event', 'UNKNOWN'))
        if self._app_bridge:
            self._app_bridge.on_alarm(robot_id, data.get('event', 'UNKNOWN'),
                                      datetime.now(timezone.utc).isoformat())

    def _on_cart(self, msg: String, robot_id: str) -> None:
        pass

    def publish_cmd(self, robot_id: str, payload: dict) -> None:
        if robot_id not in self._cmd_pubs:
            return
        msg = String()
        msg.data = json.dumps(payload)
        self._cmd_pubs[robot_id].publish(msg)

    def _cleanup_loop(self) -> None:
        while True:
            time.sleep(CLEANUP_INTERVAL_SEC)
            try:
                pass
            except Exception as e:
                logger.error(f'[cleanup] error: {e}')


def main(args=None):
    logging.basicConfig(level=logging.INFO)
    rclpy.init(args=args)
    node = ControlServiceNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

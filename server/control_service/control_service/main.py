"""control_service entry point.

Starts (all threads):
    - RobotManager (cleanup thread)
    - TCPServer     (port 8080, channels B & C)
    - CameraStream  (UDP port 9000 → YOLO)
    - ROS 2 node    (channel G, optional — skipped if rclpy unavailable)
    - Flask REST API (port 8081, main thread)
"""

from __future__ import annotations

import logging
import os
import threading

from . import db
from .camera_stream import CameraStream
from .robot_manager import RobotManager
from .rest_api import create_app
from .tcp_server import TCPServer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

REST_HOST = os.environ.get('REST_HOST', '0.0.0.0')
REST_PORT = int(os.environ.get('REST_PORT', '8081'))


def main() -> None:
    # ── 1. DB pool ────────────────────────────
    try:
        db.init_pool()
        db.reset_sessions_on_startup()
    except Exception as e:
        logger.error('Startup DB init failed: %s', e)

    # ── 2. RobotManager ───────────────────────
    rm = RobotManager()

    # ── 3. TCP server ─────────────────────────
    tcp = TCPServer(robot_manager=rm)
    threading.Thread(target=tcp.serve_forever, name='tcp-server', daemon=True).start()

    # ── 4. Camera stream ──────────────────────
    cam = CameraStream(robot_manager=rm)
    threading.Thread(target=cam.run, name='camera-stream', daemon=True).start()

    # ── 5. Start RobotManager (after cameras wired) ──
    rm.start()

    # ── 6. ROS 2 node (optional) ──────────────
    ros_node = None
    try:
        import rclpy
        rclpy.init()
        from .ros_node import ControlServiceNode
        ros_node = ControlServiceNode(robot_manager=rm)
        threading.Thread(
            target=rclpy.spin,
            args=(ros_node.get_node(),),
            name='ros-spin',
            daemon=True,
        ).start()
        logger.info('ROS 2 node started')
    except Exception as e:
        logger.warning('ROS 2 unavailable — running without Pi connectivity: %s', e)
        # Wire a no-op publish_cmd so RobotManager doesn't crash
        rm.publish_cmd = lambda robot_id, payload: logger.debug(
            '[no-ros] cmd robot=%s %s', robot_id, payload)

    # ── 7. Flask REST API (main thread) ───────
    app = create_app(robot_manager=rm, camera_stream=cam)
    logger.info('REST API starting on %s:%d', REST_HOST, REST_PORT)
    app.run(host=REST_HOST, port=REST_PORT, debug=False, use_reloader=False, threaded=True)


if __name__ == '__main__':
    main()

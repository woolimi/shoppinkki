"""BoundaryMonitor — tracks AMCL pose and fires zone-crossing callbacks.

Monitors two boundary types defined in BOUNDARY_CONFIG DB table:
    1. 결제 구역 (checkout zone):
       - TRACKING → TRACKING_CHECKOUT  on enter
       - TRACKING_CHECKOUT → TRACKING  on re-enter (exited then re-entered)
    2. 출구 (exit zone — future: block exit during TRACKING)

Only active (calls callbacks) when SM is in TRACKING or TRACKING_CHECKOUT.
In all other states pose updates are silently ignored.

Stand-alone node usage:
    ros2 run shoppinkki_core boundary_monitor
"""

from __future__ import annotations

import json
import logging
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


class Boundary:
    """Rectangular boundary region."""

    def __init__(self, name: str, x_min: float, x_max: float,
                 y_min: float, y_max: float) -> None:
        self.name = name
        self.x_min = x_min
        self.x_max = x_max
        self.y_min = y_min
        self.y_max = y_max

    def contains(self, x: float, y: float) -> bool:
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max


class BoundaryMonitor:
    """Monitors AMCL pose and fires checkout zone crossing callbacks.

    Parameters
    ----------
    boundaries:
        List of Boundary objects loaded from BOUNDARY_CONFIG table.
        Pass ``[]`` to disable all checks (useful in tests).
    on_checkout_enter:
        Called when robot enters the checkout zone while TRACKING.
    on_checkout_exit_blocked:
        Called when robot is about to exit checkout zone during checkout.
    on_checkout_reenter:
        Called when robot re-enters checkout zone while TRACKING_CHECKOUT.
    get_state:
        Callable returning current SM state string.
    node:
        Optional rclpy Node for ROS subscriptions.  Pass None for unit tests.
    """

    CHECKOUT_ZONE_NAME = '결제 구역'

    def __init__(
        self,
        boundaries: List[Boundary],
        on_checkout_enter: Optional[Callable[[], None]] = None,
        on_checkout_exit_blocked: Optional[Callable[[], None]] = None,
        on_checkout_reenter: Optional[Callable[[], None]] = None,
        get_state: Optional[Callable[[], str]] = None,
        node=None,
    ) -> None:
        self._boundaries = boundaries
        self._on_checkout_enter = on_checkout_enter
        self._on_checkout_exit_blocked = on_checkout_exit_blocked
        self._on_checkout_reenter = on_checkout_reenter
        self._get_state = get_state
        self._node = node

        self._active: bool = False
        self._in_checkout: bool = False   # whether robot was inside checkout

        # Find the checkout boundary
        self._checkout: Optional[Boundary] = next(
            (b for b in boundaries if b.name == self.CHECKOUT_ZONE_NAME), None)

        if self._checkout is None and boundaries:
            logger.warning('BoundaryMonitor: no "%s" boundary found',
                           self.CHECKOUT_ZONE_NAME)

        # Wire ROS subscription if node provided
        if node is not None:
            self._setup_ros_subscription(node)

    # ── BoundaryMonitorInterface ──────────────

    def start(self) -> None:
        self._active = True
        logger.info('BoundaryMonitor: started')

    def stop(self) -> None:
        self._active = False
        logger.info('BoundaryMonitor: stopped')

    def set_active(self, active: bool) -> None:
        self._active = active

    def set_callbacks(
        self,
        on_enter: Optional[Callable[[], None]] = None,
        on_exit_blocked: Optional[Callable[[], None]] = None,
        on_reenter: Optional[Callable[[], None]] = None,
    ) -> None:
        """체크아웃 zone 콜백을 일괄 재배선. 미지정(None) 인자는 변경하지 않는다."""
        if on_enter is not None:
            self._on_checkout_enter = on_enter
        if on_exit_blocked is not None:
            self._on_checkout_exit_blocked = on_exit_blocked
        if on_reenter is not None:
            self._on_checkout_reenter = on_reenter

    # ── Pose update (called by ROS sub or directly in tests) ──

    def on_pose_update(self, x: float, y: float) -> None:
        """Process a new AMCL pose estimate."""
        if not self._active or self._checkout is None:
            return

        state = self._get_state() if self._get_state else ''
        now_inside = self._checkout.contains(x, y)

        if now_inside and not self._in_checkout:
            # Entered checkout zone
            self._in_checkout = True
            if state == 'TRACKING':
                logger.info('BoundaryMonitor: entered checkout → enter_tracking_checkout')
                if self._on_checkout_enter:
                    self._on_checkout_enter()
            else:
                logger.info('BoundaryMonitor: entered checkout (state=%s)', state)
                if self._on_checkout_reenter:
                    self._on_checkout_reenter()

        elif not now_inside and self._in_checkout:
            # Exited checkout zone
            self._in_checkout = False
            logger.info('BoundaryMonitor: exited checkout zone (state=%s)', state)
            if self._on_checkout_exit_blocked:
                self._on_checkout_exit_blocked()

    # ── ROS wiring ────────────────────────────

    def _setup_ros_subscription(self, node) -> None:
        try:
            from geometry_msgs.msg import PoseWithCovarianceStamped
            from rclpy.qos import (
                QoSDurabilityPolicy,
                QoSHistoryPolicy,
                QoSProfile,
                QoSReliabilityPolicy,
            )

            def _pose_cb(msg):
                x = msg.pose.pose.position.x
                y = msg.pose.pose.position.y
                self.on_pose_update(x, y)

            # AMCL latches the last pose with TRANSIENT_LOCAL + RELIABLE; subscriber
            # must match or messages won't arrive at all.
            amcl_qos = QoSProfile(
                depth=1,
                reliability=QoSReliabilityPolicy.RELIABLE,
                durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
                history=QoSHistoryPolicy.KEEP_LAST,
            )
            self._amcl_sub = node.create_subscription(
                PoseWithCovarianceStamped, 'amcl_pose', _pose_cb, amcl_qos)
            logger.info('BoundaryMonitor: subscribed to amcl_pose')
        except Exception as e:
            logger.warning('BoundaryMonitor: ROS subscription failed: %s', e)


# ── Helper: load boundaries from REST API ────


def load_boundaries_from_rest(
    host: str = '127.0.0.1',
    port: int = 8081,
) -> List[Boundary]:
    """Fetch BOUNDARY_CONFIG rows from control_service REST API."""
    import urllib.request
    import json as _json
    url = f'http://{host}:{port}/boundary'
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            rows = _json.loads(resp.read())
        boundaries = []
        for row in rows:
            b = Boundary(
                name=row['description'],
                x_min=float(row['x_min']),
                x_max=float(row['x_max']),
                y_min=float(row['y_min']),
                y_max=float(row['y_max']),
            )
            boundaries.append(b)
            logger.info('Loaded boundary: %s', b.name)
        return boundaries
    except Exception as e:
        logger.warning('BoundaryMonitor: failed to load boundaries: %s', e)
        return []


# ── Stand-alone node entry point ─────────────

def main(args=None) -> None:
    import rclpy
    rclpy.init(args=args)
    import os
    from rclpy.node import Node

    class _BoundaryNode(Node):
        def __init__(self):
            super().__init__('boundary_monitor')
            host = os.environ.get('CONTROL_SERVICE_HOST', '127.0.0.1')
            port = int(os.environ.get('CONTROL_SERVICE_PORT', '8081'))
            boundaries = load_boundaries_from_rest(host, port)
            self._monitor = BoundaryMonitor(
                boundaries=boundaries,
                node=self,
            )
            self._monitor.start()
            self.get_logger().info('BoundaryMonitor node started')

    node = _BoundaryNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

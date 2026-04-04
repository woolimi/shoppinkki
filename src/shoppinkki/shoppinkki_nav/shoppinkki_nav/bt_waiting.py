"""BT 3: WAITING

Stand still. If a pedestrian is detected nearby (LiDAR), perform a small
lateral avoidance manoeuvre via Nav2, then resume waiting.

BT3 never triggers SM transitions on its own — state changes are driven
by app commands (resume_tracking / return) or WAITING_TIMEOUT (SM-level).

Returns FAILURE on timeout (WAITING_TIMEOUT exceeded).
Returns RUNNING otherwise.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional, Tuple

from shoppinkki_interfaces import BTStatus, RobotPublisherInterface

try:
    from shoppinkki_core.config import MIN_DIST, WAITING_TIMEOUT
except ImportError:
    MIN_DIST = 0.25
    WAITING_TIMEOUT = 300

# Avoidance step size in metres
AVOIDANCE_STEP = 0.30

logger = logging.getLogger(__name__)


class BTWaiting:
    """Behavior Tree for WAITING state (BT3).

    Parameters
    ----------
    publisher:
        RobotPublisherInterface — publishes /cmd_vel.
    get_scan:
        Optional callable → list[float] of LiDAR distances (full 360°).
    send_nav_goal:
        Optional callable(x, y, theta) → bool sending a Nav2 goal.
        If None, lateral avoidance is skipped.
    get_pose:
        Optional callable → (x, y, theta) current AMCL pose.
    """

    def __init__(
        self,
        publisher: RobotPublisherInterface,
        get_scan: Optional[Callable[[], List[float]]] = None,
        send_nav_goal: Optional[Callable[[float, float, float], bool]] = None,
        get_pose: Optional[Callable[[], Tuple[float, float, float]]] = None,
    ) -> None:
        self._pub = publisher
        self._get_scan = get_scan
        self._send_nav_goal = send_nav_goal
        self._get_pose = get_pose
        self._start_time: float = 0.0
        self._running: bool = False
        self._avoiding: bool = False

    # ── NavBTInterface ────────────────────────

    def start(self) -> None:
        self._start_time = time.monotonic()
        self._running = True
        self._avoiding = False
        self._pub.publish_cmd_vel(0.0, 0.0)
        logger.info('BTWaiting: started (WAITING_TIMEOUT=%ds)', WAITING_TIMEOUT)

    def stop(self) -> None:
        self._running = False
        self._pub.publish_cmd_vel(0.0, 0.0)
        logger.info('BTWaiting: stopped')

    def tick(self) -> BTStatus:
        if not self._running:
            return BTStatus.RUNNING

        elapsed = time.monotonic() - self._start_time
        if elapsed >= WAITING_TIMEOUT:
            logger.info('BTWaiting: timeout after %.0fs → FAILURE', elapsed)
            return BTStatus.FAILURE

        # ── Pedestrian avoidance ──────────────
        if not self._avoiding and self._pedestrian_nearby():
            self._do_lateral_avoidance()

        return BTStatus.RUNNING

    # ── Private helpers ───────────────────────

    def _pedestrian_nearby(self) -> bool:
        """Check if anything is closer than MIN_DIST in the forward hemisphere."""
        if self._get_scan is None:
            return False
        try:
            distances = self._get_scan()
            if not distances:
                return False
            n = len(distances)
            # Forward hemisphere: ±90° → indices 0..90 and 270..360 (1°/step)
            step = n / 360.0
            front_arc = (
                list(range(0, int(90 * step)))
                + list(range(int(270 * step), n))
            )
            valid = [distances[i] for i in front_arc if distances[i] > 0.01]
            return bool(valid) and min(valid) < MIN_DIST
        except Exception as e:
            logger.debug('BTWaiting: scan error: %s', e)
            return False

    def _do_lateral_avoidance(self) -> None:
        """Move sideways ~AVOIDANCE_STEP m to clear a passage."""
        if self._send_nav_goal is None or self._get_pose is None:
            return
        try:
            x, y, theta = self._get_pose()
            # Choose the side with more free space
            import math
            dx = math.cos(theta + math.pi / 2) * AVOIDANCE_STEP  # left
            dy = math.sin(theta + math.pi / 2) * AVOIDANCE_STEP
            # Simple heuristic: check left vs right scan clearance
            if self._get_scan is not None:
                distances = self._get_scan()
                n = len(distances)
                step = n / 360.0
                left_min = min(
                    (distances[int(60 * step)], distances[int(90 * step)]), default=9.9)
                right_min = min(
                    (distances[int(270 * step)], distances[int(300 * step)]), default=9.9)
                if right_min > left_min:  # more space on right
                    dx, dy = -dx, -dy
            goal_x = x + dx
            goal_y = y + dy
            logger.info('BTWaiting: avoidance move → (%.2f, %.2f)', goal_x, goal_y)
            self._avoiding = True
            result = self._send_nav_goal(goal_x, goal_y, theta)
            logger.info('BTWaiting: avoidance nav result=%s', result)
        except Exception as e:
            logger.debug('BTWaiting: avoidance error: %s', e)
        finally:
            self._avoiding = False
            self._pub.publish_cmd_vel(0.0, 0.0)

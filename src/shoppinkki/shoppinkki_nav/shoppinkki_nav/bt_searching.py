"""BT 2: SEARCHING

Rotate in place to re-locate the owner doll.

Behaviour:
    - Spins CCW at ANGULAR_Z_SEARCH rad/s.
    - If doll_detector.get_latest() returns a Detection → SUCCESS
      (BTRunner calls sm.resume_tracking()).
    - If elapsed time >= SEARCH_TIMEOUT → FAILURE
      (BTRunner calls sm.enter_waiting()).
    - If LiDAR detects obstacle in the current rotation direction:
        - Switch direction (CCW ↔ CW).
        - If both directions blocked → FAILURE immediately.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional

from shoppinkki_interfaces import BTStatus, DollDetectorInterface, RobotPublisherInterface

try:
    from shoppinkki_core.config import ANGULAR_Z_MAX, MIN_DIST, SEARCH_TIMEOUT
except ImportError:
    ANGULAR_Z_MAX = 1.0
    MIN_DIST = 0.25
    SEARCH_TIMEOUT = 30.0

logger = logging.getLogger(__name__)

ANGULAR_Z_SEARCH = 0.5  # rad/s rotation speed during search


class BTSearching:
    """Behavior Tree for SEARCHING state (BT2).

    Parameters
    ----------
    doll_detector:
        DollDetectorInterface — get_latest() returns Detection or None.
    publisher:
        RobotPublisherInterface — publishes /cmd_vel.
    get_scan:
        Optional callable returning list[float] of LiDAR distances.
        Full 360° scan indexed from front (0°), CCW positive.
    """

    def __init__(
        self,
        doll_detector: DollDetectorInterface,
        publisher: RobotPublisherInterface,
        get_scan: Optional[Callable[[], List[float]]] = None,
    ) -> None:
        self._detector = doll_detector
        self._pub = publisher
        self._get_scan = get_scan
        self._direction: float = 1.0  # +1 = CCW, -1 = CW
        self._start_time: float = 0.0
        self._running: bool = False

    # ── NavBTInterface ────────────────────────

    def start(self) -> None:
        self._direction = 1.0
        self._start_time = time.monotonic()
        self._running = True
        logger.info('BTSearching: started (SEARCH_TIMEOUT=%.1fs)', SEARCH_TIMEOUT)

    def stop(self) -> None:
        self._running = False
        self._pub.publish_cmd_vel(0.0, 0.0)
        logger.info('BTSearching: stopped')

    def tick(self) -> BTStatus:
        if not self._running:
            return BTStatus.RUNNING

        elapsed = time.monotonic() - self._start_time

        # ── Timeout ───────────────────────────
        if elapsed >= SEARCH_TIMEOUT:
            logger.info('BTSearching: timeout after %.1fs → FAILURE', elapsed)
            self._pub.publish_cmd_vel(0.0, 0.0)
            return BTStatus.FAILURE

        # ── Re-detected? ──────────────────────
        if self._detector.get_latest() is not None:
            logger.info('BTSearching: doll re-detected → SUCCESS')
            self._pub.publish_cmd_vel(0.0, 0.0)
            return BTStatus.SUCCESS

        # ── Obstacle check ────────────────────
        if self._get_scan is not None:
            blocked_current = self._is_blocked_in_direction(self._direction)
            if blocked_current:
                blocked_opposite = self._is_blocked_in_direction(-self._direction)
                if blocked_opposite:
                    logger.info('BTSearching: both directions blocked → FAILURE')
                    self._pub.publish_cmd_vel(0.0, 0.0)
                    return BTStatus.FAILURE
                # Switch direction
                self._direction = -self._direction
                logger.info('BTSearching: switched rotation direction')

        # ── Keep rotating ────────────────────
        self._pub.publish_cmd_vel(0.0, ANGULAR_Z_SEARCH * self._direction)
        return BTStatus.RUNNING

    # ── Private helpers ───────────────────────

    def _is_blocked_in_direction(self, direction: float) -> bool:
        """Check if rotating in `direction` is obstructed.

        Checks the lateral arc (45°~135°) on the turning side.
        direction > 0 → CCW → left side → indices 45..135 of 360-point scan.
        direction < 0 → CW  → right side → indices 225..315 (or -135..-45).
        """
        try:
            distances = self._get_scan()
            if not distances:
                return False
            n = len(distances)
            # Map angles to indices (assumes 360-point scan, 1°/index)
            step = n / 360.0
            if direction > 0:  # CCW → check left arc
                start_idx = int(45 * step)
                end_idx = int(135 * step)
            else:              # CW  → check right arc
                start_idx = int(225 * step)
                end_idx = int(315 * step)
            arc = [distances[i % n] for i in range(start_idx, end_idx)]
            valid = [d for d in arc if d > 0.01]
            return bool(valid) and min(valid) < MIN_DIST
        except Exception as e:
            logger.debug('BTSearching: scan check error: %s', e)
            return False

"""BT 1: TRACKING / TRACKING_CHECKOUT

P-Control follower + RPLiDAR obstacle avoidance (parallel).

Design:
    - doll_detector.get_latest() provides the current Detection or None.
    - publisher.publish_cmd_vel() sends velocity commands.
    - get_scan() optional callable returning a list of forward distances (m).
      If None, obstacle avoidance is disabled.
    - Returns FAILURE after N_MISS_FRAMES consecutive misses → BT Runner
      triggers enter_searching().
"""

from __future__ import annotations

import logging
import math
from typing import Callable, List, Optional

from shoppinkki_interfaces import BTStatus, DollDetectorInterface, RobotPublisherInterface

try:
    from shoppinkki_core.config import (
        ANGULAR_Z_MAX,
        IMAGE_WIDTH,
        KP_ANGLE,
        KP_DIST,
        LINEAR_X_MAX,
        MIN_DIST,
        N_MISS_FRAMES,
        TARGET_AREA,
    )
except ImportError:  # standalone / test fallback
    KP_ANGLE = 0.002
    KP_DIST = 0.0001
    TARGET_AREA = 40000
    IMAGE_WIDTH = 640
    LINEAR_X_MAX = 0.3
    ANGULAR_Z_MAX = 1.0
    MIN_DIST = 0.25
    N_MISS_FRAMES = 30

logger = logging.getLogger(__name__)


class BTTracking:
    """Behavior Tree for TRACKING and TRACKING_CHECKOUT states (BT1).

    Parameters
    ----------
    doll_detector:
        DollDetectorInterface — provides get_latest() Detection or None.
    publisher:
        RobotPublisherInterface — publishes /cmd_vel.
    get_scan:
        Optional callable returning a list[float] of LiDAR distances.
        Index 0 = front, ordered by angle increment.
        Typically the forward arc (±30°) subset is passed.
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
        self._miss_count: int = 0
        self._running: bool = False

    # ── NavBTInterface ────────────────────────

    def start(self) -> None:
        self._miss_count = 0
        self._running = True
        logger.info('BTTracking: started')

    def stop(self) -> None:
        self._running = False
        self._pub.publish_cmd_vel(0.0, 0.0)
        logger.info('BTTracking: stopped')

    def tick(self) -> BTStatus:
        if not self._running:
            return BTStatus.RUNNING

        det = self._detector.get_latest()

        if det is not None:
            # Reset miss counter
            self._miss_count = 0

            # ── P-Control ─────────────────────
            error_area = det.area - TARGET_AREA
            linear_x = KP_DIST * error_area
            linear_x = max(-LINEAR_X_MAX, min(LINEAR_X_MAX, linear_x))

            error_cx = det.cx - IMAGE_WIDTH / 2.0
            angular_z = -KP_ANGLE * error_cx  # negative: right cx → turn right
            angular_z = max(-ANGULAR_Z_MAX, min(ANGULAR_Z_MAX, angular_z))

            # ── Obstacle avoidance (post-processing) ───
            linear_x = self._apply_obstacle_avoidance(linear_x)

            self._pub.publish_cmd_vel(linear_x, angular_z)
            return BTStatus.RUNNING

        else:
            # Detection lost
            self._miss_count += 1
            self._pub.publish_cmd_vel(0.0, 0.0)

            if self._miss_count >= N_MISS_FRAMES:
                logger.info('BTTracking: %d consecutive misses → FAILURE', self._miss_count)
                return BTStatus.FAILURE

            return BTStatus.RUNNING

    # ── Private helpers ───────────────────────

    def _apply_obstacle_avoidance(self, linear_x: float) -> float:
        """Attenuate forward velocity if an obstacle is closer than MIN_DIST."""
        if self._get_scan is None or linear_x <= 0.0:
            return linear_x
        try:
            distances = self._get_scan()
            if not distances:
                return linear_x
            min_fwd = min(d for d in distances if d > 0.01)  # ignore 0-readings
            if min_fwd < MIN_DIST:
                # Scale linearly: 0 at 0 m, full speed at MIN_DIST
                factor = max(0.0, min_fwd / MIN_DIST)
                return linear_x * factor
        except Exception as e:
            logger.debug('BTTracking: scan error: %s', e)
        return linear_x

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

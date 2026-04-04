"""BT 4: GUIDING

Navigate to a zone waypoint received via the `navigate_to` command.

On SUCCESS → send `arrived` event to app, BTRunner triggers enter_waiting().
On FAILURE → send `nav_failed` event, BTRunner calls sm.resume_tracking().

The goal (x, y, theta) is set by calling set_goal() before start() —
main_node.py calls this from the _on_navigate_to() callback.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, Tuple

from shoppinkki_interfaces import BTStatus, RobotPublisherInterface

logger = logging.getLogger(__name__)


class BTGuiding:
    """Behavior Tree for GUIDING state (BT4).

    Parameters
    ----------
    publisher:
        RobotPublisherInterface — used to stop robot on failure.
    send_nav_goal:
        Callable(x, y, theta) → bool.  Sends a Nav2 NavigateToPose goal
        and BLOCKS until the goal is complete.  Returns True on success.
        This callable is executed in the BT tick thread.
    on_arrived:
        Called with zone_name when navigation succeeds.
    on_nav_failed:
        Called when navigation fails.
    """

    def __init__(
        self,
        publisher: RobotPublisherInterface,
        send_nav_goal: Optional[Callable[[float, float, float], bool]] = None,
        on_arrived: Optional[Callable[[str], None]] = None,
        on_nav_failed: Optional[Callable[[], None]] = None,
    ) -> None:
        self._pub = publisher
        self._send_nav_goal = send_nav_goal
        self._on_arrived = on_arrived
        self._on_nav_failed = on_nav_failed

        self._goal: Optional[Tuple[float, float, float]] = None
        self._zone_name: str = ''
        self._running: bool = False
        self._in_progress: bool = False
        self._result: Optional[BTStatus] = None

    # ── NavBTInterface ────────────────────────

    def start(self) -> None:
        self._running = True
        self._in_progress = False
        self._result = None
        logger.info('BTGuiding: started (goal=%s)', self._goal)

    def stop(self) -> None:
        self._running = False
        self._pub.publish_cmd_vel(0.0, 0.0)
        logger.info('BTGuiding: stopped')

    def tick(self) -> BTStatus:
        if not self._running:
            return BTStatus.RUNNING

        # Already computed result (e.g., from async callback)
        if self._result is not None:
            return self._result

        # Validate goal
        if self._goal is None:
            logger.warning('BTGuiding: no goal set → FAILURE')
            self._fire_nav_failed()
            return BTStatus.FAILURE

        if self._in_progress:
            # Nav2 action is running; return RUNNING until result arrives
            return BTStatus.RUNNING

        # ── Launch Nav2 goal ─────────────────
        self._in_progress = True
        if self._send_nav_goal is None:
            logger.warning('BTGuiding: no nav client → FAILURE')
            self._fire_nav_failed()
            return BTStatus.FAILURE

        x, y, theta = self._goal
        try:
            success = self._send_nav_goal(x, y, theta)
        except Exception as e:
            logger.error('BTGuiding: nav exception: %s', e)
            success = False

        self._in_progress = False

        if success:
            logger.info('BTGuiding: navigation succeeded')
            if self._on_arrived:
                self._on_arrived(self._zone_name)
            return BTStatus.SUCCESS
        else:
            logger.warning('BTGuiding: navigation failed')
            self._fire_nav_failed()
            return BTStatus.FAILURE

    # ── Public helpers ────────────────────────

    def set_goal(self, x: float, y: float, theta: float,
                 zone_name: str = '') -> None:
        """Set the navigation goal before or after start()."""
        self._goal = (x, y, theta)
        self._zone_name = zone_name
        self._result = None
        self._in_progress = False
        logger.info('BTGuiding: goal set → (%.2f, %.2f, θ=%.2f) zone=%s',
                    x, y, theta, zone_name)

    # ── Private helpers ───────────────────────

    def _fire_nav_failed(self) -> None:
        if self._on_nav_failed:
            self._on_nav_failed()
        self._pub.publish_cmd_vel(0.0, 0.0)

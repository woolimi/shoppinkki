"""BT 5: RETURNING / LOCKED auto-return

Sequence:
    1. Activate Keepout Filter (lifecycle_manager_filter STARTUP)
    2. GET /zone/parking/available → slot zone_id (140 | 141)
    3. Nav2 NavigateToPose to slot waypoint (theta = 90°)
    4. Deactivate Keepout Filter (PAUSE)
    5. BTRunner triggers sm.enter_charging()

On Nav2 failure → deactivate Keepout Filter, fire on_nav_failed.

The parking REST endpoint is called via `get_parking_slot` callable
to keep this class free of direct HTTP dependencies (easier to test).
"""

from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Callable, Optional, Tuple

from shoppinkki_interfaces import BTStatus, RobotPublisherInterface

logger = logging.getLogger(__name__)

# Default parking slot waypoints (overridden by REST response)
_SLOT_WAYPOINTS = {
    140: (0.0, 0.0, 1.5708),   # P1: theta=90° (north), actual coords from DB
    141: (0.0, 0.0, 1.5708),   # P2: theta=90° (north)
}


class _Phase(Enum):
    INIT = auto()
    KEEPOUT_ON = auto()
    GET_SLOT = auto()
    NAVIGATING = auto()
    KEEPOUT_OFF = auto()
    DONE = auto()
    FAILED = auto()


class BTReturning:
    """Behavior Tree for RETURNING (and LOCKED auto-return) state (BT5).

    Parameters
    ----------
    publisher:
        RobotPublisherInterface — stop robot on failure.
    get_parking_slot:
        Callable() → dict with keys ``zone_id``, ``waypoint_x``,
        ``waypoint_y``, ``waypoint_theta``.  Queries
        control_service REST GET /zone/parking/available.
        Returns None on failure.
    send_nav_goal:
        Callable(x, y, theta) → bool.  Blocks until Nav2 completes.
    set_keepout_filter:
        Callable(enable: bool) → None.  Activates/deactivates the
        lifecycle_manager_filter.  No-op if not available.
    on_nav_failed:
        Called when navigation to the parking slot fails.
    """

    def __init__(
        self,
        publisher: RobotPublisherInterface,
        get_parking_slot: Optional[Callable[[], Optional[dict]]] = None,
        send_nav_goal: Optional[Callable[[float, float, float], bool]] = None,
        set_keepout_filter: Optional[Callable[[bool], None]] = None,
        on_nav_failed: Optional[Callable[[], None]] = None,
    ) -> None:
        self._pub = publisher
        self._get_parking_slot = get_parking_slot
        self._send_nav_goal = send_nav_goal
        self._set_keepout_filter = set_keepout_filter
        self._on_nav_failed = on_nav_failed
        self._phase = _Phase.INIT
        self._running: bool = False
        self._slot: Optional[dict] = None

    # ── NavBTInterface ────────────────────────

    def start(self) -> None:
        self._phase = _Phase.INIT
        self._running = True
        self._slot = None
        logger.info('BTReturning: started')

    def stop(self) -> None:
        self._running = False
        self._pub.publish_cmd_vel(0.0, 0.0)
        logger.info('BTReturning: stopped')

    def tick(self) -> BTStatus:
        if not self._running:
            return BTStatus.RUNNING

        # ── State machine inside BT ───────────
        if self._phase == _Phase.INIT:
            return self._tick_init()

        if self._phase == _Phase.KEEPOUT_ON:
            return self._tick_keepout_on()

        if self._phase == _Phase.GET_SLOT:
            return self._tick_get_slot()

        if self._phase == _Phase.NAVIGATING:
            return self._tick_navigate()

        if self._phase == _Phase.DONE:
            return BTStatus.SUCCESS

        if self._phase == _Phase.FAILED:
            return BTStatus.FAILURE

        return BTStatus.RUNNING

    # ── Phase handlers ────────────────────────

    def _tick_init(self) -> BTStatus:
        self._phase = _Phase.KEEPOUT_ON
        return BTStatus.RUNNING

    def _tick_keepout_on(self) -> BTStatus:
        logger.info('BTReturning: activating Keepout Filter')
        self._set_keepout(True)
        self._phase = _Phase.GET_SLOT
        return BTStatus.RUNNING

    def _tick_get_slot(self) -> BTStatus:
        if self._get_parking_slot is None:
            logger.warning('BTReturning: no parking slot provider → using default P1')
            self._slot = {'zone_id': 140, 'waypoint_x': 0.0,
                          'waypoint_y': 0.0, 'waypoint_theta': 1.5708}
        else:
            try:
                self._slot = self._get_parking_slot()
            except Exception as e:
                logger.error('BTReturning: parking slot error: %s', e)
                self._slot = None

        if self._slot is None:
            logger.warning('BTReturning: no available parking slot → FAILURE')
            self._set_keepout(False)
            if self._on_nav_failed:
                self._on_nav_failed()
            self._phase = _Phase.FAILED
            return BTStatus.FAILURE

        logger.info('BTReturning: slot=%s', self._slot.get('zone_id'))
        self._phase = _Phase.NAVIGATING
        return BTStatus.RUNNING

    def _tick_navigate(self) -> BTStatus:
        if self._send_nav_goal is None or self._slot is None:
            logger.warning('BTReturning: no nav client → FAILURE')
            self._set_keepout(False)
            if self._on_nav_failed:
                self._on_nav_failed()
            self._phase = _Phase.FAILED
            return BTStatus.FAILURE

        x = float(self._slot.get('waypoint_x', 0.0))
        y = float(self._slot.get('waypoint_y', 0.0))
        theta = float(self._slot.get('waypoint_theta', 1.5708))

        logger.info('BTReturning: navigating to slot (%.2f, %.2f, θ=%.2f)',
                    x, y, theta)
        try:
            success = self._send_nav_goal(x, y, theta)
        except Exception as e:
            logger.error('BTReturning: nav exception: %s', e)
            success = False

        self._set_keepout(False)

        if success:
            logger.info('BTReturning: arrived at charging slot → SUCCESS')
            self._phase = _Phase.DONE
            return BTStatus.SUCCESS
        else:
            logger.warning('BTReturning: navigation failed → FAILURE')
            if self._on_nav_failed:
                self._on_nav_failed()
            self._phase = _Phase.FAILED
            return BTStatus.FAILURE

    # ── Private helpers ───────────────────────

    def _set_keepout(self, enable: bool) -> None:
        if self._set_keepout_filter is not None:
            try:
                self._set_keepout_filter(enable)
            except Exception as e:
                logger.warning('BTReturning: keepout filter error: %s', e)

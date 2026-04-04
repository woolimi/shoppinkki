"""BT Runner: selects and ticks the right Behavior Tree based on SM state.

BT mapping:
    BT1 (bt_tracking)  → TRACKING, TRACKING_CHECKOUT
    BT2 (bt_searching) → SEARCHING
    BT3 (bt_waiting)   → WAITING
    BT4 (bt_guiding)   → GUIDING
    BT5 (bt_returning) → RETURNING  (LOCKED auto-transitions here)
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from shoppinkki_interfaces import BTStatus, NavBTInterface

from .state_machine import ShoppinkiSM

logger = logging.getLogger(__name__)


class BTRunner:
    """Manages BT lifecycle and tick loop, driven by SM state.

    Parameters
    ----------
    sm:
        The robot's ShoppinkiSM instance.
    bt_tracking, bt_searching, bt_waiting, bt_guiding, bt_returning:
        NavBTInterface implementations for BT1~BT5.
    on_arrived:
        Called when BT4 (GUIDING) completes successfully (→ enter_waiting).
    on_nav_failed:
        Called when BT4 fails (→ resume_tracking).
    """

    def __init__(
        self,
        sm: ShoppinkiSM,
        bt_tracking: NavBTInterface,
        bt_searching: NavBTInterface,
        bt_waiting: NavBTInterface,
        bt_guiding: NavBTInterface,
        bt_returning: NavBTInterface,
        on_arrived: Optional[Callable[[], None]] = None,
        on_nav_failed: Optional[Callable[[], None]] = None,
    ) -> None:
        self.sm = sm
        self._bts = {
            'TRACKING':          bt_tracking,
            'TRACKING_CHECKOUT': bt_tracking,
            'SEARCHING':         bt_searching,
            'WAITING':           bt_waiting,
            'GUIDING':           bt_guiding,
            'RETURNING':         bt_returning,
        }
        self._active_bt: Optional[NavBTInterface] = None
        self._active_state: Optional[str] = None
        self._on_arrived = on_arrived
        self._on_nav_failed = on_nav_failed

    # ──────────────────────────────────────────
    # State change hook (called by SM callbacks)
    # ──────────────────────────────────────────

    def on_state_changed(self, new_state: str) -> None:
        """Stop the current BT and start the one for the new state."""
        # Stop previous BT
        if self._active_bt is not None:
            self._active_bt.stop()
            self._active_bt = None
            self._active_state = None

        # Start new BT if applicable
        new_bt = self._bts.get(new_state)
        if new_bt is not None:
            new_bt.start()
            self._active_bt = new_bt
            self._active_state = new_state
            logger.info('BTRunner: started BT for state=%s', new_state)
        else:
            logger.debug('BTRunner: no BT for state=%s', new_state)

    # ──────────────────────────────────────────
    # Tick loop (called at ~10 Hz from main_node timer)
    # ──────────────────────────────────────────

    def tick(self) -> None:
        """Execute one BT step and handle state transitions on result."""
        if self._active_bt is None:
            return

        status = self._active_bt.tick()
        state = self._active_state

        if status == BTStatus.RUNNING:
            return

        # ── Handle BT completion ──────────────
        if state in ('TRACKING', 'TRACKING_CHECKOUT'):
            if status == BTStatus.FAILURE:
                # N_MISS_FRAMES exceeded inside BT1
                if self.sm.state in ('TRACKING', 'TRACKING_CHECKOUT'):
                    self.sm.enter_searching()

        elif state == 'SEARCHING':
            if status == BTStatus.SUCCESS:
                # Re-detected owner
                self.sm.enter_tracking()
            elif status == BTStatus.FAILURE:
                # SEARCH_TIMEOUT
                self.sm.enter_waiting()

        elif state == 'GUIDING':
            if status == BTStatus.SUCCESS:
                # Arrived at destination
                if self._on_arrived:
                    self._on_arrived()
                self.sm.enter_waiting()
            elif status == BTStatus.FAILURE:
                # Nav2 failed
                if self._on_nav_failed:
                    self._on_nav_failed()
                self.sm.resume_tracking()

        elif state == 'RETURNING':
            if status == BTStatus.SUCCESS:
                self.sm.enter_charging()
            elif status == BTStatus.FAILURE:
                # Nav2 failed during return; retry handled by BT5 internally
                logger.warning('BTRunner: BT5 RETURNING failed; will retry')

        elif state == 'WAITING':
            if status == BTStatus.FAILURE:
                # WAITING_TIMEOUT → check cart and return / lock
                # The actual lock/return decision is made by cmd_handler
                # BT3 signals timeout via FAILURE
                logger.info('BTRunner: BT3 WAITING timeout')

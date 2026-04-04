"""ShopPinkki State Machine.

10 states:
    CHARGING → IDLE → TRACKING ↔ SEARCHING
                              ↕         ↕
                           GUIDING  WAITING
                              ↕
                    TRACKING_CHECKOUT
                              ↕
                    LOCKED → RETURNING → CHARGING
                                       (HALTED from any)

Uses the ``transitions`` library (pip install transitions).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from transitions import Machine, MachineError

logger = logging.getLogger(__name__)


class ShoppinkiSM:
    """State machine for one ShopPinkki robot.

    Parameters
    ----------
    on_state_changed:
        Called with the new state string whenever the SM transitions.
    on_locked:
        Called when entering LOCKED (before auto-transitioning to RETURNING).
    on_halted:
        Called when entering HALTED.
    on_session_end:
        Called when a session should be terminated (normal return to CHARGING,
        or staff_resolved while in CHARGING-locked).
    """

    states = [
        'CHARGING',
        'IDLE',
        'TRACKING',
        'TRACKING_CHECKOUT',
        'GUIDING',
        'SEARCHING',
        'WAITING',
        'LOCKED',
        'RETURNING',
        'HALTED',
    ]

    _transitions = [
        # ── Session start ──────────────────────────────
        # CHARGING → IDLE  (start_session cmd received)
        {'trigger': 'charging_completed',
         'source': 'CHARGING', 'dest': 'IDLE'},

        # ── Tracking ──────────────────────────────────
        # IDLE / SEARCHING / TRACKING_CHECKOUT → TRACKING
        {'trigger': 'enter_tracking',
         'source': ['IDLE', 'SEARCHING', 'TRACKING_CHECKOUT'],
         'dest': 'TRACKING'},

        # TRACKING / TRACKING_CHECKOUT → SEARCHING
        {'trigger': 'enter_searching',
         'source': ['TRACKING', 'TRACKING_CHECKOUT'],
         'dest': 'SEARCHING'},

        # ── Guiding ───────────────────────────────────
        # TRACKING / TRACKING_CHECKOUT → GUIDING  (navigate_to cmd)
        {'trigger': 'enter_guiding',
         'source': ['TRACKING', 'TRACKING_CHECKOUT'],
         'dest': 'GUIDING'},

        # ── Waiting ───────────────────────────────────
        # TRACKING / TRACKING_CHECKOUT / SEARCHING / GUIDING → WAITING
        {'trigger': 'enter_waiting',
         'source': ['TRACKING', 'TRACKING_CHECKOUT', 'SEARCHING', 'GUIDING'],
         'dest': 'WAITING'},

        # ── Resume from WAITING / GUIDING ─────────────
        {'trigger': 'resume_to_tracking',
         'source': ['WAITING', 'GUIDING'], 'dest': 'TRACKING'},

        {'trigger': 'resume_to_tracking_checkout',
         'source': ['WAITING', 'GUIDING'], 'dest': 'TRACKING_CHECKOUT'},

        # ── Checkout ──────────────────────────────────
        # TRACKING → TRACKING_CHECKOUT  (payment_success cmd)
        {'trigger': 'enter_tracking_checkout',
         'source': 'TRACKING', 'dest': 'TRACKING_CHECKOUT'},

        # ── Locked / Returning ────────────────────────
        # TRACKING / TRACKING_CHECKOUT / WAITING → LOCKED  (unpaid items)
        {'trigger': 'enter_locked',
         'source': ['TRACKING', 'TRACKING_CHECKOUT', 'WAITING'],
         'dest': 'LOCKED'},

        # TRACKING / TRACKING_CHECKOUT / WAITING / LOCKED → RETURNING
        {'trigger': 'enter_returning',
         'source': ['TRACKING', 'TRACKING_CHECKOUT', 'WAITING', 'LOCKED'],
         'dest': 'RETURNING'},

        # RETURNING → CHARGING  (BT5 Nav2 SUCCESS)
        {'trigger': 'enter_charging',
         'source': 'RETURNING', 'dest': 'CHARGING'},

        # ── Battery / HALTED ──────────────────────────
        # ANY → HALTED
        {'trigger': 'enter_halted',
         'source': '*', 'dest': 'HALTED'},

        # HALTED → CHARGING  (staff_resolved)
        {'trigger': '_trigger_staff_resolved',
         'source': 'HALTED', 'dest': 'CHARGING'},

        # ── Force terminate ───────────────────────────
        # Active states (not HALTED / LOCKED / CHARGING) → CHARGING
        {'trigger': '_force_terminate_trigger',
         'source': ['IDLE', 'TRACKING', 'TRACKING_CHECKOUT',
                    'GUIDING', 'SEARCHING', 'WAITING', 'RETURNING'],
         'dest': 'CHARGING'},
    ]

    def __init__(
        self,
        on_state_changed: Optional[Callable[[str], None]] = None,
        on_locked: Optional[Callable[[], None]] = None,
        on_halted: Optional[Callable[[], None]] = None,
        on_session_end: Optional[Callable[[], None]] = None,
    ) -> None:
        self.is_locked_return: bool = False
        self.previous_tracking_state: str = 'TRACKING'

        self._on_state_changed = on_state_changed
        self._on_locked = on_locked
        self._on_halted = on_halted
        self._on_session_end = on_session_end

        self.machine = Machine(
            model=self,
            states=ShoppinkiSM.states,
            transitions=ShoppinkiSM._transitions,
            initial='CHARGING',
            auto_transitions=False,
            ignore_invalid_triggers=False,
        )

    # ──────────────────────────────────────────
    # on_enter callbacks  (transitions 라이브러리 자동 호출)
    # ──────────────────────────────────────────

    def on_enter_IDLE(self) -> None:
        logger.info('SM → IDLE')
        self._notify('IDLE')

    def on_enter_TRACKING(self) -> None:
        self.previous_tracking_state = 'TRACKING'
        logger.info('SM → TRACKING')
        self._notify('TRACKING')

    def on_enter_TRACKING_CHECKOUT(self) -> None:
        self.previous_tracking_state = 'TRACKING_CHECKOUT'
        logger.info('SM → TRACKING_CHECKOUT')
        self._notify('TRACKING_CHECKOUT')

    def on_enter_SEARCHING(self) -> None:
        logger.info('SM → SEARCHING')
        self._notify('SEARCHING')

    def on_enter_GUIDING(self) -> None:
        logger.info('SM → GUIDING')
        self._notify('GUIDING')

    def on_enter_WAITING(self) -> None:
        logger.info('SM → WAITING')
        self._notify('WAITING')

    def on_enter_LOCKED(self) -> None:
        """Set is_locked_return and immediately auto-transition to RETURNING."""
        self.is_locked_return = True
        logger.info('SM → LOCKED  (is_locked_return=True)')
        self._notify('LOCKED')
        if self._on_locked:
            self._on_locked()
        # Immediately go to RETURNING (BT5 귀환 시작)
        self.enter_returning()

    def on_enter_RETURNING(self) -> None:
        logger.info('SM → RETURNING  (is_locked_return=%s)', self.is_locked_return)
        self._notify('RETURNING')

    def on_enter_CHARGING(self) -> None:
        logger.info('SM → CHARGING  (is_locked_return=%s)', self.is_locked_return)
        self._notify('CHARGING')
        # Normal return (not locked) → end session immediately
        if not self.is_locked_return and self._on_session_end:
            self._on_session_end()

    def on_enter_HALTED(self) -> None:
        logger.warning('SM → HALTED')
        self._notify('HALTED')
        if self._on_halted:
            self._on_halted()

    # ──────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────

    def resume_tracking(self) -> None:
        """Resume WAITING/GUIDING → TRACKING or TRACKING_CHECKOUT."""
        if self.previous_tracking_state == 'TRACKING_CHECKOUT':
            self.resume_to_tracking_checkout()
        else:
            self.resume_to_tracking()

    def handle_staff_resolved(self) -> None:
        """Handle staff_resolved command from admin.

        - HALTED state  → clear flag, transition to CHARGING.
        - CHARGING state (locked) → clear flag, end session.
        """
        self.is_locked_return = False
        if self.state == 'HALTED':
            self._trigger_staff_resolved()
        elif self.state == 'CHARGING':
            # Robot arrived at charging station with locked flag; staff resolved
            if self._on_session_end:
                self._on_session_end()
        logger.info('staff_resolved handled  (is_locked_return=False)')

    def handle_force_terminate(self) -> None:
        """Force-terminate current session and return to CHARGING.

        No-op if already in CHARGING / HALTED / LOCKED (Admin UI prevents this).
        """
        try:
            self.is_locked_return = False
            self._force_terminate_trigger()
            if self._on_session_end:
                self._on_session_end()
        except MachineError:
            logger.warning('force_terminate ignored in state=%s', self.state)

    @property
    def current_state(self) -> str:
        """Return current state string."""
        return self.state  # type: ignore[attr-defined]

    # ──────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────

    def _notify(self, new_state: str) -> None:
        if self._on_state_changed:
            self._on_state_changed(new_state)

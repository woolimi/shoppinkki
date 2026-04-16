"""Handles /robot_<id>/cmd JSON messages and routes to SM triggers.

Supported commands (채널 G):
    start_session         → charging_completed()
    mode                  → enter_waiting() / enter_returning() / enter_locked()
    resume_tracking       → sm.resume_tracking()
    navigate_to           → enter_guiding() + on_navigate_to callback
    payment_success       → enter_tracking_checkout()
    delete_item           → on_delete_item callback
    force_terminate       → sm.handle_force_terminate()
    staff_resolved        → sm.handle_staff_resolved()
    admin_goto            → on_admin_goto callback (IDLE only)
    enter_registration    → on_enter_registration callback (IDLE only, LCD 카메라 피드 전환)
    enter_simulation      → on_enter_simulation callback (IDLE only, 시뮬레이션 모드)
    registration_confirm  → on_registration_confirm callback (IDLE only, 인형 등록 확인)
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional

from .state_machine import ShoppinkiSM

logger = logging.getLogger(__name__)


class CmdHandler:
    """Parses and dispatches /robot_<id>/cmd payloads.

    Parameters
    ----------
    sm:
        The robot's ShoppinkiSM instance.
    on_navigate_to:
        Called with (zone_id, x, y, theta) when navigate_to cmd is received.
    on_delete_item:
        Called with (item_id,) when delete_item cmd is received.
    on_admin_goto:
        Called with (x, y, theta) when admin_goto is received in IDLE state.
    on_start_session:
        Called with (user_id,) after SM transitions CHARGING → IDLE.
    has_unpaid_items:
        Callable() → bool; consulted for mode=RETURNING to decide
        LOCKED vs RETURNING transition.
    on_enter_registration:
        Called (no args) when enter_registration cmd is received in IDLE.
        /register 페이지 접속 시 호출 — LCD 카메라 피드 전환.
    on_enter_simulation:
        Called (no args) when enter_simulation cmd is received in IDLE.
        시뮬레이션 모드: IDLE → TRACKING 전환 + 추종 비활성화.
    on_registration_confirm:
        Called with (bbox: dict) when registration_confirm cmd is received in IDLE.
        사용자가 앱에서 인형을 확인했을 때 호출.
    on_retake_registration:
        Called when retake_registration cmd is received in IDLE/SEARCHING.
        확인 대기 중인 후보를 해제하고 새 감지를 시작한다.
    """

    def __init__(
        self,
        sm: ShoppinkiSM,
        on_navigate_to: Optional[Callable[[int, float, float, float], None]] = None,
        on_delete_item: Optional[Callable[[int], None]] = None,
        on_admin_goto: Optional[Callable[[float, float, float], None]] = None,
        on_start_session: Optional[Callable[[str], None]] = None,
        has_unpaid_items: Optional[Callable[[], bool]] = None,
        on_enter_registration: Optional[Callable[[], None]] = None,
        on_retake_registration: Optional[Callable[[], None]] = None,
        on_enter_simulation: Optional[Callable[[], None]] = None,
        on_registration_confirm: Optional[Callable[[dict], None]] = None,
        on_navigate_through_poses: Optional[Callable[[list], None]] = None,
    on_navigate_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        self.sm = sm
        self._on_navigate_to = on_navigate_to
        self._on_navigate_through_poses = on_navigate_through_poses
        self._on_delete_item = on_delete_item
        self._on_admin_goto = on_admin_goto
        self._on_start_session = on_start_session
        self._has_unpaid_items = has_unpaid_items
        self._on_enter_registration = on_enter_registration
        self._on_retake_registration = on_retake_registration
        self._on_enter_simulation = on_enter_simulation
        self._on_registration_confirm = on_registration_confirm
        self._on_navigate_cancel = on_navigate_cancel

    def handle(self, raw: str) -> None:
        """Parse raw JSON string and dispatch to the appropriate handler."""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error('cmd_handler: invalid JSON: %s  (%s)', raw, e)
            return

        cmd = payload.get('cmd')
        if not cmd:
            logger.warning('cmd_handler: missing "cmd" field: %s', payload)
            return

        handler = self._dispatch.get(cmd)
        if handler is None:
            logger.warning('cmd_handler: unknown cmd=%s', cmd)
            return

        try:
            handler(self, payload)
        except Exception as e:
            logger.exception('cmd_handler: error handling cmd=%s: %s', cmd, e)

    # ──────────────────────────────────────────
    # Individual command handlers
    # ──────────────────────────────────────────

    def _handle_start_session(self, payload: dict) -> None:
        """세션 시작 알림 (IDLE 상태에서만 유효)."""
        user_id = payload.get('user_id', '')
        if self.sm.state != 'IDLE':
            logger.warning('start_session ignored in state=%s', self.sm.state)
            return
        if self._on_start_session:
            self._on_start_session(user_id)
        logger.info('Session started for user=%s', user_id)

    def _handle_mode(self, payload: dict) -> None:
        """mode: WAITING | RETURNING."""
        value = payload.get('value', '')
        state = self.sm.state

        if value == 'WAITING':
            if state in ('TRACKING', 'TRACKING_CHECKOUT', 'SEARCHING'):
                self.sm.enter_waiting()
            else:
                logger.warning('mode=WAITING ignored in state=%s', state)

        elif value == 'RETURNING':
            if state not in ('TRACKING', 'TRACKING_CHECKOUT', 'WAITING',
                             'GUIDING', 'SEARCHING'):
                logger.warning('mode=RETURNING ignored in state=%s', state)
                return

            unpaid = self._has_unpaid_items() if self._has_unpaid_items else False
            if state == 'WAITING':
                self.sm.waiting_exit_by_unpaid(unpaid)
            else:
                self.sm.enter_returning()

        else:
            logger.warning('mode: unknown value=%s', value)

    def _handle_resume_tracking(self, payload: dict) -> None:
        """Resume from WAITING / GUIDING to TRACKING or TRACKING_CHECKOUT."""
        if self.sm.state not in ('WAITING', 'GUIDING'):
            logger.warning('resume_tracking ignored in state=%s', self.sm.state)
            return
        self.sm.resume_tracking()

    def _handle_navigate_to(self, payload: dict) -> None:
        """TRACKING / TRACKING_CHECKOUT → GUIDING."""
        state = self.sm.state
        if state not in ('TRACKING', 'TRACKING_CHECKOUT', 'IDLE', 'WAITING',
                         'GUIDING', 'CHARGING', 'SEARCHING'):
            logger.warning('navigate_to ignored in state=%s', state)
            return

        zone_id = payload.get('zone_id', 0)
        x = float(payload.get('x', 0.0))
        y = float(payload.get('y', 0.0))
        theta = float(payload.get('theta', 0.0))

        self.sm.enter_guiding()
        if self._on_navigate_to:
            self._on_navigate_to(zone_id, x, y, theta)

    def _handle_payment_success(self, payload: dict) -> None:
        """TRACKING → TRACKING_CHECKOUT."""
        if self.sm.state != 'TRACKING':
            logger.warning('payment_success ignored in state=%s', self.sm.state)
            return
        self.sm.enter_tracking_checkout()

    def _handle_delete_item(self, payload: dict) -> None:
        """Forward item deletion to caller."""
        item_id = payload.get('item_id')
        if item_id is None:
            logger.warning('delete_item: missing item_id')
            return
        if self._on_delete_item:
            self._on_delete_item(int(item_id))

    def _handle_return_to_charger(self, payload: dict) -> None:
        """→ RETURNING (테스트/강제 복귀용)."""
        state = self.sm.state
        if state not in ('TRACKING', 'TRACKING_CHECKOUT', 'WAITING',
                         'LOCKED', 'GUIDING', 'SEARCHING', 'IDLE'):
            logger.warning('return_to_charger ignored in state=%s', state)
            return
        self.sm.enter_returning()

    def _handle_force_terminate(self, payload: dict) -> None:
        """Any active state → CHARGING (admin forced)."""
        self.sm.handle_force_terminate()

    def _handle_staff_resolved(self, payload: dict) -> None:
        """HALTED / CHARGING(locked) → reset is_locked_return + end session."""
        self.sm.handle_staff_resolved()

    def _handle_navigate_through_poses(self, payload: dict) -> None:
        """TRACKING / TRACKING_CHECKOUT → GUIDING (다중 경유점)."""
        state = self.sm.state
        if state not in ('TRACKING', 'TRACKING_CHECKOUT', 'IDLE', 'WAITING',
                         'GUIDING', 'CHARGING', 'SEARCHING'):
            logger.warning('navigate_through_poses ignored in state=%s', state)
            return

        poses = payload.get('poses', [])
        if not poses:
            logger.warning('navigate_through_poses: empty poses')
            return

        self.sm.enter_guiding()
        if self._on_navigate_through_poses:
            self._on_navigate_through_poses(poses)

    def _handle_navigate_cancel(self, payload: dict) -> None:
        """현재 Nav2 goal 취소. fleet adapter stop/replan 시 호출."""
        if self.sm.state != 'GUIDING':
            return
        if self._on_navigate_cancel:
            self._on_navigate_cancel()
        logger.info('navigate_cancel: BT4 goal cancelled')

    def _handle_admin_goto(self, payload: dict) -> None:
        """IDLE only: send Nav2 goal directly (admin test move)."""
        if self.sm.state != 'IDLE':
            logger.warning('admin_goto rejected: not in IDLE (state=%s)', self.sm.state)
            return
        x = float(payload.get('x', 0.0))
        y = float(payload.get('y', 0.0))
        theta = float(payload.get('theta', 0.0))
        if self._on_admin_goto:
            self._on_admin_goto(x, y, theta)

    def _handle_registration_confirm(self, payload: dict) -> None:
        """인형 등록 확인 (IDLE 상태에서만 유효).

        payload: {"cmd": "registration_confirm", "bbox": {...}}
        """
        if self.sm.state not in ('IDLE', 'SEARCHING'):
            logger.warning('registration_confirm ignored in state=%s (IDLE/SEARCHING 상태에서만 가능)',
                           self.sm.state)
            return
        bbox = payload.get('bbox', {})
        logger.info('registration_confirm: bbox=%s', bbox)
        if self._on_registration_confirm:
            self._on_registration_confirm(bbox)

    def _handle_enter_registration(self, payload: dict) -> None:
        """등록 시작 (IDLE 상태에서만 유효).

        /register 페이지 접속 시 호출 — _registration_active 플래그를 세워
        카메라 루프가 LCD에 카메라 피드를 표시하도록 한다.
        """
        if self.sm.state not in ('IDLE', 'SEARCHING'):
            logger.warning('enter_registration ignored in state=%s (IDLE/SEARCHING 상태에서만 가능)',
                           self.sm.state)
            return
        # Set registration flag first so any immediate state redraw can be skipped.
        if self._on_enter_registration:
            self._on_enter_registration()
        # If we were proactively searching, go back to IDLE after registration flag is active.
        if self.sm.state == 'SEARCHING':
            self.sm.enter_idle()
        logger.info('enter_registration: LCD 카메라 피드 전환')

    def _handle_retake_registration(self, payload: dict) -> None:
        """등록 재촬영 요청 (IDLE/SEARCHING에서 유효)."""
        if self.sm.state not in ('IDLE', 'SEARCHING'):
            logger.warning('retake_registration ignored in state=%s', self.sm.state)
            return
        if self._on_retake_registration:
            self._on_retake_registration()
        logger.info('retake_registration: 새 후보 감지 재개')

    def _handle_enter_simulation(self, payload: dict) -> None:
        """시뮬레이션 모드: IDLE → TRACKING + 추종 비활성화.

        주인 인형을 등록하지 않고 TRACKING 상태에 진입하되,
        P-Control 추종을 비활성화하여 로봇이 제자리에 정지한다.
        """
        if self.sm.state != 'IDLE':
            logger.warning('enter_simulation ignored in state=%s (IDLE 상태에서만 가능)',
                           self.sm.state)
            return
        logger.info('enter_simulation: IDLE → TRACKING (추종 비활성화)')
        if self._on_enter_simulation:
            self._on_enter_simulation()
        else:
            self.sm.enter_tracking()

    def _handle_force_idle(self, payload: dict) -> None:
        """강제 IDLE 전환 (테스트/디버그용)."""
        logger.info('force_idle: %s → IDLE', self.sm.state)
        self.sm.force_idle()

    # ── Dispatch table ────────────────────────

    _dispatch: dict[str, Callable] = {
        'start_session':         _handle_start_session,
        'mode':                  _handle_mode,
        'resume_tracking':       _handle_resume_tracking,
        'navigate_to':           _handle_navigate_to,
        'navigate_through_poses': _handle_navigate_through_poses,
        'navigate_cancel':       _handle_navigate_cancel,
        'payment_success':       _handle_payment_success,
        'delete_item':           _handle_delete_item,
        'return_to_charger':     _handle_return_to_charger,
        'force_terminate':       _handle_force_terminate,
        'staff_resolved':        _handle_staff_resolved,
        'admin_goto':            _handle_admin_goto,
        'enter_registration':    _handle_enter_registration,
        'retake_registration':   _handle_retake_registration,
        'enter_simulation':      _handle_enter_simulation,
        'registration_confirm':  _handle_registration_confirm,
        'force_idle':            _handle_force_idle,
    }

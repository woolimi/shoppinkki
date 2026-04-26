"""Robot state cache and business logic hub for control_service.

Responsibilities:
- Cache per-robot state (mode, pos, battery, bbox, …)
- Process incoming status / alarm / cart topics (from ros_node)
- Route admin/web commands to Pi (via publish_cmd callback)
- Cleanup thread: last_seen > 30s → OFFLINE
- Push events to TCP clients (via tcp_server callbacks)
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from . import db
from .fleet_router import FleetRouter
from shoppinkki_core.config import (
    CHECKOUT_AUTO_RETURN_FROM,
    ROBOT_TIMEOUT_SEC,
    WAITING_TIMEOUT,
)

logger = logging.getLogger(__name__)

# 쇼핑 종료(return) 시 Pi로 mode=RETURNING 릴레이 가능한 SM 상태.
# shoppinkki_core.cmd_handler._handle_mode 과 동일 집합을 유지할 것.
_RETURN_RELAY_MODES = frozenset({
    'TRACKING', 'TRACKING_CHECKOUT', 'WAITING', 'GUIDING', 'SEARCHING',
})


# ──────────────────────────────────────────────
# Data class
# ──────────────────────────────────────────────

@dataclass
class RobotState:
    robot_id: str
    mode: str = 'OFFLINE'
    pos_x: float = 0.0
    pos_y: float = 0.0
    yaw: float = 0.0
    battery: float = 100.0
    is_locked_return: bool = False
    follow_disabled: bool = False
    waiting_timeout_sec: int = WAITING_TIMEOUT
    last_seen: datetime = field(default_factory=datetime.utcnow)
    active_user_id: Optional[str] = None
    bbox: Optional[Dict] = None          # latest detection bbox from AI server
    dest_x: Optional[float] = None       # navigate_to 목적지 x
    dest_y: Optional[float] = None       # navigate_to 목적지 y
    path: List[Dict[str, float]] = field(default_factory=list)


# ──────────────────────────────────────────────
# RobotManager
# ──────────────────────────────────────────────

class RobotManager:
    """Central state manager and command router.

    Wire up callbacks after construction::

        rm = RobotManager()
        rm.publish_cmd    = ros_node.publish_cmd
        rm.push_to_admin  = tcp_server.push_to_admin
        rm.push_to_web    = tcp_server.push_to_web
        rm.start()
    """

    def __init__(self) -> None:
        self._states: Dict[str, RobotState] = {}
        self._lock = threading.Lock()
        self._running = False
        self._cleanup_thread: Optional[threading.Thread] = None
        # Debounce repeated checkout_zone_enter (pose jitter) for auto-return.
        self._last_checkout_auto_return: dict[str, float] = {}
        self._router = FleetRouter()
        # 다른 로봇이 경로를 막고 있어 대기 중인 navigate_to payload.
        # robot_id → 원본 payload. on_status 때마다 재시도해서 길이 열리면 dispatch.
        self._pending_navigate: dict[str, dict] = {}
        # 마지막 navigate_to dispatch 시각 (로봇별) — dispatch 간 최소 시차 enforce
        self._last_navigate_dispatch: dict[str, float] = {}
        # RETURNING 데드락 탐지용 — (pos_x, pos_y, 최근이동_monotonic_ts)
        self._returning_last_moved: dict[str, tuple[float, float, float]] = {}
        # 마지막 yield backoff 시각 — 반복 teleport 방지
        self._last_backoff_at: dict[str, float] = {}

        # Inject after construction
        self.publish_cmd:      Optional[Callable[[str, dict], None]] = None
        self.publish_init_pose: Optional[Callable[[str], None]] = None
        self.publish_initialpose_at: Optional[
            Callable[[str, float, float, float], None]
        ] = None
        # position adjustment in simulation world (Gazebo SetEntityPose)
        self.adjust_position_in_sim: Optional[
            Callable[[str, float, float, float], bool]
        ] = None
        self.push_to_admin:    Optional[Callable[[dict], None]] = None
        self.push_to_web:      Optional[Callable[[str, dict], None]] = None

    # ──────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────

    def start(self) -> None:
        """Load robot states from DB and start cleanup thread."""
        # 서버 재시작 시 이전 활성 세션을 유지하지 않는다.
        # (요구사항: 서버 down/up 이후 로그인 상태 초기화)
        try:
            db.reset_sessions_on_startup()
        except Exception:
            logger.exception('Startup session reset failed')

        robots = db.get_all_robots()
        with self._lock:
            for r in robots:
                self._states[r['robot_id']] = RobotState(
                    robot_id=r['robot_id'],
                    mode=r['current_mode'],
                    pos_x=float(r['pos_x']),
                    pos_y=float(r['pos_y']),
                    battery=float(r['battery_level']),
                    is_locked_return=bool(r['is_locked_return']),
                    active_user_id=r.get('active_user_id'),
                )

        self._running = True
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, name='rm-cleanup', daemon=True)
        self._cleanup_thread.start()
        logger.info('RobotManager started (%d robots)', len(self._states))

    def stop(self) -> None:
        self._running = False

    # ──────────────────────────────────────────
    # Incoming from Pi (called by ros_node)
    # ──────────────────────────────────────────

    def on_status(self, robot_id: str, payload: dict) -> None:
        """Process /robot_<id>/status JSON."""
        with self._lock:
            state = self._get_or_create(robot_id)
            prev_mode = state.mode
            state.mode = payload.get('mode', state.mode)
            state.pos_x = float(payload.get('pos_x', state.pos_x))
            state.pos_y = float(payload.get('pos_y', state.pos_y))
            state.yaw = float(payload.get('yaw', state.yaw))
            state.battery = float(payload.get('battery', state.battery))
            state.is_locked_return = bool(payload.get('is_locked_return', False))
            state.follow_disabled = bool(payload.get('follow_disabled', False))
            state.waiting_timeout_sec = int(
                payload.get('waiting_timeout_sec', state.waiting_timeout_sec)
            )
            state.last_seen = datetime.utcnow()

        # DB 갱신은 모드 변경 시에만 (위치/배터리는 메모리 캐시로 충분)
        if prev_mode != state.mode:
            db.update_robot(
                robot_id,
                current_mode=state.mode,
            )
            if prev_mode == 'OFFLINE':
                self._push_event(robot_id, 'ONLINE')
            self._push_event(
                robot_id, 'MODE_CHANGE',
                detail=f'{prev_mode} → {state.mode}',
            )
            if state.mode == 'RETURNING':
                self._end_session_if_no_unpaid_on_returning(robot_id)
                # RETURNING 진입 시 충전소까지 경로 계산 (다른 로봇 위치 회피)
                route = self._plan_return_route(robot_id, state.pos_x, state.pos_y)
                with self._lock:
                    state.path = route
                self._router.reserve(robot_id, route)
            # 경로 클리어: 도착(GUIDING→WAITING) 또는 비활성(IDLE/CHARGING) 시
            # dest도 같이 비워야 다른 로봇의 navigate_to pick 로직이 이 로봇의
            # 과거 목적지를 "점유 중"으로 오인하지 않는다.
            if state.mode in ('IDLE', 'CHARGING', 'WAITING'):
                with self._lock:
                    state.path = []
                    state.dest_x = None
                    state.dest_y = None
                self._router.release(robot_id)

        # RETURNING 중에는 매 tick 재계획해서 다른 로봇 위치 변화에 반응.
        # 새 route가 기존과 다르면 reservation 갱신 + UI push.
        if state.mode == 'RETURNING':
            new_route = self._plan_return_route(
                robot_id, state.pos_x, state.pos_y)
            if new_route and new_route != state.path:
                with self._lock:
                    state.path = new_route
                self._router.reserve(robot_id, new_route)
            # 데드락 탐지: 두 로봇이 너무 가까워 둘 다 못 움직이는 경우 yield.
            try:
                self._resolve_returning_deadlock(robot_id, state)
            except Exception:
                logger.exception('returning deadlock resolver failed')

        if state.mode == 'GUIDING':
            try:
                self._check_yield_resume(robot_id, state)
            except Exception:
                logger.exception('guiding yield resume failed')

        # Push status update to admin and web
        self._push_status(robot_id, state)

        # 경로가 막혀 대기 중인 navigate_to가 있으면 재시도 (상대 로봇이 움직였을 수 있음)
        if self._pending_navigate:
            try:
                self._retry_pending_navigates()
            except Exception:
                logger.exception('pending navigate retry failed')

        # Detect IDLE → TRACKING (registration_done)
        if prev_mode == 'IDLE' and state.mode == 'TRACKING':
            self._push_web(robot_id, {'type': 'registration_done',
                                      'robot_id': robot_id})

    def on_alarm(self, robot_id: str, payload: dict) -> None:
        """Process /robot_<id>/alarm JSON (event: LOCKED | HALTED)."""
        event = payload.get('event', '')
        logger.warning('Alarm robot=%s event=%s', robot_id, event)

        with self._lock:
            state = self._get_or_create(robot_id)
            user_id = state.active_user_id

        db.log_staff_call(robot_id, user_id, event)
        self._push_event(robot_id, event, user_id=user_id)

        self._push_admin({'type': 'alarm', 'robot_id': robot_id, 'event': event})
        self._push_web(robot_id, {'type': 'alarm', 'event': event})

    def on_cart(self, robot_id: str, payload: dict) -> None:
        """Process /robot_<id>/cart JSON and forward to web client."""
        items = payload.get('items', [])
        # customer_web expects type="cart"
        self._push_web(robot_id, {'type': 'cart', 'items': items})

    def on_snapshot(self, robot_id: str, payload: dict) -> None:
        """Process /robot_<id>/snapshot — Pi가 인형 감지 시 전송하는 스냅샷.

        browser 에 doll_detected 이벤트로 base64 이미지를 전달.
        """
        self._push_web(robot_id, {
            'type': 'doll_detected',
            'robot_id': robot_id,
            'image': payload.get('image', ''),
            'bbox': payload.get('bbox', {}),
        })
        logger.debug('snapshot → web robot=%s', robot_id)

    def on_customer_event(self, robot_id: str, payload: dict) -> None:
        """Pi /robot_<id>/customer_event — 결제 구역 진입 등 고객 UI 이벤트."""
        et = payload.get('type')
        if et == 'checkout_zone_enter':
            session = db.get_active_session_by_robot(robot_id)
            if not session:
                logger.debug('checkout_zone_enter: no session robot=%s', robot_id)
                return
            cart = db.get_cart_by_session(session['session_id'])
            if not cart:
                logger.debug('checkout_zone_enter: no cart robot=%s', robot_id)
                return
            if db.has_unpaid_items(cart['cart_id']):
                self._push_web(robot_id, {
                    'type': 'checkout_zone_enter',
                    'robot_id': robot_id,
                })
                logger.info('checkout_zone_enter → web robot=%s', robot_id)
                return

            # No unpaid items (empty or all paid): RETURNING + end session.
            with self._lock:
                st = self._states.get(robot_id)
                cached_mode = st.mode if st is not None else 'OFFLINE'
            if cached_mode not in CHECKOUT_AUTO_RETURN_FROM:
                logger.info(
                    'checkout_zone_enter: empty cart, skip auto-return '
                    '(robot=%s mode=%s)',
                    robot_id, cached_mode,
                )
                return

            _CHECKOUT_AUTO_RETURN_DEBOUNCE_S = 5.0
            now = time.monotonic()
            # check-and-set은 lock으로 보호 — 두 pose update가 거의 동시에 도착하면
            # 자동 RETURNING이 두 번 발사될 수 있다.
            with self._lock:
                last = self._last_checkout_auto_return.get(robot_id, 0.0)
                if now - last < _CHECKOUT_AUTO_RETURN_DEBOUNCE_S:
                    logger.debug(
                        'checkout_zone_enter: auto-return debounced robot=%s',
                        robot_id,
                    )
                    return
                self._last_checkout_auto_return[robot_id] = now

            user_id = session.get('user_id')
            self._relay_to_pi(robot_id, {'cmd': 'mode', 'value': 'RETURNING'})
            with self._lock:
                st = self._get_or_create(robot_id)
                prev_mode = st.mode
                st.mode = 'RETURNING'
            if prev_mode != 'RETURNING':
                db.update_robot(robot_id, current_mode='RETURNING')
            with self._lock:
                st = self._states[robot_id]
            self._push_status(robot_id, st)

            self._clear_active_cart(
                robot_id, reason='checkout_zone_enter_auto_end_empty_cart',
            )
            try:
                db.end_session(session['session_id'])
                db.update_robot(robot_id, active_user_id=None)
            except Exception:
                logger.exception(
                    'checkout_zone_enter: session end failed robot=%s', robot_id,
                )
            self.set_cached_active_user_id(robot_id, None)
            self._push_event(
                robot_id, 'SESSION_END',
                detail='checkout_zone_enter_auto_end_empty_cart',
                user_id=user_id,
            )
            self._push_web(robot_id, {'type': 'session_ended', 'robot_id': robot_id})
            logger.info(
                'checkout_zone_enter: empty cart → RETURNING + session end robot=%s',
                robot_id,
            )
        elif et == 'checkout_blocked':
            # 고객 UI 토스트용 (결제 구역 이탈 차단)
            try:
                session = db.get_active_session_by_robot(robot_id)
                user_id = session.get('user_id') if session else None
            except Exception:
                logger.exception('checkout_blocked: failed to fetch session robot=%s', robot_id)
                user_id = None
            self._push_event(
                robot_id,
                'CHECKOUT_BLOCKED',
                detail='checkout_zone_exit_blocked',
                user_id=user_id,
            )
            self._push_web(robot_id, {
                'type': 'checkout_blocked',
                'robot_id': robot_id,
            })
            logger.info('checkout_blocked → web robot=%s', robot_id)

    def _end_session_if_no_unpaid_on_returning(self, robot_id: str) -> None:
        """Auto-end session on RETURNING when there are no unpaid items."""
        try:
            session = db.get_active_session_by_robot(robot_id)
            if not session:
                return
            cart = db.get_cart_by_session(session['session_id'])
            has_unpaid = bool(cart and db.has_unpaid_items(cart['cart_id']))
            if has_unpaid:
                logger.info('RETURNING with unpaid items: keep session (robot=%s)', robot_id)
                return

            db.end_session(session['session_id'])
            db.update_robot(robot_id, active_user_id=None)
            self._push_event(
                robot_id, 'SESSION_END',
                detail='auto_end_on_returning_empty_cart',
                user_id=session.get('user_id'),
            )
            self.set_cached_active_user_id(robot_id, None)
            self._push_web(robot_id, {'type': 'session_ended', 'robot_id': robot_id})
            logger.info('Auto session end on RETURNING (robot=%s)', robot_id)
        except Exception:
            logger.exception('Auto session end failed on RETURNING (robot=%s)', robot_id)

    # ──────────────────────────────────────────
    # Commands from Admin (channel B, via tcp_server)
    # ──────────────────────────────────────────

    def handle_admin_cmd(self, robot_id: str, payload: dict) -> None:
        """Route admin commands to Pi or handle locally."""
        cmd = payload.get('cmd')
        handler = self._ADMIN_CMD_HANDLERS.get(cmd)
        if handler is not None:
            handler(self, robot_id, payload)
        elif cmd in ('mode', 'resume_tracking', 'start_session'):
            self._relay_to_pi(robot_id, payload)
        else:
            logger.warning('Unknown admin cmd=%s', cmd)

    # ── per-command handlers (admin) ──────────

    def _handle_admin_goto(self, robot_id: str, payload: dict) -> None:
        # 이동 명령: 그래프 라우팅을 거치지 않고 Nav2로 직행. IDLE에서만 허용.
        with self._lock:
            state = self._get_or_create(robot_id)
            if state.mode != 'IDLE':
                self._push_admin({
                    'type': 'admin_goto_rejected',
                    'robot_id': robot_id,
                    'reason': f'Robot is in {state.mode}, not IDLE',
                })
                return
        gx = payload.get('x')
        gy = payload.get('y')
        if gx is not None and gy is not None:
            with self._lock:
                state.dest_x = float(gx)
                state.dest_y = float(gy)
                # 직선 가시화: 현재 위치에서 목적지까지.
                state.path = [
                    {'x': state.pos_x, 'y': state.pos_y},
                    {'x': float(gx), 'y': float(gy)},
                ]
            self._router.release(robot_id)
            self._push_status(robot_id, state)
        self._relay_to_pi(robot_id, payload)

    def _handle_init_pose(self, robot_id: str, payload: dict) -> None:
        # CHARGING / IDLE 에서만 허용
        with self._lock:
            state = self._get_or_create(robot_id)
            if state.mode not in ('CHARGING', 'IDLE'):
                self._push_admin({
                    'type': 'init_pose_rejected',
                    'robot_id': robot_id,
                    'reason': f'Robot is in {state.mode}, not CHARGING/IDLE',
                })
                return
        if self.publish_init_pose:
            self.publish_init_pose(robot_id)
            logger.info('init_pose published for robot=%s', robot_id)
        else:
            logger.warning('publish_init_pose not wired; init_pose dropped for robot=%s',
                           robot_id)

    def _handle_position_adjustment(self, robot_id: str, payload: dict) -> None:
        # Position adjustment from Admin UI map click.
        # - 시뮬: Gazebo SetEntityPose + AMCL 동기화
        # - 실 로봇: AMCL-only relocalization (모델 위치는 그대로)
        x = float(payload.get('x', 0.0))
        y = float(payload.get('y', 0.0))
        theta = float(payload.get('theta', 0.0))
        ok, apply_mode = self._apply_position_adjustment(robot_id, x, y, theta)

        if not ok:
            self._push_admin({
                'type': 'position_adjustment_rejected',
                'robot_id': robot_id,
                'reason': 'position adjustment failed',
            })
            return

        # 즉시 반영: 다음 /status 수신 전에도 UI가 위치를 갱신할 수 있도록 캐시 push.
        with self._lock:
            state = self._get_or_create(robot_id)
            state.pos_x = x
            state.pos_y = y
            state.yaw = theta
            state.last_seen = datetime.utcnow()
        self._push_status(robot_id, state)
        self._push_admin({
            'type': 'position_adjustment_done',
            'robot_id': robot_id,
            'x': x, 'y': y, 'theta': theta,
            'apply_mode': apply_mode,
        })

    def _apply_position_adjustment(
        self, robot_id: str, x: float, y: float, theta: float,
    ) -> tuple[bool, str]:
        """시뮬 우선 → 실패 시 실 로봇 fallback. (성공여부, apply_mode) 반환."""
        sim_adjust = self.adjust_position_in_sim
        if sim_adjust:
            try:
                if bool(sim_adjust(robot_id, x, y, theta)):
                    return True, 'sim_pose_and_amcl'
            except Exception:
                logger.exception('admin_position_adjustment failed (robot=%s)', robot_id)

        if self.publish_initialpose_at:
            try:
                self.publish_initialpose_at(robot_id, x, y, theta)
                return True, 'amcl_only'
            except Exception:
                logger.exception(
                    'admin_position_adjustment fallback(initialpose) failed (robot=%s)',
                    robot_id,
                )
        return False, ''

    def _handle_admin_navigate_to(self, robot_id: str, payload: dict) -> None:
        # admin_ui의 "안내 이동" — IDLE에서만 허용. 나머지 라우팅은 handle_web_cmd와 동일.
        with self._lock:
            mode = self._get_or_create(robot_id).mode
        if mode != 'IDLE':
            self._push_admin({
                'type': 'admin_goto_rejected',
                'robot_id': robot_id,
                'reason': f'Robot is in {mode}, not IDLE',
            })
            return
        self.handle_web_cmd(robot_id, payload)

    def _handle_force_terminate_or_staff_resolved(
        self, robot_id: str, payload: dict,
    ) -> None:
        # 세션 강제 종료/잠금 해제 시 다음 로그인에 장바구니가 남지 않도록 정리.
        cmd = payload.get('cmd')
        self._clear_active_cart(robot_id, reason=cmd)
        if cmd == 'staff_resolved':
            try:
                session = db.get_active_session_by_robot(robot_id)
                if session:
                    db.end_session(session['session_id'])
                # Cache는 즉시 DB 정리를 반영 (Pi status는 지연 가능).
                self.set_cached_active_user_id(robot_id, None)
            except Exception:
                logger.exception('staff_resolved: failed to end session (robot=%s)', robot_id)
        self._relay_to_pi(robot_id, payload)

    _ADMIN_CMD_HANDLERS: dict = {
        'admin_goto': _handle_admin_goto,
        'init_pose': _handle_init_pose,
        'admin_position_adjustment': _handle_position_adjustment,
        'navigate_to': _handle_admin_navigate_to,
        'force_terminate': _handle_force_terminate_or_staff_resolved,
        'staff_resolved': _handle_force_terminate_or_staff_resolved,
    }

    # ──────────────────────────────────────────
    # Commands from customer_web (channel C, via tcp_server or REST)
    # ──────────────────────────────────────────

    def handle_web_cmd(self, robot_id: str, payload: dict) -> None:
        """Route customer_web commands."""
        cmd = payload.get('cmd')

        if cmd == 'process_payment':
            self._handle_process_payment(robot_id, payload)
        elif cmd == 'qr_scan':
            self._handle_qr_scan(robot_id, payload)
        elif cmd == 'update_quantity':
            self._handle_update_quantity(robot_id, payload)
        elif cmd == 'delete_item':
            self._handle_delete_item(robot_id, payload)
        elif cmd == 'get_path_preview':
            zone_id = payload.get('zone_id')
            if zone_id is None:
                return
            wp_name = self._pick_waypoint_for_zone(robot_id, zone_id)
            if wp_name:
                with self._lock:
                    st = self._get_or_create(robot_id)
                    rx, ry = st.pos_x, st.pos_y
                blocked = self._vertices_blocked_by_others(robot_id)
                route = self._router.plan(
                    robot_id, (rx, ry), wp_name, blocked_vertices=blocked)
                self._push_web(robot_id, {
                    'type': 'find_product_path',
                    'robot_id': robot_id,
                    'zone_id': zone_id,
                    'path': route,
                })
        elif cmd == 'navigate_to':
            self._dispatch_navigate_to(robot_id, payload)
        elif cmd in ('mode', 'resume_tracking',
                     'start_session', 'enter_simulation',
                     'return', 'registration_confirm', 'enter_registration',
                     'retake_registration'):
            if cmd == 'return':
                # 쇼핑 종료: 미결제 물건이 있으면 LOCKED 귀환(세션 유지),
                # 비어있으면 RETURNING 귀환(세션/장바구니 정리).
                #
                # Pi는 cmd='return'을 처리하지 않으므로 mode로 변환해 전달한다.

                def _has_unpaid_items() -> bool:
                    try:
                        session = db.get_active_session_by_robot(robot_id)
                        if not session:
                            return False
                        cart = db.get_cart_by_session(session['session_id'])
                        if not cart:
                            return False
                        return bool(db.has_unpaid_items(cart['cart_id']))
                    except Exception:
                        logger.exception('return: failed to check unpaid (robot=%s)', robot_id)
                        return False

                has_unpaid = _has_unpaid_items()
                # UX: even for unpaid cart, keep mode=RETURNING so UIs show
                # "returning to charger", while is_locked_return drives the locked styling.
                target_mode = 'RETURNING'

                def _finish_shopping_session() -> None:
                    # Only finish session when cart is empty/all-paid.
                    if has_unpaid:
                        return
                    self._clear_active_cart(robot_id, reason='return')
                    try:
                        session = db.get_active_session_by_robot(robot_id)
                        if session:
                            db.end_session(session['session_id'])
                        # Always clear ROBOT.active_user_id on shopping end.
                        db.update_robot(robot_id, active_user_id=None)
                    except Exception:
                        logger.exception(
                            'Failed to end session on return (robot=%s)', robot_id)
                    self.set_cached_active_user_id(robot_id, None)

                with self._lock:
                    st = self._states.get(robot_id)
                cached_mode = st.mode if st is not None else 'OFFLINE'
                if cached_mode not in _RETURN_RELAY_MODES:
                    logger.info(
                        'return: skip Pi %s (robot=%s cached_mode=%s; '
                        'need TRACKING/TRACKING_CHECKOUT/WAITING/GUIDING/SEARCHING)',
                        target_mode, robot_id, cached_mode,
                    )
                    # If unpaid exists, keep session and do not clear cart.
                    _finish_shopping_session()
                    return
                payload = dict(payload)
                payload.pop('cmd', None)
                payload_to_pi = {
                    'cmd': 'mode',
                    'value': target_mode,
                }
                if has_unpaid:
                    payload_to_pi['is_locked_return'] = True
                payload_to_pi.update(payload)
                self._relay_to_pi(robot_id, payload_to_pi)
                # 관제 UI·REST용 메모리/DB 즉시 반영 (Pi status 수신 전 지연 방지)
                with self._lock:
                    st = self._get_or_create(robot_id)
                    prev_mode = st.mode
                    st.mode = target_mode
                    if has_unpaid:
                        st.is_locked_return = True
                if prev_mode != target_mode:
                    if has_unpaid:
                        db.update_robot(
                            robot_id,
                            current_mode=target_mode,
                            is_locked_return=True,
                        )
                    else:
                        db.update_robot(robot_id, current_mode=target_mode)
                with self._lock:
                    st = self._states[robot_id]
                self._push_status(robot_id, st)
                _finish_shopping_session()
                return
            self._relay_to_pi(robot_id, payload)
        else:
            logger.warning('Unknown web cmd=%s', cmd)

    def _handle_process_payment(self, robot_id: str, payload: dict) -> None:
        """Mark cart items as paid and relay payment_success to Pi."""
        session = db.get_active_session_by_robot(robot_id)
        if not session:
            logger.warning('process_payment: no active session for robot=%s', robot_id)
            return
        cart = db.get_cart_by_session(session['session_id'])
        if not cart:
            logger.warning('process_payment: no cart for session=%s',
                           session['session_id'])
            return

        db.mark_items_paid(cart['cart_id'])
        self._push_event(robot_id, 'PAYMENT_SUCCESS', user_id=session['user_id'])
        self._relay_to_pi(robot_id, {'cmd': 'payment_success'})
        # customer_web listens to "payment_done" (not "payment_success")
        self._push_web(robot_id, {'type': 'payment_done', 'robot_id': robot_id})
        # UX: 결제 완료 후 고객 장바구니 즉시 비우기 (세션은 유지)
        self._push_web(robot_id, {'type': 'cart', 'robot_id': robot_id, 'items': []})
        logger.info('Payment processed for robot=%s', robot_id)

    def _handle_qr_scan(self, robot_id: str, payload: dict) -> None:
        """시뮬레이션 모드: 웹 카메라 QR 스캔 → 장바구니 추가.

        QR 데이터 형식: JSON {"product_name": "...", "price": N}
        """
        qr_data = payload.get('qr_data', '')
        session = db.get_active_session_by_robot(robot_id)
        if not session:
            logger.warning('qr_scan: no active session for robot=%s', robot_id)
            return
        cart = db.get_cart_by_session(session['session_id'])
        if not cart:
            logger.warning('qr_scan: no cart for session=%s', session['session_id'])
            return

        # QR 데이터 파싱
        try:
            item = json.loads(qr_data)
            product_name = item.get('product_name', item.get('name', ''))
            price = int(item.get('price', 0))
        except (json.JSONDecodeError, ValueError):
            # JSON이 아니면 텍스트 자체를 상품명으로 사용
            product_name = qr_data.strip()
            price = 0

        if not product_name:
            logger.warning('qr_scan: empty product_name from QR data=%s', qr_data[:100])
            return

        item_id = db.add_cart_item(cart['cart_id'], product_name, price)
        logger.info('qr_scan: added item=%d (%s, %d원) for robot=%s',
                     item_id, product_name, price, robot_id)

        # 장바구니 갱신 push
        items = db.get_cart_items(cart['cart_id'])
        self._push_web(robot_id, {
            'type': 'cart',
            'items': self._format_cart_items(items),
        })

    def _handle_update_quantity(self, robot_id: str, payload: dict) -> None:
        """장바구니 항목 수량 변경."""
        item_id  = payload.get('item_id')
        quantity = payload.get('quantity')
        if item_id is None or quantity is None:
            return
        db.update_cart_item_quantity(item_id, int(quantity))
        session = db.get_active_session_by_robot(robot_id)
        if not session:
            return
        cart = db.get_cart_by_session(session['session_id'])
        if not cart:
            return
        items = db.get_cart_items(cart['cart_id'])
        self._push_web(robot_id, {
            'type': 'cart',
            'items': self._format_cart_items(items),
        })

    def _handle_delete_item(self, robot_id: str, payload: dict) -> None:
        """장바구니 항목 삭제."""
        item_id = payload.get('item_id')
        if item_id is None:
            return
        db.delete_cart_item(int(item_id))
        session = db.get_active_session_by_robot(robot_id)
        if not session:
            return
        cart = db.get_cart_by_session(session['session_id'])
        if not cart:
            return
        items = db.get_cart_items(cart['cart_id'])
        self._push_web(robot_id, {
            'type': 'cart',
            'items': self._format_cart_items(items),
        })

    @staticmethod
    def _format_cart_items(rows: list) -> list:
        """DB CART_ITEM 행을 브라우저 스펙(id/name/quantity) 형식으로 변환."""
        return [{
            'id':       r['item_id'],
            'name':     r['product_name'],
            'price':    r['price'],
            'quantity': r.get('quantity', 1),
            'is_paid':  bool(r['is_paid']),
        } for r in rows]

    def _clear_active_cart(self, robot_id: str, reason: str) -> None:
        """해당 로봇의 활성 세션 장바구니를 비우고 웹에 empty cart push."""
        try:
            session = db.get_active_session_by_robot(robot_id)
            if not session:
                return
            cart = db.get_cart_by_session(session['session_id'])
            if not cart:
                return
            db.delete_cart_items(cart['cart_id'])
            self._push_event(robot_id, 'CART_CLEARED',
                             detail=f'reason={reason}',
                             user_id=session.get('user_id'))
            # 브라우저 장바구니 즉시 비우기
            self._push_web(robot_id, {'type': 'cart', 'items': []})
            logger.info('Cleared cart for robot=%s (reason=%s)', robot_id, reason)
        except Exception:
            logger.exception('Failed to clear cart for robot=%s (reason=%s)', robot_id, reason)

    # ──────────────────────────────────────────
    # Bbox update (from camera_stream / AI server)
    # ──────────────────────────────────────────

    def update_bbox(self, robot_id: str, bbox: Optional[dict]) -> None:
        with self._lock:
            state = self._get_or_create(robot_id)
            state.bbox = bbox

    # ──────────────────────────────────────────
    # Getters
    # ──────────────────────────────────────────

    def get_state(self, robot_id: str) -> Optional[RobotState]:
        with self._lock:
            return self._states.get(robot_id)

    def get_all_states(self) -> Dict[str, RobotState]:
        with self._lock:
            return dict(self._states)

    def set_cached_active_user_id(
        self, robot_id: str, user_id: Optional[str],
    ) -> None:
        """In-memory cache for GET /robots active_user_id."""
        with self._lock:
            st = self._states.get(robot_id)
            if st is not None:
                st.active_user_id = user_id

    def sync_active_user_from_db(self, robot_id: str) -> None:
        """Copy ROBOT.active_user_id from DB into this process's RobotState cache."""
        row = db.get_robot(robot_id)
        uid = (row or {}).get('active_user_id')
        self.set_cached_active_user_id(robot_id, uid)

    def get_available_parking(self) -> dict:
        """메모리 캐시 기반 빈 충전소 슬롯 조회."""
        slots = db.get_parking_slots()  # ZONE 140, 141 정보
        with self._lock:
            for slot in slots:
                occupied = False
                for state in self._states.values():
                    if state.mode in ('OFFLINE', 'HALTED'):
                        continue
                    if (abs(state.pos_x - slot['waypoint_x']) < 0.15 and
                            abs(state.pos_y - slot['waypoint_y']) < 0.15):
                        occupied = True
                        break
                if not occupied:
                    return slot
        # 둘 다 점유 시 P1 반환
        return slots[0] if slots else {}

    # ──────────────────────────────────────────
    # Cleanup thread
    # ──────────────────────────────────────────

    def _cleanup_loop(self) -> None:
        while self._running:
            time.sleep(10)
            threshold = datetime.utcnow() - timedelta(seconds=ROBOT_TIMEOUT_SEC)
            offline: list[tuple[str, 'RobotState']] = []
            with self._lock:
                for robot_id, state in self._states.items():
                    if state.last_seen < threshold and state.mode != 'OFFLINE':
                        state.mode = 'OFFLINE'
                        state.active_user_id = None
                        offline.append((robot_id, state))
            # DB / TCP push outside lock to avoid blocking Flask threads
            for robot_id, state in offline:
                logger.info('Robot %s → OFFLINE (timeout)', robot_id)
                db.update_robot(
                    robot_id,
                    current_mode='OFFLINE',
                    active_user_id=None,
                )
                self._push_event(robot_id, 'OFFLINE')
                self._push_status(robot_id, state)

    # ──────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────

    _OCCUPY_DIST = 0.25

    def _route_to_poses(self, route: list[dict], dest_wp_name: str) -> list[dict]:
        """route [{x,y}, ...] 에 theta를 추가하여 [{x,y,theta}, ...] 반환."""
        waypoints = db.get_fleet_waypoints()
        wp_by_name = {w['name']: w for w in waypoints}

        poses = []
        for i, pt in enumerate(route):
            if i == len(route) - 1:
                # 최종 목적지: 저장된 orientation 사용
                dest = wp_by_name.get(dest_wp_name)
                theta = float(dest['theta']) if dest and dest.get('theta') else 0.0
            else:
                # 중간 waypoint: 무조건 "다음 waypoint 방향"으로 heading.
                # pickup_zone 이 중간에 끼어도 선반 쪽을 쳐다보지 않게 하여,
                # 로봇이 중간에 멈춰서 회전하는 걸 방지한다.
                dx = route[i + 1]['x'] - pt['x']
                dy = route[i + 1]['y'] - pt['y']
                theta = math.atan2(dy, dx) if (abs(dx) > 0.001 or abs(dy) > 0.001) else 0.0

            poses.append({'x': pt['x'], 'y': pt['y'], 'theta': round(theta, 4)})
        return poses

    # ──────────────────────────────────────────
    # navigate_to dispatch (with path-blocking wait queue)
    # ──────────────────────────────────────────

    _BLOCK_RADIUS = 0.3  # 다른 로봇이 경로 vertex 근처 이 거리 이내면 "막혔다"
    # Dispatch 시차: 직전 N초 이내에 다른 로봇이 dispatch됐고, 내가 그 로봇에
    # _STAGGER_RADIUS 이내로 가까이 있으면 스스로도 잠깐 대기. 두 로봇이
    # 동시에 출발하며 서로의 lidar 간섭으로 local_costmap에 장애물로 찍혀
    # 멈추는 것을 방지.
    _STAGGER_WINDOW_S = 5.0
    _STAGGER_RADIUS = 1.0
    # 경로계획 시 "다른 로봇의 현 위치가 이 반경 안에 있는 vertex"를 blocked로
    # 간주 — 그 vertex로 향하는 edge에 큰 penalty 부여하여 우회.
    _VERTEX_BLOCK_RADIUS = 0.25

    # RETURNING 데드락 파라미터
    _DEADLOCK_PROXIMITY = 0.35   # 두 로봇이 이 거리 이내 + 둘 다 정지면 deadlock
    _DEADLOCK_STATIONARY_S = 5.0  # 이 시간만큼 안 움직이면 정지로 간주
    _DEADLOCK_MOVE_EPSILON = 0.05  # 이만큼 넘게 이동해야 "움직임"으로 인정
    _DEADLOCK_BACKOFF_M = 0.35    # yield 로봇을 반대 방향으로 이 거리 teleport
    _DEADLOCK_BACKOFF_COOLDOWN_S = 8.0  # 연속 teleport 방지

    def _resolve_returning_deadlock(
        self, robot_id: str, state: RobotState,
    ) -> None:
        """두 로봇이 RETURNING 중 너무 가까워 움직이지 못하면 한 쪽을
        반대 방향으로 teleport(시뮬)해서 데드락 해제.

        Yield 선택: robot_id 사전순으로 나중이 yield. (54 > 18 → 54 yield)
        """
        now = time.monotonic()

        # 내 정지 상태 추적
        last = self._returning_last_moved.get(robot_id)
        if last is None:
            self._returning_last_moved[robot_id] = (
                state.pos_x, state.pos_y, now)
            return
        lx, ly, lt = last
        moved = math.hypot(state.pos_x - lx, state.pos_y - ly) \
            > self._DEADLOCK_MOVE_EPSILON
        if moved:
            self._returning_last_moved[robot_id] = (
                state.pos_x, state.pos_y, now)
            return
        if now - lt < self._DEADLOCK_STATIONARY_S:
            return

        # 근거리 RETURNING 상대 로봇 찾기
        partner_id: Optional[str] = None
        partner_pos: Optional[tuple[float, float]] = None
        with self._lock:
            for rid, other in self._states.items():
                if rid == robot_id or other.mode != 'RETURNING':
                    continue
                if math.hypot(other.pos_x - state.pos_x,
                              other.pos_y - state.pos_y) \
                        < self._DEADLOCK_PROXIMITY:
                    partner_id = rid
                    partner_pos = (other.pos_x, other.pos_y)
                    break
        if partner_id is None or partner_pos is None:
            return

        # Yield 결정 — 사전순 나중(=더 큰 ID)가 양보
        if robot_id <= partner_id:
            return

        # teleport cooldown
        if now - self._last_backoff_at.get(robot_id, 0.0) \
                < self._DEADLOCK_BACKOFF_COOLDOWN_S:
            return

        # 반대 방향 단위벡터
        dx = state.pos_x - partner_pos[0]
        dy = state.pos_y - partner_pos[1]
        d = math.hypot(dx, dy)
        if d < 1e-3:
            # 완전히 겹치면 +x 방향으로 대피
            ux, uy = 1.0, 0.0
        else:
            ux, uy = dx / d, dy / d
        back_x = state.pos_x + ux * self._DEADLOCK_BACKOFF_M
        back_y = state.pos_y + uy * self._DEADLOCK_BACKOFF_M
        back_theta = state.yaw

        adjust = self.adjust_position_in_sim
        if adjust is None:
            logger.warning(
                'deadlock yield needed (robot=%s ↔ %s) but sim teleport '
                'unavailable — skipping (real robot needs manual unstuck)',
                robot_id, partner_id)
            return

        try:
            ok = bool(adjust(robot_id, back_x, back_y, back_theta))
        except Exception:
            logger.exception('deadlock teleport failed (robot=%s)', robot_id)
            return

        if not ok:
            return

        self._last_backoff_at[robot_id] = now
        # 방금 옮긴 위치를 기준으로 다시 정지 타이머 초기화
        self._returning_last_moved[robot_id] = (back_x, back_y, now)
        logger.info(
            'RETURNING deadlock: robot=%s yields to robot=%s → '
            'teleport (%.3f, %.3f)',
            robot_id, partner_id, back_x, back_y,
        )
        # UI에 즉시 반영 + 이벤트 push
        with self._lock:
            state.pos_x = back_x
            state.pos_y = back_y
            state.yaw = back_theta
        self._push_event(
            robot_id, 'YIELD_BACKOFF',
            detail=f'deadlock yield to {partner_id}')

    # ──────────────────────────────────────────
    # GUIDING preemptive yield
    # ──────────────────────────────────────────

    def _guiding_remaining(
        self, state: 'RobotState', route: list[dict],
    ) -> float:
        """현재 위치 → route polyline 길이. route 가 비었거나 1개 이하면
        (dest_x, dest_y) 까지 직선거리 fallback."""
        if not route or len(route) < 2:
            if state.dest_x is None or state.dest_y is None:
                return 0.0
            return math.hypot(state.dest_x - state.pos_x,
                              state.dest_y - state.pos_y)
        total = math.hypot(route[0]['x'] - state.pos_x,
                           route[0]['y'] - state.pos_y)
        for a, b in zip(route, route[1:]):
            total += math.hypot(b['x'] - a['x'], b['y'] - a['y'])
        return total

    _YIELD_PARTNER_CLEARANCE_M = 0.25

    def _pick_yield_vertex(
        self,
        route_idx: list[int],
        entry_idx: int,
        partner_route_idx: list[int],
        partner_pos: tuple[float, float],
        my_pos: tuple[float, float],
        all_wps: list[dict],
    ) -> Optional[dict]:
        """Loser 양보 vertex 선택 (3단계).

        1차: route 위 entry_idx 직전 vertex 들을 역순 훑어 holding_point 이면서
             winner 경로 vertex 아닌 것
        2차: route 밖 holding_point 중 winner 경로·현 위치에서 충분히 떨어진 것 중
             내 현 위치에서 가장 가까운 것
        3차: 후보 없음 → None (caller 가 in-place wait 처리)
        """
        wp_by_idx = {w['idx']: w for w in all_wps}
        winner_vertices = set(partner_route_idx)

        # 1차
        for i in range(entry_idx - 1, -1, -1):
            v = route_idx[i]
            wp = wp_by_idx.get(v)
            if wp is None:
                continue
            if wp.get('holding_point', False) and v not in winner_vertices:
                return wp

        # 2차
        candidates: list[tuple[float, dict]] = []
        for wp in all_wps:
            if not wp.get('holding_point', False):
                continue
            if wp['idx'] in winner_vertices:
                continue
            d_partner = math.hypot(wp['x'] - partner_pos[0],
                                   wp['y'] - partner_pos[1])
            if d_partner < self._YIELD_PARTNER_CLEARANCE_M:
                continue
            d_me = math.hypot(wp['x'] - my_pos[0], wp['y'] - my_pos[1])
            candidates.append((d_me, wp))
        if candidates:
            candidates.sort(key=lambda t: t[0])
            return candidates[0][1]

        # 3차
        return None

    def _resolve_guiding_conflict(
        self,
        robot_id: str,
        route: list[dict],
        payload: dict,
    ) -> tuple[list[dict], bool]:
        """GUIDING dispatch 중 경로 충돌 감지 & 해소.

        Returns: (used_route, should_proceed)
          - should_proceed=True  → caller 는 원래 흐름 계속 (reserve + dispatch)
          - should_proceed=False → loser 분기 — 이 함수 내부에서 축소 경로 dispatch
                                   또는 in-place wait 까지 완료. caller 는 early return.
        """
        info = self._router.detect_conflict(route, robot_id)
        if info is None:
            return route, True

        # 잔여거리 비교
        with self._lock:
            my_state = self._states.get(robot_id)
            partner_state = self._states.get(info.partner_id)
        if my_state is None or partner_state is None:
            return route, True

        my_remaining = self._guiding_remaining(my_state, route)
        partner_remaining = self._guiding_remaining(
            partner_state, partner_state.path or [])

        # Tiebreaker: 차이 < 0.05m 이면 사전순 앞이 winner
        if abs(my_remaining - partner_remaining) < 0.05:
            im_winner = robot_id < info.partner_id
        else:
            im_winner = my_remaining < partner_remaining

        if im_winner:
            return route, True   # 원 route 로 진행

        # Loser: yield vertex 선택
        all_wps = db.get_fleet_waypoints()
        route_idx = self._router._route_to_idx_path(route)
        partner_route_idx = self._router._route_to_idx_path(partner_state.path or [])
        yield_wp = self._pick_yield_vertex(
            route_idx=route_idx,
            entry_idx=info.conflict_entry_idx,
            partner_route_idx=partner_route_idx,
            partner_pos=(partner_state.pos_x, partner_state.pos_y),
            my_pos=(my_state.pos_x, my_state.pos_y),
            all_wps=all_wps,
        )

        # 원 payload 는 resume 용으로 보존
        self._pending_navigate[robot_id] = dict(payload)

        if yield_wp is None:
            # 3차: in-place wait — 예약 release, Pi 에 아무 것도 보내지 않음
            self._router.release(robot_id)
            with self._lock:
                my_state.path = []
            self._push_event(
                robot_id, 'YIELD_HOLD',
                detail=f'in-place wait for {info.partner_id} (no candidate)',
            )
            return [], False

        # 축소 경로: 현 위치 근처 → yield_wp
        yield_route = self._router.plan(
            robot_id, (my_state.pos_x, my_state.pos_y), yield_wp['name'],
        )
        if not yield_route or len(yield_route) < 2:
            # 경로 계산 실패 → in-place wait
            self._router.release(robot_id)
            with self._lock:
                my_state.path = []
            self._push_event(
                robot_id, 'YIELD_HOLD',
                detail=f'in-place wait for {info.partner_id} (plan fail)',
            )
            return [], False

        with self._lock:
            my_state.path = yield_route
        self._router.reserve(robot_id, yield_route)

        poses = self._route_to_poses(yield_route, yield_wp['name'])
        self._relay_to_pi(robot_id, {
            'cmd': 'navigate_through_poses',
            'poses': poses,
        })
        self._push_event(
            robot_id, 'YIELD_HOLD',
            detail=f'yield to {info.partner_id} at {yield_wp["name"]}',
        )
        logger.info(
            'GUIDING yield: robot=%s → holding_point=%s (partner=%s, type=%s)',
            robot_id, yield_wp['name'], info.partner_id, info.conflict_type,
        )
        return yield_route, False

    def _check_yield_resume(
        self, robot_id: str, state: 'RobotState',
    ) -> None:
        """대기 중이던 loser 가 원 목적지로 재출발할 수 있는지 검사."""
        original = self._pending_navigate.get(robot_id)
        if not original:
            return
        if state.mode != 'GUIDING':
            # GUIDING 아니면 대기 자체가 무의미 — 큐에서 제거
            self._pending_navigate.pop(robot_id, None)
            return

        zone_id = original.get('zone_id')
        if zone_id is None:
            self._pending_navigate.pop(robot_id, None)
            return

        wp_name = self._pick_waypoint_for_zone(robot_id, zone_id)
        if not wp_name:
            return

        blocked = self._vertices_blocked_by_others(robot_id)
        candidate = self._router.plan(
            robot_id, (state.pos_x, state.pos_y), wp_name,
            blocked_vertices=blocked,
        )
        if not candidate:
            return

        if self._router.detect_conflict(candidate, robot_id) is not None:
            return

        # 충돌 해소 — 원 payload 로 재dispatch
        payload_copy = dict(original)
        self._pending_navigate.pop(robot_id, None)
        self._dispatch_navigate_to(robot_id, payload_copy)
        self._push_event(
            robot_id, 'YIELD_CLEAR',
            detail=f'resumed to zone={zone_id}',
        )

    def _plan_return_route(
        self, robot_id: str, pos_x: float, pos_y: float,
    ) -> list[dict]:
        """RETURNING용 충전소 복귀 경로 — 다른 로봇 위치 회피.

        하단 구역(y < -1.2 AND x < 0.3)은 그래프 노드가 없는 좁은 통로이므로
        고정 경유점(출구2 → 하단_복도)을 먼저 붙이고 나머지는 그래프 plan.
        """
        charger = 'P2' if robot_id == '54' else 'P1'
        blocked = self._vertices_blocked_by_others(robot_id)
        if pos_y < -1.2 and pos_x < 0.3:
            exit2 = {'x': 0.0, 'y': -1.402}
            lower_corridor = {'x': 0.0, 'y': -1.137}
            tail = self._router.plan(
                robot_id, (lower_corridor['x'], lower_corridor['y']),
                charger, blocked_vertices=blocked)
            # tail은 그래프 시작 waypoint부터 시작. 중복 방지 위해 앞단 합치기.
            return [{'x': pos_x, 'y': pos_y}, exit2, lower_corridor, *tail]
        return self._router.plan(
            robot_id, (pos_x, pos_y), charger, blocked_vertices=blocked)

    def _vertices_blocked_by_others(self, robot_id: str) -> set[str]:
        """내가 아닌 다른 로봇이 _VERTEX_BLOCK_RADIUS 이내에 있는 vertex 이름 집합."""
        try:
            waypoints = db.get_fleet_waypoints()
        except Exception:
            return set()
        blocked: set[str] = set()
        with self._lock:
            others = [(st.pos_x, st.pos_y) for rid, st in self._states.items()
                      if rid != robot_id]
        if not others:
            return blocked
        for wp in waypoints:
            wx, wy = float(wp['x']), float(wp['y'])
            for ox, oy in others:
                if math.hypot(wx - ox, wy - oy) <= self._VERTEX_BLOCK_RADIUS:
                    blocked.add(wp['name'])
                    break
        return blocked

    def _path_blocked_by(
        self, robot_id: str, route: list[dict]
    ) -> Optional[str]:
        """route의 최종 목적지를 제외한 중간 vertex들이 다른 로봇에게
        점유 중이면 해당 로봇 ID 반환. 자유로우면 None.

        최종 목적지 자체에 상대 로봇이 있는 경우는 "이미 다른 로봇이 도착"
        이므로 _pick_waypoint_for_zone 단계에서 이미 피했다고 보고 여기서는
        무시한다.
        """
        if len(route) <= 2:
            return None
        intermediates = route[1:-1]
        with self._lock:
            for rid, state in self._states.items():
                if rid == robot_id:
                    continue
                for pt in intermediates:
                    if math.hypot(pt['x'] - state.pos_x,
                                  pt['y'] - state.pos_y) <= self._BLOCK_RADIUS:
                        return rid
        return None

    def _dispatch_navigate_to(self, robot_id: str, payload: dict) -> None:
        """navigate_to 처리 — 경로 계획 후 막혀 있으면 대기 큐에 저장."""
        zone_id = payload.get('zone_id')
        if zone_id is None:
            logger.warning('navigate_to: zone_id missing')
            return

        all_wps = db.get_fleet_waypoints()
        with self._lock:
            wp_name = self._pick_waypoint_for_zone_locked(robot_id, zone_id)
            if not wp_name:
                logger.warning('navigate_to: zone_id=%s has no waypoints', zone_id)
                self._pending_navigate.pop(robot_id, None)
                return
            wp = next((w for w in all_wps if w['name'] == wp_name), None)
            st = self._get_or_create(robot_id)
            rx, ry = st.pos_x, st.pos_y
            if wp:
                st.dest_x = float(wp['x'])
                st.dest_y = float(wp['y'])

        blocked = self._vertices_blocked_by_others(robot_id)
        route = self._router.plan(
            robot_id, (rx, ry), wp_name, blocked_vertices=blocked)
        logger.info('navigate_to: wp=%s, route=%d points (blocked=%d)',
                    wp_name, len(route), len(blocked))

        # GUIDING preemptive conflict resolution
        with self._lock:
            mode = st.mode
        if mode == 'GUIDING':
            try:
                route, should_proceed = self._resolve_guiding_conflict(
                    robot_id, route, payload)
            except Exception:
                logger.exception('guiding conflict resolve failed')
                should_proceed = True
            if not should_proceed:
                # loser 분기 — 이미 내부에서 dispatch 또는 in-place wait 처리됨
                return

        # 계획된 경로를 즉시 state에 반영하고 UI에 push.
        # stagger/block으로 Pi dispatch가 지연되더라도 admin/customer UI는
        # 요청 즉시 새 경로를 보게 된다. (지연 중 로봇 아이콘은 구 위치에 있고
        # 경로 선만 새 것이지만, "곧 이동할 경로"로 해석 가능.)
        if route and len(route) >= 2:
            with self._lock:
                st.path = route
            self._router.reserve(robot_id, route)
            self._push_status(robot_id, st)

        # Stagger: 다른 로봇이 최근에 dispatch됐고 가까이 있으면 대기
        now_ts = time.monotonic()
        # iteration 중 다른 thread가 dispatch dict을 변경하면 RuntimeError가 난다.
        for other_id, last_ts in list(self._last_navigate_dispatch.items()):
            if other_id == robot_id:
                continue
            if now_ts - last_ts > self._STAGGER_WINDOW_S:
                continue
            with self._lock:
                other = self._states.get(other_id)
                my_state = self._states.get(robot_id)
            if not other or not my_state:
                continue
            if math.hypot(other.pos_x - my_state.pos_x,
                          other.pos_y - my_state.pos_y) <= self._STAGGER_RADIUS:
                self._pending_navigate[robot_id] = dict(payload)
                logger.info(
                    'navigate_to: robot=%s staggered — robot=%s dispatched '
                    '%.1fs ago and is within %.1fm. Will retry.',
                    robot_id, other_id,
                    now_ts - last_ts, self._STAGGER_RADIUS,
                )
                return

        blocker = self._path_blocked_by(robot_id, route)
        if blocker is not None:
            # 중간 경유점을 다른 로봇이 점유 → 대기 큐에 저장
            self._pending_navigate[robot_id] = dict(payload)
            logger.info(
                'navigate_to: robot=%s queued — path blocked by robot=%s at '
                'intermediate waypoint. Will retry on next status update.',
                robot_id, blocker,
            )
            self._push_admin({
                'type': 'navigate_to_queued',
                'robot_id': robot_id,
                'reason': f'path blocked by robot {blocker}',
                'zone_id': zone_id,
            })
            return

        # 경로 확보 — Pi에 dispatch
        self._pending_navigate.pop(robot_id, None)
        self._last_navigate_dispatch[robot_id] = time.monotonic()

        if route and len(route) > 1:
            poses = self._route_to_poses(route, wp_name)
            self._relay_to_pi(robot_id, {
                'cmd': 'navigate_through_poses',
                'poses': poses,
            })
            logger.info('navigate_to zone=%s → through_poses %d pts',
                        zone_id, len(poses))
        elif wp:
            out = dict(payload, x=wp['x'], y=wp['y'],
                       theta=wp.get('theta', 0.0))
            self._relay_to_pi(robot_id, out)
            logger.info('navigate_to zone=%s → single waypoint', zone_id)

    def _retry_pending_navigates(self) -> None:
        """on_status 콜백에서 1Hz 호출. 대기 중인 navigate_to 중 경로 열린 것 dispatch."""
        if not self._pending_navigate:
            return
        for rid in list(self._pending_navigate.keys()):
            payload = self._pending_navigate.get(rid)
            if not payload:
                continue
            # 재검사
            self._dispatch_navigate_to(rid, payload)

    def _pick_waypoint_for_zone(self, robot_id: str, zone_id: int) -> Optional[str]:
        """Thread-safe public wrapper — 필요 시 외부에서 사용."""
        with self._lock:
            return self._pick_waypoint_for_zone_locked(robot_id, zone_id)

    def _pick_waypoint_for_zone_locked(
        self, robot_id: str, zone_id: int
    ) -> Optional[str]:
        """zone_id에 속한 waypoint 중 비어 있는 것을 선택.

        caller가 ``self._lock``을 이미 잡고 있어야 한다. 반환 직후 caller가
        ``state.dest_x/dest_y``를 세팅해야 후속 요청이 점유로 인식한다.

        점유 판정 기준 (다른 로봇):
        - 현재 위치(pos_x/pos_y)가 waypoint 0.25m 이내 → 그 자리에 있음
        - GUIDING 중이고 dest_x/dest_y가 0.25m 이내 → 그리로 가는 중
        """
        waypoints = db.get_waypoints_by_zone(zone_id)
        if not waypoints:
            return None

        candidates = [wp for wp in waypoints if wp.get('pickup_zone')]
        if not candidates:
            candidates = waypoints

        if len(candidates) == 1:
            return candidates[0]['name']

        # 점유 판정:
        # - pos 기반: 로봇이 이 waypoint 근처(0.25m 이내)에 물리적으로 있음
        # - dest 기반: 다른 로봇의 목적지 좌표가 이 waypoint와 "같은 지점"(5cm 이내)
        #   → 같은 zone 안의 다른 waypoint(거리 20cm 수준)를 오점유로 막지 않기 위함
        _DEST_SAME_POINT = 0.05
        occupied: set[str] = set()
        for rid, state in self._states.items():
            if rid == robot_id:
                continue
            for wp in candidates:
                wx, wy = float(wp['x']), float(wp['y'])
                if math.hypot(wx - state.pos_x, wy - state.pos_y) <= self._OCCUPY_DIST:
                    occupied.add(wp['name'])
                if (state.dest_x is not None and state.dest_y is not None
                        and math.hypot(wx - state.dest_x, wy - state.dest_y)
                        <= _DEST_SAME_POINT):
                    occupied.add(wp['name'])

        free = [wp for wp in candidates if wp['name'] not in occupied]
        # 갈 수 있는 후보가 여럿이면 현재 위치에서 가장 가까운 waypoint 선택.
        # (zone=육류인데 육류1/육류2 중 로봇과 가까운 쪽으로 가야 최단 경로)
        pool = free if free else candidates
        my = self._states.get(robot_id)
        if my is not None:
            pool = sorted(
                pool,
                key=lambda w: math.hypot(
                    float(w['x']) - my.pos_x, float(w['y']) - my.pos_y
                ),
            )
        return pool[0]['name']

    def _get_or_create(self, robot_id: str) -> RobotState:
        """Get or create a RobotState (must be called under self._lock)."""
        if robot_id not in self._states:
            self._states[robot_id] = RobotState(robot_id=robot_id)
        return self._states[robot_id]

    def _relay_to_pi(self, robot_id: str, payload: dict) -> None:
        if self.publish_cmd:
            self.publish_cmd(robot_id, payload)
        else:
            logger.warning('publish_cmd not wired; dropping cmd=%s', payload.get('cmd'))

    def _enrich_status_for_web(
        self, robot_id: str, state: RobotState, msg: dict
    ) -> dict:
        """Web-only: add my_robot / other_robots for mart map; admin TCP stays flat."""
        web = dict(msg)
        web['my_robot'] = {
            'robot_id': state.robot_id,
            'pos_x': state.pos_x,
            'pos_y': state.pos_y,
            'yaw': state.yaw,
            'mode': state.mode,
            'battery': state.battery,
            'is_locked_return': state.is_locked_return,
            'follow_disabled': state.follow_disabled,
            'waiting_timeout_sec': state.waiting_timeout_sec,
            'bbox': state.bbox,
            'path': state.path,
        }
        # lock 잡은 채로 dict 빌드를 하면 다른 Flask 쓰레드를 블로킹한다 — 스냅샷만 잡고
        # 나머지 변환은 lock 밖에서 수행.
        with self._lock:
            snapshot = [
                (rid, st.pos_x, st.pos_y, st.mode)
                for rid, st in self._states.items()
                if rid != robot_id
            ]
        web['other_robots'] = [
            {'robot_id': rid, 'pos_x': px, 'pos_y': py, 'mode': mode}
            for rid, px, py, mode in snapshot
        ]
        return web

    def _push_status(self, robot_id: str, state: RobotState) -> None:
        msg = {
            'type': 'status',
            'robot_id': robot_id,
            'mode': state.mode,
            'pos_x': state.pos_x,
            'pos_y': state.pos_y,
            'yaw': state.yaw,
            'battery': state.battery,
            'is_locked_return': state.is_locked_return,
            'follow_disabled': state.follow_disabled,
            'waiting_timeout_sec': state.waiting_timeout_sec,
            'bbox': state.bbox,
            'path': state.path,
        }
        self._push_admin(msg)
        self._push_web(robot_id, self._enrich_status_for_web(robot_id, state, msg))

    def _push_event(self, robot_id: str, event_type: str,
                    detail: str = '', user_id: str | None = None) -> None:
        """DB 기록 + admin UI 실시간 전송."""
        db.log_event(robot_id, event_type, user_id, detail=detail or None)
        self._push_admin({
            'type': 'event',
            'robot_id': robot_id,
            'event_type': event_type,
            'detail': detail,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
        })

    def _push_admin(self, msg: dict) -> None:
        if self.push_to_admin:
            self.push_to_admin(msg)

    def _push_web(self, robot_id: str, msg: dict) -> None:
        if self.push_to_web:
            self.push_to_web(robot_id, msg)

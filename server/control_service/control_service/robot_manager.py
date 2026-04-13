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
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from . import db
from shoppinkki_core.config import ROBOT_TIMEOUT_SEC

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
    last_seen: datetime = field(default_factory=datetime.utcnow)
    active_user_id: Optional[str] = None
    bbox: Optional[Dict] = None          # latest detection bbox from AI server
    dest_x: Optional[float] = None       # navigate_to 목적지 x
    dest_y: Optional[float] = None       # navigate_to 목적지 y


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
            state.last_seen = datetime.utcnow()

        # DB 갱신은 모드 변경 시에만 (위치/배터리는 메모리 캐시로 충분)
        if prev_mode != state.mode:
            db.update_robot(
                robot_id,
                current_mode=state.mode,
            )

        # Push status update to admin and web
        self._push_status(robot_id, state)

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
        db.log_event(robot_id, event, user_id)

        self._push_admin({'type': 'alarm', 'robot_id': robot_id, 'event': event})
        self._push_web(robot_id, {'type': 'alarm', 'event': event})

    def on_cart(self, robot_id: str, payload: dict) -> None:
        """Process /robot_<id>/cart JSON and forward to web client."""
        items = payload.get('items', [])
        self._push_web(robot_id, {'type': 'cart_update', 'items': items})

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
            if not db.has_unpaid_items(cart['cart_id']):
                logger.info('checkout_zone_enter: no unpaid items robot=%s', robot_id)
                return
            self._push_web(robot_id, {
                'type': 'checkout_zone_enter',
                'robot_id': robot_id,
            })
            logger.info('checkout_zone_enter → web robot=%s', robot_id)

    # ──────────────────────────────────────────
    # Commands from Admin (channel B, via tcp_server)
    # ──────────────────────────────────────────

    def handle_admin_cmd(self, robot_id: str, payload: dict) -> None:
        """Route admin commands to Pi or handle locally."""
        cmd = payload.get('cmd')

        if cmd == 'admin_goto':
            # Only allowed in IDLE state
            with self._lock:
                state = self._get_or_create(robot_id)
                if state.mode != 'IDLE':
                    self._push_admin({
                        'type': 'admin_goto_rejected',
                        'robot_id': robot_id,
                        'reason': f'Robot is in {state.mode}, not IDLE',
                    })
                    return
            self._relay_to_pi(robot_id, payload)

        elif cmd == 'init_pose':
            # Only allowed in CHARGING or IDLE state
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

        elif cmd == 'admin_position_adjustment':
            # Position adjustment from Admin UI map click.
            # - Simulation: Gazebo pose + AMCL sync
            # - Real robot: AMCL-only relocalization (no physical model move)
            x = float(payload.get('x', 0.0))
            y = float(payload.get('y', 0.0))
            theta = float(payload.get('theta', 0.0))
            ok = False
            apply_mode = ''

            # 1) Try simulation path first (Gazebo SetEntityPose + AMCL sync in ros_node)
            sim_adjust = self.adjust_position_in_sim
            if sim_adjust:
                try:
                    ok = bool(sim_adjust(robot_id, x, y, theta))
                    if ok:
                        apply_mode = 'sim_pose_and_amcl'
                except Exception:
                    logger.exception('admin_position_adjustment failed (robot=%s)', robot_id)

            # 2) Fallback for real robot (or when Gazebo bridge is unavailable):
            #    publish map-frame initialpose only.
            if not ok and self.publish_initialpose_at:
                try:
                    self.publish_initialpose_at(robot_id, x, y, theta)
                    ok = True
                    apply_mode = 'amcl_only'
                except Exception:
                    logger.exception(
                        'admin_position_adjustment fallback(initialpose) failed (robot=%s)',
                        robot_id,
                    )

            if not ok:
                self._push_admin({
                    'type': 'position_adjustment_rejected',
                    'robot_id': robot_id,
                    'reason': 'position adjustment failed',
                })
            else:
                # 즉시 반영: 다음 /status 수신 전에도 UI가 위치를 갱신할 수 있도록
                # 캐시 좌표를 먼저 업데이트하고 status를 push한다.
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

        elif cmd in ('mode', 'resume_tracking', 'navigate_to', 'start_session'):
            self._relay_to_pi(robot_id, payload)

        elif cmd in ('force_terminate', 'staff_resolved'):
            # 세션을 강제 종료하거나 잠금 해제 처리 시, 다음 로그인에 장바구니가 남지 않도록 정리한다.
            self._clear_active_cart(robot_id, reason=cmd)
            self._relay_to_pi(robot_id, payload)

        else:
            logger.warning('Unknown admin cmd=%s', cmd)

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
        elif cmd == 'navigate_to':
            zone_id = payload.get('zone_id')
            if zone_id is not None and 'x' not in payload:
                zone = db.get_zone(zone_id)
                if zone:
                    payload = dict(payload,
                                   x=zone['waypoint_x'], y=zone['waypoint_y'],
                                   theta=zone.get('waypoint_theta', 0.0))
                else:
                    logger.warning('navigate_to: zone_id=%s not found in DB', zone_id)
            self._relay_to_pi(robot_id, payload)
        elif cmd in ('mode', 'resume_tracking',
                     'start_session', 'enter_simulation',
                     'return', 'registration_confirm', 'enter_registration',
                     'retake_registration'):
            if cmd == 'return':
                # 쇼핑 종료: customer_web의 return 이벤트를 Pi가 이해하는 mode=RETURNING으로 변환해 전달한다.
                # (Pi는 cmd='return'을 처리하지 않음)
                #
                # Pi로 RETURNING을 보낸 뒤에 세션/장바구니를 정리한다. (이전에는 먼저 세션을 끊어
                # 캐시 모드와 실제 SM이 어긋나거나, GUIDING 등에서 릴레이가 스킵된 채 DB만 비워지는
                # 경우가 있었음)

                def _finish_shopping_session() -> None:
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
                        'return: skip Pi RETURNING (robot=%s cached_mode=%s; '
                        'need TRACKING/TRACKING_CHECKOUT/WAITING/GUIDING/SEARCHING)',
                        robot_id, cached_mode,
                    )
                    _finish_shopping_session()
                    return
                payload = dict(payload)
                payload.pop('cmd', None)
                payload_to_pi = {
                    'cmd': 'mode',
                    'value': 'RETURNING',
                }
                payload_to_pi.update(payload)
                self._relay_to_pi(robot_id, payload_to_pi)
                # 관제 UI·REST용 메모리/DB 즉시 반영 (Pi status 수신 전 지연 방지)
                with self._lock:
                    st = self._get_or_create(robot_id)
                    prev_mode = st.mode
                    st.mode = 'RETURNING'
                if prev_mode != 'RETURNING':
                    db.update_robot(robot_id, current_mode='RETURNING')
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
        db.log_event(robot_id, 'PAYMENT_SUCCESS', session['user_id'])
        self._relay_to_pi(robot_id, {'cmd': 'payment_success'})
        self._push_web(robot_id, {'type': 'payment_success'})
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
            db.log_event(robot_id, 'CART_CLEARED', session.get('user_id'),
                         detail=f'reason={reason}')
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
            with self._lock:
                for robot_id, state in self._states.items():
                    if state.last_seen < threshold and state.mode != 'OFFLINE':
                        logger.info('Robot %s → OFFLINE (timeout)', robot_id)
                        state.mode = 'OFFLINE'
                        state.active_user_id = None
                        db.update_robot(
                            robot_id,
                            current_mode='OFFLINE',
                            active_user_id=None,
                        )
                        db.log_event(robot_id, 'OFFLINE')
                        self._push_status(robot_id, state)

    # ──────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────

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
            'bbox': state.bbox,
        }
        others: List[dict] = []
        with self._lock:
            for rid, st in self._states.items():
                if rid == robot_id:
                    continue
                others.append({
                    'robot_id': rid,
                    'pos_x': st.pos_x,
                    'pos_y': st.pos_y,
                    'mode': st.mode,
                })
        web['other_robots'] = others
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
            'bbox': state.bbox,
        }
        self._push_admin(msg)
        self._push_web(robot_id, self._enrich_status_for_web(robot_id, state, msg))

    def _push_admin(self, msg: dict) -> None:
        if self.push_to_admin:
            self.push_to_admin(msg)

    def _push_web(self, robot_id: str, msg: dict) -> None:
        if self.push_to_web:
            self.push_to_web(robot_id, msg)

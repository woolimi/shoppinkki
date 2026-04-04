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


# ──────────────────────────────────────────────
# Data class
# ──────────────────────────────────────────────

@dataclass
class RobotState:
    robot_id: str
    mode: str = 'OFFLINE'
    pos_x: float = 0.0
    pos_y: float = 0.0
    battery: float = 100.0
    is_locked_return: bool = False
    last_seen: datetime = field(default_factory=datetime.utcnow)
    active_user_id: Optional[str] = None
    bbox: Optional[Dict] = None          # latest detection bbox from AI server


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
        self.publish_cmd:   Optional[Callable[[str, dict], None]] = None
        self.push_to_admin: Optional[Callable[[dict], None]] = None
        self.push_to_web:   Optional[Callable[[str, dict], None]] = None

    # ──────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────

    def start(self) -> None:
        """Load robot states from DB and start cleanup thread."""
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
            state.battery = float(payload.get('battery', state.battery))
            state.is_locked_return = bool(payload.get('is_locked_return', False))
            state.last_seen = datetime.utcnow()

        # Persist to DB
        db.update_robot(
            robot_id,
            current_mode=state.mode,
            pos_x=state.pos_x,
            pos_y=state.pos_y,
            battery_level=int(state.battery),
            is_locked_return=int(state.is_locked_return),
            last_seen=state.last_seen,
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

        elif cmd in ('mode', 'resume_tracking', 'force_terminate',
                     'staff_resolved', 'navigate_to', 'start_session'):
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
        elif cmd in ('navigate_to', 'mode', 'resume_tracking',
                     'delete_item', 'start_session'):
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

    def _push_status(self, robot_id: str, state: RobotState) -> None:
        msg = {
            'type': 'status',
            'robot_id': robot_id,
            'mode': state.mode,
            'pos_x': state.pos_x,
            'pos_y': state.pos_y,
            'battery': state.battery,
            'is_locked_return': state.is_locked_return,
            'bbox': state.bbox,
        }
        self._push_admin(msg)
        self._push_web(robot_id, msg)

    def _push_admin(self, msg: dict) -> None:
        if self.push_to_admin:
            self.push_to_admin(msg)

    def _push_web(self, robot_id: str, msg: dict) -> None:
        if self.push_to_web:
            self.push_to_web(robot_id, msg)

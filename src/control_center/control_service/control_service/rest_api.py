"""REST API for control_service (Flask, port 8081).

All endpoints return JSON.  Error responses: {"error": "message"}.

Endpoints
---------
GET  /robots                          → all robot states
GET  /zones                           → all zones
GET  /zone/parking/available          → available parking slot
GET  /boundary                        → all boundary configs
GET  /events?limit=<n>                → recent event log

POST /session                         → create session
GET  /session/robot/<robot_id>        → active session by robot_id
GET  /session/<id>                    → get session
PATCH /session/<id>                   → end session ({"is_active": 0})

GET  /cart/<cart_id>                  → cart items
POST /cart/<cart_id>/item             → add item
DELETE /item/<item_id>                → delete item
PATCH /cart/<cart_id>/items/mark_paid → mark all paid
GET  /cart/<cart_id>/has_unpaid       → bool

GET  /camera/<robot_id>               → MJPEG stream (handled by camera_stream)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from flask import Flask, Response, jsonify, request

from . import db

if TYPE_CHECKING:
    from .robot_manager import RobotManager
    from .camera_stream import CameraStream

logger = logging.getLogger(__name__)


def create_app(robot_manager: 'RobotManager',
               camera_stream: 'CameraStream | None' = None) -> Flask:
    app = Flask(__name__)
    app.config['JSON_AS_ASCII'] = False

    # ── Robots ────────────────────────────────

    @app.get('/robots')
    def get_robots():
        states = robot_manager.get_all_states()
        return jsonify({
            rid: {
                'mode': s.mode,
                'pos_x': s.pos_x,
                'pos_y': s.pos_y,
                'battery': s.battery,
                'is_locked_return': s.is_locked_return,
                'active_user_id': s.active_user_id,
            }
            for rid, s in states.items()
        })

    # ── Zone ──────────────────────────────────

    @app.get('/zones')
    def get_all_zones():
        zones = db.get_all_zones()
        return jsonify([_zone_dict(z) for z in zones])

    @app.get('/zone/parking/available')
    def parking_available():
        zone = robot_manager.get_available_parking()
        if not zone:
            return jsonify({'error': 'no parking available'}), 404
        return jsonify(_zone_dict(zone))

    # ── Boundary ──────────────────────────────

    @app.get('/boundary')
    def boundary():
        rows = db.get_all_boundaries()
        return jsonify(rows)

    # ── Events ────────────────────────────────

    @app.get('/events')
    def events():
        limit = int(request.args.get('limit', 100))
        rows = db.get_events(limit)
        return jsonify(_serialize_rows(rows))

    # ── Session ───────────────────────────────

    @app.post('/session')
    def create_session():
        data = request.get_json(silent=True) or {}
        robot_id = data.get('robot_id')
        user_id  = data.get('user_id')
        if not robot_id or not user_id:
            return jsonify({'error': 'robot_id and user_id required'}), 400

        # Check user exists
        user = db.get_user(user_id)
        if not user:
            return jsonify({'error': 'user not found'}), 404

        # Check robot availability by mode
        robot = db.get_robot(robot_id)
        if robot:
            mode = robot.get('current_mode')
            if mode == 'CHARGING':
                return jsonify({'error': 'robot is charging'}), 409
            if mode in ('RETURNING', 'LOCKED'):
                return jsonify({'error': 'robot is returning'}), 409

        # Check for existing active session on same robot
        existing = db.get_active_session_by_robot(robot_id)
        if existing:
            # 같은 사용자가 같은 로봇에 재로그인 → 기존 세션 반환
            if existing.get('user_id') == user_id:
                cart = db.get_cart_by_session(existing['session_id'])
                return jsonify({
                    'session_id': existing['session_id'],
                    'cart_id': cart['cart_id'] if cart else None,
                }), 200
            return jsonify({'error': 'robot already in session',
                            'session_id': existing['session_id']}), 409

        # Check if user already has an active session on another robot
        existing_user = db.get_active_session_by_user(user_id)
        if existing_user:
            return jsonify({'error': 'user already has active session'}), 409

        session_id = db.create_session(robot_id, user_id)
        db.update_robot(robot_id, active_user_id=user_id)
        db.log_event(robot_id, 'SESSION_START', user_id)

        # CHARGING → IDLE 전환: Pi에 start_session cmd 전달
        if robot_manager.publish_cmd:
            robot_manager.publish_cmd(robot_id, {
                'cmd': 'start_session',
                'user_id': user_id,
            })
        else:
            logger.warning('publish_cmd not wired; start_session dropped for robot=%s', robot_id)

        cart = db.get_cart_by_session(session_id)
        return jsonify({
            'session_id': session_id,
            'cart_id': cart['cart_id'] if cart else None,
        }), 201

    @app.get('/session/robot/<robot_id>')
    def get_session_by_robot(robot_id: str):
        session = db.get_active_session_by_robot(robot_id)
        if not session:
            return jsonify({'error': 'no active session'}), 404
        cart = db.get_cart_by_session(session['session_id'])
        return jsonify({
            'session_id': session['session_id'],
            'cart_id': cart['cart_id'] if cart else None,
        })

    @app.get('/session/<int:session_id>')
    def get_session(session_id: int):
        session = db.get_session(session_id)
        if not session:
            return jsonify({'error': 'not found'}), 404
        return jsonify(_serialize_row(session))

    @app.patch('/session/<int:session_id>')
    def update_session(session_id: int):
        data = request.get_json(silent=True) or {}
        if data.get('is_active') == 0:
            db.end_session(session_id)
        return jsonify({'ok': True})

    # ── Cart ──────────────────────────────────

    @app.get('/cart/<int:cart_id>')
    def get_cart(cart_id: int):
        items = db.get_cart_items(cart_id)
        return jsonify(_serialize_rows(items))

    @app.post('/cart/<int:cart_id>/item')
    def add_item(cart_id: int):
        data = request.get_json(silent=True) or {}
        product_name = data.get('product_name', '')
        price = int(data.get('price', 0))
        if not product_name:
            return jsonify({'error': 'product_name required'}), 400
        item_id = db.add_cart_item(cart_id, product_name, price)
        return jsonify({'item_id': item_id}), 201

    @app.delete('/item/<int:item_id>')
    def delete_item(item_id: int):
        db.delete_cart_item(item_id)
        return jsonify({'ok': True})

    @app.patch('/cart/<int:cart_id>/items/mark_paid')
    def mark_paid(cart_id: int):
        db.mark_items_paid(cart_id)
        return jsonify({'ok': True})

    @app.get('/cart/<int:cart_id>/has_unpaid')
    def has_unpaid(cart_id: int):
        return jsonify({'has_unpaid': db.has_unpaid_items(cart_id)})

    # ── Camera MJPEG stream ───────────────────

    @app.get('/camera/<robot_id>')
    def camera(robot_id: str):
        if camera_stream is None:
            return jsonify({'error': 'camera stream not available'}), 503

        def generate():
            yield from camera_stream.mjpeg_frames(robot_id)

        return Response(
            generate(),
            mimetype='multipart/x-mixed-replace; boundary=frame',
        )

    # ── Health check ──────────────────────────

    @app.get('/health')
    def health():
        return jsonify({'ok': True})

    return app


# ──────────────────────────────────────────────
# Serialisation helpers
# ──────────────────────────────────────────────

def _zone_dict(z: dict) -> dict:
    return {
        'zone_id': z['zone_id'],
        'zone_name': z['zone_name'],
        'zone_type': z['zone_type'],
        'x': float(z['waypoint_x']),
        'y': float(z['waypoint_y']),
        'theta': float(z['waypoint_theta']),
    }


def _serialize_row(row: dict) -> dict:
    """Convert datetime objects to ISO strings for JSON serialisation."""
    out = {}
    for k, v in row.items():
        if hasattr(v, 'isoformat'):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _serialize_rows(rows: list) -> list:
    return [_serialize_row(r) for r in rows]

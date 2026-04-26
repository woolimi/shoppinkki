"""PostgreSQL database access layer for control_service.

Connection pool (size=5) backed by environment variables.
All queries use %s placeholders and RealDictCursor for dict rows.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


# ──────────────────────────────────────────────
# Connection pool
# ──────────────────────────────────────────────

def _load_env() -> None:
    """Load .env file from ros_ws root if present (no extra deps needed)."""
    p = Path(__file__).resolve().parent
    env_file = None
    for _ in range(10):
        candidate = p / '.env'
        if candidate.exists():
            env_file = candidate
            break
        p = p.parent
    if env_file is None:
        return
    for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


def init_pool() -> None:
    """Initialise the global connection pool (idempotent)."""
    global _pool
    if _pool is not None:
        return
    _load_env()
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=5,
        host=os.environ.get('PG_HOST', '127.0.0.1'),
        port=int(os.environ.get('PG_PORT', '5432')),
        user=os.environ.get('PG_USER', 'shoppinkki'),
        password=os.environ.get('PG_PASSWORD', 'shoppinkki'),
        dbname=os.environ.get('PG_DATABASE', 'shoppinkki'),
    )
    logger.info('DB pool initialised (%s:%s/%s)',
                os.environ.get('PG_HOST', '127.0.0.1'),
                os.environ.get('PG_PORT', '5432'),
                os.environ.get('PG_DATABASE', 'shoppinkki'))


@contextmanager
def _cursor(dictionary: bool = True):
    """Context manager: get cursor, commit on success, rollback on error."""
    if _pool is None:
        init_pool()
    conn = _pool.getconn()  # type: ignore[union-attr]
    try:
        if dictionary:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        _pool.putconn(conn)


# ──────────────────────────────────────────────
# ROBOT
# ──────────────────────────────────────────────

def get_robot(robot_id: str) -> Optional[Dict]:
    with _cursor() as cur:
        cur.execute('SELECT * FROM ROBOT WHERE robot_id = %s', (robot_id,))
        return cur.fetchone()


def get_all_robots() -> List[Dict]:
    with _cursor() as cur:
        cur.execute('SELECT * FROM ROBOT')
        return cur.fetchall()


_ROBOT_UPDATABLE_COLUMNS = frozenset({
    'ip_address', 'current_mode', 'pos_x', 'pos_y', 'battery_level',
    'last_seen', 'active_user_id', 'is_locked_return',
})


def update_robot(robot_id: str, **fields) -> None:
    """Update ROBOT columns by keyword argument.

    Column names are validated against an allowlist before interpolation
    to prevent SQL injection via attacker-controlled keyword arguments.
    """
    if not fields:
        return
    invalid = set(fields) - _ROBOT_UPDATABLE_COLUMNS
    if invalid:
        raise ValueError(f'update_robot: unknown columns {sorted(invalid)}')
    cols = ', '.join(f'{k} = %s' for k in fields)
    vals = list(fields.values()) + [robot_id]
    with _cursor() as cur:
        cur.execute(f'UPDATE ROBOT SET {cols} WHERE robot_id = %s', vals)


# ──────────────────────────────────────────────
# USER
# ──────────────────────────────────────────────

def get_user(user_id: str) -> Optional[Dict]:
    with _cursor() as cur:
        cur.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
        return cur.fetchone()


# ──────────────────────────────────────────────
# SESSION maintenance
# ──────────────────────────────────────────────

def reset_sessions_on_startup() -> None:
    """Hard reset sessions for test/demo runs.

    - Deactivate all active sessions
    - Clear robot ownership (active_user_id)
    """
    with _cursor(dictionary=False) as cur:
        cur.execute('UPDATE SESSION SET is_active = FALSE WHERE is_active = TRUE')
    with _cursor(dictionary=False) as cur:
        cur.execute('UPDATE ROBOT SET active_user_id = NULL WHERE active_user_id IS NOT NULL')


# ──────────────────────────────────────────────
# SESSION
# ──────────────────────────────────────────────

def create_session(robot_id: str, user_id: str, hours: int = 4) -> int:
    """Create an active session and return its session_id."""
    expires = datetime.utcnow() + timedelta(hours=hours)
    with _cursor() as cur:
        cur.execute(
            'INSERT INTO SESSION (robot_id, user_id, is_active, expires_at) '
            'VALUES (%s, %s, TRUE, %s) RETURNING session_id',
            (robot_id, user_id, expires),
        )
        session_id = cur.fetchone()['session_id']
    # Also create empty cart
    with _cursor() as cur:
        cur.execute('INSERT INTO CART (session_id) VALUES (%s)', (session_id,))
    return session_id


def get_session(session_id: int) -> Optional[Dict]:
    with _cursor() as cur:
        cur.execute('SELECT * FROM SESSION WHERE session_id = %s', (session_id,))
        return cur.fetchone()


def get_active_session_by_robot(robot_id: str) -> Optional[Dict]:
    with _cursor() as cur:
        cur.execute(
            'SELECT * FROM SESSION '
            'WHERE robot_id = %s AND is_active = TRUE AND expires_at > NOW()',
            (robot_id,),
        )
        return cur.fetchone()


def get_active_session_by_user(user_id: str) -> Optional[Dict]:
    with _cursor() as cur:
        cur.execute(
            'SELECT * FROM SESSION '
            'WHERE user_id = %s AND is_active = TRUE AND expires_at > NOW()',
            (user_id,),
        )
        return cur.fetchone()


def end_session(session_id: int) -> None:
    with _cursor() as cur:
        cur.execute(
            'SELECT cart_id FROM CART WHERE session_id = %s',
            (session_id,),
        )
        cart = cur.fetchone()
        if cart and cart.get('cart_id'):
            cur.execute(
                'DELETE FROM CART_ITEM WHERE cart_id = %s',
                (cart['cart_id'],),
            )
        # Update session
        cur.execute(
            'UPDATE SESSION SET is_active = FALSE WHERE session_id = %s',
            (session_id,),
        )
        # Clear active_user_id in ROBOT
        cur.execute(
            'UPDATE robot SET active_user_id = NULL WHERE robot_id = ('
            '  SELECT robot_id FROM SESSION WHERE session_id = %s'
            ')',
            (session_id,),
        )


def deactivate_expired_sessions() -> int:
    """Deactivate sessions that have passed their expires_at time.

    Also clears the owning robot's active_user_id so the robot becomes
    available again. Returns the number of sessions deactivated.
    """
    with _cursor() as cur:
        cur.execute(
            'SELECT session_id, robot_id FROM SESSION '
            'WHERE is_active = TRUE AND expires_at < NOW()'
        )
        expired = cur.fetchall()
        if not expired:
            return 0

        expired_ids = [s['session_id'] for s in expired]
        expired_robots = [s['robot_id'] for s in expired]

        cur.execute(
            'UPDATE SESSION SET is_active = FALSE WHERE session_id = ANY(%s)',
            (expired_ids,),
        )
        cur.execute(
            'UPDATE robot SET active_user_id = NULL WHERE robot_id = ANY(%s)',
            (expired_robots,),
        )
        logger.info('Deactivated %d expired sessions.', len(expired_ids))
        return len(expired_ids)


# ──────────────────────────────────────────────
# CART
# ──────────────────────────────────────────────

def get_cart_by_session(session_id: int) -> Optional[Dict]:
    with _cursor() as cur:
        cur.execute('SELECT * FROM CART WHERE session_id = %s', (session_id,))
        return cur.fetchone()


def add_cart_item(cart_id: int, product_name: str, price: int) -> int:
    """Insert a new cart item or increment quantity if the same unpaid item exists.

    Single round-trip CTE upsert: UPDATE first (with row lock), then INSERT
    only if no row was updated. Avoids the schema change a real ON CONFLICT
    would require (no partial UNIQUE index on is_paid=FALSE).
    """
    with _cursor() as cur:
        cur.execute(
            'WITH updated AS ( '
            '  UPDATE CART_ITEM SET quantity = quantity + 1 '
            '  WHERE cart_id = %s AND product_name = %s AND price = %s '
            '        AND is_paid = FALSE '
            '  RETURNING item_id '
            '), inserted AS ( '
            '  INSERT INTO CART_ITEM (cart_id, product_name, price) '
            '  SELECT %s, %s, %s WHERE NOT EXISTS (SELECT 1 FROM updated) '
            '  RETURNING item_id '
            ') '
            'SELECT item_id FROM updated UNION ALL SELECT item_id FROM inserted '
            'LIMIT 1',
            (cart_id, product_name, price, cart_id, product_name, price),
        )
        return cur.fetchone()['item_id']


def update_cart_item_quantity(item_id: int, quantity: int) -> None:
    """Set quantity for an unpaid cart item (minimum 1)."""
    if quantity < 1:
        quantity = 1
    with _cursor() as cur:
        cur.execute(
            'UPDATE CART_ITEM SET quantity = %s WHERE item_id = %s AND is_paid = FALSE',
            (quantity, item_id),
        )


def delete_cart_item(item_id: int) -> None:
    with _cursor() as cur:
        cur.execute('DELETE FROM CART_ITEM WHERE item_id = %s', (item_id,))


def get_cart_items(cart_id: int) -> List[Dict]:
    with _cursor() as cur:
        cur.execute(
            'SELECT * FROM CART_ITEM WHERE cart_id = %s ORDER BY scanned_at',
            (cart_id,),
        )
        return cur.fetchall()


def mark_items_paid(cart_id: int) -> None:
    with _cursor() as cur:
        cur.execute(
            'UPDATE CART_ITEM SET is_paid = TRUE WHERE cart_id = %s',
            (cart_id,),
        )


def has_unpaid_items(cart_id: int) -> bool:
    with _cursor() as cur:
        cur.execute(
            'SELECT COUNT(*) AS cnt FROM CART_ITEM '
            'WHERE cart_id = %s AND is_paid = FALSE',
            (cart_id,),
        )
        row = cur.fetchone()
        return (row['cnt'] > 0) if row else False


def delete_cart_items(cart_id: int) -> None:
    with _cursor() as cur:
        cur.execute('DELETE FROM CART_ITEM WHERE cart_id = %s', (cart_id,))


# ──────────────────────────────────────────────
# ZONE
# ──────────────────────────────────────────────

def get_zone(zone_id: int) -> Optional[Dict]:
    with _cursor() as cur:
        cur.execute('SELECT * FROM ZONE WHERE zone_id = %s', (zone_id,))
        return cur.fetchone()


def get_all_zones() -> List[Dict]:
    with _cursor() as cur:
        cur.execute('SELECT * FROM ZONE ORDER BY zone_id')
        return cur.fetchall()


def get_fleet_waypoints() -> List[Dict]:
    with _cursor() as cur:
        cur.execute('SELECT * FROM fleet_waypoint ORDER BY idx')
        return cur.fetchall()


def get_fleet_lanes() -> List[Dict]:
    with _cursor() as cur:
        cur.execute('SELECT * FROM fleet_lane ORDER BY from_idx, to_idx')
        return cur.fetchall()


def get_waypoints_by_zone(zone_id: int) -> List[Dict]:
    """zone_waypoint_map을 통해 해당 zone에 속하는 fleet_waypoint 목록 반환."""
    with _cursor() as cur:
        cur.execute(
            'SELECT w.* FROM fleet_waypoint w '
            'JOIN zone_waypoint_map m ON w.idx = m.waypoint_idx '
            'WHERE m.zone_id = %s ORDER BY w.idx',
            (zone_id,),
        )
        return cur.fetchall()


def get_parking_slots() -> List[Dict]:
    """Return ZONE rows for parking slots 140, 141."""
    with _cursor() as cur:
        cur.execute('SELECT * FROM ZONE WHERE zone_id IN (140, 141) ORDER BY zone_id')
        return cur.fetchall()


def get_parking_available() -> Optional[Dict]:
    """First parking slot row (lower zone_id first), or None if none defined."""
    slots = get_parking_slots()
    return slots[0] if slots else None


# ──────────────────────────────────────────────
# BOUNDARY
# ──────────────────────────────────────────────

def get_boundary(description: str) -> Optional[Dict]:
    with _cursor() as cur:
        cur.execute(
            'SELECT * FROM BOUNDARY_CONFIG WHERE description = %s',
            (description,),
        )
        return cur.fetchone()


def get_all_boundaries() -> List[Dict]:
    with _cursor() as cur:
        cur.execute('SELECT * FROM BOUNDARY_CONFIG')
        return cur.fetchall()


# ──────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────

def log_event(
    robot_id: str,
    event_type: str,
    user_id: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    with _cursor() as cur:
        cur.execute(
            'INSERT INTO EVENT_LOG (robot_id, user_id, event_type, event_detail) '
            'VALUES (%s, %s, %s, %s)',
            (robot_id, user_id, event_type, detail),
        )


def log_staff_call(robot_id: str, user_id: Optional[str], event_type: str) -> int:
    with _cursor() as cur:
        cur.execute(
            'INSERT INTO STAFF_CALL_LOG (robot_id, user_id, event_type) '
            'VALUES (%s, %s, %s) RETURNING log_id',
            (robot_id, user_id, event_type),
        )
        return cur.fetchone()['log_id']


def resolve_staff_call(log_id: int) -> None:
    with _cursor() as cur:
        cur.execute(
            'UPDATE STAFF_CALL_LOG SET resolved_at = NOW() WHERE log_id = %s',
            (log_id,),
        )


def get_unresolved_staff_calls() -> List[Dict]:
    with _cursor() as cur:
        cur.execute(
            'SELECT * FROM STAFF_CALL_LOG WHERE resolved_at IS NULL '
            'ORDER BY occurred_at DESC'
        )
        return cur.fetchall()


def get_events(limit: int = 100) -> List[Dict]:
    with _cursor() as cur:
        cur.execute(
            'SELECT * FROM EVENT_LOG ORDER BY occurred_at DESC LIMIT %s',
            (limit,),
        )
        return cur.fetchall()

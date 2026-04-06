"""MySQL database access layer for control_service.

Connection pool (size=5) backed by environment variables.
All queries use %s placeholders and dictionary=True cursors.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import mysql.connector
from mysql.connector import pooling

logger = logging.getLogger(__name__)

_pool: Optional[pooling.MySQLConnectionPool] = None


# ──────────────────────────────────────────────
# Connection pool
# ──────────────────────────────────────────────

def _load_env() -> None:
    """Load .env file from ros_ws root if present (no extra deps needed)."""
    env_file = Path(__file__).parents[4] / '.env'
    if env_file.exists():
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
    _pool = pooling.MySQLConnectionPool(
        pool_name='shoppinkki',
        pool_size=5,
        host=os.environ.get('MYSQL_HOST', '127.0.0.1'),
        port=int(os.environ.get('MYSQL_PORT', '3306')),
        user=os.environ.get('MYSQL_USER', 'shoppinkki'),
        password=os.environ.get('MYSQL_PASSWORD', 'shoppinkki'),
        database=os.environ.get('MYSQL_DATABASE', 'shoppinkki'),
        autocommit=False,
    )
    logger.info('DB pool initialised (%s:%s/%s)',
                os.environ.get('MYSQL_HOST', '127.0.0.1'),
                os.environ.get('MYSQL_PORT', '3306'),
                os.environ.get('MYSQL_DATABASE', 'shoppinkki'))


@contextmanager
def _cursor(dictionary: bool = True):
    """Context manager: get cursor, commit on success, rollback on error."""
    if _pool is None:
        init_pool()
    conn = _pool.get_connection()  # type: ignore[union-attr]
    cur = conn.cursor(dictionary=dictionary)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


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


def update_robot(robot_id: str, **fields) -> None:
    """Update arbitrary ROBOT columns by keyword argument."""
    if not fields:
        return
    cols = ', '.join(f'{k} = %s' for k in fields)
    vals = list(fields.values()) + [robot_id]
    with _cursor() as cur:
        cur.execute(f'UPDATE ROBOT SET {cols} WHERE robot_id = %s', vals)


# ──────────────────────────────────────────────
# USER
# ──────────────────────────────────────────────

def get_user(user_id: str) -> Optional[Dict]:
    with _cursor() as cur:
        cur.execute('SELECT * FROM USER WHERE user_id = %s', (user_id,))
        return cur.fetchone()


# ──────────────────────────────────────────────
# SESSION
# ──────────────────────────────────────────────

def create_session(robot_id: str, user_id: str, hours: int = 4) -> int:
    """Create an active session and return its session_id."""
    expires = datetime.utcnow() + timedelta(hours=hours)
    with _cursor() as cur:
        cur.execute(
            'INSERT INTO SESSION (robot_id, user_id, is_active, expires_at) '
            'VALUES (%s, %s, 1, %s)',
            (robot_id, user_id, expires),
        )
        session_id = cur.lastrowid
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
            'WHERE robot_id = %s AND is_active = 1 AND expires_at > NOW()',
            (robot_id,),
        )
        return cur.fetchone()


def get_active_session_by_user(user_id: str) -> Optional[Dict]:
    with _cursor() as cur:
        cur.execute(
            'SELECT * FROM SESSION '
            'WHERE user_id = %s AND is_active = 1 AND expires_at > NOW()',
            (user_id,),
        )
        return cur.fetchone()


def end_session(session_id: int) -> None:
    with _cursor() as cur:
        cur.execute(
            'UPDATE SESSION SET is_active = 0 WHERE session_id = %s',
            (session_id,),
        )


# ──────────────────────────────────────────────
# CART
# ──────────────────────────────────────────────

def get_cart_by_session(session_id: int) -> Optional[Dict]:
    with _cursor() as cur:
        cur.execute('SELECT * FROM CART WHERE session_id = %s', (session_id,))
        return cur.fetchone()


def add_cart_item(cart_id: int, product_name: str, price: int) -> int:
    """Insert a new cart item or increment quantity if the same unpaid item exists."""
    with _cursor() as cur:
        cur.execute(
            'SELECT item_id FROM CART_ITEM '
            'WHERE cart_id = %s AND product_name = %s AND price = %s AND is_paid = 0',
            (cart_id, product_name, price),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                'UPDATE CART_ITEM SET quantity = quantity + 1 WHERE item_id = %s',
                (row['item_id'],),
            )
            return row['item_id']
        cur.execute(
            'INSERT INTO CART_ITEM (cart_id, product_name, price) VALUES (%s, %s, %s)',
            (cart_id, product_name, price),
        )
        return cur.lastrowid


def update_cart_item_quantity(item_id: int, quantity: int) -> None:
    """Set quantity for an unpaid cart item (minimum 1)."""
    if quantity < 1:
        quantity = 1
    with _cursor() as cur:
        cur.execute(
            'UPDATE CART_ITEM SET quantity = %s WHERE item_id = %s AND is_paid = 0',
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
            'UPDATE CART_ITEM SET is_paid = 1 WHERE cart_id = %s',
            (cart_id,),
        )


def has_unpaid_items(cart_id: int) -> bool:
    with _cursor() as cur:
        cur.execute(
            'SELECT COUNT(*) AS cnt FROM CART_ITEM '
            'WHERE cart_id = %s AND is_paid = 0',
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


def get_parking_slots() -> List[Dict]:
    """Return ZONE rows for parking slots 140, 141."""
    with _cursor() as cur:
        cur.execute('SELECT * FROM ZONE WHERE zone_id IN (140, 141) ORDER BY zone_id')
        return cur.fetchall()


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
            'VALUES (%s, %s, %s)',
            (robot_id, user_id, event_type),
        )
        return cur.lastrowid


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

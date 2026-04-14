"""Integration tests for db.py — requires Docker PostgreSQL to be running.

Run:
    cd ~/ros_ws && python -m pytest server/control_service/test/test_db.py -v
"""

import pytest

# Skip entire module if PostgreSQL is not reachable
try:
    from control_service import db
    db.init_pool()
    with db._cursor() as cur:
        cur.execute('SELECT 1')
    PG_AVAILABLE = True
except Exception:
    PG_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not PG_AVAILABLE,
    reason='PostgreSQL not reachable (run: docker compose up -d pg)',
)


class TestRobot:
    def test_get_all_robots(self):
        robots = db.get_all_robots()
        assert isinstance(robots, list)
        ids = [r['robot_id'] for r in robots]
        assert '54' in ids
        assert '18' in ids

    def test_get_robot(self):
        r = db.get_robot('54')
        assert r is not None
        assert r['robot_id'] == '54'

    def test_update_robot(self):
        db.update_robot('54', pos_x=1.0, pos_y=2.0)
        r = db.get_robot('54')
        assert abs(float(r['pos_x']) - 1.0) < 0.01
        # Reset
        db.update_robot('54', pos_x=0.0, pos_y=0.0)


class TestZone:
    def test_get_zone(self):
        zone = db.get_zone(6)
        assert zone is not None
        assert zone['zone_name'] == '음료'

    def test_get_parking_available(self):
        slot = db.get_parking_available()
        assert slot is not None
        assert slot['zone_id'] in (140, 141)


class TestBoundary:
    def test_get_all_boundaries(self):
        rows = db.get_all_boundaries()
        assert len(rows) >= 1
        descs = [r['description'] for r in rows]
        assert '결제 구역' in descs


class TestSessionCart:
    def setup_method(self):
        """Ensure test user and robot exist."""
        self.robot_id = '54'
        self.user_id = 'test01'
        # Make tests robust: ensure this user has no active session anywhere
        existing_user = db.get_active_session_by_user(self.user_id)
        if existing_user:
            db.end_session(existing_user['session_id'])

    def teardown_method(self):
        """Clean up any test sessions."""
        with db._cursor() as cur:
            cur.execute(
                "UPDATE SESSION SET is_active=FALSE "
                "WHERE user_id=%s",
                (self.user_id,),
            )
        # Clear robot.active_user_id if it points to this user
        try:
            r = db.get_robot(self.robot_id)
            if r and r.get('active_user_id') == self.user_id:
                db.update_robot(self.robot_id, active_user_id=None)
        except Exception:
            pass

    def test_create_and_get_session(self):
        # End any existing active session first
        existing = db.get_active_session_by_robot(self.robot_id)
        if existing:
            db.end_session(existing['session_id'])

        sid = db.create_session(self.robot_id, self.user_id)
        assert sid > 0

        session = db.get_session(sid)
        assert session['robot_id'] == self.robot_id
        assert session['is_active'] is True

        db.end_session(sid)
        session = db.get_session(sid)
        assert session['is_active'] is False

    def test_deactivate_expired_sessions(self):
        # Ensure no active sessions first (by robot and by user)
        existing = db.get_active_session_by_robot(self.robot_id)
        if existing:
            db.end_session(existing['session_id'])

        # Create a session, then force it to be expired but still active
        sid = db.create_session(self.robot_id, self.user_id)
        with db._cursor(dictionary=False) as cur:
            cur.execute(
                "UPDATE SESSION SET expires_at = NOW() - interval '1 minute', is_active = TRUE "
                "WHERE session_id = %s",
                (sid,),
            )

        updated = db.deactivate_expired_sessions()
        assert updated >= 1

        row = db.get_session(sid)
        assert row is not None
        assert row['is_active'] is False

    def test_cart_operations(self):
        existing = db.get_active_session_by_robot(self.robot_id)
        if existing:
            db.end_session(existing['session_id'])

        sid = db.create_session(self.robot_id, self.user_id)
        cart = db.get_cart_by_session(sid)
        assert cart is not None
        cid = cart['cart_id']

        # Add items
        item_id = db.add_cart_item(cid, '콜라', 1500)
        assert item_id > 0

        items = db.get_cart_items(cid)
        assert len(items) == 1
        assert items[0]['product_name'] == '콜라'
        assert items[0]['is_paid'] is False

        # Unpaid check
        assert db.has_unpaid_items(cid) is True

        # Mark paid
        db.mark_items_paid(cid)
        assert db.has_unpaid_items(cid) is False

        
        db.delete_cart_item(item_id)
        assert db.get_cart_items(cid) == []

        db.end_session(sid)

"""Integration tests for REST /session idempotency.

Requires Docker PostgreSQL to be running.
"""

import pytest


# Skip entire module if PostgreSQL is not reachable
try:
    from control_service import db
    from control_service.rest_api import create_app

    db.init_pool()
    with db._cursor() as cur:
        cur.execute("SELECT 1")
    PG_AVAILABLE = True
except Exception:
    PG_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not PG_AVAILABLE,
    reason="PostgreSQL not reachable (run: docker compose up -d pg)",
)


class _DummyRobotManager:
    publish_cmd = None

    def get_all_states(self):
        return {}

    def get_available_parking(self):
        return None


@pytest.fixture()
def client():
    app = create_app(robot_manager=_DummyRobotManager(), camera_stream=None)
    app.testing = True
    return app.test_client()


class TestSessionIdempotency:
    ROBOT_ID = "54"
    USER_ID = "test01"

    def teardown_method(self):
        # Clean up any test sessions
        with db._cursor(dictionary=False) as cur:
            cur.execute(
                "UPDATE SESSION SET is_active=FALSE WHERE robot_id=%s AND user_id=%s",
                (self.ROBOT_ID, self.USER_ID),
            )
        # Also clear robot active_user_id if it points to this user
        r = db.get_robot(self.ROBOT_ID)
        if r and r.get("active_user_id") == self.USER_ID:
            db.update_robot(self.ROBOT_ID, active_user_id=None)

    def test_same_user_same_robot_returns_existing_session(self, client):
        payload = {"robot_id": self.ROBOT_ID, "user_id": self.USER_ID, "password": "1234"}

        r1 = client.post("/session", json=payload)
        assert r1.status_code in (200, 201)
        s1 = r1.get_json()
        assert "session_id" in s1

        r2 = client.post("/session", json=payload)
        assert r2.status_code == 200
        s2 = r2.get_json()
        assert s2["session_id"] == s1["session_id"]


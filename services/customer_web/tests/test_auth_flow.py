"""
customer_web 로그인/로그아웃 플로우 통합 테스트.

대상 라우트:
    GET  /            — 세션 상태에 따른 리다이렉트
    GET  /login       — 로그인 페이지 렌더링
    POST /login       — 로그인 처리
    GET  /main        — 메인 쇼핑 페이지 (세션 필요)
    POST /logout      — 로그아웃

mock_ctrl_rest 픽스처 (conftest.py, autouse):
    - 기본값 None → 실제 HTTP 호출 없음
    - 테스트 내에서 return_value / side_effect로 동작 지정
"""


def _set_session(client, **kwargs):
    """테스트용 Flask 세션 값 주입."""
    with client.session_transaction() as sess:
        sess.update(kwargs)


# ── GET / (Index) ──────────────────────────────────────────────


class TestIndex:
    """인덱스 라우트: 세션 상태에 따라 /main 또는 /login으로 분기."""

    def test_no_session_redirects_to_login(self, client):
        resp = client.get("/?robot_id=54")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_valid_session_redirects_to_main(self, client, mock_ctrl_rest):
        _set_session(client, session_id=1, robot_id="54", user_id="test01")
        mock_ctrl_rest.return_value = {"is_active": True}
        resp = client.get("/?robot_id=54")
        assert resp.status_code == 302
        assert "/main" in resp.headers["Location"]

    def test_expired_session_clears_and_redirects_to_login(self, client, mock_ctrl_rest):
        _set_session(client, session_id=1, robot_id="54", user_id="test01")
        mock_ctrl_rest.return_value = {"is_active": False}
        resp = client.get("/?robot_id=54")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
        with client.session_transaction() as sess:
            assert "session_id" not in sess

    def test_session_robot_id_mismatch_returns_400(self, client, mock_ctrl_rest):
        # 세션은 54번 로봇, URL은 18번 → 400
        _set_session(client, session_id=1, robot_id="54", user_id="test01")
        mock_ctrl_rest.return_value = {"is_active": True}
        resp = client.get("/?robot_id=18")
        assert resp.status_code == 400

    def test_robot_in_use_without_user_redirects_to_blocked(self, client, mock_ctrl_rest):
        # active_user_id 없고 모드가 TRACKING → /blocked
        mock_ctrl_rest.return_value = {
            "54": {"mode": "TRACKING", "active_user_id": None}
        }
        resp = client.get("/?robot_id=54")
        assert resp.status_code == 302
        assert "blocked" in resp.headers["Location"]


# ── GET /login ─────────────────────────────────────────────────


class TestLoginGet:
    """로그인 페이지 GET."""

    def test_renders_login_page(self, client):
        resp = client.get("/login?robot_id=54")
        assert resp.status_code == 200

    def test_unknown_robot_id_returns_404(self, client):
        resp = client.get("/login?robot_id=99")
        assert resp.status_code == 404


# ── POST /login ────────────────────────────────────────────────


class TestLoginPost:
    """로그인 처리 POST."""

    URL = "/login?robot_id=54"
    FORM = {"robot_id": "54", "user_id": "test01", "password": "1234"}

    def test_empty_credentials_redirects_back_to_login(self, client):
        resp = client.post(self.URL, data={"robot_id": "54", "user_id": "", "password": ""})
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_success_sets_session_and_redirects_to_main(self, client, mock_ctrl_rest):
        mock_ctrl_rest.return_value = {"session_id": 42, "cart_id": 7}
        resp = client.post(self.URL, data=self.FORM)
        assert resp.status_code == 302
        assert "/main" in resp.headers["Location"]
        with client.session_transaction() as sess:
            assert sess["session_id"] == 42
            assert sess["robot_id"] == "54"
            assert sess["user_id"] == "test01"

    def test_robot_charging_redirects_to_blocked_with_reason(self, client, mock_ctrl_rest):
        mock_ctrl_rest.return_value = {"error": "robot is charging"}
        resp = client.post(self.URL, data=self.FORM)
        assert resp.status_code == 302
        loc = resp.headers["Location"]
        assert "blocked" in loc
        assert "charging" in loc

    def test_robot_returning_redirects_to_blocked_with_reason(self, client, mock_ctrl_rest):
        mock_ctrl_rest.return_value = {"error": "robot is returning"}
        resp = client.post(self.URL, data=self.FORM)
        assert resp.status_code == 302
        loc = resp.headers["Location"]
        assert "blocked" in loc
        assert "returning" in loc

    def test_robot_already_in_session_redirects_to_blocked(self, client, mock_ctrl_rest):
        mock_ctrl_rest.return_value = {"error": "robot already in session", "session_id": 1}
        resp = client.post(self.URL, data=self.FORM)
        assert resp.status_code == 302
        assert "blocked" in resp.headers["Location"]

    def test_user_already_in_session_redirects_back_to_login(self, client, mock_ctrl_rest):
        mock_ctrl_rest.return_value = {"error": "user already has active session"}
        resp = client.post(self.URL, data=self.FORM)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_user_not_found_redirects_back_to_login(self, client, mock_ctrl_rest):
        mock_ctrl_rest.return_value = {"error": "user not found"}
        resp = client.post(self.URL, data=self.FORM)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_server_error_redirects_back_to_login(self, client, mock_ctrl_rest):
        mock_ctrl_rest.return_value = None  # 연결 실패
        resp = client.post(self.URL, data=self.FORM)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_unknown_robot_id_returns_404(self, client):
        resp = client.post(
            "/login?robot_id=99",
            data={"robot_id": "99", "user_id": "test01", "password": "1234"},
        )
        assert resp.status_code == 404


# ── GET /main ──────────────────────────────────────────────────


class TestMain:
    """메인 쇼핑 페이지: 유효 세션 필요."""

    def test_no_session_redirects_to_login(self, client):
        resp = client.get("/main?robot_id=54")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_valid_session_renders_page(self, client):
        _set_session(client, session_id=1, robot_id="54", user_id="test01")
        resp = client.get("/main?robot_id=54")
        assert resp.status_code == 200

    def test_wrong_robot_id_redirects_to_session_robot(self, client):
        # 세션은 54번 로봇, URL은 18번 → 54번으로 리다이렉트
        _set_session(client, session_id=1, robot_id="54", user_id="test01")
        resp = client.get("/main?robot_id=18")
        assert resp.status_code == 302
        assert "robot_id=54" in resp.headers["Location"]


# ── POST /logout ───────────────────────────────────────────────


class TestLogout:
    """로그아웃: 세션 초기화 + control_service에 세션 종료 통보."""

    def test_clears_session_and_redirects_to_login(self, client, mock_ctrl_rest):
        _set_session(client, session_id=1, robot_id="54", user_id="test01")
        resp = client.post("/logout?robot_id=54")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
        with client.session_transaction() as sess:
            assert "session_id" not in sess
            assert "robot_id" not in sess

    def test_calls_session_end_api(self, client, mock_ctrl_rest):
        _set_session(client, session_id=5, robot_id="54", user_id="test01")
        client.post("/logout?robot_id=54")
        mock_ctrl_rest.assert_called_once_with(
            "PATCH", "/session/5", json={"is_active": False}
        )

    def test_without_session_redirects_to_login(self, client):
        resp = client.post("/logout")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

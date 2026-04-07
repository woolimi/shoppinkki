"""
테스트 픽스처 설정.

app.py 임포트 전에 ControlClient를 mock 처리하여
TCP 연결 시도를 차단한다.
"""

import os
import sys
from unittest.mock import MagicMock, patch

# customer_web 디렉터리를 import 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ControlClient.connect()가 TCP 연결을 시도하지 않도록
# app.py 임포트 전에 패치한다
_mock_cc = MagicMock()
_mock_cc.is_connected = True

with patch("control_client.ControlClient", return_value=_mock_cc):
    import app as _app  # noqa: E402

import pytest


@pytest.fixture(scope="session")
def flask_app():
    _app.app.config.update({"TESTING": True, "SECRET_KEY": "test-secret"})
    yield _app.app


@pytest.fixture()
def client(flask_app):
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def mock_ctrl_rest(monkeypatch):
    """모든 테스트에서 _ctrl_rest를 mock 처리 (실제 HTTP 호출 차단).

    기본 반환값은 None (서버 연결 실패와 동일).
    개별 테스트에서 return_value 또는 side_effect로 동작을 지정한다.
    """
    mock = MagicMock(return_value=None)
    monkeypatch.setattr(_app, "_ctrl_rest", mock)
    return mock

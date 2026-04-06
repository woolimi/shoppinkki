"""
cart 기능 socket_handlers 단위 테스트.

대상 이벤트:
    update_quantity — {"item_id": N, "quantity": N} → control_service TCP 릴레이
    delete_item     — {"item_id": N} → TCP 릴레이 (회귀)
    qr_scan         — {"data": "..."} → TCP 릴레이 (회귀)

conftest.py (autouse mock_ctrl_rest) 와 _mock_cc 픽스처를 활용한다.
"""

import sys
import os
from unittest.mock import MagicMock, patch

import pytest

# customer_web 모듈이 conftest.py에서 이미 로드됨
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# conftest.py에서 임포트된 app 모듈 참조
import app as _app


def _set_session(client, **kwargs):
    """테스트용 Flask 세션 값 주입."""
    with client.session_transaction() as sess:
        sess.update(kwargs)


@pytest.fixture()
def sio_client(client):
    """세션이 설정된 SocketIO 테스트 클라이언트."""
    _set_session(client, robot_id="54", user_id="test01", session_id=1)
    sc = _app.socketio.test_client(_app.app, flask_test_client=client)
    yield sc
    sc.disconnect()


@pytest.fixture(autouse=True)
def reset_mock_cc():
    """각 테스트 전에 _mock_cc.send 호출 기록을 초기화한다."""
    # conftest.py의 _mock_cc는 control_clients["54"] 와 ["18"] 로 등록됨
    for cc in _app.control_clients.values():
        cc.send.reset_mock()
    yield


# ── update_quantity ────────────────────────────────────────────


class TestUpdateQuantity:
    """update_quantity 이벤트 → TCP relay."""

    def test_relays_correct_cmd(self, sio_client):
        sio_client.emit("update_quantity", {"item_id": 5, "quantity": 3})
        cc = _app.control_clients["54"]
        cc.send.assert_called_once_with({
            "cmd": "update_quantity",
            "robot_id": "54",
            "item_id": 5,
            "quantity": 3,
        })

    def test_missing_item_id_is_ignored(self, sio_client):
        sio_client.emit("update_quantity", {"quantity": 2})
        cc = _app.control_clients["54"]
        cc.send.assert_not_called()

    def test_missing_quantity_is_ignored(self, sio_client):
        sio_client.emit("update_quantity", {"item_id": 5})
        cc = _app.control_clients["54"]
        cc.send.assert_not_called()

    def test_empty_payload_is_ignored(self, sio_client):
        sio_client.emit("update_quantity", {})
        cc = _app.control_clients["54"]
        cc.send.assert_not_called()


# ── delete_item (회귀) ─────────────────────────────────────────


class TestDeleteItem:
    """delete_item 이벤트 → TCP relay (회귀 테스트)."""

    def test_relays_correct_cmd(self, sio_client):
        sio_client.emit("delete_item", {"item_id": 7})
        cc = _app.control_clients["54"]
        cc.send.assert_called_once_with({
            "cmd": "delete_item",
            "robot_id": "54",
            "item_id": 7,
        })

    def test_missing_item_id_is_ignored(self, sio_client):
        sio_client.emit("delete_item", {})
        cc = _app.control_clients["54"]
        cc.send.assert_not_called()


# ── qr_scan (회귀) ────────────────────────────────────────────


class TestQrScan:
    """qr_scan 이벤트 → TCP relay (회귀 테스트)."""

    def test_relays_correct_cmd(self, sio_client):
        qr_text = '{"product_name": "콜라", "price": 1500}'
        sio_client.emit("qr_scan", {"data": qr_text})
        cc = _app.control_clients["54"]
        cc.send.assert_called_once_with({
            "cmd": "qr_scan",
            "robot_id": "54",
            "qr_data": qr_text,
        })

    def test_empty_data_is_ignored(self, sio_client):
        sio_client.emit("qr_scan", {"data": ""})
        cc = _app.control_clients["54"]
        cc.send.assert_not_called()

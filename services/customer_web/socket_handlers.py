"""
채널 A: 브라우저 SocketIO 이벤트 핸들러 등록.
브라우저 → customer_web → control_service (채널 C) 릴레이.
"""

import logging

import llm_client as llm

logger = logging.getLogger(__name__)


def register_handlers(socketio, control_client, llm_cfg: dict, robot_id: str):
    """
    Flask-SocketIO 이벤트 핸들러를 등록한다.

    Parameters
    ----------
    socketio        : Flask-SocketIO 인스턴스
    control_client  : ControlClient 인스턴스
    llm_cfg         : {"host": ..., "port": ...} LLM 서버 설정
    robot_id        : 로봇 ID 문자열 (예: "54")
    """

    @socketio.on("connect")
    def on_connect():
        logger.info("브라우저 SocketIO 연결")
        if control_client.is_connected:
            socketio.emit("control_connected", {"connected": True})
        else:
            socketio.emit("control_connected", {"connected": False})

    @socketio.on("disconnect")
    def on_disconnect():
        logger.info("브라우저 SocketIO 연결 해제")

    # ── 모드 전환 ──────────────────────────────────────────────

    @socketio.on("mode")
    def on_mode(data):
        """{"value": "WAITING" | "RETURNING"}"""
        value = data.get("value") if isinstance(data, dict) else None
        if not value:
            return
        control_client.send({"cmd": "mode", "robot_id": robot_id, "value": value})

    @socketio.on("resume_tracking")
    def on_resume_tracking(data=None):
        control_client.send({"cmd": "resume_tracking", "robot_id": robot_id})

    # ── 귀환 요청 ──────────────────────────────────────────────

    @socketio.on("return")
    def on_return(data=None):
        control_client.send({"cmd": "return", "robot_id": robot_id})

    # ── 상품 안내 ──────────────────────────────────────────────

    @socketio.on("navigate_to")
    def on_navigate_to(data):
        """{"zone_id": N}"""
        zone_id = data.get("zone_id") if isinstance(data, dict) else None
        if zone_id is None:
            return
        control_client.send({"cmd": "navigate_to", "robot_id": robot_id, "zone_id": zone_id})

    # ── 결제 ───────────────────────────────────────────────────

    @socketio.on("payment")
    def on_payment(data=None):
        control_client.send({"cmd": "process_payment", "robot_id": robot_id})

    # ── 장바구니 삭제 ──────────────────────────────────────────

    @socketio.on("delete_item")
    def on_delete_item(data):
        """{"item_id": N}"""
        item_id = data.get("item_id") if isinstance(data, dict) else None
        if item_id is None:
            return
        control_client.send({"cmd": "delete_item", "robot_id": robot_id, "item_id": item_id})

    # ── 자연어 상품 검색 ───────────────────────────────────────

    @socketio.on("find_product")
    def on_find_product(data):
        """
        {"name": "콜라"}
        → LLM 서버 질의 → navigate_to relay
        """
        name = data.get("name") if isinstance(data, dict) else None
        if not name:
            socketio.emit("find_product_result", {"error": "검색어를 입력해주세요."})
            return

        result = llm.query(
            name,
            host=llm_cfg.get("host", "127.0.0.1"),
            port=llm_cfg.get("port", 8000),
        )
        if result is None:
            socketio.emit("find_product_result", {"error": "상품을 찾을 수 없습니다."})
            return

        zone_id = result["zone_id"]
        zone_name = result["zone_name"]
        # 안내 시작: control_service에 navigate_to 전송
        control_client.send({
            "cmd": "navigate_to",
            "robot_id": robot_id,
            "zone_id": zone_id,
        })
        # 브라우저에 결과 즉시 전달 (control_service의 find_product_result와 별개)
        socketio.emit("find_product_result", {
            "type": "find_product_result",
            "zone_id": zone_id,
            "zone_name": zone_name,
        })

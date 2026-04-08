"""
채널 A: 브라우저 SocketIO 이벤트 핸들러 등록.
브라우저 → customer_web → control_service (채널 C) 릴레이.
"""

import logging

from flask import session

import llm_client as llm

logger = logging.getLogger(__name__)


def register_handlers(socketio, control_clients: dict, llm_cfg: dict):
    """
    Flask-SocketIO 이벤트 핸들러를 등록한다.

    Parameters
    ----------
    socketio        : Flask-SocketIO 인스턴스
    control_clients : {robot_id: ControlClient} 딕셔너리
    llm_cfg         : {"host": ..., "port": ...} LLM 서버 설정
    """

    def _get_client():
        """세션의 robot_id로 ControlClient를 조회. 없으면 None."""
        robot_id = session.get("robot_id")
        if not robot_id:
            logger.warning("SocketIO 핸들러: 세션에 robot_id 없음")
            return None, None
        cc = control_clients.get(str(robot_id))
        if cc is None:
            logger.warning("SocketIO 핸들러: 알 수 없는 robot_id=%s", robot_id)
        return robot_id, cc

    @socketio.on("connect")
    def on_connect():
        logger.info("브라우저 SocketIO 연결")
        robot_id, cc = _get_client()
        if cc and cc.is_connected:
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
        robot_id, cc = _get_client()
        if cc:
            cc.send({"cmd": "mode", "robot_id": robot_id, "value": value})

    @socketio.on("resume_tracking")
    def on_resume_tracking(data=None):
        robot_id, cc = _get_client()
        if cc:
            cc.send({"cmd": "resume_tracking", "robot_id": robot_id})

    # ── 귀환 요청 ──────────────────────────────────────────────

    @socketio.on("return")
    def on_return(data=None):
        """[쇼핑 종료] 버튼 → control_service에 RETURNING 요청."""
        robot_id, cc = _get_client()
        if cc:
            cc.send({"cmd": "return", "robot_id": robot_id})

    # ── 상품 안내 ──────────────────────────────────────────────

    @socketio.on("navigate_to")
    def on_navigate_to(data):
        """{"zone_id": N}"""
        zone_id = data.get("zone_id") if isinstance(data, dict) else None
        if zone_id is None:
            return
        robot_id, cc = _get_client()
        if cc:
            cc.send({"cmd": "navigate_to", "robot_id": robot_id, "zone_id": zone_id})

    # ── 결제 ───────────────────────────────────────────────────

    @socketio.on("payment")
    def on_payment(data=None):
        robot_id, cc = _get_client()
        if cc:
            cc.send({"cmd": "process_payment", "robot_id": robot_id})

    # ── 장바구니 삭제 ──────────────────────────────────────────

    @socketio.on("delete_item")
    def on_delete_item(data):
        """{"item_id": N}"""
        item_id = data.get("item_id") if isinstance(data, dict) else None
        if item_id is None:
            return
        robot_id, cc = _get_client()
        if cc:
            cc.send({"cmd": "delete_item", "robot_id": robot_id, "item_id": item_id})

    # ── 수량 변경 ──────────────────────────────────────────────

    @socketio.on("update_quantity")
    def on_update_quantity(data):
        """{"item_id": N, "quantity": N}"""
        item_id = data.get("item_id") if isinstance(data, dict) else None
        quantity = data.get("quantity") if isinstance(data, dict) else None
        if item_id is None or quantity is None:
            return
        robot_id, cc = _get_client()
        if cc:
            cc.send({
                "cmd": "update_quantity",
                "robot_id": robot_id,
                "item_id": item_id,
                "quantity": quantity,
            })

    # ── QR 스캔 (시뮬레이션 모드: 웹 카메라) ──────────��─────────

    @socketio.on("qr_scan")
    def on_qr_scan(data):
        """시뮬레이션 모드에서 웹 카메라로 스캔한 QR 데이터 → 장바구니 추가.

        data: {"data": "<QR 텍스트>"}
        QR 텍스트는 JSON {"product_name": "...", "price": N} 형식을 기대.
        """
        qr_data = data.get("data") if isinstance(data, dict) else None
        if not qr_data:
            return
        robot_id, cc = _get_client()
        if cc:
            logger.info("qr_scan: robot_id=%s data=%s", robot_id, qr_data[:100])
            cc.send({"cmd": "qr_scan", "robot_id": robot_id, "qr_data": qr_data})

    # ── 시뮬레이션 모드 ───────────────────────────────────────────

    @socketio.on("enter_simulation")
    def on_enter_simulation(data=None):
        """IDLE 패널의 [시뮬레이션 모드] 버튼 → enter_simulation cmd 전송.

        시뮬레이션 모드: 인형 등록 없이 TRACKING 진입 + 추종 비활성화.
        """
        robot_id, cc = _get_client()
        if cc:
            logger.info("enter_simulation 요청 (robot_id=%s)", robot_id)
            cc.send({"cmd": "enter_simulation", "robot_id": robot_id})

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

        robot_id, cc = _get_client()
        if cc:
            cc.send({
                "cmd": "navigate_to",
                "robot_id": robot_id,
                "zone_id": zone_id,
            })
        # 브라우저에 결과 즉시 전달
        socketio.emit("find_product_result", {
            "type": "find_product_result",
            "zone_id": zone_id,
            "zone_name": zone_name,
        })

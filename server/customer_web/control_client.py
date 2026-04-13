"""
채널 C: customer_web ↔ control_service (TCP :8080, JSON 개행 구분)
자동 재연결 지원 TCP 클라이언트.
"""

import json
import logging
import socket
import threading
import time

logger = logging.getLogger(__name__)

RECONNECT_DELAY = 5  # 초


class ControlClient:
    """
    control_service TCP 서버에 연결하여 JSON 메시지를 송수신한다.

    수신한 메시지는 socketio.emit()으로 클라이언트 브라우저에 push한다.
    연결 끊김 시 RECONNECT_DELAY초 후 자동 재연결한다.
    """

    def __init__(self, host: str, port: int, robot_id: str, socketio_instance):
        self.host = host
        self.port = port
        self.robot_id = robot_id
        self._sio = socketio_instance
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    # ── 연결 관리 ──────────────────────────────────────────────

    def connect(self):
        """백그라운드 스레드에서 연결 루프를 시작한다."""
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._connect_loop, daemon=True)
        self._thread.start()

    def disconnect(self):
        """연결 루프를 중단하고 소켓을 닫는다."""
        self._running = False
        self._close_socket()

    def _close_socket(self):
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None

    def _connect_loop(self):
        """연결 → 등록 → 수신 루프. 끊기면 재연결 대기 후 반복."""
        while self._running:
            try:
                logger.info("control_service 연결 시도: %s:%d", self.host, self.port)
                sock = socket.create_connection((self.host, self.port), timeout=10)
                sock.settimeout(None)
                with self._lock:
                    self._sock = sock
                self._register()
                logger.info("control_service 연결 성공 (robot_id=%s)", self.robot_id)
                self._recv_loop(sock)
            except Exception as e:
                logger.warning("control_service 연결 실패: %s", e)
            finally:
                self._close_socket()
            if self._running:
                logger.info("%.0f초 후 재연결...", RECONNECT_DELAY)
                time.sleep(RECONNECT_DELAY)

    def _register(self):
        """연결 직후 role 등록 메시지 전송."""
        self.send({"type": "register", "role": "web", "robot_id": self.robot_id})

    def _recv_loop(self, sock: socket.socket):
        """소켓에서 개행 구분 JSON 메시지를 읽어 브라우저로 push."""
        buf = b""
        while self._running:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    logger.info("control_service 연결 종료 (EOF)")
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line.decode("utf-8"))
                        self._dispatch(msg)
                    except json.JSONDecodeError as e:
                        logger.warning("JSON 파싱 오류: %s | raw: %s", e, line[:200])
            except OSError:
                break

    def _dispatch(self, msg: dict):
        """
        수신 메시지 타입에 따라 SocketIO 이벤트로 브라우저에 push.

        처리 타입:
            status, cart, registration_done, checkout_zone_enter,
            payment_done, checkout_blocked, find_product_result,
            arrived, nav_failed, enter_locked, enter_halted, staff_resolved,
            doll_detected
        """
        msg_type = msg.get("type")
        if not msg_type:
            return
        known = {
            "status", "cart", "registration_done", "checkout_zone_enter",
            "payment_done", "checkout_blocked", "find_product_result",
            "arrived", "nav_failed", "enter_locked", "enter_halted", "staff_resolved",
            "doll_detected",
        }
        if msg_type in known:
            self._sio.emit(msg_type, msg)
        else:
            logger.debug("미처리 메시지 타입: %s", msg_type)

    # ── 송신 ───────────────────────────────────────────────────

    def send(self, payload: dict, retry_timeout: float = 10.0):
        """
        JSON 메시지를 개행 구분 방식으로 control_service에 전송.
        소켓이 없으면 백그라운드에서 최대 retry_timeout초 대기 후 재전송.
        """
        with self._lock:
            sock = self._sock

        if sock is not None:
            self._do_send(sock, payload)
        else:
            # Non-blocking retry in background thread
            logger.warning("소켓 없음 — 백그라운드에서 재시도 (최대 %.0fs): %s", retry_timeout, payload)
            t = threading.Thread(target=self._send_with_retry,
                                 args=(payload, retry_timeout), daemon=True)
            t.start()

    def _send_with_retry(self, payload: dict, retry_timeout: float):
        """백그라운드에서 소켓 연결 대기 후 전송."""
        deadline = time.monotonic() + retry_timeout
        while time.monotonic() < deadline:
            with self._lock:
                sock = self._sock
            if sock is not None:
                self._do_send(sock, payload)
                return
            time.sleep(0.5)
        logger.warning("소켓 재시도 타임아웃, 메시지 미전송: %s", payload)

    def _do_send(self, sock, payload: dict):
        """실제 소켓 전송."""
        try:
            data = json.dumps(payload, ensure_ascii=False) + "\n"
            sock.sendall(data.encode("utf-8"))
        except Exception as e:
            logger.error("전송 오류: %s", e)
            self._close_socket()

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._sock is not None

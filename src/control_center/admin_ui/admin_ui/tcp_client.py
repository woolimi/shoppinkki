# Copyright 2024 shoppinkki
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""TCP 클라이언트 — control_service:8080, QThread 기반.

연결 시 등록 메시지:
    {"type": "register", "role": "admin"}

수신 루프:
    개행('\\n') 구분 JSON 파싱
    → message_received(dict) pyqtSignal 발행 (Qt 메인 스레드에서 처리)

재연결:
    연결 끊김 시 5초 후 자동 재시도
    connection_changed(bool) pyqtSignal 발행

API:
    send(payload: dict) → bool  # 스레드 안전
    stop()
"""

import json
import socket
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal


class TCPClientThread(QThread):
    """TCP 클라이언트 스레드."""

    message_received = pyqtSignal(dict)
    connection_changed = pyqtSignal(bool)

    RECONNECT_DELAY = 5  # seconds

    def __init__(self, host: str, port: int, robot_ids: list, parent=None):
        super().__init__(parent)
        self._host = host
        self._port = port
        self._robot_ids = robot_ids
        self._sock: socket.socket | None = None
        self._running = False
        self._lock = threading.Lock()

    def run(self):
        """메인 연결 + 수신 루프."""
        self._running = True
        while self._running:
            try:
                self._connect_and_receive()
            except Exception:
                pass
            if self._running:
                self.connection_changed.emit(False)
                time.sleep(self.RECONNECT_DELAY)

    def _connect_and_receive(self):
        """소켓 연결, 등록, 수신 루프."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((self._host, self._port))
        sock.settimeout(None)

        with self._lock:
            self._sock = sock

        # 등록 메시지 전송
        reg = json.dumps({'type': 'register', 'role': 'admin'}) + '\n'
        sock.sendall(reg.encode('utf-8'))
        self.connection_changed.emit(True)

        buf = ''
        try:
            while self._running:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk.decode('utf-8', errors='replace')
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        self.message_received.emit(data)
                    except json.JSONDecodeError:
                        pass
        finally:
            with self._lock:
                self._sock = None
            try:
                sock.close()
            except Exception:
                pass

    def send(self, payload: dict) -> bool:
        """스레드 안전 전송. 성공 시 True 반환."""
        with self._lock:
            sock = self._sock
        if sock is None:
            return False
        try:
            data = json.dumps(payload) + '\n'
            sock.sendall(data.encode('utf-8'))
            return True
        except Exception:
            return False

    def stop(self):
        """스레드 종료."""
        self._running = False
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
        self.wait()

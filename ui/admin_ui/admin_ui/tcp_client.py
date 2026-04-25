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
import queue
import socket
import threading
import time

from PyQt5.QtCore import QObject, QThread, QTimer, pyqtSignal


class TCPClientThread(QThread):
    """TCP 클라이언트 스레드.

    중요: macOS PyQt5에서 worker thread의 pyqtSignal emit이 dict/object를
    크로스-스레드 마셜링할 때 간헐적 bus error를 일으킨다. 이를 피하기 위해
    수신된 메시지는 thread-safe Queue에 쌓기만 하고, **메인 스레드의
    QTimer가 polling하여 꺼내 시그널 emit**한다 (emit이 메인 스레드에서
    발생하므로 마셜링이 필요 없음).
    """

    # 메인 스레드에서만 emit → 마셜링 없음 → 안전
    message_received = pyqtSignal(object)
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
        # TCP thread → main thread: 메시지/연결상태 큐
        self._msg_q: 'queue.Queue[dict]' = queue.Queue()
        self._conn_q: 'queue.Queue[bool]' = queue.Queue()
        # 메인 스레드에서 주기적으로 큐를 드레인
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(50)  # 20 Hz
        self._drain_timer.timeout.connect(self._drain_queues)
        self._drain_timer.start()

    def _drain_queues(self) -> None:
        """메인 스레드에서 실행 — 큐를 비우며 시그널 emit."""
        for _ in range(200):
            try:
                msg = self._msg_q.get_nowait()
            except queue.Empty:
                break
            try:
                self.message_received.emit(msg)
            except Exception:
                pass
        for _ in range(10):
            try:
                ok = self._conn_q.get_nowait()
            except queue.Empty:
                break
            try:
                self.connection_changed.emit(ok)
            except Exception:
                pass

    def run(self):
        """메인 연결 + 수신 루프."""
        self._running = True
        while self._running:
            try:
                self._connect_and_receive()
            except Exception:
                pass
            if self._running:
                self._conn_q.put(False)
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
        self._conn_q.put(True)

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
                        self._msg_q.put(data)
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

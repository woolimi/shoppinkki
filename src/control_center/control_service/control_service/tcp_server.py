"""TCP server for channels B (Admin UI) and C (customer_web).

Port 8080.  JSON newline-delimited protocol.

Connection flow:
    1. Client connects
    2. Client sends register message:
         Admin:  {"type": "register", "role": "admin"}
         Web:    {"type": "register", "role": "web", "robot_id": "54"}
    3. Bidirectional JSON-newline exchange begins
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

TCP_HOST = '0.0.0.0'
TCP_PORT = 8080
RECV_BUF = 4096


class TCPServer:
    """Threaded TCP server — one thread per client connection."""

    def __init__(self, robot_manager) -> None:
        self._rm = robot_manager
        self._admin_clients: List[_Client] = []
        self._web_clients: Dict[str, List[_Client]] = {}  # robot_id → clients
        self._lock = threading.Lock()
        self._server_sock: Optional[socket.socket] = None
        self._running = False

        # Wire push callbacks into robot_manager
        robot_manager.push_to_admin = self.push_to_admin
        robot_manager.push_to_web   = self.push_to_web

    # ──────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────

    def serve_forever(self) -> None:
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((TCP_HOST, TCP_PORT))
        self._server_sock.listen(16)
        self._running = True
        logger.info('TCP server listening on %s:%d', TCP_HOST, TCP_PORT)
        while self._running:
            try:
                conn, addr = self._server_sock.accept()
                t = threading.Thread(
                    target=self._handle_client,
                    args=(conn, addr),
                    daemon=True,
                )
                t.start()
            except OSError:
                break

    def stop(self) -> None:
        self._running = False
        if self._server_sock:
            self._server_sock.close()

    # ──────────────────────────────────────────
    # Push helpers (called by robot_manager)
    # ──────────────────────────────────────────

    def push_to_admin(self, msg: dict) -> None:
        data = json.dumps(msg) + '\n'
        with self._lock:
            dead = []
            for c in self._admin_clients:
                if not c.send(data):
                    dead.append(c)
            for c in dead:
                self._admin_clients.remove(c)

    def push_to_web(self, robot_id: str, msg: dict) -> None:
        data = json.dumps(msg) + '\n'
        with self._lock:
            clients = self._web_clients.get(robot_id, [])
            dead = []
            for c in clients:
                if not c.send(data):
                    dead.append(c)
            for c in dead:
                clients.remove(c)

    # ──────────────────────────────────────────
    # Per-client handler
    # ──────────────────────────────────────────

    def _handle_client(self, conn: socket.socket, addr) -> None:
        logger.info('TCP client connected: %s', addr)
        client = _Client(conn)
        buf = ''
        role = None
        robot_id = None

        try:
            while True:
                chunk = conn.recv(RECV_BUF)
                if not chunk:
                    break
                buf += chunk.decode('utf-8', errors='replace')
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning('TCP bad JSON from %s: %s', addr, line)
                        continue

                    # ── Registration ──────────────
                    if payload.get('type') == 'register' and role is None:
                        role = payload.get('role')
                        robot_id = payload.get('robot_id')
                        if role == 'admin':
                            with self._lock:
                                self._admin_clients.append(client)
                            client.send(json.dumps({'type': 'registered',
                                                    'role': 'admin'}) + '\n')
                            logger.info('Admin registered from %s', addr)
                            # Send current state snapshot
                            self._send_snapshot_admin(client)
                        elif role == 'web' and robot_id:
                            with self._lock:
                                self._web_clients.setdefault(robot_id, []).append(client)
                            client.send(json.dumps({'type': 'registered',
                                                    'role': 'web',
                                                    'robot_id': robot_id}) + '\n')
                            logger.info('Web registered robot=%s from %s', robot_id, addr)
                        else:
                            client.send(json.dumps({'type': 'error',
                                                    'msg': 'invalid register'}) + '\n')
                        continue

                    # ── Route by role ──────────────
                    if role == 'admin' and robot_id is None:
                        # admin cmds include robot_id in payload
                        rid = payload.get('robot_id', '')
                        self._rm.handle_admin_cmd(rid, payload)
                    elif role == 'admin':
                        self._rm.handle_admin_cmd(robot_id, payload)
                    elif role == 'web' and robot_id:
                        self._rm.handle_web_cmd(robot_id, payload)
                    else:
                        logger.warning('TCP msg before register from %s', addr)

        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            logger.info('TCP client disconnected: %s', addr)
            conn.close()
            with self._lock:
                if role == 'admin':
                    if client in self._admin_clients:
                        self._admin_clients.remove(client)
                elif role == 'web' and robot_id:
                    clients = self._web_clients.get(robot_id, [])
                    if client in clients:
                        clients.remove(client)

    def _send_snapshot_admin(self, client: '_Client') -> None:
        """Send current robot states to newly connected admin."""
        states = self._rm.get_all_states()
        for robot_id, state in states.items():
            msg = {
                'type': 'status',
                'robot_id': robot_id,
                'mode': state.mode,
                'pos_x': state.pos_x,
                'pos_y': state.pos_y,
                'battery': state.battery,
                'is_locked_return': state.is_locked_return,
                'bbox': state.bbox,
            }
            client.send(json.dumps(msg) + '\n')


class _Client:
    """Thread-safe wrapper around a socket connection."""

    def __init__(self, conn: socket.socket) -> None:
        self._conn = conn
        self._lock = threading.Lock()
        self._alive = True

    def send(self, data: str) -> bool:
        """Send data; return False if the connection is dead."""
        if not self._alive:
            return False
        with self._lock:
            try:
                self._conn.sendall(data.encode('utf-8'))
                return True
            except OSError:
                self._alive = False
                return False

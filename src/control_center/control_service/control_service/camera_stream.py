"""Camera stream handler (channel H + channel F).

channel H  Pi → control_service : UDP raw frames
channel F  control_service → AI Server YOLO (TCP :5005) + bbox response

The MJPEG re-stream endpoint (/camera/<robot_id>) is served by rest_api.py
using mjpeg_frames() generator from this module.
"""

from __future__ import annotations

import logging
import os
import socket
import struct
import threading
import time
from collections import deque
from typing import Dict, Generator, Optional

logger = logging.getLogger(__name__)

UDP_HOST = '0.0.0.0'
UDP_PORT = int(os.environ.get('CAMERA_UDP_PORT', '9000'))

YOLO_HOST = os.environ.get('YOLO_HOST', '127.0.0.1')
YOLO_PORT = int(os.environ.get('YOLO_PORT', '5005'))

MAX_FRAME_BUF = 2   # keep latest N frames per robot


class CameraStream:
    """Receives UDP camera frames from Pi and forwards to YOLO AI server."""

    def __init__(self, robot_manager) -> None:
        self._rm = robot_manager
        self._frames: Dict[str, deque] = {}   # robot_id → deque of JPEG bytes
        self._lock = threading.Lock()
        self._running = False

    def run(self) -> None:
        """Main loop: receive UDP frames, forward to YOLO, update bbox cache."""
        self._running = True
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((UDP_HOST, UDP_PORT))
        sock.settimeout(1.0)
        logger.info('CameraStream listening on UDP %s:%d', UDP_HOST, UDP_PORT)

        while self._running:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break

            # Packet header: 2-byte robot_id length + robot_id + JPEG bytes
            if len(data) < 3:
                continue
            id_len = struct.unpack('!H', data[:2])[0]
            if len(data) < 2 + id_len:
                continue
            robot_id = data[2:2 + id_len].decode('utf-8', errors='replace')
            frame = data[2 + id_len:]

            # Store latest frame for MJPEG
            with self._lock:
                if robot_id not in self._frames:
                    self._frames[robot_id] = deque(maxlen=MAX_FRAME_BUF)
                self._frames[robot_id].append(frame)

            # Forward to YOLO (non-blocking, best-effort)
            threading.Thread(
                target=self._query_yolo,
                args=(robot_id, frame),
                daemon=True,
            ).start()

        sock.close()

    def stop(self) -> None:
        self._running = False

    # ── YOLO query ────────────────────────────

    def _query_yolo(self, robot_id: str, frame: bytes) -> None:
        """Send frame to YOLO server and update robot_manager bbox cache."""
        try:
            with socket.create_connection((YOLO_HOST, YOLO_PORT), timeout=0.5) as s:
                # Send: 4-byte length + JPEG frame
                header = struct.pack('!I', len(frame))
                s.sendall(header + frame)
                # Receive: JSON bbox response
                resp_len_b = s.recv(4)
                if len(resp_len_b) < 4:
                    return
                resp_len = struct.unpack('!I', resp_len_b)[0]
                resp_data = b''
                while len(resp_data) < resp_len:
                    chunk = s.recv(resp_len - len(resp_data))
                    if not chunk:
                        break
                    resp_data += chunk
            import json
            bbox = json.loads(resp_data.decode())
            self._rm.update_bbox(robot_id, bbox)
        except Exception:
            # YOLO server not available — clear bbox
            self._rm.update_bbox(robot_id, None)

    # ── MJPEG generator ───────────────────────

    def mjpeg_frames(self, robot_id: str) -> Generator[bytes, None, None]:
        """Yield MJPEG multipart frames for the given robot."""
        while True:
            frame = None
            with self._lock:
                buf = self._frames.get(robot_id)
                if buf:
                    frame = buf[-1]

            if frame:
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' +
                    frame +
                    b'\r\n'
                )
            else:
                time.sleep(0.05)

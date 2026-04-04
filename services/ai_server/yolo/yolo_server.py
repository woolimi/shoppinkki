"""ShopPinkki YOLO 추론 서버 (채널 F).

TCP:5005 에서 대기하며 control_service 로부터 JPEG 프레임을 수신,
YOLOv8 추론 후 bbox JSON 응답을 반환한다.

프로토콜 (binary, big-endian):
    요청  : [4B 길이][JPEG bytes]
    응답  : [4B 길이][JSON bytes]

JSON 응답 형식 (인형 감지 성공):
    {"cx": 320, "cy": 240, "area": 12000, "confidence": 0.92,
     "x1": 200, "y1": 100, "x2": 440, "y2": 380}

JSON 응답 형식 (감지 없음):
    {}

환경 변수:
    MODEL_PATH       — 커스텀 가중치 파일 경로 (없으면 FALLBACK_MODEL 사용)
    FALLBACK_MODEL   — 커스텀 모델 없을 때 사용할 베이스 모델 (기본 yolov8n.pt)
    YOLO_CONFIDENCE  — 신뢰도 임계값 (기본 0.40)
    HOST             — 바인드 호스트 (기본 0.0.0.0)
    PORT             — 바인드 포트 (기본 5005)
"""

from __future__ import annotations

import json
import logging
import os
import socket
import struct
import threading
from io import BytesIO
from typing import Optional

import cv2
import numpy as np
from ultralytics import YOLO

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('yolo_server')

# ── 환경 변수 ──────────────────────────────────────────────────────────────────
MODEL_PATH = os.environ.get('MODEL_PATH', '/app/models/doll_yolov8n.pt')
FALLBACK_MODEL = os.environ.get('FALLBACK_MODEL', 'yolov8n.pt')
YOLO_CONF = float(os.environ.get('YOLO_CONFIDENCE', '0.40'))
HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', '5005'))


def load_model() -> YOLO:
    """커스텀 모델 또는 베이스 모델 로드."""
    if os.path.isfile(MODEL_PATH):
        logger.info('커스텀 모델 로드: %s', MODEL_PATH)
        return YOLO(MODEL_PATH)
    logger.warning(
        '커스텀 모델 없음 (%s). 베이스 모델 사용: %s', MODEL_PATH, FALLBACK_MODEL
    )
    return YOLO(FALLBACK_MODEL)


def infer(model: YOLO, frame_bytes: bytes) -> dict:
    """JPEG bytes → YOLOv8 추론 → bbox dict.

    인형이 여러 개 감지될 경우 신뢰도 가장 높은 1개 반환.
    감지 없으면 빈 dict 반환.
    """
    # JPEG 디코드
    buf = np.frombuffer(frame_bytes, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        logger.warning('프레임 디코드 실패 (길이=%d)', len(frame_bytes))
        return {}

    results = model(img, conf=YOLO_CONF, verbose=False)

    best: Optional[dict] = None
    best_conf = -1.0

    for r in results:
        for box in r.boxes:
            conf = float(box.conf[0])
            if conf <= best_conf:
                continue
            x1, y1, x2, y2 = map(float, box.xyxy[0])
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0
            area = (x2 - x1) * (y2 - y1)
            best_conf = conf
            best = {
                'cx': round(cx, 1),
                'cy': round(cy, 1),
                'area': round(area, 1),
                'confidence': round(conf, 4),
                'x1': round(x1, 1),
                'y1': round(y1, 1),
                'x2': round(x2, 1),
                'y2': round(y2, 1),
            }

    return best if best is not None else {}


# ── TCP 연결 처리 ──────────────────────────────────────────────────────────────

def recv_all(sock: socket.socket, n: int) -> bytes:
    """정확히 n 바이트를 수신. 연결 종료 시 빈 bytes 반환."""
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return b''
        data += chunk
    return data


def handle_client(conn: socket.socket, addr: tuple, model: YOLO) -> None:
    """단일 클라이언트 연결 처리 (요청-응답 반복)."""
    logger.debug('연결: %s', addr)
    try:
        with conn:
            while True:
                # 요청 길이 (4B)
                len_b = recv_all(conn, 4)
                if not len_b:
                    break
                frame_len = struct.unpack('!I', len_b)[0]
                if frame_len == 0 or frame_len > 10_000_000:
                    logger.warning('비정상 프레임 길이: %d', frame_len)
                    break

                # JPEG 프레임 수신
                frame = recv_all(conn, frame_len)
                if len(frame) < frame_len:
                    break

                # 추론
                result = infer(model, frame)
                resp = json.dumps(result, ensure_ascii=False).encode()

                # 응답 전송 (4B 길이 + JSON)
                conn.sendall(struct.pack('!I', len(resp)) + resp)

    except Exception as e:
        logger.debug('클라이언트 오류 %s: %s', addr, e)
    finally:
        logger.debug('연결 종료: %s', addr)


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    model = load_model()
    logger.info('YOLO 모델 준비 완료. TCP %s:%d 대기 중...', HOST, PORT)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(32)

    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(
                target=handle_client, args=(conn, addr, model), daemon=True
            )
            t.start()
    except KeyboardInterrupt:
        logger.info('서버 종료')
    finally:
        server.close()


if __name__ == '__main__':
    main()

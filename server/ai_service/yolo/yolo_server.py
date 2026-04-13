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
    YOLO_CONFIDENCE  — 신뢰도 임계값 (기본 0.75)
    HOST             — 바인드 호스트 (기본 0.0.0.0)
    PORT             — 바인드 포트 (기본 5005)
"""

from __future__ import annotations

import json
import time
import logging
import os
import socket
import struct
import threading
from io import BytesIO
from typing import Optional

import cv2
import numpy as np
import torch
import torch.nn as nn
import torchvision.models as models
import torchvision.transforms as T
from ultralytics import YOLO

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('yolo_server')

# ── Configuration (Auto-detect paths) ────────────────────────────────────────
_script_dir = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(_script_dir, 'models')
CONFIG_PATH = os.path.join(_script_dir, 'active_model.json')

# ── 환경 변수 ──────────────────────────────────────────────────────────────────
MODEL_PATH = os.environ.get('MODEL_PATH', os.path.join(MODELS_DIR, 'best1.pt'))
FALLBACK_MODEL = os.environ.get('FALLBACK_MODEL', 'yolov8n.pt')
YOLO_CONF = float(os.environ.get('YOLO_CONFIDENCE', '0.50')) # Default lowered to 0.50
HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', '5005'))
ENABLE_REID = os.environ.get('ENABLE_REID', 'true').lower() == 'true'
# Parsing CLASS_FILTER (e.g. "0" or "0,1,2")
_filter_str = os.environ.get('YOLO_CLASS_FILTER', '').strip()
YOLO_CLASS_FILTER = [int(x) for x in _filter_str.split(',')] if _filter_str else []


# ── ReID 엔진 ────────────────────────────────────────────────────────────────
class ReIDEngine:
    def __init__(self):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        # MobileNetV3-Small: lightweight, fast inference
        backbone = models.mobilenet_v3_small(
            weights=models.MobileNet_V3_Small_Weights.IMAGENET1K_V1
        )
        # Remove the classifier head (1024-dim output)
        self.model = nn.Sequential(*list(backbone.children())[:-1])
        self.model.to(self.device)
        self.model.eval()

        self.transform = T.Compose([
            T.ToPILImage(),
            T.Resize((224, 224)),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406],
                        std=[0.229, 0.224, 0.225]),
        ])
        logger.info('ReIDEngine 로드 완료 (%s)', self.device)

    def extract(self, roi):
        try:
            rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
            tensor = self.transform(rgb).unsqueeze(0).to(self.device)
            with torch.no_grad():
                feat = self.model(tensor)
            feat = feat.squeeze().cpu().numpy().astype(np.float32)
            norm = np.linalg.norm(feat)
            if norm > 1e-8:
                feat = feat / norm
            return feat.tolist()
        except Exception as e:
            logger.debug('ReID 추출 실패: %s', e)
            return [0.0] * 1024


def load_model(path: str) -> YOLO:
    """모델 로드 helper."""
    if os.path.isfile(path):
        logger.info('YOLO 모델 로드: %s', path)
        return YOLO(path)
    logger.warning('모델 파일 없음: %s. 베이스 모델(yolov8n.pt) 사용.', path)
    return YOLO('yolov8n.pt')


class ModelManager:
    """YOLO 모델 동적 전환 관리자."""
    def __init__(self, initial_path: str):
        self.model = load_model(initial_path)
        self.current_path = initial_path
        self.confidence = YOLO_CONF
        self._lock = threading.Lock()
        logger.info('설정 파일 경로: %s', os.path.abspath(CONFIG_PATH))

    def get_model(self) -> YOLO:
        with self._lock:
            return self.model

    def reload(self, new_path: str):
        if new_path == self.current_path:
            return
        logger.info('YOLO 모델 교체 시도: %s -> %s', self.current_path, new_path)
        try:
            new_model = load_model(new_path)
            with self._lock:
                self.model = new_model
                self.current_path = new_path
            logger.info('YOLO 모델 교체 완료')
        except Exception as e:
            logger.error('YOLO 모델 교체 실패: %s', e)

    def check_config(self):
        if not os.path.exists(CONFIG_PATH):
            return
        try:
            # Race condition 방지: 파일이 쓰여지는 중일 수 있으므로 짧은 대기 후 읽기
            config = None
            for _ in range(3):
                try:
                    with open(CONFIG_PATH, 'r') as f:
                        config = json.load(f)
                    break
                except json.JSONDecodeError:
                    time.sleep(0.1)
            
            if not config:
                return

            # 모델 경로 체크
            new_model_name = config.get('active_model')
            if new_model_name:
                new_path = os.path.join(MODELS_DIR, new_model_name)
                if os.path.exists(new_path) and new_path != self.current_path:
                    self.reload(new_path)
            
            # 신뢰도 체크
            new_conf = config.get('confidence')
            if new_conf is not None and float(new_conf) != self.confidence:
                with self._lock:
                    self.confidence = float(new_conf)
                logger.info('신뢰도 임계값 변경됨: %.2f', self.confidence)

        except Exception as e:
            logger.debug('Config 읽기 실패: %s', e)

    def get_model_and_conf(self) -> tuple[YOLO, float]:
        with self._lock:
            return self.model, self.confidence


def infer(model: YOLO, reid: ReIDEngine, frame_bytes: bytes, confidence: float = 0.25, class_filter: list[int] = []) -> list[dict]:
    """JPEG bytes → YOLOv8 + ReID → list of detections.
    """
    buf = np.frombuffer(frame_bytes, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        return []

    # ByteTracker 적용 (persist=True) - retina_masks=False 로 성능 최적화
    results = model.track(img, persist=True, conf=confidence, verbose=False, retina_masks=False, imgsz=320)
    h_img, w_img = img.shape[:2]
    
    outputs = []
    # logger.debug(f"Inference with confidence threshold: {confidence}")
    
    for r in results:
        # Use universal indexing to support Detect, Segment, and Pose models
        for i in range(len(r)):
            det = r[i]
            conf = float(det.boxes.conf[0])
            
            # 🛡️ Double Filter: Manually enforce confidence threshold
            if conf < confidence:
                continue
                
            x1, y1, x2, y2 = map(float, det.boxes.xyxy[0])
            cls_id = int(det.boxes.cls[0])
            
            # 🛡️ Class Filter: Skip if not in allowed list
            if class_filter and cls_id not in class_filter:
                continue
            
            # ROI 크롭 및 ReID 추출 (활성화된 경우만)
            ix1, iy1, ix2, iy2 = map(int, [max(0, x1), max(0, y1), min(w_img, x2), min(h_img, y2)])
            features = [0.0] * 1024
            if ENABLE_REID and ix2 > ix1 and iy2 > iy1:
                roi = img[iy1:iy2, ix1:ix2]
                features = reid.extract(roi)

            # Segmentation 마스크 추출 및 클리닝 (Morphological Opening)
            mask_pts = None
            if hasattr(r, 'masks') and r.masks is not None and r.masks.data is not None:
                # r.masks.data (bitmask tensor) 에서 해당 인덱스 추출 및 0-255 스케일링
                m_data = (r.masks.data[i].cpu().numpy() * 255).astype(np.uint8)
                
                # Morphological Opening 으로 노이즈 제거 및 테두리 정돈
                kernel = np.ones((5, 5), np.uint8)
                m_clean = cv2.morphologyEx(m_data, cv2.MORPH_OPEN, kernel)
                
                # 정돈된 마스크를 컨투어로 변환하여 좌표 리스트 생성
                contours, _ = cv2.findContours(m_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if contours:
                    # 마스크 데이터를 원본 이미지 크기로 스케일링
                    # model.track(imgsz=640)인 경우 m_clean은 640x640 혹은 원본비율에 맞춰 리사이즈됨
                    # 여기서는 원본 이미지 h_img, w_img 에 맞춰 다시 보정
                    c = contours[0].reshape(-1, 2).astype(np.float32)
                    h_mask, w_mask = m_clean.shape[:2]
                    c[:, 0] *= (w_img / w_mask)
                    c[:, 1] *= (h_img / h_mask)
                    mask_pts = c.astype(np.int32).tolist()
            elif hasattr(r, 'masks') and r.masks is not None:
                # Fallback: raw xy 마스크
                m = r.masks.xy[i]
                if len(m) > 0:
                    mask_pts = m.tolist()

            outputs.append({
                'cx': round((x1 + x2) / 2.0, 1),
                'cy': round((y1 + y2) / 2.0, 1),
                'area': round((x2 - x1) * (y2 - y1), 1),
                'confidence': round(conf, 4),
                'x1': round(x1, 1),
                'y1': round(y1, 1),
                'x2': round(x2, 1),
                'y2': round(y2, 1),
                'features': features,
                'mask': mask_pts
            })

    if outputs:
        logger.info('감지 성공: %d개 인형 (conf=%.2f)', len(outputs), outputs[0]['confidence'])

    return outputs


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


def handle_client(conn: socket.socket, addr: tuple, model_manager: ModelManager, reid: ReIDEngine) -> None:
    """단일 클라이언트 연결 처리 (요청-응답 반복)."""
    logger.info('--- [NEW CONNECTION] Pinky Robot Joined: %s ---', addr)
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

                # 추론 (YOLO + ReID)
                current_model, current_conf = model_manager.get_model_and_conf()
                result = infer(current_model, reid, frame, confidence=current_conf, class_filter=YOLO_CLASS_FILTER)
                resp = json.dumps(result, ensure_ascii=False).encode()

                # 응답 전송 (4B 길이 + JSON)
                conn.sendall(struct.pack('!I', len(resp)) + resp)

    except Exception as e:
        logger.debug('클라이언트 오류 %s: %s', addr, e)
    finally:
        logger.debug('연결 종료: %s', addr)


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # 초기 모델 경로 설정
    initial_path = MODEL_PATH
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                conf = json.load(f)
                if conf.get('active_model'):
                    initial_path = os.path.join(MODELS_DIR, conf['active_model'])
        except: pass

    model_manager = ModelManager(initial_path)
    reid = ReIDEngine()

    # Config 감시 스레드 (1초마다 체크)
    def config_watcher():
        while True:
            model_manager.check_config()
            time.sleep(1.0)
    
    threading.Thread(target=config_watcher, daemon=True).start()

    logger.info('AI 서버 준비 완료 (YOLO + ReID). TCP %s:%d 대기 중...', HOST, PORT)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(32)

    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(
                target=handle_client, args=(conn, addr, model_manager, reid), daemon=True
            )
            t.start()
    except KeyboardInterrupt:
        logger.info('서버 종료')
    finally:
        server.close()


if __name__ == '__main__':
    main()

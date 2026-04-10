"""DollDetector — 주인 인형 등록 + ReID + IoU 추적 기반 추종.

등록 흐름 (SC-01):
    1. IDLE 상태에서 register(frame) 반복 호출
       → YOLO로 인형 감지 시 pending_snapshot 저장 (2초 rate-limit)
    2. 브라우저에서 사용자가 스냅샷 확인 후 confirm_registration(frame, bbox) 호출
       → CNN ReID 피처 추출 → gallery[0] 초기화 → _ready = True
    3. run(frame) 을 호출하면 owner를 식별해 get_latest() 로 노출

추종 중 자동 보정 (joey_detection 방식):
    - 30프레임마다, gallery 최대 유사도 < 0.94 && gallery < 50 → 새 피처 추가
    - 다양한 각도/조명에서 자동 갤러리 확장

safe_id 잠금 (ByteTrack-like, IoU 트래커 연동):
    - 5프레임 연속 ReID 매칭 통과 시 track_id 잠금
    - 잠금 후에는 ID 기반 빠른 경로 (ReID 연산 생략)

세션 종료 시 reset() 호출 → 메모리 전체 소거 (파일 저장 없음).
"""

from __future__ import annotations

import base64
import logging
import socket
import struct
import threading
import time
from typing import Dict, List, Optional, Tuple

from shoppinkki_interfaces import Detection

from .iou_tracker import IouTracker
from .reid_engine import ReIDEngine

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────────────
MIN_CONFIDENCE: float = 0.4       # YOLO 최소 신뢰도
REID_THRESHOLD: float = 0.55      # ReID 코사인 유사도 임계값 (갤러리 max)
HSV_THRESHOLD: float = 0.45       # HSV 히스토그램 상관계수 임계값
CALIBRATION_ADD_THRESHOLD: float = 0.94  # 이 이상이면 이미 커버됨 → 갤러리 추가 안 함
MAX_GALLERY_SIZE: int = 50        # 최대 갤러리 크기
VERIFY_FRAMES: int = 5            # safe_id 잠금 필요 연속 매칭 횟수
CALIBRATION_INTERVAL: int = 30    # 자동 보정 프레임 간격


class DollDetector:
    """주인 인형 감지·추종 구현체.

    Parameters
    ----------
    yolo_host:
        YOLO TCP 서버 호스트 (기본: env YOLO_HOST 또는 '127.0.0.1')
    yolo_port:
        YOLO TCP 서버 포트 (기본: 5005)
    """

    def __init__(
        self,
        yolo_host: str = '127.0.0.1',
        yolo_port: int = 5005,
    ) -> None:
        self._host = yolo_host
        self._port = yolo_port
        self._lock = threading.Lock()

        # ── ReID 엔진 ──────────────────────────────────────────────
        self._reid = ReIDEngine()

        # ── IoU 트래커 ─────────────────────────────────────────────
        self._tracker = IouTracker(max_age=10, min_iou=0.3)

        # ── 갤러리 (CNN 피처 벡터 리스트) ──────────────────────────
        self._gallery: List[List[float]] = []

        # ── HSV 템플릿 (단일, 등록 시 고정) ───────────────────────
        self._template_hsv: Optional[List[float]] = None

        # ── 등록 완료 플래그 ───────────────────────────────────────
        self._ready: bool = False

        # ── 최신 감지 결과 ─────────────────────────────────────────
        self._latest: Optional[Detection] = None

        # ── pending snapshot (등록 전 사용자 확인용) ───────────────
        # (jpeg_bytes, bbox_dict)
        self._pending_snapshot: Optional[Tuple[bytes, dict]] = None

        # ── safe_id (track_id 잠금) ────────────────────────────────
        self._safe_id: Optional[int] = None
        self._verification_buffer: Dict[int, int] = {}  # track_id → 연속 매칭 횟수

        # ── 자동 보정 카운터 ───────────────────────────────────────
        self._frame_count: int = 0

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def register(self, frame) -> None:
        """IDLE 상태에서 호출. 인형이 감지되면 pending_snapshot을 갱신한다.

        실제 템플릿 등록은 confirm_registration() 에서 수행.
        """
        detections = self._run_yolo(frame)
        if not detections:
            return

        best = max(detections, key=lambda d: d.get('confidence', 0))
        if best.get('confidence', 0) < MIN_CONFIDENCE:
            return

        roi = self._extract_roi(frame, best)
        if roi is None:
            return

        # ROI → JPEG
        jpeg = _roi_to_jpeg(roi)
        with self._lock:
            self._pending_snapshot = (jpeg, best)

    def confirm_registration(self, frame, bbox: dict) -> None:
        """사용자가 확인한 frame+bbox로 즉시 템플릿 등록.

        이 메서드가 호출된 후 is_ready() == True 가 된다.
        """
        roi = self._extract_roi(frame, bbox)
        if roi is None:
            logger.warning('DollDetector: confirm_registration ROI 추출 실패')
            return

        reid_vec = self._reid.extract_features(roi).tolist()
        hsv_vec = self._compute_hsv_hist(roi)

        with self._lock:
            self._gallery = [reid_vec]
            self._template_hsv = hsv_vec
            self._ready = True
            self._pending_snapshot = None
            self._safe_id = None
            self._verification_buffer.clear()
            self._frame_count = 0
        logger.info('DollDetector: 주인 인형 등록 완료 (gallery 초기화)')

    def run(self, frame) -> None:
        """TRACKING 상태에서 매 프레임 호출. 주인 인형을 식별해 _latest 갱신."""
        if not self._ready:
            return

        raw_detections = self._run_yolo(frame)
        detections = self._tracker.update(raw_detections) if raw_detections else []

        self._frame_count += 1

        best_det: Optional[dict] = None
        best_reid_vec: Optional[List[float]] = None

        with self._lock:
            gallery_snapshot = list(self._gallery)
            hsv_template = self._template_hsv
            safe_id = self._safe_id

        for d in detections:
            if d.get('confidence', 0) < MIN_CONFIDENCE:
                continue

            tid = d['track_id']

            # 빠른 경로: safe_id 일치 시 ReID 생략
            if safe_id is not None and tid == safe_id:
                best_det = d
                # 자동 보정용 피처는 백그라운드에서 계산
                roi = self._extract_roi(frame, d)
                if roi is not None:
                    best_reid_vec = self._reid.extract_features(roi).tolist()
                break

            # 일반 경로: ReID + HSV 매칭
            roi = self._extract_roi(frame, d)
            if roi is None:
                continue

            reid_vec = self._reid.extract_features(roi).tolist()
            hsv_vec = self._compute_hsv_hist(roi)

            if not gallery_snapshot:
                continue

            reid_sim = max(_cosine_similarity(g, reid_vec) for g in gallery_snapshot)
            hsv_sim = _histogram_correlation(hsv_template or [], hsv_vec)

            if reid_sim >= REID_THRESHOLD and hsv_sim >= HSV_THRESHOLD:
                # verification buffer 업데이트
                with self._lock:
                    cnt = self._verification_buffer.get(tid, 0) + 1
                    self._verification_buffer[tid] = cnt
                    if cnt >= VERIFY_FRAMES and self._safe_id is None:
                        self._safe_id = tid
                        logger.info('DollDetector: track_id=%d → safe_id 잠금', tid)

                best_det = d
                best_reid_vec = reid_vec
                break
            else:
                # 불일치 → buffer 리셋
                with self._lock:
                    self._verification_buffer.pop(tid, None)

        # _latest 갱신
        with self._lock:
            if best_det is not None:
                self._latest = Detection(
                    cx=float(best_det.get('cx', 0)),
                    cy=float(best_det.get('cy', 0)),
                    area=float(best_det.get('area',
                               best_det.get('w', 0) * best_det.get('h', 0))),
                    confidence=float(best_det.get('confidence', 0)),
                )
            else:
                self._latest = None

        # 자동 보정: 30프레임마다 갤러리 확장
        if (best_det is not None and best_reid_vec is not None
                and self._frame_count % CALIBRATION_INTERVAL == 0):
            self._try_calibrate(best_reid_vec)

    def get_latest(self) -> Optional[Detection]:
        with self._lock:
            return self._latest

    def is_ready(self) -> bool:
        with self._lock:
            return self._ready

    def get_pending_snapshot(self) -> Optional[Tuple[bytes, dict]]:
        """(jpeg_bytes, bbox_dict) 또는 None."""
        with self._lock:
            return self._pending_snapshot

    def clear_pending_snapshot(self) -> None:
        with self._lock:
            self._pending_snapshot = None

    def reset(self) -> None:
        """세션 종료 시 호출 — 모든 추종 데이터 소거 (메모리 전용)."""
        with self._lock:
            self._gallery.clear()
            self._template_hsv = None
            self._ready = False
            self._latest = None
            self._pending_snapshot = None
            self._safe_id = None
            self._verification_buffer.clear()
            self._frame_count = 0
        self._tracker.reset()
        logger.info('DollDetector: reset 완료')

    # ── 내부 메서드 ──────────────────────────────────────────────────────────

    def _try_calibrate(self, reid_vec: List[float]) -> None:
        """갤러리에 새 피처 추가 (자동 보정)."""
        with self._lock:
            if not self._gallery:
                return
            scores = [_cosine_similarity(g, reid_vec) for g in self._gallery]
            if max(scores) < CALIBRATION_ADD_THRESHOLD and len(self._gallery) < MAX_GALLERY_SIZE:
                self._gallery.append(reid_vec)
                logger.debug('DollDetector: 갤러리 보정 추가 (size=%d)', len(self._gallery))

    # ── YOLO 클라이언트 ───────────────────────────────────────────────────────

    def _run_yolo(self, frame) -> List[dict]:
        """JPEG 프레임을 YOLO TCP 서버에 전송, bbox 리스트 반환."""
        try:
            jpeg = _to_jpeg(frame)
            with socket.create_connection(
                    (self._host, self._port), timeout=0.5) as s:
                header = struct.pack('!I', len(jpeg))
                s.sendall(header + jpeg)
                resp_len_b = _recv_exact(s, 4)
                if resp_len_b is None:
                    return []
                resp_len = struct.unpack('!I', resp_len_b)[0]
                resp_data = _recv_exact(s, resp_len)
                if resp_data is None:
                    return []
            import json
            result = json.loads(resp_data.decode())
            if isinstance(result, dict):
                return [result] if result else []
            if isinstance(result, list):
                return result
            return []
        except Exception as e:
            logger.debug('DollDetector: YOLO 쿼리 실패: %s', e)
            return []

    # ── 피처 추출 ─────────────────────────────────────────────────────────────

    def _extract_roi(self, frame, det: dict):
        """bbox dict (cx, cy, x1, y1, x2, y2) 로 ROI 크롭."""
        try:
            import numpy as np
            img = _ensure_numpy(frame)
            h_img, w_img = img.shape[:2]

            if 'x1' in det and 'x2' in det and 'y1' in det and 'y2' in det:
                x1 = max(0, int(det['x1']))
                y1 = max(0, int(det['y1']))
                x2 = min(w_img, int(det['x2']))
                y2 = min(h_img, int(det['y2']))
            else:
                cx = int(det.get('cx', w_img // 2))
                cy = int(det.get('cy', h_img // 2))
                side = int(det.get('area', 10000) ** 0.5)
                x1 = max(0, cx - side // 2)
                y1 = max(0, cy - side // 2)
                x2 = min(w_img, cx + side // 2)
                y2 = min(h_img, cy + side // 2)

            if x2 <= x1 or y2 <= y1:
                return None
            return img[y1:y2, x1:x2]
        except Exception as e:
            logger.debug('DollDetector: ROI 추출 실패: %s', e)
            return None

    def _compute_hsv_hist(self, roi) -> List[float]:
        """HSV 히스토그램 (16H + 16S + 16V = 48 floats, 정규화)."""
        try:
            import numpy as np
            import cv2
            if roi is None or roi.size == 0:
                return [0.0] * 48
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            hist_h = cv2.calcHist([hsv], [0], None, [16], [0, 180]).flatten()
            hist_s = cv2.calcHist([hsv], [1], None, [16], [0, 256]).flatten()
            hist_v = cv2.calcHist([hsv], [2], None, [16], [0, 256]).flatten()
            hist = np.concatenate([hist_h, hist_s, hist_v])
            total = hist.sum()
            if total > 0:
                hist = hist / total
            return hist.tolist()
        except Exception as e:
            logger.debug('DollDetector: HSV hist 실패: %s', e)
            return [0.0] * 48


# ── 순수 수학 헬퍼 ────────────────────────────────────────────────────────────

def _cosine_similarity(a: List[float], b: List[float]) -> float:
    try:
        import math
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)
    except Exception:
        return 0.0


def _histogram_correlation(a: List[float], b: List[float]) -> float:
    """Pearson 상관계수 [-1,1] → [0,1] 매핑."""
    try:
        n = len(a)
        if n == 0 or len(b) != n:
            return 0.0
        mean_a = sum(a) / n
        mean_b = sum(b) / n
        num = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
        den_a = (sum((x - mean_a) ** 2 for x in a)) ** 0.5
        den_b = (sum((y - mean_b) ** 2 for y in b)) ** 0.5
        if den_a == 0 and den_b == 0:
            if abs(mean_a) < 1e-9 and abs(mean_b) < 1e-9:
                return 0.0
            return 1.0 if abs(mean_a - mean_b) < 1e-9 else 0.0
        if den_a == 0 or den_b == 0:
            return 0.5
        return (num / (den_a * den_b) + 1.0) / 2.0
    except Exception:
        return 0.0


# ── I/O 헬퍼 ──────────────────────────────────────────────────────────────────

def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def _to_jpeg(frame) -> bytes:
    if isinstance(frame, (bytes, bytearray)):
        return bytes(frame)
    try:
        import cv2
        _, buf = cv2.imencode('.jpg', frame)
        return bytes(buf)
    except Exception:
        return bytes(frame)


def _roi_to_jpeg(roi) -> bytes:
    """ROI numpy 배열(BGR) → JPEG bytes."""
    try:
        import cv2
        rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        _, buf = cv2.imencode('.jpg', rgb, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return bytes(buf)
    except Exception:
        return b''


def _ensure_numpy(frame):
    if hasattr(frame, 'shape'):
        return frame
    try:
        import numpy as np
        import cv2
        arr = np.frombuffer(frame, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        import numpy as np
        return np.zeros((64, 64, 3), dtype=np.uint8)

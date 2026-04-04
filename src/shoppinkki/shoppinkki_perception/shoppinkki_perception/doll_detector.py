"""DollDetector — ReID + HSV histogram owner-doll tracker.

Pipeline (per frame):
    1. Send JPEG frame to control_service → AI Server YOLO via TCP.
       Receive list of bbox dicts: [{cx, cy, w, h, confidence}, ...].
    2. For each detected bbox, extract ROI from frame.
    3. If REGISTERED (is_ready()):
        - Compute ReID feature vector + HSV histogram for the ROI.
        - Compare against stored template.  Pick best-match candidate.
        - Store as latest Detection if similarity >= threshold.
    4. If IDLE (register phase):
        - Accumulate templates from high-confidence detections.
        - Mark ready after MIN_REGISTER_FRAMES consistent detections.

Offline / no-YOLO mode:
    If YOLO_HOST is unreachable, doll_detector.run() silently returns
    None (Detection not updated). Behaviour remains correct for testing.
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
from typing import List, Optional

from shoppinkki_interfaces import Detection

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────
MIN_CONFIDENCE = 0.4       # minimum YOLO confidence to consider
REID_THRESHOLD = 0.55      # cosine similarity threshold
HSV_THRESHOLD = 0.45       # histogram correlation threshold
MIN_REGISTER_FRAMES = 5    # frames needed to confirm owner template
COMBINED_WEIGHT_REID = 0.6
COMBINED_WEIGHT_HSV = 0.4


class DollDetector:
    """DollDetectorInterface implementation.

    Parameters
    ----------
    yolo_host:
        Hostname of the YOLO TCP server (default: value of env var
        YOLO_HOST or '127.0.0.1').
    yolo_port:
        Port of the YOLO TCP server (default: 5005).
    """

    def __init__(
        self,
        yolo_host: str = '127.0.0.1',
        yolo_port: int = 5005,
    ) -> None:
        self._host = yolo_host
        self._port = yolo_port
        self._lock = threading.Lock()

        # Template storage
        self._template_reid: Optional[List[float]] = None
        self._template_hsv: Optional[List[float]] = None
        self._register_count: int = 0
        self._ready: bool = False

        # Latest detection result
        self._latest: Optional[Detection] = None

    # ── DollDetectorInterface ─────────────────

    def register(self, frame) -> None:
        """Accumulate owner template from IDLE phase detections.

        frame: numpy ndarray (BGR) or bytes (JPEG).
        """
        detections = self._run_yolo(frame)
        if not detections:
            return

        # Pick best-confidence detection as candidate template
        best = max(detections, key=lambda d: d.get('confidence', 0))
        if best.get('confidence', 0) < MIN_CONFIDENCE:
            return

        roi = self._extract_roi(frame, best)
        if roi is None:
            return

        reid_vec = self._compute_reid(roi)
        hsv_vec = self._compute_hsv_hist(roi)

        with self._lock:
            if self._template_reid is None:
                self._template_reid = reid_vec
                self._template_hsv = hsv_vec
                self._register_count = 1
            else:
                # Running average
                self._template_reid = _avg_lists(self._template_reid, reid_vec)
                self._template_hsv = _avg_lists(self._template_hsv, hsv_vec)
                self._register_count += 1

            if self._register_count >= MIN_REGISTER_FRAMES:
                self._ready = True
                logger.info('DollDetector: owner template registered '
                            '(frames=%d)', self._register_count)

    def run(self, frame) -> None:
        """Detect and identify the owner doll in a frame.

        Updates the internal latest detection buffer.
        frame: numpy ndarray (BGR) or bytes (JPEG).
        """
        if not self._ready:
            return

        detections = self._run_yolo(frame)
        if not detections:
            with self._lock:
                self._latest = None
            return

        best_det = None
        best_score = -1.0

        for d in detections:
            if d.get('confidence', 0) < MIN_CONFIDENCE:
                continue
            roi = self._extract_roi(frame, d)
            if roi is None:
                continue
            reid_vec = self._compute_reid(roi)
            hsv_vec = self._compute_hsv_hist(roi)

            with self._lock:
                if self._template_reid is None:
                    continue
                reid_sim = _cosine_similarity(self._template_reid, reid_vec)
                hsv_sim = _histogram_correlation(self._template_hsv, hsv_vec)

            score = (COMBINED_WEIGHT_REID * reid_sim
                     + COMBINED_WEIGHT_HSV * hsv_sim)

            if (score > best_score
                    and reid_sim >= REID_THRESHOLD
                    and hsv_sim >= HSV_THRESHOLD):
                best_score = score
                best_det = d

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

    def get_latest(self) -> Optional[Detection]:
        with self._lock:
            return self._latest

    def is_ready(self) -> bool:
        with self._lock:
            return self._ready

    def reset(self) -> None:
        with self._lock:
            self._template_reid = None
            self._template_hsv = None
            self._register_count = 0
            self._ready = False
            self._latest = None
        logger.info('DollDetector: reset')

    # ── YOLO client ───────────────────────────

    def _run_yolo(self, frame) -> List[dict]:
        """Send frame to YOLO server, return list of bbox dicts."""
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
            # Support both single bbox dict and list of dicts
            if isinstance(result, dict):
                return [result]
            if isinstance(result, list):
                return result
            return []
        except Exception as e:
            logger.debug('DollDetector: YOLO query failed: %s', e)
            return []

    # ── Feature extraction ────────────────────

    def _extract_roi(self, frame, det: dict):
        """Crop ROI from frame using bbox (cx, cy, w, h or area)."""
        try:
            import numpy as np
            img = _ensure_numpy(frame)
            h_img, w_img = img.shape[:2]
            cx = int(det.get('cx', w_img // 2))
            cy = int(det.get('cy', h_img // 2))
            w = int(det.get('w', det.get('area', 10000) ** 0.5))
            h = int(det.get('h', det.get('area', 10000) ** 0.5))
            x1 = max(0, cx - w // 2)
            y1 = max(0, cy - h // 2)
            x2 = min(w_img, cx + w // 2)
            y2 = min(h_img, cy + h // 2)
            if x2 <= x1 or y2 <= y1:
                return None
            return img[y1:y2, x1:x2]
        except Exception as e:
            logger.debug('DollDetector: ROI extraction failed: %s', e)
            return None

    def _compute_reid(self, roi) -> List[float]:
        """Compute a simple appearance feature vector from ROI.

        In production this would be a CNN embedding. Here we use
        a lightweight mean-colour vector (R, G, B per channel mean)
        as a placeholder until a real ReID model is integrated.
        """
        try:
            import numpy as np
            if roi is None or roi.size == 0:
                return [0.0] * 3
            roi_resized = _resize(roi, (32, 64))
            # Flatten colour statistics: mean + std per channel
            features = []
            for c in range(roi_resized.shape[2] if len(roi_resized.shape) == 3 else 1):
                ch = roi_resized[:, :, c] if len(roi_resized.shape) == 3 else roi_resized
                features.append(float(np.mean(ch)) / 255.0)
                features.append(float(np.std(ch)) / 255.0)
            return features
        except Exception as e:
            logger.debug('DollDetector: ReID feature error: %s', e)
            return [0.0] * 6

    def _compute_hsv_hist(self, roi) -> List[float]:
        """Compute normalised HSV histogram as colour signature."""
        try:
            import numpy as np
            import cv2
            if roi is None or roi.size == 0:
                return [0.0] * 48  # 16H + 16S + 16V
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
            logger.debug('DollDetector: HSV hist error: %s', e)
            return [0.0] * 48


# ── Pure math helpers ─────────────────────────

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
    """Normalised cross-correlation in [−1, 1], mapped to [0, 1].

    For zero-variance histograms (constant vectors):
      - Both constant and equal  → 1.0  (identical)
      - Both constant, different → 0.0  (cannot compare)
      - One constant             → 0.5  (undefined)
    """
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
            # Both constant: equal iff same non-zero mean
            if abs(mean_a) < 1e-9 and abs(mean_b) < 1e-9:
                return 0.0  # both zero-vectors — no information
            return 1.0 if abs(mean_a - mean_b) < 1e-9 else 0.0
        if den_a == 0 or den_b == 0:
            return 0.5
        return (num / (den_a * den_b) + 1.0) / 2.0
    except Exception:
        return 0.0


def _avg_lists(a: List[float], b: List[float]) -> List[float]:
    return [(x + y) / 2.0 for x, y in zip(a, b)]


def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def _to_jpeg(frame) -> bytes:
    """Convert numpy array or bytes to JPEG bytes."""
    if isinstance(frame, (bytes, bytearray)):
        return bytes(frame)
    try:
        import cv2
        import numpy as np
        _, buf = cv2.imencode('.jpg', frame)
        return bytes(buf)
    except Exception:
        return bytes(frame)


def _ensure_numpy(frame):
    """Ensure frame is a numpy BGR image."""
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


def _resize(img, size: tuple):
    try:
        import cv2
        return cv2.resize(img, size)
    except Exception:
        return img

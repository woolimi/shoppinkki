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
import os
try:
    from ultralytics import YOLO
    _ULTRALYTICS_AVAILABLE = True
except ImportError:
    _ULTRALYTICS_AVAILABLE = False

from shoppinkki_interfaces import Detection

from .iou_tracker import IouTracker
from .reid_engine import ReIDEngine

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────────────
MIN_CONFIDENCE: float = float(os.environ.get('MIN_CONFIDENCE', '0.45'))  # YOLO 최소 신뢰도 (0.25 -> 0.45)
REGISTRATION_MIN_CONFIDENCE: float = 0.20  # 등록 단계 추가 신뢰도 임계값
REGISTRATION_MIN_AREA_RATIO: float = 0.005  # 등록 단계 bbox 최소 화면 점유율
REGISTRATION_SNAPSHOT_COOLDOWN: float = 0.4  # 등록 스냅샷 최소 간격(초)
REGISTRATION_STABLE_FRAMES: int = 1  # 동일 후보 연속 감지 필요 프레임 수
REID_THRESHOLD: float = float(os.environ.get('REID_THRESHOLD', '0.55')) # ReID 임계값 (0.40 -> 0.55)
HSV_THRESHOLD: float = 0.45       # HSV 히스토그램 상관계수 임계값 (0.25 -> 0.45)
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
    model_path:
        로컬 NCNN 모델 경로 (기본: /home/pinky/ros_ws/server/ai_service/yolo/models/best1_ncnn_model)
    """

    def __init__(
        self,
        yolo_host: str = '127.0.0.1',
        yolo_port: int = 5005,
        model_path: str = '/home/pinky/ros_ws/server/ai_service/yolo/models/best1_ncnn_model'
    ) -> None:
        self._host = yolo_host
        self._port = yolo_port
        self._lock = threading.Lock()
        # Owner following defaults to remote server to save Pi 5 resources.
        self._force_local_ncnn = os.environ.get('FORCE_LOCAL_NCNN', 'false').lower() == 'true'
        # Runtime NCNN confidence threshold (0.0~1.0), default 0.25
        try:
            self._ncnn_conf = float(os.environ.get('NCNN_CONF', str(MIN_CONFIDENCE)))
        except Exception:
            self._ncnn_conf = MIN_CONFIDENCE
        self._ncnn_conf = max(0.01, min(1.0, self._ncnn_conf))
        try:
            # Lower default for faster real-time updates on Pi 5.
            # 320 is typically 2x faster than 416 on CPU.
            self._ncnn_imgsz = int(os.environ.get('NCNN_IMGSZ', '320'))
        except Exception:
            self._ncnn_imgsz = 320
        self._ncnn_imgsz = max(160, min(1280, self._ncnn_imgsz))
        self._single_class_model = False
        self._registration_require_red = (
            os.environ.get('REGISTRATION_REQUIRE_RED', 'false').lower() == 'true'
        )
        self._reject_dark_objects = (
            os.environ.get('REJECT_DARK_OBJECTS', 'true').lower() == 'true'
        )
        try:
            self._dark_ratio_threshold = float(os.environ.get('DARK_RATIO_THRESHOLD', '0.40')) # Stricter dark rejection (0.50 -> 0.40)
        except Exception:
            self._dark_ratio_threshold = 0.40
        self._dark_ratio_threshold = max(0.05, min(0.95, self._dark_ratio_threshold))

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
        self._pending_confirm_frame = None
        self._pending_confirm_bbox: Optional[dict] = None
        self._last_registration_snapshot_ts: float = 0.0
        self._reg_candidate_bbox: Optional[Tuple[float, float, float, float]] = None
        self._reg_candidate_hits: int = 0
        self._last_reg_debug_ts: float = 0.0

        # ── safe_id (track_id 잠금) ────────────────────────────────
        self._safe_id: Optional[int] = None
        self._verification_buffer: Dict[int, int] = {}  # track_id → 연속 매칭 횟수

        # ── 자동 보정 카운터 ───────────────────────────────────────
        self._frame_count: int = 0

        # ── YOLO 소켓 (Persistent Connection) ──────────────────────
        self._socket: Optional[socket.socket] = None
        self._socket_lock = threading.Lock()

        # ── 디버그 모드 (모든 인형 감지 결과 노출) ─────────────────
        self.show_all_detections = os.environ.get('YOLO_DEBUG', 'false').lower() == 'true'
        self._connected = False
        self._last_count = 0
        
        # ── 로컬 YOLO (NCNN) ───────────────────────────────────────
        if _ULTRALYTICS_AVAILABLE and os.path.exists(model_path):
            try:
                # Let Ultralytics infer task (detect/segment) from model metadata.
                self._local_model = YOLO(model_path)
                try:
                    names = getattr(self._local_model, 'names', None)
                    if isinstance(names, dict):
                        self._single_class_model = len(names) == 1
                    elif isinstance(names, (list, tuple)):
                        self._single_class_model = len(names) == 1
                except Exception:
                    self._single_class_model = False
                logger.info(
                    'DollDetector: 로컬 모델 로드 완료 (%s, conf=%.2f, imgsz=%d, single_class=%s)',
                    model_path, self._ncnn_conf, self._ncnn_imgsz, self._single_class_model
                )
            except Exception as e:
                logger.error('DollDetector: 로컬 모델 로드 실패: %s', e)
        else:
            if not _ULTRALYTICS_AVAILABLE:
                logger.info('DollDetector: ultralytics 미설치 — 원격 모드만 사용 가능')
            else:
                logger.warning('DollDetector: 로컬 모델 없음 (%s), 원격 서버 사용 시도', model_path)

    # ── 공개 API ──────────────────────────────────────────────────────────────
    
    def is_connected(self) -> bool:
        return self._connected

    def get_latest_count(self) -> int:
        return self._last_count

    def register(self, frame) -> None:
        """IDLE 상태에서 호출. 인형이 감지되면 pending_snapshot을 갱신한다.

        실제 템플릿 등록은 confirm_registration() 에서 수행.
        """
        detections = self._run_yolo(frame)
        if detections:
            logger.info('DollDetector: 등록 중 %d개 감지', len(detections))
        if not detections:
            self._log_registration_debug(total=0, in_ellipse=0, class_ok=0, top_conf=0.0, red_ratio=0.0, reason='no_detections')
            return

        # Registration guide: only accept detections whose center is inside
        # the same ellipse used by LCD registration UI.
        in_ellipse = [d for d in detections if self._is_in_registration_ellipse(frame, d)]
        if not in_ellipse:
            self._log_registration_debug(
                total=len(detections),
                in_ellipse=0,
                class_ok=0,
                top_conf=max(float(d.get('confidence', 0.0)) for d in detections),
                red_ratio=0.0,
                reason='outside_ellipse',
            )
            self._reg_candidate_hits = 0
            self._reg_candidate_bbox = None
            return

        candidates = [d for d in in_ellipse if self._is_doll_class(d)]
        if not candidates:
            self._log_registration_debug(
                total=len(detections),
                in_ellipse=len(in_ellipse),
                class_ok=0,
                top_conf=max(float(d.get('confidence', 0.0)) for d in in_ellipse),
                red_ratio=0.0,
                reason='class_filter',
            )
            self._reg_candidate_hits = 0
            self._reg_candidate_bbox = None
            return
        if self._reject_dark_objects:
            dark_filtered = [
                d for d in candidates
                if not self._is_mostly_dark(frame, d, threshold=self._dark_ratio_threshold)
            ]
            if not dark_filtered:
                self._log_registration_debug(
                    total=len(detections),
                    in_ellipse=len(in_ellipse),
                    class_ok=0,
                    top_conf=max(float(d.get('confidence', 0.0)) for d in candidates),
                    red_ratio=0.0,
                    reason='dark_filter',
                )
                self._reg_candidate_hits = 0
                self._reg_candidate_bbox = None
                return
            candidates = dark_filtered

        best = max(candidates, key=lambda d: d.get('confidence', 0))
        if best.get('confidence', 0) < REGISTRATION_MIN_CONFIDENCE:
            self._log_registration_debug(
                total=len(detections),
                in_ellipse=len(in_ellipse),
                class_ok=len(candidates),
                top_conf=float(best.get('confidence', 0.0)),
                red_ratio=0.0,
                reason='low_confidence',
            )
            self._reg_candidate_hits = 0
            self._reg_candidate_bbox = None
            return

        img = _ensure_numpy(frame)
        frame_area = float(max(1, img.shape[0] * img.shape[1]))
        area = float(best.get('area', 0.0))
        if (area / frame_area) < REGISTRATION_MIN_AREA_RATIO:
            self._log_registration_debug(
                total=len(detections),
                in_ellipse=len(in_ellipse),
                class_ok=len(candidates),
                top_conf=float(best.get('confidence', 0.0)),
                red_ratio=0.0,
                reason='small_area',
            )
            self._reg_candidate_hits = 0
            self._reg_candidate_bbox = None
            return

        # Optional hard gate to reject human-like false positives during registration.
        red_ratio = self._compute_red_ratio(frame, best)
        if self._registration_require_red and red_ratio < 0.08:
            self._log_registration_debug(
                total=len(detections),
                in_ellipse=len(in_ellipse),
                class_ok=len(candidates),
                top_conf=float(best.get('confidence', 0.0)),
                red_ratio=red_ratio,
                reason='red_filter',
            )
            self._reg_candidate_hits = 0
            self._reg_candidate_bbox = None
            return

        # Temporal stability gate: require the same candidate in a few
        # consecutive frames before prompting on the web page.
        curr_bbox = (
            float(best.get('x1', 0.0)),
            float(best.get('y1', 0.0)),
            float(best.get('x2', 0.0)),
            float(best.get('y2', 0.0)),
        )
        if self._reg_candidate_bbox is None:
            self._reg_candidate_bbox = curr_bbox
            self._reg_candidate_hits = 1
            return

        iou = self._bbox_iou(self._reg_candidate_bbox, curr_bbox)
        if iou >= 0.5:
            self._reg_candidate_hits += 1
        else:
            self._reg_candidate_bbox = curr_bbox
            self._reg_candidate_hits = 1

        if self._reg_candidate_hits < REGISTRATION_STABLE_FRAMES:
            self._log_registration_debug(
                total=len(detections),
                in_ellipse=len(in_ellipse),
                class_ok=len(candidates),
                top_conf=float(best.get('confidence', 0.0)),
                red_ratio=red_ratio,
                reason='stability_wait',
            )
            return

        now = time.monotonic()
        with self._lock:
            if (now - self._last_registration_snapshot_ts) < REGISTRATION_SNAPSHOT_COOLDOWN:
                return

        roi = self._extract_roi(frame, best)
        if roi is None:
            return

        # ROI → JPEG
        jpeg = _roi_to_jpeg(roi)
        with self._lock:
            self._pending_snapshot = (jpeg, best)
            # Keep the exact frame/bbox shown to user for confirmation.
            self._pending_confirm_frame = img.copy()
            self._pending_confirm_bbox = dict(best)
            self._last_registration_snapshot_ts = now
        self._log_registration_debug(
            total=len(detections),
            in_ellipse=len(in_ellipse),
            class_ok=len(candidates),
            top_conf=float(best.get('confidence', 0.0)),
            red_ratio=red_ratio,
            reason='snapshot_ready',
        )
        self._reg_candidate_hits = 0
        self._reg_candidate_bbox = None

    def _is_in_registration_ellipse(self, frame, det: dict) -> bool:
        """Return True when detection center is inside registration guide ellipse."""
        try:
            img = _ensure_numpy(frame)
            h, w = img.shape[:2]
            if h <= 0 or w <= 0:
                return False

            cx = float(det.get('cx', (w / 2.0)))
            cy = float(det.get('cy', (h / 2.0)))
            ex = w / 2.0
            ey = h / 2.0

            # Keep visual proportions aligned with HWController ellipse
            # while scaling to camera resolution.
            rx = max(20.0, (w / 320.0) * 140.0)
            ry = max(20.0, (h / 240.0) * 210.0)

            dx = (cx - ex) / rx
            dy = (cy - ey) / ry
            # Slight tolerance to avoid missing near-boundary valid detections.
            return (dx * dx + dy * dy) <= 1.25
        except Exception:
            return False

    def confirm_registration(self, frame, bbox: dict) -> None:
        """사용자가 확인한 frame+bbox로 즉시 템플릿 등록.

        이 메서드가 호출된 후 is_ready() == True 가 된다.
        """
        with self._lock:
            cached_frame = self._pending_confirm_frame
            cached_bbox = dict(self._pending_confirm_bbox) if self._pending_confirm_bbox else None

        # Prefer the exact candidate snapshot that was shown on /register.
        source_frame = cached_frame if cached_frame is not None else frame
        source_bbox = cached_bbox if cached_bbox is not None else bbox

        roi = self._extract_roi(source_frame, source_bbox)
        if roi is None:
            logger.warning('DollDetector: confirm_registration ROI 추출 실패')
            return

        # Use features from server if available (e.g. from registration candidate)
        if source_bbox.get('features'):
            reid_vec = source_bbox['features']
        else:
            reid_vec = self._reid.extract_features(roi).tolist()
            
        hsv_vec = self._compute_hsv_hist(roi)

        with self._lock:
            self._gallery = [reid_vec]
            self._template_hsv = hsv_vec
            self._ready = True
            self._pending_snapshot = None
            self._pending_confirm_frame = None
            self._pending_confirm_bbox = None
            self._safe_id = None
            self._verification_buffer.clear()
            self._frame_count = 0
        logger.info('DollDetector: 주인 인형 등록 완료 (gallery 초기화)')

    def run(self, frame) -> None:
        """TRACKING 상태에서 매 프레임 호출. 주인 인형을 식별해 _latest 갱신."""
        # During registration, we still want to run YOLO to update _latest for the LCD preview
        if not self._ready and not self.show_all_detections:
            # If we are not ready, just run YOLO to update the connection status and count
            raw_detections = self._run_yolo(frame)
            self._frame_count += 1
            
            # Update _latest with the best raw detection for the LCD preview during registration
            # BUT only if it is Red, to avoid showing QR code boxes
            with self._lock:
                if raw_detections:
                    doll_detections = [d for d in raw_detections if self._is_doll_class(d)]
                    if self._reject_dark_objects:
                        doll_detections = [
                            d for d in doll_detections
                            if not self._is_mostly_dark(frame, d, threshold=self._dark_ratio_threshold)
                        ]
                    if doll_detections:
                        best_raw = max(doll_detections, key=lambda d: d.get('confidence', 0))
                        self._latest = Detection(
                            cx=float(best_raw.get('cx', 0)),
                            cy=float(best_raw.get('cy', 0)),
                            area=float(best_raw.get('area', 10000)),
                            confidence=float(best_raw.get('confidence', 0)),
                            bbox=[
                                float(best_raw.get('x1', 0)),
                                float(best_raw.get('y1', 0)),
                                float(best_raw.get('x2', 0)),
                                float(best_raw.get('y2', 0))
                            ],
                            mask=best_raw.get('mask'),
                            features=best_raw.get('features')
                        )
                    else:
                        self._latest = None
                else:
                    self._latest = None
            return

        raw_detections = self._run_yolo(frame)
        if raw_detections:
            logger.info('DollDetector: 수신 %d개 (신뢰도 %f)', 
                        len(raw_detections), raw_detections[0]['confidence'])
        
        # 주인 인형을 찾기 위한 트래커 업데이트는 ready 상태일 때만 수행하거나 
        # 디버그 모드일 때도 기본 박스를 보여주기 위해 수행
        detections = self._tracker.update(raw_detections) if raw_detections else []

        self._frame_count += 1

        best_det: Optional[dict] = None
        best_reid_vec: Optional[List[float]] = None

        with self._lock:
            gallery_snapshot = list(self._gallery)
            hsv_template = self._template_hsv
            safe_id = self._safe_id

        # ReID is expensive. Evaluate only the highest-confidence candidates first
        # to reduce bbox/control lag while preserving owner matching quality.
        detections_sorted = sorted(
            detections,
            key=lambda x: float(x.get('confidence', 0.0)),
            reverse=True
        )
        reid_candidates = detections_sorted[:3]

        for d in reid_candidates:
            if d.get('confidence', 0) < MIN_CONFIDENCE:
                continue

            tid = d['track_id']

            # 빠른 경로: safe_id 일치 시 ReID 생략
            if safe_id is not None and tid == safe_id:
                best_det = d
                # 자동 보정 주기에만 피처 계산 (리소소 절약)
                # 원격 서버에서 피처를 이미 준 경우 그것을 사용
                if self._frame_count % CALIBRATION_INTERVAL == 0:
                    if d.get('features'):
                        best_reid_vec = d['features']
                    else:
                        roi = self._extract_roi(frame, d)
                        if roi is not None:
                            best_reid_vec = self._reid.extract_features(roi).tolist()
                break

            # 원격 서버에서 준 피처가 있으면 활용, 없으면 추출
            if d.get('features'):
                reid_vec = d['features']
            else:
                roi = self._extract_roi(frame, d)
                if roi is None:
                    continue
                reid_vec = self._reid.extract_features(roi).tolist()
                
            # HSV 는 로컬에서 보조적으로 계산 (색상 필터용)
            roi = self._extract_roi(frame, d)
            if roi is None:
                continue
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
                    bbox=[
                        float(best_det.get('x1', 0)),
                        float(best_det.get('y1', 0)),
                        float(best_det.get('x2', 0)),
                        float(best_det.get('y2', 0))
                    ],
                    mask=best_det.get('mask'),
                    features=best_det.get('features')
                )
            elif self.show_all_detections and raw_detections:
                # 디버그 모드: 주인은 아니지만 감지된 최선의 결과를 노출
                # YOLO_CONF 를 존중하기 위해 필터를 대폭 낮춤 (서버 설정값에 의존)
                best_raw = max(raw_detections, key=lambda d: d.get('confidence', 0))
                if best_raw.get('confidence', 0) >= 0.20:
                    self._latest = Detection(
                        cx=float(best_raw.get('cx', 0)),
                        cy=float(best_raw.get('cy', 0)),
                        area=float(best_raw.get('area', 10000)),
                        confidence=float(best_raw.get('confidence', 0)),
                        class_name='yolo_debug',
                        bbox=[
                            float(best_raw.get('x1', 0)),
                            float(best_raw.get('y1', 0)),
                            float(best_raw.get('x2', 0)),
                            float(best_raw.get('y2', 0))
                        ],
                        mask=best_raw.get('mask'),
                        features=best_raw.get('features')
                    )
                else:
                    self._latest = None
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
            self._pending_confirm_frame = None
            self._pending_confirm_bbox = None
            # Retake should allow immediate re-detection without cooldown carryover.
            self._last_registration_snapshot_ts = 0.0
            self._reg_candidate_bbox = None
            self._reg_candidate_hits = 0

    def reset(self) -> None:
        """세션 종료 시 호출 — 모든 추종 데이터 소거 (메모리 전용)."""
        with self._lock:
            self._gallery.clear()
            self._template_hsv = None
            self._ready = False
            self._latest = None
            self._pending_snapshot = None
            self._pending_confirm_frame = None
            self._pending_confirm_bbox = None
            self._safe_id = None
            self._verification_buffer.clear()
            self._frame_count = 0
        self._tracker.reset()
        self._close_socket()
        logger.info('DollDetector: reset 완료')

    def is_mostly_red(self, frame, det: dict, threshold: float = 0.20) -> bool:
        """ROI 추출 후 HSV 공간에서 '빨간색' 비율을 체크한다."""
        return self._compute_red_ratio(frame, det) >= threshold

    def _compute_red_ratio(self, frame, det: dict) -> float:
        """ROI의 빨간색 픽셀 비율을 반환한다."""
        try:
            import cv2
            import numpy as np
            roi = self._extract_roi(frame, det)
            if roi is None or roi.size == 0:
                return 0.0
            
            # BGR → HSV 변환
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            
            # 'Natural Red' Hue 범위 (H: 0-10, 170-180)
            # Saturation(S) 70 이상: 무채색(검정/회색) 제외
            # Value(V) 50 이상: 너무 어두운 영역 제외
            lower_red1 = np.array([0, 70, 50])
            upper_red1 = np.array([10, 255, 255])
            lower_red2 = np.array([165, 70, 50])
            upper_red2 = np.array([180, 255, 255])
            
            mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
            mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
            red_mask = cv2.bitwise_or(mask1, mask2)
            
            # 빨간색 픽셀 비율 계산
            red_ratio = np.count_nonzero(red_mask) / (roi.shape[0] * roi.shape[1])
            return float(red_ratio)
        except Exception as e:
            logger.debug('DollDetector: _compute_red_ratio 실패: %s', e)
            return 0.0

    def _log_registration_debug(
        self,
        total: int,
        in_ellipse: int,
        class_ok: int,
        top_conf: float,
        red_ratio: float,
        reason: str,
    ) -> None:
        """Throttled registration diagnostics."""
        now = time.monotonic()
        if (now - self._last_reg_debug_ts) < 1.0:
            return
        self._last_reg_debug_ts = now
        logger.info(
            'REGDBG total=%d in_ellipse=%d class_ok=%d conf=%.3f red=%.3f reason=%s',
            total, in_ellipse, class_ok, top_conf, red_ratio, reason
        )

    def _is_mostly_dark(self, frame, det: dict, threshold: float = 0.50) -> bool:
        """Return True when ROI is mostly dark/black."""
        try:
            import cv2
            import numpy as np
            roi = self._extract_roi(frame, det)
            if roi is None or roi.size == 0:
                return False
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            dark_mask = cv2.inRange(hsv, np.array([0, 0, 0]), np.array([180, 255, 60]))
            dark_ratio = np.count_nonzero(dark_mask) / (roi.shape[0] * roi.shape[1])
            return float(dark_ratio) >= threshold
        except Exception:
            return False

    def _is_doll_class(self, det: dict) -> bool:
        """best1_ncnn_model class 0(doll)만 통과."""
        try:
            cls = int(det.get('class_id', 0))
            return cls == 0
        except Exception:
            return False

    def _bbox_iou(
        self,
        a: Tuple[float, float, float, float],
        b: Tuple[float, float, float, float],
    ) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter_w = max(0.0, inter_x2 - inter_x1)
        inter_h = max(0.0, inter_y2 - inter_y1)
        inter = inter_w * inter_h
        if inter <= 0.0:
            return 0.0
        area_a = max(0.0, (ax2 - ax1)) * max(0.0, (ay2 - ay1))
        area_b = max(0.0, (bx2 - bx1)) * max(0.0, (by2 - by1))
        denom = area_a + area_b - inter
        if denom <= 1e-6:
            return 0.0
        return inter / denom
            
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

    # ── 소켓 관리 ────────────────────────────────────────────────────────────

    def _get_socket(self) -> Optional[socket.socket]:
        """기존 소켓을 반환하거나 새로 연결한다."""
        with self._socket_lock:
            if self._socket is not None:
                return self._socket

            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.2)
                s.connect((self._host, self._port))
                self._socket = s
                logger.info('DollDetector: YOLO 서버 연결 성공 (%s:%d)', self._host, self._port)
                return self._socket
            except Exception as e:
                logger.error('DollDetector: YOLO 서버 연결 실패 (%s:%d): %s', self._host, self._port, e)
                return None

    def _close_socket(self) -> None:
        """소켓을 닫고 초기화한다."""
        with self._socket_lock:
            if self._socket:
                try:
                    self._socket.close()
                except Exception:
                    pass
                self._socket = None

    # ── YOLO 클라이언트 ───────────────────────────────────────────────────────

    def _run_yolo(self, frame) -> List[dict]:
        """YOLO 추론을 수행한다. (로컬 NCNN 우선, 실패 시 원격 서버)"""
        if self._local_model:
            return self._run_local_yolo(frame)
        if self._force_local_ncnn:
            self._connected = False
            self._last_count = 0
            return []
        return self._run_remote_yolo(frame)

    def _run_local_yolo(self, frame) -> List[dict]:
        """Pi 5에서 직접 YOLOv8 NCNN 추론 수행."""
        try:
            img = _ensure_numpy(frame)
            # imgsz=320, half=True 로 성능 최적화 (Pi 5 CPU 환경)
            results = self._local_model.predict(
                img, 
                imgsz=self._ncnn_imgsz,
                conf=self._ncnn_conf,
                verbose=False,
                device='cpu'
            )
            
            detections = []
            if not results:
                return []
                
            for r in results:
                for box in r.boxes:
                    x1, y1, x2, y2 = map(float, box.xyxy[0])
                    conf = float(box.conf[0])
                    cls = int(box.cls[0])
                    
                    # YOLO_SERVER의 JSON 포맷과 동일하게 변환
                    det = {
                        'cx': float((x1 + x2) / 2.0),
                        'cy': float((y1 + y2) / 2.0),
                        'area': float((x2 - x1) * (y2 - y1)),
                        'confidence': conf,
                        'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                        'class_id': cls
                    }
                    detections.append(det)
            
            self._connected = True # 로컬이므로 항상 '연결'된 것으로 간주
            self._last_count = len(detections)
            return detections
        except Exception as e:
            logger.error('DollDetector: 로컬 추론 실패: %s', e)
            self._last_count = 0
            return []

    def _run_remote_yolo(self, frame) -> List[dict]:
        """기존 TCP 서버 방식 추론 (백업용)."""
        # ── 성능 최적화: 네트워크 전송 전 리사이즈 (640px 기준) ──
        # 카메라 해상도가 높을 경우 Wi-Fi 지연의 원인이 됨.
        h, w = frame.shape[:2]
        if w > 640:
            scale = 640.0 / w
            new_size = (640, int(h * scale))
            proc_frame = cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)
        else:
            proc_frame = frame

        jpeg = _to_jpeg(proc_frame)
        sock = self._get_socket()
        if sock is None:
            self._connected = False
            self._last_count = 0
            return []

        try:
            # 헤더(길이) + 데이터 전송
            header = struct.pack('!I', len(jpeg))
            sock.sendall(header + jpeg)

            # 응답 길이 수신
            resp_len_b = _recv_exact(sock, 4)
            if resp_len_b is None:
                raise ConnectionError('YOLO 서버 응답 헤더 수신 실패')
            
            resp_len = struct.unpack('!I', resp_len_b)[0]
            
            # 응답 본문 수신
            resp_data = _recv_exact(sock, resp_len)
            if resp_data is None:
                raise ConnectionError('YOLO 서버 응답 본문 수신 실패')

            import json
            result = json.loads(resp_data.decode())
            self._connected = True
            
            if isinstance(result, dict):
                detections = [result] if result else []
            elif isinstance(result, list):
                detections = result
            else:
                detections = []
            
            self._last_count = len(detections)
            return detections
        except Exception as e:
            self._connected = False
            self._last_count = 0
            logger.debug('DollDetector: YOLO 쿼리 실패 (소켓 리셋): %s', e)
            self._close_socket()
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
        import numpy as np
        arr_a = np.array(a)
        arr_b = np.array(b)
        dot = np.dot(arr_a, arr_b)
        norm_a = np.linalg.norm(arr_a)
        norm_b = np.linalg.norm(arr_b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))
    except Exception:
        return 0.0


def _histogram_correlation(a: List[float], b: List[float]) -> float:
    """Pearson 상관계수 [-1,1] → [0,1] 매핑 (NumPy 최적화)."""
    try:
        import numpy as np
        arr_a = np.array(a)
        arr_b = np.array(b)
        if arr_a.shape != arr_b.shape:
            return 0.0
        
        # NumPy pearson correlation coefficient
        corr = np.corrcoef(arr_a, arr_b)[0, 1]
        if np.isnan(corr):
            return 0.5
        return float((corr + 1.0) / 2.0)
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
        # Quality 60으로 압축하여 네트워크 전송 속도 향상
        _, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
        return bytes(buf)
    except Exception:
        return bytes(frame)


def _roi_to_jpeg(roi) -> bytes:
    """ROI numpy 배열(BGR) → JPEG bytes."""
    try:
        import cv2
        # OpenCV imencode expects BGR input. Converting to RGB here
        # causes blue/red channel swap on web snapshots.
        _, buf = cv2.imencode('.jpg', roi, [cv2.IMWRITE_JPEG_QUALITY, 85])
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

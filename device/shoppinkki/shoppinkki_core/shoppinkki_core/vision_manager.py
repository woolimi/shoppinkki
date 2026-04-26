"""카메라 + AI(DollDetector) + MJPEG 스트림 매니저.

3개 daemon thread (camera/AI/stream)와 frame buffer 공유 상태를 관리.
모든 shared state는 self._lock으로 보호 (단, _ai_event는 자체 thread-safe).

설계 원칙:
- lock 안에서 I/O 금지 — only frame ref / bytes copy. cv2.imencode, socket.send,
  HW calls는 모두 lock 밖에서 수행.
- _ai_event.set/clear은 lock 밖에서 호출.
- Camera loop write 시 단일 lock 안에 모든 shared state snapshot.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import socket
import struct
import threading
import time
from typing import TYPE_CHECKING, Optional

import cv2
import numpy as np

import rclpy
from std_msgs.msg import String

from .config import CAMERA_ACTIVE_MODES, RobotMode

if TYPE_CHECKING:
    import rclpy.node
    from .hw_controller import HWController

try:
    from shoppinkki_perception.doll_detector import DollDetector
    _PERCEPTION_AVAILABLE = True
except ImportError:
    DollDetector = None
    _PERCEPTION_AVAILABLE = False

try:
    from pinkylib import Camera as PinkyCamera
    _PINKYLIB_AVAILABLE = True
except ImportError:
    PinkyCamera = None
    _PINKYLIB_AVAILABLE = False

logger = logging.getLogger(__name__)


class VisionManager:
    """Camera/AI/stream 통합 매니저.

    3 daemon thread + DollDetector 소유. Lifecycle: start()/stop().
    단일 self._lock으로 frame buffer + 등록 flag 보호.
    """

    _CAM_STATES = CAMERA_ACTIVE_MODES
    _LCD_FEED_STATES = frozenset({
        RobotMode.TRACKING, RobotMode.TRACKING_CHECKOUT, RobotMode.SEARCHING,
    })
    _REG_FRAME_INTERVAL = 0.083  # ~12 FPS — blur + SPI 부담을 감안한 등록 모드 업데이트 주기
    _LCD_FRAME_INTERVAL = 0.040  # ~25 FPS — 평상시 LCD 카메라 피드 업데이트 주기

    def __init__(
        self,
        node: 'rclpy.node.Node',
        hw: 'HWController',
        sm,
        robot_id: str,
    ) -> None:
        self._node = node
        self._hw = hw
        self._sm = sm
        self._robot_id = robot_id
        self._started = False

        # ── Lock + shared state ──
        self._lock = threading.Lock()
        self._cam_frame: Optional[np.ndarray] = None
        self._ai_frame: Optional[np.ndarray] = None
        self._stream_frame: Optional[bytes] = None
        # AI thread가 읽는 동안 카메라 thread가 덮어쓰지 않도록 더블 버퍼.
        # Pi 5에서 30Hz × ~900KB frame.copy() = ~27MB/s 할당 churn을 제거한다.
        self._ai_frame_buffers: list[Optional[np.ndarray]] = [None, None]
        self._ai_frame_buf_idx: int = 0

        # 등록 상태 (lock 보호)
        self._registration_active: bool = False
        self._registration_waiting_confirm: bool = False
        self._tracking_grace_until: float = 0.0

        # follow_disabled (sim 모드, lock 보호)
        self.follow_disabled: bool = False

        # Snapshot rate-limit (camera/AI thread 단독 접근)
        self._last_snapshot_time: float = 0.0
        self._snapshot_rate_limit: float = 0.5
        # LCD throttle 시각 (camera thread 단독 접근)
        self._last_reg_frame_t: float = 0.0
        self._last_lcd_update_t: float = 0.0

        # AI signaling (Event 자체 thread-safe)
        self._ai_event = threading.Event()

        # Threads (start()에서 생성)
        self._cam_thread: Optional[threading.Thread] = None
        self._ai_thread: Optional[threading.Thread] = None
        self._stream_thread: Optional[threading.Thread] = None

        # snapshot publisher (등록 후보 이미지 발행)
        self._snapshot_pub = node.create_publisher(
            String, f'/robot_{robot_id}/snapshot', 10)

        # DollDetector 초기화
        if _PERCEPTION_AVAILABLE:
            yolo_host = os.environ.get('YOLO_HOST', '127.0.0.1')
            yolo_port = int(os.environ.get('YOLO_PORT', '5005'))
            doll_model_path = os.environ.get(
                'DOLL_MODEL_PATH',
                '/home/pinky/ros_ws/server/ai_service/yolo/models/best1.pt',
            )
            self.doll_detector = DollDetector(
                yolo_host=yolo_host, yolo_port=yolo_port,
                model_path=doll_model_path,
            )
            self._node.get_logger().info(
                f'DollDetector 초기화 (YOLO {yolo_host}:{yolo_port}, '
                f'model={doll_model_path})'
            )
        else:
            self.doll_detector = None
            self._node.get_logger().warning(
                'shoppinkki_perception 미설치 — DollDetector 비활성화'
            )

    # ──────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────

    def start(self) -> None:
        """3 daemon thread 시작 (idempotent)."""
        if self._started:
            return
        self._started = True
        self._ai_thread = threading.Thread(
            target=self._ai_loop, daemon=True, name='vision-ai')
        self._ai_thread.start()
        self._stream_thread = threading.Thread(
            target=self._stream_loop, daemon=True, name='vision-stream')
        self._stream_thread.start()
        self._cam_thread = threading.Thread(
            target=self._camera_loop, daemon=True, name='vision-cam')
        self._cam_thread.start()

    def stop(self) -> None:
        """thread 종료 신호 (rclpy shutdown 시 daemon thread는 자동 종료)."""
        self._started = False
        # AI loop이 wait 중일 때 깨우기
        self._ai_event.set()

    # ──────────────────────────────────────────
    # 외부 API (main_node가 호출)
    # ──────────────────────────────────────────

    def is_registration_active(self) -> bool:
        """Registration mode 여부 (BTRunner / cmd_handler용 callable bind 대상)."""
        with self._lock:
            return self._registration_active

    def set_registration_active(self, active: bool) -> None:
        with self._lock:
            self._registration_active = active

    def reset_registration_after_session(self) -> None:
        """세션 종료 시 등록 상태 리셋 + DollDetector reset."""
        with self._lock:
            self._registration_active = False
        if self.doll_detector is not None:
            self.doll_detector.reset()

    def reset_detector(self) -> None:
        """세션 시작 등에서 DollDetector만 리셋."""
        if self.doll_detector is not None:
            self.doll_detector.reset()

    def set_follow_disabled(self, disabled: bool) -> None:
        with self._lock:
            self.follow_disabled = disabled

    def get_follow_disabled(self) -> bool:
        with self._lock:
            return self.follow_disabled

    def enter_registration(self) -> None:
        """고객이 /register 페이지에 접속: LCD 카메라 피드 전환."""
        with self._lock:
            self._registration_active = True
            self._registration_waiting_confirm = False
        self._node.get_logger().info('enter_registration: 카메라 피드 활성화')

    def retake_registration(self) -> None:
        """사용자가 [다시 찍기]를 눌렀을 때 새 후보 감지 재개."""
        with self._lock:
            self._registration_waiting_confirm = False
        if self.doll_detector is not None:
            self.doll_detector.clear_pending_snapshot()

    def is_tracking_grace_active(self) -> bool:
        with self._lock:
            return time.monotonic() < self._tracking_grace_until

    def confirm_registration(self, bbox: dict) -> bool:
        """사용자가 앱에서 [확인]을 누르면 호출됨 (IDLE 상태).

        최신 카메라 프레임 + bbox로 DollDetector 템플릿 등록.
        성공 시 True, FSM 전환은 main_node가 책임.
        """
        with self._lock:
            frame = self._cam_frame
        if frame is None:
            self._node.get_logger().warning('registration_confirm: 카메라 프레임 없음')
            return False
        if self.doll_detector is None:
            self._node.get_logger().warning('registration_confirm: DollDetector 없음')
            return False

        self.doll_detector.confirm_registration(frame, bbox)
        self._node.get_logger().info('registration_confirm: 등록 완료 → TRACKING 진입')
        with self._lock:
            self._registration_active = False
            self._registration_waiting_confirm = False
            # Prevent immediate TRACKING→SEARCHING flapping right after confirmation.
            self._tracking_grace_until = time.monotonic() + 5.0
        return True

    # ──────────────────────────────────────────
    # 카메라 루프 (별도 스레드)
    # ──────────────────────────────────────────

    def _camera_loop(self) -> None:
        """카메라 프레임을 읽어 상태에 따라 처리하는 백그라운드 스레드.

        - IDLE    : LCD 피드 표시 + 인형 감지 시 snapshot 발행
        - TRACKING / TRACKING_CHECKOUT : doll_detector.run() 호출
        """
        try:
            import cv2
        except ImportError:
            self._node.get_logger().warning('cv2 없음 — 카메라 루프 비활성화')
            return

        def _open_camera():
            if _PINKYLIB_AVAILABLE:
                try:
                    cam = PinkyCamera()
                    cam.start()
                    self._node.get_logger().info('pinkylib.Camera started')
                    return cam
                except Exception as e:
                    self._node.get_logger().warning(
                        f'pinkylib.Camera 시작 실패: {e} — VideoCapture로 전환'
                    )

            self._node.get_logger().warning(
                'pinkylib 없음/실패 — camera loop를 VideoCapture로 전환 시도'
            )
            cam = cv2.VideoCapture(int(os.environ.get('CAMERA_INDEX', '0')))
            if hasattr(cam, 'isOpened') and not cam.isOpened():
                self._node.get_logger().warning('VideoCapture 열기 실패')
                if hasattr(cam, 'release'):
                    cam.release()
                return None
            self._node.get_logger().info('cv2.VideoCapture started')
            return cam

        def _close_camera(cam) -> None:
            try:
                if _PINKYLIB_AVAILABLE and isinstance(cam, PinkyCamera):
                    cam.close()
                elif hasattr(cam, 'release'):
                    cam.release()
            except Exception:
                pass

        cap = None
        open_retry_sec = 1.0
        read_failures = 0
        camera_paused_for_sim = False
        self._node.get_logger().info('카메라 루프 시작')

        while rclpy.ok():
            # 시뮬레이션 모드(follow_disabled)에서는 Pi 카메라 점유를 내려
            # 웹(노트북/휴대폰) QR 카메라와의 충돌(NoReadableError)을 피한다.
            with self._lock:
                follow_disabled = self.follow_disabled
            if follow_disabled:
                if cap is not None:
                    _close_camera(cap)
                    cap = None
                if not camera_paused_for_sim:
                    self._node.get_logger().info('simulation_mode: Pi camera paused')
                    camera_paused_for_sim = True
                time.sleep(0.2)
                continue

            if camera_paused_for_sim:
                self._node.get_logger().info('simulation_mode off: Pi camera resume')
                camera_paused_for_sim = False

            if cap is None:
                cap = _open_camera()
                if cap is None:
                    time.sleep(open_retry_sec)
                    open_retry_sec = min(open_retry_sec * 2.0, 5.0)
                    continue
                # 성공하면 재시도 간격/실패 카운터 리셋
                open_retry_sec = 1.0
                read_failures = 0

            state = self._sm.state

            # 카메라가 불필요한 상태 → 프레임 읽기 건너뜀
            if state not in self._CAM_STATES:
                time.sleep(0.2)
                continue

            try:
                if _PINKYLIB_AVAILABLE and isinstance(cap, PinkyCamera):
                    frame = cap.get_frame()
                    if frame is None:
                        raise RuntimeError('pinky camera returned empty frame')
                else:
                    ret, frame = cap.read()
                    if not ret:
                        raise RuntimeError('cv2 camera read failed')
                read_failures = 0
            except Exception as e:
                read_failures += 1
                if read_failures in (1, 10):
                    self._node.get_logger().warning(
                        f'카메라 프레임 읽기 실패({read_failures}): {e}'
                    )
                # 연속 실패 시 카메라만 재오픈하고 노드는 계속 유지
                if read_failures >= 10:
                    self._node.get_logger().warning('카메라 재오픈 시도')
                    _close_camera(cap)
                    cap = None
                    read_failures = 0
                time.sleep(0.05)
                continue

            # ── Shared frame state 갱신 (lock) ──
            # 더블 버퍼 회전: AI thread가 직전 버퍼를 들고 있어도 다른 슬롯에 쓴다.
            ai_frame_copy: Optional[np.ndarray] = None
            if frame is not None:
                idx = 1 - self._ai_frame_buf_idx
                buf = self._ai_frame_buffers[idx]
                if buf is None or buf.shape != frame.shape or buf.dtype != frame.dtype:
                    buf = np.empty_like(frame)
                    self._ai_frame_buffers[idx] = buf
                np.copyto(buf, frame)
                self._ai_frame_buf_idx = idx
                ai_frame_copy = buf
            with self._lock:
                self._cam_frame = frame
                self._ai_frame = ai_frame_copy
                is_registration = self._registration_active

            # AI signal은 lock 밖에서
            self._ai_event.set()

            # ── LCD 업데이트 (lock 밖, HW I/O) ──
            self._update_lcd_feed(frame, state, is_registration)

            # ── 스트림용 JPEG 인코딩 (lock 밖, CPU heavy) ──
            _, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
            jpeg_bytes = jpeg.tobytes()
            with self._lock:
                self._stream_frame = jpeg_bytes

        if cap is not None:
            _close_camera(cap)

    def _update_lcd_feed(self, frame, state: str, is_registration: bool) -> None:
        """카메라 프레임을 상태에 맞춰 LCD에 표시한다.

        등록 모드는 12FPS, 일반 모드는 25FPS로 throttle. 일반 모드에서는 추종/탐색 또는
        debug 표시 상태에서만 카메라 피드를 LCD에 덮어쓴다 — IDLE/WAITING/GUIDING에서는
        상태 텍스트/QR이 LCD 전체를 차지하므로 건드리지 않는다.
        """
        connected = self.doll_detector.is_connected() if self.doll_detector else False
        det_count = self.doll_detector.get_latest_count() if self.doll_detector else 0

        if is_registration:
            now = time.monotonic()
            if (now - self._last_reg_frame_t) < self._REG_FRAME_INTERVAL:
                return
            self._last_reg_frame_t = now
            self._hw.display_frame(
                frame, connected=connected, det_count=det_count,
                is_registration=True, mirror=True)
            return

        now = time.monotonic()
        if (now - self._last_lcd_update_t) < self._LCD_FRAME_INTERVAL:
            return

        show_debug = self.doll_detector is not None and getattr(
            self.doll_detector, 'show_all_detections', False)
        should_display = state in self._LCD_FEED_STATES or show_debug
        if not should_display:
            return  # IDLE/WAITING/GUIDING 등은 상태 텍스트/QR이 점유

        self._last_lcd_update_t = now
        det = self.doll_detector.get_latest() if self.doll_detector else None
        if det:
            self._hw.draw_detection(frame, det)
        self._hw.display_frame(
            frame, connected=connected, det_count=det_count, mirror=True)

    def _ai_loop(self) -> None:
        """AI 연산을 수행하는 백그라운드 스레드.

        카메라 루프에서 신호를 받으면 최신 프레임에 대해 YOLO 및 ReID를 수행한다.
        네트워킹/연산 지연이 LCD 피드에 영향을 주지 않도록 분리됨.
        """
        while rclpy.ok():
            # 신호 대기 (Timeout을 두어 rclpy.ok() 체크 기회 확보)
            if not self._ai_event.wait(timeout=1.0):
                continue

            self._ai_event.clear()
            with self._lock:
                frame = self._ai_frame
                is_registration = self._registration_active
                waiting_confirm = self._registration_waiting_confirm

            if frame is None:
                continue

            state = self._sm.state

            if self.doll_detector is not None:
                show_debug = getattr(self.doll_detector, 'show_all_detections', False)

                if state == 'IDLE' and is_registration:
                    # 인형 등록 중 (Snapshot 쿼리)
                    if not waiting_confirm:
                        self.doll_detector.register(frame)
                        snapshot = self.doll_detector.get_pending_snapshot()
                        now = time.time()
                        if snapshot and (now - self._last_snapshot_time) >= self._snapshot_rate_limit:
                            self._last_snapshot_time = now
                            jpeg_bytes, bbox = snapshot
                            b64 = base64.b64encode(jpeg_bytes).decode('ascii')
                            msg = String()
                            msg.data = json.dumps({
                                'robot_id': self._robot_id,
                                'image': b64,
                                'bbox': bbox,
                            })
                            self._snapshot_pub.publish(msg)
                            with self._lock:
                                self._registration_waiting_confirm = True
                            # Keep pending confirm frame/bbox in detector for exact confirm.
                            self.doll_detector.clear_pending_snapshot()
                elif (state in ('TRACKING', 'TRACKING_CHECKOUT', 'SEARCHING', 'IDLE') or show_debug) and not is_registration:
                    # 추종 중이거나 디버그 모드일 때 실시간 감지 실행 (등록 중에는 스킵)
                    self.doll_detector.run(frame)

            elif state in ('TRACKING', 'TRACKING_CHECKOUT', 'SEARCHING'):
                # 추종/탐색 중 (YOLO + ReID + Tracker)
                if self.doll_detector is not None:
                    self.doll_detector.run(frame)

    def _stream_loop(self) -> None:
        """가벼운 TCP/MJPEG 스트리머."""
        # 다중 로봇 시뮬에서 포트 충돌 방지 — ROBOT_ID로 오프셋.
        # 예: 54 → 5061, 18 → 5025
        try:
            port = 5007 + int(self._robot_id)
        except (TypeError, ValueError):
            port = 5007
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('0.0.0.0', port))
            sock.listen(1)
            self._node.get_logger().info(f'Monitor Streamer 시작됨 (Port {port})')
        except Exception as e:
            self._node.get_logger().error(f'Streamer Bind 실패: {e}')
            return

        while rclpy.ok():
            try:
                conn, addr = sock.accept()
                self._node.get_logger().info(f'Monitor Dashboard 연결됨: {addr}')
                while rclpy.ok():
                    with self._lock:
                        frame = self._stream_frame
                    if frame is None:
                        time.sleep(0.1)
                        continue

                    # MJPEG 헤더 없이 단순 바이트 전송 (프레임 구분은 size로)
                    size = len(frame)
                    conn.sendall(struct.pack("!I", size) + frame)
                    time.sleep(0.05)  # ~20 FPS limit
            except Exception:
                time.sleep(1.0)

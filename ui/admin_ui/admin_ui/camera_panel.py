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

"""CameraDebugPanel — MJPEG 스트림 + 바운딩박스 오버레이.

MJPEG 수신:
    QThread에서 GET http://{host}:{port}/camera/{robot_id} 스트림 수신
    --frame\\r\\n...JPEG bytes\\r\\n 파싱
    → frame_received(bytes) pyqtSignal

바운딩박스 오버레이:
    status push의 bbox 필드: {"cx": N, "cy": N, "area": N, "confidence": 0.92}
    → QPainter로 초록 사각형 + 신뢰도% 텍스트

UI:
    - 로봇 선택 QComboBox
    - QLabel (영상 표시)
    - [패널 닫기] QPushButton
    - 상태 레이블 (해상도, bbox 좌표)
"""

import math
import time
import urllib.request

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_FRAME_BOUNDARY = b'--frame'
_JPEG_START = b'\xff\xd8'
_JPEG_END = b'\xff\xd9'


class MjpegThread(QThread):
    """MJPEG 스트림 수신 스레드."""

    frame_received = pyqtSignal(bytes)
    error_occurred = pyqtSignal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._running = False

    def run(self):
        self._running = True
        try:
            req = urllib.request.urlopen(self._url, timeout=10)
            buf = b''
            while self._running:
                chunk = req.read(4096)
                if not chunk:
                    break
                buf += chunk
                # JPEG 프레임 추출
                while True:
                    start = buf.find(_JPEG_START)
                    end = buf.find(_JPEG_END, start + 2)
                    if start == -1 or end == -1:
                        break
                    jpeg_bytes = buf[start:end + 2]
                    buf = buf[end + 2:]
                    self.frame_received.emit(jpeg_bytes)
        except Exception as e:
            if self._running:
                self.error_occurred.emit(str(e))

    def stop(self):
        self._running = False
        self.wait(3000)


class CameraDebugPanel(QWidget):
    """카메라 디버그 패널 위젯."""

    def __init__(self, rest_host: str, rest_port: int, robot_ids: list, parent=None):
        super().__init__(parent)
        self._rest_host = rest_host
        self._rest_port = rest_port
        self._robot_ids = list(robot_ids)
        self._current_robot: str | None = None
        self._mjpeg_thread: MjpegThread | None = None
        self._bbox: dict | None = None
        self._current_pixmap: QPixmap | None = None
        self._last_render_ts = 0.0
        self._max_fps = 12.0  # UI 렌더링 상한 (너무 높으면 렉/CPU 급증)

        self.setWindowTitle('카메라 디버그 패널')
        self.setMinimumSize(680, 440)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 상단 컨트롤
        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel('로봇 선택:'))
        self._combo_robot = QComboBox()
        for rid in self._robot_ids:
            self._combo_robot.addItem(f'Robot #{rid}', rid)
        self._combo_robot.currentIndexChanged.connect(self._on_robot_changed)
        ctrl_layout.addWidget(self._combo_robot)
        ctrl_layout.addStretch()
        self._lbl_status = QLabel('연결 안됨')
        ctrl_layout.addWidget(self._lbl_status)
        btn_close = QPushButton('패널 닫기')
        btn_close.clicked.connect(self.hide_panel)
        ctrl_layout.addWidget(btn_close)
        layout.addLayout(ctrl_layout)

        # 영상 표시
        self._lbl_frame = QLabel('카메라 스트림 없음')
        self._lbl_frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_frame.setMinimumSize(640, 360)
        self._lbl_frame.setStyleSheet('background-color: #222222; color: #ffffff;')
        self._lbl_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._lbl_frame)

        # bbox 정보
        self._lbl_bbox_info = QLabel('bbox: -')
        layout.addWidget(self._lbl_bbox_info)

    def _on_robot_changed(self, index: int):
        robot_id = self._combo_robot.itemData(index)
        self.set_robot(robot_id)

    def set_robot(self, robot_id: str):
        """로봇 변경 시 스트림 재시작."""
        if self._current_robot == robot_id:
            return
        self._stop_stream()
        self._current_robot = robot_id
        self._bbox = None
        self._lbl_bbox_info.setText('bbox: -')
        if robot_id and self.isVisible():
            self._start_stream(robot_id)

    def _start_stream(self, robot_id: str):
        url = f'http://{self._rest_host}:{self._rest_port}/camera/{robot_id}'
        self._lbl_status.setText(f'연결 중... {url}')
        self._mjpeg_thread = MjpegThread(url, self)
        self._mjpeg_thread.frame_received.connect(self._on_frame_received)
        self._mjpeg_thread.error_occurred.connect(self._on_stream_error)
        self._mjpeg_thread.start()

    def _stop_stream(self):
        if self._mjpeg_thread is not None:
            self._mjpeg_thread.stop()
            self._mjpeg_thread = None

    def _on_frame_received(self, jpeg_bytes: bytes):
        img = QImage.fromData(jpeg_bytes, 'JPEG')
        if img.isNull():
            return
        self._current_pixmap = QPixmap.fromImage(img)
        now = time.monotonic()
        if (now - self._last_render_ts) >= (1.0 / max(self._max_fps, 1.0)):
            self._last_render_ts = now
            self._render_frame()
        w, h = img.width(), img.height()
        self._lbl_status.setText(f'스트리밍 중 {w}x{h}')

    def _render_frame(self):
        if self._current_pixmap is None:
            return
        pix = self._current_pixmap.copy()
        if self._bbox:
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            cx = self._bbox.get('cx', 0)
            area = self._bbox.get('area', 0)
            conf = self._bbox.get('confidence', 0.0)
            # area로 사각형 크기 추정
            side = int(math.sqrt(area)) if area > 0 else 20
            x1 = cx - side // 2
            y1 = self._bbox.get('cy', 0) - side // 2
            painter.setPen(QPen(QColor('#27ae60'), 2))
            painter.drawRect(x1, y1, side, side)
            painter.setPen(QColor('#27ae60'))
            painter.drawText(x1, y1 - 4, f'{conf * 100:.0f}%')
            painter.end()
        scaled = pix.scaled(
            self._lbl_frame.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            # Smooth는 고비용이라 실시간 프리뷰에서는 Fast가 체감이 훨씬 좋음
            Qt.TransformationMode.FastTransformation,
        )
        self._lbl_frame.setPixmap(scaled)

    def _on_stream_error(self, msg: str):
        self._lbl_status.setText(f'오류: {msg}')
        self._lbl_frame.setText(f'스트림 오류\n{msg}')

    def update_bbox(self, robot_id: str, bbox: dict):
        """status 메시지의 bbox 갱신."""
        if robot_id != self._current_robot:
            return
        self._bbox = bbox
        # 패널이 숨겨져 있으면 QPainter/pixmap 렌더 자체를 건너뛴다.
        # macOS PyQt5에서 hidden widget에 그리는 게 간헐적 bus error 원인.
        if not self.isVisible():
            return
        cx = bbox.get('cx', '-')
        area = bbox.get('area', '-')
        conf = bbox.get('confidence', 0.0)
        self._lbl_bbox_info.setText(f'bbox: cx={cx}, area={area}, conf={conf:.2f}')
        self._render_frame()

    def show_panel(self):
        self.show()
        self.raise_()
        if self._current_robot is None and self._robot_ids:
            self.set_robot(self._robot_ids[0])
        elif self._current_robot and self._mjpeg_thread is None:
            self._start_stream(self._current_robot)

    def hide_panel(self):
        self._stop_stream()
        self.hide()

    def closeEvent(self, event):
        self._stop_stream()
        super().closeEvent(event)

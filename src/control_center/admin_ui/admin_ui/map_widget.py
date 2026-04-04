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

"""MapWidget — shop_map.png 위에 로봇 위치 실시간 표시.

좌표 변환:
    px = int((x - origin_x) / resolution)
    py = int(img_height - (y - origin_y) / resolution)  # Y축 반전

로봇 아이콘:
    온라인: 색상 원형 (robot_id별 색상)
    is_locked_return=True: 빨간 점멸 테두리
    HALTED: 흰색 점멸 테두리
    OFFLINE: x 표시, 마지막 위치 유지

맵 클릭:
    클릭 좌표를 월드 좌표로 변환
    → map_clicked(x, y) pyqtSignal 발행
    → 파란 십자 마커 표시

맵 이미지:
    assets/shop_map.png 로드 시도.
    없으면 회색 배경 + "맵 이미지 없음" 텍스트 표시.
    shop.yaml: resolution=0.01, origin=(-0.293, -1.660)
"""

import os

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QLabel

MAP_RESOLUTION = 0.01    # m/px  (shop.yaml resolution=0.010)
MAP_ORIGIN_X = -0.293    # m     (shop.yaml origin[0])
MAP_ORIGIN_Y = -1.660    # m     (shop.yaml origin[1])
MAP_SCALE = 4            # PNG를 원본 PGM의 4배로 저장했으므로 픽셀 변환에 곱함

# robot_id별 색상 (최대 10대 지원)
ROBOT_COLORS = [
    QColor('#27ae60'),  # green
    QColor('#2980b9'),  # blue
    QColor('#8e44ad'),  # purple
    QColor('#e67e22'),  # orange
    QColor('#16a085'),  # teal
    QColor('#c0392b'),  # red
    QColor('#d35400'),  # dark orange
    QColor('#2c3e50'),  # dark navy
    QColor('#f39c12'),  # yellow
    QColor('#1abc9c'),  # emerald
]

ROBOT_ICON_RADIUS = 8
BLINK_INTERVAL_MS = 500


class MapWidget(QLabel):
    """맵 오버레이 위젯."""

    map_clicked = pyqtSignal(float, float)  # world x, y

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_pixmap: QPixmap | None = None
        self._robot_states: dict[str, dict] = {}  # robot_id → state dict
        self._robot_color_map: dict[str, QColor] = {}
        self._color_index = 0
        self._goto_marker: tuple[float, float] | None = None  # world (x, y)
        self._blink_state = False

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(BLINK_INTERVAL_MS)
        self._blink_timer.timeout.connect(self._on_blink)
        self._blink_timer.start()

        self.setMinimumSize(400, 320)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._load_map()

    def _load_map(self):
        # 후보 경로 순서대로 탐색
        # 1) colcon install 후 ament share 디렉터리
        # 2) 소스 트리 직접 실행 (개발 편의)
        candidates = []
        try:
            from ament_index_python.packages import get_package_share_directory
            candidates.append(
                os.path.join(get_package_share_directory('admin_ui'), 'assets', 'shop_map.png')
            )
        except Exception:
            pass
        candidates.append(
            os.path.join(os.path.dirname(__file__), '..', 'assets', 'shop_map.png')
        )

        for map_path in candidates:
            if os.path.isfile(map_path):
                pix = QPixmap(map_path)
                if not pix.isNull():
                    self._base_pixmap = pix
                    self.setFixedSize(pix.size())
                    return

    def _get_robot_color(self, robot_id: str) -> QColor:
        if robot_id not in self._robot_color_map:
            self._robot_color_map[robot_id] = ROBOT_COLORS[
                self._color_index % len(ROBOT_COLORS)
            ]
            self._color_index += 1
        return self._robot_color_map[robot_id]

    def _world_to_pixel(self, x: float, y: float) -> tuple[int, int]:
        """월드 좌표 → 픽셀 좌표 변환."""
        if self._base_pixmap is not None:
            img_h = self._base_pixmap.height()
        else:
            img_h = self.height()
        px = int((x - MAP_ORIGIN_X) / MAP_RESOLUTION * MAP_SCALE)
        py = int(img_h - (y - MAP_ORIGIN_Y) / MAP_RESOLUTION * MAP_SCALE)
        return px, py

    def _pixel_to_world(self, px: int, py: int) -> tuple[float, float]:
        """픽셀 좌표 → 월드 좌표 변환."""
        if self._base_pixmap is not None:
            img_h = self._base_pixmap.height()
        else:
            img_h = self.height()
        x = px / MAP_SCALE * MAP_RESOLUTION + MAP_ORIGIN_X
        y = (img_h - py) / MAP_SCALE * MAP_RESOLUTION + MAP_ORIGIN_Y
        return x, y

    def update_robot(self, robot_id: str, state: dict):
        """로봇 상태 업데이트 후 다시 그리기."""
        self._robot_states[robot_id] = state
        self.update()

    def set_goto_marker(self, x: float, y: float):
        """admin_goto 클릭 마커 설정."""
        self._goto_marker = (x, y)
        self.update()

    def clear_goto_marker(self):
        """마커 제거."""
        self._goto_marker = None
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            x, y = self._pixel_to_world(event.pos().x(), event.pos().y())
            self._goto_marker = (x, y)
            self.map_clicked.emit(x, y)
            self.update()
        super().mousePressEvent(event)

    def _on_blink(self):
        self._blink_state = not self._blink_state
        # 점멸이 필요한 로봇이 있으면 갱신
        needs_blink = any(
            s.get('mode') in ('LOCKED', 'HALTED') or s.get('is_locked_return')
            for s in self._robot_states.values()
        )
        if needs_blink:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 배경
        if self._base_pixmap is not None:
            painter.drawPixmap(0, 0, self._base_pixmap)
        else:
            painter.fillRect(self.rect(), QColor('#555555'))
            painter.setPen(QColor('#ffffff'))
            font = QFont()
            font.setPointSize(14)
            painter.setFont(font)
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, '맵 이미지 없음'
            )

        # 로봇 아이콘
        for robot_id, state in self._robot_states.items():
            pos_x = state.get('pos_x', 0.0)
            pos_y = state.get('pos_y', 0.0)
            mode = state.get('mode', 'OFFLINE')
            is_locked_return = state.get('is_locked_return', False)

            px, py = self._world_to_pixel(pos_x, pos_y)
            color = self._get_robot_color(robot_id)
            r = ROBOT_ICON_RADIUS

            if mode == 'OFFLINE':
                # x 표시
                painter.setPen(QPen(QColor('#aaaaaa'), 2))
                painter.drawLine(px - r, py - r, px + r, py + r)
                painter.drawLine(px + r, py - r, px - r, py + r)
            else:
                # 원형 아이콘
                painter.setBrush(color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(px - r, py - r, r * 2, r * 2)

                # 점멸 테두리
                if is_locked_return and self._blink_state:
                    painter.setPen(QPen(QColor('#e74c3c'), 3))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(px - r - 3, py - r - 3, (r + 3) * 2, (r + 3) * 2)
                elif mode == 'HALTED' and self._blink_state:
                    painter.setPen(QPen(QColor('#ffffff'), 3))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(px - r - 3, py - r - 3, (r + 3) * 2, (r + 3) * 2)

                # robot_id 레이블
                painter.setPen(QColor('#ffffff'))
                font = QFont()
                font.setPointSize(8)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(px - r, py - r - 2, robot_id)

        # admin_goto 마커 (파란 십자)
        if self._goto_marker is not None:
            mx, my = self._goto_marker
            mpx, mpy = self._world_to_pixel(mx, my)
            pen = QPen(QColor('#3498db'), 2)
            painter.setPen(pen)
            arm = 10
            painter.drawLine(mpx - arm, mpy, mpx + arm, mpy)
            painter.drawLine(mpx, mpy - arm, mpx, mpy + arm)
            painter.drawEllipse(mpx - 4, mpy - 4, 8, 8)

        painter.end()

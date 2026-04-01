"""MapView — renders the shop map with robot position overlays."""

import os
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont
from PyQt6.QtCore import Qt, QPointF

# Map image shipped with shoppinkki_nav
_MAP_PATH = os.path.join(
    os.path.dirname(__file__),
    '..', '..', '..', '..', '..', '..', '..', '..', '..', '..', '..', '..',
    'shoppinkki', 'shoppinkki_nav', 'maps', 'shop.pgm',
)

# Coordinate conversion constants (placeholder — fill in after map calibration)
MAP_ORIGIN_X = 0.0    # metres
MAP_ORIGIN_Y = 0.0    # metres
MAP_RESOLUTION = 0.05  # metres per pixel


def world_to_pixel(x: float, y: float, img_height: int):
    """Convert ROS world coordinates (m) to image pixel coordinates."""
    px = int((x - MAP_ORIGIN_X) / MAP_RESOLUTION)
    py = img_height - int((y - MAP_ORIGIN_Y) / MAP_RESOLUTION)
    return px, py


class MapView(QWidget):
    """Draws shop map with live robot position dots."""

    ROBOT_COLORS = {'54': QColor('#00cc44'), '18': QColor('#3399ff')}

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._positions: dict[str, tuple[float, float]] = {}
        self._pixmap: QPixmap | None = None
        self._load_map()
        self._connect_signals()
        self.setMinimumSize(300, 200)

    def _load_map(self):
        if os.path.exists(_MAP_PATH):
            self._pixmap = QPixmap(_MAP_PATH)
        else:
            self._pixmap = None

    def _connect_signals(self):
        self._bridge.robot_status_updated.connect(self._on_status)
        self._bridge.robot_offline.connect(self._on_offline)

    def _on_status(self, robot_id: str, status: dict):
        self._positions[robot_id] = (
            float(status.get('pos_x', 0.0)),
            float(status.get('pos_y', 0.0)),
        )
        self.update()  # trigger paintEvent

    def _on_offline(self, robot_id: str):
        self._positions.pop(robot_id, None)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        if self._pixmap:
            scaled = self._pixmap.scaled(
                w, h, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, scaled)
            img_h = scaled.height()
            img_w = scaled.width()
        else:
            painter.fillRect(0, 0, w, h, QColor('#222222'))
            painter.setPen(QColor('#555555'))
            painter.drawText(w // 2 - 50, h // 2, '맵 이미지 없음')
            img_h = h
            img_w = w

        # Draw robot dots
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        for robot_id, (rx, ry) in self._positions.items():
            px, py = world_to_pixel(rx, ry, img_h)
            color = self.ROBOT_COLORS.get(robot_id, QColor('#ffffff'))
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(px, py), 8, 8)
            painter.setPen(QColor('#ffffff'))
            painter.drawText(px + 10, py + 4, f'#{robot_id}')

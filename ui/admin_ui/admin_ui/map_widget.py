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

"""MapWidget -- shop_map.png 위에 로봇 위치를 실시간 표시.

원본 PNG를 그대로 표시 (회전·반전 없음).
shop.yaml에서 resolution, origin을 런타임에 로드하여
ROS map_server 표준 좌표 변환으로 Gazebo pose → 픽셀 매핑.

좌표 변환 (ROS map_server 표준):
    px = (x - origin_x) / resolution * scale
    py = img_h - (y - origin_y) / resolution * scale

    - px: 오른쪽으로 갈수록 X 증가
    - py: 위로 갈수록 Y 증가 (이미지 row는 위→아래이므로 반전)
"""

from __future__ import annotations

import math
import os
from typing import Any

import yaml
from PyQt6.QtCore import Qt, QPointF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
)
from PyQt6.QtWidgets import QLabel

# ────────────────────────────────────────────────────
# 상수
# ────────────────────────────────────────────────────
ROBOT_ICON_RADIUS = 8
ARROW_LENGTH_PX = 18
MAP_DISPLAY_SCALE = 3  # PNG 대비 표시 배율
BLINK_INTERVAL_MS = 500

ROBOT_COLORS = [
    QColor('#27ae60'),   # green
    QColor('#2980b9'),   # blue
    QColor('#8e44ad'),   # purple
    QColor('#e67e22'),   # orange
    QColor('#16a085'),   # teal
    QColor('#c0392b'),   # red
    QColor('#d35400'),   # dark orange
    QColor('#2c3e50'),   # dark navy
    QColor('#f39c12'),   # yellow
    QColor('#1abc9c'),   # emerald
]


# ────────────────────────────────────────────────────
# YAML 로더
# ────────────────────────────────────────────────────
def _find_map_yaml() -> str | None:
    """shop.yaml 경로를 찾는다. 없으면 None."""
    candidates: list[str] = []

    # 1) shoppinkki_nav 패키지 (source of truth)
    try:
        from ament_index_python.packages import get_package_share_directory
        candidates.append(
            os.path.join(
                get_package_share_directory('shoppinkki_nav'),
                'maps', 'shop.yaml',
            )
        )
    except Exception:
        pass

    # 2) 소스 트리 fallback
    candidates.append(
        os.path.join(
            os.path.dirname(__file__), '..', '..', '..', '..',
            'device', 'shoppinkki', 'shoppinkki_nav', 'maps', 'shop.yaml',
        )
    )

    for path in candidates:
        if os.path.isfile(path):
            return os.path.abspath(path)
    return None


def _load_map_meta() -> dict[str, Any]:
    """shop.yaml를 읽어 resolution, origin_x, origin_y를 반환."""
    defaults = {'resolution': 0.01, 'origin_x': 0.0, 'origin_y': 0.0}

    yaml_path = _find_map_yaml()
    if yaml_path is None:
        return defaults

    with open(yaml_path, 'r') as f:
        data = yaml.safe_load(f)

    origin = data.get('origin', [0.0, 0.0, 0.0])
    return {
        'resolution': float(data.get('resolution', 0.01)),
        'origin_x': float(origin[0]),
        'origin_y': float(origin[1]),
    }


# ────────────────────────────────────────────────────
# PNG 탐색
# ────────────────────────────────────────────────────
def _find_map_png() -> str | None:
    """shop.png 경로를 찾는다 (shoppinkki_nav/maps/ 단일 원본)."""
    candidates: list[str] = []

    try:
        from ament_index_python.packages import get_package_share_directory
        candidates.append(
            os.path.join(
                get_package_share_directory('shoppinkki_nav'),
                'maps', 'shop.png',
            )
        )
    except Exception:
        pass

    candidates.append(
        os.path.join(
            os.path.dirname(__file__), '..', '..', '..', '..',
            'device', 'shoppinkki', 'shoppinkki_nav', 'maps', 'shop.png',
        )
    )

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


# ────────────────────────────────────────────────────
# MapWidget
# ────────────────────────────────────────────────────
class MapWidget(QLabel):
    """맵 오버레이 위젯.

    원본 PNG를 그대로 표시하고, ROS map_server 표준 좌표 변환으로
    Gazebo/AMCL pose를 맵 픽셀에 매핑한다.
    """

    map_clicked = pyqtSignal(float, float, float)  # world (x, y, theta)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 맵 메타데이터 (YAML)
        meta = _load_map_meta()
        self._resolution: float = meta['resolution']
        self._origin_x: float = meta['origin_x']
        self._origin_y: float = meta['origin_y']
        self._scale: int = 1  # PNG/PGM 비율, _load_map에서 계산

        # 맵 이미지
        self._base_pixmap: QPixmap | None = None
        self._img_h: int = 0  # 원본 PNG 높이 (회전 전)
        self._img_w: int = 0  # 원본 PNG 너비 (회전 전)

        # 로봇 상태
        self._robot_states: dict[str, dict] = {}
        self._robot_color_map: dict[str, QColor] = {}
        self._color_idx = 0

        # 목적지 마커
        self._goto_marker: tuple[float, float] | None = None
        self._goto_theta: float = 0.0  # 목적지 방향 (rad)
        self._click_label: str = ''  # 클릭 좌표 텍스트

        # 드래그 상태 (클릭=위치, 드래그=방향)
        self._drag_origin_px: tuple[int, int] | None = None  # 클릭 위치 (px)
        self._drag_origin_world: tuple[float, float] | None = None  # 클릭 위치 (world)
        self._drag_current_px: tuple[int, int] | None = None  # 현재 마우스 (px)
        self._dragging: bool = False

        # 점멸 타이머
        self._blink_on = False
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(BLINK_INTERVAL_MS)
        self._blink_timer.timeout.connect(self._toggle_blink)
        self._blink_timer.start()

        self.setMinimumSize(400, 320)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._load_map()

    # ── 맵 로드 ─────────────────────────────────────

    def _load_map(self):
        map_path = _find_map_png()
        if map_path is None:
            return

        pix = QPixmap(map_path)
        if pix.isNull():
            return

        # 원본 크기 저장 (좌표 변환용)
        self._img_w = pix.width()
        self._img_h = pix.height()

        # PNG/PGM scale 자동 계산 (PGM resolution 기준)
        yaml_path = _find_map_yaml()
        if yaml_path:
            pgm_dir = os.path.dirname(yaml_path)
            with open(yaml_path, 'r') as f:
                data = yaml.safe_load(f)
            pgm_name = data.get('image', '')
            pgm_path = os.path.join(pgm_dir, pgm_name)
            if os.path.isfile(pgm_path):
                pgm_pix = QPixmap(pgm_path)
                if not pgm_pix.isNull() and pgm_pix.width() > 0:
                    self._scale = pix.width() // pgm_pix.width()

        if self._scale < 1:
            self._scale = 1

        # 270° CW 회전 + 상하 반전
        rotated = pix.transformed(QTransform().rotate(270).scale(1, -1))
        self._base_pixmap = rotated
        # 초기 크기: 맵 × MAP_DISPLAY_SCALE, 리사이즈 가능
        self.setMinimumSize(rotated.width(), rotated.height())
        self.resize(rotated.width() * MAP_DISPLAY_SCALE,
                    rotated.height() * MAP_DISPLAY_SCALE)

    # ── 좌표 변환 ───────────────────────────────────
    #
    # 원본 ROS map_server 표준:
    #   col_orig = (x - origin_x) / resolution * scale
    #   row_orig = img_h - (y - origin_y) / resolution * scale
    #
    # 270° CW 회전 후 (90° CCW):
    #   col_rot = row_orig = img_h - (y - origin_y) / resolution * scale
    #   row_rot = img_w - col_orig = img_w - (x - origin_x) / resolution * scale

    @property
    def _display_scale(self) -> float:
        """위젯 크기 / 원본 픽스맵 크기 비율 (비율 유지, 작은 쪽 기준)."""
        if self._base_pixmap is None or self._base_pixmap.width() == 0:
            return 1.0
        sx = self.width() / self._base_pixmap.width()
        sy = self.height() / self._base_pixmap.height()
        return min(sx, sy)

    @property
    def _map_offset(self) -> tuple[int, int]:
        """비율 유지 시 맵을 위젯 중앙에 배치하기 위한 (ox, oy) 오프셋."""
        if self._base_pixmap is None:
            return 0, 0
        d = self._display_scale
        draw_w = int(self._base_pixmap.width() * d)
        draw_h = int(self._base_pixmap.height() * d)
        return (self.width() - draw_w) // 2, (self.height() - draw_h) // 2

    def _world_to_pixel(self, x: float, y: float) -> tuple[int, int]:
        """월드 좌표 → 위젯 픽셀 좌표."""
        s = self._scale
        r = self._resolution
        d = self._display_scale
        ox, oy = self._map_offset
        px = int((self._img_h - (y - self._origin_y) / r * s) * d) + ox
        py = int((self._img_w - (x - self._origin_x) / r * s) * d) + oy
        return px, py

    def _pixel_to_world(self, px: int, py: int) -> tuple[float, float]:
        """위젯 픽셀 좌표 → 월드 좌표."""
        s = self._scale
        r = self._resolution
        d = self._display_scale
        ox, oy = self._map_offset
        x = self._origin_x + (self._img_w - (py - oy) / d) / s * r
        y = self._origin_y + (self._img_h - (px - ox) / d) / s * r
        return x, y

    # ── 공개 API ────────────────────────────────────

    def update_robot(self, robot_id: str, state: dict):
        """로봇 상태 업데이트."""
        self._robot_states[robot_id] = state
        self.update()

    def set_goto_marker(self, x: float, y: float, theta: float = 0.0):
        """목적지 마커 표시."""
        self._goto_marker = (x, y)
        self._goto_theta = theta
        self.update()

    def clear_goto_marker(self):
        """목적지 마커 제거."""
        self._goto_marker = None
        self.update()

    # ── 이벤트 핸들링 ──────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            px, py = event.pos().x(), event.pos().y()
            wx, wy = self._pixel_to_world(px, py)
            self._drag_origin_px = (px, py)
            self._drag_origin_world = (wx, wy)
            self._drag_current_px = (px, py)
            self._dragging = False
            self._goto_marker = (wx, wy)
            self._goto_theta = 0.0
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_origin_px is not None:
            px, py = event.pos().x(), event.pos().y()
            dx = px - self._drag_origin_px[0]
            dy = py - self._drag_origin_px[1]
            if dx * dx + dy * dy > 25:  # 5px 이상 드래그 시 방향 모드
                self._dragging = True
            self._drag_current_px = (px, py)
            if self._dragging:
                raw = math.atan2(-(dy), dx)  # 화면 y 반전 보정
                # 30° 단위로 스냅 (12방향)
                step = math.radians(30)
                self._goto_theta = round(raw / step) * step
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_origin_world:
            wx, wy = self._drag_origin_world
            theta = self._goto_theta
            self._click_label = f'({wx:.3f}, {wy:.3f}, {math.degrees(theta):.0f}°)'
            self.map_clicked.emit(wx, wy, theta)
            self._drag_origin_px = None
            self._drag_origin_world = None
            self._drag_current_px = None
            self._dragging = False
            self.update()
        super().mouseReleaseEvent(event)

    def _toggle_blink(self):
        self._blink_on = not self._blink_on
        needs = any(
            s.get('mode') in ('LOCKED', 'HALTED') or s.get('is_locked_return')
            for s in self._robot_states.values()
        )
        if needs:
            self.update()

    # ── 렌더링 ──────────────────────────────────────

    def _get_color(self, robot_id: str) -> QColor:
        if robot_id not in self._robot_color_map:
            self._robot_color_map[robot_id] = ROBOT_COLORS[
                self._color_idx % len(ROBOT_COLORS)
            ]
            self._color_idx += 1
        return self._robot_color_map[robot_id]

    def _draw_robot(self, p: QPainter, robot_id: str, state: dict):
        pos_x = state.get('pos_x', 0.0)
        pos_y = state.get('pos_y', 0.0)
        yaw = state.get('yaw', 0.0)
        mode = state.get('mode', 'OFFLINE')
        locked_ret = state.get('is_locked_return', False)

        cx, cy = self._world_to_pixel(pos_x, pos_y)
        color = self._get_color(robot_id)
        r = ROBOT_ICON_RADIUS

        # OFFLINE: 회색 X
        if mode == 'OFFLINE':
            p.setPen(QPen(QColor('#aaaaaa'), 2))
            p.drawLine(cx - r, cy - r, cx + r, cy + r)
            p.drawLine(cx + r, cy - r, cx - r, cy + r)
            return

        # 원형 아이콘
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # 방향 화살표
        arrow_m = ARROW_LENGTH_PX * self._resolution / self._scale
        end_x = pos_x + arrow_m * math.cos(yaw)
        end_y = pos_y + arrow_m * math.sin(yaw)
        ax, ay = self._world_to_pixel(end_x, end_y)

        p.setPen(QPen(color.darker(130), 2))
        p.drawLine(cx, cy, ax, ay)

        # 화살촉
        hs = 5
        dx, dy = float(ax - cx), float(ay - cy)
        ang = math.atan2(dy, dx)
        p.setBrush(color.darker(130))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([
            QPointF(ax, ay),
            QPointF(ax - hs * math.cos(ang - 0.5), ay - hs * math.sin(ang - 0.5)),
            QPointF(ax - hs * math.cos(ang + 0.5), ay - hs * math.sin(ang + 0.5)),
        ]))

        # 점멸 테두리 (LOCKED/HALTED)
        if self._blink_on:
            if locked_ret:
                p.setPen(QPen(QColor('#e74c3c'), 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(cx - r - 3, cy - r - 3, (r + 3) * 2, (r + 3) * 2)
            elif mode == 'HALTED':
                p.setPen(QPen(QColor('#ffffff'), 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(cx - r - 3, cy - r - 3, (r + 3) * 2, (r + 3) * 2)

        # ID 레이블 (배경 박스 + 텍스트)
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(robot_id)
        th = fm.height()
        tx = cx - tw // 2
        ty = cy - r - th - 2
        p.setBrush(QColor(0, 0, 0, 160))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(tx - 3, ty - 1, tw + 6, th + 2, 3, 3)
        p.setPen(QColor('#ffffff'))
        p.drawText(tx, ty + fm.ascent(), robot_id)

    def _draw_goto_marker(self, p: QPainter):
        if self._goto_marker is None:
            return
        mx, my = self._world_to_pixel(*self._goto_marker)
        arm = 10
        color = QColor('#3498db')
        p.setPen(QPen(color, 2))
        p.drawLine(mx - arm, my, mx + arm, my)
        p.drawLine(mx, my - arm, mx, my + arm)
        p.drawEllipse(mx - 4, my - 4, 8, 8)

        # 방향 화살표 (30° 스냅된 theta 기반)
        arrow_len = 30
        theta = self._goto_theta
        ex = mx + int(arrow_len * math.cos(-theta))
        ey = my + int(arrow_len * math.sin(-theta))
        p.setPen(QPen(color, 3))
        p.drawLine(mx, my, ex, ey)
        # 화살촉
        hs = 8
        dx, dy = float(ex - mx), float(ey - my)
        ang = math.atan2(dy, dx)
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([
            QPointF(ex, ey),
            QPointF(ex - hs * math.cos(ang - 0.4), ey - hs * math.sin(ang - 0.4)),
            QPointF(ex - hs * math.cos(ang + 0.4), ey - hs * math.sin(ang + 0.4)),
        ]))

        # 좌표 텍스트
        if self._click_label:
            font = QFont()
            font.setPointSize(9)
            font.setBold(True)
            p.setFont(font)
            p.setPen(color)
            p.drawText(mx + 12, my - 4, self._click_label)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._base_pixmap is not None:
            d = self._display_scale
            ox, oy = self._map_offset
            draw_w = int(self._base_pixmap.width() * d)
            draw_h = int(self._base_pixmap.height() * d)
            from PyQt6.QtCore import QRect
            p.drawPixmap(QRect(ox, oy, draw_w, draw_h), self._base_pixmap)
        else:
            p.fillRect(self.rect(), QColor('#555555'))
            p.setPen(QColor('#ffffff'))
            font = QFont()
            font.setPointSize(14)
            p.setFont(font)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '맵 이미지 없음')

        for rid, st in self._robot_states.items():
            self._draw_robot(p, rid, st)

        self._draw_goto_marker(p)
        p.end()

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

# 로봇 footprint (m) — base_footprint 기준, 바구니 포함
ROBOT_FRONT = 0.07   # 앞 (바구니 포함)
ROBOT_REAR  = 0.08   # 뒤
ROBOT_HALF_W = 0.055 # 좌우 반폭
BLINK_INTERVAL_MS = 500

# 맵 스타일링 색상
MAP_FLOOR_COLOR = QColor('#E0E4E8')      # 가독성 높은 라이트 그레이 바닥
MAP_WALL_COLOR = QColor('#2C3E50')       # 더 짙은 미드나잇 블루 벽
MAP_SHELF_COLOR = QColor('#3D5A80')      # 조금 더 밝고 푸른빛이 도는 선반 내부
MAP_UNKNOWN_COLOR = QColor('#CED4DA')    # 미확인 영역 (외부)
MAP_SUBTLE_COLOR = QColor('#BDC3C7')     # 보조선 (결제구역 등)
MAP_BG_COLOR = QColor('#FFFFFF')         # 맵 외부 배경 (순백색)

ROBOT_COLORS = [
    QColor('#f1c40f'),   # yellow (Sun Flower)
    QColor('#9b59b6'),   # purple (Amethyst)
    QColor('#27ae60'),   # green
    QColor('#2980b9'),   # blue
    QColor('#8e44ad'),   # dark purple
    QColor('#e67e22'),   # orange
    QColor('#16a085'),   # teal
    QColor('#c0392b'),   # red
    QColor('#d35400'),   # dark orange
    QColor('#2c3e50'),   # dark navy
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
    """shop_styled.png(UI 표시용)을 우선 탐색, 없으면 shop.png fallback."""
    # 탐색 순서: styled → original, 설치 경로 → 소스 트리
    names = ['shop_styled.png', 'shop.png']
    candidates: list[str] = []

    for name in names:
        try:
            from ament_index_python.packages import get_package_share_directory
            candidates.append(
                os.path.join(
                    get_package_share_directory('shoppinkki_nav'),
                    'maps', name,
                )
            )
        except Exception:
            pass

        candidates.append(
            os.path.join(
                os.path.dirname(__file__), '..', '..', '..', '..',
                'device', 'shoppinkki', 'shoppinkki_nav', 'maps', name,
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

        # Fleet graph 데이터
        self._fleet_waypoints: list[dict] = []
        self._fleet_lanes: list[dict] = []

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

        # 스타일 적용 (색상 치환)
        pix = self._stylize_pixmap(pix)

        # 270° CW 회전 + 상하 반전
        rotated = pix.transformed(QTransform().rotate(270).scale(1, -1))
        self._base_pixmap = rotated
        # 초기 크기: 맵 × MAP_DISPLAY_SCALE, 리사이즈 가능
        self.setMinimumSize(rotated.width(), rotated.height())
        self.resize(rotated.width() * MAP_DISPLAY_SCALE,
                    rotated.height() * MAP_DISPLAY_SCALE)

    def _stylize_pixmap(self, pix: QPixmap) -> QPixmap:
        """원본 점유 격자 맵을 세련된 색상으로 변환."""
        img = pix.toImage()
        w, h = img.width(), img.height()

        for y in range(h):
            for x in range(w):
                c = img.pixelColor(x, y)
                gray = c.lightness()
                if gray > 200:       # 빈 공간 → 깨끗한 화이트
                    img.setPixelColor(x, y, MAP_FLOOR_COLOR)
                elif gray < 10:      # 벽 → 짙은 블루그레이
                    img.setPixelColor(x, y, MAP_WALL_COLOR)
                elif 90 <= gray <= 110:   # 선반 내부 (값 100)
                    img.setPixelColor(x, y, MAP_SHELF_COLOR)
                elif 160 <= gray <= 180:  # 보조선 (값 170)
                    img.setPixelColor(x, y, MAP_SUBTLE_COLOR)
                else:                # 미확인 영역
                    img.setPixelColor(x, y, MAP_UNKNOWN_COLOR)

        return QPixmap.fromImage(img)

    def _draw_grid(self, p: QPainter):
        """바닥 위에 미세한 격자선을 그린다."""
        if self._base_pixmap is None:
            return
        d = self._display_scale
        ox, oy = self._map_offset
        draw_w = int(self._base_pixmap.width() * d)
        draw_h = int(self._base_pixmap.height() * d)

        grid_step_px = 0.1 / self._resolution * self._scale * d
        if grid_step_px < 4:
            return

        p.setPen(QPen(MAP_GRID_COLOR, 0.5))
        x = float(ox)
        while x <= ox + draw_w:
            p.drawLine(int(x), oy, int(x), oy + draw_h)
            x += grid_step_px
        y = float(oy)
        while y <= oy + draw_h:
            p.drawLine(ox, int(y), ox + draw_w, int(y))
            y += grid_step_px

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

    def set_fleet_graph(self, waypoints: list[dict], lanes: list[dict]):
        """Fleet nav graph 데이터 설정 (REST /fleet/graph 응답)."""
        self._fleet_waypoints = waypoints
        self._fleet_lanes = lanes
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
            display_theta = self._goto_theta
            # 화면 좌표계 → ROS map frame 보정 (맵 270° CW + 상하반전)
            ros_theta = display_theta - math.pi / 2
            self._click_label = f'({wx:.3f}, {wy:.3f}, {math.degrees(display_theta):.0f}°)'
            self.map_clicked.emit(wx, wy, ros_theta)
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
        # 54번: 청록색, 18번: 보라색 고정
        rid_str = str(robot_id)
        if rid_str == '54':
            return QColor('#16A085')
        if rid_str == '18':
            return QColor('#9B59B6')

        if robot_id not in self._robot_color_map:
            self._robot_color_map[robot_id] = ROBOT_COLORS[
                self._color_idx % len(ROBOT_COLORS)
            ]
            self._color_idx += 1
        return self._robot_color_map[robot_id]

    def _draw_fleet_graph(self, p: QPainter):
        """Fleet nav graph 렌더링 — 미니멀하고 깔끔한 스타일."""
        if not self._fleet_waypoints:
            return

        # 인덱스 → 픽셀 좌표 매핑
        wp_px: dict[int, tuple[int, int]] = {}
        for w in self._fleet_waypoints:
            px, py = self._world_to_pixel(w['x'], w['y'])
            wp_px[w['idx']] = (px, py)

        # 레인 (조금 더 선명한 점선)
        p.setPen(QPen(QColor(100, 120, 140, 130), 0.7, Qt.PenStyle.DotLine))
        for lane in self._fleet_lanes:
            f = wp_px.get(lane['from'])
            t = wp_px.get(lane['to'])
            if f and t:
                p.drawLine(f[0], f[1], t[0], t[1])

        # 레이블 폰트 (작지만 또렷하게)
        font = QFont('Segoe UI', 8)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()

        label_rects: list[tuple] = []  # 겹침 감지용

        for w in self._fleet_waypoints:
            px, py = wp_px[w['idx']]
            r = 4  # 마커 반지름 — 작게

            # 색상 (채도를 낮추고 투명도 조절)
            if w.get('pickup_zone'):
                fill = QColor(100, 160, 220, 160)
                border = QColor(70, 130, 190)
            elif w.get('is_charger'):
                fill = QColor(80, 190, 130, 160)
                border = QColor(60, 160, 110)
            elif w.get('holding_point'):
                fill = QColor(220, 150, 70, 160)
                border = QColor(190, 120, 50)
            else:
                fill = QColor(170, 175, 180, 100)
                border = QColor(140, 145, 150)

            # 마커 (작은 원)
            p.setBrush(fill)
            p.setPen(QPen(border, 1))
            p.drawEllipse(px - r, py - r, r * 2, r * 2)

            # 이름 레이블 — 컴팩트, 겹침 회피
            name = w['name']
            tw = fm.horizontalAdvance(name)
            th = fm.height()
            pad_x, pad_y = 3, 1
            tx = px - tw // 2
            # 스마트 배치: 특정 키워드(결제, 로비, 선반류)는 무조건 위로
            force_above_kws = ['결제', '로비', '과자', '해산물', '육류', '채소']
            force_below = ['입구1', '입구2', 'P1', 'P2', '하단_복도', '출구2', '출구1', '결제구역1_입구']
            
            should_be_above = any(kw in name for kw in force_above_kws)
            is_bottom_area = py > self.height() * 0.7
            
            if (is_bottom_area or should_be_above) and (name not in force_below):
                ty = py - r - th - 8 # 위로
            else:
                ty = py + r + 8      # 아래로
                
            label_rect = (tx - pad_x, ty - pad_y, tw + pad_x * 2, th + pad_y * 2)
            
            # 겹침 방지: 위 배치 우선순위 지점은 가급적 아래로 밀려나지 않게 함
            for prev in label_rects:
                if (label_rect[0] < prev[0] + prev[2] and
                    label_rect[0] + label_rect[2] > prev[0] and
                    label_rect[1] < prev[1] + prev[3] and
                    label_rect[1] + label_rect[3] > prev[1]):
                    # 겹칠 경우, 강제 위 배치 지점이 아닌 경우에만 스왑 시도
                    if not should_be_above:
                        if ty < py: ty = py + r + 6
                        else:       ty = py - r - th - 6
                        label_rect = (tx - pad_x, ty - pad_y, tw + pad_x * 2, th + pad_y * 2)
                    break
            label_rects.append(label_rect)

            # 반투명 배경 (더 진하게)
            p.setBrush(QColor(25, 30, 40, 210))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(label_rect[0], label_rect[1],
                              label_rect[2], label_rect[3], 4, 4)
            p.setPen(QColor(240, 242, 245))
            p.drawText(tx, ty + fm.ascent(), name)

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

        # footprint 직사각형 (base_footprint 기준 비대칭)
        d = self._display_scale
        res = self._resolution
        s = self._scale
        # 미터 → 픽셀 변환 계수
        m2px = d / res * s
        front_px = ROBOT_FRONT * m2px
        rear_px = ROBOT_REAR * m2px
        hw_px = ROBOT_HALF_W * m2px

        # 로봇 로컬 좌표 (앞=+x) → 4 꼭짓점
        corners_local = [
            ( front_px,  hw_px),   # 앞 좌
            ( front_px, -hw_px),   # 앞 우
            (-rear_px,  -hw_px),   # 뒤 우
            (-rear_px,   hw_px),   # 뒤 좌
        ]
        # 맵 회전 보정: 화면상 yaw → 픽셀 회전 (270° CW + 상하반전)
        screen_angle = -(yaw - math.pi / 2)
        cos_a = math.cos(screen_angle)
        sin_a = math.sin(screen_angle)
        poly = QPolygonF()
        for lx, ly in corners_local:
            rx = lx * cos_a - ly * sin_a
            ry = lx * sin_a + ly * cos_a
            poly.append(QPointF(cx + rx, cy + ry))

        p.setBrush(QColor(color.red(), color.green(), color.blue(), 140))
        p.setPen(QPen(color, 1.5))
        p.drawPolygon(poly)

        # 앞면 표시 (바구니 쪽, 굵은 선) — poly[2],[3]이 화면상 앞면
        p.setPen(QPen(color.lighter(150), 3))
        p.drawLine(poly[2], poly[3])

        # 방향 화살표 (중심 → 앞면 중앙에서 돌출)
        front_mid = QPointF((poly[2].x() + poly[3].x()) / 2,
                            (poly[2].y() + poly[3].y()) / 2)
        # 중심 → 앞면 중앙 방향으로 연장
        dx_arrow = front_mid.x() - cx
        dy_arrow = front_mid.y() - cy
        arr_len = math.hypot(dx_arrow, dy_arrow)
        if arr_len > 0:
            nx, ny = dx_arrow / arr_len, dy_arrow / arr_len
        else:
            nx, ny = 1.0, 0.0
        ext = front_px * 0.8
        tip = QPointF(front_mid.x() + nx * ext, front_mid.y() + ny * ext)
        p.setPen(QPen(color.darker(130), 2))
        p.drawLine(QPointF(cx, cy), tip)
        # 화살촉
        hs = 8
        arr_ang = math.atan2(ny, nx)
        p.setBrush(color.darker(130))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([
            tip,
            QPointF(tip.x() - hs * math.cos(arr_ang - 0.5),
                    tip.y() - hs * math.sin(arr_ang - 0.5)),
            QPointF(tip.x() - hs * math.cos(arr_ang + 0.5),
                    tip.y() - hs * math.sin(arr_ang + 0.5)),
        ]))

        # 점멸 테두리 (LOCKED/HALTED)
        if self._blink_on:
            if locked_ret:
                p.setPen(QPen(QColor('#e74c3c'), 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolygon(poly)
            elif mode == 'HALTED':
                p.setPen(QPen(QColor('#ffffff'), 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolygon(poly)

        # ID 레이블 (배경 박스 + 텍스트)
        font = QFont('Segoe UI', 8)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(robot_id)
        th = fm.height()
        tx = cx - tw // 2
        ty = cy - r - th - 5
        # 로봇 색상 배경 + 둥근 모서리 (더 진하게)
        bg = QColor(color.red(), color.green(), color.blue(), 230)
        p.setBrush(bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(tx - 3, ty - 1, tw + 6, th + 2, 4, 4)
        p.setPen(QColor('#ffffff'))
        p.drawText(tx, ty + fm.ascent(), robot_id)

    def _draw_path(self, p: QPainter, robot_id: str, state: dict):
        """로봇의 전체 계획 경로를 지도 위에 점선(DashLine)으로 렌더링."""
        path = state.get('path', [])
        if not path or len(path) < 2:
            return

        color = self._get_color(robot_id)
        # 본체 색상을 사용하되 적당한 투명도와 점선 스타일 적용
        pen_color = QColor(color.red(), color.green(), color.blue(), 130)
        p.setPen(QPen(pen_color, 2.5, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)

        poly = QPolygonF()
        for pt in path:
            px, py = self._world_to_pixel(pt['x'], pt['y'])
            poly.append(QPointF(px, py))

        p.drawPolyline(poly)

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

        # 좌표 텍스트 (오른쪽 넘치면 왼쪽에 표시)
        if self._click_label:
            font = QFont()
            font.setPointSize(9)
            font.setBold(True)
            p.setFont(font)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(self._click_label)
            if mx + 12 + tw > self.width():
                tx = mx - 12 - tw
            else:
                tx = mx + 12
            p.setPen(color)
            p.drawText(tx, my - 4, self._click_label)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 맵 외부 배경
        p.fillRect(self.rect(), MAP_BG_COLOR)

        if self._base_pixmap is not None:
            d = self._display_scale
            ox, oy = self._map_offset
            draw_w = int(self._base_pixmap.width() * d)
            draw_h = int(self._base_pixmap.height() * d)
            from PyQt6.QtCore import QRect
            p.drawPixmap(QRect(ox, oy, draw_w, draw_h), self._base_pixmap)
            # 미세 테두리
            p.setPen(QPen(QColor(255, 255, 255, 30), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRect(ox, oy, draw_w, draw_h))
        else:
            p.setPen(QColor('#888888'))
            font = QFont()
            font.setPointSize(14)
            p.setFont(font)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '맵 이미지 없음')

        self._draw_fleet_graph(p)

        for rid, st in self._robot_states.items():
            self._draw_path(p, rid, st)  # 경로를 아이콘 아래에 배경으로 그림
            self._draw_robot(p, rid, st)

        self._draw_goto_marker(p)
        p.end()

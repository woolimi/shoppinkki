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

"""QMainWindow — 전체 레이아웃 조립.

레이아웃:
    - 상단: 연결 상태 레이블 + 제목
    - 좌: MapWidget
    - 우상: RobotCardPanel (HBox, 로봇 카드 2개)
    - 우중: CameraDebugPanel (기본 숨김)
    - 하좌: StaffCallPanel
    - 하우: EventLogPanel

TCP 메시지 처리 (message_received 시그널 연결):
    status       → robot_card.update_state(), map_widget.update_robot(),
                   camera_panel.update_bbox()
    staff_call   → staff_panel.add_call(), robot_card 테두리 강조
    staff_resolved → staff_panel.mark_resolved()
    event        → event_log_panel.add_event()
    admin_goto_rejected → QMessageBox.warning()

맵 클릭 → admin_goto 흐름:
    robot_card [이동 명령] 클릭 → goto_mode_activated(robot_id) emit
    map_widget.map_clicked → 대기 중인 로봇에 admin_goto 즉시 전송
"""

import json
import time
import urllib.request

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QAction
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .camera_panel import CameraDebugPanel
from .event_log_panel import EventLogPanel
from .map_widget import MapWidget
from .robot_card import RobotCard
from .robot_detail_dialog import RobotDetailDialog
from .staff_panel import StaffCallPanel
from .tcp_client import TCPClientThread
from .zone_select_dialog import ZoneSelectDialog

# OFFLINE 판정 기준 (초)
OFFLINE_TIMEOUT_SEC = 30


class MainWindow(QMainWindow):
    """Admin UI 메인 윈도우."""

    def __init__(
        self,
        tcp_host: str,
        tcp_port: int,
        rest_host: str,
        rest_port: int,
        robot_ids: list,
        parent=None,
    ):
        super().__init__(parent)
        self._tcp_host = tcp_host
        self._tcp_port = tcp_port
        self._rest_host = rest_host
        self._rest_port = rest_port
        self._robot_ids = robot_ids

        # 마지막 status 수신 시각 (OFFLINE 판정용)
        self._last_status_time: dict[str, float] = {}
        # 로봇별 최근 상태 캐시
        self._robot_states: dict[str, dict] = {}
        # 맵 클릭 대기 중인 로봇 ID (None = 대기 없음)
        self._goto_pending_robot: str | None = None
        # 위치 재조정 맵 클릭 대기 중인 로봇 ID (None = 대기 없음)
        self._position_adjustment_pending_robot: str | None = None
        # 로봇 상세 다이얼로그 (robot_id → dialog)
        self._detail_dialogs: dict[str, RobotDetailDialog] = {}
        self._rest_base = f'http://{rest_host}:{rest_port}'

        self.setWindowTitle('ShopPinkki — 관제 패널')
        self.resize(1400, 900)

        # 선택된 로봇 (확장성 — 로봇 셀렉터) — _build_ui 전에 초기화
        self._selected_robot: str | None = self._robot_ids[0] if self._robot_ids else None

        self._build_ui()
        self._fetch_fleet_graph()
        self._start_tcp()

        # OFFLINE 감지 + last_seen 갱신 타이머 (2초 주기)
        self._offline_timer = QTimer(self)
        self._offline_timer.setInterval(2000)
        self._offline_timer.timeout.connect(self._check_offline)
        self._offline_timer.start()


    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self):
        # 툴바
        toolbar = QToolBar('메인 툴바', self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._lbl_conn = QLabel('연결 중...')
        self._lbl_conn.setStyleSheet('color: #e67e22; font-weight: bold; padding: 0 8px;')
        toolbar.addWidget(self._lbl_conn)

        spacer = QWidget()
        spacer.setMinimumWidth(20)
        toolbar.addWidget(spacer)

        lbl_title = QLabel('쑈삥끼 관제 패널')
        lbl_title.setStyleSheet('font-size: 16px; font-weight: bold;')
        toolbar.addWidget(lbl_title)

        # 툴바 오른쪽: 카메라 패널 토글
        stretch = QWidget()
        stretch.setSizePolicy(
            stretch.sizePolicy().horizontalPolicy(),
            stretch.sizePolicy().verticalPolicy(),
        )
        from PyQt5.QtWidgets import QSizePolicy as SP
        stretch.setSizePolicy(SP.Policy.Expanding, SP.Policy.Preferred)
        toolbar.addWidget(stretch)

        btn_camera = QPushButton('카메라 패널')
        btn_camera.clicked.connect(self._toggle_camera_panel)
        toolbar.addWidget(btn_camera)

        # 중앙 위젯
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setSpacing(4)

        # 메인 수평 splitter (좌: 맵, 우: 카드+패널)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(main_splitter, stretch=1)

        # -- 좌: 맵 위젯
        self._map_widget = MapWidget()
        self._map_widget.map_clicked.connect(self._on_map_clicked)
        main_splitter.addWidget(self._map_widget)

        # -- 우: 수직 splitter (카드 패널 / 하단 패널)
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.addWidget(right_splitter)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 1)

        # 우상: 로봇 셀렉터 + 선택된 카드
        card_container = QWidget()
        card_outer = QVBoxLayout(card_container)
        card_outer.setContentsMargins(4, 4, 4, 4)
        card_outer.setSpacing(4)

        # 로봇 셀렉터 바 (확장성 — 로봇 수 증가에도 스크롤 가능)
        selector_row = QHBoxLayout()
        selector_row.setSpacing(4)
        self._selector_buttons: dict[str, QPushButton] = {}
        for rid in self._robot_ids:
            btn = QPushButton(f'#{rid}')
            btn.setCheckable(True)
            btn.setMinimumWidth(70)
            btn.setFixedHeight(32)
            btn.clicked.connect(lambda checked, r=rid: self._select_robot(r))
            selector_row.addWidget(btn)
            self._selector_buttons[rid] = btn
        selector_row.addStretch()

        # 전체 제어 버튼
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedHeight(28)
        selector_row.addWidget(sep)

        btn_all_wait = QPushButton('전체 대기')
        btn_all_wait.setFixedHeight(32)
        btn_all_wait.setToolTip('모든 로봇을 WAITING 상태로 전환')
        btn_all_wait.setStyleSheet('color: #2980b9; font-weight: bold;')
        btn_all_wait.clicked.connect(lambda: self._send_all('mode', 'WAITING'))
        selector_row.addWidget(btn_all_wait)

        btn_all_return = QPushButton('전체 복귀')
        btn_all_return.setFixedHeight(32)
        btn_all_return.setToolTip('모든 로봇을 충전소로 복귀')
        btn_all_return.setStyleSheet('color: #9b59b6; font-weight: bold;')
        btn_all_return.clicked.connect(lambda: self._send_all('mode', 'RETURNING'))
        selector_row.addWidget(btn_all_return)

        card_outer.addLayout(selector_row)

        # pending actions 배너 (#6)
        self._lbl_pending = QLabel('')
        self._lbl_pending.setStyleSheet(
            'background-color: #f39c12; color: white; font-weight: bold; '
            'padding: 4px 8px; border-radius: 4px;'
        )
        self._lbl_pending.hide()
        card_outer.addWidget(self._lbl_pending)

        # 카드 영역을 수직 중앙 배치
        card_outer.addStretch()

        # 각 로봇 카드 (모두 생성, 선택된 것만 표시)
        self._robot_cards: dict[str, RobotCard] = {}
        for rid in self._robot_ids:
            card = RobotCard(rid)
            card.command_requested.connect(self._on_command_requested)
            card.card_clicked.connect(self._on_card_clicked)
            card.goto_mode_activated.connect(self._on_goto_mode_activated)
            card.position_adjustment_mode_activated.connect(
                self._on_position_adjustment_mode_activated
            )
            card.guide_requested.connect(self._on_guide_requested)
            card.hide()
            card_outer.addWidget(card)
            self._robot_cards[rid] = card

        card_outer.addStretch()
        right_splitter.addWidget(card_container)

        # 초기 선택
        if self._selected_robot:
            self._select_robot(self._selected_robot)

        # 우중: 카메라 디버그 패널 (기본 숨김)
        self._camera_panel = CameraDebugPanel(
            self._rest_host, self._rest_port, self._robot_ids
        )
        self._camera_panel.hide()
        right_splitter.addWidget(self._camera_panel)

        # 하단: 스태프 패널 + 이벤트 로그
        bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(bottom_splitter, stretch=0)
        bottom_splitter.setFixedHeight(220)

        self._staff_panel = StaffCallPanel()
        self._staff_panel.resolve_requested.connect(self._on_resolve_requested)
        bottom_splitter.addWidget(self._staff_panel)

        self._event_log_panel = EventLogPanel()
        self._event_log_panel.row_clicked.connect(self._on_event_row_clicked)
        bottom_splitter.addWidget(self._event_log_panel)
        bottom_splitter.setStretchFactor(0, 1)
        bottom_splitter.setStretchFactor(1, 2)

        # 상태 바
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage('준비')

    # ------------------------------------------------------------------
    # Fleet graph 데이터 fetch
    # ------------------------------------------------------------------

    def _fetch_fleet_graph(self):
        """REST /fleet/graph에서 nav graph fetch → map_widget에 전달."""
        url = f'{self._rest_base}/fleet/graph'
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                data = json.loads(resp.read())
            self._map_widget.set_fleet_graph(
                data.get('waypoints', []),
                data.get('lanes', []),
            )
        except Exception:
            pass  # 서버 미기동 시 무시

    # ------------------------------------------------------------------
    # TCP 클라이언트
    # ------------------------------------------------------------------

    def _start_tcp(self):
        self._tcp = TCPClientThread(self._tcp_host, self._tcp_port, self._robot_ids)
        self._tcp.message_received.connect(self._on_message)
        self._tcp.connection_changed.connect(self._on_connection_changed)
        self._tcp.start()

    def _select_robot(self, robot_id: str):
        """로봇 셀렉터에서 로봇 선택."""
        self._selected_robot = robot_id
        for rid, btn in self._selector_buttons.items():
            btn.setChecked(rid == robot_id)
            state = self._robot_states.get(rid, {})
            mode = state.get('mode', 'OFFLINE')
            from .robot_card import MODE_COLORS
            color = MODE_COLORS.get(mode, '#aaaaaa')
            if rid == robot_id:
                btn.setStyleSheet(
                    f'QPushButton {{ background-color: {color}; color: white; '
                    f'font-weight: bold; border-radius: 4px; }}'
                )
            else:
                btn.setStyleSheet(
                    f'QPushButton {{ border: 2px solid {color}; border-radius: 4px; }}'
                )
        for rid, card in self._robot_cards.items():
            card.setVisible(rid == robot_id)

    def _update_selector_buttons(self):
        """셀렉터 버튼의 모드 색상 갱신."""
        for rid, btn in self._selector_buttons.items():
            state = self._robot_states.get(rid, {})
            mode = state.get('mode', 'OFFLINE')
            from .robot_card import MODE_COLORS
            color = MODE_COLORS.get(mode, '#aaaaaa')
            if rid == self._selected_robot:
                btn.setStyleSheet(
                    f'QPushButton {{ background-color: {color}; color: white; '
                    f'font-weight: bold; border-radius: 4px; }}'
                )
            else:
                btn.setStyleSheet(
                    f'QPushButton {{ border: 2px solid {color}; border-radius: 4px; }}'
                )

    def _on_connection_changed(self, connected: bool):
        if connected:
            self._lbl_conn.setText(
                f'연결됨  {self._tcp_host}:{self._tcp_port}'
            )
            self._lbl_conn.setStyleSheet('color: #27ae60; font-weight: bold; padding: 0 8px;')
            self.statusBar().showMessage('TCP 연결 완료')
        else:
            self._lbl_conn.setText(f'연결 끊김 — {self._tcp_port} 재연결 대기 중...')
            self._lbl_conn.setStyleSheet('color: #e74c3c; font-weight: bold; padding: 0 8px;')
            self.statusBar().showMessage('TCP 연결 끊김')
            # #5: pending 상태 전부 리셋
            self._goto_pending_robot = None
            self._position_adjustment_pending_robot = None
            for card in self._robot_cards.values():
                card.reset_pending()
            self._map_widget.set_pending_overlay(None)
            self._update_pending_banner()

    # ------------------------------------------------------------------
    # TCP 메시지 처리
    # ------------------------------------------------------------------

    def _on_message(self, data: dict):
        msg_type = data.get('type', '')

        if msg_type == 'status':
            self._handle_status(data)
        elif msg_type == 'staff_call':
            self._handle_staff_call(data)
        elif msg_type == 'staff_resolved':
            self._handle_staff_resolved(data)
        elif msg_type == 'event':
            self._handle_event(data)
        elif msg_type == 'event_history':
            self._event_log_panel.load_initial(data.get('events', []))
        elif msg_type == 'admin_goto_rejected':
            self._handle_goto_rejected(data)
        elif msg_type == 'position_adjustment_rejected':
            robot_id = str(data.get('robot_id', ''))
            QMessageBox.warning(
                self,
                '위치 재조정 실패',
                f'Robot #{robot_id} 위치 재조정이 실패했습니다.\n'
                f'{data.get("reason", "")}',
            )
        elif msg_type == 'position_adjustment_done':
            robot_id = str(data.get('robot_id', ''))
            if robot_id:
                # status 토픽 지연 시에도 위치 재조정 좌표를 UI에 즉시 반영
                state = dict(self._robot_states.get(robot_id, {}))
                state['robot_id'] = robot_id
                state['pos_x'] = float(data.get('x', state.get('pos_x', 0.0)))
                state['pos_y'] = float(data.get('y', state.get('pos_y', 0.0)))
                state['yaw'] = float(data.get('theta', state.get('yaw', 0.0)))
                self._robot_states[robot_id] = state
                self._last_status_time[robot_id] = time.monotonic()
                if robot_id in self._robot_cards:
                    self._robot_cards[robot_id].update_state(state)
                self._map_widget.update_robot(robot_id, state)
            self.statusBar().showMessage(
                f'Robot #{robot_id} 위치 재조정 완료'
            )

    def _handle_status(self, data: dict):
        robot_id = str(data.get('robot_id', ''))
        if not robot_id:
            return

        self._last_status_time[robot_id] = time.monotonic()
        self._robot_states[robot_id] = data

        # 로봇 카드 갱신
        if robot_id in self._robot_cards:
            self._robot_cards[robot_id].update_state(data)

        # 맵 갱신
        self._map_widget.update_robot(robot_id, data)

        # 카메라 bbox 갱신
        bbox = data.get('bbox')
        if bbox:
            self._camera_panel.update_bbox(robot_id, bbox)

        # 셀렉터 버튼 색상 갱신
        self._update_selector_buttons()

        # 상세 다이얼로그 상태 갱신
        dlg = self._detail_dialogs.get(robot_id)
        if dlg and dlg.isVisible():
            dlg.update_state(data)

    def _handle_staff_call(self, data: dict):
        robot_id = str(data.get('robot_id', ''))
        event_type = data.get('event', '')
        timestamp = data.get('timestamp', '')
        self._staff_panel.add_call(robot_id, event_type, timestamp)
        self.statusBar().showMessage(
            f'스태프 호출: Robot #{robot_id} [{event_type}]'
        )

    def _handle_staff_resolved(self, data: dict):
        robot_id = str(data.get('robot_id', ''))
        self._staff_panel.mark_resolved(robot_id)

    def _handle_event(self, data: dict):
        robot_id = str(data.get('robot_id', ''))
        event_type = data.get('event_type', '')
        detail = data.get('detail', '')
        timestamp = data.get('timestamp', '')
        self._event_log_panel.add_event(robot_id, event_type, detail, timestamp)

    def _handle_goto_rejected(self, data: dict):
        robot_id = str(data.get('robot_id', ''))
        QMessageBox.warning(
            self,
            'admin_goto 거부됨',
            f'Robot #{robot_id} 이동 명령이 거부되었습니다.\n'
            '로봇이 IDLE 상태인지 확인하세요.',
        )

    # ------------------------------------------------------------------
    # 맵 클릭 → admin_goto 흐름
    # ------------------------------------------------------------------

    def _update_pending_banner(self):
        """#6: 글로벌 pending actions 배너 + #1: 맵 오버레이 갱신."""
        parts = []
        if self._goto_pending_robot:
            parts.append(f'#{self._goto_pending_robot} 이동 명령 대기')
        if self._position_adjustment_pending_robot:
            parts.append(f'#{self._position_adjustment_pending_robot} 위치 재조정 대기')
        if parts:
            self._lbl_pending.setText('  |  '.join(parts) + '  — 맵을 클릭하세요')
            self._lbl_pending.show()
            self._map_widget.set_pending_overlay(
                '  |  '.join(parts) + '  — 맵을 클릭하세요'
            )
        else:
            self._lbl_pending.hide()
            self._map_widget.set_pending_overlay(None)

    def _on_goto_mode_activated(self, robot_id: str):
        """[이동 명령] 버튼 클릭 — 맵 클릭 대기 모드 진입/취소."""
        # 위치 재조정 대기 상태 해제
        if self._position_adjustment_pending_robot is not None:
            prev = self._position_adjustment_pending_robot
            self._position_adjustment_pending_robot = None
            if prev in self._robot_cards:
                self._robot_cards[prev].set_position_adjustment_pending(False)

        if not robot_id:
            self._goto_pending_robot = None
            self.statusBar().showMessage('이동 명령 취소')
            self._update_pending_banner()
            return

        # 다른 카드의 대기 상태 해제
        for rid, card in self._robot_cards.items():
            if rid != robot_id:
                card.set_goto_pending(False)

        self._goto_pending_robot = robot_id
        self.statusBar().showMessage(
            f'Robot #{robot_id} — 맵에서 목적지를 클릭하세요'
        )
        self._update_pending_banner()

    def _on_position_adjustment_mode_activated(self, robot_id: str):
        """[위치 재조정] 버튼 클릭 — 맵 클릭 대기 모드 진입/취소."""
        # 이동 명령 대기 상태 해제
        if self._goto_pending_robot is not None:
            prev = self._goto_pending_robot
            self._goto_pending_robot = None
            if prev in self._robot_cards:
                self._robot_cards[prev].set_goto_pending(False)

        if not robot_id:
            self._position_adjustment_pending_robot = None
            self.statusBar().showMessage('위치 재조정 취소')
            self._update_pending_banner()
            return

        # 다른 카드의 대기 상태 해제
        for rid, card in self._robot_cards.items():
            if rid != robot_id:
                card.set_position_adjustment_pending(False)

        self._position_adjustment_pending_robot = robot_id
        if robot_id in self._robot_cards:
            self._robot_cards[robot_id].set_position_adjustment_pending(True)
        self.statusBar().showMessage(
            f'Robot #{robot_id} — 맵에서 재조정할 위치를 클릭하세요'
        )
        self._update_pending_banner()

    def _on_map_clicked(self, x: float, y: float, theta: float):
        """맵 클릭+드래그: 대기 중인 로봇에 admin_goto(위치+방향) 전송."""
        import math as _math

        # 위치 재조정
        tr = self._position_adjustment_pending_robot
        if tr is not None:
            reply = QMessageBox.question(
                self, '위치 재조정 확인',
                f'Robot #{tr} 위치를 ({x:.3f}, {y:.3f})로 재조정하시겠습니까?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            payload = {
                'cmd': 'admin_position_adjustment',
                'robot_id': tr,
                'x': round(x, 4),
                'y': round(y, 4),
                'theta': round(theta, 4),
            }
            self._tcp.send(payload)
            self.statusBar().showMessage(
                f'Robot #{tr} → 위치 재조정 '
                f'({x:.3f}, {y:.3f}, {_math.degrees(theta):.0f}°) 전송'
            )
            self._position_adjustment_pending_robot = None
            if tr in self._robot_cards:
                self._robot_cards[tr].set_position_adjustment_pending(False)
            self._update_pending_banner()
            return

        rid = self._goto_pending_robot
        if rid is None:
            return

        state = self._robot_states.get(rid, {})
        if state.get('mode') != 'IDLE':
            self.statusBar().showMessage(
                f'Robot #{rid} 이 IDLE 상태가 아닙니다 (현재: {state.get("mode")})'
            )
            return

        reply = QMessageBox.question(
            self, '이동 명령 확인',
            f'Robot #{rid}를 ({x:.3f}, {y:.3f})로 이동시키겠습니까?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        payload = {
            'cmd': 'admin_goto',
            'robot_id': rid,
            'x': round(x, 4),
            'y': round(y, 4),
            'theta': round(theta, 4),
        }
        self._tcp.send(payload)
        self.statusBar().showMessage(
            f'Robot #{rid} → 이동 명령 ({x:.3f}, {y:.3f}, {_math.degrees(theta):.0f}°) 전송'
        )

        # 대기 상태 해제
        self._goto_pending_robot = None
        if rid in self._robot_cards:
            self._robot_cards[rid].set_goto_pending(False)
        self._update_pending_banner()

    # ------------------------------------------------------------------
    # 전체 로봇 제어
    # ------------------------------------------------------------------

    def _send_all(self, cmd: str, value: str):
        """모든 로봇에 동일한 명령 전송 (상태 조건 체크 포함)."""
        from .robot_card import _WAITING_MODES, _RETURNING_MODES
        allowed = {
            'WAITING': _WAITING_MODES,
            'RETURNING': _RETURNING_MODES,
        }
        valid_modes = allowed.get(value)
        targets = []
        skipped = []
        for rid in self._robot_ids:
            mode = self._robot_states.get(rid, {}).get('mode', 'OFFLINE')
            if valid_modes and mode in valid_modes:
                targets.append(rid)
            else:
                skipped.append(rid)

        if not targets:
            self.statusBar().showMessage(
                f'전체 {value}: 전환 가능한 로봇이 없습니다'
            )
            return

        label = '대기' if value == 'WAITING' else '복귀'
        names = ', '.join(f'#{r}' for r in targets)
        reply = QMessageBox.question(
            self, f'전체 {label} 확인',
            f'{names} → {value} 전환하시겠습니까?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        for rid in targets:
            payload = {'cmd': cmd, 'robot_id': rid, 'value': value}
            self._tcp.send(payload)

        msg = f'전체 {label}: {names} 전송 완료'
        if skipped:
            msg += f' (제외: {", ".join(f"#{s}" for s in skipped)})'
        self.statusBar().showMessage(msg)

    # ------------------------------------------------------------------
    # 로봇 카드 클릭 → 상세 다이얼로그
    # ------------------------------------------------------------------

    def _on_card_clicked(self, robot_id: str):
        dlg = self._detail_dialogs.get(robot_id)
        if dlg and dlg.isVisible():
            dlg.activateWindow()
            return
        dlg = RobotDetailDialog(robot_id, self._rest_base, parent=self)
        if robot_id in self._robot_states:
            dlg.update_state(self._robot_states[robot_id])
        self._detail_dialogs[robot_id] = dlg
        dlg.show()

    # ------------------------------------------------------------------
    # 명령 전송
    # ------------------------------------------------------------------

    def _on_command_requested(self, robot_id: str, payload: dict):
        ok = self._tcp.send(payload)
        if not ok:
            QMessageBox.warning(
                self,
                '전송 실패',
                f'Robot #{robot_id} 명령 전송 실패.\nTCP 연결 상태를 확인하세요.',
            )
        else:
            self.statusBar().showMessage(
                f"Robot #{robot_id} → {payload.get('cmd', '?')} 전송 완료"
            )

    def _on_guide_requested(self, robot_id: str):
        """카드의 [안내 이동] 클릭 — 구역 선택 다이얼로그를 띄우고 navigate_to 전송."""
        state = self._robot_states.get(robot_id, {})
        if state.get('mode') != 'IDLE':
            QMessageBox.information(
                self, '안내 이동 불가',
                f"Robot #{robot_id} 는 현재 {state.get('mode')} 상태입니다. "
                'IDLE 상태에서만 안내 이동을 시작할 수 있습니다.',
            )
            return

        dlg = ZoneSelectDialog(self._rest_base, robot_id, parent=self)
        from PyQt5.QtWidgets import QDialog
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        zone = dlg.selected_zone()
        if not zone:
            return

        payload = {
            'cmd': 'navigate_to',
            'robot_id': robot_id,
            'zone_id': int(zone['zone_id']),
            'x': float(zone['x']),
            'y': float(zone['y']),
            'theta': float(zone.get('theta', 0.0)),
        }
        if self._tcp.send(payload):
            self.statusBar().showMessage(
                f"Robot #{robot_id} → 안내 이동 [{zone['zone_name']}] 전송"
            )
        else:
            QMessageBox.warning(
                self, '전송 실패',
                f'Robot #{robot_id} 안내 이동 명령 전송 실패.',
            )

    def _on_resolve_requested(self, robot_id: str):
        payload = {'cmd': 'staff_resolved', 'robot_id': robot_id}
        self._tcp.send(payload)
        self.statusBar().showMessage(f'Robot #{robot_id} 잠금 해제 전송')

    # ------------------------------------------------------------------
    # 이벤트 로그 행 클릭
    # ------------------------------------------------------------------

    def _on_event_row_clicked(self, robot_id: str):
        self.statusBar().showMessage(f'Robot #{robot_id} 이벤트 선택됨')

    # ------------------------------------------------------------------
    # OFFLINE 감지
    # ------------------------------------------------------------------

    def _check_offline(self):
        now = time.monotonic()
        for robot_id in self._robot_ids:
            last = self._last_status_time.get(robot_id)
            # #7: 마지막 수신 경과 시간 카드에 전달
            if robot_id in self._robot_cards:
                if last is not None:
                    self._robot_cards[robot_id].update_last_seen(now - last)
                else:
                    self._robot_cards[robot_id].update_last_seen(-1)
            if last is None:
                continue
            if now - last > OFFLINE_TIMEOUT_SEC:
                state = dict(self._robot_states.get(robot_id, {}))
                if state.get('mode') != 'OFFLINE':
                    state['mode'] = 'OFFLINE'
                    self._robot_states[robot_id] = state
                    if robot_id in self._robot_cards:
                        self._robot_cards[robot_id].update_state(state)
                    self._map_widget.update_robot(robot_id, state)
        self._update_selector_buttons()

    # ------------------------------------------------------------------
    # 카메라 패널 토글
    # ------------------------------------------------------------------

    def _toggle_camera_panel(self):
        if self._camera_panel.isVisible():
            self._camera_panel.hide_panel()
        else:
            self._camera_panel.show_panel()

    # ------------------------------------------------------------------
    # 종료 처리
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self._tcp.stop()
        super().closeEvent(event)

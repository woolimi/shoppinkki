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

"""RobotCard — 로봇 1대의 상태 표시 + 명령 버튼 위젯.

표시 항목:
    - 모드 뱃지 (색상 구분)
    - 배터리 바 (QProgressBar, 20% 이하 빨강)
    - 활성 사용자 ID
    - 좌표 (pos_x, pos_y)

상태 전환 버튼 (현재 모드에 따라 활성화):
    [대기]  → mode WAITING       (TRACKING, TRACKING_CHECKOUT, SEARCHING)
    [추종]  → resume_tracking    (WAITING, SEARCHING)
    [복귀]  → mode RETURNING     (TRACKING, TRACKING_CHECKOUT, WAITING, SEARCHING)

관제 명령 버튼:
    [강제 종료] → force_terminate  (CHARGING·OFFLINE·HALTED·LOCKED 제외)
    [이동 명령] → admin_goto       (IDLE만, 맵 클릭 후 활성화)
    [잠금 해제] → staff_resolved   (is_locked_return=True 또는 HALTED)
    [위치 초기화] → init_pose      (CHARGING·IDLE만, Gazebo/AMCL 초기 위치 설정)

시그널:
    command_requested = pyqtSignal(str, dict)  # robot_id, payload
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

MODE_COLORS = {
    'CHARGING': '#808080',
    'IDLE': '#4a90d9',
    'TRACKING': '#27ae60',
    'TRACKING_CHECKOUT': '#1abc9c',
    'GUIDING': '#f39c12',
    'SEARCHING': '#e67e22',
    'WAITING': '#3498db',
    'LOCKED': '#e74c3c',
    'RETURNING': '#9b59b6',
    'HALTED': '#e74c3c',
    'OFFLINE': '#aaaaaa',
}

# force_terminate 비활성 모드
_FORCE_TERMINATE_DISABLED = {'CHARGING', 'OFFLINE', 'HALTED', 'LOCKED'}
# 상태 전환 버튼 활성 조건
_WAITING_MODES = {'TRACKING', 'TRACKING_CHECKOUT', 'SEARCHING'}
_RESUME_MODES = {'WAITING', 'SEARCHING'}
_RETURNING_MODES = {'TRACKING', 'TRACKING_CHECKOUT', 'WAITING', 'SEARCHING'}
# 위치 초기화 가능 모드 (시뮬/실물 AMCL 초기 위치 설정)
_INIT_POSE_MODES = {'CHARGING', 'IDLE'}


class RobotCard(QFrame):
    """로봇 카드 위젯."""

    command_requested = pyqtSignal(str, dict)
    card_clicked = pyqtSignal(str)  # robot_id

    def __init__(self, robot_id: str, parent=None):
        super().__init__(parent)
        self._robot_id = robot_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._current_state: dict = {}
        self._goto_pending = False  # 맵 클릭 대기 상태
        self._pending_goto_coords: tuple[float, float] | None = None

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.setMinimumWidth(260)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 헤더: robot_id + 모드 뱃지
        header_layout = QHBoxLayout()
        self._lbl_robot_id = QLabel(f'Robot #{self._robot_id}')
        self._lbl_robot_id.setStyleSheet('font-weight: bold; font-size: 14px;')
        header_layout.addWidget(self._lbl_robot_id)
        header_layout.addStretch()
        self._lbl_mode = QLabel('OFFLINE')
        self._lbl_mode.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_mode.setFixedWidth(130)
        self._lbl_mode.setStyleSheet(
            'border-radius: 4px; padding: 2px 6px; font-weight: bold; '
            'color: white; background-color: #aaaaaa;'
        )
        header_layout.addWidget(self._lbl_mode)
        layout.addLayout(header_layout)

        # 배터리 바
        batt_layout = QHBoxLayout()
        batt_layout.addWidget(QLabel('배터리:'))
        self._progress_battery = QProgressBar()
        self._progress_battery.setRange(0, 100)
        self._progress_battery.setValue(0)
        self._progress_battery.setTextVisible(True)
        self._progress_battery.setFixedHeight(16)
        batt_layout.addWidget(self._progress_battery)
        layout.addLayout(batt_layout)

        # 사용자 / 좌표
        self._lbl_user = QLabel('사용자: -')
        self._lbl_pos = QLabel('위치: (-, -)')
        layout.addWidget(self._lbl_user)
        layout.addWidget(self._lbl_pos)

        # 상태 전환 버튼 행
        trans_layout = QHBoxLayout()
        self._btn_waiting = QPushButton('대기')
        self._btn_waiting.setToolTip('WAITING 전환')
        self._btn_waiting.clicked.connect(self._on_waiting)

        self._btn_resume = QPushButton('추종')
        self._btn_resume.setToolTip('resume_tracking')
        self._btn_resume.clicked.connect(self._on_resume)

        self._btn_returning = QPushButton('복귀')
        self._btn_returning.setToolTip('RETURNING 전환')
        self._btn_returning.clicked.connect(self._on_returning)

        for btn in (self._btn_waiting, self._btn_resume, self._btn_returning):
            trans_layout.addWidget(btn)
        layout.addLayout(trans_layout)

        # 관제 명령 버튼 행
        cmd_layout = QHBoxLayout()
        self._btn_force_terminate = QPushButton('강제 종료')
        self._btn_force_terminate.setToolTip('force_terminate')
        self._btn_force_terminate.setStyleSheet('color: #c0392b; font-weight: bold;')
        self._btn_force_terminate.clicked.connect(self._on_force_terminate)

        self._btn_admin_goto = QPushButton('이동 명령')
        self._btn_admin_goto.setToolTip('admin_goto (맵 클릭 후 활성화)')
        self._btn_admin_goto.clicked.connect(self._on_admin_goto)

        self._btn_staff_resolved = QPushButton('잠금 해제')
        self._btn_staff_resolved.setToolTip('staff_resolved')
        self._btn_staff_resolved.setStyleSheet('color: #8e44ad; font-weight: bold;')
        self._btn_staff_resolved.clicked.connect(self._on_staff_resolved)

        for btn in (self._btn_force_terminate, self._btn_admin_goto, self._btn_staff_resolved):
            cmd_layout.addWidget(btn)
        layout.addLayout(cmd_layout)

        # 위치 초기화 버튼 행
        init_layout = QHBoxLayout()
        self._btn_init_pose = QPushButton('위치 초기화')
        self._btn_init_pose.setToolTip('AMCL 초기 위치 설정 (CHARGING·IDLE 상태에서만 활성화)')
        self._btn_init_pose.setStyleSheet('color: #2980b9;')
        self._btn_init_pose.clicked.connect(self._on_init_pose)
        init_layout.addStretch()
        init_layout.addWidget(self._btn_init_pose)
        layout.addLayout(init_layout)

        self._update_button_states()

    def update_state(self, state: dict):
        """상태 딕셔너리로 카드 갱신."""
        self._current_state = state
        mode = state.get('mode', 'OFFLINE')
        battery = state.get('battery', 0)
        user_id = state.get('active_user_id') or '-'
        pos_x = state.get('pos_x', 0.0)
        pos_y = state.get('pos_y', 0.0)
        is_locked_return = state.get('is_locked_return', False)

        # 모드 뱃지
        follow_disabled = state.get('follow_disabled', False)
        color = MODE_COLORS.get(mode, '#aaaaaa')
        mode_text = f'SIM | {mode}' if follow_disabled else mode
        self._lbl_mode.setText(mode_text)
        self._lbl_mode.setStyleSheet(
            f'border-radius: 4px; padding: 2px 6px; font-weight: bold; '
            f'color: white; background-color: {color};'
        )

        # 카드 테두리 (HALTED: 빨간, is_locked_return: 주황, 기본: 없음)
        if mode == 'HALTED':
            self.setStyleSheet('QFrame { border: 3px solid #e74c3c; border-radius: 6px; }')
        elif is_locked_return:
            self.setStyleSheet('QFrame { border: 3px solid #e67e22; border-radius: 6px; }')
        else:
            self.setStyleSheet('')

        # 배터리 바
        self._progress_battery.setValue(int(battery))
        if battery <= 20:
            self._progress_battery.setStyleSheet(
                'QProgressBar::chunk { background-color: #e74c3c; }'
            )
        else:
            self._progress_battery.setStyleSheet(
                'QProgressBar::chunk { background-color: #27ae60; }'
            )

        self._lbl_user.setText(f'사용자: {user_id}')
        self._lbl_pos.setText(f'위치: ({pos_x:.2f}, {pos_y:.2f})')

        self._update_button_states()

    def set_goto_pending(self, pending: bool):
        """맵 클릭 대기 상태 설정."""
        self._goto_pending = pending
        if pending:
            self._btn_admin_goto.setText('클릭 대기...')
            self._btn_admin_goto.setStyleSheet('color: #e67e22; font-weight: bold;')
        else:
            self._btn_admin_goto.setText('이동 명령')
            self._btn_admin_goto.setStyleSheet('')
        self._update_button_states()

    def set_goto_coords(self, x: float, y: float):
        """맵 클릭으로 좌표 저장."""
        self._pending_goto_coords = (x, y)
        self._goto_pending = False
        self._btn_admin_goto.setText('이동 명령')
        self._update_button_states()

    def _update_button_states(self):
        mode = self._current_state.get('mode', 'OFFLINE')
        is_locked_return = self._current_state.get('is_locked_return', False)

        self._btn_waiting.setEnabled(mode in _WAITING_MODES)
        self._btn_resume.setEnabled(mode in _RESUME_MODES)
        self._btn_returning.setEnabled(mode in _RETURNING_MODES)
        self._btn_force_terminate.setEnabled(mode not in _FORCE_TERMINATE_DISABLED)
        # admin_goto: IDLE + 좌표 준비됨
        self._btn_admin_goto.setEnabled(
            mode == 'IDLE' and self._pending_goto_coords is not None
        )
        # staff_resolved: HALTED 또는 is_locked_return
        self._btn_staff_resolved.setEnabled(
            mode == 'HALTED' or is_locked_return
        )
        # init_pose: CHARGING 또는 IDLE (시뮬 Gazebo / 실물 AMCL 초기화용)
        self._btn_init_pose.setEnabled(mode in _INIT_POSE_MODES)

    def _send_cmd(self, payload: dict):
        self.command_requested.emit(self._robot_id, payload)

    def _on_waiting(self):
        self._send_cmd({'cmd': 'mode', 'robot_id': self._robot_id, 'value': 'WAITING'})

    def _on_resume(self):
        self._send_cmd({'cmd': 'resume_tracking', 'robot_id': self._robot_id})

    def _on_returning(self):
        self._send_cmd({'cmd': 'mode', 'robot_id': self._robot_id, 'value': 'RETURNING'})

    def _on_force_terminate(self):
        reply = QMessageBox.question(
            self,
            '강제 종료 확인',
            f'Robot #{self._robot_id} 세션을 강제 종료하시겠습니까?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._send_cmd({'cmd': 'force_terminate', 'robot_id': self._robot_id})

    def _on_admin_goto(self):
        if self._pending_goto_coords is None:
            return
        x, y = self._pending_goto_coords
        self._send_cmd({
            'cmd': 'admin_goto',
            'robot_id': self._robot_id,
            'x': x,
            'y': y,
            'theta': 0.0,
        })
        self._pending_goto_coords = None
        self._update_button_states()

    def _on_staff_resolved(self):
        reply = QMessageBox.question(
            self,
            '잠금 해제 확인',
            f'Robot #{self._robot_id} 잠금을 해제하시겠습니까?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._send_cmd({'cmd': 'staff_resolved', 'robot_id': self._robot_id})

    def _on_init_pose(self):
        reply = QMessageBox.question(
            self,
            '위치 초기화 확인',
            f'Robot #{self._robot_id} AMCL 초기 위치를 설정하시겠습니까?\n'
            f'(맵 상 기본 출발 위치로 초기화)',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._send_cmd({'cmd': 'init_pose', 'robot_id': self._robot_id})

    def mousePressEvent(self, event):
        self.card_clicked.emit(self._robot_id)
        super().mousePressEvent(event)

    @property
    def robot_id(self) -> str:
        return self._robot_id

    @property
    def current_mode(self) -> str:
        return self._current_state.get('mode', 'OFFLINE')

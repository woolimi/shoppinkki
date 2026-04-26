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
    [이동 명령] → goto_mode_activated 시그널 emit (IDLE만)
                  버튼 클릭 → 맵 클릭 대기 모드 진입/취소 토글
                  맵 클릭은 MainWindow에서 처리하여 admin_goto 전송
    [잠금 해제] → staff_resolved   (is_locked_return=True 또는 HALTED)
    [위치 재조정] → admin_position_adjustment 맵 클릭
                  (IDLE / TRACKING / TRACKING_CHECKOUT; 후자는 확인 대화상자)
    [위치 초기화] → init_pose      (CHARGING·IDLE만, Gazebo/AMCL 초기 위치 설정)

시그널:
    command_requested = pyqtSignal(str, dict)  # robot_id, payload
    goto_mode_activated = pyqtSignal(str)       # robot_id (빈 문자열 = 취소)
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
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
_RETURNING_MODES = {'TRACKING', 'TRACKING_CHECKOUT', 'WAITING', 'SEARCHING', 'IDLE'}
# 위치 초기화 가능 모드 (시뮬/실물 AMCL 초기 위치 설정)
_INIT_POSE_MODES = {'CHARGING', 'IDLE'}
# OFFLINE 판정 기준 (main_window와 동기화)
OFFLINE_TIMEOUT_SEC = 30
# admin_position_adjustment — 맵 좌표 기준 위치 재조정 (시뮬/실물 공통)
_POSITION_ADJUSTMENT_BTN_LABEL = '위치 재조정'
_POSITION_ADJUSTMENT_MODES = frozenset({'IDLE', 'TRACKING', 'TRACKING_CHECKOUT'})


class RobotCard(QFrame):
    """로봇 카드 위젯."""

    command_requested = pyqtSignal(str, dict)
    card_clicked = pyqtSignal(str)       # robot_id
    goto_mode_activated = pyqtSignal(str)  # robot_id or '' (cancel)
    position_adjustment_mode_activated = pyqtSignal(str)  # robot_id or '' (cancel)
    guide_requested = pyqtSignal(str)    # robot_id — zone 선택 다이얼로그 요청

    def __init__(self, robot_id: str, parent=None):
        super().__init__(parent)
        self._robot_id = robot_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._current_state: dict = {}
        self._goto_pending = False  # 맵 클릭 대기 상태
        self._position_adjustment_pending = False  # 위치 재조정 맵 클릭 대기 상태

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

            # 사용자 / 좌표 / 마지막 수신
        self._lbl_user = QLabel('사용자: -')
        self._lbl_pos = QLabel('위치: (-, -)')
        self._lbl_last_seen = QLabel('')
        self._lbl_last_seen.setStyleSheet('color: #888; font-size: 11px;')
        layout.addWidget(self._lbl_user)
        layout.addWidget(self._lbl_pos)
        layout.addWidget(self._lbl_last_seen)

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

        # 관제/유틸 버튼 (3x2 그리드)
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

        self._btn_position_adjustment = QPushButton(_POSITION_ADJUSTMENT_BTN_LABEL)
        self._btn_position_adjustment.setToolTip(
            '맵 클릭 후 위치 재조정 (admin_position_adjustment). '
            'TRACKING 계열에서는 확인 후 AMCL/Gazebo 좌표 반영'
        )
        self._btn_position_adjustment.setStyleSheet('color: #d35400; font-weight: bold;')
        self._btn_position_adjustment.clicked.connect(self._on_position_adjustment)
        self._btn_init_pose = QPushButton('위치 초기화')
        self._btn_init_pose.setToolTip('AMCL 초기 위치 설정 (CHARGING·IDLE 상태에서만 활성화)')
        self._btn_init_pose.setStyleSheet('color: #2980b9;')
        self._btn_init_pose.clicked.connect(self._on_init_pose)

        self._btn_guide = QPushButton('안내 이동')
        self._btn_guide.setToolTip('구역을 선택해 GUIDING 시작 (IDLE 상태에서만)')
        self._btn_guide.setStyleSheet('color: #16a085; font-weight: bold;')
        self._btn_guide.clicked.connect(self._on_guide)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        # 1행: 강제종료 | 이동명령 | 잠금해제
        grid.addWidget(self._btn_force_terminate, 0, 0)
        grid.addWidget(self._btn_admin_goto, 0, 1)
        grid.addWidget(self._btn_staff_resolved, 0, 2)
        # 2행: 위치 재조정 | 안내 이동 | 위치 초기화
        grid.addWidget(self._btn_position_adjustment, 1, 0)
        grid.addWidget(self._btn_guide, 1, 1)
        grid.addWidget(self._btn_init_pose, 1, 2)
        layout.addLayout(grid)

        self._update_button_states()

    def _on_position_adjustment(self):
        """[위치 재조정] 버튼 클릭 — 맵 클릭 대기 모드 진입/취소."""
        self.set_goto_pending(False)

        if self._position_adjustment_pending:
            self._position_adjustment_pending = False
            self._btn_position_adjustment.setText(_POSITION_ADJUSTMENT_BTN_LABEL)
            self.position_adjustment_mode_activated.emit('')
            return

        mode = self._current_state.get('mode', 'OFFLINE')
        if mode in ('TRACKING', 'TRACKING_CHECKOUT') and not self._confirm_position_adjustment(mode):
            return

        self._position_adjustment_pending = True
        self._btn_position_adjustment.setText('취소')
        self.position_adjustment_mode_activated.emit(self._robot_id)

    def _confirm_position_adjustment(self, mode: str) -> bool:
        """추종·쇼핑 중 위치 재조정 확인 다이얼로그. Yes 응답 시 True."""
        reply = QMessageBox.question(
            self,
            '위치 재조정 (추종·쇼핑 중)',
            f'Robot #{self._robot_id} — 현재 상태: {mode}\n\n'
            '맵에서 선택한 좌표로 로컬라이제이션을 바꿉니다 '
            '(시뮬: Gazebo 자세 + AMCL, 실물: initialpose). '
            '이후에도 이 추정이 유지됩니다.\n\n'
            '추종·Nav2·장애물 회피와 어긋날 수 있습니다. 계속하시겠습니까?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

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
        batt_int = int(battery)
        self._progress_battery.setValue(batt_int)
        if battery <= 10:
            self._progress_battery.setStyleSheet(
                'QProgressBar::chunk { background-color: #e74c3c; }'
            )
            self._progress_battery.setFormat(f'{batt_int}% LOW')
        elif battery <= 20:
            self._progress_battery.setStyleSheet(
                'QProgressBar::chunk { background-color: #e67e22; }'
            )
            self._progress_battery.setFormat(f'{batt_int}%')
        else:
            self._progress_battery.setStyleSheet(
                'QProgressBar::chunk { background-color: #27ae60; }'
            )
            self._progress_battery.setFormat(f'{batt_int}%')

        self._lbl_user.setText(f'사용자: {user_id}')
        self._lbl_pos.setText(f'위치: ({pos_x:.2f}, {pos_y:.2f})')

        self._update_button_states()

    def set_goto_pending(self, pending: bool):
        """맵 클릭 대기 상태 설정."""
        self._goto_pending = pending
        if pending:
            self._btn_admin_goto.setText('취소')
            self._btn_admin_goto.setStyleSheet('color: #e67e22; font-weight: bold;')
        else:
            self._btn_admin_goto.setText('이동 명령')
            self._btn_admin_goto.setStyleSheet('')
        self._update_button_states()

    def set_position_adjustment_pending(self, pending: bool):
        """위치 재조정 맵 클릭 대기 상태 설정."""
        self._position_adjustment_pending = pending
        if pending:
            self._btn_position_adjustment.setText('취소')
        else:
            self._btn_position_adjustment.setText(_POSITION_ADJUSTMENT_BTN_LABEL)

    def update_last_seen(self, seconds_ago: float):
        """마지막 status 수신 이후 경과 시간 표시."""
        if seconds_ago < 0:
            self._lbl_last_seen.setText('')
            return
        sec = int(seconds_ago)
        if sec < 5:
            self._lbl_last_seen.setText('')
            self._lbl_last_seen.setStyleSheet('color: #888; font-size: 11px;')
        elif sec < OFFLINE_TIMEOUT_SEC:
            self._lbl_last_seen.setText(f'마지막 수신 {sec}초 전')
            self._lbl_last_seen.setStyleSheet('color: #e67e22; font-size: 11px;')
        else:
            self._lbl_last_seen.setText(f'응답 없음 ({sec}초)')
            self._lbl_last_seen.setStyleSheet('color: #e74c3c; font-size: 11px; font-weight: bold;')

    def reset_pending(self):
        """모든 pending 상태 초기화 (TCP 연결 끊김 시 호출)."""
        self._goto_pending = False
        self._btn_admin_goto.setText('이동 명령')
        self._btn_admin_goto.setStyleSheet('')
        self._position_adjustment_pending = False
        self._btn_position_adjustment.setText(_POSITION_ADJUSTMENT_BTN_LABEL)

    def _update_button_states(self):
        mode = self._current_state.get('mode', 'OFFLINE')
        is_locked_return = self._current_state.get('is_locked_return', False)

        # 활성/비활성 + 동적 tooltip
        self._btn_waiting.setEnabled(mode in _WAITING_MODES)
        if mode not in _WAITING_MODES:
            self._btn_waiting.setToolTip(f'WAITING 전환 (현재 {mode} — TRACKING/SEARCHING에서 가능)')
        else:
            self._btn_waiting.setToolTip('WAITING 전환')

        self._btn_resume.setEnabled(mode in _RESUME_MODES)
        if mode not in _RESUME_MODES:
            self._btn_resume.setToolTip(f'추종 재개 (현재 {mode} — WAITING/SEARCHING에서 가능)')
        else:
            self._btn_resume.setToolTip('추종 재개')

        self._btn_returning.setEnabled(mode in _RETURNING_MODES)
        if mode not in _RETURNING_MODES:
            self._btn_returning.setToolTip(f'복귀 (현재 {mode} — TRACKING/WAITING에서 가능)')
        else:
            self._btn_returning.setToolTip('충전소로 복귀')

        self._btn_force_terminate.setEnabled(mode not in _FORCE_TERMINATE_DISABLED)
        if mode in _FORCE_TERMINATE_DISABLED:
            self._btn_force_terminate.setToolTip(f'강제 종료 불가 (현재 {mode})')
        else:
            self._btn_force_terminate.setToolTip('세션 강제 종료')

        self._btn_admin_goto.setEnabled(mode == 'IDLE' or self._goto_pending)
        if mode != 'IDLE' and not self._goto_pending:
            self._btn_admin_goto.setToolTip(f'이동 명령 (현재 {mode} — IDLE에서만 가능)')
        else:
            self._btn_admin_goto.setToolTip('맵 클릭으로 목적지 지정')

        self._btn_position_adjustment.setEnabled(mode in _POSITION_ADJUSTMENT_MODES
                                                  or self._position_adjustment_pending)
        if mode not in _POSITION_ADJUSTMENT_MODES and not self._position_adjustment_pending:
            self._btn_position_adjustment.setToolTip(
                f'위치 재조정 불가 (현재 {mode} — IDLE/TRACKING에서 가능)')
        else:
            self._btn_position_adjustment.setToolTip('맵 클릭으로 위치 재조정')

        self._btn_staff_resolved.setEnabled(mode == 'HALTED' or is_locked_return)
        if not (mode == 'HALTED' or is_locked_return):
            self._btn_staff_resolved.setToolTip(f'잠금 해제 불가 (현재 {mode}, HALTED/LOCKED에서 가능)')
        else:
            self._btn_staff_resolved.setToolTip('잠금 해제')

        self._btn_init_pose.setEnabled(mode in _INIT_POSE_MODES)
        if mode not in _INIT_POSE_MODES:
            self._btn_init_pose.setToolTip(f'위치 초기화 불가 (현재 {mode} — CHARGING/IDLE에서 가능)')
        else:
            self._btn_init_pose.setToolTip('AMCL 초기 위치 설정')

        self._btn_guide.setEnabled(mode == 'IDLE')
        if mode != 'IDLE':
            self._btn_guide.setToolTip(f'안내 이동 불가 (현재 {mode} — IDLE에서만 가능)')
        else:
            self._btn_guide.setToolTip('구역 선택해서 안내 이동 시작')

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
        if self._goto_pending:
            # 이미 대기 중 → 취소
            self._goto_pending = False
            self._btn_admin_goto.setText('이동 명령')
            self._btn_admin_goto.setStyleSheet('')
            self.goto_mode_activated.emit('')
        else:
            # 대기 모드 진입
            self._goto_pending = True
            self._btn_admin_goto.setText('취소')
            self._btn_admin_goto.setStyleSheet('color: #e67e22; font-weight: bold;')
            self.goto_mode_activated.emit(self._robot_id)

    def _on_staff_resolved(self):
        reply = QMessageBox.question(
            self,
            '잠금 해제 확인',
            f'Robot #{self._robot_id} 잠금을 해제하시겠습니까?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._send_cmd({'cmd': 'staff_resolved', 'robot_id': self._robot_id})

    def _on_guide(self):
        # 다이얼로그는 REST 주소를 모르므로 MainWindow에 요청만 전달한다.
        self.guide_requested.emit(self._robot_id)

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

"""RobotPanel — displays real-time status for one robot."""

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QDialog, QFormLayout,
    QDoubleSpinBox, QDialogButtonBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette

MODE_COLORS = {
    'IDLE':        '#888888',
    'REGISTERING': '#3399ff',
    'TRACKING':    '#00cc44',
    'SEARCHING':   '#ffaa00',
    'WAITING':     '#aaaaaa',
    'ITEM_ADDING': '#9966ff',
    'GUIDING':     '#0066ff',
    'RETURNING':   '#ff6600',
    'ALARM':       '#ff2222',
    'OFFLINE':     '#444444',
}


class RobotPanel(QGroupBox):
    """Status card for a single robot."""

    def __init__(self, robot_id: str, bridge, parent=None):
        super().__init__(f'Robot #{robot_id}', parent)
        self._robot_id = robot_id
        self._bridge = bridge
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # --- Mode indicator ---
        mode_row = QHBoxLayout()
        self._mode_dot = QLabel('●')
        self._mode_dot.setStyleSheet('color: #888888; font-size: 18px;')
        self._mode_label = QLabel('OFFLINE')
        self._mode_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        mode_row.addWidget(self._mode_dot)
        mode_row.addWidget(self._mode_label)
        mode_row.addStretch()
        root.addLayout(mode_row)

        # --- Battery ---
        bat_row = QHBoxLayout()
        bat_row.addWidget(QLabel('배터리:'))
        self._battery_bar = QProgressBar()
        self._battery_bar.setRange(0, 100)
        self._battery_bar.setValue(0)
        self._battery_bar.setFixedHeight(14)
        bat_row.addWidget(self._battery_bar)
        self._battery_label = QLabel('0%')
        self._battery_label.setFixedWidth(36)
        bat_row.addWidget(self._battery_label)
        root.addLayout(bat_row)

        # --- Position ---
        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel('위치:'))
        self._pos_label = QLabel('(-.-- , -.--)')
        pos_row.addWidget(self._pos_label)
        pos_row.addStretch()
        root.addLayout(pos_row)

        # --- Alarm indicator ---
        self._alarm_label = QLabel('')
        self._alarm_label.setStyleSheet('color: #ff2222; font-weight: bold;')
        root.addWidget(self._alarm_label)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        self._btn_force = QPushButton('강제 종료')
        self._btn_force.clicked.connect(self._on_force_terminate)
        self._btn_goto = QPushButton('위치 호출')
        self._btn_goto.clicked.connect(self._on_goto)
        btn_row.addWidget(self._btn_force)
        btn_row.addWidget(self._btn_goto)
        root.addLayout(btn_row)

    def _connect_signals(self):
        self._bridge.robot_status_updated.connect(self._on_status)
        self._bridge.alarm_raised.connect(self._on_alarm)
        self._bridge.alarm_dismissed.connect(self._on_alarm_dismissed)
        self._bridge.robot_offline.connect(self._on_offline)
        self._bridge.robot_online.connect(self._on_online)

    # --- Signal handlers (Qt main thread) ---

    def _on_status(self, robot_id: str, status: dict):
        if robot_id != self._robot_id:
            return
        mode = status.get('mode', 'OFFLINE')
        battery = int(status.get('battery', 0))
        pos_x = float(status.get('pos_x', 0.0))
        pos_y = float(status.get('pos_y', 0.0))

        color = MODE_COLORS.get(mode, '#888888')
        self._mode_dot.setStyleSheet(f'color: {color}; font-size: 18px;')
        self._mode_label.setText(mode)
        self._battery_bar.setValue(battery)
        self._battery_label.setText(f'{battery}%')
        self._pos_label.setText(f'({pos_x:.2f} , {pos_y:.2f})')

        # Battery bar color
        if battery <= 20:
            bar_color = '#ff2222'
        elif battery <= 50:
            bar_color = '#ffaa00'
        else:
            bar_color = '#00cc44'
        self._battery_bar.setStyleSheet(
            f'QProgressBar::chunk {{ background-color: {bar_color}; }}'
        )

    def _on_alarm(self, robot_id: str, event_type: str, occurred_at: str):
        if robot_id != self._robot_id:
            return
        self._alarm_label.setText(f'⚠ {event_type}  {occurred_at}')

    def _on_alarm_dismissed(self, robot_id: str):
        if robot_id != self._robot_id:
            return
        self._alarm_label.setText('')

    def _on_offline(self, robot_id: str):
        if robot_id != self._robot_id:
            return
        self._mode_dot.setStyleSheet('color: #444444; font-size: 18px;')
        self._mode_label.setText('OFFLINE')

    def _on_online(self, robot_id: str):
        if robot_id != self._robot_id:
            return
        self._mode_label.setText('IDLE')

    # --- Button actions ---

    def _on_force_terminate(self):
        self._bridge.force_terminate(self._robot_id)

    def _on_goto(self):
        dlg = _GoToDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            x, y, theta = dlg.get_values()
            self._bridge.admin_goto(self._robot_id, x, y, theta)


class _GoToDialog(QDialog):
    """Dialog for entering admin_goto coordinates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('위치 호출')
        layout = QFormLayout(self)

        self._x = QDoubleSpinBox()
        self._x.setRange(-10.0, 10.0)
        self._x.setSingleStep(0.1)
        self._x.setDecimals(2)

        self._y = QDoubleSpinBox()
        self._y.setRange(-10.0, 10.0)
        self._y.setSingleStep(0.1)
        self._y.setDecimals(2)

        self._theta = QDoubleSpinBox()
        self._theta.setRange(-3.15, 3.15)
        self._theta.setSingleStep(0.1)
        self._theta.setDecimals(2)

        layout.addRow('X (m):', self._x)
        layout.addRow('Y (m):', self._y)
        layout.addRow('Theta (rad):', self._theta)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_values(self):
        return self._x.value(), self._y.value(), self._theta.value()

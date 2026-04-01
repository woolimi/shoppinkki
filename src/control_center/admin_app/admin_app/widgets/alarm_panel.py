"""AlarmPanel — shows active alarms with dismiss button."""

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QWidget,
)
from PyQt6.QtCore import Qt

ALARM_LABELS = {
    'THEFT':         '🚨 도난',
    'BATTERY_LOW':   '🔋 배터리 부족',
    'TIMEOUT':       '⏱ 타임아웃',
    'PAYMENT_ERROR': '💳 결제 오류',
}


class AlarmPanel(QGroupBox):
    """Panel listing active (unresolved) alarms."""

    def __init__(self, bridge, parent=None):
        super().__init__('알람', parent)
        self._bridge = bridge
        self._alarm_rows: dict[str, QWidget] = {}  # robot_id → row widget
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        root = QVBoxLayout(self)

        self._empty_label = QLabel('활성 알람 없음')
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet('color: #888888;')
        root.addWidget(self._empty_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_widget)
        root.addWidget(scroll)

    def _connect_signals(self):
        self._bridge.alarm_raised.connect(self._on_alarm)
        self._bridge.alarm_dismissed.connect(self._on_dismissed)

    def _on_alarm(self, robot_id: str, event_type: str, occurred_at: str):
        self._empty_label.setVisible(False)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 2, 4, 2)

        label_text = ALARM_LABELS.get(event_type, event_type)
        lbl = QLabel(f'Robot #{robot_id}  {label_text}  {occurred_at[:19]}')
        lbl.setStyleSheet('color: #ff4444;')
        row_layout.addWidget(lbl)
        row_layout.addStretch()

        btn = QPushButton('해제')
        btn.setFixedWidth(48)
        btn.clicked.connect(lambda: self._bridge.dismiss_alarm(robot_id))
        row_layout.addWidget(btn)

        self._list_layout.insertWidget(self._list_layout.count() - 1, row)
        self._alarm_rows[robot_id] = row

    def _on_dismissed(self, robot_id: str):
        row = self._alarm_rows.pop(robot_id, None)
        if row:
            row.setParent(None)
            row.deleteLater()
        if not self._alarm_rows:
            self._empty_label.setVisible(True)

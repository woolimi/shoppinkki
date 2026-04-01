"""EventLogPanel — scrollable recent event log."""

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import Qt

MAX_ROWS = 200

EVENT_ICONS = {
    'SESSION_START':    '🟢',
    'SESSION_END':      '🔵',
    'FORCE_TERMINATE':  '🔴',
    'ALARM_RAISED':     '🚨',
    'ALARM_DISMISSED':  '✅',
    'PAYMENT_SUCCESS':  '💳',
    'PAYMENT_FAIL':     '❌',
    'MODE_CHANGE':      '🔄',
    'OFFLINE':          '⚫',
    'ONLINE':           '⚪',
    'QUEUE_ADVANCE':    '➡',
}


class EventLogPanel(QGroupBox):
    """Scrollable real-time event log panel."""

    def __init__(self, bridge, parent=None):
        super().__init__('이벤트 로그', parent)
        self._bridge = bridge
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list)

    def _connect_signals(self):
        self._bridge.event_logged.connect(self._on_event)
        self._bridge.robot_offline.connect(
            lambda rid: self._add_row({'robot_id': rid, 'event_type': 'OFFLINE',
                                       'user_id': '', 'event_detail': '', 'occurred_at': ''})
        )
        self._bridge.robot_online.connect(
            lambda rid: self._add_row({'robot_id': rid, 'event_type': 'ONLINE',
                                       'user_id': '', 'event_detail': '', 'occurred_at': ''})
        )

    def _on_event(self, event_dict: dict):
        self._add_row(event_dict)

    def _add_row(self, event: dict):
        icon = EVENT_ICONS.get(event.get('event_type', ''), '•')
        ts = str(event.get('occurred_at', ''))[:19]
        robot = event.get('robot_id', '')
        etype = event.get('event_type', '')
        detail = event.get('event_detail', '') or ''
        user = event.get('user_id', '') or ''

        text = f"{icon} [{ts}] #{robot}"
        if user:
            text += f" ({user})"
        text += f"  {etype}"
        if detail:
            text += f"  — {detail}"

        item = QListWidgetItem(text)
        self._list.insertItem(0, item)

        # Keep list bounded
        while self._list.count() > MAX_ROWS:
            self._list.takeItem(self._list.count() - 1)

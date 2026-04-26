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

"""EventLogPanel — 운용 이벤트 실시간 로그.

표시: 최신 이벤트 상단. 최대 200건.
필터 버튼: [전체] [스태프호출] [세션] [이벤트]
행 클릭 → row_clicked(robot_id) pyqtSignal

이벤트 배경색:
    SESSION_START/END: #d4edda, FORCE_TERMINATE: #fff3cd,
    LOCKED: #f8d7da, HALTED: #ffe5d0, STAFF_RESOLVED: #e2e3e5,
    PAYMENT_SUCCESS: #d4edda, OFFLINE: #dddddd, ONLINE: #d4edda
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

MAX_ROWS = 200

_EVENT_COLORS = {
    'SESSION_START': '#d4edda',
    'SESSION_END': '#d4edda',
    'FORCE_TERMINATE': '#fff3cd',
    'LOCKED': '#f8d7da',
    'HALTED': '#ffe5d0',
    'STAFF_RESOLVED': '#e2e3e5',
    'PAYMENT_SUCCESS': '#d4edda',
    'MODE_CHANGE': '#f0f0f0',
    'OFFLINE': '#dddddd',
    'ONLINE': '#d4edda',
}

_FILTER_GROUPS = {
    '전체': None,
    '스태프호출': {'LOCKED', 'HALTED', 'STAFF_RESOLVED'},
    '세션': {'SESSION_START', 'SESSION_END', 'FORCE_TERMINATE'},
    '이벤트': {'PAYMENT_SUCCESS', 'MODE_CHANGE', 'ONLINE', 'OFFLINE'},
}

_COLUMNS = ['시간', '로봇', '이벤트', '상세']


class EventLogPanel(QWidget):
    """이벤트 로그 패널."""

    row_clicked = pyqtSignal(str)  # robot_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_rows: list[dict] = []  # {'robot_id', 'event_type', 'detail', 'timestamp'}
        self._current_filter: str = '전체'

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 헤더
        header_layout = QHBoxLayout()
        header_lbl = QLabel('이벤트 로그')
        header_lbl.setStyleSheet(
            'background-color: #2c3e50; color: white; font-weight: bold; padding: 4px 8px;'
        )
        header_layout.addWidget(header_lbl)
        header_layout.addStretch()

        # 필터 버튼
        self._filter_buttons: dict[str, QPushButton] = {}
        for label in _FILTER_GROUPS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedWidth(72)
            btn.clicked.connect(lambda checked, lbl=label: self._apply_filter(lbl))
            header_layout.addWidget(btn)
            self._filter_buttons[label] = btn
        self._filter_buttons['전체'].setChecked(True)

        layout.addLayout(header_layout)

        # 테이블
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        self._table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self._table)

    def add_event(self, robot_id: str, event_type: str, detail: str, timestamp: str):
        """이벤트 추가 (최신 상단 삽입). 매번 테이블 전체를 다시 그리지 않고
        단일 행만 prepend한다 — 200건 누적 후 add_event마다의 비용이 O(1)."""
        row_data = {
            'robot_id': robot_id,
            'event_type': event_type,
            'detail': detail,
            'timestamp': timestamp,
        }
        self._all_rows.insert(0, row_data)
        if len(self._all_rows) > MAX_ROWS:
            self._all_rows = self._all_rows[:MAX_ROWS]

        allowed = _FILTER_GROUPS.get(self._current_filter)
        if allowed is not None and event_type not in allowed:
            return  # 현재 필터에 안 맞으면 캐시에만 두고 테이블 변경 없음

        self._table.insertRow(0)
        self._set_row_items(0, row_data)
        # 표시 행도 MAX_ROWS로 cap
        while self._table.rowCount() > MAX_ROWS:
            self._table.removeRow(self._table.rowCount() - 1)

    def load_initial(self, events: list):
        """초기 이벤트 목록 일괄 로드."""
        for evt in events:
            self._all_rows.append({
                'robot_id': evt.get('robot_id', ''),
                'event_type': evt.get('event_type', ''),
                'detail': evt.get('detail', ''),
                'timestamp': evt.get('timestamp', ''),
            })
        self._all_rows = self._all_rows[:MAX_ROWS]
        self._rebuild_table()

    def _apply_filter(self, filter_type: str):
        self._current_filter = filter_type
        for lbl, btn in self._filter_buttons.items():
            btn.setChecked(lbl == filter_type)
        self._rebuild_table()

    def _set_row_items(self, table_row: int, row_data: dict) -> None:
        """단일 테이블 행 셀 설정 — _rebuild_table과 add_event가 공유."""
        event_type = row_data['event_type']
        bg = QBrush(QColor(_EVENT_COLORS.get(event_type, '#ffffff')))
        fg = QBrush(QColor('#222222'))
        items = [
            QTableWidgetItem(row_data['timestamp']),
            QTableWidgetItem(f"Robot #{row_data['robot_id']}"),
            QTableWidgetItem(event_type),
            QTableWidgetItem(row_data['detail']),
        ]
        for col, item in enumerate(items):
            item.setBackground(bg)
            item.setForeground(fg)
            self._table.setItem(table_row, col, item)

    def _rebuild_table(self):
        allowed = _FILTER_GROUPS.get(self._current_filter)
        rows = self._all_rows
        if allowed is not None:
            rows = [r for r in rows if r['event_type'] in allowed]

        self._table.setRowCount(len(rows))
        for i, row_data in enumerate(rows):
            self._set_row_items(i, row_data)

    def _on_cell_clicked(self, row: int, col: int):
        robot_item = self._table.item(row, 1)
        if robot_item is None:
            return
        # "Robot #54" → "54"
        text = robot_item.text()
        robot_id = text.replace('Robot #', '').strip()
        self.row_clicked.emit(robot_id)

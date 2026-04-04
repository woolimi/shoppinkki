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

"""StaffCallPanel — LOCKED / HALTED 스태프 호출 목록.

항목 구성:
    Robot#54  LOCKED   12:34:05
    미결제 물건 있음   [잠금 해제]

이벤트 색상:
    LOCKED: #ffd6d6 (빨강), HALTED: #ffe5d0 (주황)
    처리됨: #e2e3e5 (회색) + "처리됨" 텍스트

시그널:
    resolve_requested = pyqtSignal(str)  # robot_id
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_EVENT_COLORS = {
    'LOCKED': '#ffd6d6',
    'HALTED': '#ffe5d0',
    'RESOLVED': '#e2e3e5',
}

_EVENT_DESCRIPTIONS = {
    'LOCKED': '미결제 물건 있음',
    'HALTED': '배터리 부족 — 즉시 처리 필요',
}


class _StaffCallItem(QFrame):
    """스태프 호출 항목 위젯."""

    resolve_clicked = pyqtSignal(str)  # robot_id

    def __init__(self, robot_id: str, event_type: str, timestamp: str, parent=None):
        super().__init__(parent)
        self._robot_id = robot_id
        self._event_type = event_type
        self._resolved = False

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._update_style()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        # 왼쪽: 로봇 ID, 이벤트 타입, 시간
        info_layout = QVBoxLayout()
        lbl_header = QLabel(f'Robot #{robot_id}  [{event_type}]  {timestamp}')
        lbl_header.setStyleSheet('font-weight: bold;')
        info_layout.addWidget(lbl_header)

        desc = _EVENT_DESCRIPTIONS.get(event_type, event_type)
        self._lbl_desc = QLabel(desc)
        info_layout.addWidget(self._lbl_desc)
        layout.addLayout(info_layout)

        layout.addStretch()

        # 오른쪽: 잠금 해제 버튼
        self._btn_resolve = QPushButton('잠금 해제')
        self._btn_resolve.setFixedWidth(80)
        self._btn_resolve.clicked.connect(lambda: self.resolve_clicked.emit(self._robot_id))
        layout.addWidget(self._btn_resolve)

    def _update_style(self):
        if self._resolved:
            bg = _EVENT_COLORS['RESOLVED']
        else:
            bg = _EVENT_COLORS.get(self._event_type, '#ffffff')
        self.setStyleSheet(f'QFrame {{ background-color: {bg}; border-radius: 4px; }}')

    def mark_resolved(self):
        self._resolved = True
        self._lbl_desc.setText('✓ 처리됨')
        self._btn_resolve.setEnabled(False)
        self._update_style()


class StaffCallPanel(QWidget):
    """스태프 호출 패널."""

    resolve_requested = pyqtSignal(str)  # robot_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: dict[str, _StaffCallItem] = {}  # robot_id → item

        self.setMinimumHeight(160)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 헤더
        header = QLabel('스태프 호출')
        header.setStyleSheet(
            'background-color: #c0392b; color: white; font-weight: bold; '
            'padding: 4px 8px;'
        )
        layout.addWidget(header)

        # 스크롤 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_content = QWidget()
        self._items_layout = QVBoxLayout(self._scroll_content)
        self._items_layout.setSpacing(4)
        self._items_layout.setContentsMargins(4, 4, 4, 4)
        self._items_layout.addStretch()
        scroll.setWidget(self._scroll_content)
        layout.addWidget(scroll)

    def add_call(self, robot_id: str, event_type: str, timestamp: str):
        """스태프 호출 항목 추가 (또는 기존 항목 갱신)."""
        if robot_id in self._items:
            # 기존 항목 제거 후 새로 추가
            old = self._items[robot_id]
            self._items_layout.removeWidget(old)
            old.deleteLater()

        item = _StaffCallItem(robot_id, event_type, timestamp, self._scroll_content)
        item.resolve_clicked.connect(self.resolve_requested)
        # stretch 앞에 삽입
        stretch_idx = self._items_layout.count() - 1
        self._items_layout.insertWidget(stretch_idx, item)
        self._items[robot_id] = item

    def mark_resolved(self, robot_id: str):
        """해당 로봇의 호출을 처리됨으로 표시."""
        if robot_id in self._items:
            self._items[robot_id].mark_resolved()

"""ZoneSelectDialog — 안내 이동 목적지(zone) 선택 다이얼로그.

REST /zones를 호출해 pickup_zone 타입 구역 목록을 보여주고,
사용자가 선택한 zone_id를 반환한다.
"""

from __future__ import annotations

import json
import urllib.request

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
)

# 안내 이동 대상에서 제외할 zone_type (충전소, 결제 구역 등 내부 전용)
_EXCLUDED_ZONE_TYPES = {'charging', 'checkout'}


class ZoneSelectDialog(QDialog):
    """안내 이동 대상 zone 선택.

    사용 예::

        dlg = ZoneSelectDialog(rest_base, robot_id, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            zone = dlg.selected_zone()  # {'zone_id', 'zone_name', 'x', 'y', ...}
    """

    def __init__(self, rest_base: str, robot_id: str, parent=None):
        super().__init__(parent)
        self._rest_base = rest_base.rstrip('/')
        self._robot_id = robot_id
        self._zones: list[dict] = []
        self._selected: dict | None = None

        self.setWindowTitle(f'안내 이동 — Robot #{robot_id}')
        self.setMinimumSize(360, 420)
        self._build_ui()
        self._load_zones()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('이동할 구역을 선택하세요:'))

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_accept)
        layout.addWidget(self._list)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_zones(self) -> None:
        url = f'{self._rest_base}/zones'
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                zones = json.loads(resp.read())
        except Exception as e:
            QMessageBox.warning(
                self, 'zone 목록 조회 실패',
                f'{url}\n{e}',
            )
            self.reject()
            return

        self._zones = [
            z for z in zones
            if z.get('zone_type') not in _EXCLUDED_ZONE_TYPES
        ]
        if not self._zones:
            QMessageBox.information(
                self, '이동 가능한 구역 없음',
                '서버에 등록된 이동 가능 구역이 없습니다.',
            )
            self.reject()
            return

        for z in self._zones:
            label = f"[{z['zone_id']}] {z['zone_name']}  ({z['x']:.2f}, {z['y']:.2f})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, z)
            self._list.addItem(item)

        self._list.setCurrentRow(0)

    def _on_accept(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        self._selected = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def selected_zone(self) -> dict | None:
        return self._selected

"""RobotDetailDialog — 로봇 상세 정보 + 장바구니 조회 다이얼로그.

비모달 QDialog. 로봇 카드 클릭 시 열리고, REST API로 장바구니를 1회 조회한다.

공개 API:
    RobotDetailDialog(robot_id, rest_base_url, parent=None)
    update_state(state: dict)   — 상단 요약 갱신 (TCP status 수신 시 호출)

순수 함수 (단위 테스트용):
    _calc_unpaid_total(items)   — 미결제 항목의 price×quantity 합계
    _format_won(amount)         — "1,500원" 형식 문자열
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
import logging

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 순수 함수 (Qt 없이 테스트 가능)
# ──────────────────────────────────────────────

def _calc_unpaid_total(items: list) -> int:
    """미결제 항목만 price × quantity 합산."""
    return sum(
        i['price'] * i.get('quantity', 1)
        for i in items
        if not i.get('is_paid', False)
    )


def _format_won(amount: int) -> str:
    return f'{amount:,}원'


# ──────────────────────────────────────────────
# 다이얼로그
# ──────────────────────────────────────────────

class RobotDetailDialog(QDialog):
    """로봇 상세 정보 + 장바구니 표시 다이얼로그."""

    def __init__(self, robot_id: str, rest_base_url: str, parent=None):
        super().__init__(parent)
        self._robot_id = robot_id
        self._rest_base = rest_base_url.rstrip('/')

        self.setWindowTitle(f'Robot #{robot_id} 상세 정보')
        self.setWindowFlag(Qt.WindowType.Tool)
        self.setMinimumWidth(460)
        self.setMinimumHeight(340)

        self._build_ui()
        # _fetch_cart는 urllib blocking 호출(최대 3초 × 2) → __init__에서 부르면
        # 메인 Qt event loop가 막혀 그동안 쌓인 status 시그널이 dialog 뜨자마자
        # 폭주해 paint 경합으로 macOS에서 bus error를 유발한다.
        # 이벤트 루프 한 tick 뒤에 실행.
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, self._fetch_cart)

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 상단 요약 레이블
        self._lbl_mode    = QLabel('모드: -')
        self._lbl_battery = QLabel('배터리: -')
        self._lbl_user    = QLabel('사용자: -')
        self._lbl_pos     = QLabel('위치: (-, -)')

        info_row1 = QHBoxLayout()
        info_row1.addWidget(self._lbl_mode)
        info_row1.addWidget(self._lbl_battery)
        info_row1.addStretch()
        layout.addLayout(info_row1)

        info_row2 = QHBoxLayout()
        info_row2.addWidget(self._lbl_user)
        info_row2.addWidget(self._lbl_pos)
        info_row2.addStretch()
        layout.addLayout(info_row2)

        # 구분선
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet('background: #cccccc;')
        layout.addWidget(sep)

        # 장바구니 제목
        self._lbl_cart_title = QLabel('🛒 장바구니')
        self._lbl_cart_title.setStyleSheet('font-weight: bold; font-size: 13px;')
        layout.addWidget(self._lbl_cart_title)

        # 장바구니 테이블 (상품명 | 단가 | 수량 | 소계 | 결제)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(['상품명', '단가', '수량', '소계', '결제'])
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setColumnWidth(0, 160)
        self._table.setColumnWidth(1, 70)
        self._table.setColumnWidth(2, 45)
        self._table.setColumnWidth(3, 70)
        self._table.setColumnWidth(4, 45)
        layout.addWidget(self._table)

        # 하단: 합계 + 새로고침
        bottom = QHBoxLayout()
        self._lbl_total = QLabel('미결제 합계: -')
        self._lbl_total.setStyleSheet('font-weight: bold;')
        bottom.addWidget(self._lbl_total)
        bottom.addStretch()
        btn_refresh = QPushButton('새로고침')
        btn_refresh.clicked.connect(self._fetch_cart)
        bottom.addWidget(btn_refresh)
        layout.addLayout(bottom)

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def update_state(self, state: dict) -> None:
        """상단 요약 갱신 (TCP status 수신 시 호출)."""
        mode    = state.get('mode', '-')
        battery = state.get('battery', '-')
        user    = state.get('active_user_id') or '-'
        pos_x   = state.get('pos_x', 0.0)
        pos_y   = state.get('pos_y', 0.0)

        self._lbl_mode.setText(f'모드: {mode}')
        self._lbl_battery.setText(f'배터리: {battery}%')
        self._lbl_user.setText(f'사용자: {user}')
        self._lbl_pos.setText(f'위치: ({pos_x:.2f}, {pos_y:.2f})')

    # ------------------------------------------------------------------
    # REST 조회
    # ------------------------------------------------------------------

    def _fetch_cart(self):
        """REST API로 장바구니를 조회해 테이블을 갱신한다."""
        try:
            # 1) active session → cart_id
            session_url = f'{self._rest_base}/session/robot/{self._robot_id}'
            with urllib.request.urlopen(session_url, timeout=3) as resp:
                session_data = json.loads(resp.read())
            cart_id = session_data.get('cart_id')
            if cart_id is None:
                self._show_empty('활성 세션이 없습니다')
                return

            # 2) cart items
            cart_url = f'{self._rest_base}/cart/{cart_id}'
            with urllib.request.urlopen(cart_url, timeout=3) as resp:
                items = json.loads(resp.read())

            self._populate_table(items)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                self._show_empty('활성 세션이 없습니다')
            else:
                self._show_empty(f'오류: HTTP {e.code}')
            logger.warning('_fetch_cart HTTP error: %s', e)
        except Exception as e:
            self._show_empty('장바구니를 불러올 수 없습니다')
            logger.warning('_fetch_cart error: %s', e)

    def _populate_table(self, items: list):
        """아이템 목록으로 테이블을 채운다."""
        self._table.setRowCount(len(items))

        paid_fg = QColor('#aaaaaa')
        paid_bg = QColor('#f5f5f5')

        for row, item in enumerate(items):
            name     = item.get('product_name', item.get('name', ''))
            price    = int(item.get('price', 0))
            qty      = int(item.get('quantity', 1))
            subtotal = price * qty
            is_paid  = bool(item.get('is_paid', False))

            cells = [
                name,
                _format_won(price),
                str(qty),
                _format_won(subtotal),
                '✓' if is_paid else '-',
            ]
            for col, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                cell.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter
                    if col > 0
                    else Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
                )
                if is_paid:
                    cell.setForeground(paid_fg)
                    cell.setBackground(paid_bg)
                self._table.setItem(row, col, cell)

        total = _calc_unpaid_total(items)
        unpaid_count = sum(1 for i in items if not i.get('is_paid', False))
        total_count = len(items)
        self._lbl_cart_title.setText(
            f'🛒 장바구니 ({total_count}개 · 미결제 {_format_won(total)})'
        )
        self._lbl_total.setText(f'미결제 합계: {_format_won(total)}')

    def _show_empty(self, message: str):
        """장바구니 테이블을 비우고 메시지를 표시한다."""
        self._table.setRowCount(0)
        self._lbl_cart_title.setText('🛒 장바구니')
        self._lbl_total.setText(message)

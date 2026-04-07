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

"""admin_ui 패키지 기본 임포트 테스트."""


def test_import_tcp_client():
    """TCPClientThread 임포트 테스트."""
    from admin_ui.tcp_client import TCPClientThread
    assert TCPClientThread is not None


def test_mode_colors():
    """MODE_COLORS 딕셔너리 키 확인."""
    from admin_ui.robot_card import MODE_COLORS
    expected_modes = {
        'CHARGING', 'IDLE', 'TRACKING', 'TRACKING_CHECKOUT',
        'GUIDING', 'SEARCHING', 'WAITING', 'LOCKED',
        'RETURNING', 'HALTED', 'OFFLINE',
    }
    assert expected_modes.issubset(set(MODE_COLORS.keys()))


def test_map_yaml_load():
    """맵 YAML 로드 및 메타데이터 확인."""
    from admin_ui.map_widget import _load_map_meta
    meta = _load_map_meta()
    assert meta['resolution'] > 0
    assert isinstance(meta['origin_x'], float)
    assert isinstance(meta['origin_y'], float)


def test_event_log_max_rows():
    """EventLogPanel MAX_ROWS 상수 확인."""
    from admin_ui.event_log_panel import MAX_ROWS
    assert MAX_ROWS == 200


def test_robot_detail_dialog_import():
    from admin_ui.robot_detail_dialog import RobotDetailDialog
    assert RobotDetailDialog is not None


def test_robot_detail_dialog_pure_functions_empty():
    from admin_ui.robot_detail_dialog import _calc_unpaid_total, _format_won
    assert _calc_unpaid_total([]) == 0
    assert _format_won(0) == '0원'


def test_robot_detail_dialog_total_calculation():
    """미결제만 합산, 결제 완료 항목 제외."""
    from admin_ui.robot_detail_dialog import _calc_unpaid_total
    items = [
        {'price': 1000, 'quantity': 2, 'is_paid': False},   # 2000
        {'price': 500,  'quantity': 1, 'is_paid': True},    # 제외
        {'price': 800,  'quantity': 3, 'is_paid': False},   # 2400
    ]
    assert _calc_unpaid_total(items) == 4400


def test_robot_card_has_card_clicked_signal():
    from admin_ui.robot_card import RobotCard
    assert hasattr(RobotCard, 'card_clicked')

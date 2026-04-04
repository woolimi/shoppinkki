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


def test_map_constants():
    """맵 좌표 변환 상수 확인."""
    from admin_ui.map_widget import MAP_RESOLUTION, MAP_ORIGIN_X, MAP_ORIGIN_Y
    assert MAP_RESOLUTION == 0.01
    assert MAP_ORIGIN_X == -0.1
    assert MAP_ORIGIN_Y == -0.1


def test_event_log_max_rows():
    """EventLogPanel MAX_ROWS 상수 확인."""
    from admin_ui.event_log_panel import MAX_ROWS
    assert MAX_ROWS == 200

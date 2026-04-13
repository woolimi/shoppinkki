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

"""QApplication 진입점.

환경변수:
    CONTROL_SERVICE_HOST (기본 127.0.0.1)
    CONTROL_SERVICE_PORT (기본 8080)
    REST_PORT (기본 8081)
    ROBOT_IDS (기본 54,18)
"""

import os
import sys


def _setup_qt_platform() -> None:
    """Qt 플랫폼 플러그인 경로를 OS에 맞게 설정.

    QApplication 생성 전에 반드시 호출해야 한다.
    환경 변수가 이미 설정되어 있으면 덮어쓰지 않는다.
    """
    if sys.platform == 'darwin':
        # macOS: PyQt6 번들 내 cocoa 플러그인 경로 자동 탐색
        try:
            import PyQt6  # noqa: PLC0415
            path = os.path.join(os.path.dirname(PyQt6.__file__), 'Qt6', 'plugins', 'platforms')
            if os.path.isdir(path):
                os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', path)
        except Exception:
            pass
    elif sys.platform.startswith('linux'):
        # Ubuntu/Linux: Wayland 세션이면 wayland, 없으면 xcb(X11) 사용
        if os.environ.get('WAYLAND_DISPLAY'):
            os.environ.setdefault('QT_QPA_PLATFORM', 'wayland')
        else:
            os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')
        # pip 설치 PyQt6의 플러그인 경로가 시스템 경로와 다를 수 있으므로 같이 설정
        try:
            import PyQt6  # noqa: PLC0415
            path = os.path.join(os.path.dirname(PyQt6.__file__), 'Qt6', 'plugins', 'platforms')
            if os.path.isdir(path):
                os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', path)
        except Exception:
            pass


_setup_qt_platform()  # QApplication import 전에 실행

from PyQt6.QtWidgets import QApplication  # noqa: E402

from .main_window import MainWindow


def main():
    """Admin UI 엔트리포인트."""
    host = os.environ.get('CONTROL_SERVICE_HOST', '127.0.0.1')
    port = int(os.environ.get('CONTROL_SERVICE_PORT', '8080'))
    rest_port = int(os.environ.get('REST_PORT', '8081'))
    robot_ids_str = os.environ.get('ROBOT_IDS', '11,18,54')
    robot_ids = [rid.strip() for rid in robot_ids_str.split(',') if rid.strip()]

    app = QApplication(sys.argv)
    app.setApplicationName('ShopPinkki Admin UI')
    app.setOrganizationName('ShopPinkki')

    window = MainWindow(
        tcp_host=host,
        tcp_port=port,
        rest_host=host,
        rest_port=rest_port,
        robot_ids=robot_ids,
    )
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()

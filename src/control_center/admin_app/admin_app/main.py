"""admin_app entry point — launches control_service node + PyQt6 window in same process."""

import os
import sys
import threading
import logging

# ── Qt platform plugin 경로 자동 설정 (macOS + conda 환경) ──────────────────
# ros2 run은 conda 환경 변수를 그대로 상속하지 않아 cocoa 플러그인을 못 찾을 수 있음.
# PyQt6 패키지 위치로부터 platforms 디렉터리를 직접 찾아서 주입한다.
def _ensure_qt_platform_plugin():
    if os.environ.get('QT_QPA_PLATFORM_PLUGIN_PATH'):
        return  # 이미 설정됨
    try:
        import PyQt6
        qt_pkg_dir = os.path.dirname(PyQt6.__file__)
        candidates = [
            os.path.join(qt_pkg_dir, 'Qt6', 'plugins', 'platforms'),
            os.path.join(qt_pkg_dir, 'Qt6', 'plugins'),
        ]
        for path in candidates:
            if os.path.isdir(path):
                os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = path
                break
    except ImportError:
        pass

_ensure_qt_platform_plugin()

import rclpy
from PyQt6.QtWidgets import QApplication

from admin_app.app_bridge import AdminAppBridge
from admin_app.main_window import MainWindow
from control_service.main_node import ControlServiceNode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _spin(node):
    """ROS2 spin loop — runs in background thread."""
    try:
        rclpy.spin(node)
    except Exception as e:
        logger.error(f'[ros_spin] error: {e}')


def main(args=None):
    # --- 1. Qt application (must own the main thread) ---
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName('쑈삥끼 관제')

    # --- 2. ROS2 init ---
    rclpy.init(args=args)

    # --- 3. Bridge (QObject — must be created after QApplication) ---
    bridge = AdminAppBridge()

    # --- 4. control_service node with bridge injected ---
    node = ControlServiceNode(app_bridge=bridge)
    bridge.set_control_node(node)

    # --- 5. ROS spin in background thread ---
    ros_thread = threading.Thread(target=_spin, args=(node,), daemon=True)
    ros_thread.start()

    # --- 6. Main window ---
    window = MainWindow(bridge)
    window.show()

    # --- 7. Qt event loop (blocks until window closed) ---
    exit_code = qt_app.exec()

    # --- 8. Cleanup ---
    node.destroy_node()
    rclpy.shutdown()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()

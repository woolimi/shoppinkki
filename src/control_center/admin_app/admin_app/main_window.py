"""MainWindow — top-level QMainWindow for admin_app."""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QStatusBar,
)
from PyQt6.QtCore import Qt, QTimer

from admin_app.app_bridge import AdminAppBridge
from admin_app.widgets.robot_panel import RobotPanel
from admin_app.widgets.alarm_panel import AlarmPanel
from admin_app.widgets.map_view import MapView
from admin_app.widgets.event_log_panel import EventLogPanel

ROBOT_IDS = ['54', '18']


class MainWindow(QMainWindow):
    """ShopPinkki admin dashboard main window."""

    def __init__(self, bridge: AdminAppBridge, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self.setWindowTitle('쑈삥끼 관제 센터')
        self.resize(1280, 720)
        self._build_ui()
        self._setup_status_bar()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # --- Left column: Robot panels + Alarm ---
        left_col = QWidget()
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)

        for rid in ROBOT_IDS:
            panel = RobotPanel(rid, self._bridge)
            left_layout.addWidget(panel)

        self._alarm_panel = AlarmPanel(self._bridge)
        left_layout.addWidget(self._alarm_panel)
        left_layout.addStretch()

        # --- Center: Map view ---
        self._map_view = MapView(self._bridge)

        # --- Right column: Event log ---
        self._event_log = EventLogPanel(self._bridge)

        # --- Splitter ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_col)
        splitter.addWidget(self._map_view)
        splitter.addWidget(self._event_log)
        splitter.setSizes([280, 640, 360])

        root.addWidget(splitter)

    def _setup_status_bar(self):
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage('ROS2 연결 대기 중...')

        # Update status bar every 5 seconds
        timer = QTimer(self)
        timer.timeout.connect(lambda: self._status_bar.showMessage('ROS2 연결됨'))
        timer.start(5000)

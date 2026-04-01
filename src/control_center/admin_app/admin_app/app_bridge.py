"""AdminAppBridge — Channel D interface between control_service and admin_app.

control_service calls methods on this bridge (from ROS thread).
Bridge emits Qt signals so the UI updates safely in the Qt main thread.
"""

from PyQt6.QtCore import QObject, pyqtSignal


class AdminAppBridge(QObject):
    """Qt signal hub for Channel D (control_service → admin_app)."""

    # Emitted when robot status changes (1~2 Hz heartbeat)
    # args: robot_id (str), status (dict with mode/pos_x/pos_y/battery)
    robot_status_updated = pyqtSignal(str, dict)

    # Emitted when a new alarm is raised
    # args: robot_id (str), event_type (str), occurred_at (str ISO8601)
    alarm_raised = pyqtSignal(str, str, str)

    # Emitted when an alarm is resolved
    # args: robot_id (str)
    alarm_dismissed = pyqtSignal(str)

    # Emitted when a robot goes offline
    # args: robot_id (str)
    robot_offline = pyqtSignal(str)

    # Emitted when a robot comes back online
    # args: robot_id (str)
    robot_online = pyqtSignal(str)

    # Emitted for any EVENT_LOG entry
    # args: event_dict (dict with robot_id/user_id/event_type/event_detail/occurred_at)
    event_logged = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._control_node = None   # set by main.py after node creation

    def set_control_node(self, node) -> None:
        """Inject control_service node reference for admin→control calls."""
        self._control_node = node

    # ------------------------------------------------------------------
    # control_service → admin  (called from ROS thread → emit signal)
    # ------------------------------------------------------------------

    def on_robot_status_update(self, robot_id: str, status: dict) -> None:
        """Called by control_service when /robot_<id>/status arrives."""
        self.robot_status_updated.emit(robot_id, status)

    def on_alarm(self, robot_id: str, event_type: str, occurred_at: str) -> None:
        """Called by control_service when a new alarm is inserted."""
        self.alarm_raised.emit(robot_id, event_type, occurred_at)

    def on_alarm_dismissed(self, robot_id: str) -> None:
        """Called by control_service when an alarm is resolved."""
        self.alarm_dismissed.emit(robot_id)

    def on_robot_offline(self, robot_id: str) -> None:
        """Called by control_service cleanup thread when robot goes offline."""
        self.robot_offline.emit(robot_id)

    def on_robot_online(self, robot_id: str) -> None:
        """Called by control_service when robot comes back online."""
        self.robot_online.emit(robot_id)

    def on_event(self, event_dict: dict) -> None:
        """Called by control_service for every EVENT_LOG entry."""
        self.event_logged.emit(event_dict)

    # ------------------------------------------------------------------
    # admin → control_service  (called from Qt thread → direct call OK)
    # ------------------------------------------------------------------

    def dismiss_alarm(self, robot_id: str) -> None:
        """Send dismiss_alarm cmd to robot via control_service."""
        if self._control_node:
            self._control_node.publish_cmd(robot_id, {'cmd': 'dismiss_alarm'})

    def force_terminate(self, robot_id: str) -> None:
        """Send force_terminate cmd to robot via control_service."""
        if self._control_node:
            self._control_node.publish_cmd(robot_id, {'cmd': 'force_terminate'})

    def admin_goto(self, robot_id: str, x: float, y: float, theta: float = 0.0) -> None:
        """Send admin_goto cmd to robot via control_service."""
        if self._control_node:
            self._control_node.publish_cmd(
                robot_id,
                {'cmd': 'admin_goto', 'x': x, 'y': y, 'theta': theta},
            )

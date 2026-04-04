"""Unit tests for RobotManager — uses mock DB functions, no MySQL needed."""

import pytest
from unittest.mock import MagicMock, patch
from control_service.robot_manager import RobotManager


def make_rm():
    """Create a RobotManager with DB calls mocked out."""
    with patch('control_service.robot_manager.db') as mock_db:
        mock_db.get_all_robots.return_value = [
            {'robot_id': '54', 'current_mode': 'CHARGING', 'pos_x': 0.0,
             'pos_y': 0.0, 'battery_level': 100, 'is_locked_return': 0,
             'active_user_id': None},
        ]
        mock_db.update_robot.return_value = None
        mock_db.log_event.return_value = None
        mock_db.log_staff_call.return_value = 1

        rm = RobotManager()
        rm.start()
        rm._db_mock = mock_db   # keep ref for assertions
    return rm


class TestStatusUpdate:
    def test_mode_updated(self):
        rm = make_rm()
        rm.on_status('54', {'mode': 'TRACKING', 'pos_x': 1.0, 'pos_y': 2.0,
                            'battery': 85.0, 'is_locked_return': False})
        state = rm.get_state('54')
        assert state.mode == 'TRACKING'
        assert state.pos_x == 1.0
        assert state.battery == 85.0

    def test_new_robot_created(self):
        rm = make_rm()
        rm.on_status('18', {'mode': 'IDLE', 'pos_x': 0.0, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        assert rm.get_state('18') is not None

    def test_registration_done_push(self):
        pushed = []
        rm = make_rm()
        rm.push_to_web = lambda rid, msg: pushed.append((rid, msg))
        # Simulate IDLE → TRACKING
        rm.on_status('54', {'mode': 'IDLE', 'pos_x': 0, 'pos_y': 0,
                            'battery': 100, 'is_locked_return': False})
        rm.on_status('54', {'mode': 'TRACKING', 'pos_x': 0, 'pos_y': 0,
                            'battery': 100, 'is_locked_return': False})
        reg_events = [(r, m) for r, m in pushed if m.get('type') == 'registration_done']
        assert len(reg_events) == 1
        assert reg_events[0][0] == '54'


class TestAlarm:
    def test_alarm_pushes_to_admin_and_web(self):
        admin_msgs = []
        web_msgs = []
        rm = make_rm()
        rm.push_to_admin = admin_msgs.append
        rm.push_to_web = lambda rid, msg: web_msgs.append(msg)
        rm.on_alarm('54', {'event': 'LOCKED'})
        assert any(m.get('event') == 'LOCKED' for m in admin_msgs)
        assert any(m.get('event') == 'LOCKED' for m in web_msgs)


class TestAdminCmd:
    def test_relay_mode_cmd(self):
        cmds = []
        rm = make_rm()
        rm.publish_cmd = lambda rid, p: cmds.append((rid, p))
        rm.handle_admin_cmd('54', {'cmd': 'mode', 'value': 'WAITING'})
        assert any(c[1]['cmd'] == 'mode' for c in cmds)

    def test_admin_goto_rejected_when_not_idle(self):
        rejected = []
        rm = make_rm()
        rm.push_to_admin = rejected.append
        # Robot is CHARGING (not IDLE)
        rm.handle_admin_cmd('54', {'cmd': 'admin_goto',
                                   'robot_id': '54', 'x': 1.0, 'y': 0.5, 'theta': 0.0})
        assert any(m.get('type') == 'admin_goto_rejected' for m in rejected)

    def test_admin_goto_allowed_when_idle(self):
        cmds = []
        rm = make_rm()
        rm.publish_cmd = lambda rid, p: cmds.append((rid, p))
        # Set robot to IDLE
        rm.on_status('54', {'mode': 'IDLE', 'pos_x': 0, 'pos_y': 0,
                            'battery': 100, 'is_locked_return': False})
        rm.handle_admin_cmd('54', {'cmd': 'admin_goto',
                                   'robot_id': '54', 'x': 1.0, 'y': 0.5, 'theta': 0.0})
        assert any(c[1]['cmd'] == 'admin_goto' for c in cmds)


class TestBboxUpdate:
    def test_bbox_stored(self):
        rm = make_rm()
        rm.update_bbox('54', {'cx': 320, 'area': 12000, 'confidence': 0.9})
        state = rm.get_state('54')
        assert state.bbox is not None
        assert state.bbox['cx'] == 320

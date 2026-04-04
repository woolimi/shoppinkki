"""RobotCommandHandle 단위 테스트.

실제 RMF / ROS / control_service 없이 mock 으로 navigate / stop / dock 동작 검증.
"""

import math
import threading
import time
import unittest
from unittest.mock import MagicMock, patch


class MockStatusBridge:
    """RobotStatusBridge mock."""

    def __init__(self, x=0.0, y=0.0, yaw=0.0, mode='IDLE'):
        self._x = x
        self._y = y
        self._yaw = yaw
        self._mode = mode

    @property
    def pose(self):
        return (self._x, self._y, self._yaw)

    @property
    def current_mode(self):
        return self._mode

    def teleport(self, x, y, yaw, mode=None):
        self._x, self._y, self._yaw = x, y, yaw
        if mode:
            self._mode = mode


class TestPinkyCommandHandle(unittest.TestCase):

    def _make_handle(self, bridge=None):
        """PinkyCommandHandle 인스턴스 생성 (REST mock)."""
        from shoppinkki_rmf.robot_command_handle import PinkyCommandHandle

        bridge = bridge or MockStatusBridge()
        handle = PinkyCommandHandle('54', bridge)
        # REST 호출 mock
        handle._send_cmd = MagicMock(return_value=True)
        return handle, bridge

    # ── navigate ─────────────────────────────────────────────────────────────

    def test_navigate_sends_correct_payload(self):
        """navigate() 가 navigate_to payload 를 전송하는지 확인."""
        handle, bridge = self._make_handle()
        done = threading.Event()

        class FakePose:
            x, y, yaw = 1.0, 0.8, 0.0

        handle.navigate(FakePose(), 6, done.set)
        time.sleep(0.1)

        handle._send_cmd.assert_called_once()
        payload = handle._send_cmd.call_args[0][0]
        self.assertEqual(payload['cmd'], 'navigate_to')
        self.assertAlmostEqual(payload['x'], 1.0)
        self.assertAlmostEqual(payload['y'], 0.8)

    def test_navigate_done_callback_when_arrived(self):
        """로봇이 목표 지점에 있으면 done_callback 이 호출되는지 확인."""
        bridge = MockStatusBridge(x=1.0, y=0.8, yaw=0.0)
        handle, _ = self._make_handle(bridge)

        done = threading.Event()

        class FakePose:
            x, y, yaw = 1.0, 0.8, 0.0

        handle.navigate(FakePose(), 6, done.set)
        # 도착 조건 이미 충족 → done 이벤트 발생 대기
        fired = done.wait(timeout=3.0)
        self.assertTrue(fired, 'done_callback 이 호출되지 않음')

    # ── stop ─────────────────────────────────────────────────────────────────

    def test_stop_sends_waiting(self):
        """stop() 이 mode WAITING cmd 를 전송하는지 확인."""
        handle, _ = self._make_handle()
        handle.stop()
        payload = handle._send_cmd.call_args[0][0]
        self.assertEqual(payload['cmd'], 'mode')
        self.assertEqual(payload['value'], 'WAITING')

    def test_stop_calls_done_callback(self):
        """stop() 이 done_callback 을 즉시 호출하는지 확인."""
        handle, _ = self._make_handle()
        done = threading.Event()
        handle.stop(done_callback=done.set)
        self.assertTrue(done.is_set())

    # ── dock ─────────────────────────────────────────────────────────────────

    def test_dock_sends_returning(self):
        """dock() 이 mode RETURNING cmd 를 전송하는지 확인."""
        handle, bridge = self._make_handle()
        done = threading.Event()

        handle.dock('P1', done.set)
        time.sleep(0.1)

        payload = handle._send_cmd.call_args[0][0]
        self.assertEqual(payload['cmd'], 'mode')
        self.assertEqual(payload['value'], 'RETURNING')

    def test_dock_done_when_charging(self):
        """CHARGING 상태 도달 시 dock done_callback 이 호출되는지 확인."""
        bridge = MockStatusBridge(mode='RETURNING')
        handle, _ = self._make_handle(bridge)

        done = threading.Event()
        handle.dock('P1', done.set)

        # 0.5s 후 CHARGING 상태로 전환
        time.sleep(0.5)
        bridge.teleport(0.2, 0.2, 1.5708, mode='CHARGING')

        fired = done.wait(timeout=5.0)
        self.assertTrue(fired, 'dock done_callback 이 호출되지 않음')


class TestAngleDiff(unittest.TestCase):

    def test_angle_diff_zero(self):
        from shoppinkki_rmf.robot_command_handle import _angle_diff
        self.assertAlmostEqual(_angle_diff(0.0, 0.0), 0.0)

    def test_angle_diff_wrap(self):
        from shoppinkki_rmf.robot_command_handle import _angle_diff
        diff = _angle_diff(math.pi - 0.1, -math.pi + 0.1)
        self.assertAlmostEqual(abs(diff), 0.2, places=5)


if __name__ == '__main__':
    unittest.main()

"""Unit tests for BTSearching — no ROS needed."""

import time
import pytest

from shoppinkki_interfaces import BTStatus
from shoppinkki_interfaces.mocks import MockDollDetector, MockRobotPublisher
from shoppinkki_nav.bt_searching import BTSearching


def make_bt(search_timeout=0.2, mock_scan=None):
    """Create a BTSearching with short timeout for fast tests."""
    import shoppinkki_nav.bt_searching as mod
    # Patch SEARCH_TIMEOUT for the duration of this test
    original = mod.SEARCH_TIMEOUT
    mod.SEARCH_TIMEOUT = search_timeout

    detector = MockDollDetector()
    publisher = MockRobotPublisher()
    bt = BTSearching(
        doll_detector=detector,
        publisher=publisher,
        get_scan=mock_scan,
    )
    return bt, detector, publisher, (mod, original)


def restore_timeout(patch_info):
    mod, original = patch_info
    mod.SEARCH_TIMEOUT = original


class TestBTSearchingTimeout:
    def test_returns_failure_on_timeout(self):
        bt, detector, publisher, patch = make_bt(search_timeout=0.1)
        bt.start()
        time.sleep(0.15)
        status = bt.tick()
        assert status == BTStatus.FAILURE
        restore_timeout(patch)

    def test_running_before_timeout(self):
        bt, detector, publisher, patch = make_bt(search_timeout=5.0)
        bt.start()
        status = bt.tick()
        assert status == BTStatus.RUNNING
        bt.stop()
        restore_timeout(patch)


class TestBTSearchingDetection:
    def test_returns_success_when_doll_detected(self):
        bt, detector, publisher, patch = make_bt(search_timeout=5.0)
        bt.start()
        # Initially no detection → RUNNING
        assert bt.tick() == BTStatus.RUNNING
        # Now inject detection
        from shoppinkki_interfaces import Detection
        detector.set_detection(Detection(cx=320, cy=240, area=10000, confidence=0.9))
        status = bt.tick()
        assert status == BTStatus.SUCCESS
        bt.stop()
        restore_timeout(patch)


class TestBTSearchingRotation:
    def test_publishes_rotation_on_tick(self):
        bt, detector, publisher, patch = make_bt(search_timeout=5.0)
        bt.start()
        bt.tick()
        # Should have published a non-zero angular velocity
        assert publisher.last_angular_z != 0.0
        bt.stop()
        restore_timeout(patch)

    def test_stops_on_stop(self):
        bt, detector, publisher, patch = make_bt(search_timeout=5.0)
        bt.start()
        bt.tick()
        bt.stop()
        assert publisher.last_linear_x == 0.0
        assert publisher.last_angular_z == 0.0
        restore_timeout(patch)


class TestBTSearchingObstacle:
    def test_switches_direction_on_obstacle(self):
        # Scan that always reports obstacle in left arc (simulating CCW blocked)
        obstacles_left = [9.9] * 360
        # Block left side (45°..135°)
        for i in range(45, 136):
            obstacles_left[i] = 0.05

        bt, detector, publisher, patch = make_bt(
            search_timeout=5.0,
            mock_scan=lambda: obstacles_left,
        )
        bt.start()
        bt.tick()   # First tick: detects left blocked, switches to CW
        # Direction should now be CW (-1.0), so angular_z should be negative
        bt.tick()
        assert publisher.last_angular_z < 0.0
        bt.stop()
        restore_timeout(patch)

    def test_failure_when_both_directions_blocked(self):
        # All arcs blocked
        all_blocked = [0.05] * 360
        bt, detector, publisher, patch = make_bt(
            search_timeout=5.0,
            mock_scan=lambda: all_blocked,
        )
        bt.start()
        status = bt.tick()
        assert status == BTStatus.FAILURE
        restore_timeout(patch)

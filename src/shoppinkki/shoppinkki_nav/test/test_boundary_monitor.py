"""Unit tests for BoundaryMonitor — no ROS needed."""

import pytest
from shoppinkki_nav.boundary_monitor import Boundary, BoundaryMonitor


def make_checkout_boundary():
    return Boundary(
        name='결제 구역',
        x_min=0.5, x_max=1.5,
        y_min=0.5, y_max=1.5,
    )


class TestBoundaryContains:
    def test_inside(self):
        b = make_checkout_boundary()
        assert b.contains(1.0, 1.0) is True

    def test_outside(self):
        b = make_checkout_boundary()
        assert b.contains(0.0, 0.0) is False

    def test_on_edge(self):
        b = make_checkout_boundary()
        assert b.contains(0.5, 0.5) is True


class TestBoundaryMonitor:
    def _make_monitor(self, state='TRACKING'):
        entered = []
        exited = []
        reentered = []

        monitor = BoundaryMonitor(
            boundaries=[make_checkout_boundary()],
            on_checkout_enter=lambda: entered.append(1),
            on_checkout_exit_blocked=lambda: exited.append(1),
            on_checkout_reenter=lambda: reentered.append(1),
            get_state=lambda: state_box[0],
        )
        state_box = [state]
        monitor.start()
        return monitor, state_box, entered, exited, reentered

    def test_enter_checkout_fires_callback(self):
        monitor, state_box, entered, exited, reentered = self._make_monitor('TRACKING')
        monitor.on_pose_update(1.0, 1.0)
        assert len(entered) == 1
        assert len(exited) == 0

    def test_no_callback_outside_tracking_states(self):
        monitor, state_box, entered, exited, reentered = self._make_monitor('CHARGING')
        monitor.on_pose_update(1.0, 1.0)
        assert len(entered) == 0

    def test_exit_checkout_fires_blocked(self):
        monitor, state_box, entered, exited, reentered = self._make_monitor('TRACKING')
        # Enter checkout
        monitor.on_pose_update(1.0, 1.0)
        # Simulate SM changed to TRACKING_CHECKOUT
        state_box[0] = 'TRACKING_CHECKOUT'
        # Exit checkout
        monitor.on_pose_update(0.0, 0.0)
        assert len(exited) == 1

    def test_reenter_checkout_fires_reenter(self):
        monitor, state_box, entered, exited, reentered = self._make_monitor('TRACKING')
        monitor.on_pose_update(1.0, 1.0)       # enter
        state_box[0] = 'TRACKING_CHECKOUT'
        monitor.on_pose_update(0.0, 0.0)       # exit (blocked)
        monitor.on_pose_update(1.0, 1.0)       # re-enter while TRACKING_CHECKOUT
        assert len(reentered) == 1

    def test_inactive_monitor_ignores_pose(self):
        monitor, state_box, entered, exited, reentered = self._make_monitor('TRACKING')
        monitor.set_active(False)
        monitor.on_pose_update(1.0, 1.0)
        assert len(entered) == 0

    def test_enter_only_once_on_repeated_pose_updates(self):
        monitor, state_box, entered, exited, reentered = self._make_monitor('TRACKING')
        for _ in range(5):
            monitor.on_pose_update(1.0, 1.0)
        assert len(entered) == 1

    def test_no_boundaries_no_crash(self):
        monitor = BoundaryMonitor(
            boundaries=[],
            get_state=lambda: 'TRACKING',
        )
        monitor.start()
        monitor.on_pose_update(1.0, 1.0)   # should not raise

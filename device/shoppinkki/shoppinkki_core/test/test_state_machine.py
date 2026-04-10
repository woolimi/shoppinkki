"""Unit tests for ShoppinkiSM — no ROS, no hardware required.

Run:
    cd ~/ros_ws
    python -m pytest device/shoppinkki/shoppinkki_core/test/test_state_machine.py -v
"""

import pytest
from shoppinkki_core.state_machine import ShoppinkiSM


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def make_sm(**kwargs) -> ShoppinkiSM:
    """Create a fresh SM, optionally with callbacks."""
    return ShoppinkiSM(**kwargs)


def reach_tracking(sm: ShoppinkiSM) -> None:
    """Drive SM from initial CHARGING to TRACKING."""
    sm.charging_completed()   # → IDLE
    sm.enter_tracking()       # → TRACKING


def reach_tracking_checkout(sm: ShoppinkiSM) -> None:
    reach_tracking(sm)
    sm.enter_tracking_checkout()   # → TRACKING_CHECKOUT


# ──────────────────────────────────────────────────────────────────────────────
# Basic state transitions
# ──────────────────────────────────────────────────────────────────────────────

class TestInitialState:
    def test_starts_charging(self):
        sm = make_sm()
        assert sm.state == 'CHARGING'

    def test_is_locked_return_false(self):
        sm = make_sm()
        assert sm.is_locked_return is False

    def test_previous_tracking_state_is_tracking(self):
        sm = make_sm()
        assert sm.previous_tracking_state == 'TRACKING'


class TestSessionStart:
    def test_charging_to_idle(self):
        sm = make_sm()
        sm.charging_completed()
        assert sm.state == 'IDLE'

    def test_idle_to_tracking(self):
        sm = make_sm()
        sm.charging_completed()
        sm.enter_tracking()
        assert sm.state == 'TRACKING'

    def test_previous_tracking_state_set(self):
        sm = make_sm()
        reach_tracking(sm)
        assert sm.previous_tracking_state == 'TRACKING'


class TestTracking:
    def test_tracking_to_searching(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_searching()
        assert sm.state == 'SEARCHING'

    def test_searching_back_to_tracking(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_searching()
        sm.enter_tracking()   # re-detected
        assert sm.state == 'TRACKING'

    def test_searching_to_waiting_on_timeout(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_searching()
        sm.enter_waiting()
        assert sm.state == 'WAITING'

    def test_tracking_to_waiting_on_mode_cmd(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_waiting()
        assert sm.state == 'WAITING'


class TestGuiding:
    def test_tracking_to_guiding(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_guiding()
        assert sm.state == 'GUIDING'

    def test_guiding_to_waiting_on_arrive(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_guiding()
        sm.enter_waiting()
        assert sm.state == 'WAITING'

    def test_guiding_resume_to_tracking(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_guiding()
        sm.resume_tracking()
        assert sm.state == 'TRACKING'

    def test_guiding_resume_to_tracking_checkout(self):
        sm = make_sm()
        reach_tracking_checkout(sm)
        sm.enter_guiding()
        sm.resume_tracking()
        assert sm.state == 'TRACKING_CHECKOUT'


class TestCheckout:
    def test_tracking_to_tracking_checkout(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_tracking_checkout()
        assert sm.state == 'TRACKING_CHECKOUT'
        assert sm.previous_tracking_state == 'TRACKING_CHECKOUT'

    def test_tracking_checkout_to_tracking_on_reenter(self):
        sm = make_sm()
        reach_tracking_checkout(sm)
        sm.enter_tracking()   # BoundaryMonitor re-enter
        assert sm.state == 'TRACKING'

    def test_tracking_checkout_to_searching(self):
        sm = make_sm()
        reach_tracking_checkout(sm)
        sm.enter_searching()
        assert sm.state == 'SEARCHING'


class TestResumeTracking:
    def test_waiting_resumes_to_tracking(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_waiting()
        sm.resume_tracking()
        assert sm.state == 'TRACKING'

    def test_waiting_resumes_to_tracking_checkout(self):
        sm = make_sm()
        reach_tracking_checkout(sm)
        sm.enter_waiting()
        sm.resume_tracking()
        assert sm.state == 'TRACKING_CHECKOUT'


class TestReturning:
    def test_tracking_to_returning(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_returning()
        assert sm.state == 'RETURNING'

    def test_returning_to_charging(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_returning()
        sm.enter_charging()
        assert sm.state == 'CHARGING'

    def test_waiting_to_returning(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_waiting()
        sm.enter_returning()
        assert sm.state == 'RETURNING'

    def test_guiding_to_returning(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_guiding()
        sm.enter_returning()
        assert sm.state == 'RETURNING'

    def test_searching_to_returning(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_searching()
        sm.enter_returning()
        assert sm.state == 'RETURNING'


class TestLocked:
    def test_tracking_to_locked_auto_returning(self):
        """LOCKED immediately auto-transitions to RETURNING."""
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_locked()
        # LOCKED auto-fires enter_returning() in on_enter_LOCKED
        assert sm.state == 'RETURNING'

    def test_is_locked_return_true_after_locked(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_locked()
        assert sm.is_locked_return is True

    def test_locked_return_charging_does_not_end_session(self):
        session_ended = []
        sm = make_sm(on_session_end=lambda: session_ended.append(True))
        reach_tracking(sm)
        sm.enter_locked()        # → RETURNING
        sm.enter_charging()      # → CHARGING (locked)
        # Session should NOT end yet (staff_resolved needed)
        assert session_ended == []

    def test_waiting_to_locked(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_waiting()
        sm.enter_locked()
        assert sm.state == 'RETURNING'

    def test_guiding_to_locked_auto_returning(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_guiding()
        sm.enter_locked()
        assert sm.state == 'RETURNING'
        assert sm.is_locked_return is True


class TestHalted:
    def test_tracking_to_halted(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_halted()
        assert sm.state == 'HALTED'

    def test_halted_from_any_state(self):
        for pre_state in ('IDLE', 'TRACKING', 'SEARCHING', 'WAITING', 'GUIDING'):
            sm = make_sm()
            sm.charging_completed()   # CHARGING → IDLE
            if pre_state != 'IDLE':
                sm.enter_tracking()
                if pre_state == 'SEARCHING':
                    sm.enter_searching()
                elif pre_state == 'WAITING':
                    sm.enter_waiting()
                elif pre_state == 'GUIDING':
                    sm.enter_guiding()
            sm.enter_halted()
            assert sm.state == 'HALTED', f'Expected HALTED from {pre_state}'

    def test_staff_resolved_halted_to_charging(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_halted()
        sm.handle_staff_resolved()
        assert sm.state == 'CHARGING'

    def test_staff_resolved_clears_locked_return(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_locked()     # → RETURNING, is_locked_return=True
        sm.enter_charging()   # → CHARGING (locked)
        sm.handle_staff_resolved()
        assert sm.is_locked_return is False


class TestForceTerminate:
    def test_force_terminate_from_tracking(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.handle_force_terminate()
        assert sm.state == 'CHARGING'

    def test_force_terminate_from_waiting(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_waiting()
        sm.handle_force_terminate()
        assert sm.state == 'CHARGING'

    def test_force_terminate_from_guiding(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_guiding()
        sm.handle_force_terminate()
        assert sm.state == 'CHARGING'

    def test_force_terminate_ignored_in_halted(self):
        sm = make_sm()
        reach_tracking(sm)
        sm.enter_halted()
        sm.handle_force_terminate()  # should be no-op
        assert sm.state == 'HALTED'

    def test_force_terminate_ignored_in_charging(self):
        sm = make_sm()
        sm.handle_force_terminate()  # initial CHARGING — no-op
        assert sm.state == 'CHARGING'


class TestCallbacks:
    def test_state_changed_callback_fires(self):
        states = []
        sm = make_sm(on_state_changed=states.append)
        sm.charging_completed()
        sm.enter_tracking()
        assert 'IDLE' in states
        assert 'TRACKING' in states

    def test_on_locked_callback_fires(self):
        locked_events = []
        sm = make_sm(on_locked=lambda: locked_events.append(True))
        reach_tracking(sm)
        sm.enter_locked()
        assert locked_events == [True]

    def test_on_session_end_fires_on_normal_return(self):
        ended = []
        sm = make_sm(on_session_end=lambda: ended.append(True))
        reach_tracking(sm)
        sm.enter_returning()
        sm.enter_charging()
        assert ended == [True]

    def test_on_halted_callback_fires(self):
        halted = []
        sm = make_sm(on_halted=lambda: halted.append(True))
        reach_tracking(sm)
        sm.enter_halted()
        assert halted == [True]

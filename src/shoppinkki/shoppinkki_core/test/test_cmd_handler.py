"""Unit tests for CmdHandler — no ROS required."""

import json
import pytest
from shoppinkki_core.state_machine import ShoppinkiSM
from shoppinkki_core.cmd_handler import CmdHandler


def make_handler(**kwargs):
    sm = ShoppinkiSM()
    handler = CmdHandler(sm=sm, **kwargs)
    return sm, handler


def cmd(sm, handler, **payload):
    handler.handle(json.dumps(payload))


class TestStartSession:
    def test_charging_to_idle(self):
        sm, h = make_handler()
        cmd(sm, h, cmd='start_session', user_id='test01')
        assert sm.state == 'IDLE'

    def test_callback_fired(self):
        users = []
        sm, h = make_handler(on_start_session=users.append)
        cmd(sm, h, cmd='start_session', user_id='test01')
        assert users == ['test01']

    def test_ignored_outside_charging(self):
        sm, h = make_handler()
        sm.charging_completed()   # → IDLE
        cmd(sm, h, cmd='start_session', user_id='x')
        assert sm.state == 'IDLE'  # no change


class TestModeWaiting:
    def test_tracking_to_waiting(self):
        sm, h = make_handler()
        sm.charging_completed()
        sm.enter_tracking()
        cmd(sm, h, cmd='mode', value='WAITING')
        assert sm.state == 'WAITING'

    def test_tracking_checkout_to_waiting(self):
        sm, h = make_handler()
        sm.charging_completed()
        sm.enter_tracking()
        sm.enter_tracking_checkout()
        cmd(sm, h, cmd='mode', value='WAITING')
        assert sm.state == 'WAITING'


class TestModeReturning:
    def test_empty_cart_to_returning(self):
        sm, h = make_handler(has_unpaid_items=lambda: False)
        sm.charging_completed()
        sm.enter_tracking()
        cmd(sm, h, cmd='mode', value='RETURNING')
        assert sm.state == 'RETURNING'

    def test_unpaid_to_locked_then_returning(self):
        sm, h = make_handler(has_unpaid_items=lambda: True)
        sm.charging_completed()
        sm.enter_tracking()
        cmd(sm, h, cmd='mode', value='RETURNING')
        # LOCKED auto-transitions to RETURNING
        assert sm.state == 'RETURNING'
        assert sm.is_locked_return is True


class TestResumeTracking:
    def test_resume_from_waiting(self):
        sm, h = make_handler()
        sm.charging_completed()
        sm.enter_tracking()
        sm.enter_waiting()
        cmd(sm, h, cmd='resume_tracking')
        assert sm.state == 'TRACKING'


class TestNavigateTo:
    def test_tracking_to_guiding(self):
        goals = []
        sm, h = make_handler(on_navigate_to=lambda *a: goals.append(a))
        sm.charging_completed()
        sm.enter_tracking()
        cmd(sm, h, cmd='navigate_to', zone_id=6, x=1.2, y=0.8, theta=0.0)
        assert sm.state == 'GUIDING'
        assert goals == [(6, 1.2, 0.8, 0.0)]


class TestPaymentSuccess:
    def test_tracking_to_checkout(self):
        sm, h = make_handler()
        sm.charging_completed()
        sm.enter_tracking()
        cmd(sm, h, cmd='payment_success')
        assert sm.state == 'TRACKING_CHECKOUT'


class TestDeleteItem:
    def test_callback_fired(self):
        deleted = []
        sm, h = make_handler(on_delete_item=deleted.append)
        sm.charging_completed()
        sm.enter_tracking()
        cmd(sm, h, cmd='delete_item', item_id=42)
        assert deleted == [42]


class TestForceTerminate:
    def test_tracking_to_charging(self):
        sm, h = make_handler()
        sm.charging_completed()
        sm.enter_tracking()
        cmd(sm, h, cmd='force_terminate')
        assert sm.state == 'CHARGING'


class TestStaffResolved:
    def test_halted_to_charging(self):
        sm, h = make_handler()
        sm.charging_completed()
        sm.enter_tracking()
        sm.enter_halted()
        cmd(sm, h, cmd='staff_resolved')
        assert sm.state == 'CHARGING'

    def test_clears_locked_return(self):
        sm, h = make_handler()
        sm.charging_completed()
        sm.enter_tracking()
        sm.enter_locked()    # → RETURNING, is_locked_return=True
        sm.enter_charging()  # → CHARGING
        cmd(sm, h, cmd='staff_resolved')
        assert sm.is_locked_return is False


class TestAdminGoto:
    def test_idle_fires_callback(self):
        gotos = []
        sm, h = make_handler(on_admin_goto=lambda *a: gotos.append(a))
        sm.charging_completed()   # → IDLE
        cmd(sm, h, cmd='admin_goto', x=1.0, y=0.5, theta=0.0)
        assert gotos == [(1.0, 0.5, 0.0)]

    def test_non_idle_rejected(self):
        gotos = []
        sm, h = make_handler(on_admin_goto=lambda *a: gotos.append(a))
        sm.charging_completed()
        sm.enter_tracking()
        cmd(sm, h, cmd='admin_goto', x=1.0, y=0.5, theta=0.0)
        assert gotos == []


class TestInvalidInput:
    def test_invalid_json_ignored(self):
        sm, h = make_handler()
        h.handle('not json')  # should not raise
        assert sm.state == 'CHARGING'

    def test_unknown_cmd_ignored(self):
        sm, h = make_handler()
        h.handle(json.dumps({'cmd': 'fly_to_moon'}))
        assert sm.state == 'CHARGING'

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


class TestStartup:
    def test_start_resets_sessions_on_startup(self):
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

            mock_db.reset_sessions_on_startup.assert_called_once()


class TestStatusUpdate:
    def test_status_admin_flat_web_has_fleet_snapshot(self):
        admin_msgs = []
        web_msgs = []
        rm = make_rm()
        rm.push_to_admin = admin_msgs.append
        rm.push_to_web = lambda rid, msg: web_msgs.append((rid, msg))
        rm.on_status('18', {'mode': 'IDLE', 'pos_x': 3.0, 'pos_y': 4.0,
                            'battery': 90.0, 'is_locked_return': False})
        rm.on_status('54', {'mode': 'TRACKING', 'pos_x': 1.0, 'pos_y': 2.0,
                            'battery': 85.0, 'is_locked_return': False})
        admin_status = [m for m in admin_msgs if m.get('type') == 'status'][-1]
        assert 'my_robot' not in admin_status
        assert 'other_robots' not in admin_status
        rid, w = [x for x in web_msgs if x[1].get('type') == 'status'][-1]
        assert rid == '54'
        assert w['my_robot']['robot_id'] == '54'
        assert w['my_robot']['pos_x'] == 1.0
        assert len(w['other_robots']) == 1
        assert w['other_robots'][0]['robot_id'] == '18'
        assert w['other_robots'][0]['pos_x'] == 3.0

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

    def test_staff_resolved_ends_session_and_clears_active_user(self):
        with patch('control_service.robot_manager.db') as mock_db:
            mock_db.get_all_robots.return_value = [
                {'robot_id': '54', 'current_mode': 'CHARGING', 'pos_x': 0.0,
                 'pos_y': 0.0, 'battery_level': 100, 'is_locked_return': 1,
                 'active_user_id': 'u1'},
            ]
            mock_db.update_robot.return_value = None
            mock_db.log_event.return_value = None
            mock_db.log_staff_call.return_value = 1
            mock_db.get_active_session_by_robot.return_value = {
                'session_id': 11,
                'user_id': 'u1',
            }
            mock_db.get_cart_by_session.return_value = {'cart_id': 22}
            mock_db.delete_cart_items.return_value = None

            rm = RobotManager()
            rm.start()
            rm.publish_cmd = MagicMock()

            rm.handle_admin_cmd('54', {'cmd': 'staff_resolved', 'robot_id': '54'})

            mock_db.end_session.assert_called_once_with(11)
            # Cache should be cleared even before next status arrives
            st = rm.get_state('54')
            assert st is not None
            assert st.active_user_id is None

    def test_admin_position_adjustment_rejected_when_not_wired(self):
        admin_msgs = []
        rm = make_rm()
        rm.push_to_admin = admin_msgs.append
        rm.handle_admin_cmd('54', {'cmd': 'admin_position_adjustment', 'robot_id': '54',
                                   'x': 0.1, 'y': 0.2, 'theta': 0.0})
        assert any(m.get('type') == 'position_adjustment_rejected' for m in admin_msgs)

    def test_admin_position_adjustment_fallbacks_to_initialpose_when_no_gazebo(self):
        admin_msgs = []
        calls = []
        rm = make_rm()
        rm.push_to_admin = admin_msgs.append
        rm.publish_initialpose_at = lambda rid, x, y, th: calls.append((rid, x, y, th))

        rm.handle_admin_cmd('54', {'cmd': 'admin_position_adjustment', 'robot_id': '54',
                                   'x': 1.2, 'y': -0.3, 'theta': 0.4})

        assert calls == [('54', 1.2, -0.3, 0.4)]
        done = [m for m in admin_msgs if m.get('type') == 'position_adjustment_done']
        assert len(done) == 1
        assert done[0].get('apply_mode') == 'amcl_only'

    def test_admin_position_adjustment_uses_initialpose_fallback_when_gazebo_call_fails(self):
        admin_msgs = []
        calls = []
        rm = make_rm()
        rm.push_to_admin = admin_msgs.append
        rm.adjust_position_in_sim = lambda *_: False
        rm.publish_initialpose_at = lambda rid, x, y, th: calls.append((rid, x, y, th))

        rm.handle_admin_cmd('54', {'cmd': 'admin_position_adjustment', 'robot_id': '54',
                                   'x': 0.5, 'y': 0.6, 'theta': 0.7})

        assert calls == [('54', 0.5, 0.6, 0.7)]
        done = [m for m in admin_msgs if m.get('type') == 'position_adjustment_done']
        assert len(done) == 1
        assert done[0].get('apply_mode') == 'amcl_only'


class TestBboxUpdate:
    def test_bbox_stored(self):
        rm = make_rm()
        rm.update_bbox('54', {'cx': 320, 'area': 12000, 'confidence': 0.9})
        state = rm.get_state('54')
        assert state.bbox is not None
        assert state.bbox['cx'] == 320


class TestWebReturn:
    """쇼핑 종료(return): 쇼핑 중 SM(TRACKING 계열·GUIDING·SEARCHING)에서 Pi로 RETURNING 릴레이."""

    @pytest.mark.parametrize(
        'mode',
        ['TRACKING', 'TRACKING_CHECKOUT', 'WAITING', 'GUIDING', 'SEARCHING'],
    )
    def test_return_relays_returning_when_shopping_mode(self, mode):
        with patch('control_service.robot_manager.db') as mock_db:
            mock_db.get_all_robots.return_value = [
                {'robot_id': '54', 'current_mode': mode, 'pos_x': 0.0,
                 'pos_y': 0.0, 'battery_level': 100, 'is_locked_return': 0,
                 'active_user_id': None},
            ]
            mock_db.update_robot.return_value = None
            mock_db.log_event.return_value = None
            mock_db.log_staff_call.return_value = 1
            mock_db.get_active_session_by_robot.return_value = None
            mock_db.get_cart_by_session.return_value = None

            rm = RobotManager()
            rm.start()
            rm.publish_cmd = MagicMock()
            rm.push_to_admin = MagicMock()
            rm.push_to_web = MagicMock()

            rm.handle_web_cmd('54', {'cmd': 'return', 'robot_id': '54'})

            rm.publish_cmd.assert_called_once()
            _rid, payload = rm.publish_cmd.call_args[0]
            assert _rid == '54'
            assert payload.get('cmd') == 'mode'
            assert payload.get('value') == 'RETURNING'

    @pytest.mark.parametrize(
        'mode',
        ['TRACKING', 'TRACKING_CHECKOUT', 'WAITING', 'GUIDING', 'SEARCHING'],
    )
    def test_return_relays_locked_when_unpaid_items(self, mode):
        with patch('control_service.robot_manager.db') as mock_db:
            mock_db.get_all_robots.return_value = [
                {'robot_id': '54', 'current_mode': mode, 'pos_x': 0.0,
                 'pos_y': 0.0, 'battery_level': 100, 'is_locked_return': 0,
                 'active_user_id': 'u1'},
            ]
            mock_db.update_robot.return_value = None
            mock_db.log_event.return_value = None
            mock_db.log_staff_call.return_value = 1
            mock_db.get_active_session_by_robot.return_value = {'session_id': 11, 'user_id': 'u1'}
            mock_db.get_cart_by_session.return_value = {'cart_id': 22}
            mock_db.has_unpaid_items.return_value = True

            rm = RobotManager()
            rm.start()
            rm.publish_cmd = MagicMock()
            rm.push_to_admin = MagicMock()
            rm.push_to_web = MagicMock()

            rm.handle_web_cmd('54', {'cmd': 'return', 'robot_id': '54'})

            rm.publish_cmd.assert_called_once()
            _rid, payload = rm.publish_cmd.call_args[0]
            assert _rid == '54'
            assert payload.get('cmd') == 'mode'
            assert payload.get('value') == 'RETURNING'
            assert payload.get('is_locked_return') is True
            mock_db.end_session.assert_not_called()

    def test_return_skips_pi_when_idle(self):
        with patch('control_service.robot_manager.db') as mock_db:
            mock_db.get_all_robots.return_value = [
                {'robot_id': '54', 'current_mode': 'IDLE', 'pos_x': 0.0,
                 'pos_y': 0.0, 'battery_level': 100, 'is_locked_return': 0,
                 'active_user_id': None},
            ]
            mock_db.update_robot.return_value = None
            mock_db.log_event.return_value = None
            mock_db.log_staff_call.return_value = 1
            mock_db.get_active_session_by_robot.return_value = None
            mock_db.get_cart_by_session.return_value = None

            rm = RobotManager()
            rm.start()
            rm.publish_cmd = MagicMock()
            rm.push_to_admin = MagicMock()
            rm.push_to_web = MagicMock()

            rm.handle_web_cmd('54', {'cmd': 'return', 'robot_id': '54'})

            rm.publish_cmd.assert_not_called()


class TestReturningSessionCleanup:
    def test_returning_without_unpaid_auto_ends_session(self):
        web_msgs = []
        with patch('control_service.robot_manager.db') as mock_db:
            mock_db.get_all_robots.return_value = [
                {'robot_id': '54', 'current_mode': 'WAITING', 'pos_x': 0.0,
                 'pos_y': 0.0, 'battery_level': 100, 'is_locked_return': 0,
                 'active_user_id': 'test01'},
            ]
            mock_db.update_robot.return_value = None
            mock_db.log_event.return_value = None
            mock_db.log_staff_call.return_value = 1
            mock_db.get_active_session_by_robot.return_value = {
                'session_id': 11,
                'user_id': 'test01',
            }
            mock_db.get_cart_by_session.return_value = {'cart_id': 22}
            mock_db.has_unpaid_items.return_value = False

            rm = RobotManager()
            rm.start()
            rm.push_to_web = lambda rid, msg: web_msgs.append((rid, msg))

            rm.on_status('54', {
                'mode': 'RETURNING', 'pos_x': 0.0, 'pos_y': 0.0,
                'battery': 100.0, 'is_locked_return': False,
            })

            mock_db.end_session.assert_called_once_with(11)
            mock_db.update_robot.assert_any_call('54', current_mode='RETURNING')
            mock_db.update_robot.assert_any_call('54', active_user_id=None)
            assert any(
                rid == '54' and msg.get('type') == 'session_ended'
                for rid, msg in web_msgs
            )


class TestCheckoutZoneAutoReturnEmptyCart:
    """장바구니가 비었을 때 결제 구역 진입 → RETURNING + 세션 종료."""

    def test_empty_cart_triggers_returning_and_session_end(self):
        web_msgs = []
        with patch('control_service.robot_manager.db') as mock_db:
            mock_db.get_all_robots.return_value = [
                {'robot_id': '54', 'current_mode': 'TRACKING', 'pos_x': 0.0,
                 'pos_y': 0.0, 'battery_level': 100, 'is_locked_return': 0,
                 'active_user_id': 'u1'},
            ]
            mock_db.update_robot.return_value = None
            mock_db.log_event.return_value = None
            mock_db.log_staff_call.return_value = 1
            mock_db.get_active_session_by_robot.return_value = {
                'session_id': 11,
                'user_id': 'u1',
            }
            mock_db.get_cart_by_session.return_value = {'cart_id': 22}
            mock_db.has_unpaid_items.return_value = False

            rm = RobotManager()
            rm.start()
            rm.publish_cmd = MagicMock()
            rm.push_to_web = lambda rid, msg: web_msgs.append((rid, msg))

            rm.on_status('54', {
                'mode': 'TRACKING', 'pos_x': 0.0, 'pos_y': 0.0,
                'battery': 100.0, 'is_locked_return': False,
            })

            rm.on_customer_event('54', {'type': 'checkout_zone_enter'})

            rm.publish_cmd.assert_called_once()
            _rid, payload = rm.publish_cmd.call_args[0]
            assert _rid == '54'
            assert payload == {'cmd': 'mode', 'value': 'RETURNING'}
            mock_db.end_session.assert_called_once_with(11)
            mock_db.update_robot.assert_any_call('54', current_mode='RETURNING')
            mock_db.update_robot.assert_any_call('54', active_user_id=None)
            assert any(
                rid == '54' and msg.get('type') == 'session_ended'
                for rid, msg in web_msgs
            )

    def test_unpaid_cart_still_pushes_checkout_zone_enter(self):
        web_msgs = []
        with patch('control_service.robot_manager.db') as mock_db:
            mock_db.get_all_robots.return_value = [
                {'robot_id': '54', 'current_mode': 'TRACKING', 'pos_x': 0.0,
                 'pos_y': 0.0, 'battery_level': 100, 'is_locked_return': 0,
                 'active_user_id': 'u1'},
            ]
            mock_db.update_robot.return_value = None
            mock_db.log_event.return_value = None
            mock_db.log_staff_call.return_value = 1
            mock_db.get_active_session_by_robot.return_value = {
                'session_id': 11,
                'user_id': 'u1',
            }
            mock_db.get_cart_by_session.return_value = {'cart_id': 22}
            mock_db.has_unpaid_items.return_value = True

            rm = RobotManager()
            rm.start()
            rm.publish_cmd = MagicMock()
            rm.push_to_web = lambda rid, msg: web_msgs.append((rid, msg))

            rm.on_status('54', {
                'mode': 'TRACKING', 'pos_x': 0.0, 'pos_y': 0.0,
                'battery': 100.0, 'is_locked_return': False,
            })

            rm.on_customer_event('54', {'type': 'checkout_zone_enter'})

            rm.publish_cmd.assert_not_called()
            mock_db.end_session.assert_not_called()
            assert any(
                rid == '54' and m.get('type') == 'checkout_zone_enter'
                for rid, m in web_msgs
            )

    def test_empty_cart_non_tracking_mode_skips_auto_return(self):
        with patch('control_service.robot_manager.db') as mock_db:
            mock_db.get_all_robots.return_value = [
                {'robot_id': '54', 'current_mode': 'WAITING', 'pos_x': 0.0,
                 'pos_y': 0.0, 'battery_level': 100, 'is_locked_return': 0,
                 'active_user_id': 'u1'},
            ]
            mock_db.update_robot.return_value = None
            mock_db.log_event.return_value = None
            mock_db.log_staff_call.return_value = 1
            mock_db.get_active_session_by_robot.return_value = {
                'session_id': 11,
                'user_id': 'u1',
            }
            mock_db.get_cart_by_session.return_value = {'cart_id': 22}
            mock_db.has_unpaid_items.return_value = False

            rm = RobotManager()
            rm.start()
            rm.publish_cmd = MagicMock()

            rm.on_status('54', {
                'mode': 'WAITING', 'pos_x': 0.0, 'pos_y': 0.0,
                'battery': 100.0, 'is_locked_return': False,
            })

            rm.on_customer_event('54', {'type': 'checkout_zone_enter'})

            rm.publish_cmd.assert_not_called()
            mock_db.end_session.assert_not_called()


class TestGuidingYield:
    def test_guiding_remaining_empty_route(self):
        rm = make_rm()
        rm.on_status('54', {'mode': 'GUIDING', 'pos_x': 0.0, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        state = rm.get_state('54')
        state.dest_x = 3.0
        state.dest_y = 4.0
        # Empty route → fallback to straight-line pos→dest = 5.0
        assert abs(rm._guiding_remaining(state, []) - 5.0) < 1e-6

    def test_guiding_remaining_polyline(self):
        rm = make_rm()
        rm.on_status('54', {'mode': 'GUIDING', 'pos_x': 0.0, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        state = rm.get_state('54')
        route = [{'x': 1.0, 'y': 0.0}, {'x': 1.0, 'y': 3.0}, {'x': 4.0, 'y': 3.0}]
        # 0→(1,0) = 1.0; (1,0)→(1,3) = 3.0; (1,3)→(4,3) = 3.0. Total 7.0.
        assert abs(rm._guiding_remaining(state, route) - 7.0) < 1e-6

    def test_pick_yield_vertex_tier1_on_route_holding(self):
        rm = make_rm()
        # route_idx: [start=10, holding=11, conflict_entry=12, endpoint=13]
        route_idx = [10, 11, 12, 13]
        all_wps = [
            {'idx': 10, 'name': 'S', 'x': 0.0, 'y': 0.0, 'holding_point': False},
            {'idx': 11, 'name': 'H', 'x': 1.0, 'y': 0.0, 'holding_point': True},
            {'idx': 12, 'name': 'X', 'x': 2.0, 'y': 0.0, 'holding_point': False},
            {'idx': 13, 'name': 'Y', 'x': 3.0, 'y': 0.0, 'holding_point': False},
        ]
        # Conflict enters at edge (12,13) → entry_idx = 2; walk back from i=1 finds H
        winner_route = [99, 12, 13]
        pick = rm._pick_yield_vertex(
            route_idx, entry_idx=2,
            partner_route_idx=winner_route,
            partner_pos=(2.5, 0.0),
            my_pos=(0.0, 0.0),
            all_wps=all_wps,
        )
        assert pick is not None
        assert pick['name'] == 'H'

    def test_pick_yield_vertex_tier2_off_route_holding(self):
        rm = make_rm()
        # Route has NO holding_point before conflict.
        route_idx = [10, 12]  # S → X (immediate conflict at edge 0)
        all_wps = [
            {'idx': 10, 'name': 'S', 'x': 0.0, 'y': 0.0, 'holding_point': False},
            {'idx': 12, 'name': 'X', 'x': 2.0, 'y': 0.0, 'holding_point': False},
            # Off-route holding_point candidate (close to my_pos, far from partner)
            {'idx': 20, 'name': 'OFF', 'x': 0.2, 'y': 1.0, 'holding_point': True},
        ]
        pick = rm._pick_yield_vertex(
            route_idx, entry_idx=0,
            partner_route_idx=[99, 12],
            partner_pos=(2.0, 0.0),
            my_pos=(0.0, 0.0),
            all_wps=all_wps,
        )
        assert pick is not None
        assert pick['name'] == 'OFF'

    def test_pick_yield_vertex_tier3_no_candidate(self):
        rm = make_rm()
        route_idx = [10, 12]
        all_wps = [
            {'idx': 10, 'name': 'S', 'x': 0.0, 'y': 0.0, 'holding_point': False},
            {'idx': 12, 'name': 'X', 'x': 2.0, 'y': 0.0, 'holding_point': False},
        ]
        pick = rm._pick_yield_vertex(
            route_idx, entry_idx=0,
            partner_route_idx=[99, 12],
            partner_pos=(2.0, 0.0),
            my_pos=(0.0, 0.0),
            all_wps=all_wps,
        )
        assert pick is None

    def test_resolve_guiding_conflict_winner_proceeds(self):
        """Winner (잔여거리 짧은 쪽) 은 원 route 그대로 반환, should_proceed=True."""
        rm = make_rm()
        rm.on_status('54', {'mode': 'GUIDING', 'pos_x': 0.0, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        state = rm.get_state('54')
        state.dest_x = 1.0
        state.dest_y = 0.0

        rm._router.detect_conflict = MagicMock(return_value=None)
        route = [{'x': 0.0, 'y': 0.0}, {'x': 1.0, 'y': 0.0}]
        used, proceed = rm._resolve_guiding_conflict('54', route, {'zone_id': 22})
        assert proceed is True
        assert used == route

    def test_resolve_guiding_conflict_loser_events(self):
        """Loser 는 YIELD_HOLD event 를 push."""
        rm = make_rm()
        events = []
        rm._push_event = lambda rid, ev, **kw: events.append((rid, ev, kw.get('detail', '')))

        rm.on_status('54', {'mode': 'GUIDING', 'pos_x': 0.0, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        rm.on_status('18', {'mode': 'GUIDING', 'pos_x': 3.0, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        st54 = rm.get_state('54')
        st18 = rm.get_state('18')
        st54.dest_x = 10.0; st54.dest_y = 0.0  # 54 is far (loser)
        st18.dest_x = 3.5; st18.dest_y = 0.0   # 18 is close (winner)
        st18.path = [{'x': 3.0, 'y': 0.0}, {'x': 3.5, 'y': 0.0}]

        from control_service.fleet_router import ConflictInfo
        info = ConflictInfo(partner_id='18', conflict_entry_idx=1,
                            conflict_exit_idx=2, conflict_type='E_OPPOSE')
        rm._router.detect_conflict = MagicMock(return_value=info)
        rm._pick_yield_vertex = MagicMock(return_value={
            'idx': 99, 'name': 'HOLD', 'x': 0.5, 'y': 0.0, 'theta': 0.0,
        })
        rm._router.plan = MagicMock(return_value=[
            {'x': 0.0, 'y': 0.0}, {'x': 0.5, 'y': 0.0}])
        rm._router.reserve = MagicMock()
        rm._route_to_poses = MagicMock(return_value=[{'x': 0.5, 'y': 0.0, 'theta': 0.0}])
        rm._relay_to_pi = MagicMock()

        route = [{'x': 0.0, 'y': 0.0}, {'x': 1.0, 'y': 0.0}, {'x': 10.0, 'y': 0.0}]
        used, proceed = rm._resolve_guiding_conflict('54', route, {'zone_id': 22})
        assert proceed is False
        hold_events = [e for e in events if e[1] == 'YIELD_HOLD']
        assert len(hold_events) == 1
        assert '18' in hold_events[0][2]
        # loser payload preserved for resume
        assert rm._pending_navigate.get('54') == {'zone_id': 22}

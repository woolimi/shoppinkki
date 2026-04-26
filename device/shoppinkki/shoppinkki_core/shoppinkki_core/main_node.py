"""ShopPinkki main ROS 2 node entry point.

Wires together:
    ShoppinkkiFSM  ←→  BTRunner  ←→  BT1~BT5
    CmdHandler  (subscribes /robot_<id>/cmd)
    HWController (LED / LCD / buzzer)
    Status publisher  (/robot_<id>/status  @ 1 Hz)

Run with:
    ros2 run shoppinkki_core main_node
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import rclpy
import rclpy.time  # noqa: F401 — submodule 명시 (정적 분석기 경고 방지)
from rclpy.node import Node
from rclpy.qos import QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from std_msgs.msg import String

from .bt_runner import BTRunner
from .cart_session_manager import CartSessionManager
from .checkout_zone_guard import CheckoutZoneGuard
from .cmd_handler import CmdHandler
from .localization_manager import LocalizationManager
from .nav_manager import NavManager
from .vision_manager import VisionManager
from .config import (
    BATTERY_THRESHOLD,
    CHARGING_COMPLETE_THRESHOLD,
    CHARGER_ZONE_IDS,
    WAITING_TIMEOUT,
)
from .hw_controller import HWController
from .state_machine import ShoppinkkiFSM

try:
    from shoppinkki_nav.bt_tracking import create_tracking_tree
    from shoppinkki_nav.bt_searching import create_searching_tree
    from shoppinkki_nav.bt_waiting import create_waiting_tree
    from shoppinkki_nav.bt_guiding import create_guiding_tree
    from shoppinkki_nav.bt_returning import create_returning_tree
    _NAV_BT_AVAILABLE = True
except ImportError:
    _NAV_BT_AVAILABLE = False

# BT3 (WAITING) can load even when BT1/2 are Mock — timeout must still run in sim/dev.
try:
    from shoppinkki_nav.bt_waiting import create_waiting_tree as _create_waiting_bt3
except ImportError:
    _create_waiting_bt3 = None

logger = logging.getLogger(__name__)

# Robot ID is read from the environment variable ROBOT_ID (default '54')
ROBOT_ID = os.environ.get('ROBOT_ID', '54')


class ShoppinkkiMainNode(Node):
    """Main node: SM + BT Runner + HW + publishers/subscribers."""

    def __init__(self) -> None:
        super().__init__(f'shoppinkki_main_{ROBOT_ID}')
        self.get_logger().info(f'Starting ShopPinkki main node (robot_id={ROBOT_ID})')

        # ── Cart / Battery / Session / Zones / REST 매니저 ──
        # control_service REST /zones는 시작 시 1회 fetch (BT4 charger zone 등에서 사용).
        _cs_host = os.environ.get('CONTROL_SERVICE_HOST', '127.0.0.1')
        _cs_port = int(os.environ.get('CONTROL_SERVICE_PORT', '8081'))
        self._cart = CartSessionManager(
            self,
            robot_id=ROBOT_ID,
            control_service_base=f'http://{_cs_host}:{_cs_port}',
        )
        self._cart.fetch_zones(_cs_host, _cs_port)

        # ── State machine ─────────────────────
        self.sm = ShoppinkkiFSM(
            on_state_changed=self._on_state_changed,
            on_locked=self._on_locked,
            on_halted=self._on_halted,
            on_session_end=self._on_session_end,
        )

        # ── Hardware controller ────────────────
        self.hw = HWController(node=self, robot_id=ROBOT_ID)

        # ── Vision (camera + AI + stream + DollDetector 소유) ──
        # BT가 doll_detector를 참조하므로 BT 생성 이전에 인스턴스화 필요.
        self._vision = VisionManager(self, self.hw, sm=self.sm, robot_id=ROBOT_ID)

        # ── RobotPublisher (BT가 /cmd_vel 발행에 사용) ────────
        from .robot_publisher import RobotPublisher
        self._robot_publisher = RobotPublisher(node=self, robot_id=ROBOT_ID)

        # ── LiDAR 스캔 캐시 (장애물 회피용) ───────────────────
        from sensor_msgs.msg import LaserScan
        self._latest_scan: list = []
        self.create_subscription(
            LaserScan, f'/robot_{ROBOT_ID}/scan', self._scan_callback,
            QoSProfile(
                reliability=QoSReliabilityPolicy.BEST_EFFORT,
                history=QoSHistoryPolicy.KEEP_LAST, depth=1))

        # ── py_trees BT 생성 (BT1~BT5) ─────────────────────
        import py_trees
        if _NAV_BT_AVAILABLE and self._vision.doll_detector is not None:
            self._bt_tracking = create_tracking_tree(
                doll_detector=self._vision.doll_detector,
                publisher=self._robot_publisher,
                get_scan=self._get_forward_scan,
            )
            self._bt_searching = create_searching_tree(
                doll_detector=self._vision.doll_detector,
                publisher=self._robot_publisher,
                get_scan=self._get_forward_scan,
            )
            self._bt_waiting = create_waiting_tree(
                publisher=self._robot_publisher,
                get_scan=self._get_forward_scan,
            )
            self._bt_guiding = create_guiding_tree(
                publisher=self._robot_publisher,
            )
            charger_zone_id = CHARGER_ZONE_IDS.get(ROBOT_ID)
            charger_zone = self._cart.zones.get(charger_zone_id) if charger_zone_id else None

            def _get_parking_slot(z=charger_zone):
                if z is None:
                    return None
                return {
                    'zone_id': z.get('zone_id', charger_zone_id),
                    'waypoint_x': z['x'],
                    'waypoint_y': z['y'],
                    'waypoint_theta': z.get('theta', 0.0),
                }

            self._bt_returning = create_returning_tree(
                publisher=self._robot_publisher,
                robot_id=ROBOT_ID,
                get_parking_slot=_get_parking_slot,
            )
            self.get_logger().info('BT1~BT5: py_trees Behaviour 연결 완료')
        else:
            self._bt_tracking = py_trees.behaviours.Running(name='MockBT1')
            self._bt_searching = py_trees.behaviours.Running(name='MockBT2')
            if _create_waiting_bt3 is not None:
                self._bt_waiting = _create_waiting_bt3(
                    publisher=self._robot_publisher,
                    get_scan=self._get_forward_scan,
                )
                self.get_logger().info(
                    'BT3: WaitAndAvoid 사용 (BT1/2/4/5는 Mock — perception/nav 미설치)')
            else:
                self._bt_waiting = py_trees.behaviours.Running(name='MockBT3')
            self._bt_guiding = py_trees.behaviours.Running(name='MockBT4')
            self._bt_returning = py_trees.behaviours.Running(name='MockBT5')
            self.get_logger().warning('BT1/2/4/5: py_trees Mock (nav/perception 미설치)')

        # ── Nav2 매니저 (NavigateToPose / ThroughPoses 클라이언트 + 모드 전환) ──
        self._nav = NavManager(self, robot_id=ROBOT_ID)

        # BT5 RETURNING의 _get_current_pose가 LocalizationManager를 참조하므로
        # 아래 wire-up 전에 LocalizationManager를 먼저 생성해야 한다.
        self._localization = LocalizationManager(self, robot_id=ROBOT_ID)

        if self._nav.is_ready() or self._nav._nav2_client is not None:
            # Nav2 콜백 연결 (BT 인스턴스 속성으로 주입)
            if hasattr(self._bt_guiding, '_send_nav_goal'):
                self._bt_guiding._send_nav_goal = self._nav.send_goal_guiding
                self.get_logger().info('BT4 GUIDING: Nav2 connected (collision ON)')
            if hasattr(self._bt_guiding, '_send_nav_through_poses'):
                self._bt_guiding._send_nav_through_poses = self._nav._send_nav_through_poses
                self.get_logger().info('BT4 GUIDING: Nav2 through-poses connected')
            if hasattr(self._bt_returning, '_send_nav_goal'):
                self._bt_returning._send_nav_goal = self._nav._send_nav_goal
                self.get_logger().info('BT5 RETURNING: Nav2 send_nav_goal connected')
            if hasattr(self._bt_returning, '_set_nav2_mode'):
                self._bt_returning._set_nav2_mode = self._nav._set_nav2_mode
                self.get_logger().info('BT5 RETURNING: Nav2 mode switcher connected')

            # BT4 cancel_nav 확장: 로컬 플래그만 리셋하지 말고 실제 Nav2 action도 취소.
            if hasattr(self._bt_guiding, 'cancel_nav'):
                _bt_cancel = self._bt_guiding.cancel_nav

                def _cancel_with_action():
                    _bt_cancel()
                    self._nav.cancel_active()

                self._bt_guiding.cancel_nav = _cancel_with_action
                self.get_logger().info('BT4 GUIDING: cancel_nav wired to Nav2 action cancel')
            if hasattr(self._bt_returning, '_set_inflation'):
                self._bt_returning._set_inflation = self._nav._set_inflation
                self.get_logger().info('BT5 RETURNING: inflation switcher connected')
            if hasattr(self._bt_returning, '_get_current_pose'):
                self._bt_returning._get_current_pose = self._localization.get_live_pose
                self.get_logger().info('BT5 RETURNING: pose callback connected')
        else:
            self.get_logger().warning('nav2_msgs not available — admin_goto disabled')

        # ── BT runner ─────────────────────────
        self.bt_runner = BTRunner(
            sm=self.sm,
            bt_tracking=self._bt_tracking,
            bt_searching=self._bt_searching,
            bt_waiting=self._bt_waiting,
            bt_guiding=self._bt_guiding,
            bt_returning=self._bt_returning,
            on_arrived=self._on_arrived,
            on_nav_failed=self._on_nav_failed,
            doll_detector=self._vision.doll_detector,
            is_registration_active=self._vision.is_registration_active,
            is_tracking_grace_active=self._vision.is_tracking_grace_active,
            has_unpaid_items=self._cart.has_unpaid_items,
        )
        self.bt_runner.setup(node=self)

        # ── Cmd handler ───────────────────────
        self.cmd_handler = CmdHandler(
            sm=self.sm,
            on_navigate_to=self._on_navigate_to,
            on_navigate_through_poses=self._on_navigate_through_poses,
            on_delete_item=self._on_delete_item,
            on_admin_goto=self._on_admin_goto,
            on_start_session=self._on_start_session,
            has_unpaid_items=self._cart.has_unpaid_items,
            on_enter_registration=self._on_enter_registration,
            on_retake_registration=self._on_retake_registration,
            on_enter_simulation=self._on_enter_simulation,
            on_registration_confirm=self._on_registration_confirm,
            on_navigate_cancel=self._on_navigate_cancel,
        )

        # ── ROS publishers ────────────────────
        self._status_pub = self.create_publisher(
            String, f'/robot_{ROBOT_ID}/status', 10)
        self._alarm_pub = self.create_publisher(
            String, f'/robot_{ROBOT_ID}/alarm', 10)
        # NOTE: /robot_<id>/cart publisher는 CartSessionManager가 소유한다.
        # NOTE: /robot_<id>/snapshot publisher는 VisionManager가 소유한다.
        self._customer_event_pub = self.create_publisher(
            String, f'/robot_{ROBOT_ID}/customer_event', 10)

        # ── ROS subscribers ───────────────────
        self.create_subscription(
            String, f'/robot_{ROBOT_ID}/cmd',
            self._cmd_callback, 10)

        # ── Timers ────────────────────────────
        self.create_timer(0.05, self._bt_tick_callback)   # 20 Hz BT tick (increased for PID responsiveness)
        self.create_timer(1.0, self._status_pub_callback)  # 1 Hz status

        # ── 결제 구역 (BoundaryMonitor + CheckoutZoneGuard) ─────────────
        # REST에서 폴리곤 로드 → BoundaryMonitor 생성 → CheckoutZoneGuard로 래핑.
        # CheckoutZoneGuard가 LocalizationManager.on_pose_updated를 직접 wire한다.
        self._boundary_monitor: Optional[object] = None
        try:
            from shoppinkki_core.boundary_monitor import (
                BoundaryMonitor,
                load_boundaries_from_rest,
            )
            _bounds = load_boundaries_from_rest(_cs_host, _cs_port)
            self._boundary_monitor = BoundaryMonitor(
                boundaries=_bounds,
                # 콜백은 CheckoutZoneGuard 생성자에서 재배선됨.
                on_checkout_enter=None,
                on_checkout_exit_blocked=None,
                on_checkout_reenter=None,
                get_state=lambda: self.sm.state,
                node=None,
            )
            self._boundary_monitor.start()
            self.get_logger().info(
                f'BoundaryMonitor: {len(_bounds)} boundary row(s), checkout active'
            )
        except Exception as e:
            self.get_logger().warning(f'BoundaryMonitor unavailable: {e}')

        # CheckoutZoneGuard: BoundaryMonitor 콜백 + Localization wiring + hook.
        self._checkout = CheckoutZoneGuard(
            self,
            localization=self._localization,
            boundary_monitor=self._boundary_monitor,
            is_exit_allowed=lambda: self.sm.state in (
                'TRACKING_CHECKOUT', 'RETURNING'
            ),
        )
        self._checkout.on_zone_enter = self._emit_checkout_zone_enter
        self._checkout.on_exit_blocked = self._on_checkout_exit_blocked
        self._checkout.on_reenter = self._on_checkout_reenter

        self.hw.bind_registration_active(self._vision.is_registration_active)

        # ── Vision threads 시작 (camera + AI + stream) ─────────
        self._vision.start()

        self.get_logger().info('ShopPinkki main node ready')

    # ──────────────────────────────────────────
    # ROS callbacks
    # ──────────────────────────────────────────

    def _scan_callback(self, msg) -> None:
        """LiDAR 스캔 캐시 갱신 (BT1/BT2 장애물 회피용)."""
        self._latest_scan = list(msg.ranges)

    def _get_forward_scan(self) -> list:
        """BT에 전달할 LiDAR 거리 리스트."""
        return self._latest_scan

    def _emit_checkout_zone_enter(self) -> None:
        """CheckoutZoneGuard hook: 결제 구역 최초 진입 시 WebSocket 이벤트 요청."""
        payload = json.dumps({'type': 'checkout_zone_enter'})
        msg = String()
        msg.data = payload
        self._customer_event_pub.publish(msg)
        self.get_logger().info('Published customer_event checkout_zone_enter')

    def _on_checkout_exit_blocked(self) -> None:
        """CheckoutZoneGuard hook: 이탈 시도 처리 (허용 시 차단 해제, 아니면 차단)."""
        if self._checkout.is_exit_allowed():
            if hasattr(self._robot_publisher, 'set_motion_blocked'):
                self._robot_publisher.set_motion_blocked(False)
            return

        if hasattr(self._robot_publisher, 'set_motion_blocked'):
            self._robot_publisher.set_motion_blocked(True)

        # 웹 토스트용 이벤트 (rate-limit은 CheckoutZoneGuard가 관리)
        if self._checkout.should_emit_blocked_toast(min_interval_sec=1.0):
            payload = json.dumps({'type': 'checkout_blocked'})
            msg = String()
            msg.data = payload
            self._customer_event_pub.publish(msg)
            self.get_logger().info(
                'Published customer_event checkout_blocked (state=%s)',
                self.sm.state,
            )

    def _on_checkout_reenter(self) -> None:
        """CheckoutZoneGuard hook: 결제 구역 재진입 시 차단 해제."""
        if hasattr(self._robot_publisher, 'set_motion_blocked'):
            self._robot_publisher.set_motion_blocked(False)

    def _cmd_callback(self, msg: String) -> None:
        self.cmd_handler.handle(msg.data)

    def _bt_tick_callback(self) -> None:
        # Battery check (HALTED trigger)
        battery = self._cart.battery
        if battery < BATTERY_THRESHOLD and self.sm.state != 'HALTED':
            self.get_logger().warning(f'Battery low ({battery:.0f}%) → HALTED')
            self.sm.enter_halted()
            return
        # CHARGING → IDLE: 배터리 충분하면 자동 전환
        if self.sm.state == 'CHARGING' and battery >= CHARGING_COMPLETE_THRESHOLD:
            self.get_logger().info(f'Battery {battery:.0f}% >= {CHARGING_COMPLETE_THRESHOLD}% → IDLE')
            self.sm.charging_completed()
            return
        self.bt_runner.tick()

    def _status_pub_callback(self) -> None:
        self._localization._update_pos_from_tf()
        payload = json.dumps({
            'mode': self.sm.current_state,
            'pos_x': self._localization.pos_x,
            'pos_y': self._localization.pos_y,
            'yaw': self._localization.yaw,
            'battery': self._cart.battery,
            'is_locked_return': self.sm.is_locked_return,
            'follow_disabled': self._vision.get_follow_disabled(),
            'waiting_timeout_sec': int(WAITING_TIMEOUT),
        })
        msg = String()
        msg.data = payload
        self._status_pub.publish(msg)

    # ──────────────────────────────────────────
    # SM callbacks
    # ──────────────────────────────────────────

    def _on_state_changed(self, new_state: str) -> None:
        self.hw.set_led_for_state(new_state, self.sm.is_locked_return)
        # Avoid state redraws while registration camera feed is active.
        if not self._vision.is_registration_active():
            self.hw.set_lcd_for_state(new_state)
        self.bt_runner.on_state_changed(new_state)

    def _on_locked(self) -> None:
        alarm = json.dumps({'event': 'LOCKED'})
        msg = String()
        msg.data = alarm
        self._alarm_pub.publish(msg)
        self.hw.buzz('alert')

    def _on_halted(self) -> None:
        alarm = json.dumps({'event': 'HALTED'})
        msg = String()
        msg.data = alarm
        self._alarm_pub.publish(msg)
        self.hw.buzz('alert')

    def _on_session_end(self) -> None:
        self.get_logger().info('Session ended for robot %s' % ROBOT_ID)
        self._cart.clear_session()
        self._vision.set_follow_disabled(False)
        self.bt_runner.follow_disabled = False
        # 추종 데이터 소거 (gallery, safe_id, verification_buffer) + 등록 상태 리셋
        self._vision.reset_registration_after_session()

    # ──────────────────────────────────────────
    # CmdHandler callbacks
    # ──────────────────────────────────────────

    def _on_start_session(self, user_id: str) -> None:
        self.get_logger().info('Session started: user=%s' % user_id)
        self._cart.clear_session()
        self._vision.reset_detector()

    def _on_navigate_cancel(self) -> None:
        """fleet adapter에서 navigate_cancel 수신 — BT4 goal 취소."""
        if hasattr(self._bt_guiding, 'cancel_nav'):
            self._bt_guiding.cancel_nav()
        self.get_logger().info('navigate_cancel: BT4 stopped')

    def _on_navigate_to(self, zone_id: int, x: float, y: float, theta: float) -> None:
        self.get_logger().info(f'navigate_to zone={zone_id} ({x:.2f}, {y:.2f}, {theta:.2f})')
        if hasattr(self._bt_guiding, 'set_goal'):
            self._bt_guiding.set_goal(x, y, theta)

    def _on_navigate_through_poses(self, poses: list) -> None:
        """다중 경유점 navigate — BT4에 전체 경로 전달."""
        goal_poses = [(float(p['x']), float(p['y']), float(p.get('theta', 0.0)))
                      for p in poses]
        for i, (px, py, pt) in enumerate(goal_poses):
            self.get_logger().info('  through_pose[%d]: (%.3f, %.3f, θ=%.2f)' % (i, px, py, pt))
        self.get_logger().info('navigate_through_poses: %d waypoints' % len(goal_poses))
        if hasattr(self._bt_guiding, 'set_goals'):
            self._bt_guiding.set_goals(goal_poses)

    def _on_delete_item(self, item_id: int) -> None:
        self._cart.remove_item(item_id)

    def _on_enter_registration(self) -> None:
        """고객이 /register 페이지에 접속: LCD 카메라 피드 전환."""
        self._vision.enter_registration()

    def _on_retake_registration(self) -> None:
        """사용자가 [다시 찍기]를 눌렀을 때 새 후보 감지 재개."""
        self._vision.retake_registration()

    def _on_enter_simulation(self) -> None:
        """시뮬레이션 모드 진입: IDLE → TRACKING 전환 + 추종 비활성화."""
        if self.sm.state != 'IDLE':
            self.get_logger().debug(
                'enter_simulation: IDLE 아님 (state=%s), 무시', self.sm.state
            )
            return
        self.get_logger().info(
            'enter_simulation: IDLE → TRACKING (추종 비활성화)'
        )
        self._vision.set_follow_disabled(True)
        self.bt_runner.follow_disabled = True
        self.sm.enter_tracking()

    def _on_admin_goto(self, x: float, y: float, theta: float) -> None:
        self.get_logger().info('admin_goto: (%.2f, %.2f, %.2f)' % (x, y, theta))
        if not self._nav.is_ready():
            self.get_logger().warning('admin_goto: Nav2 not ready')
            return
        # 라이다 기반 장애물 회피 보장: inflation ON
        # (이전에 RETURNING에서 inflation OFF로 바꿔둔 상태일 수 있어 명시적으로 복원).
        try:
            self._nav._set_inflation(True)
        except Exception:
            pass
        self._nav.send_goal_async(x, y, theta, mode='guiding')

    def _on_arrived(self) -> None:
        self.get_logger().info('Arrived at destination')

    def _on_nav_failed(self) -> None:
        self.get_logger().warning('Navigation failed')

    # ──────────────────────────────────────────
    # 인형 등록 확인 콜백
    # ──────────────────────────────────────────

    def _on_registration_confirm(self, bbox: dict) -> None:
        """사용자가 앱에서 [확인]을 누르면 호출됨 (IDLE 상태).

        VisionManager에 confirm 위임 후 성공 시 FSM TRACKING 전환.
        """
        if self._vision.confirm_registration(bbox):
            self.sm.enter_tracking()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ShoppinkkiMainNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

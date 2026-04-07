"""ShopPinkki main ROS 2 node entry point.

Wires together:
    ShoppinkiSM  ←→  BTRunner  ←→  BT1~BT5
    CmdHandler  (subscribes /robot_<id>/cmd)
    HWController (LED / LCD / buzzer)
    Status publisher  (/robot_<id>/status  @ 1 Hz)

Run with:
    ros2 run shoppinkki_core main_node
"""

from __future__ import annotations

import json
import logging
import math
import os

import rclpy
import tf2_ros
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from std_msgs.msg import String

# Nav2 action client (optional — graceful fallback if nav2_msgs not installed)
try:
    from geometry_msgs.msg import PoseStamped
    from nav2_msgs.action import NavigateToPose
    from rclpy.action import ActionClient
    _NAV2_AVAILABLE = True
except ImportError:
    _NAV2_AVAILABLE = False

from .bt_runner import BTRunner
from .cmd_handler import CmdHandler
from .config import BATTERY_THRESHOLD, CHARGING_COMPLETE_THRESHOLD
from .hw_controller import HWController
from .state_machine import ShoppinkiSM

logger = logging.getLogger(__name__)

# Robot ID is read from the environment variable ROBOT_ID (default '54')
ROBOT_ID = os.environ.get('ROBOT_ID', '54')



class ShoppinkiMainNode(Node):
    """Main node: SM + BT Runner + HW + publishers/subscribers."""

    def __init__(self) -> None:
        super().__init__('shoppinkki_main_node')
        self.get_logger().info(f'Starting ShopPinkki main node (robot_id={ROBOT_ID})')

        # ── State machine ─────────────────────
        self.sm = ShoppinkiSM(
            on_state_changed=self._on_state_changed,
            on_locked=self._on_locked,
            on_halted=self._on_halted,
            on_session_end=self._on_session_end,
        )

        # ── Hardware controller ────────────────
        self.hw = HWController(node=self)

        # ── BT stubs (replaced by real BTs in shoppinkki_nav) ──────────
        # Import lazily so the node boots even without shoppinkki_nav built
        from shoppinkki_interfaces import MockNavBT
        self._bt_tracking = MockNavBT()
        self._bt_searching = MockNavBT()
        self._bt_waiting = MockNavBT()
        self._bt_guiding = MockNavBT()
        self._bt_returning = MockNavBT()

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
        )

        # ── Cmd handler ───────────────────────
        self.cmd_handler = CmdHandler(
            sm=self.sm,
            on_navigate_to=self._on_navigate_to,
            on_delete_item=self._on_delete_item,
            on_admin_goto=self._on_admin_goto,
            on_start_session=self._on_start_session,
            has_unpaid_items=self._has_unpaid_items,
            on_enter_simulation=self._on_enter_simulation,
        )

        # ── ROS publishers ────────────────────
        self._status_pub = self.create_publisher(
            String, f'/robot_{ROBOT_ID}/status', 10)
        self._alarm_pub = self.create_publisher(
            String, f'/robot_{ROBOT_ID}/alarm', 10)
        self._cart_pub = self.create_publisher(
            String, f'/robot_{ROBOT_ID}/cart', 10)

        # ── ROS subscribers ───────────────────
        self.create_subscription(
            String, f'/robot_{ROBOT_ID}/cmd',
            self._cmd_callback, 10)

        # ── Nav2 action client (admin_goto / navigate_to) ─────
        # 멀티로봇 환경에서 Nav2는 /robot_<id>/navigate_to_pose 로 실행됨
        self._nav2_client = None
        if _NAV2_AVAILABLE:
            nav2_action = f'robot_{ROBOT_ID}/navigate_to_pose'
            self._nav2_client = ActionClient(self, NavigateToPose, nav2_action)
            self.get_logger().info(f'Nav2 action client ready ({nav2_action})')
        else:
            self.get_logger().warning('nav2_msgs not available — admin_goto disabled')

        # ── Timers ────────────────────────────
        self.create_timer(0.1, self._bt_tick_callback)    # 10 Hz BT tick
        self.create_timer(1.0, self._status_pub_callback)  # 1 Hz status

        # ── TF 기반 위치 추적 ─────────────────
        # AMCL amcl_pose 토픽은 TF 에러 시 발행되지 않을 수 있으므로
        # TF lookup (map → base_footprint) 을 주 위치 소스로 사용.
        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self)
        self._base_frame = f'robot_{ROBOT_ID}/base_footprint'

        # AMCL amcl_pose 도 구독 (AMCL 수렴 후 더 정확한 위치 반영)
        amcl_qos = QoSProfile(
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            history=QoSHistoryPolicy.KEEP_LAST,
        )
        amcl_topic = f'/robot_{ROBOT_ID}/amcl_pose'
        self.create_subscription(
            PoseWithCovarianceStamped,
            amcl_topic,
            self._amcl_callback,
            amcl_qos,
        )
        self.get_logger().info(f'TF + AMCL pose tracking: {amcl_topic}')

        # ── Internal state ────────────────────
        self._pos_x: float = 0.0
        self._pos_y: float = 0.0
        self._yaw: float = 0.0
        self._battery: float = 100.0
        self._cart_items: list = []
        self.follow_disabled: bool = False

        self.get_logger().info('ShopPinkki main node ready')

    # ──────────────────────────────────────────
    # ROS callbacks
    # ──────────────────────────────────────────

    def _amcl_callback(self, msg: PoseWithCovarianceStamped) -> None:
        """AMCL 추정 위치를 내부 상태에 반영."""
        self._pos_x = msg.pose.pose.position.x
        self._pos_y = msg.pose.pose.position.y

    def _cmd_callback(self, msg: String) -> None:
        self.cmd_handler.handle(msg.data)

    def _bt_tick_callback(self) -> None:
        # Battery check (HALTED trigger)
        if self._battery < BATTERY_THRESHOLD and self.sm.state != 'HALTED':
            self.get_logger().warning(f'Battery low ({self._battery:.0f}%) → HALTED')
            self.sm.enter_halted()
            return
        # CHARGING → IDLE: 배터리 충분하면 자동 전환
        if self.sm.state == 'CHARGING' and self._battery >= CHARGING_COMPLETE_THRESHOLD:
            self.get_logger().info(f'Battery {self._battery:.0f}% >= {CHARGING_COMPLETE_THRESHOLD}% → IDLE')
            self.sm.charging_completed()
            return
        self.bt_runner.tick()

    def _update_pos_from_tf(self) -> None:
        """TF에서 map → base_footprint 변환을 조회하여 위치·방향 갱신."""
        try:
            t = self._tf_buffer.lookup_transform(
                'map', self._base_frame, rclpy.time.Time())
            self._pos_x = t.transform.translation.x
            self._pos_y = t.transform.translation.y
            # quaternion → yaw
            q = t.transform.rotation
            siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
            cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
            self._yaw = math.atan2(siny_cosp, cosy_cosp)
        except (tf2_ros.LookupException,
                tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException):
            pass  # TF 미사용 환경(실물 부팅 초기 등)에서는 amcl_pose 로 갱신

    def _status_pub_callback(self) -> None:
        self._update_pos_from_tf()
        payload = json.dumps({
            'mode': self.sm.current_state,
            'pos_x': self._pos_x,
            'pos_y': self._pos_y,
            'yaw': self._yaw,
            'battery': self._battery,
            'is_locked_return': self.sm.is_locked_return,
            'follow_disabled': self.follow_disabled,
        })
        msg = String()
        msg.data = payload
        self._status_pub.publish(msg)

    # ──────────────────────────────────────────
    # SM callbacks
    # ──────────────────────────────────────────

    def _on_state_changed(self, new_state: str) -> None:
        self.hw.set_led_for_state(new_state, self.sm.is_locked_return)
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
        self.get_logger().info('Session ended for robot %s', ROBOT_ID)
        self._cart_items = []
        self.follow_disabled = False
        self.bt_runner.follow_disabled = False

    # ──────────────────────────────────────────
    # CmdHandler callbacks
    # ──────────────────────────────────────────

    def _on_start_session(self, user_id: str) -> None:
        self.get_logger().info('Session started: user=%s', user_id)

    def _on_navigate_to(self, zone_id: int, x: float, y: float, theta: float) -> None:
        self.get_logger().info('navigate_to zone=%d (%.2f, %.2f, %.2f)',
                               zone_id, x, y, theta)
        # BT4 (bt_guiding) receives the goal via its own Nav2 client
        # Here we just log; BT4 reads the goal from a shared data object
        if hasattr(self._bt_guiding, 'set_goal'):
            self._bt_guiding.set_goal(x, y, theta)

    def _on_delete_item(self, item_id: int) -> None:
        self.get_logger().info('delete_item: id=%d', item_id)
        self._cart_items = [i for i in self._cart_items if i.get('id') != item_id]

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
        self.follow_disabled = True
        self.bt_runner.follow_disabled = True
        self.sm.enter_tracking()

    def _on_admin_goto(self, x: float, y: float, theta: float) -> None:
        self.get_logger().info('admin_goto: (%.2f, %.2f, %.2f)', x, y, theta)
        if self._nav2_client is None:
            self.get_logger().warning('admin_goto: nav2_msgs not available')
            return
        if not self._nav2_client.server_is_ready():
            self.get_logger().warning('admin_goto: Nav2 action server not ready')
            return

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = PoseStamped()
        goal_msg.pose.header.frame_id = 'map'
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = x
        goal_msg.pose.pose.position.y = y
        goal_msg.pose.pose.orientation.z = math.sin(theta / 2.0)
        goal_msg.pose.pose.orientation.w = math.cos(theta / 2.0)

        self._nav2_client.send_goal_async(goal_msg)
        self.get_logger().info('admin_goto: Nav2 goal sent → (%.2f, %.2f)', x, y)

    def _on_arrived(self) -> None:
        self.get_logger().info('Arrived at destination')

    def _on_nav_failed(self) -> None:
        self.get_logger().warning('Navigation failed')

    def _has_unpaid_items(self) -> bool:
        return any(not item.get('is_paid', True) for item in self._cart_items)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ShoppinkiMainNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

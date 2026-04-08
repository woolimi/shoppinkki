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

import base64
import json
import logging
import math
import os
import threading
import time

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

try:
    from shoppinkki_perception.doll_detector import DollDetector
    _PERCEPTION_AVAILABLE = True
except ImportError:
    _PERCEPTION_AVAILABLE = False

try:
    from pinkylib import Camera as PinkyCamera
    _PINKYLIB_AVAILABLE = True
except ImportError:
    _PINKYLIB_AVAILABLE = False

logger = logging.getLogger(__name__)

# Robot ID is read from the environment variable ROBOT_ID (default '54')
ROBOT_ID = os.environ.get('ROBOT_ID', '54')



class ShoppinkiMainNode(Node):
    """Main node: SM + BT Runner + HW + publishers/subscribers."""

    def __init__(self) -> None:
        super().__init__(f'shoppinkki_main_node_{ROBOT_ID}')
        self.get_logger().info(f'Starting ShopPinkki main node (robot_id={ROBOT_ID})')

        # ── State machine ─────────────────────
        self.sm = ShoppinkiSM(
            on_state_changed=self._on_state_changed,
            on_locked=self._on_locked,
            on_halted=self._on_halted,
            on_session_end=self._on_session_end,
        )

        # ── Hardware controller ────────────────
        self.hw = HWController(node=self, robot_id=ROBOT_ID)

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

        # ── DollDetector ──────────────────────
        YOLO_HOST = os.environ.get('YOLO_HOST', '127.0.0.1')
        YOLO_PORT = int(os.environ.get('YOLO_PORT', '5005'))
        if _PERCEPTION_AVAILABLE:
            self.doll_detector = DollDetector(
                yolo_host=YOLO_HOST, yolo_port=YOLO_PORT)
            self.get_logger().info(
                f'DollDetector 초기화 (YOLO {YOLO_HOST}:{YOLO_PORT})')
        else:
            self.doll_detector = None
            self.get_logger().warning('shoppinkki_perception 미설치 — DollDetector 비활성화')

        # ── Cmd handler ───────────────────────
        self.cmd_handler = CmdHandler(
            sm=self.sm,
            on_navigate_to=self._on_navigate_to,
            on_delete_item=self._on_delete_item,
            on_admin_goto=self._on_admin_goto,
            on_start_session=self._on_start_session,
            has_unpaid_items=self._has_unpaid_items,
            on_enter_registration=self._on_enter_registration,
            on_enter_simulation=self._on_enter_simulation,
            on_registration_confirm=self._on_registration_confirm,
        )

        # ── ROS publishers ────────────────────
        self._status_pub = self.create_publisher(
            String, f'/robot_{ROBOT_ID}/status', 10)
        self._alarm_pub = self.create_publisher(
            String, f'/robot_{ROBOT_ID}/alarm', 10)
        self._cart_pub = self.create_publisher(
            String, f'/robot_{ROBOT_ID}/cart', 10)
        self._snapshot_pub = self.create_publisher(
            String, f'/robot_{ROBOT_ID}/snapshot', 10)

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

        # ── 카메라 / 스냅샷 상태 ───────────────
        self._cam_frame = None              # 최신 카메라 프레임 (numpy BGR)
        self._last_snapshot_time: float = 0.0  # 스냅샷 rate-limit (2초)
        self._snapshot_rate_limit: float = 2.0
        # 고객이 /register 페이지에 접속했을 때 True → LCD 카메라 피드 표시
        self._registration_active: bool = False

        # ── 카메라 스레드 ─────────────────────
        self._cam_thread = threading.Thread(
            target=self._camera_loop, daemon=True)
        self._cam_thread.start()

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
        self.get_logger().info(f'Session ended for robot {ROBOT_ID}')
        self._cart_items = []
        self.follow_disabled = False
        self.bt_runner.follow_disabled = False
        self._registration_active = False
        # 추종 데이터 소거 (gallery, safe_id, verification_buffer)
        if self.doll_detector is not None:
            self.doll_detector.reset()

    # ──────────────────────────────────────────
    # CmdHandler callbacks
    # ──────────────────────────────────────────

    def _on_start_session(self, user_id: str) -> None:
        self.get_logger().info(f'Session started: user={user_id}')

    def _on_navigate_to(self, zone_id: int, x: float, y: float, theta: float) -> None:
        self.get_logger().info(f'navigate_to zone={zone_id} ({x:.2f}, {y:.2f}, {theta:.2f})')
        if self._nav2_client is None:
            self.get_logger().warning('navigate_to: nav2_msgs not available')
            return
        if not self._nav2_client.server_is_ready():
            self.get_logger().warning('navigate_to: Nav2 action server not ready')
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
        self.get_logger().info(f'navigate_to: Nav2 goal sent → ({x:.2f}, {y:.2f})')

    def _on_delete_item(self, item_id: int) -> None:
        self.get_logger().info(f'delete_item: id={item_id}')
        self._cart_items = [i for i in self._cart_items if i.get('id') != item_id]

    def _on_enter_registration(self) -> None:
        """고객이 /register 페이지에 접속: LCD 카메라 피드 전환."""
        self._registration_active = True
        self.get_logger().info('enter_registration: 카메라 피드 활성화')

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
        self.get_logger().info(f'admin_goto: ({x:.2f}, {y:.2f}, {theta:.2f})')
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
        self.get_logger().info(f'admin_goto: Nav2 goal sent → ({x:.2f}, {y:.2f})')

    def _on_arrived(self) -> None:
        self.get_logger().info('Arrived at destination')

    def _on_nav_failed(self) -> None:
        self.get_logger().warning('Navigation failed')

    def _has_unpaid_items(self) -> bool:
        return any(not item.get('is_paid', True) for item in self._cart_items)

    # ──────────────────────────────────────────
    # 카메라 루프 (별도 스레드)
    # ──────────────────────────────────────────

    def _camera_loop(self) -> None:
        """카메라 프레임을 읽어 상태에 따라 처리하는 백그라운드 스레드.

        - IDLE    : LCD 피드 표시 + 인형 감지 시 snapshot 발행
        - TRACKING / TRACKING_CHECKOUT : doll_detector.run() 호출
        """
        try:
            import cv2
        except ImportError:
            self.get_logger().warning('cv2 없음 — 카메라 루프 비활성화')
            return

        if not _PINKYLIB_AVAILABLE:
            self.get_logger().warning('pinkylib 없음 — camera loop를 VideoCapture(0)으로 전환 시도')
            cap = cv2.VideoCapture(int(os.environ.get('CAMERA_INDEX', '0')))
        else:
            try:
                cap = PinkyCamera()
                cap.start()
                self.get_logger().info('pinkylib.Camera started')
            except Exception as e:
                self.get_logger().warning(f'pinkylib.Camera 시작 실패: {e} — VideoCapture(0)으로 전환')
                cap = cv2.VideoCapture(int(os.environ.get('CAMERA_INDEX', '0')))

        if not cap.isOpened() if not _PINKYLIB_AVAILABLE or isinstance(cap, cv2.VideoCapture) else False:
             self.get_logger().warning(f'카메라 열기 실패 — 카메라 루프 종료')
             return

        self.get_logger().info(f'카메라 루프 시작')

        _CAM_STATES = {'IDLE', 'TRACKING', 'TRACKING_CHECKOUT'}

        while rclpy.ok():
            state = self.sm.state

            # 카메라가 불필요한 상태 → 프레임 읽기 건너뜀
            if state not in _CAM_STATES:
                time.sleep(0.2)
                continue

            if _PINKYLIB_AVAILABLE and isinstance(cap, PinkyCamera):
                frame_rgb = cap.get_frame()
                if frame_rgb is None:
                    time.sleep(0.05)
                    continue
                # BGR로 변환 (기존 시스템 스펙)
                frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            else:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

            self._cam_frame = frame

            if state == 'IDLE' and self._registration_active:
                # 고객이 /register 접속 중 — LCD 카메라 피드 표시
                self.hw.display_frame(frame)
                # 인형 감지 → pending_snapshot 갱신
                if self.doll_detector is not None:
                    self.doll_detector.register(frame)

                # rate-limit: 2초마다 snapshot 발행
                snapshot = self.doll_detector.get_pending_snapshot()
                now = time.time()
                if snapshot and (now - self._last_snapshot_time) >= self._snapshot_rate_limit:
                    self._last_snapshot_time = now
                    jpeg_bytes, bbox = snapshot
                    b64 = base64.b64encode(jpeg_bytes).decode('ascii')
                    msg = String()
                    msg.data = json.dumps({
                        'robot_id': ROBOT_ID,
                        'image': b64,
                        'bbox': bbox,
                    })
                    self._snapshot_pub.publish(msg)
                    self.get_logger().debug('snapshot 발행 (bbox conf=%.2f)',
                                            bbox.get('confidence', 0))

            elif state in ('TRACKING', 'TRACKING_CHECKOUT'):
                if self.doll_detector is not None:
                    self.doll_detector.run(frame)

        if _PINKYLIB_AVAILABLE and isinstance(cap, PinkyCamera):
            cap.close()
        elif hasattr(cap, 'release'):
            cap.release()

    # ──────────────────────────────────────────
    # 인형 등록 확인 콜백
    # ──────────────────────────────────────────

    def _on_registration_confirm(self, bbox: dict) -> None:
        """사용자가 앱에서 [확인]을 누르면 호출됨 (IDLE 상태).

        최신 카메라 프레임 + bbox로 DollDetector 템플릿 등록 후 TRACKING 진입.
        """
        frame = self._cam_frame
        if frame is None:
            self.get_logger().warning('registration_confirm: 카메라 프레임 없음')
            return
        if self.doll_detector is None:
            self.get_logger().warning('registration_confirm: DollDetector 없음')
            return

        self.doll_detector.confirm_registration(frame, bbox)
        self.get_logger().info('registration_confirm: 등록 완료 → TRACKING 진입')
        self._registration_active = False
        self.sm.enter_tracking()


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

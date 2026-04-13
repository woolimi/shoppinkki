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
from typing import Optional
import struct
import cv2
import numpy as np

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
from .config import BATTERY_THRESHOLD, CHARGING_COMPLETE_THRESHOLD, CHARGER_ZONE_IDS
from shoppinkki_nav.nav2_client import fetch_all_zones
from .hw_controller import HWController
from .state_machine import ShoppinkiSM

try:
    from shoppinkki_perception.doll_detector import DollDetector
    _PERCEPTION_AVAILABLE = True
except ImportError:
    _PERCEPTION_AVAILABLE = False

try:
    from shoppinkki_nav.bt_tracking import create_tracking_tree
    from shoppinkki_nav.bt_searching import create_searching_tree
    from shoppinkki_nav.bt_waiting import create_waiting_tree
    from shoppinkki_nav.bt_guiding import create_guiding_tree
    from shoppinkki_nav.bt_returning import create_returning_tree
    _NAV_BT_AVAILABLE = True
except ImportError:
    _NAV_BT_AVAILABLE = False

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
        super().__init__(f'shoppinkki_main_{ROBOT_ID}')
        self.get_logger().info(f'Starting ShopPinkki main node (robot_id={ROBOT_ID})')

        # ── Zone cache (control_service REST /zones, 시작 시 1회 fetch) ──
        _cs_host = os.environ.get('CONTROL_SERVICE_HOST', '127.0.0.1')
        _cs_port = int(os.environ.get('CONTROL_SERVICE_PORT', '8081'))
        self._zones: dict[int, dict] = fetch_all_zones(_cs_host, _cs_port)

        # ── State machine ─────────────────────
        self.sm = ShoppinkiSM(
            on_state_changed=self._on_state_changed,
            on_locked=self._on_locked,
            on_halted=self._on_halted,
            on_session_end=self._on_session_end,
        )

        # ── Hardware controller ────────────────
        self.hw = HWController(node=self, robot_id=ROBOT_ID)

        # ── DollDetector (BT보다 먼저 생성 — BT1/BT2가 참조) ──────
        YOLO_HOST = os.environ.get('YOLO_HOST', '127.0.0.1')
        YOLO_PORT = int(os.environ.get('YOLO_PORT', '5005'))
        DOLL_MODEL_PATH = os.environ.get(
            'DOLL_MODEL_PATH',
            '/home/pinky/ros_ws/server/ai_service/yolo/models/best1.pt'
        )
        if _PERCEPTION_AVAILABLE:
            self.doll_detector = DollDetector(
                yolo_host=YOLO_HOST, yolo_port=YOLO_PORT,
                model_path=DOLL_MODEL_PATH)
            self.get_logger().info(
                f'DollDetector 초기화 (YOLO {YOLO_HOST}:{YOLO_PORT}, model={DOLL_MODEL_PATH})')
        else:
            self.doll_detector = None
            self.get_logger().warning('shoppinkki_perception 미설치 — DollDetector 비활성화')

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
        if _NAV_BT_AVAILABLE and self.doll_detector is not None:
            self._bt_tracking = create_tracking_tree(
                doll_detector=self.doll_detector,
                publisher=self._robot_publisher,
                get_scan=self._get_forward_scan,
            )
            self._bt_searching = create_searching_tree(
                doll_detector=self.doll_detector,
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
            charger_zone = self._zones.get(charger_zone_id) if charger_zone_id else None

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
            self._bt_waiting = py_trees.behaviours.Running(name='MockBT3')
            self._bt_guiding = py_trees.behaviours.Running(name='MockBT4')
            self._bt_returning = py_trees.behaviours.Running(name='MockBT5')
            self.get_logger().warning('BT1~BT5: py_trees Mock (nav/perception 미설치)')

        # ── Nav2 action client (admin_goto / navigate_to) ─────
        self._nav2_client = None
        if _NAV2_AVAILABLE:
            nav2_action = f'robot_{ROBOT_ID}/navigate_to_pose'
            self._nav2_client = ActionClient(self, NavigateToPose, nav2_action)
            self.get_logger().info(f'Nav2 action client ready ({nav2_action})')

            # Nav2 콜백 연결
            if hasattr(self._bt_guiding, '_send_nav_goal'):
                self._bt_guiding._send_nav_goal = self._send_nav_goal_guiding
                self.get_logger().info('BT4 GUIDING: Nav2 connected (collision ON)')
            if hasattr(self._bt_returning, '_send_nav_goal'):
                self._bt_returning._send_nav_goal = self._send_nav_goal
                self.get_logger().info('BT5 RETURNING: Nav2 send_nav_goal connected')
            if hasattr(self._bt_returning, '_set_nav2_mode'):
                self._bt_returning._set_nav2_mode = self._set_nav2_mode
                self.get_logger().info('BT5 RETURNING: Nav2 mode switcher connected')
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
            doll_detector=self.doll_detector,
            is_registration_active=lambda: self._registration_active,
            is_tracking_grace_active=self._is_tracking_grace_active,
        )
        self.bt_runner.setup(node=self)

        # ── Cmd handler ───────────────────────
        self.cmd_handler = CmdHandler(
            sm=self.sm,
            on_navigate_to=self._on_navigate_to,
            on_delete_item=self._on_delete_item,
            on_admin_goto=self._on_admin_goto,
            on_start_session=self._on_start_session,
            has_unpaid_items=self._has_unpaid_items,
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
        self._cart_pub = self.create_publisher(
            String, f'/robot_{ROBOT_ID}/cart', 10)
        self._snapshot_pub = self.create_publisher(
            String, f'/robot_{ROBOT_ID}/snapshot', 10)
        self._customer_event_pub = self.create_publisher(
            String, f'/robot_{ROBOT_ID}/customer_event', 10)

        # ── ROS subscribers ───────────────────
        self.create_subscription(
            String, f'/robot_{ROBOT_ID}/cmd',
            self._cmd_callback, 10)

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

        # ── 결제 구역 (BoundaryMonitor) ── REST에서 폴리곤 로드, AMCL로 진입 감지
        self._boundary_monitor: Optional[object] = None
        try:
            from shoppinkki_core.boundary_monitor import (
                BoundaryMonitor,
                load_boundaries_from_rest,
            )
            _bounds = load_boundaries_from_rest(_cs_host, _cs_port)
            self._boundary_monitor = BoundaryMonitor(
                boundaries=_bounds,
                on_checkout_enter=self._emit_checkout_zone_enter,
                get_state=lambda: self.sm.state,
                node=None,
            )
            self._boundary_monitor.start()
            self.get_logger().info(
                f'BoundaryMonitor: {len(_bounds)} boundary row(s), checkout active'
            )
        except Exception as e:
            self.get_logger().warning(f'BoundaryMonitor unavailable: {e}')

        # ── Internal state ────────────────────
        self._pos_x: float = 0.0
        self._pos_y: float = 0.0
        self._yaw: float = 0.0
        self._battery: float = 100.0
        self._cart_items: list = []
        self.follow_disabled: bool = False

        # ── 카메라 / 스냅샷 상태 ───────────────
        self._cam_frame = None              # 최신 카메라 프레임 (numpy BGR)
        self._last_snapshot_time: float = 0.0  # 스냅샷 rate-limit (0.5초)
        self._snapshot_rate_limit: float = 0.5
        # 고객이 /register 페이지에 접속했을 때 True → LCD 카메라 피드 표시
        self._registration_active: bool = False
        # True after a snapshot is sent; waits for confirm/retake.
        self._registration_waiting_confirm: bool = False
        self._tracking_grace_until: float = 0.0
        self.hw.bind_registration_active(lambda: self._registration_active)

        # ── 카메라 및 AI 스레드 ─────────────────
        self._cam_frame: Optional[np.ndarray] = None
        self._ai_frame: Optional[np.ndarray] = None
        self._ai_event = threading.Event()
        self._ai_thread = threading.Thread(target=self._ai_loop, daemon=True)
        self._ai_thread.start()

        # ── Live Streamer (Laptop Monitor용) ─────────────────
        self._stream_frame: Optional[bytes] = None
        self._stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._stream_thread.start()

        # ── 카메라 스레드 ─────────────────────
        self._cam_thread = threading.Thread(
            target=self._camera_loop, daemon=True)
        self._cam_thread.start()

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

    def _amcl_callback(self, msg: PoseWithCovarianceStamped) -> None:
        """AMCL 추정 위치를 내부 상태에 반영."""
        self._pos_x = msg.pose.pose.position.x
        self._pos_y = msg.pose.pose.position.y
        if self._boundary_monitor is not None:
            self._boundary_monitor.on_pose_update(self._pos_x, self._pos_y)

    def _emit_checkout_zone_enter(self) -> None:
        """TRACKING 상태에서 결제 구역 최초 진입 시 control_service로 WebSocket 이벤트 요청."""
        payload = json.dumps({'type': 'checkout_zone_enter'})
        msg = String()
        msg.data = payload
        self._customer_event_pub.publish(msg)
        self.get_logger().info('Published customer_event checkout_zone_enter')

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

    def _get_live_pose(self) -> tuple[float, float, float]:
        """TF에서 실시간 위치 조회 (후진 도킹용)."""
        try:
            t = self._tf_buffer.lookup_transform(
                'map', self._base_frame, rclpy.time.Time())
            x = t.transform.translation.x
            y = t.transform.translation.y
            q = t.transform.rotation
            yaw = math.atan2(
                2.0 * (q.w * q.z + q.x * q.y),
                1.0 - 2.0 * (q.y * q.y + q.z * q.z))
            return (x, y, yaw)
        except Exception:
            return (self._pos_x, self._pos_y, self._yaw)

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
        # Avoid state redraws while registration camera feed is active.
        if not self._registration_active:
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
        self.get_logger().info('Session started: user=%s' % user_id)
        if self.doll_detector: self.doll_detector.reset()

    def _on_navigate_cancel(self) -> None:
        """fleet adapter에서 navigate_cancel 수신 — BT4 goal 취소."""
        if hasattr(self._bt_guiding, 'cancel_nav'):
            self._bt_guiding.cancel_nav()
        self.get_logger().info('navigate_cancel: BT4 stopped')

    def _on_navigate_to(self, zone_id: int, x: float, y: float, theta: float) -> None:
        self.get_logger().info(f'navigate_to zone={zone_id} ({x:.2f}, {y:.2f}, {theta:.2f})')
        if hasattr(self._bt_guiding, 'set_goal'):
            self._bt_guiding.set_goal(x, y, theta)

    def _on_delete_item(self, item_id: int) -> None:
        self.get_logger().info('delete_item: id=%d' % item_id)
        self._cart_items = [i for i in self._cart_items if i.get('id') != item_id]

    def _on_enter_registration(self) -> None:
        """고객이 /register 페이지에 접속: LCD 카메라 피드 전환."""
        self._registration_active = True
        self._registration_waiting_confirm = False
        self.get_logger().info('enter_registration: 카메라 피드 활성화')

    def _on_retake_registration(self) -> None:
        """사용자가 [다시 찍기]를 눌렀을 때 새 후보 감지 재개."""
        self._registration_waiting_confirm = False
        if self.doll_detector is not None:
            self.doll_detector.clear_pending_snapshot()

    def _is_tracking_grace_active(self) -> bool:
        return time.monotonic() < self._tracking_grace_until

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

    _current_nav2_mode: str = ''

    def _set_nav2_mode(self, mode: str) -> None:
        """Nav2 파라미터를 GUIDING/RETURNING 모드에 맞게 동적 전환.

        모드가 같으면 스킵. 유일한 차이: allow_reversing (returning=true).
        """
        if mode == self._current_nav2_mode:
            return
        self._current_nav2_mode = mode

        import subprocess
        ns = f'robot_{ROBOT_ID}'
        reversing = 'true' if mode == 'returning' else 'false'

        try:
            subprocess.run(
                ['ros2', 'param', 'set', f'/{ns}/controller_server',
                 'FollowPath.allow_reversing', reversing],
                capture_output=True, timeout=10)
        except Exception as e:
            self.get_logger().warning('set_nav2_mode: %s' % e)
        self.get_logger().info('Nav2 mode → %s (reversing=%s)' % (mode, reversing))

    def _send_nav_goal_guiding(self, x: float, y: float, theta: float) -> bool:
        """GUIDING 모드: collision detection ON, 벽에서 떨어진 경로."""
        self._set_nav2_mode('guiding')
        return self._send_nav_goal(x, y, theta)

    def _send_nav_goal_returning(self, x: float, y: float, theta: float) -> bool:
        """RETURNING 모드: collision detection OFF, 벽까지 도달 가능."""
        self._set_nav2_mode('returning')
        return self._send_nav_goal(x, y, theta)

    def _send_nav_goal(self, x: float, y: float, theta: float) -> bool:
        """Nav2 NavigateToPose 동기 호출 — BT4/BT5 콜백용 (threading.Event 기반)."""
        if self._nav2_client is None or not self._nav2_client.server_is_ready():
            self.get_logger().warning('send_nav_goal: Nav2 not ready')
            return False

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = PoseStamped()
        goal_msg.pose.header.frame_id = 'map'
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = x
        goal_msg.pose.pose.position.y = y
        goal_msg.pose.pose.orientation.z = math.sin(theta / 2.0)
        goal_msg.pose.pose.orientation.w = math.cos(theta / 2.0)

        self.get_logger().info('send_nav_goal: (%.2f, %.2f, θ=%.2f)' % (x, y, theta))

        done_event = threading.Event()
        result_holder: list = [None]

        def _goal_response(future):
            goal_handle = future.result()
            if goal_handle is None or not goal_handle.accepted:
                self.get_logger().warning('send_nav_goal: goal rejected')
                done_event.set()
                return
            result_holder.append(goal_handle)
            goal_handle.get_result_async().add_done_callback(_result_response)

        def _result_response(future):
            result_holder[0] = future.result()
            done_event.set()

        self._nav2_client.send_goal_async(goal_msg).add_done_callback(_goal_response)
        done_event.wait(timeout=120.0)

        result = result_holder[0]
        if result is None:
            self.get_logger().warning('send_nav_goal: timeout or rejected')
            return False

        from action_msgs.msg import GoalStatus
        if result.status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info('send_nav_goal: succeeded')
            return True
        else:
            self.get_logger().warning('send_nav_goal: failed (status=%d)' % result.status)
            return False

    def _on_admin_goto(self, x: float, y: float, theta: float) -> None:
        self.get_logger().info('admin_goto: (%.2f, %.2f, %.2f)' % (x, y, theta))
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
        self.get_logger().info('admin_goto: Nav2 goal sent → (%.2f, %.2f)' % (x, y))

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

        _CAM_STATES = {'IDLE', 'TRACKING', 'TRACKING_CHECKOUT', 'SEARCHING'}

        while rclpy.ok():
            state = self.sm.state

            # 카메라가 불필요한 상태 → 프레임 읽기 건너뜜
            if state not in _CAM_STATES:
                time.sleep(0.2)
                continue

            if _PINKYLIB_AVAILABLE and isinstance(cap, PinkyCamera):
                frame = cap.get_frame()
                if frame is None:
                    time.sleep(0.05)
                    continue
            else:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

            self._cam_frame = frame
            # Process for AI (Now standardizing on BGR native)
            self._ai_frame = frame.copy() if frame is not None else None
            self._ai_event.set()

            # LCD 업데이트 (지연 없이 즉시)
            show_debug = self.doll_detector is not None and getattr(self.doll_detector, 'show_all_detections', False)
            
            connected = self.doll_detector.is_connected() if self.doll_detector else False
            det_count = self.doll_detector.get_latest_count() if self.doll_detector else 0

            # [UNSTOPPABLE DISPLAY] Registration check FIRST — always wins over state
            if self._registration_active:
                # Rate-limit to ~12fps during registration (blur is CPU-heavy, SPI needs time)
                now = time.monotonic()
                if not hasattr(self, '_last_reg_frame_t') or (now - self._last_reg_frame_t) >= 0.083:
                    self._last_reg_frame_t = now
                    self.hw.display_frame(frame, connected=connected, det_count=det_count, is_registration=True, mirror=True)
            elif state in ('TRACKING', 'TRACKING_CHECKOUT', 'SEARCHING'):
                det = self.doll_detector.get_latest() if self.doll_detector else None
                if det:
                    self.hw.draw_detection(frame, det)
                self.hw.display_frame(frame, connected=connected, det_count=det_count, mirror=True)
            elif state == 'IDLE':
                # IDLE without registration: show QR, don't override with camera
                pass
            elif show_debug:
                det = self.doll_detector.get_latest() if self.doll_detector else None
                if det:
                    self.hw.draw_detection(frame, det)
                self.hw.display_frame(frame, connected=connected, det_count=det_count, mirror=True)
            else:
                self.hw.display_frame(frame, connected=connected, det_count=det_count, mirror=True)

            # 스트림용 JPEG 인코딩
            _, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
            self._stream_frame = jpeg.tobytes()

        if _PINKYLIB_AVAILABLE and isinstance(cap, PinkyCamera):
            cap.close()
        elif hasattr(cap, 'release'):
            cap.release()

    def _ai_loop(self) -> None:
        """AI 연산을 수행하는 백그라운드 스레드.
        
        카메라 루프에서 신호를 받으면 최신 프레임에 대해 YOLO 및 ReID를 수행한다.
        네트워킹/연산 지연이 LCD 피드에 영향을 주지 않도록 분리됨.
        """
        while rclpy.ok():
            # 신호 대기 (Timeout을 두어 rclpy.ok() 체크 기회 확보)
            if not self._ai_event.wait(timeout=1.0):
                continue
            
            self._ai_event.clear()
            frame = self._ai_frame
            if frame is None:
                continue

            state = self.sm.state

            if self.doll_detector is not None:
                show_debug = getattr(self.doll_detector, 'show_all_detections', False)
                
                if state == 'IDLE' and self._registration_active:
                    # 인형 등록 중 (Snapshot 쿼리)
                    if not self._registration_waiting_confirm:
                        self.doll_detector.register(frame)
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
                            self._registration_waiting_confirm = True
                            # Keep pending confirm frame/bbox in detector for exact confirm.
                            self.doll_detector.clear_pending_snapshot()
                elif (state in ('TRACKING', 'TRACKING_CHECKOUT', 'SEARCHING') or show_debug) and not self._registration_active:
                    # 추종 중이거나 디버그 모드일 때 실시간 감지 실행 (등록 중에는 스킵)
                    self.doll_detector.run(frame)

            elif state in ('TRACKING', 'TRACKING_CHECKOUT', 'SEARCHING'):
                # 추종/탐색 중 (YOLO + ReID + Tracker)
                if self.doll_detector is not None:
                    self.doll_detector.run(frame)

    def _stream_loop(self) -> None:
        """가벼운 TCP/MJPEG 스트리머."""
        import socket
        port = 5007
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('0.0.0.0', port))
            sock.listen(1)
            self.get_logger().info(f'Monitor Streamer 시작됨 (Port {port})')
        except Exception as e:
            self.get_logger().error(f'Streamer Bind 실패: {e}')
            return

        while rclpy.ok():
            try:
                conn, addr = sock.accept()
                self.get_logger().info(f'Monitor Dashboard 연결됨: {addr}')
                while rclpy.ok():
                    frame = self._stream_frame
                    if frame is None:
                        time.sleep(0.1)
                        continue
                    
                    # MJPEG 헤더 없이 단순 바이트 전송 (프레임 구분은 size로)
                    size = len(frame)
                    conn.sendall(struct.pack("!I", size) + frame)
                    time.sleep(0.05) # ~20 FPS limit
            except Exception:
                time.sleep(1.0)

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
        self._registration_waiting_confirm = False
        # Prevent immediate TRACKING→SEARCHING flapping right after confirmation.
        self._tracking_grace_until = time.monotonic() + 5.0
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

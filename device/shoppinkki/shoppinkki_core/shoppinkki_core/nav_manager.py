"""Nav2 액션/파라미터 관리 매니저.

main_node에서 분리된 Nav2 인터페이스. NavigateToPose/ThroughPoses 동기·비동기
호출, allow_reversing/inflation_radius 동적 전환 담당.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Optional

import rclpy
import rclpy.time
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import SetParameters

from .geometry import yaw_to_quat

if TYPE_CHECKING:
    import rclpy.node

try:
    from nav2_msgs.action import NavigateToPose, NavigateThroughPoses
    from rclpy.action import ActionClient
    _NAV2_AVAILABLE = True
except ImportError:
    NavigateToPose = None  # type: ignore[assignment]
    NavigateThroughPoses = None  # type: ignore[assignment]
    ActionClient = None  # type: ignore[assignment]
    _NAV2_AVAILABLE = False

logger = logging.getLogger(__name__)


_INFLATION_RADIUS_DEFAULT = 0.10


class NavManager:
    """Nav2 NavigateToPose/ThroughPoses 클라이언트 + 모드/팽창 파라미터 전환."""

    def __init__(self, node: 'rclpy.node.Node', robot_id: str) -> None:
        self._node = node
        self._robot_id = str(robot_id)
        self._current_nav2_mode: Optional[str] = None
        self._active_goal_handle = None
        self._active_through_goal_handle = None
        self._param_clients: dict[str, 'rclpy.client.Client'] = {}

        self._nav2_client = None
        self._nav2_through_client = None
        if _NAV2_AVAILABLE:
            nav2_action = f'robot_{self._robot_id}/navigate_to_pose'
            self._nav2_client = ActionClient(node, NavigateToPose, nav2_action)
            self._node.get_logger().info(f'Nav2 action client ready ({nav2_action})')

            nav2_through_action = f'robot_{self._robot_id}/navigate_through_poses'
            self._nav2_through_client = ActionClient(
                node, NavigateThroughPoses, nav2_through_action)
            self._node.get_logger().info(
                f'Nav2 through-poses client ready ({nav2_through_action})')
        else:
            self._node.get_logger().warning(
                'NavManager: nav2_msgs unavailable — Nav2 disabled')

    # ──────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────

    def is_ready(self) -> bool:
        """Nav2 NavigateToPose 액션 서버가 준비되었는지."""
        return self._nav2_client is not None and self._nav2_client.server_is_ready()

    def send_goal_guiding(self, x: float, y: float, theta: float) -> bool:
        """GUIDING 모드: collision detection ON, 벽에서 떨어진 경로."""
        self._set_nav2_mode('guiding')
        return self._send_nav_goal(x, y, theta)

    def send_goal_returning(self, x: float, y: float, theta: float) -> bool:
        """RETURNING 모드: collision detection OFF, 벽까지 도달 가능."""
        self._set_nav2_mode('returning')
        return self._send_nav_goal(x, y, theta)

    def send_through_poses(
        self,
        poses: list,
        mode: str = 'guiding',
    ) -> bool:
        """다중 경유점 NavigateThroughPoses 동기 호출."""
        self._set_nav2_mode(mode)
        return self._send_nav_through_poses(poses)

    def send_goal_async(
        self,
        x: float,
        y: float,
        theta: float,
        mode: str = 'guiding',
    ) -> None:
        """admin_goto 등 비동기 호출 — 결과를 기다리지 않고 바로 반환."""
        if not self.is_ready():
            self._node.get_logger().warning('send_goal_async: Nav2 not ready')
            return

        self._set_nav2_mode(mode)
        goal_msg = self._create_nav_goal_msg(x, y, theta)

        def _clear_handle(_future):
            self._active_goal_handle = None

        def _store_handle(future):
            gh = future.result()
            if gh is not None and gh.accepted:
                self._active_goal_handle = gh
                gh.get_result_async().add_done_callback(_clear_handle)

        self._nav2_client.send_goal_async(goal_msg).add_done_callback(_store_handle)
        self._node.get_logger().info(
            'send_goal_async: Nav2 goal sent → (%.2f, %.2f)' % (x, y))

    def cancel_active(self) -> None:
        """현재 진행 중인 Nav2 goal을 실제로 취소한다.

        force_terminate / navigate_cancel 등 상태 전환 시 BT4의 cancel_nav에서
        호출한다. goal handle에 cancel_goal_async()를 보내야 Nav2 planner/controller가
        "Passing new path to controller"를 중단한다.
        """
        for attr in ('_active_goal_handle', '_active_through_goal_handle'):
            gh = getattr(self, attr, None)
            if gh is None:
                continue
            try:
                gh.cancel_goal_async()
                self._node.get_logger().info(f'Nav2 cancel sent ({attr})')
            except Exception as e:
                self._node.get_logger().warning(f'Nav2 cancel failed ({attr}): {e}')
            setattr(self, attr, None)

    # ──────────────────────────────────────────
    # 내부 — 파라미터 전환
    # ──────────────────────────────────────────

    def _get_param_client(self, target_node: str) -> 'rclpy.client.Client':
        """Lazily create + cache a SetParameters service client for a remote Nav2 node."""
        cli = self._param_clients.get(target_node)
        if cli is None:
            cli = self._node.create_client(SetParameters, f'{target_node}/set_parameters')
            self._param_clients[target_node] = cli
        return cli

    def _set_remote_param_async(self, target_node: str, name: str, value: ParameterValue) -> None:
        """비동기로 원격 Nav2 노드 파라미터 설정. 콜백/이벤트 루프 블로킹 없음."""
        cli = self._get_param_client(target_node)
        if not cli.service_is_ready():
            self._node.get_logger().debug(
                f'set_param skipped: {target_node}/set_parameters not ready')
            return
        req = SetParameters.Request()
        req.parameters = [Parameter(name=name, value=value)]
        cli.call_async(req)

    def _set_nav2_mode(self, mode: str) -> None:
        """Nav2 파라미터를 GUIDING/RETURNING 모드에 맞게 동적 전환.

        모드가 같으면 스킵. 유일한 차이: allow_reversing (returning=true).
        """
        if mode == self._current_nav2_mode:
            return
        self._current_nav2_mode = mode

        ns = f'/robot_{self._robot_id}'
        reversing = mode == 'returning'
        value = ParameterValue(type=ParameterType.PARAMETER_BOOL, bool_value=reversing)
        self._set_remote_param_async(
            f'{ns}/controller_server', 'FollowPath.allow_reversing', value)
        self._node.get_logger().info(
            'Nav2 mode → %s (reversing=%s)' % (mode, reversing))

    def _set_inflation(self, enable: bool) -> None:
        """Inflation 동적 제어 — 좁은 복도 통과 시 비활성화."""
        ns = f'/robot_{self._robot_id}'
        radius = _INFLATION_RADIUS_DEFAULT if enable else 0.0
        value = ParameterValue(type=ParameterType.PARAMETER_DOUBLE, double_value=radius)
        for costmap in ('local_costmap/local_costmap', 'global_costmap/global_costmap'):
            self._set_remote_param_async(
                f'{ns}/{costmap}', 'inflation_layer.inflation_radius', value)
        self._node.get_logger().info(
            'Inflation → %s (radius=%.2f)' % ('ON' if enable else 'OFF', radius))

    # ──────────────────────────────────────────
    # 내부 — Nav2 호출
    # ──────────────────────────────────────────

    def _create_nav_goal_msg(self, x: float, y: float, theta: float):
        """map 프레임 (x, y, θ) 용 NavigateToPose.Goal 메시지 생성.

        stamp=0 → Nav2가 "최신 TF 사용". 실제 시계(get_clock().now())를 찍으면
        sim_time 롤오버/재시작 시 "Lookup would require extrapolation into the past"
        TF 에러가 난다.
        """
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = PoseStamped()
        goal_msg.pose.header.frame_id = 'map'
        goal_msg.pose.header.stamp = rclpy.time.Time().to_msg()
        goal_msg.pose.pose.position.x = x
        goal_msg.pose.pose.position.y = y
        _, _, qz, qw = yaw_to_quat(theta)
        goal_msg.pose.pose.orientation.z = qz
        goal_msg.pose.pose.orientation.w = qw
        return goal_msg

    def _send_nav_goal(self, x: float, y: float, theta: float) -> bool:
        """Nav2 NavigateToPose 동기 호출 — BT4/BT5 콜백용 (threading.Event 기반)."""
        if self._nav2_client is None or not self._nav2_client.server_is_ready():
            self._node.get_logger().warning('send_nav_goal: Nav2 not ready')
            return False

        goal_msg = self._create_nav_goal_msg(x, y, theta)

        self._node.get_logger().info(
            'send_nav_goal: (%.2f, %.2f, θ=%.2f)' % (x, y, theta))

        done_event = threading.Event()
        result_holder: list = [None]

        def _goal_response(future):
            goal_handle = future.result()
            if goal_handle is None or not goal_handle.accepted:
                self._node.get_logger().warning('send_nav_goal: goal rejected')
                done_event.set()
                return
            result_holder.append(goal_handle)
            self._active_goal_handle = goal_handle
            goal_handle.get_result_async().add_done_callback(_result_response)

        def _result_response(future):
            result_holder[0] = future.result()
            self._active_goal_handle = None
            done_event.set()

        self._nav2_client.send_goal_async(goal_msg).add_done_callback(_goal_response)
        done_event.wait(timeout=120.0)

        result = result_holder[0]
        if result is None:
            self._node.get_logger().warning('send_nav_goal: timeout or rejected')
            return False

        if result.status == GoalStatus.STATUS_SUCCEEDED:
            self._node.get_logger().info('send_nav_goal: succeeded')
            return True
        else:
            self._node.get_logger().warning(
                'send_nav_goal: failed (status=%d)' % result.status)
            return False

    def _send_nav_through_poses(
        self,
        poses: list,
    ) -> bool:
        """Nav2 NavigateThroughPoses 동기 호출 — 다중 경유점 네비게이션."""
        if self._nav2_through_client is None:
            self._node.get_logger().warning(
                'send_nav_through_poses: client not available')
            return False
        if not self._nav2_through_client.wait_for_server(timeout_sec=5.0):
            self._node.get_logger().warning(
                'send_nav_through_poses: Nav2 not ready (5s)')
            return False

        goal_msg = NavigateThroughPoses.Goal()
        for x, y, theta in poses:
            p = PoseStamped()
            p.header.frame_id = 'map'
            p.header.stamp = rclpy.time.Time().to_msg()
            p.pose.position.x = x
            p.pose.position.y = y
            _, _, qz, qw = yaw_to_quat(theta)
            p.pose.orientation.z = qz
            p.pose.orientation.w = qw
            goal_msg.poses.append(p)

        self._node.get_logger().info(
            'send_nav_through_poses: %d poses, final=(%.2f,%.2f)'
            % (len(poses), poses[-1][0], poses[-1][1]))

        done_event = threading.Event()
        result_holder: list = [None]

        def _goal_response(future):
            goal_handle = future.result()
            if goal_handle is None or not goal_handle.accepted:
                self._node.get_logger().warning(
                    'send_nav_through_poses: goal rejected')
                done_event.set()
                return
            result_holder.append(goal_handle)
            self._active_through_goal_handle = goal_handle
            goal_handle.get_result_async().add_done_callback(_result_response)

        def _result_response(future):
            result_holder[0] = future.result()
            self._active_through_goal_handle = None
            done_event.set()

        self._nav2_through_client.send_goal_async(goal_msg).add_done_callback(
            _goal_response)
        done_event.wait(timeout=180.0)

        result = result_holder[0]
        if result is None:
            self._node.get_logger().warning(
                'send_nav_through_poses: timeout or rejected')
            return False

        if result.status == GoalStatus.STATUS_SUCCEEDED:
            self._node.get_logger().info('send_nav_through_poses: succeeded')
            return True
        else:
            self._node.get_logger().warning(
                'send_nav_through_poses: failed (status=%d)' % result.status)
            return False

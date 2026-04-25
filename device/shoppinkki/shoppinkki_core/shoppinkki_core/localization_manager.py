"""TF + AMCL 기반 위치 추적 매니저.

main_node에서 분리된 위치 추적 컴포넌트. TF lookup (map → base_footprint)을
주 위치 소스로 사용하고, AMCL `amcl_pose` 토픽으로 보조 갱신한다.

`on_pose_updated` 콜백을 main_node가 wire하면 위치 갱신 시 호출된다.
BoundaryMonitor 등 위치 의존 컴포넌트가 이 콜백으로 갱신을 받는다.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Callable, Optional

import rclpy
import rclpy.time
import tf2_ros
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)

if TYPE_CHECKING:
    import rclpy.node

logger = logging.getLogger(__name__)


class LocalizationManager:
    """AMCL 토픽 + TF lookup으로 로봇 위치/방향을 추적한다.

    `on_pose_updated` 콜백이 설정되어 있으면 AMCL 갱신 시 (x, y) 좌표로 호출된다.
    BoundaryMonitor 등 위치 의존 컴포넌트가 이 콜백으로 갱신을 받는다.
    """

    def __init__(self, node: 'rclpy.node.Node', robot_id: str) -> None:
        self._node = node
        self._robot_id = str(robot_id)

        # ── 캐시된 위치/방향 ──
        self._pos_x: float = 0.0
        self._pos_y: float = 0.0
        self._yaw: float = 0.0

        # ── TF buffer / listener ──
        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, node)
        self._base_frame = f'robot_{self._robot_id}/base_footprint'

        # ── AMCL subscriber ──
        amcl_qos = QoSProfile(
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            history=QoSHistoryPolicy.KEEP_LAST,
        )
        amcl_topic = f'/robot_{self._robot_id}/amcl_pose'
        self._amcl_sub = node.create_subscription(
            PoseWithCovarianceStamped,
            amcl_topic,
            self._amcl_callback,
            amcl_qos,
        )
        self._node.get_logger().info(f'TF + AMCL pose tracking: {amcl_topic}')

        # main_node가 BoundaryMonitor 등 위치 의존 컴포넌트와 wire하기 위한 콜백.
        self.on_pose_updated: Optional[Callable[[float, float], None]] = None

    # ──────────────────────────────────────────
    # Public properties
    # ──────────────────────────────────────────

    @property
    def pos_x(self) -> float:
        return self._pos_x

    @property
    def pos_y(self) -> float:
        return self._pos_y

    @property
    def yaw(self) -> float:
        return self._yaw

    # ──────────────────────────────────────────
    # AMCL callback
    # ──────────────────────────────────────────

    def _amcl_callback(self, msg: PoseWithCovarianceStamped) -> None:
        """AMCL 추정 위치를 내부 상태에 반영."""
        self._pos_x = msg.pose.pose.position.x
        self._pos_y = msg.pose.pose.position.y
        if self.on_pose_updated is not None:
            self.on_pose_updated(self._pos_x, self._pos_y)

    # ──────────────────────────────────────────
    # TF lookup
    # ──────────────────────────────────────────

    def get_live_pose(self) -> tuple[float, float, float]:
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

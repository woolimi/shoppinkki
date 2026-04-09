"""Nav2 action client helper.

Provides a blocking send_nav_goal(x, y, theta) → bool helper used by
BT4 (BTGuiding) and BT5 (BTReturning).

Also provides:
    set_keepout_filter(node, enable) — lifecycle_manager_filter control.
    fetch_all_zones(host, port) — REST /zones 전체 fetch.
    get_parking_slot(host, port) — REST /zone/parking/available query.
"""

from __future__ import annotations

import logging
import math
import urllib.request
import json as _json
from typing import Optional

logger = logging.getLogger(__name__)

LIFECYCLE_MGR_SRV = '/lifecycle_manager_filter/manage_nodes'


def make_send_nav_goal(node):
    """Return a blocking send_nav_goal(x, y, theta) → bool callable.

    Parameters
    ----------
    node:
        rclpy Node (must have an executor running — called from timer/BT thread).
    """
    try:
        from nav2_msgs.action import NavigateToPose
        from rclpy.action import ActionClient
        from geometry_msgs.msg import PoseStamped
        import rclpy

        client = ActionClient(node, NavigateToPose, 'navigate_to_pose')

        def _send(x: float, y: float, theta: float) -> bool:
            if not client.wait_for_server(timeout_sec=5.0):
                logger.warning('nav2_client: NavigateToPose server not available')
                return False

            goal_msg = NavigateToPose.Goal()
            goal_msg.pose = _make_pose(x, y, theta, node.get_clock().now().to_msg())

            future = client.send_goal_async(goal_msg)
            rclpy.spin_until_future_complete(node, future, timeout_sec=60.0)
            goal_handle = future.result()
            if goal_handle is None or not goal_handle.accepted:
                logger.warning('nav2_client: goal rejected')
                return False

            result_future = goal_handle.get_result_async()
            rclpy.spin_until_future_complete(node, result_future, timeout_sec=120.0)
            result = result_future.result()
            if result is None:
                logger.warning('nav2_client: no result received')
                return False
            from action_msgs.msg import GoalStatus
            return result.status == GoalStatus.STATUS_SUCCEEDED

        return _send

    except Exception as e:
        logger.warning('nav2_client: cannot create client: %s', e)
        return lambda x, y, theta: False


def make_set_keepout_filter(node):
    """Return a set_keepout_filter(enable: bool) callable."""
    try:
        from nav2_msgs.srv import ManageLifecycleNodes

        client = node.create_client(ManageLifecycleNodes, LIFECYCLE_MGR_SRV)

        def _set(enable: bool) -> None:
            if not client.wait_for_service(timeout_sec=2.0):
                logger.warning('keepout_filter: lifecycle_manager_filter not available')
                return
            req = ManageLifecycleNodes.Request()
            req.command = (ManageLifecycleNodes.Request.STARTUP if enable
                           else ManageLifecycleNodes.Request.PAUSE)
            future = client.call_async(req)
            import rclpy
            rclpy.spin_until_future_complete(node, future, timeout_sec=5.0)
            logger.info('keepout_filter: %s', 'ON' if enable else 'OFF')

        return _set

    except Exception as e:
        logger.warning('nav2_client: cannot create keepout filter client: %s', e)
        return lambda enable: None


def make_get_parking_slot(host: str = '127.0.0.1', port: int = 8081):
    """Return a get_parking_slot() → Optional[dict] callable."""

    def _get() -> Optional[dict]:
        url = f'http://{host}:{port}/zone/parking/available'
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                return _json.loads(resp.read())
        except Exception as e:
            logger.warning('get_parking_slot: %s', e)
            return None

    return _get


def fetch_all_zones(
    host: str = '127.0.0.1',
    port: int = 8081,
) -> dict[int, dict]:
    """REST GET /zones → zone_id 키의 dict 로 캐시.

    반환값 예시:
        {1: {'zone_id': 1, 'zone_name': '가전제품', 'zone_type': 'product',
             'x': 0.619, 'y': -0.007, 'theta': 0.0}, ...}
    실패 시 빈 dict 반환.
    """
    url = f'http://{host}:{port}/zones'
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            rows = _json.loads(resp.read())
        cache = {row['zone_id']: row for row in rows}
        logger.info('fetch_all_zones: %d zones loaded', len(cache))
        return cache
    except Exception as e:
        logger.warning('fetch_all_zones: %s', e)
        return {}


def _make_pose(x: float, y: float, theta: float, stamp):
    """Build a geometry_msgs/PoseStamped from x, y, theta (yaw)."""
    from geometry_msgs.msg import PoseStamped
    pose = PoseStamped()
    pose.header.frame_id = 'map'
    pose.header.stamp = stamp
    pose.pose.position.x = x
    pose.pose.position.y = y
    pose.pose.position.z = 0.0
    # Quaternion from yaw
    qz = math.sin(theta / 2.0)
    qw = math.cos(theta / 2.0)
    pose.pose.orientation.x = 0.0
    pose.pose.orientation.y = 0.0
    pose.pose.orientation.z = qz
    pose.pose.orientation.w = qw
    return pose

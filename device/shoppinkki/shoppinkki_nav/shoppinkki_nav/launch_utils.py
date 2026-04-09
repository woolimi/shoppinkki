"""Launch 유틸리티 — nav2_params 치환 + map↔Gazebo 좌표 변환.

nav2_params.yaml 의 플레이스홀더를 로봇별 값으로 치환하여
임시 파일 경로를 반환한다.

AMCL 초기 pose 는 control_service REST /zones 에서 가져온다.
서버 미기동 시 fallback 좌표 사용.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import urllib.request

from shoppinkki_core.config import CHARGER_ZONE_IDS

logger = logging.getLogger(__name__)

# DB 미접속 시 fallback (seed_data.sql 충전소 좌표와 동기화)
_FALLBACK_POSES: dict[str, dict[str, float]] = {
    '54': {'x': -0.056, 'y': -0.899, 'yaw': 0.0},
    '18': {'x': -0.056, 'y': -0.606, 'yaw': 0.0},
}
_DEFAULT_POSE = {'x': 0.0, 'y': 0.0, 'yaw': 0.0}

# ── Map ↔ Gazebo 좌표 변환 (SLAM 벽 ↔ Gazebo collision 벽 기준) ──────────
# 대응: gz_y ↔ map_x (같은 방향), gz_x ↔ map_y (반대 방향)
# Gazebo collision 벽 범위
_GZ_WEST = 0.012001
_GZ_EAST = 1.864201
_GZ_SOUTH = 0.000134
_GZ_NORTH = 1.397034
# SLAM 맵 벽 범위 (shop.pgm occupied 픽셀 중심)
_SLAM_WEST = -0.1364
_SLAM_EAST = 1.2605
_SLAM_SOUTH = -1.7266
_SLAM_NORTH = 0.1256


def map_to_gazebo(mx: float, my: float, myaw: float = 0.0
                  ) -> dict[str, float]:
    """Map frame (x, y, yaw) → Gazebo world frame (x, y, yaw)."""
    # 정규화: map 좌표 → [0,1]
    ny = (mx - _SLAM_WEST) / (_SLAM_EAST - _SLAM_WEST)   # → gz_y 방향
    nx = (_SLAM_NORTH - my) / (_SLAM_NORTH - _SLAM_SOUTH) # → gz_x 방향 (반전)
    # Gazebo 좌표
    gx = _GZ_WEST + nx * (_GZ_EAST - _GZ_WEST)
    gy = _GZ_SOUTH + ny * (_GZ_NORTH - _GZ_SOUTH)
    gyaw = myaw + math.pi / 2  # map yaw → gz yaw (+90°)
    return {'x': gx, 'y': gy, 'yaw': gyaw}


def get_charger_pose(
    robot_id: str,
    host: str = '127.0.0.1',
    port: int = 8081,
) -> dict[str, float]:
    """REST /zones 에서 충전소 waypoint → {'x', 'y', 'yaw'} 반환."""
    fallback = _FALLBACK_POSES.get(robot_id, _DEFAULT_POSE)
    zone_id = CHARGER_ZONE_IDS.get(robot_id)
    if zone_id is None:
        return fallback

    url = f'http://{host}:{port}/zones'
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            zones = json.loads(resp.read())
        for z in zones:
            if z['zone_id'] == zone_id:
                return {
                    'x': float(z['x']),
                    'y': float(z['y']),
                    'yaw': float(z['theta']),
                }
    except Exception as exc:
        logger.warning('launch_utils: charger pose fetch failed, using fallback: %s', exc)

    return fallback


def resolve_nav2_params(
    template_path: str,
    ns: str,
    robot_id: str | None = None,
) -> str:
    """nav2_params.yaml 템플릿의 플레이스홀더를 치환하고 임시 파일 경로를 반환.

    Parameters
    ----------
    template_path:
        __NS__ 등 플레이스홀더가 포함된 YAML 경로.
    ns:
        로봇 namespace (e.g. ``robot_54``).
    robot_id:
        로봇 번호 (e.g. ``54``). None 이면 ns 에서 추출.
    """
    if robot_id is None:
        robot_id = ns.replace('robot_', '')

    host = os.environ.get('CONTROL_SERVICE_HOST', '127.0.0.1')
    port = int(os.environ.get('CONTROL_SERVICE_PORT', '8081'))
    pose = get_charger_pose(robot_id, host, port)

    with open(template_path) as f:
        content = f.read()

    content = (
        content
        .replace('__NS__', ns)
        .replace('__INIT_X__', str(pose['x']))
        .replace('__INIT_Y__', str(pose['y']))
        .replace('__INIT_YAW__', str(pose['yaw']))
    )

    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.yaml', prefix=f'nav2_{ns}_', delete=False,
    )
    tmp.write(content)
    tmp.close()
    return tmp.name

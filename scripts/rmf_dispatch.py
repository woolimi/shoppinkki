#!/usr/bin/env python3
"""RMF task 제출 스크립트 — 구역 기반 스마트 배정.

Usage:
    # 로봇 54를 가전제품 구역으로 (빈 자리 자동 선택)
    python3 scripts/rmf_dispatch.py --robot pinky_54 --zone 가전제품

    # 특정 waypoint로 직접 이동
    python3 scripts/rmf_dispatch.py --robot pinky_54 --waypoint 가전제품1

    # 두 로봇 동시 — 같은 구역, 다른 waypoint 자동 배정
    python3 scripts/rmf_dispatch.py --robot pinky_54 --zone 가전제품 &
    python3 scripts/rmf_dispatch.py --robot pinky_18 --zone 가전제품 &

    # waypoint 목록 보기
    python3 scripts/rmf_dispatch.py --list
"""

import argparse
import json
import math
import time
import uuid

import requests
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from rmf_task_msgs.msg import ApiRequest, ApiResponse

# 구역 → 후보 waypoint 목록
ZONE_WAYPOINTS = {
    '가전제품': ['가전제품1', '가전제품2'],
    '과자':     ['과자1'],
    '해산물':   ['해산물2'],
    '육류':     ['육류1', '육류2'],
    '채소':     ['채소1'],
    '음료':     ['음료1', '음료2'],
    '베이커리': ['빵1', '빵2'],
    '음식':     ['가공식품1', '가공식품2'],
}

# waypoint 좌표 (nav_graph 기준)
WAYPOINT_COORDS = {
    '가전제품1': (0.489, -0.12), '가전제품2': (0.749, -0.12),
    '과자1': (0.950, -0.12),
    '해산물2': (1.05, -0.300),
    '육류1': (1.05, -0.606), '육류2': (1.05, -0.899),
    '채소1': (1.05, -1.224),
    '음료1': (0.76, -0.899), '음료2': (0.76, -1.224),
    '빵1': (0.42, -0.300), '빵2': (0.76, -0.300),
    '가공식품1': (0.76, -0.606), '가공식품2': (0.42, -0.606),
    'P1': (0.12, -0.606), 'P2': (0.12, -0.899),
}

QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.RELIABLE,
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
    depth=10,
)

REST_BASE = 'http://localhost:8081'
OCCUPY_DIST = 0.25  # 이 거리 이내면 "점유" 판정


def get_robot_positions() -> dict[str, tuple[float, float]]:
    """REST API로 모든 로봇 위치를 조회."""
    positions = {}
    for rid in ['54', '18']:
        try:
            resp = requests.get(f'{REST_BASE}/robot/{rid}/status', timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                positions[f'pinky_{rid}'] = (
                    float(data.get('pos_x', 0)),
                    float(data.get('pos_y', 0)),
                )
        except Exception:
            pass
    return positions


def get_robot_states() -> dict[str, dict]:
    """REST API로 모든 로봇 상태(위치 + mode + 목적지)를 조회."""
    states = {}
    for rid in ['54', '18']:
        try:
            resp = requests.get(f'{REST_BASE}/robot/{rid}/status', timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                states[f'pinky_{rid}'] = {
                    'x': float(data.get('pos_x', 0)),
                    'y': float(data.get('pos_y', 0)),
                    'mode': data.get('mode', ''),
                    'dest_x': data.get('dest_x'),
                    'dest_y': data.get('dest_y'),
                }
        except Exception:
            pass
    return states


def pick_best_waypoint(zone: str, robot_name: str) -> str:
    """구역 내 빈 waypoint를 선택. 다른 로봇이 점유 중이거나 이동 중이면 대안 선택."""
    candidates = ZONE_WAYPOINTS.get(zone)
    if not candidates:
        print(f'[WARN] 알 수 없는 구역: {zone}')
        return zone

    if len(candidates) == 1:
        return candidates[0]

    states = get_robot_states()
    other_robots = {k: v for k, v in states.items() if k != robot_name}

    occupied = set()
    for r_name, r_state in other_robots.items():
        # 1) 현재 위치 기반: 가장 가까운 waypoint 1개 점유
        r_pos = (r_state['x'], r_state['y'])
        closest_wp = None
        closest_dist = float('inf')
        for wp_name in candidates:
            wp_coord = WAYPOINT_COORDS.get(wp_name)
            if wp_coord is None:
                continue
            dist = math.sqrt((wp_coord[0] - r_pos[0])**2 +
                             (wp_coord[1] - r_pos[1])**2)
            if dist < closest_dist:
                closest_dist = dist
                closest_wp = wp_name
        if closest_wp and closest_dist <= OCCUPY_DIST:
            occupied.add(closest_wp)
            print(f'  [{closest_wp}] 점유 중 ({r_name}, dist={closest_dist:.3f}m)')

        # 2) 목적지 기반: GUIDING 상태에서 이동 중인 목적지도 점유
        dest_x = r_state.get('dest_x')
        dest_y = r_state.get('dest_y')
        if dest_x is not None and dest_y is not None and r_state['mode'] == 'GUIDING':
            for wp_name in candidates:
                wp_coord = WAYPOINT_COORDS.get(wp_name)
                if wp_coord is None:
                    continue
                dist = math.sqrt((wp_coord[0] - dest_x)**2 +
                                 (wp_coord[1] - dest_y)**2)
                if dist <= OCCUPY_DIST:
                    occupied.add(wp_name)
                    print(f'  [{wp_name}] 이동 중 ({r_name} → dest, dist={dist:.3f}m)')

    free = [wp for wp in candidates if wp not in occupied]
    if free:
        chosen = free[0]
        print(f'  → {chosen} (비점유)')
    else:
        chosen = max(candidates, key=lambda wp: min(
            math.sqrt((WAYPOINT_COORDS[wp][0] - s['x'])**2 +
                      (WAYPOINT_COORDS[wp][1] - s['y'])**2)
            for s in other_robots.values()
        ) if other_robots else 0)
        print(f'  → {chosen} (모두 점유, 최대 이격 선택)')

    return chosen


def make_patrol_request(robot_name: str, waypoint: str, request_id: str) -> dict:
    """RMF patrol task JSON — 특정 로봇에 직접 할당."""
    now_ms = int(time.time() * 1000)
    return {
        "type": "robot_task_request",
        "robot": robot_name,
        "fleet": "pinky_fleet",
        "request": {
            "unix_millis_earliest_start_time": now_ms,
            "category": "patrol",
            "description": {
                "places": [waypoint],
                "rounds": 1,
            },
            "requester": "test_script",
        },
    }


def main():
    parser = argparse.ArgumentParser(description='RMF task 제출')
    parser.add_argument('--robot', default='pinky_54',
                        help='로봇 이름 (pinky_54 or pinky_18)')
    parser.add_argument('--waypoint', default=None,
                        help='목적지 웨이포인트 이름 (직접 지정)')
    parser.add_argument('--zone', default=None,
                        help='구역 이름 (빈 자리 자동 선택)')
    parser.add_argument('--list', action='store_true',
                        help='구역/웨이포인트 목록 출력')
    args = parser.parse_args()

    if args.list:
        print('\n구역별 웨이포인트:')
        for zone, wps in ZONE_WAYPOINTS.items():
            print(f'  {zone}: {", ".join(wps)}')
        return

    # 목적지 결정
    if args.zone:
        waypoint = pick_best_waypoint(args.zone, args.robot)
    elif args.waypoint:
        waypoint = args.waypoint
    else:
        print('--zone 또는 --waypoint 중 하나를 지정하세요.')
        return

    rclpy.init()
    node = Node('rmf_dispatch_client')

    pub = node.create_publisher(ApiRequest, '/task_api_requests', QOS)

    # 응답 수신
    response_holder = [None]
    request_id = str(uuid.uuid4())

    def response_cb(msg: ApiResponse):
        if msg.request_id == request_id:
            response_holder[0] = msg

    node.create_subscription(ApiResponse, '/task_api_responses', response_cb, QOS)

    # 발행 준비 대기
    time.sleep(1.0)

    task_json = make_patrol_request(args.robot, waypoint, request_id)

    msg = ApiRequest()
    msg.request_id = request_id
    msg.json_msg = json.dumps(task_json)

    print(f'>> RMF task 제출: {args.robot} → {waypoint}')
    pub.publish(msg)

    # 응답 대기
    for _ in range(50):
        rclpy.spin_once(node, timeout_sec=0.1)
        if response_holder[0] is not None:
            resp = response_holder[0]
            print(f'<< 응답 (request_id={resp.request_id[:8]}):')
            print(f'   {resp.json_msg[:200]}')
            break
    else:
        print('<< 응답 없음 (5초 타임아웃)')

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()

"""ShopPinkki RMF RobotCommandHandle 구현체.

RMF가 navigate / stop / dock 명령을 내리면
control_service REST API(/robot_<id>/cmd) 로 변환하여 전달.

Pi SM·BT 코드 변경 없음 — control_service 위에 RMF 레이어가 끼어들 뿐.

RMF CommandHandle 인터페이스:
    navigate(pose, graph_index, done_cb, ...)  → navigate_to cmd
    stop(activity, done_cb)                    → mode WAITING cmd
    dock(dock_name, done_cb)                   → RETURNING 트리거
    action_executor(...)                       → 사용 안 함 (pass)
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)


class PinkyCommandHandle:
    """RMF EasyFullControl 에 등록되는 로봇 명령 핸들.

    fleet_adapter.py 에서 인스턴스화 후 rmf adapter 에 콜백으로 전달.
    """

    # GUIDING 도착 판정 허용 오차
    _ARRIVE_DIST_M = 0.15   # m
    _ARRIVE_YAW_RAD = 0.30  # rad

    def __init__(
        self,
        robot_id: str,
        status_bridge,         # RobotStatusBridge 인스턴스
        control_host: str = '127.0.0.1',
        control_http_port: int = 8081,
    ) -> None:
        self.robot_id = robot_id
        self._bridge = status_bridge
        self._rest_base = f'http://{control_host}:{control_http_port}'

        self._nav_thread: Optional[threading.Thread] = None
        self._nav_cancel = threading.Event()

    # ── REST 헬퍼 ─────────────────────────────────────────────────────────────

    def _send_cmd(self, payload: dict, timeout: float = 3.0) -> bool:
        """control_service /robot_<id>/cmd REST POST."""
        # control_service 는 /robot/<id>/cmd 에 POST 를 받지 않음.
        # 대신 TCP channel B admin_goto / mode 형식으로 전달하거나
        # ROS2 토픽 /robot_<id>/cmd 를 직접 퍼블리시한다.
        # 여기서는 REST proxy 를 가정: POST /robot/<id>/cmd
        url = f'{self._rest_base}/robot/{self.robot_id}/cmd'
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code == 200:
                return True
            logger.warning('[CmdHandle] cmd 응답 %d: %s', resp.status_code, resp.text[:100])
            return False
        except Exception as e:
            logger.error('[CmdHandle] cmd 전송 실패: %s', e)
            return False

    # ── RMF CommandHandle 인터페이스 ─────────────────────────────────────────

    def navigate(
        self,
        pose,                          # rmf_fleet_adapter.Pose (x, y, yaw)
        graph_node_index: int,
        done_callback: Callable,
        *args,
        **kwargs,
    ) -> None:
        """RMF → navigate_to → Pi GUIDING 상태 진입.

        Args:
            pose            : 목표 위치 (RMF Pose 또는 (x, y, yaw) 튜플)
            graph_node_index: Nav graph 상의 웨이포인트 인덱스
            done_callback   : 도착/실패 시 호출 (인수 없음)
        """
        # 이전 내비게이션 취소
        self._cancel_nav()

        try:
            x = float(pose.x)
            y = float(pose.y)
            yaw = float(pose.yaw)
        except AttributeError:
            x, y, yaw = float(pose[0]), float(pose[1]), float(pose[2])

        logger.info(
            '[CmdHandle] robot_%s navigate → (%.2f, %.2f, yaw=%.2f)',
            self.robot_id, x, y, yaw,
        )

        payload = {
            'cmd': 'navigate_to',
            'zone_id': graph_node_index,
            'x': round(x, 4),
            'y': round(y, 4),
            'theta': round(yaw, 4),
        }
        self._send_cmd(payload)

        # 도착 감지 스레드 (pose 기반 polling)
        self._nav_cancel.clear()
        self._nav_thread = threading.Thread(
            target=self._wait_arrive,
            args=(x, y, yaw, done_callback),
            daemon=True,
        )
        self._nav_thread.start()

    def stop(self, activity=None, done_callback: Optional[Callable] = None) -> None:
        """RMF → mode WAITING → Pi WAITING 상태."""
        self._cancel_nav()
        logger.info('[CmdHandle] robot_%s stop → WAITING', self.robot_id)
        self._send_cmd({'cmd': 'mode', 'value': 'WAITING'})
        if done_callback:
            done_callback()

    def dock(
        self,
        dock_name: str,
        done_callback: Callable,
        *args,
        **kwargs,
    ) -> None:
        """RMF Dock → Pi RETURNING 상태 진입 트리거.

        dock_name: 'P1' 또는 'P2' (충전소 슬롯)
        """
        self._cancel_nav()
        logger.info('[CmdHandle] robot_%s dock → %s (RETURNING)', self.robot_id, dock_name)
        # RETURNING 은 Pi BT5 가 처리 (/zone/parking/available → Nav2)
        # 여기서는 mode RETURNING 만 전달
        self._send_cmd({'cmd': 'mode', 'value': 'RETURNING'})

        # CHARGING 상태 도달 대기
        self._nav_cancel.clear()
        t = threading.Thread(
            target=self._wait_charging,
            args=(done_callback,),
            daemon=True,
        )
        t.start()

    # ── 내부 헬퍼 ────────────────────────────────────────────────────────────

    def _cancel_nav(self) -> None:
        """진행 중인 내비게이션 감지 스레드 취소."""
        self._nav_cancel.set()
        if self._nav_thread and self._nav_thread.is_alive():
            self._nav_thread.join(timeout=2.0)

    def _wait_arrive(
        self,
        goal_x: float,
        goal_y: float,
        goal_yaw: float,
        done_cb: Callable,
        timeout_s: float = 120.0,
    ) -> None:
        """목표 지점 도달 polling (2Hz). 도달 시 done_cb() 호출."""
        deadline = time.monotonic() + timeout_s
        while not self._nav_cancel.is_set():
            px, py, pyaw = self._bridge.pose
            dx = px - goal_x
            dy = py - goal_y
            dist = math.sqrt(dx * dx + dy * dy)
            dyaw = abs(_angle_diff(pyaw, goal_yaw))

            if dist <= self._ARRIVE_DIST_M and dyaw <= self._ARRIVE_YAW_RAD:
                logger.info(
                    '[CmdHandle] robot_%s 도착 (dist=%.3f, dyaw=%.3f)',
                    self.robot_id, dist, dyaw,
                )
                done_cb()
                return

            if time.monotonic() >= deadline:
                logger.warning('[CmdHandle] robot_%s navigate timeout', self.robot_id)
                done_cb()
                return

            time.sleep(0.5)

    def _wait_charging(self, done_cb: Callable, timeout_s: float = 120.0) -> None:
        """CHARGING 상태 도달 대기."""
        deadline = time.monotonic() + timeout_s
        while not self._nav_cancel.is_set():
            if self._bridge.current_mode == 'CHARGING':
                logger.info('[CmdHandle] robot_%s CHARGING 도달', self.robot_id)
                done_cb()
                return
            if time.monotonic() >= deadline:
                logger.warning('[CmdHandle] robot_%s dock timeout', self.robot_id)
                done_cb()
                return
            time.sleep(1.0)


def _angle_diff(a: float, b: float) -> float:
    """두 각도의 차 ([-π, π] 범위)."""
    diff = (a - b + math.pi) % (2 * math.pi) - math.pi
    return diff

"""ShopPinkki RMF Status Bridge.

/robot_<id>/status (std_msgs/String JSON) 토픽을 구독하여
RMF RobotUpdateHandle.update(location, battery_soc) 를 주기적으로 호출.

Pi 코드 변경 없이 기존 status 토픽을 RMF에 공급.

JSON 포맷 (/robot_<id>/status):
    {
        "mode": "TRACKING",
        "pos_x": 0.85,
        "pos_y": 1.10,
        "yaw": 1.5708,
        "battery": 87,
        "is_locked_return": false
    }
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class RobotStatusBridge:
    """한 로봇의 /robot_<id>/status → RMF pose 업데이트 브리지.

    fleet_adapter.py 에서 인스턴스화하고,
    RMF RobotUpdateHandle 이 준비되면 register_handle() 로 등록.
    """

    def __init__(self, robot_id: str, node) -> None:
        """
        Args:
            robot_id: '54' 또는 '18'
            node    : rclpy.Node 인스턴스
        """
        from std_msgs.msg import String  # rclpy 사용 가능 환경 전제

        self.robot_id = robot_id
        self._node = node
        self._handle = None          # rmf_fleet_adapter RobotUpdateHandle
        self._handle_lock = threading.Lock()

        # 마지막으로 수신한 상태 캐시
        self._last_x: float = 0.0
        self._last_y: float = 0.0
        self._last_yaw: float = 0.0
        self._last_battery: float = 1.0   # 0.0~1.0 (RMF 기준)
        self._last_mode: str = 'CHARGING'

        # 변화 감지를 위한 이전 모드
        self._prev_mode: str = ''

        # 모드 변화 콜백 (fleet_adapter 에서 주입)
        self.on_mode_change: Optional[Callable[[str, str, str], None]] = None

        # 구독
        node.create_subscription(
            String,
            f'/robot_{robot_id}/status',
            self._on_status,
            10,
        )
        logger.info('[StatusBridge] robot_%s 구독 시작', robot_id)

    def register_handle(self, handle) -> None:
        """RMF RobotUpdateHandle 등록 (fleet_adapter 에서 호출)."""
        with self._handle_lock:
            self._handle = handle
        logger.info('[StatusBridge] robot_%s RMF handle 등록 완료', self.robot_id)

    def _on_status(self, msg) -> None:
        """/robot_<id>/status 수신 핸들러."""
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError as e:
            logger.warning('[StatusBridge] JSON 파싱 오류: %s', e)
            return

        self._last_x = float(data.get('pos_x', self._last_x))
        self._last_y = float(data.get('pos_y', self._last_y))
        self._last_yaw = float(data.get('yaw', self._last_yaw))
        battery_pct = float(data.get('battery', self._last_battery * 100))
        self._last_battery = max(0.0, min(1.0, battery_pct / 100.0))
        self._last_mode = data.get('mode', self._last_mode)

        # RMF 핸들 업데이트
        self._push_to_rmf()

        # 모드 변화 콜백
        if self._last_mode != self._prev_mode:
            if self.on_mode_change:
                try:
                    self.on_mode_change(self.robot_id, self._prev_mode, self._last_mode)
                except Exception as e:
                    logger.warning('[StatusBridge] on_mode_change 오류: %s', e)
            self._prev_mode = self._last_mode

    def _push_to_rmf(self) -> None:
        """현재 상태를 RMF RobotUpdateHandle 에 전달."""
        with self._handle_lock:
            if self._handle is None:
                return
            try:
                # rmf_fleet_adapter.Location 은 (level_name, x, y, yaw)
                import rmf_fleet_adapter as rmf
                loc = rmf.Location('L1', self._last_x, self._last_y, self._last_yaw)
                self._handle.update(loc, self._last_battery)
            except Exception as e:
                logger.debug('[StatusBridge] RMF update 오류: %s', e)

    # ── 외부 접근용 ────────────────────────────────────────────────────────────

    @property
    def current_mode(self) -> str:
        return self._last_mode

    @property
    def pose(self) -> tuple:
        """(x, y, yaw) 현재 위치."""
        return (self._last_x, self._last_y, self._last_yaw)

    @property
    def battery_soc(self) -> float:
        """배터리 잔량 (0.0 ~ 1.0)."""
        return self._last_battery

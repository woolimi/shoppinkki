"""ShopPinkki RMF Task Dispatcher.

navigate_to / dock 임무를 control_service REST 경유로 RMF Task 로 래핑하여 제출.

주요 기능:
  - dispatch_navigate(robot_id, zone_id, x, y, theta)
      기존 control_service navigate_to 를 RMF TaskRequest 로 래핑
      (경로 충돌 시 RMF Traffic Scheduler 가 대기/우회 협상)

  - dispatch_dock(robot_id)
      충전소 귀환 임무를 RMF Dock task 로 제출
      (충전소 슬롯 배정은 /zone/parking/available 기반)

RMF Task API:
  - 직접 TaskRequest 제출: rmf_task_msgs.msg.TaskSummary 기반
  - 여기서는 경량 래퍼로 control_service REST 호출 후 done 콜백 처리

⚠️ RMF Task API 는 버전에 따라 크게 달라집니다.
   pip show rmf-adapter 로 버전 확인 후 아래 _submit_rmf_task() 수정 필요.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)


class TaskDispatcher:
    """navigate_to / dock 임무 제출기."""

    def __init__(
        self,
        control_host: str = '127.0.0.1',
        control_http_port: int = 8081,
    ) -> None:
        self._rest_base = f'http://{control_host}:{control_http_port}'

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def dispatch_navigate(
        self,
        robot_id: str,
        zone_id: int,
        x: float,
        y: float,
        theta: float,
        done_callback: Optional[Callable] = None,
    ) -> None:
        """navigate_to 임무 제출.

        control_service 를 경유하여 Pi에 navigate_to cmd 전달.
        RMF FleetAdapter 가 경로 충돌을 감지하면 PinkyCommandHandle.navigate()
        를 호출하므로, 여기서는 직접 REST 전달 경로도 제공.

        Args:
            robot_id     : '54' 또는 '18'
            zone_id      : ZONE.zone_id
            x, y, theta  : 목표 위치
            done_callback: 완료 시 호출 (선택)
        """
        payload = {
            'cmd': 'navigate_to',
            'zone_id': zone_id,
            'x': round(x, 4),
            'y': round(y, 4),
            'theta': round(theta, 4),
        }
        logger.info(
            '[TaskDispatcher] robot_%s navigate_to zone=%d (%.2f, %.2f)',
            robot_id, zone_id, x, y,
        )
        self._post_cmd(robot_id, payload, done_callback)

    def dispatch_dock(
        self,
        robot_id: str,
        done_callback: Optional[Callable] = None,
    ) -> None:
        """충전소 귀환 임무 제출.

        /zone/parking/available 로 빈 슬롯을 조회한 뒤 navigate_to 전달.
        슬롯 조회 실패 시 기본 zone_id=140 (P1) 사용.
        """
        logger.info('[TaskDispatcher] robot_%s dock (RETURNING) 제출', robot_id)

        def _run():
            slot = self._query_parking_slot() or {'zone_id': 140, 'x': 0.20, 'y': 0.20, 'theta': 1.5708}
            payload = {
                'cmd': 'navigate_to',
                'zone_id': slot['zone_id'],
                'x': slot.get('x', 0.20),
                'y': slot.get('y', 0.20),
                'theta': slot.get('theta', 1.5708),
            }
            self._post_cmd(robot_id, payload, done_callback)

        threading.Thread(target=_run, daemon=True).start()

    # ── 내부 헬퍼 ────────────────────────────────────────────────────────────

    def _post_cmd(
        self,
        robot_id: str,
        payload: dict,
        done_callback: Optional[Callable],
    ) -> None:
        """control_service REST POST /robot/<id>/cmd."""
        url = f'{self._rest_base}/robot/{robot_id}/cmd'
        try:
            resp = requests.post(url, json=payload, timeout=3.0)
            if resp.status_code != 200:
                logger.warning('[TaskDispatcher] 응답 %d: %s', resp.status_code, resp.text[:80])
        except Exception as e:
            logger.error('[TaskDispatcher] REST 오류: %s', e)
        if done_callback:
            done_callback()

    def _query_parking_slot(self) -> Optional[dict]:
        """GET /zone/parking/available → 슬롯 정보."""
        try:
            resp = requests.get(
                f'{self._rest_base}/zone/parking/available', timeout=3.0
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning('[TaskDispatcher] 주차 슬롯 조회 실패: %s', e)
        return None

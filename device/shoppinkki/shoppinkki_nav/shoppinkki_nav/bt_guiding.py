"""BT 4: GUIDING  (py_trees 기반)

Navigate to a zone waypoint via Nav2.

SUCCESS → arrived event + enter_waiting
FAILURE → nav_failed event + resume_tracking
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional, Tuple

import py_trees

from shoppinkki_interfaces import RobotPublisherInterface

logger = logging.getLogger(__name__)


class NavigateToZone(py_trees.behaviour.Behaviour):
    """Nav2 로 목적지까지 이동."""

    def __init__(
        self,
        name: str = 'NavigateToZone',
        publisher: RobotPublisherInterface = None,
        send_nav_goal: Optional[Callable[[float, float, float], bool]] = None,
        send_nav_through_poses: Optional[Callable[[list], bool]] = None,
        on_arrived: Optional[Callable[[str], None]] = None,
        on_nav_failed: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(name)
        self._pub = publisher
        self._send_nav_goal = send_nav_goal
        self._send_nav_through_poses = send_nav_through_poses
        self._on_arrived = on_arrived
        self._on_nav_failed = on_nav_failed

        self._goal: Optional[Tuple[float, float, float]] = None
        self._goals: Optional[list[Tuple[float, float, float]]] = None
        self._zone_name: str = ''
        self._in_progress: bool = False
        self._nav_success: Optional[bool] = None
        self._nav_thread: Optional[threading.Thread] = None

    def initialise(self) -> None:
        self._in_progress = False
        self._nav_success = None
        self._nav_thread = None
        logger.info('NavigateToZone: started (goal=%s zone=%s)',
                     self._goal, self._zone_name)

    def update(self) -> py_trees.common.Status:
        if self._goal is None:
            logger.warning('NavigateToZone: no goal set → FAILURE')
            self._fire_nav_failed()
            return py_trees.common.Status.FAILURE

        if self._send_nav_goal is None:
            logger.warning('NavigateToZone: no nav client → FAILURE')
            self._fire_nav_failed()
            return py_trees.common.Status.FAILURE

        # 완료 확인 (스레드가 끝나고 결과가 있는 경우)
        if self._nav_success is not None and not self._in_progress:
            if self._nav_success:
                logger.info('NavigateToZone: navigation succeeded')
                if self._on_arrived:
                    self._on_arrived(self._zone_name)
                return py_trees.common.Status.SUCCESS
            else:
                logger.warning('NavigateToZone: navigation failed')
                self._fire_nav_failed()
                return py_trees.common.Status.FAILURE

        # 스레드 실행 중
        if self._in_progress:
            return py_trees.common.Status.RUNNING

        # 아직 스레드 시작 전 → 시작
        self._in_progress = True
        self._nav_success = None

        # 다중 경유점 모드 — 경유점마다 순차 NavigateToPose
        if self._goals and self._send_nav_goal:
            goals = list(self._goals)
            logger.info('NavigateToZone: sequential %d waypoints', len(goals))

            def _run():
                try:
                    for i, (gx, gy, gtheta) in enumerate(goals):
                        logger.info('NavigateToZone: [%d/%d] → (%.2f, %.2f)',
                                    i + 1, len(goals), gx, gy)
                        ok = self._send_nav_goal(gx, gy, gtheta)
                        if not ok:
                            logger.warning('NavigateToZone: [%d/%d] failed', i + 1, len(goals))
                            self._nav_success = False
                            return
                    self._nav_success = True
                except Exception as e:
                    logger.error('NavigateToZone: sequential exception: %s', e)
                    self._nav_success = False
                finally:
                    self._in_progress = False

            self._nav_thread = threading.Thread(target=_run, daemon=True)
            self._nav_thread.start()
            return py_trees.common.Status.RUNNING

        # 단일 목표점 모드
        x, y, theta = self._goal

        def _run():
            try:
                self._nav_success = self._send_nav_goal(x, y, theta)
            except Exception as e:
                logger.error('NavigateToZone: nav exception: %s', e)
                self._nav_success = False
            finally:
                self._in_progress = False

        self._nav_thread = threading.Thread(target=_run, daemon=True)
        self._nav_thread.start()
        return py_trees.common.Status.RUNNING

    def terminate(self, new_status: py_trees.common.Status) -> None:
        self._pub.publish_cmd_vel(0.0, 0.0)

    # ── Public ────────────────────────────────

    def cancel_nav(self) -> None:
        """Cancel current navigation goal."""
        self._in_progress = False
        self._nav_success = None
        self._goal = None
        self._pub.publish_cmd_vel(0.0, 0.0)
        logger.info('NavigateToZone: navigation cancelled')

    def set_goal(self, x: float, y: float, theta: float,
                 zone_name: str = '') -> None:
        self._goal = (x, y, theta)
        self._goals = None
        self._zone_name = zone_name
        self._in_progress = False
        logger.info('NavigateToZone: goal set → (%.2f, %.2f, θ=%.2f) zone=%s',
                    x, y, theta, zone_name)

    def set_goals(self, poses: list[tuple[float, float, float]],
                  zone_name: str = '') -> None:
        """다중 경유점 설정 (NavigateThroughPoses 용)."""
        self._goals = poses
        self._goal = poses[-1] if poses else None
        self._zone_name = zone_name
        self._in_progress = False
        logger.info('NavigateToZone: goals set → %d poses, final=(%.2f,%.2f)',
                    len(poses), poses[-1][0], poses[-1][1])

    def _fire_nav_failed(self) -> None:
        if self._on_nav_failed:
            self._on_nav_failed()
        self._pub.publish_cmd_vel(0.0, 0.0)


def create_guiding_tree(
    publisher: RobotPublisherInterface,
    send_nav_goal: Optional[Callable[[float, float, float], bool]] = None,
    on_arrived: Optional[Callable[[str], None]] = None,
    on_nav_failed: Optional[Callable[[], None]] = None,
) -> NavigateToZone:
    """BT4 트리를 생성하여 반환. set_goal() 호출이 필요하므로 인스턴스를 직접 반환."""
    return NavigateToZone(
        name='BT4_Guiding',
        publisher=publisher,
        send_nav_goal=send_nav_goal,
        on_arrived=on_arrived,
        on_nav_failed=on_nav_failed,
    )

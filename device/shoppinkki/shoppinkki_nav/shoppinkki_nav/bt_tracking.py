"""BT 1: TRACKING / TRACKING_CHECKOUT  (py_trees 기반)

P-Control follower + RPLiDAR obstacle avoidance.

트리 구조:
    BT1_Tracking (Selector)
    ├─ FollowDoll (Sequence)
    │  ├─ CheckDetection       ← get_latest() != None → SUCCESS
    │  ├─ ComputeVelocity      ← P-Control linear_x, angular_z 계산
    │  └─ ObstacleAvoidance    ← LiDAR 감속 + cmd_vel 발행
    └─ HandleMiss              ← miss_count 증가, N_MISS_FRAMES 초과 시 FAILURE
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

import py_trees

from shoppinkki_interfaces import DollDetectorInterface, RobotPublisherInterface

try:
    from shoppinkki_core.config import (
        ANGULAR_Z_MAX,
        IMAGE_WIDTH,
        KP_ANGLE,
        KP_DIST,
        LINEAR_X_MAX,
        MIN_DIST,
        N_MISS_FRAMES,
        TARGET_SIZE,
    )
except ImportError:
    KP_ANGLE = 0.002
    KP_DIST = 0.003
    TARGET_SIZE = 200.0
    IMAGE_WIDTH = 640
    LINEAR_X_MAX = 0.22
    ANGULAR_Z_MAX = 1.0
    MIN_DIST = 0.25
    N_MISS_FRAMES = 30

logger = logging.getLogger(__name__)


# ── Shared state (Behaviour 간 데이터 전달) ──────────────────

class _TrackingCtx:
    """BT1 내부 Behaviour 간 공유 컨텍스트."""

    def __init__(self, detector, publisher, get_scan):
        self.detector = detector
        self.publisher = publisher
        self.get_scan = get_scan
        self.miss_count: int = 0
        # ComputeVelocity → ObstacleAvoidance 로 전달
        self.linear_x: float = 0.0
        self.angular_z: float = 0.0


# ── Leaf Behaviours ──────────────────────────────────────────

class CheckDetection(py_trees.behaviour.Behaviour):
    """인형 감지 여부 확인.

    감지됨 → SUCCESS (miss_count 리셋)
    미감지 → FAILURE (FollowDoll Sequence 탈출 → HandleMiss 로)
    """

    def __init__(self, name: str, ctx: _TrackingCtx) -> None:
        super().__init__(name)
        self._ctx = ctx

    def update(self) -> py_trees.common.Status:
        det = self._ctx.detector.get_latest()
        if det is not None:
            self._ctx.miss_count = 0
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.FAILURE


class ComputeVelocity(py_trees.behaviour.Behaviour):
    """P-Control 속도 계산.

    bbox 크기(area) → linear_x (거리 제어)
    bbox 중심(cx)   → angular_z (방향 제어)
    """

    def __init__(self, name: str, ctx: _TrackingCtx) -> None:
        super().__init__(name)
        self._ctx = ctx

    def update(self) -> py_trees.common.Status:
        det = self._ctx.detector.get_latest()
        if det is None:
            return py_trees.common.Status.FAILURE

        import math

        # sqrt(area) ≈ bbox 한 변 길이 — 거리에 역비례 (area는 역제곱)
        # 이렇게 하면 속도 변화가 선형적이고 부드러움
        current_size = math.sqrt(det.area)
        error_size = TARGET_SIZE - current_size
        self._ctx.linear_x = KP_DIST * error_size
        self._ctx.linear_x = max(0.0, min(LINEAR_X_MAX, self._ctx.linear_x))

        error_cx = det.cx - IMAGE_WIDTH / 2.0
        self._ctx.angular_z = -KP_ANGLE * error_cx
        self._ctx.angular_z = max(-ANGULAR_Z_MAX, min(ANGULAR_Z_MAX, self._ctx.angular_z))

        return py_trees.common.Status.SUCCESS


class ObstacleAvoidance(py_trees.behaviour.Behaviour):
    """LiDAR 장애물 감속 + cmd_vel 발행.

    전방 장애물이 MIN_DIST 이내이면 linear_x를 비례 감속.
    최종 속도를 cmd_vel 로 발행 → RUNNING (추종 지속).
    """

    def __init__(self, name: str, ctx: _TrackingCtx) -> None:
        super().__init__(name)
        self._ctx = ctx

    def update(self) -> py_trees.common.Status:
        linear_x = self._ctx.linear_x
        angular_z = self._ctx.angular_z

        # LiDAR 감속
        if self._ctx.get_scan is not None and linear_x > 0.0:
            try:
                distances = self._ctx.get_scan()
                if distances:
                    min_fwd = min(d for d in distances if d > 0.01)
                    if min_fwd < MIN_DIST:
                        factor = max(0.0, min_fwd / MIN_DIST)
                        linear_x *= factor
            except Exception as e:
                logger.debug('ObstacleAvoidance: scan error: %s', e)

        self._ctx.publisher.publish_cmd_vel(linear_x, angular_z)
        return py_trees.common.Status.RUNNING

    def terminate(self, new_status: py_trees.common.Status) -> None:
        self._ctx.publisher.publish_cmd_vel(0.0, 0.0)


class HandleMiss(py_trees.behaviour.Behaviour):
    """미감지 처리.

    miss_count 증가 + 정지.
    N_MISS_FRAMES 초과 → FAILURE (BTRunner 가 SEARCHING 전환)
    아직 여유 있음 → RUNNING (재감지 대기)
    """

    def __init__(self, name: str, ctx: _TrackingCtx) -> None:
        super().__init__(name)
        self._ctx = ctx

    def update(self) -> py_trees.common.Status:
        self._ctx.miss_count += 1
        self._ctx.publisher.publish_cmd_vel(0.0, 0.0)

        if self._ctx.miss_count >= N_MISS_FRAMES:
            logger.info('HandleMiss: %d consecutive misses → FAILURE',
                        self._ctx.miss_count)
            return py_trees.common.Status.FAILURE

        return py_trees.common.Status.RUNNING


# ── Tree factory ─────────────────────────────────────────────

def create_tracking_tree(
    doll_detector: DollDetectorInterface,
    publisher: RobotPublisherInterface,
    get_scan: Optional[Callable[[], List[float]]] = None,
) -> py_trees.behaviour.Behaviour:
    """BT1 트리를 생성하여 반환.

    BT1_Tracking (Selector, memory=False)
    ├─ FollowDoll (Sequence, memory=False)
    │  ├─ CheckDetection
    │  ├─ ComputeVelocity
    │  └─ ObstacleAvoidance
    └─ HandleMiss
    """
    ctx = _TrackingCtx(doll_detector, publisher, get_scan)

    follow = py_trees.composites.Sequence(name='FollowDoll', memory=False)
    follow.add_children([
        CheckDetection('CheckDetection', ctx),
        ComputeVelocity('ComputeVelocity', ctx),
        ObstacleAvoidance('ObstacleAvoidance', ctx),
    ])

    root = py_trees.composites.Selector(name='BT1_Tracking', memory=False)
    root.add_children([
        follow,
        HandleMiss('HandleMiss', ctx),
    ])

    return root

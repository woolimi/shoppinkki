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
        KI_ANGLE,
        KD_ANGLE,
        KP_DIST,
        KI_DIST,
        KD_DIST,
        LINEAR_X_MAX,
        MIN_DIST,
        N_MISS_FRAMES,
        TARGET_SIZE,
        ANGLE_DEADZONE,
    )
except ImportError:
    KP_ANGLE = 0.002
    KP_DIST = 0.005
    TARGET_SIZE = 250.0
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
        # ComputeVelocity → ObstacleAvoidance 전달용
        self.linear_x: float = 0.0
        self.angular_z: float = 0.0
        
        # PID 제어용 상태 (거리 및 각도)
        self.prev_error_size: float = 0.0
        self.integral_size: float = 0.0
        self.prev_error_cx: float = 0.0
        self.integral_cx: float = 0.0
        self.last_time: float = 0.0


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
        import time

        # ── 시간 간격 계산 (dt) ──
        now = time.monotonic()
        if self._ctx.last_time == 0.0:
            dt = 0.1  # 기본 10Hz 가정
        else:
            dt = now - self._ctx.last_time
        self._ctx.last_time = now
        
        # dt가 너무 크면(예: 일시 중지 후 재개) 튈 수 있으므로 제한
        if dt > 0.5: dt = 0.1

        # ── 1. 거리 PID (linear_x) ──
        current_size = math.sqrt(det.area)
        error_size = TARGET_SIZE - current_size
        
        self._ctx.integral_size += error_size * dt
        # 적분 윈드업 방지 (Clamping)
        self._ctx.integral_size = max(-50.0, min(50.0, self._ctx.integral_size))
        
        derivative_size = (error_size - self._ctx.prev_error_size) / dt
        self._ctx.prev_error_size = error_size

        self._ctx.linear_x = (KP_DIST * error_size) + (KI_DIST * self._ctx.integral_size) + (KD_DIST * derivative_size)
        self._ctx.linear_x = max(0.0, min(LINEAR_X_MAX, self._ctx.linear_x))

        # ── 2. 방향 PID (angular_z) ──
        error_cx = (IMAGE_WIDTH / 2.0) - det.cx  # 좌우 편차 (중심이 0이 되도록)
        
        # Deadzone: 중심 근처에서는 회전하지 않음 (Oscillation 방지)
        if abs(error_cx) < ANGLE_DEADZONE:
            error_cx = 0.0

        self._ctx.integral_cx += error_cx * dt
        self._ctx.integral_cx = max(-200.0, min(200.0, self._ctx.integral_cx))
        
        derivative_cx = (error_cx - self._ctx.prev_error_cx) / dt
        self._ctx.prev_error_cx = error_cx

        target_angular_z = (KP_ANGLE * error_cx) + (KI_ANGLE * self._ctx.integral_cx) + (KD_ANGLE * derivative_cx)
        
        # Smoothing (Low-pass filter for angular velocity)
        smoothing = 0.3 # 30% new value, 70% old value
        self._ctx.angular_z = (smoothing * target_angular_z) + ((1.0 - smoothing) * self._ctx.angular_z)
        self._ctx.angular_z = max(-ANGULAR_Z_MAX, min(ANGULAR_Z_MAX, self._ctx.angular_z))

        # ── [NEW] LKP (Last Known Position) 메모리 저장 ──
        # doll_detector 가 이미 'last_known_direction' 정보를 제공할 수도 있으나,
        # P-Control 레벨에서 실제 틀어진 방향을 저장하는 것이 더 정확함.
        try:
            bb = py_trees.blackboard.Blackboard()
            # angular_z가 양수(왼쪽 회전 중)면 1.0, 음수(오른쪽 회전 중)면 -1.0
            if abs(self._ctx.angular_z) > 0.01:
                bb.set("last_known_direction", 1.0 if self._ctx.angular_z > 0 else -1.0)
        except Exception:
            pass

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

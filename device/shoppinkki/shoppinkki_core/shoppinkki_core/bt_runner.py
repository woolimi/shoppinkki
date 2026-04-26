"""BT Runner: py_trees_ros 기반 Behaviour Tree 관리자.

하나의 루트 트리에 모든 BT(BT1~BT5)를 배치하고,
SM 상태에 따라 해당 BT만 실행한다.

py_trees_ros_viewer 로 실시간 시각화 가능:
    ros2 run py_trees_ros_viewer py-trees-tree-viewer

트리 구조:
    Root (Selector)
    ├─ [TRACKING] (Sequence)
    │  ├─ StateGuard("TRACKING|TRACKING_CHECKOUT")
    │  └─ BT1_Tracking (PControl)
    ├─ [SEARCHING] (Sequence)
    │  ├─ StateGuard("SEARCHING")
    │  └─ BT2_Searching (RotateSearch)
    ├─ [WAITING] (Sequence)
    │  ├─ StateGuard("WAITING")
    │  └─ BT3_Waiting (WaitAndAvoid)
    ├─ [GUIDING] (Sequence)
    │  ├─ StateGuard("GUIDING")
    │  └─ BT4_Guiding (NavigateToZone)
    └─ [RETURNING] (Sequence)
       ├─ StateGuard("RETURNING")
       └─ BT5_Returning (ReturnToCharger)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, Optional, Set

import py_trees
import py_trees_ros.trees
from rclpy.node import Node
from shoppinkki_interfaces import DollDetectorInterface

from .state_machine import ShoppinkkiFSM

logger = logging.getLogger(__name__)


# ── StateGuard: SM 상태 체크용 Behaviour ─────────────────────

class StateGuard(py_trees.behaviour.Behaviour):
    """SM 이 허용 상태 중 하나이면 SUCCESS, 아니면 FAILURE."""

    def __init__(self, name: str, sm: ShoppinkkiFSM,
                 allowed_states: Set[str]) -> None:
        super().__init__(name)
        self._sm = sm
        self._allowed = allowed_states

    def update(self) -> py_trees.common.Status:
        if self._sm.state in self._allowed:
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.FAILURE


# ── BTRunner ─────────────────────────────────────────────────

class BTRunner:
    """py_trees_ros 기반 BT 라이프사이클 관리자.

    Parameters
    ----------
    sm:
        ShoppinkkiFSM 인스턴스.
    bt_tracking ... bt_returning:
        py_trees.behaviour.Behaviour 인스턴스 (BT1~BT5).
    on_arrived / on_nav_failed:
        BT4 결과 콜백.
    """

    def __init__(
        self,
        sm: ShoppinkkiFSM,
        bt_tracking: py_trees.behaviour.Behaviour,
        bt_searching: py_trees.behaviour.Behaviour,
        bt_waiting: py_trees.behaviour.Behaviour,
        bt_guiding: py_trees.behaviour.Behaviour,
        bt_returning: py_trees.behaviour.Behaviour,
        on_arrived: Optional[Callable[[], None]] = None,
        on_nav_failed: Optional[Callable[[], None]] = None,
        doll_detector: Optional[DollDetectorInterface] = None,
        is_registration_active: Optional[Callable[[], bool]] = None,
        is_tracking_grace_active: Optional[Callable[[], bool]] = None,
        has_unpaid_items: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.sm = sm
        self.detector = doll_detector
        self._on_arrived = on_arrived
        self._on_nav_failed = on_nav_failed
        self._is_registration_active = is_registration_active
        self._is_tracking_grace_active = is_tracking_grace_active
        self._has_unpaid_items = has_unpaid_items
        self.follow_disabled: bool = False
        self._last_search_fail_time: float = 0.0
        self._SEARCH_COOLDOWN: float = 5.0 # Seconds
        self._enable_idle_proactive_search: bool = (
            os.environ.get('ENABLE_IDLE_PROACTIVE_SEARCH', 'false').lower() == 'true'
        )

        # ── 루트 트리 구성 ────────────────────
        self._root = py_trees.composites.Selector(
            name='ShopPinkki_BT', memory=False)

        # BT1: TRACKING / TRACKING_CHECKOUT
        bt1_seq = py_trees.composites.Sequence(
            name='[TRACKING]', memory=True)
        bt1_seq.add_children([
            StateGuard('State=TRACKING?', sm,
                       {'TRACKING', 'TRACKING_CHECKOUT'}),
            bt_tracking,
        ])

        # BT2: SEARCHING
        bt2_seq = py_trees.composites.Sequence(
            name='[SEARCHING]', memory=True)
        bt2_seq.add_children([
            StateGuard('State=SEARCHING?', sm, {'SEARCHING'}),
            bt_searching,
        ])

        # BT3: WAITING
        bt3_seq = py_trees.composites.Sequence(
            name='[WAITING]', memory=True)
        bt3_seq.add_children([
            StateGuard('State=WAITING?', sm, {'WAITING'}),
            bt_waiting,
        ])

        # BT4: GUIDING (memory=False: 매 tick StateGuard 재평가)
        bt4_seq = py_trees.composites.Sequence(
            name='[GUIDING]', memory=False)
        bt4_seq.add_children([
            StateGuard('State=GUIDING?', sm, {'GUIDING'}),
            bt_guiding,
        ])

        # BT5: RETURNING (memory=False: 매 tick StateGuard 재평가)
        bt5_seq = py_trees.composites.Sequence(
            name='[RETURNING]', memory=False)
        bt5_seq.add_children([
            StateGuard('State=RETURNING?', sm, {'RETURNING'}),
            bt_returning,
        ])

        self._root.add_children([bt1_seq, bt2_seq, bt3_seq, bt4_seq, bt5_seq])

        # ── py_trees_ros BehaviourTree 래퍼 ──────
        self._tree = py_trees_ros.trees.BehaviourTree(
            root=self._root, unicode_tree_debug=False)

        # BT 인스턴스 참조 (외부 접근용 + _get_active_bt에서 children index 우회)
        self._bt_tracking = bt_tracking
        self._bt_searching = bt_searching
        self._bt_guiding = bt_guiding
        self._bt_waiting = bt_waiting
        self._bt_returning = bt_returning

        logger.info('BTRunner: py_trees 트리 구성 완료')
        logger.info('\n' + py_trees.display.unicode_tree(root=self._root))

    def setup(self, node: Node) -> None:
        """py_trees_ros setup — ROS 토픽 발행 시작 (viewer 연동)."""
        self._tree.setup(node=node, node_name='shoppinkki_bt')
        logger.info('BTRunner: py_trees_ros setup 완료 (viewer 연동 가능)')

    # ──────────────────────────────────────────
    # State change hook (called by SM callbacks)
    # ──────────────────────────────────────────

    def on_state_changed(self, new_state: str) -> None:
        """상태 변경 시 진행 중인 BT의 내부 상태를 리셋."""
        # 새 상태에 맞는 BT가 다음 tick에서 자동으로 시작됨
        if new_state == 'SEARCHING':
            # ── [NEW] 진입 시마다 LKP와 시작 시간을 초기화 ──
            if hasattr(self._bt_searching, 'ctx'):
                self._bt_searching.ctx.start_time = 0.0
                logger.info('BTRunner: SEARCHING 진입, start_time 초기화됨 (LKP 방향 재로드)')
        # (StateGuard가 게이트 역할)
        # WAITING 진입 시 BT3를 INVALID로 내려 initialise()를 강제한다.
        if new_state == 'WAITING':
            self._bt_waiting.stop(py_trees.common.Status.INVALID)
        # follow_disabled 처리
        if self.follow_disabled and new_state in ('TRACKING', 'TRACKING_CHECKOUT'):
            logger.info('BTRunner: follow_disabled — BT1 skipped for state=%s',
                        new_state)

        # GUIDING 이탈 시 진행 중인 Nav2 goal 취소
        if new_state != 'GUIDING' and hasattr(self._bt_guiding, 'cancel_nav'):
            self._bt_guiding.cancel_nav()

        # 상태 전환 시 모든 Sequence를 리셋하여 다음 tick에서 깨끗하게 시작
        for child in self._root.children:
            if child.status != py_trees.common.Status.INVALID:
                child.stop(py_trees.common.Status.INVALID)

        logger.info('BTRunner: state changed to %s (BT reset)', new_state)

    # ──────────────────────────────────────────
    # Tick loop (called at ~10 Hz from main_node timer)
    # ──────────────────────────────────────────

    def tick(self) -> None:
        """루트 트리를 한번 tick하고 BT 결과에 따라 SM 전이 처리."""
        # follow_disabled 중에는 TRACKING guard가 통과해도 실행 안 함
        if self.follow_disabled and self.sm.state in ('TRACKING', 'TRACKING_CHECKOUT'):
            return

        self._tree.tick()

        # ── 각 BT의 결과 확인 → SM 전이 ──────
        self._handle_transitions()

    def _handle_transitions(self) -> None:
        """BT 결과(SUCCESS/FAILURE)에 따른 SM 상태 전이."""
        state = self.sm.state

        # IDLE은 BT가 없는 특수 케이스 — Auto-Resume / Proactive SEARCHING 분기.
        if state == 'IDLE':
            self._handle_idle_transition()
            return

        bt = self._get_active_bt(state)
        if bt is None or bt.status == py_trees.common.Status.RUNNING:
            return

        handler = self._STATE_TRANSITION_HANDLERS.get(state)
        if handler is not None:
            handler(self, bt.status)

    # ── per-state transition handlers ─────────

    def _handle_idle_transition(self) -> None:
        if self._is_registration_active and self._is_registration_active():
            return

        if not (self.detector is not None
                and self.detector.is_ready()
                and self.detector.is_connected()):
            return

        # [Auto-Resume] 이미 등록된 주인을 IDLE에서 다시 보면 즉시 TRACKING 복귀.
        if self.detector.get_latest() is not None:
            logger.info('BTRunner: Re-acquired owner from IDLE! Resuming TRACKING')
            self.sm.enter_tracking()
            return

        # Proactive SEARCHING: 등록된 주인이 안 보이면 cooldown 후 탐색 모드로.
        if not self._enable_idle_proactive_search:
            return
        elapsed = time.monotonic() - self._last_search_fail_time
        if elapsed >= self._SEARCH_COOLDOWN:
            logger.info('BTRunner: Proactive SEARCHING - owner missing from IDLE')
            self.sm.enter_searching()
        else:
            logger.debug('BTRunner: Search cooldown active (%.1fs left)',
                         self._SEARCH_COOLDOWN - elapsed)

    def _handle_tracking_transition(self, status) -> None:
        if status != py_trees.common.Status.FAILURE:
            return
        if self._is_tracking_grace_active and self._is_tracking_grace_active():
            logger.info('BTRunner: tracking grace active, suppress SEARCHING transition')
            return
        self.sm.enter_searching()

    def _handle_searching_transition(self, status) -> None:
        if status == py_trees.common.Status.SUCCESS:
            self.sm.enter_tracking()
        elif status == py_trees.common.Status.FAILURE:
            self._last_search_fail_time = time.monotonic()
            logger.info('BTRunner: SEARCHING failed → returning to IDLE')
            self.sm.enter_idle()

    def _handle_guiding_transition(self, status) -> None:
        if status == py_trees.common.Status.SUCCESS:
            if self._on_arrived:
                self._on_arrived()
            self.sm.enter_waiting()
        elif status == py_trees.common.Status.FAILURE:
            if self._on_nav_failed:
                self._on_nav_failed()
            self.sm.enter_waiting()

    def _handle_returning_transition(self, status) -> None:
        if status == py_trees.common.Status.SUCCESS:
            self.sm.enter_charging()
        elif status == py_trees.common.Status.FAILURE:
            logger.warning('BTRunner: BT5 RETURNING failed')

    def _handle_waiting_transition(self, status) -> None:
        if status != py_trees.common.Status.FAILURE:
            return
        logger.info('BTRunner: BT3 WAITING timeout')
        unpaid = False
        if self._has_unpaid_items:
            try:
                unpaid = bool(self._has_unpaid_items())
            except Exception:
                # Same policy as main_node._has_unpaid_items: unknown → not unpaid → RETURNING.
                logger.exception('BTRunner: has_unpaid_items callback failed')
        self.sm.waiting_exit_by_unpaid(unpaid)

    _STATE_TRANSITION_HANDLERS: dict = {
        'TRACKING': _handle_tracking_transition,
        'TRACKING_CHECKOUT': _handle_tracking_transition,
        'SEARCHING': _handle_searching_transition,
        'GUIDING': _handle_guiding_transition,
        'RETURNING': _handle_returning_transition,
        'WAITING': _handle_waiting_transition,
    }

    _STATE_TO_BT_ATTR: dict[str, str] = {
        'TRACKING': '_bt_tracking',
        'TRACKING_CHECKOUT': '_bt_tracking',
        'SEARCHING': '_bt_searching',
        'WAITING': '_bt_waiting',
        'GUIDING': '_bt_guiding',
        'RETURNING': '_bt_returning',
    }

    def _get_active_bt(self, state: str):
        """현재 SM 상태에 대응하는 leaf BT를 반환."""
        attr = self._STATE_TO_BT_ATTR.get(state)
        return getattr(self, attr, None) if attr else None

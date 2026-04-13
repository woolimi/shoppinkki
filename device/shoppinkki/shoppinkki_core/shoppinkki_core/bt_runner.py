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
from typing import Callable, Optional, Set

import py_trees
import py_trees_ros.trees
from rclpy.node import Node

from .state_machine import ShoppinkiSM

logger = logging.getLogger(__name__)


# ── StateGuard: SM 상태 체크용 Behaviour ─────────────────────

class StateGuard(py_trees.behaviour.Behaviour):
    """SM 이 허용 상태 중 하나이면 SUCCESS, 아니면 FAILURE."""

    def __init__(self, name: str, sm: ShoppinkiSM,
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
        ShoppinkiSM 인스턴스.
    bt_tracking ... bt_returning:
        py_trees.behaviour.Behaviour 인스턴스 (BT1~BT5).
    on_arrived / on_nav_failed:
        BT4 결과 콜백.
    """

    def __init__(
        self,
        sm: ShoppinkiSM,
        bt_tracking: py_trees.behaviour.Behaviour,
        bt_searching: py_trees.behaviour.Behaviour,
        bt_waiting: py_trees.behaviour.Behaviour,
        bt_guiding: py_trees.behaviour.Behaviour,
        bt_returning: py_trees.behaviour.Behaviour,
        on_arrived: Optional[Callable[[], None]] = None,
        on_nav_failed: Optional[Callable[[], None]] = None,
    ) -> None:
        self.sm = sm
        self._on_arrived = on_arrived
        self._on_nav_failed = on_nav_failed
        self.follow_disabled: bool = False

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

        # BT 인스턴스 참조 (외부 접근용)
        self._bt_tracking = bt_tracking
        self._bt_searching = bt_searching
        self._bt_guiding = bt_guiding

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

        bt = self._get_active_bt(state)
        if bt is None or bt.status == py_trees.common.Status.RUNNING:
            return

        status = bt.status

        if state in ('TRACKING', 'TRACKING_CHECKOUT'):
            if status == py_trees.common.Status.FAILURE:
                self.sm.enter_searching()

        elif state == 'SEARCHING':
            if status == py_trees.common.Status.SUCCESS:
                self.sm.enter_tracking()
            elif status == py_trees.common.Status.FAILURE:
                self.sm.enter_waiting()

        elif state == 'GUIDING':
            if status == py_trees.common.Status.SUCCESS:
                if self._on_arrived:
                    self._on_arrived()
                self.sm.enter_waiting()
            elif status == py_trees.common.Status.FAILURE:
                if self._on_nav_failed:
                    self._on_nav_failed()
                self.sm.resume_tracking()

        elif state == 'RETURNING':
            if status == py_trees.common.Status.SUCCESS:
                self.sm.enter_charging()
            elif status == py_trees.common.Status.FAILURE:
                logger.warning('BTRunner: BT5 RETURNING failed')

        elif state == 'WAITING':
            if status == py_trees.common.Status.FAILURE:
                logger.info('BTRunner: BT3 WAITING timeout')

    def _get_active_bt(self, state: str):
        """현재 SM 상태에 대응하는 leaf BT를 반환."""
        mapping = {
            'TRACKING': self._bt_tracking,
            'TRACKING_CHECKOUT': self._bt_tracking,
            'SEARCHING': self._bt_searching,
        }
        # BT3~BT5: root children의 leaf로 접근
        children = self._root.children
        state_map = {
            'WAITING': children[2].children[1] if len(children) > 2 else None,
            'GUIDING': children[3].children[1] if len(children) > 3 else None,
            'RETURNING': children[4].children[1] if len(children) > 4 else None,
        }
        mapping.update(state_map)
        return mapping.get(state)

"""결제 구역 진입/이탈 감시 매니저.

main_node에서 분리된 결제 구역(zone 150) 경계 감시 컴포넌트.

`BoundaryMonitor`를 래핑하여 LocalizationManager의 위치 갱신을 받아 zone
진입/이탈을 감지한다. 상태 변화 시 main_node가 wire한 hook 콜백을 호출하여
부수효과(WebSocket 이벤트 publish, motion 차단 등)를 발생시킨다.

main_node가 wire하는 hook
-------------------------
on_zone_enter:
    TRACKING 상태에서 결제 구역 최초 진입 시 호출.
on_exit_blocked:
    이탈 차단 이벤트 (`is_exit_allowed`가 False면 차단 발생).
on_reenter:
    결제 구역 재진입 시 호출.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    import rclpy.node
    from .localization_manager import LocalizationManager

logger = logging.getLogger(__name__)


class CheckoutZoneGuard:
    """결제 구역 boundary 감시 + 미납 시 이탈 차단 매니저.

    BoundaryMonitor 인스턴스를 외부에서 주입받아 그 콜백을
    이 클래스의 내부 메서드로 재배선한다. main_node는 이 클래스의
    `on_zone_enter` / `on_exit_blocked` / `on_reenter` 콜백 hook을 wire하여
    실제 부수효과(publish, motion block 등)를 처리한다.
    """

    def __init__(
        self,
        node: 'rclpy.node.Node',
        localization: 'LocalizationManager',
        boundary_monitor=None,
        is_exit_allowed: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._node = node
        self._localization = localization
        self._boundary_monitor = boundary_monitor

        # 외부에서 SM 상태를 보고 이탈 허용 여부 판단 (main_node가 sm 소유)
        self._is_exit_allowed_fn: Optional[Callable[[], bool]] = is_exit_allowed

        # 마지막 차단 toast publish 시각 (rate-limit)
        self._last_blocked_toast: float = 0.0

        # main_node가 wire하는 콜백 hook
        self.on_zone_enter: Optional[Callable[[], None]] = None
        self.on_exit_blocked: Optional[Callable[[], None]] = None
        self.on_reenter: Optional[Callable[[], None]] = None

        # BoundaryMonitor 콜백을 본 클래스 메서드로 재배선 (공개 setter 경유).
        if self._boundary_monitor is not None:
            self._boundary_monitor.set_callbacks(
                on_enter=self.emit_zone_enter,
                on_exit_blocked=self.on_exit_blocked_event,
                on_reenter=self.on_reenter_event,
            )

        # LocalizationManager → BoundaryMonitor wiring (AMCL pose 갱신 시 호출).
        if self._localization is not None and self._boundary_monitor is not None:
            self._localization.on_pose_updated = self._on_pose_updated

    # ──────────────────────────────────────────
    # Public configuration
    # ──────────────────────────────────────────

    def set_exit_allowed_predicate(
        self, fn: Optional[Callable[[], bool]]
    ) -> None:
        """`is_exit_allowed`를 외부에서 늦게 wire할 때 사용."""
        self._is_exit_allowed_fn = fn

    @property
    def last_blocked_toast(self) -> float:
        """마지막 차단 toast publish 시각 (rate-limit 디버그용 read-only)."""
        return self._last_blocked_toast

    # ──────────────────────────────────────────
    # Pose-update relay
    # ──────────────────────────────────────────

    def _on_pose_updated(self, x: float, y: float) -> None:
        """위치 갱신 시 BoundaryMonitor로 전달."""
        if self._boundary_monitor is None:
            return
        try:
            self._boundary_monitor.on_pose_update(x, y)
        except Exception as e:
            self._node.get_logger().warning(
                f'CheckoutZoneGuard: boundary update error: {e}'
            )

    # ──────────────────────────────────────────
    # State queries
    # ──────────────────────────────────────────

    def is_exit_allowed(self) -> bool:
        """결제 구역 밖으로 이동 허용 상태.

        외부에서 주입한 predicate(`is_exit_allowed`)을 호출. 미주입 시 False.
        """
        if self._is_exit_allowed_fn is None:
            return False
        try:
            return bool(self._is_exit_allowed_fn())
        except Exception as e:
            self._node.get_logger().warning(
                f'CheckoutZoneGuard: is_exit_allowed predicate error: {e}'
            )
            return False

    # ──────────────────────────────────────────
    # BoundaryMonitor callback handlers
    # (BoundaryMonitor가 직접 호출 → 외부 hook으로 fan-out)
    # ──────────────────────────────────────────

    def _safe_call(self, hook: Optional[Callable[[], None]], hook_name: str) -> None:
        """외부 hook 호출 시 예외를 삼키고 로깅만 한다 (3개 핸들러 공통)."""
        if hook is None:
            return
        try:
            hook()
        except Exception as e:
            self._node.get_logger().warning(
                f'CheckoutZoneGuard: {hook_name} hook error: {e}'
            )

    def emit_zone_enter(self) -> None:
        """TRACKING 상태에서 결제 구역 최초 진입."""
        self._safe_call(self.on_zone_enter, 'on_zone_enter')

    def on_exit_blocked_event(self) -> None:
        """결제 구역 이탈 시도: 허용 상태가 아니면 motion 차단 + toast publish.

        실제 motion block / publish 작업은 main_node가 wire한 `on_exit_blocked`
        hook이 담당한다.
        """
        self._safe_call(self.on_exit_blocked, 'on_exit_blocked')

    def on_reenter_event(self) -> None:
        """결제 구역 재진입: 차단 해제 hook 호출."""
        self._safe_call(self.on_reenter, 'on_reenter')

    # ──────────────────────────────────────────
    # Toast rate-limit helper (for hooks)
    # ──────────────────────────────────────────

    def should_emit_blocked_toast(self, min_interval_sec: float = 1.0) -> bool:
        """마지막 차단 toast 이후 ``min_interval_sec`` 초 경과했으면 True.

        True 반환 시 내부 시각이 갱신되므로 hook은 호출 직후 publish하면 된다.
        """
        now = time.monotonic()
        if now - self._last_blocked_toast >= min_interval_sec:
            self._last_blocked_toast = now
            return True
        return False

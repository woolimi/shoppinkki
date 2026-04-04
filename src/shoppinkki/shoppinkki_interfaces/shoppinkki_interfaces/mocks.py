"""Mock implementations of all Protocol interfaces for unit testing.

Usage::

    from shoppinkki_interfaces import MockDollDetector, MockNavBT, BTStatus

    detector = MockDollDetector()
    detector.set_detection(Detection(cx=320, cy=240, area=12000, confidence=0.9))
    assert detector.get_latest() is not None
"""

from __future__ import annotations

from typing import Callable, List, Optional

from .protocols import BTStatus, CartItem, Detection


# ──────────────────────────────────────────────
# MockDollDetector
# ──────────────────────────────────────────────

class MockDollDetector:
    """Controllable mock for DollDetectorInterface."""

    def __init__(self) -> None:
        self._ready: bool = False
        self._latest: Optional[Detection] = None

    def register(self, frame) -> None:
        self._ready = True

    def run(self, frame) -> None:
        pass  # latest is set externally via set_detection()

    def get_latest(self) -> Optional[Detection]:
        return self._latest

    def is_ready(self) -> bool:
        return self._ready

    def reset(self) -> None:
        self._ready = False
        self._latest = None

    # ── test helpers ──

    def set_detection(self, detection: Optional[Detection]) -> None:
        """Inject a detection result for the next get_latest() call."""
        self._latest = detection

    def set_ready(self, ready: bool) -> None:
        self._ready = ready


# ──────────────────────────────────────────────
# MockQRScanner
# ──────────────────────────────────────────────

class MockQRScanner:
    """Controllable mock for QRScannerInterface."""

    def __init__(self) -> None:
        self._on_scanned: Optional[Callable[[str], None]] = None
        self._on_timeout: Optional[Callable[[], None]] = None
        self._running: bool = False

    def start(
        self,
        on_scanned: Callable[[str], None],
        on_timeout: Callable[[], None],
    ) -> None:
        self._on_scanned = on_scanned
        self._on_timeout = on_timeout
        self._running = True

    def stop(self) -> None:
        self._running = False

    # ── test helpers ──

    def simulate_scan(self, qr_data: str) -> None:
        """Simulate a successful QR scan."""
        if self._on_scanned and self._running:
            self._on_scanned(qr_data)

    def simulate_timeout(self) -> None:
        """Simulate a scan timeout."""
        if self._on_timeout and self._running:
            self._on_timeout()


# ──────────────────────────────────────────────
# MockNavBT
# ──────────────────────────────────────────────

class MockNavBT:
    """Controllable mock for NavBTInterface."""

    def __init__(self, result: BTStatus = BTStatus.RUNNING) -> None:
        self._result: BTStatus = result
        self._running: bool = False
        self.tick_count: int = 0
        self.started: bool = False
        self.stopped: bool = False

    def start(self) -> None:
        self._running = True
        self.started = True
        self.stopped = False

    def stop(self) -> None:
        self._running = False
        self.stopped = True

    def tick(self) -> BTStatus:
        if self._running:
            self.tick_count += 1
            return self._result
        return BTStatus.FAILURE

    # ── test helpers ──

    def set_result(self, result: BTStatus) -> None:
        self._result = result


# ──────────────────────────────────────────────
# MockBoundaryMonitor
# ──────────────────────────────────────────────

class MockBoundaryMonitor:
    """Controllable mock for BoundaryMonitorInterface."""

    def __init__(self) -> None:
        self._active: bool = False
        self._started: bool = False

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def set_active(self, active: bool) -> None:
        self._active = active

    @property
    def is_active(self) -> bool:
        return self._active


# ──────────────────────────────────────────────
# MockRobotPublisher
# ──────────────────────────────────────────────

class MockRobotPublisher:
    """Records all publish calls for assertion in tests."""

    def __init__(self) -> None:
        self.cmd_vel_history: List[tuple] = []
        self.status_history: List[dict] = []
        self.alarm_history: List[str] = []
        self.cart_history: List[List[CartItem]] = []

    def publish_cmd_vel(self, linear_x: float, angular_z: float) -> None:
        self.cmd_vel_history.append((linear_x, angular_z))

    def publish_status(
        self,
        mode: str,
        pos_x: float,
        pos_y: float,
        battery: float,
        is_locked_return: bool,
    ) -> None:
        self.status_history.append({
            'mode': mode,
            'pos_x': pos_x,
            'pos_y': pos_y,
            'battery': battery,
            'is_locked_return': is_locked_return,
        })

    def publish_alarm(self, event: str) -> None:
        self.alarm_history.append(event)

    def publish_cart(self, items: List[CartItem]) -> None:
        self.cart_history.append(list(items))

    # ── test helpers ──

    @property
    def last_status(self) -> Optional[dict]:
        return self.status_history[-1] if self.status_history else None

    @property
    def last_alarm(self) -> Optional[str]:
        return self.alarm_history[-1] if self.alarm_history else None

    @property
    def last_cmd_vel(self) -> Optional[tuple]:
        return self.cmd_vel_history[-1] if self.cmd_vel_history else None

    @property
    def last_linear_x(self) -> float:
        v = self.last_cmd_vel
        return v[0] if v is not None else 0.0

    @property
    def last_angular_z(self) -> float:
        v = self.last_cmd_vel
        return v[1] if v is not None else 0.0

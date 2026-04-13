"""Protocol interfaces shared across all ShopPinkki packages.

All hardware/Nav2 dependencies are abstracted behind these Protocols
so unit tests can use Mock implementations without a real robot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional

try:
    from typing import Protocol, runtime_checkable
except ImportError:  # Python < 3.8
    from typing_extensions import Protocol, runtime_checkable


# ──────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────

@dataclass
class Detection:
    """Single object detection result from YOLO / ReID pipeline."""

    cx: float          # bounding-box center X  (pixels)
    cy: float          # bounding-box center Y  (pixels)
    area: float        # bounding-box area      (pixels²)
    confidence: float  # detection confidence   (0.0 ~ 1.0)
    class_name: str = 'doll'
    bbox: Optional[List[float]] = None  # [x1, y1, x2, y2]
    mask: Optional[List[List[float]]] = None  # [[x1, y1], [x2, y2], ...]


@dataclass
class CartItem:
    """One item in the robot's shopping cart."""

    item_id: int
    product_name: str
    price: int
    is_paid: bool
    scanned_at: str    # ISO-8601 datetime string


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class BTStatus(Enum):
    """Behavior Tree tick result."""

    RUNNING = 'RUNNING'
    SUCCESS = 'SUCCESS'
    FAILURE = 'FAILURE'


# ──────────────────────────────────────────────
# Protocols
# ──────────────────────────────────────────────

@runtime_checkable
class DollDetectorInterface(Protocol):
    """Detects and tracks the owner doll via ReID + HSV histogram."""

    def register(self, frame) -> None:
        """Register owner template from the given camera frame (IDLE phase)."""
        ...

    def run(self, frame) -> None:
        """Run detection on frame; internally updates latest detection."""
        ...

    def get_latest(self) -> Optional[Detection]:
        """Return the most recent matched Detection, or None."""
        ...

    def is_ready(self) -> bool:
        """True once the owner template has been successfully registered."""
        ...

    def reset(self) -> None:
        """Clear registered template and detection buffer."""
        ...


@runtime_checkable
class QRScannerInterface(Protocol):
    """Scans QR codes from the camera and reports results via callbacks."""

    def start(
        self,
        on_scanned: Callable[[str], None],
        on_timeout: Callable[[], None],
    ) -> None:
        """Start scanning. Calls on_scanned(data) or on_timeout() after 30 s."""
        ...

    def stop(self) -> None:
        """Stop scanning."""
        ...


@runtime_checkable
class NavBTInterface(Protocol):
    """Single Behavior Tree (BT1~BT5) that can be started/stopped/ticked."""

    def start(self) -> None:
        """Activate this BT (called on SM state entry)."""
        ...

    def stop(self) -> None:
        """Deactivate this BT (called on SM state exit)."""
        ...

    def tick(self) -> BTStatus:
        """Execute one BT step. Returns RUNNING / SUCCESS / FAILURE."""
        ...


@runtime_checkable
class BoundaryMonitorInterface(Protocol):
    """Monitors robot AMCL pose and fires zone-crossing callbacks."""

    def start(self) -> None:
        """Start subscribing to /amcl_pose."""
        ...

    def stop(self) -> None:
        """Stop subscribing."""
        ...

    def set_active(self, active: bool) -> None:
        """Enable/disable boundary checks (active only in TRACKING states)."""
        ...


@runtime_checkable
class RobotPublisherInterface(Protocol):
    """Publishes ROS topics from the robot side (채널 G)."""

    def publish_cmd_vel(self, linear_x: float, angular_z: float) -> None:
        """Publish /cmd_vel."""
        ...

    def publish_status(
        self,
        mode: str,
        pos_x: float,
        pos_y: float,
        battery: float,
        is_locked_return: bool,
    ) -> None:
        """Publish /robot_<id>/status JSON."""
        ...

    def publish_alarm(self, event: str) -> None:
        """Publish /robot_<id>/alarm JSON (event: 'LOCKED' | 'HALTED')."""
        ...

    def publish_cart(self, items: List[CartItem]) -> None:
        """Publish /robot_<id>/cart JSON."""
        ...

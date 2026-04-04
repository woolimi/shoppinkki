"""ShopPinkki shared Protocol interfaces and Mock implementations."""
from .protocols import (
    Detection,
    CartItem,
    BTStatus,
    DollDetectorInterface,
    QRScannerInterface,
    NavBTInterface,
    BoundaryMonitorInterface,
    RobotPublisherInterface,
)
from .mocks import (
    MockDollDetector,
    MockQRScanner,
    MockNavBT,
    MockBoundaryMonitor,
    MockRobotPublisher,
)

__all__ = [
    'Detection',
    'CartItem',
    'BTStatus',
    'DollDetectorInterface',
    'QRScannerInterface',
    'NavBTInterface',
    'BoundaryMonitorInterface',
    'RobotPublisherInterface',
    'MockDollDetector',
    'MockQRScanner',
    'MockNavBT',
    'MockBoundaryMonitor',
    'MockRobotPublisher',
]

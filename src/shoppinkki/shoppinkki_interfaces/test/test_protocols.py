"""Tests for shoppinkki_interfaces protocols and mocks."""

import pytest
from shoppinkki_interfaces import (
    BTStatus,
    CartItem,
    Detection,
    MockBoundaryMonitor,
    MockDollDetector,
    MockNavBT,
    MockQRScanner,
    MockRobotPublisher,
    DollDetectorInterface,
    NavBTInterface,
    BoundaryMonitorInterface,
    RobotPublisherInterface,
)


class TestDetection:
    def test_fields(self):
        d = Detection(cx=320.0, cy=240.0, area=12000.0, confidence=0.92)
        assert d.cx == 320.0
        assert d.area == 12000.0
        assert d.class_name == 'doll'


class TestCartItem:
    def test_fields(self):
        item = CartItem(item_id=1, product_name='콜라', price=1500,
                        is_paid=False, scanned_at='2026-01-01T00:00:00')
        assert item.product_name == '콜라'
        assert not item.is_paid


class TestMockDollDetector:
    def setup_method(self):
        self.det = MockDollDetector()

    def test_initial_not_ready(self):
        assert not self.det.is_ready()
        assert self.det.get_latest() is None

    def test_register_makes_ready(self):
        self.det.register(frame=None)
        assert self.det.is_ready()

    def test_set_detection(self):
        d = Detection(cx=100, cy=200, area=5000, confidence=0.8)
        self.det.set_detection(d)
        assert self.det.get_latest() is d

    def test_reset_clears(self):
        self.det.register(None)
        self.det.set_detection(Detection(100, 200, 5000, 0.8))
        self.det.reset()
        assert not self.det.is_ready()
        assert self.det.get_latest() is None

    def test_implements_protocol(self):
        assert isinstance(self.det, DollDetectorInterface)


class TestMockQRScanner:
    def test_scan_callback(self):
        scanner = MockQRScanner()
        results = []
        scanner.start(on_scanned=results.append, on_timeout=lambda: None)
        scanner.simulate_scan('product:42')
        assert results == ['product:42']

    def test_timeout_callback(self):
        scanner = MockQRScanner()
        timed_out = []
        scanner.start(on_scanned=lambda x: None, on_timeout=lambda: timed_out.append(True))
        scanner.simulate_timeout()
        assert timed_out

    def test_no_callback_after_stop(self):
        scanner = MockQRScanner()
        results = []
        scanner.start(on_scanned=results.append, on_timeout=lambda: None)
        scanner.stop()
        scanner.simulate_scan('product:99')
        assert results == []


class TestMockNavBT:
    def test_initial_failure(self):
        bt = MockNavBT()
        assert bt.tick() == BTStatus.FAILURE  # not started

    def test_running_after_start(self):
        bt = MockNavBT(BTStatus.RUNNING)
        bt.start()
        assert bt.tick() == BTStatus.RUNNING

    def test_set_result(self):
        bt = MockNavBT()
        bt.start()
        bt.set_result(BTStatus.SUCCESS)
        assert bt.tick() == BTStatus.SUCCESS

    def test_tick_count(self):
        bt = MockNavBT()
        bt.start()
        bt.tick(); bt.tick(); bt.tick()
        assert bt.tick_count == 3

    def test_implements_protocol(self):
        assert isinstance(MockNavBT(), NavBTInterface)


class TestMockBoundaryMonitor:
    def test_set_active(self):
        bm = MockBoundaryMonitor()
        assert not bm.is_active
        bm.set_active(True)
        assert bm.is_active

    def test_implements_protocol(self):
        assert isinstance(MockBoundaryMonitor(), BoundaryMonitorInterface)


class TestMockRobotPublisher:
    def setup_method(self):
        self.pub = MockRobotPublisher()

    def test_publish_status(self):
        self.pub.publish_status('TRACKING', 1.0, 2.0, 80.0, False)
        assert self.pub.last_status['mode'] == 'TRACKING'
        assert self.pub.last_status['battery'] == 80.0

    def test_publish_alarm(self):
        self.pub.publish_alarm('LOCKED')
        assert self.pub.last_alarm == 'LOCKED'

    def test_publish_cmd_vel(self):
        self.pub.publish_cmd_vel(0.3, -0.5)
        assert self.pub.last_cmd_vel == (0.3, -0.5)

    def test_implements_protocol(self):
        assert isinstance(self.pub, RobotPublisherInterface)

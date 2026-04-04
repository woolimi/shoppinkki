"""Unit tests for DollDetector — no real YOLO/camera needed.

We subclass DollDetector to inject fake YOLO responses.
"""

import pytest
from shoppinkki_interfaces import Detection
from shoppinkki_perception.doll_detector import (
    DollDetector,
    _cosine_similarity,
    _histogram_correlation,
)


class FakeDollDetector(DollDetector):
    """DollDetector with overridable YOLO responses."""

    def __init__(self):
        super().__init__()
        self._fake_detections = []

    def set_fake_detections(self, detections):
        """Set list of bbox dicts to return from _run_yolo."""
        self._fake_detections = detections

    def _run_yolo(self, frame):
        return list(self._fake_detections)

    def _compute_reid(self, roi):
        # Return deterministic feature based on detection cx
        return [0.8, 0.1, 0.8, 0.1, 0.8, 0.1]

    def _compute_hsv_hist(self, roi):
        return [1.0 / 48] * 48

    def _extract_roi(self, frame, det):
        # Return a fake "frame" (no real cropping needed)
        return object()


class TestDollDetectorRegistration:
    def test_not_ready_initially(self):
        dd = FakeDollDetector()
        assert dd.is_ready() is False

    def test_ready_after_min_frames(self):
        dd = FakeDollDetector()
        dd.set_fake_detections([{'cx': 320, 'cy': 240, 'w': 80, 'h': 120,
                                  'confidence': 0.9}])
        for _ in range(5):
            dd.register(b'fake_frame')
        assert dd.is_ready() is True

    def test_not_ready_if_low_confidence(self):
        dd = FakeDollDetector()
        dd.set_fake_detections([{'cx': 320, 'cy': 240, 'w': 80, 'h': 120,
                                  'confidence': 0.1}])   # below MIN_CONFIDENCE
        for _ in range(10):
            dd.register(b'fake_frame')
        assert dd.is_ready() is False

    def test_reset_clears_template(self):
        dd = FakeDollDetector()
        dd.set_fake_detections([{'cx': 320, 'cy': 240, 'w': 80, 'h': 120,
                                  'confidence': 0.9}])
        for _ in range(5):
            dd.register(b'fake_frame')
        assert dd.is_ready() is True
        dd.reset()
        assert dd.is_ready() is False
        assert dd.get_latest() is None


class TestDollDetectorRunning:
    def _make_ready(self):
        dd = FakeDollDetector()
        dd.set_fake_detections([{'cx': 320, 'cy': 240, 'w': 80, 'h': 120,
                                  'confidence': 0.9}])
        for _ in range(5):
            dd.register(b'fake_frame')
        return dd

    def test_run_returns_none_when_not_ready(self):
        dd = FakeDollDetector()
        dd.set_fake_detections([{'cx': 320, 'cy': 240, 'w': 80, 'h': 120,
                                  'confidence': 0.9}])
        dd.run(b'fake_frame')
        assert dd.get_latest() is None

    def test_run_detects_when_similarity_high(self):
        dd = self._make_ready()
        dd.set_fake_detections([{'cx': 320, 'cy': 240, 'w': 80, 'h': 120,
                                  'confidence': 0.9}])
        dd.run(b'fake_frame')
        det = dd.get_latest()
        assert det is not None
        assert det.cx == 320.0

    def test_run_returns_none_when_no_detections(self):
        dd = self._make_ready()
        dd.set_fake_detections([])
        dd.run(b'fake_frame')
        assert dd.get_latest() is None


class TestMathHelpers:
    def test_cosine_similarity_same_vector(self):
        v = [1.0, 0.5, 0.3]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_cosine_similarity_orthogonal(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_histogram_correlation_same(self):
        h = [1.0 / 48] * 48
        score = _histogram_correlation(h, h)
        assert score > 0.9  # perfect correlation → near 1.0

    def test_histogram_correlation_zero_vector(self):
        h = [0.0] * 48
        score = _histogram_correlation(h, h)
        assert score == 0.0  # degenerate case

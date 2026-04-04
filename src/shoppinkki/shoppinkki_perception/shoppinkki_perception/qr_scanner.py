"""QRScanner — OpenCV-based QR code scanner with timeout.

Runs in a background thread while the IDLE LCD shows the registration QR.
When the customer scans the QR with their phone, the QR data (URL) is
passed to the on_scanned callback.  After 30 seconds of inactivity the
on_timeout callback fires.

QR content format:  http://<server>/session?robot=<robot_id>
The caller (main_node) handles the URL and forwards to control_service.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

QR_SCAN_TIMEOUT = 30.0   # seconds until on_timeout fires


class QRScanner:
    """QRScannerInterface implementation using OpenCV QRCodeDetector.

    Parameters
    ----------
    get_frame:
        Callable returning the latest camera frame (numpy BGR ndarray).
        Called ~5 Hz from the scanning thread.
    scan_interval:
        How often to poll for a QR code (seconds).
    """

    def __init__(
        self,
        get_frame: Optional[Callable] = None,
        scan_interval: float = 0.2,
    ) -> None:
        self._get_frame = get_frame
        self._scan_interval = scan_interval
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ── QRScannerInterface ────────────────────

    def start(
        self,
        on_scanned: Callable[[str], None],
        on_timeout: Callable[[], None],
    ) -> None:
        """Start the scanning thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._scan_loop,
            args=(on_scanned, on_timeout),
            daemon=True,
            name='qr-scanner',
        )
        self._thread.start()
        logger.info('QRScanner: started (timeout=%.0fs)', QR_SCAN_TIMEOUT)

    def stop(self) -> None:
        """Stop the scanning thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info('QRScanner: stopped')

    # ── Scanning loop ─────────────────────────

    def _scan_loop(
        self,
        on_scanned: Callable[[str], None],
        on_timeout: Callable[[], None],
    ) -> None:
        try:
            import cv2
            qr_decoder = cv2.QRCodeDetector()
        except ImportError:
            logger.warning('QRScanner: OpenCV not available; QR scanning disabled')
            return

        deadline = time.monotonic() + QR_SCAN_TIMEOUT

        while not self._stop_event.is_set():
            if time.monotonic() >= deadline:
                logger.info('QRScanner: timeout')
                on_timeout()
                return

            frame = self._get_latest_frame()
            if frame is None:
                time.sleep(self._scan_interval)
                continue

            try:
                data, pts, _ = qr_decoder.detectAndDecode(frame)
                if data:
                    logger.info('QRScanner: decoded QR → %s', data)
                    on_scanned(data)
                    return
            except Exception as e:
                logger.debug('QRScanner: decode error: %s', e)

            time.sleep(self._scan_interval)

    def _get_latest_frame(self):
        if self._get_frame is None:
            return None
        try:
            return self._get_frame()
        except Exception:
            return None

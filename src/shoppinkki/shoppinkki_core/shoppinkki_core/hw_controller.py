"""Hardware controller wrapper for LED, LCD, and buzzer.

Wraps ROS service calls. On non-ARM64 machines or before services are
available, each method silently logs and returns — so unit tests work
without a physical robot.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import rclpy.node

logger = logging.getLogger(__name__)

# LED colour presets  (R, G, B) — used with /set_led
LED_OFF = (0, 0, 0)
LED_GREEN = (0, 255, 0)       # TRACKING
LED_YELLOW = (255, 200, 0)    # GUIDING
LED_BLUE = (0, 100, 255)      # WAITING / SEARCHING
LED_PURPLE = (180, 0, 255)    # RETURNING
LED_RED_BLINK = (255, 0, 0)   # LOCKED / is_locked_return
LED_RED = (255, 0, 0)         # CHARGING (locked)
LED_WHITE = (255, 255, 255)   # IDLE

# LCD emotion presets  — used with /set_emotion
EMOTION_HELLO = 'hello'
EMOTION_HAPPY = 'happy'
EMOTION_BASIC = 'basic'
EMOTION_INTEREST = 'interest'
EMOTION_ANGRY = 'angry'
EMOTION_SAD = 'sad'
EMOTION_BORED = 'bored'


class HWController:
    """Wraps pinky_interfaces service calls.

    Parameters
    ----------
    node:
        rclpy Node that owns the service clients.
        Pass ``None`` in unit-test environments (all calls become no-ops).
    """

    def __init__(self, node: Optional['rclpy.node.Node'] = None) -> None:
        self._node = node
        self._led_client = None
        self._emotion_client = None
        self._lamp_client = None

        if node is not None:
            self._init_clients()

    def _init_clients(self) -> None:
        """Create ROS service clients (lazy — won't block if service is absent)."""
        try:
            from pinky_interfaces.srv import SetLed, SetBrightness
            from pinky_interfaces.srv import SetLamp
            from rclpy.node import Node

            self._led_client = self._node.create_client(SetLed, '/set_led')
            self._lamp_client = self._node.create_client(SetLamp, '/set_lamp')
            logger.info('HWController: service clients created')
        except Exception as e:
            logger.warning('HWController: could not create service clients: %s', e)

    # ── LED ───────────────────────────────────

    def set_led(self, r: int, g: int, b: int, blink: bool = False) -> None:
        """Set WS2812B LED strip colour."""
        logger.debug('set_led(%d, %d, %d, blink=%s)', r, g, b, blink)
        if self._led_client is None:
            return
        try:
            from pinky_interfaces.srv import SetLed
            req = SetLed.Request()
            req.r = r
            req.g = g
            req.b = b
            self._led_client.call_async(req)
        except Exception as e:
            logger.warning('set_led failed: %s', e)

    def set_led_for_state(self, state: str, is_locked_return: bool = False) -> None:
        """Set LED colour based on SM state.

        is_locked_return overrides all colours with red blink.
        """
        if is_locked_return:
            self.set_led(*LED_RED_BLINK, blink=True)
            return

        mapping = {
            'CHARGING': LED_RED,
            'IDLE': LED_WHITE,
            'TRACKING': LED_GREEN,
            'TRACKING_CHECKOUT': LED_GREEN,
            'GUIDING': LED_YELLOW,
            'SEARCHING': LED_BLUE,
            'WAITING': LED_BLUE,
            'LOCKED': LED_RED_BLINK,
            'RETURNING': LED_PURPLE,
            'HALTED': LED_RED_BLINK,
        }
        colour = mapping.get(state, LED_OFF)
        blink = state in ('LOCKED', 'HALTED')
        self.set_led(*colour, blink=blink)

    # ── LCD / Emotion ─────────────────────────

    def set_emotion(self, emotion: str) -> None:
        """Display emotion GIF on the LCD."""
        logger.debug('set_emotion(%s)', emotion)
        if self._node is None:
            return
        try:
            from pinky_interfaces.srv import SetEmotion
            from rclpy.node import Node
            # SetEmotion is defined in pinky_interfaces; call async
            client = self._node.create_client(SetEmotion, '/set_emotion')
            req = SetEmotion.Request()
            req.emotion = emotion
            client.call_async(req)
        except Exception as e:
            logger.warning('set_emotion failed: %s', e)

    def set_lcd_text(self, text: str) -> None:
        """Display plain text on the LCD (non-IDLE states)."""
        logger.info('LCD: %s', text)
        # LCD text display is handled by the emotion node's text mode
        # For now, log only; full impl requires custom LCD service

    def set_lcd_for_state(self, state: str) -> None:
        """Update LCD content based on SM state."""
        text_map = {
            'CHARGING': '충전 중',
            'IDLE': '',             # QR code shown by separate QR node
            'TRACKING': '추종 중',
            'TRACKING_CHECKOUT': '결제 완료 — 추종 중',
            'GUIDING': '목적지 안내 중',
            'SEARCHING': '주인 탐색 중',
            'WAITING': '대기 중',
            'LOCKED': '충전소 이동 중',
            'RETURNING': '충전소 이동 중',
            'HALTED': '배터리 부족',
        }
        text = text_map.get(state, state)
        if state == 'IDLE':
            # QR display is handled externally
            return
        self.set_lcd_text(text)

    # ── Buzzer ────────────────────────────────

    def buzz(self, pattern: str = 'short') -> None:
        """Trigger buzzer pattern ('short' | 'long' | 'alert')."""
        logger.debug('buzz(%s)', pattern)
        # Buzzer GPIO is managed by a separate node on Pi; log-only for now

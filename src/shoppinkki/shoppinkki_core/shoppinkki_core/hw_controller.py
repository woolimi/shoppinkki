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

    def __init__(self, node: Optional['rclpy.node.Node'] = None,
                 robot_id: str = '54') -> None:
        self._node = node
        self._robot_id = str(robot_id)
        self._led_client = None
        self._emotion_client = None
        self._lamp_client = None
        self._lcd = None          # pinky_lcd.LCD 인스턴스 (Pi 전용, 지연 초기화)

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

    # ── LCD 텍스트 / QR 렌더링 ─────────────────

    # IDLE 상태에서 표시할 고객 웹 URL
    # CUSTOMER_WEB_HOST 환경변수로 노트북 IP를 주입받음 (run_robot.sh에서 설정)
    @staticmethod
    def _get_customer_web_url() -> str:
        import os
        host = os.environ.get('CUSTOMER_WEB_HOST', '127.0.0.1')
        return f'http://{host}:8501'

    _TEXT_LINES = {
        'CHARGING':  ['충전 중'],
        'SEARCHING': ['주인', '탐색 중'],
        'WAITING':   ['잠깐', '기다려요'],
        'GUIDING':   ['목적지', '안내 중'],
        'RETURNING': ['충전소로', '이동 중'],
        'LOCKED':    ['긴급', '복귀 중'],
        'HALTED':    ['배터리', '부족'],
    }
    _BG_COLORS = {
        'CHARGING':  (20,  20,  80),
        'SEARCHING': (80,  40,   0),
        'WAITING':   (60,   0,  60),
        'GUIDING':   (0,   60,  60),
        'RETURNING': (60,  20,  20),
        'LOCKED':    (100,  0,   0),
        'HALTED':    (100,  0,   0),
    }
    _FONT_PATHS = [
        '/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf',
        '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    ]

    def _get_lcd(self):
        """pinky_lcd.LCD 인스턴스를 반환. Pi가 아니거나 초기화 실패 시 None."""
        if self._lcd is not None:
            return self._lcd
        try:
            from pinky_emotion.pinky_lcd import LCD as PinkyLCD
            self._lcd = PinkyLCD()
            return self._lcd
        except Exception as e:
            logger.debug('pinky_lcd 초기화 실패 (Non-Pi 정상): %s', e)
            return None

    def _get_font(self, size: int = 40):
        """한글 지원 폰트 로드. 없으면 기본 폰트 반환."""
        try:
            from PIL import ImageFont
            for fp in self._FONT_PATHS:
                try:
                    return ImageFont.truetype(fp, size)
                except Exception:
                    pass
            return ImageFont.load_default()
        except ImportError:
            return None

    def _lcd_show(self, target_portrait):
        """PIL 이미지를 LCD에 표시.

        pinky_lcd.img_show() 내부에서 FLIP_LEFT_RIGHT → ROTATE_270 이 적용되므로
        그 역변환을 먼저 적용한다:
          source = ROTATE_90_CCW( FLIP_LR(target) )
        즉 target 을 좌우 반전한 뒤 90° 반시계 회전하면 img_show 이후 원본이 복원된다.
        """
        try:
            from PIL import Image
        except ImportError:
            return
        # 역변환: ROTATE_90 (CCW) → FLIP_LR  (LCD가 FLIP_LR→ROTATE_270 을 적용하므로)
        source = target_portrait.transpose(Image.ROTATE_90).transpose(Image.FLIP_LEFT_RIGHT)
        lcd = self._get_lcd()
        if lcd is not None:
            try:
                lcd.img_show(source)
            except Exception as e:
                logger.warning('LCD img_show 실패: %s', e)

    def display_state_text(self, state: str) -> None:
        """상태 텍스트를 PIL로 LCD에 렌더링."""
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            logger.debug('PIL 없음 — LCD 텍스트 스킵')
            return

        lines = self._TEXT_LINES.get(state, [state])
        bg    = self._BG_COLORS.get(state, (30, 30, 30))
        font  = self._get_font(40)
        if font is None:
            return

        target = Image.new('RGB', (240, 320), color=bg)
        draw   = ImageDraw.Draw(target)

        line_height = 52
        total_h     = len(lines) * line_height
        start_y     = (320 - total_h) // 2

        for i, line in enumerate(lines):
            bbox   = draw.textbbox((0, 0), line, font=font)
            text_w = bbox[2] - bbox[0]
            x = (240 - text_w) // 2
            y = start_y + i * line_height
            draw.text((x, y), line, fill=(255, 255, 255), font=font)

        self._lcd_show(target)

    def display_qr(self, url: str, label: str = '') -> None:
        """URL QR 코드를 LCD에 표시. label이 있으면 하단에 작은 텍스트로 표시."""
        try:
            import qrcode
            from PIL import Image, ImageDraw
        except ImportError:
            logger.debug('qrcode/PIL 없음 — QR 스킵')
            return

        qr = qrcode.QRCode(box_size=4, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color='black', back_color='white').convert('RGB')

        # 240×320 portrait 배경에 QR 중앙 배치
        target = Image.new('RGB', (240, 320), color=(255, 255, 255))
        qw, qh = qr_img.size
        # 최대 220×260 에 맞게 비율 축소
        max_w, max_h = 220, 260
        scale = min(max_w / qw, max_h / qh)
        qw2 = int(qw * scale)
        qh2 = int(qh * scale)
        qr_img = qr_img.resize((qw2, qh2), Image.LANCZOS)

        x_off = (240 - qw2) // 2
        if label:
            y_off = (320 - qh2) // 2 - 15
        else:
            y_off = (320 - qh2) // 2
        target.paste(qr_img, (x_off, y_off))

        if label:
            draw = ImageDraw.Draw(target)
            font = self._get_font(18)
            if font:
                bbox   = draw.textbbox((0, 0), label, font=font)
                text_w = bbox[2] - bbox[0]
                lx = (240 - text_w) // 2
                ly = y_off + qh2 + 6
                draw.text((lx, ly), label, fill=(0, 0, 0), font=font)

        self._lcd_show(target)

    def set_lcd_for_state(self, state: str) -> None:
        """SM 상태에 따라 LCD 내용 갱신.

        TRACKING / TRACKING_CHECKOUT: 카메라 피드가 표시하므로 건드리지 않음.
        IDLE: 고객 웹 QR 코드 표시.
        나머지: 한글 상태 텍스트 표시.
        """
        if state in ('TRACKING', 'TRACKING_CHECKOUT'):
            return
        if state == 'IDLE':
            url   = f'{self._get_customer_web_url()}/?robot_id={self._robot_id}'
            label = f'{self._robot_id}번 카트'
            logger.info('LCD: QR (%s)', url)
            self.display_qr(url, label=label)
            return
        logger.info('LCD 상태 표시: %s', state)
        self.display_state_text(state)

    # ── Buzzer ────────────────────────────────

    def buzz(self, pattern: str = 'short') -> None:
        """Trigger buzzer pattern ('short' | 'long' | 'alert')."""
        logger.debug('buzz(%s)', pattern)
        # Buzzer GPIO is managed by a separate node on Pi; log-only for now

    # ── 카메라 피드 표시 ──────────────────────

    def display_frame(self, frame) -> None:
        """카메라 프레임을 LCD에 표시.

        BGR numpy 배열(OpenCV)을 받아 PIL로 변환 후 _lcd_show()로 LCD에 출력.
        DISPLAY 환경 변수가 설정된 경우 cv2 디버그 창도 함께 표시.
        """
        try:
            import cv2
            from PIL import Image

            # BGR → RGB 변환 후 PIL 이미지로 변환
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb).resize((320, 240), Image.LANCZOS)
            self._lcd_show(pil_img)

            import os
            if os.environ.get('DISPLAY'):
                small = cv2.resize(frame, (320, 240))
                cv2.imshow('ShopPinkki Camera', small)
                cv2.waitKey(1)
        except Exception:
            pass

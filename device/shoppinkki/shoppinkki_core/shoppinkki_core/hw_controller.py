"""Hardware controller wrapper for LED, LCD, and buzzer.

Wraps ROS service calls. On non-ARM64 machines or before services are
available, each method silently logs and returns — so unit tests work
without a physical robot.
"""

from __future__ import annotations

import logging
import time
import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import rclpy.node

from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2
import numpy as np

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
        self._lcd = None
        self._lcd_pub = None
        self._bridge = CvBridge()
        self._registration_active_ref = None # Reference to main_node._registration_active
        self._reg_mask = None
        self._reg_mask_inv = None
        self._lcd_lock = threading.Lock()

        if node is not None:
            self._init_clients()
            self._init_publishers()
            self._init_lcd()

    def _init_lcd(self) -> None:
        """Initialize the LCD hardware directly."""
        self._lcd = self._get_lcd()
        if self._lcd:
            logger.info('HWController: Direct LCD drive enabled')

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

    def _init_publishers(self) -> None:
        """Create ROS 2 publishers (Optional since we now drive LCD directly)."""
        try:
            self._lcd_pub = self._node.create_publisher(Image, '/pinky/lcd_image', 10)
        except Exception:
            pass

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
        return f"http://{host}:8501"

    # LCD 해상도 — 320x240 Landscape (하드웨어 240x320 가로 거치)
    LCD_W, LCD_H = 320, 240

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

    def _lcd_show(self, image, is_registration=False, mirror=False):
        """LCD에 이미지를 표시한다. (Nuclear Fix: Force-cast to kill all tuple bugs)"""
        if self._lcd is None:
            return

        try:
            # 1. Normalize color order for LCD path.
            # - PIL images are RGB already.
            # - OpenCV/NumPy camera frames are BGR, so convert once to RGB.
            if hasattr(image, "convert"):  # PIL Image
                image = np.array(image.convert('RGB'))
            elif isinstance(image, np.ndarray):
                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            
            # 2. Mirroring (Selfie view)
            if mirror:
                image = cv2.flip(image, 1)

            # 3. Nuclear Fix: Ensure we have a clean, standard NumPy array
            img_array = np.ascontiguousarray(image, dtype=np.uint8)

            # 3. Registration UI: blur outside ellipse
            if is_registration:
                img_array = self._apply_registration_ui(img_array)

            # 4. Final Show
            with self._lcd_lock:
                self._lcd.img_show(img_array)
            
        except Exception as e:
            # PATH REVEALER: Find out exactly which file is causing the crash
            import traceback
            logger.error("!!! NUCLEAR SHIELD TRACEBACK !!!")
            logger.error(traceback.format_exc())
            try:
                import pinky_emotion.pinky_lcd as lcd
                logger.error(f"IMPOSTER PATH: {lcd.__file__}")
            except Exception:
                pass
            logger.error(f"NUCLEAR SHIELD: LCD show blocked a crash: {e}")

    def bind_registration_active(self, registration_active_ref) -> None:
        """Bind a callable that returns current registration-active flag."""
        self._registration_active_ref = registration_active_ref

    def _apply_registration_ui(self, image):
        """인형 등록 시 세로로 긴 타원형만 선명하게, 주변은 블러 처리된 UI (Ultra-High Speed Caching)."""
        try:
            h, w = image.shape[:2]
            
            # Pre-cache the mask once for the session (Saves 5-10ms per frame)
            if self._reg_mask is None or self._reg_mask.shape[:2] != (h, w):
                mask = np.zeros((h, w), dtype=np.uint8)
                center = (w // 2, h // 2)
                # Bigger guide ellipse for easier registration alignment
                axes = (140, 210)
                cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1)
                self._reg_mask = mask
                self._reg_mask_inv = cv2.bitwise_not(mask)

            # High-Speed Bitwise Blending (Zero Lagrangian lag)
            blurred = cv2.GaussianBlur(image, (5, 5), 0)
            if self._reg_mask is None or self._reg_mask.shape[:2] != image.shape[:2]: return image
            res_fg = cv2.bitwise_and(image, image, mask=self._reg_mask)
            res_bg = cv2.bitwise_and(blurred, blurred, mask=self._reg_mask_inv)
            result = cv2.add(res_fg, res_bg)
            
            # 4. Final Guide Ring
            cv2.ellipse(result, (w // 2, h // 2), (140, 210), 0, 0, 360, (255, 255, 255), 1, cv2.LINE_AA)
            
            return result
        except Exception as e:
            logger.warning(f"Registration UI failed: {e}")
            return image
        
        # Fallback: keep publishing for the monitor/debugging
        if self._lcd_pub is not None:
            try:
                cv_img = np.array(target_landscape)
                bgr_img = cv2.cvtColor(cv_img, cv2.COLOR_RGB2BGR)
                msg = self._bridge.cv2_to_imgmsg(bgr_img, encoding='bgr8')
                self._lcd_pub.publish(msg)
            except Exception: pass

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

        target = Image.new('RGB', (self.LCD_W, self.LCD_H), color=bg)
        draw   = ImageDraw.Draw(target)

        line_height = 52
        total_h     = len(lines) * line_height
        start_y     = (self.LCD_H - total_h) // 2

        for i, line in enumerate(lines):
            bbox   = draw.textbbox((0, 0), line, font=font)
            text_w = bbox[2] - bbox[0]
            x = (self.LCD_W - text_w) // 2
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

        # 320x240 Landscape 배경에 QR 중앙 배치
        target = Image.new('RGB', (self.LCD_W, self.LCD_H), color=(255, 255, 255))
        qw, qh = qr_img.size
        # QR 코드 크기 최적화 (텍스트 공간 확보를 위해 180x180으로 조정)
        max_w, max_h = 180, 180
        scale = min(max_w / qw, max_h / qh)
        qw2 = int(qw * scale)
        qh2 = int(qh * scale)
        qr_img = qr_img.resize((qw2, qh2), Image.Resampling.LANCZOS)

        x_off = (self.LCD_W - qw2) // 2
        if label:
            # 텍스트가 있을 경우 QR을 위로 더 올림
            y_off = (self.LCD_H - qh2) // 2 - 20
        else:
            y_off = (self.LCD_H - qh2) // 2
        target.paste(qr_img, (x_off, y_off))

        if label:
            draw = ImageDraw.Draw(target)
            font = self._get_font(22)  # 가독성을 위해 폰트 크기 약간 키움
            if font:
                bbox   = draw.textbbox((0, 0), label, font=font)
                text_w = bbox[2] - bbox[0]
                lx = (self.LCD_W - text_w) // 2
                # QR 직후에 텍스트 배치 (간격 5px)
                ly = y_off + qh2 + 5
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
            if self._lcd:
                with self._lcd_lock:
                    self._lcd.clear(color=(255, 255, 255))
            # Skip QR if registration just started to avoid flicker
            if self._registration_active_ref and self._registration_active_ref():
                return
                
            url   = f'{self._get_customer_web_url()}/?robot_id={self._robot_id}'
            logger.info('LCD: READY (Check Dashboard for QR %s)', url)
            self.display_qr(url, label=f'{self._robot_id}번 카트')
            return
        
        # If searching, only draw text if registration is NOT active
        if state == 'SEARCHING' and self._registration_active_ref and self._registration_active_ref():
            return

        logger.info('LCD 상태 표시: %s', state)
        self.display_state_text(state)

    # ── Buzzer ────────────────────────────────

    def buzz(self, pattern: str = 'short') -> None:
        """Trigger buzzer pattern ('short' | 'long' | 'alert')."""
        logger.debug('buzz(%s)', pattern)
        # Buzzer GPIO is managed by a separate node on Pi; log-only for now

    # ── 카메라 피드 표시 ──────────────────────

    def draw_detection(self, frame, detection) -> None:
        """프레임에 BBOX 및 정보를 직접 그린다 (OpenCV)."""
        if frame is None or detection is None or detection.bbox is None:
            return

        try:
            import cv2
            h, w = frame.shape[:2]
            
            # 좌표 클리핑 (Safety Clipping) — 이미지 경계를 벗어나지 않도록 보정
            raw_x1, raw_y1, raw_x2, raw_y2 = map(int, detection.bbox)
            x1 = max(0, min(w - 1, raw_x1))
            y1 = max(0, min(h - 1, raw_y1))
            x2 = max(0, min(w - 1, raw_x2))
            y2 = max(0, min(h - 1, raw_y2))
            
            conf = detection.confidence
            is_owner = detection.class_name != 'yolo_debug'
            
            # 박스 그리기 (Owner: Gold/Yellow, Debug: Vibrant Green)
            color = (0, 215, 255) if is_owner else (0, 255, 0)
            thickness = 3 if is_owner else 2
            if x2 > x1 and y2 > y1:
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

            # 텍스트 배경
            label = "OWNER" if is_owner else "doll"
            label = f"{label} {conf:.2f}"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.6 if is_owner else 0.5
            font_thickness = 2 if is_owner else 1
            (tw, th), baseline = cv2.getTextSize(label, font, font_scale, font_thickness)
            cv2.rectangle(frame, (x1, y1 - th - 5), (x1 + tw, y1), color, -1)
            
            # 텍스트 그리기 (Black)
            cv2.putText(frame, label, (x1, y1 - 5), font, font_scale, (0, 0, 0), font_thickness)
        except Exception as e:
            logger.debug('draw_detection 실패: %s', e)

    def draw_status(self, frame, connected: bool, det_count: int) -> None:
        """상단에 AI 서버 연결 상태 및 감지 개수를 표시한다."""
        if frame is None: return
        import cv2
        status_text = f"AI: {'CONNECTED' if connected else 'DISCONNECTED'} ({det_count})"
        color = (0, 255, 0) if connected else (0, 0, 255)
        cv2.putText(frame, status_text, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,0), 2) # Shadow
        cv2.putText(frame, status_text, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    def display_frame(self, frame, connected: bool = False, det_count: int = 0, is_registration: bool = False, mirror: bool = False) -> None:
        """카메라 프레임을 LCD에 표시 (UI 오버레이 포함)"""
        try:
            # 1. 상태 오버레이 (Connected/Disconnected)
            self.draw_status(frame, connected, det_count)

            # 2. LCD 표시 (Nuclear Shield & Blur UI 적용)
            self._lcd_show(frame, is_registration=is_registration, mirror=mirror)

            # Debug UI Removed
        except Exception as e:
            logger.debug('display_frame 실패: %s', e)

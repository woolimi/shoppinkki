import spidev, time, numpy as np, RPi.GPIO as GPIO
from PIL import Image
RST_PIN, DC_PIN, BL_PIN = 27, 25, 18
class LCD():
    def __init__(self):
        self.w, self.h = 320, 240
        # Hardware workaround:
        # Some panels stay in inverted-display mode regardless of INVOFF.
        # Keep this compensation enabled so camera/QR colors look normal.
        self._compensate_panel_inversion = True
        GPIO.setmode(GPIO.BCM); GPIO.setwarnings(False)
        GPIO.setup(RST_PIN, GPIO.OUT); GPIO.setup(DC_PIN, GPIO.OUT); GPIO.setup(BL_PIN, GPIO.OUT)
        self.bl = GPIO.PWM(BL_PIN, 1000); self.bl.start(100)
        self.spi = spidev.SpiDev(); self.spi.open(0, 0); self.spi.max_speed_hz = 40000000; self.spi.mode = 0b00
        print(f"LCD ACTIVE: {self.w}x{self.h}")
        self.lcd_init()
    def _write_cmd(self, cmd):
        GPIO.output(DC_PIN, 0); self.spi.writebytes([int(cmd)])
    def _write_data(self, val):
        GPIO.output(DC_PIN, 1)
        if hasattr(val, 'item'): val = val.item()
        if isinstance(val, (list, tuple, np.ndarray)): val = int(val[0])
        self.spi.writebytes([int(val)])
    def _write_data_buffer(self, buf):
        GPIO.output(DC_PIN, 1)
        if not isinstance(buf, (bytes, bytearray)): buf = bytearray(buf)
        self.spi.writebytes2(buf)
    def reset(self):
        GPIO.output(RST_PIN, 1); time.sleep(0.01); GPIO.output(RST_PIN, 0); time.sleep(0.01); GPIO.output(RST_PIN, 1); time.sleep(0.01)
    def lcd_init(self):
        # Standard RGB pipeline + explicit normal display mode.
        # Some panels boot with inversion enabled, which looks like a negative filter.
        self.reset()
        self._write_cmd(0x11)  # Sleep out
        time.sleep(0.12)
        self._write_cmd(0x3A); self._write_data(0x55)  # 16-bit RGB565
        self._write_cmd(0x36); self._write_data(0x60)  # MADCTL RGB
        self._write_cmd(0x20)  # INVOFF: disable display inversion explicitly
        self._write_cmd(0x29)  # Display ON
    def _set_windows(self, x1, y1, x2, y2):
        self._write_cmd(0x2A); self._write_data(x1 >> 8); self._write_data(x1 & 0xff); self._write_data((x2-1) >> 8); self._write_data((x2-1) & 0xff)
        self._write_cmd(0x2B); self._write_data(y1 >> 8); self._write_data(y1 & 0xff); self._write_data((y2-1) >> 8); self._write_data((y2-1) & 0xff); self._write_cmd(0x2C)
    def img_show(self, img):
        if isinstance(img, np.ndarray): # EXPLICIT NumPy handling
            if img.shape[0] != self.h or img.shape[1] != self.w:
                import cv2
                img = cv2.resize(img, (self.w, self.h), interpolation=cv2.INTER_NEAREST)
            image = img
        else: # Handle PIL or other types
            if img.size != (self.w, self.h): 
                img = img.resize((self.w, self.h), Image.NEAREST)
            image = np.asarray(img.convert('RGB'))
        if self._compensate_panel_inversion:
            image = 255 - image
        image = image.astype(np.uint16)
        r, g, b = (image[:,:,0] & 0xF8) << 8, (image[:,:,1] & 0xFC) << 3, (image[:,:,2] & 0xF8) >> 3
        rgb565 = r | g | b
        data = np.stack(((rgb565 >> 8).astype(np.uint8), (rgb565 & 0xFF).astype(np.uint8)), axis=2).reshape(-1)
        self._set_windows(0, 0, self.w, self.h); self._write_data_buffer(data)
    def clear(self, color=0x0000):
        if isinstance(color, (list, tuple, np.ndarray)) and len(color) >= 3:
            color = ((int(color[0]) & 0xF8) << 8) | ((int(color[1]) & 0xFC) << 3) | ((int(color[2]) & 0xF8) >> 3)
        if self._compensate_panel_inversion:
            color = int(color) ^ 0xFFFF
        h, l = int(color) >> 8, int(color) & 0xFF
        buf = bytearray([h, l] * 4096)
        self._set_windows(0, 0, self.w, self.h)
        for _ in range(0, self.w * self.h * 2, len(buf)): self._write_data_buffer(buf)
    def set_backlight(self, val): self.bl.ChangeDutyCycle(max(0, min(100, val)))
    def close(self): self.spi.close(); self.bl.stop(); GPIO.cleanup([RST_PIN, DC_PIN, BL_PIN])

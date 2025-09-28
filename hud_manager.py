import time
import cv2
import numpy as np

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

class HUDManager:
    """
    HUDManager показує тимчасові повідомлення поверх відео.
    Повідомлення з’являється внизу екрана на чорній напівпрозорій смузі.
    """

    def __init__(self, timeout=2.5, font=None):
        self.message = None
        self.message_time = 0
        self.timeout = timeout
        self.font = font

    def show_message(self, text):
        """Показати повідомлення (буде видиме кілька секунд)."""
        self.message = text
        self.message_time = time.time()

    def _draw_text_pil(self, frame, text, pos, color=(0, 255, 0)):
        """
        Малює текст на кадрі OpenCV за допомогою Pillow.
        Підтримує UTF-8 символи.
        """
        if not PIL_AVAILABLE or not self.font:
            # Fallback до стандартного cv2.putText, якщо Pillow недоступний
            cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
            return frame

        img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(img_pil)
        draw.text(pos, text, font=self.font, fill=color)
        return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

    def _get_text_size_pil(self, text):
        """
        Отримує розмір тексту за допомогою Pillow.
        """
        if not PIL_AVAILABLE or not self.font:
            # Fallback для cv2
            (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)
            return w, h

        try: # Pillow >= 10.0.0
            left, top, right, bottom = self.font.getbbox(text)
            return right - left, bottom - top
        except AttributeError: # Старі версії Pillow
            return self.font.getsize(text)

    def draw(self, frame):
        """Накладає повідомлення на кадр, якщо воно ще актуальне."""
        if self.message and (time.time() - self.message_time < self.timeout):
            overlay = frame.copy()
            h, w = frame.shape[:2]

            # висота смуги
            rect_h = 60
            y1, y2 = h - rect_h, h

            # Відступ зліва, щоб не перекривати кнопки
            left_offset = 170  # Ширина колонки кнопок (150) + невеликий відступ

            cv2.rectangle(
                overlay,
                (left_offset, y1),
                (w, y2),
                (0, 0, 0),
                -1
            )
            frame = cv2.addWeighted(overlay, 0.6, frame, 0.4, 0)

            # --- Центрування тексту ---
            text_w, text_h = self._get_text_size_pil(self.message)

            # Центруємо текст у межах нової, звуженої області
            text_x = left_offset + (w - left_offset - text_w) // 2
            text_y = y1 + (rect_h - text_h) // 2

            frame = self._draw_text_pil(
                frame, 
                self.message, 
                (text_x, text_y)
            )
        return frame

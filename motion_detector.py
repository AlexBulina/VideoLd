import cv2

class MotionDetector:
    """
    Клас для детектування руху на послідовності кадрів за допомогою
    алгоритму віднімання фону.
    """
    def __init__(self, min_contour_area=500, scale_factor=0.5, var_threshold=70):
        """
        Ініціалізація детектора руху.

        :param min_contour_area: Мінімальна площа контуру, яка вважається рухом.
                                 Це допомагає відфільтрувати дрібний шум.
        :param scale_factor: Коефіцієнт масштабування кадру для аналізу (0.5 = 50%).
                             Зменшення кадру значно прискорює детекцію.
        :param var_threshold: Поріг для віднімача фону. Більші значення роблять детектор менш чутливим.
        """
        # Створюємо віднімач фону. MOG2 - це ефективний і поширений алгоритм.
        # history: кількість кадрів для побудови моделі фону.
        # varThreshold: поріг для визначення, чи є піксель частиною фону.
        self.var_threshold = var_threshold
        self.backSub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=self.var_threshold, detectShadows=False)
        self.min_contour_area = min_contour_area
        self.scale_factor = scale_factor

    def detect(self, frame):
        """
        Виявляє рух на поточному кадрі та малює прямокутники навколо рухомих об'єктів.

        :param frame: Вхідний кадр для аналізу.
        :return: Кадр з намальованими прямокутниками навколо виявлених об'єктів.
        """
        # 1. Зменшуємо кадр для прискорення обробки.
        height, width = frame.shape[:2]
        resized_frame = cv2.resize(
            frame, 
            (int(width * self.scale_factor), int(height * self.scale_factor)), 
            interpolation=cv2.INTER_AREA
        )

        # 2. (Новий крок) Застосовуємо розмиття для зменшення шуму і підвищення продуктивності.
        # Це допомагає віднімачу фону генерувати менше помилкових контурів.
        blurred_frame = cv2.GaussianBlur(resized_frame, (5, 5), 0)

        # 3. Застосовуємо віднімач фону, щоб отримати "маску" руху.
        # Маска буде білою там, де є рух, і чорною, де його немає.
        fgMask = self.backSub.apply(blurred_frame)

        # 4. Знаходимо контури на масці руху.
        # Контури - це безперервні криві, що окреслюють об'єкти.
        contours, _ = cv2.findContours(fgMask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # 4. Ітеруємо по знайдених контурах.
        for contour in contours:
            # 5. Якщо площа контуру занадто мала, ігноруємо його (це, ймовірно, шум).
            if cv2.contourArea(contour) < self.min_contour_area:
                continue

            # 6. Отримуємо координати обмежуючого прямокутника на зменшеному кадрі.
            (x, y, w, h) = cv2.boundingRect(contour)
            # 7. Масштабуємо координати назад до розміру оригінального кадру.
            x, y, w, h = int(x / self.scale_factor), int(y / self.scale_factor), int(w / self.scale_factor), int(h / self.scale_factor)
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 255), 2)

        return frame

    def reset(self):
        """Скидає стан віднімача фону."""
        self.backSub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=self.var_threshold, detectShadows=False)
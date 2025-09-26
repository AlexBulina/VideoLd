import av
import cv2
import time

class HLSVideo:
    def __init__(self, url, hud=None, fps=30, width=1024, height=600, reconnect_timeout=2.0):
        """
        url: HLS URL
        hud: об'єкт HUDManager для показу повідомлень
        fps: частота кадрів
        width, height: розмір кадру
        reconnect_timeout: час у секундах для перепідключення
        """
        self.url = url
        self.hud = hud
        self.fps = fps
        self.frame_time = 1.0 / fps
        self.width = width
        self.height = height
        self.reconnect_timeout = reconnect_timeout

        self.container = None
        self.stream = None
        self.frame_iter = None
        self.last_time = time.time()

        self._open_stream()

    def _open_stream(self):
        try:
            self.container = av.open(self.url, options={"timeout": str(int(self.reconnect_timeout * 1e6))})
            self.stream = self.container.streams.video[0]
            self.frame_iter = self.container.decode(video=0)
        except av.AVError:
            self.container = None
            self.stream = None
            self.frame_iter = None
            if self.hud:
                self.hud.trigger("crosshair_warning", "Stream error", "no active video stream", duration=3)

    def read(self):
        """
        Повертає (ret, frame)
        ret = False якщо кадр не отримано
        """
        if not self.isOpened():
            self._open_stream()
            return False, None

        try:
            # чекати інтервал FPS
            elapsed = time.time() - self.last_time
            if elapsed < self.frame_time:
                time.sleep(self.frame_time - elapsed)

            frame = next(self.frame_iter)
            self.last_time = time.time()

            img = frame.to_ndarray(format="bgr24")
            img = cv2.resize(img, (self.width, self.height))
            return True, img

        except (StopIteration, av.AVError):
            # Потік завис/закінчився → перепідключення
            self.release()
            time.sleep(0.1)
            self._open_stream()
            return False, None

    def release(self):
        if self.container:
            self.container.close()
            self.container = None
            self.stream = None
            self.frame_iter = None

    def isOpened(self):
        return self.container is not None

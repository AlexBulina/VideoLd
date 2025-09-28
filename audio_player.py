import pygame
import os
import os

class AudioPlayer:
    def __init__(self, audio_file):
        """
        Ініціалізує аудіоплеєр з вказаним аудіофайлом.
        """
        try:
            # Force alsa driver, and hdmi output (перевірте правильність hw:X,0)
            os.environ['SDL_AUDIODRIVER'] = 'alsa'
            os.environ['SDL_AUDIO_DEVICE'] = 'hw:0,0'  # Try HDMI 0 first, change if needed
            pygame.mixer.init()
        except pygame.error as e:
            print(f"Помилка ініціалізації Pygame mixer: {e}")
            raise  # Re-raise the exception to prevent further execution

        self.audio_file = audio_file
        if not os.path.exists(self.audio_file):
            raise FileNotFoundError(f"Аудіофайл не знайдено: {self.audio_file}")
        try:
            pygame.mixer.music.load(self.audio_file)
        except pygame.error as e:
            print(f"Помилка завантаження аудіофайлу: {e}")
            raise

    def play(self):
        """
        Відтворює аудіофайл.
        """
        pygame.mixer.music.play()
    def stop(self):
        pygame.mixer.music.stop()
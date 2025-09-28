#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import cv2
import numpy as np
import time
import math
import os
import json
import sys
from audio_player import AudioPlayer
from datetime import datetime
from hud_manager import HUDManager
from motion_detector import MotionDetector

# ---------------------------
# --- Заглушки / безпечні імпорти ---
# ---------------------------
# Якщо у тебе є реальні модулі ldtest, hud_manager, hls_player, wifi_hotspot — вони будуть імпортовані.
# Якщо ні — використовуються прості заглушки, щоб код можна було запустити.
try:
    from PIL import ImageFont, ImageDraw, Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️  Pillow не встановлено. Українські літери в HUD не будуть відображатись.")

try:
    from ldtest import LRF
except Exception:
    class LRF:
        SINGLE = 0
        def __init__(self, port=None, enable_pin=None, mode=None):
            self._on = False
        def power_on(self):
            self._on = True
        def power_off(self):
            self._on = False
        def get_single_measurement(self):
            # заглушка: випадкове значення
            return 123.4

try:
    from wifi_hotspot import WifiHotspotServer
except Exception:
    class WifiHotspotServer:
        def __init__(self, ssid="Pi", password=None, folder="download", port=8000):
            print("WifiHotspotServer: заглушка ініціалізована")
        def start_all(self):
            print("WifiHotspotServer: start_all (заглушка)")

# Спроба імпорту HLSVideo (повинен надавати інтерфейс схожий на VideoCapture)
HLS_AVAILABLE = True
try:
    from hls_player import HLSVideo
except Exception:
    HLS_AVAILABLE = False
    class HLSVideo:
        def __init__(self, url, fps=30, width=1024, height=600):
            print("HLSVideo: заглушка, використовується cv2.VideoCapture")
            # спробуємо використовувати OpenCV для простих HTTP MJPEG/RTSP/файлів
            self.cap = cv2.VideoCapture(url)
            self._fps = fps
            self._width = width
            self._height = height
        def isOpened(self):
            return self.cap.isOpened()
        def read(self):
            return self.cap.read()
        def release(self):
            return self.cap.release()
        def get(self, prop):
            return self.cap.get(prop)
        def set(self, prop, val):
            return self.cap.set(prop, val)

# ---------------------------
# --- Конфіг та константи ---
# ---------------------------
FRAME_W, FRAME_H = 1024, 600
ZOOM_STEP = 0.06
ZOOM_MIN, ZOOM_MAX = 1.0, 5.0
CONTINUOUS_AUTO_OFF_MINUTES = 2
RECORD_DIR = "record"
MENU_FILES_PER_PAGE = 15
FPS = 30.0

STREAMS_JSON = "hls_streams.json"

# Якщо немає streams.json — створимо дефолтний
DEFAULT_STREAMS = [
  {
    "name": "Norvegian cam 1",
    "url": "http://109.247.15.178:6001/mjpg/video.mjpg"
  },
  {
    "name": "beach",
    "url": "http://85.196.146.82:3337/mjpg/video.mjpg"}
    ,
  
   { "name": "boats club",
    "url": "http://213.236.250.78/mjpg/video.mjpg"
    },
    {
      "name": "park",
      "url": "http://192.171.163.3/?id=3324&imagePath=/mjpg/video.mjpg&size=1"
      }

]
def ensure_streams_file(filename=STREAMS_JSON):
    """
    Перевіряє наявність файлу `hls_streams.json` і створює його
    зі значеннями за замовчуванням, якщо файл відсутній.
    """
    if not os.path.exists(filename):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_STREAMS, f, ensure_ascii=False, indent=2)
        print(f"Створено дефолтний {filename}")

def load_hls_streams(filename=STREAMS_JSON):
    if not os.path.exists(filename):
        ensure_streams_file(filename)
    try:
        with open(filename, "r", encoding="utf-8") as f:
            streams = json.load(f)
            # Фільтруємо тільки валідні записи
            valid_streams = [s for s in streams if isinstance(s, dict) and "url" in s and "name" in s]
            streams = valid_streams[:8]  # Беремо тільки перші 8 стрімів
            return streams
    except Exception as e:
        print("Помилка читання streams.json:", e)
        print(f"Помилка читання {filename}:", e)
        return []

# ---------------------------
# --- Ініціалізація апаратури та станів ---
# ---------------------------
hotspot = WifiHotspotServer(ssid="PiLdVideo", password="video1234", folder="download", port=8000)

lrf_sensor = LRF(port='/dev/ttyAMA0', enable_pin=17, mode=LRF.SINGLE)
lrf_sensor.power_on()  # на старті можемо включити, або керувати пізніше
lrf_powered = True

# --- Шрифти для HUD ---
FONT_PATH = "/home/laserlab/LD_PROJECT/DejaVuSans.ttf"
if PIL_AVAILABLE and os.path.exists(FONT_PATH):
    FONT_HUD = ImageFont.truetype(FONT_PATH, 16)
    FONT_HUD_LARGE = ImageFont.truetype(FONT_PATH, 22)
    FONT_STREAM_MODE = ImageFont.truetype(FONT_PATH, 24)
    FONT_HLS = ImageFont.truetype(FONT_PATH, 14)
else:
    FONT_HUD = None
    FONT_HUD_LARGE = None
    FONT_STREAM_MODE = None
    FONT_HLS = None
    
# HUD, хотспот, LRF
hud = HUDManager(font=FONT_HUD_LARGE)

# ---------------------------
# --- Потоки та device_list ---
# ---------------------------
hls_streams = load_hls_streams(STREAMS_JSON)
current_hls_idx = 0  # індекс активного HLS-потоку

# Порядок пристроїв: pipeline CSI / /dev/video0 / HLS
device_list = [
    "libcamerasrc ! video/x-raw,format=BGR,width=1024,height=600,framerate=30/1 ! videoconvert ! appsink",
    "/dev/video0"
]
if hls_streams:
    device_list.append(hls_streams[current_hls_idx]["url"])
else:
    device_list.append("")  # placeholder

camera_labels = ["Wide camera", "Thermal camera", "HTTP Stream"]
current_cam_idx = 0

# ---------------------------
# --- Глобальні стани UI ---
# ---------------------------
show_crosshair = False
zoom = 1.0
continuous_measure = False
continuous_start_time = None
motion_detection_active = False
enhance_active = False
recording = False
video_writer = None
distance_text = "Distance: N/A"
active_set = "HUD"
menu_page = 0
menu_files = []
continuous_off_msg = ""
button_sets = {}
button_pressed = {}

# Лічильник кадрів для оптимізації
frame_count = 0
MOTION_DETECT_FRAME_SKIP = 5 # Аналізувати кожен 5-й кадр

# Детектор руху
motion_detector = MotionDetector(
    min_contour_area=300,   # Збільшено з 100. Ігноруємо дрібні об'єкти.
    scale_factor=0.6,       # Аналізуємо зменшений кадр для швидкості.
    var_threshold=700       # Збільшено з 50. Робить детектор менш чутливим до змін освітлення.
)

# Ініціалізація аудіоплеєра
audio_player = AudioPlayer("/home/laserlab/LD_PROJECT/alarm-clock-beep-1_zjgin-vd.mp3")

# Ініціалізація аудіоплеєра
audio_player_ondetect = AudioPlayer("/home/laserlab/LD_PROJECT/audio-editor-output.mp3")

# Video playback
video_playing = False
video_cap = None

# mouse state
mouse_pressed_name = None
mouse_pressed_rect = None
mouse_pressed_set = None

# HLS buttons layout
HLS_BTN_SIZE = 40
HLS_BTN_SPACING = 10
HLS_BTN_X_START = 200
HLS_BTN_Y_START = 10

# Close btn for playback
close_x = close_y = close_w = close_h = 0

# Blink start
blink_start_time = time.time()

# --- Функції для камер / HLS ---
def open_camera(index):
    global current_hls_idx
    source = None
    try:
        source = device_list[index]
    except IndexError:
        return None

    if isinstance(source, str):
        # HLS case: third index (2)
        if index == 2 and hls_streams:
            url = hls_streams[current_hls_idx]["url"]
            try:
                cap = HLSVideo(url, fps=FPS, width=FRAME_W, height=FRAME_H)
                # якщо у HLSVideo є isOpened:
                if hasattr(cap, "isOpened"):
                    if not cap.isOpened():
                        print("HLSVideo не відкрився, пробуємо OpenCV")
                return cap
            except Exception as e:
                print("HLSVideo error:", e)
                # fallback to cv2
                cap = cv2.VideoCapture(url)
                return cap

        # /dev/video* device
        if source.startswith("/dev/"):
            cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
            if not cap.isOpened():
                cap = cv2.VideoCapture(source)
            try:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
            except Exception:
                pass
            return cap

        # GStreamer pipeline (string with '!')
        if "!" in source:
            cap = cv2.VideoCapture(source, cv2.CAP_GSTREAMER)
            return cap

        # Generic HTTP/RTSP/local file
        cap = cv2.VideoCapture(source)
        return cap
    else:
        # other types
        return None

# Запускаємо стартову камеру
cap = open_camera(current_cam_idx)
if cap is None or (hasattr(cap, "isOpened") and not cap.isOpened()):
    print("Не вдалося відкрити початкову камеру:", device_list[current_cam_idx])
    # спробуємо /dev/video0
    current_cam_idx = 1
    cap = open_camera(current_cam_idx)
    if cap is None or (hasattr(cap, "isOpened") and not cap.isOpened()):
        print("Критична помилка: не знайдено доступних камер.")
        # не робимо exit — даємо шанс запустити і перевірити
        # sys.exit(1)

# --- Enhancement filter ---
def enhance_image(frame):
    alpha, beta = 1.8, 20
    frame_enhanced = cv2.convertScaleAbs(frame, alpha=alpha, beta=beta)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    return cv2.filter2D(frame_enhanced, -1, kernel)

# --- Функція для малювання тексту з підтримкою UTF-8 ---
def draw_text_pil(frame, text, pos, font, color=(255, 255, 255)):
    """
    Малює текст на кадрі OpenCV за допомогою Pillow.
    Підтримує UTF-8 символи.
    """
    if not PIL_AVAILABLE or not font:
        # Fallback до стандартного cv2.putText, якщо Pillow недоступний
        # або шрифт не завантажено. Кирилиця не буде працювати.
        cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        return frame

    # Конвертуємо кадр OpenCV (BGR) в зображення Pillow (RGB)
    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)

    # Малюємо текст
    draw.text(pos, text, font=font, fill=color)

    # Конвертуємо назад в кадр OpenCV
    frame = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
    return frame


# --- Buttons system (HUD/Menu) ---
def create_button_set(name, buttons_dict):
    button_sets[name] = buttons_dict
    for btn in buttons_dict.keys():
        button_pressed[btn] = False

def set_active_button_set(name):
    global active_set
    if name in button_sets:
        active_set = name

create_button_set("HUD", {
    "crosshair": (10, 10, 150, 50, "Crosshair"),
    "zoom_in": (10, 70, 150, 50, "Zoom +"),
    "zoom_out": (10, 130, 150, 50, "Zoom -"),
    "switch_cam": (10, 190, 150, 50, camera_labels[current_cam_idx]),
    "single_measure": (10, 250, 150, 50, "Single Measure"),
    "continuous_measure": (10, 310, 150, 50, "Cont. Measure"),
    "enhance": (10, 370, 150, 50, "Enhance"),
    "record": (10, 430, 150, 50, "Record"),
    "play": (10, 490, 150, 50, "Play"),
    "motion_detect": (10, 550, 150, 50, "Motion Detect")
})

def update_switch_cam_label():
    if "HUD" in button_sets and "switch_cam" in button_sets["HUD"]:
        x, y, w, h, _ = button_sets["HUD"]["switch_cam"]
        button_sets["HUD"]["switch_cam"] = (x, y, w, h, camera_labels[current_cam_idx])

# --- Recording / menu files ---
def start_or_stop_recording():
    global recording, video_writer
    if not os.path.exists(RECORD_DIR):
        os.makedirs(RECORD_DIR)
    if not recording:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(RECORD_DIR, f"rec_{timestamp}.mp4")
        video_writer = cv2.VideoWriter(filename, cv2.VideoWriter_fourcc(*'mp4v'), FPS, (FRAME_W, FRAME_H))
        recording = True
        print("▶️ Запис стартував:", filename)
    else:
        recording = False
        if video_writer:
            video_writer.release()
            video_writer = None
        print("⏹ Запис зупинено")

def update_menu_files():
    global menu_files
    if not os.path.exists(RECORD_DIR):
        os.makedirs(RECORD_DIR)
    menu_files = sorted([f for f in os.listdir(RECORD_DIR) if f.endswith(".mp4")],
                        key=lambda x: os.path.getmtime(os.path.join(RECORD_DIR, x)),
                        reverse=True)

def get_menu_buttons(page):
    buttons = {}
    start_idx = page * MENU_FILES_PER_PAGE
    end_idx = start_idx + MENU_FILES_PER_PAGE
    files_to_show = menu_files[start_idx:end_idx]

    col_w, col_h = 200, 40
    x_positions = [10, 220, 430]
    y_start = 10
    spacing = 10

    for i, fname in enumerate(files_to_show):
        col_idx = i % 3
        row_idx = i // 3
        col = x_positions[col_idx]
        row = y_start + row_idx * (col_h + spacing)
        name_no_ext = os.path.splitext(fname)[0]
        buttons[f"file_{fname}"] = (col, row, col_w, col_h, name_no_ext)

    btn_y = y_start + 5 * (col_h + spacing) + 20
    if (page + 1) * MENU_FILES_PER_PAGE < len(menu_files):
        buttons["next_page"] = (10, btn_y, 150, 40, "Next")
    if page > 0:
        buttons["prev_page"] = (170, btn_y, 150, 40, "Prev")
    buttons["back"] = (340, btn_y, 150, 40, "Back")
    buttons["delete_all"] = (500, btn_y, 180, 40, "Delete All")
    return buttons

def refresh_menu_buttons():
    global button_sets
    update_menu_files()
    button_sets["Menu"] = get_menu_buttons(menu_page)

# --- Video playback ---
def start_video(filename):
    global video_playing, video_cap
    filepath = os.path.join(RECORD_DIR, filename)
    if not os.path.exists(filepath):
        print("Файл не знайдено:", filepath)
        return
    video_cap = cv2.VideoCapture(filepath)
    if not video_cap.isOpened():
        print("Не вдалося відкрити відео:", filepath)
        return
    video_playing = True

def stop_video():
    global video_playing, video_cap
    if video_cap:
        video_cap.release()
    video_playing = False
    set_active_button_set("Menu")
    refresh_menu_buttons()

# --- Measures / camera switching ---
def do_single_measure():
    global distance_text, lrf_powered
    if not lrf_powered:
        lrf_sensor.power_on()
        lrf_powered = True
        time.sleep(0.3) # Даємо час на ініціалізацію

    result = lrf_sensor.get_single_measurement()
    if result:
        distance_text = f"Distance: {result:.1f} m"
    else:
        distance_text = "Distance: N/A"
    hud.show_message("Single measurement done")

def switch_camera():
    global current_cam_idx, cap, hud
    global current_cam_idx, cap, hud, motion_detection_active

    if motion_detection_active:
        motion_detection_active = False
        hud.show_message("Motion Detection OFF (camera switched)")

    motion_detector.reset() # Скидаємо детектор при зміні камери
    
    previous_cam_idx = current_cam_idx
    
    try:
        cap.release()
    except Exception:
        pass
    current_cam_idx = (current_cam_idx + 1) % len(device_list)
    cap = open_camera(current_cam_idx)
    if not cap or (hasattr(cap, "isOpened") and not cap.isOpened()):
        cam_name = camera_labels[current_cam_idx]
        hud.show_message(f"Error: {cam_name} not found")
        print(f"Помилка: не вдалося відкрити камеру {cam_name}")
        # Повертаємось до попередньої камери
        current_cam_idx = previous_cam_idx
        cap = open_camera(current_cam_idx)
    update_switch_cam_label()


# --- HLS stream switching ---
def switch_hls_stream(index):
    global current_hls_idx, cap, device_list
    global current_hls_idx, cap, device_list, motion_detection_active

    if motion_detection_active:
        motion_detection_active = False
        hud.show_message("Motion Detection OFF (stream switched)")

    if index < 0 or index >= len(hls_streams):
        motion_detector.reset() # Скидаємо детектор при зміні стріму
        return
    current_hls_idx = index
    # Оновлюємо device_list[2] на новий URL (на випадок, якщо іншими місцями звертаємось)
    device_list[2] = hls_streams[current_hls_idx]["url"]
    try:
        cap.release()
    except Exception:
        pass
    # Відкриваємо HLS (якщо зараз активна HTTP камера)
    if current_cam_idx == 2:
        cap = open_camera(2)
    print(f"🔄 Перемикання HLS → {hls_streams[current_hls_idx]['name']}")

# --- Button callback ---
def menu_button_callback(name):
    global menu_page
    if name.startswith("file_"):
        filename = name[5:]
        start_video(filename)
    elif name == "next_page":
        menu_page += 1
    elif name == "prev_page":
        menu_page -= 1
    elif name == "back":
        set_active_button_set("HUD")
    elif name == "delete_all":
        for f in menu_files:
            os.remove(os.path.join(RECORD_DIR, f))
        menu_page = 0
        update_menu_files()
        refresh_menu_buttons()
        print("🗑 Усі файли видалено")
    refresh_menu_buttons()

def button_callback(name, pressed, current_set):
    global show_crosshair, zoom, recording, enhance_active, continuous_measure, continuous_start_time
    global lrf_powered, distance_text, video_playing, motion_detection_active
    if not pressed:
        return

    if current_set == "Menu":
        menu_button_callback(name)
        return

    if current_set == "HUD":
        if name == "crosshair":
            if continuous_measure:
                hud.show_message("Спочатку зупиніть безперервне вимірювання")
                return
            show_crosshair = not show_crosshair
            # Скидаємо текст відстані, якщо вимикаємо приціл
            if show_crosshair:
                lrf_sensor.power_on()
                lrf_powered = True
                result = lrf_sensor.get_single_measurement()
                distance_text = f"Distance: {result:.1f} m" if result else "Distance: N/A"
                print("Приціл увімкнено, далекомір запущено")
            else:
                lrf_sensor.power_off()
                lrf_powered = False
                distance_text = "Distance: N/A"
                print("Приціл вимкнено, далекомір зупинено")
        elif name == "zoom_in":
            global zoom
            zoom = min(ZOOM_MAX, zoom + ZOOM_STEP)
        elif name == "zoom_out":
            zoom = max(ZOOM_MIN, zoom - ZOOM_STEP)
        elif name == "switch_cam":
            switch_camera()
        elif name == "single_measure":
            if continuous_measure:
                hud.show_message("Спочатку зупиніть безперервне вимірювання")
                return
            if not show_crosshair:
                hud.show_message("Спочатку увімкніть приціл")
                return
            do_single_measure()
        elif name == "continuous_measure":
            if not show_crosshair:
                hud.show_message("Спочатку увімкніть приціл")
                return
            continuous_measure = not continuous_measure
            if continuous_measure:
                continuous_start_time = time.time()
                hud.show_message("Continuous measurement ON")
            else:
                continuous_start_time = None
                hud.show_message("Continuous measurement OFF")
        elif name == "enhance":
            enhance_active = not enhance_active
        elif name == "record":
            start_or_stop_recording()
        elif name == "play":
            refresh_menu_buttons()
            set_active_button_set("Menu")
        elif name == "motion_detect":
            motion_detection_active = not motion_detection_active
            if motion_detection_active:
                motion_detector.reset() # Скидаємо стан при активації
                hud.show_message("Motion Detection ON")
                audio_player.play()
        elif name == "exit":
            if lrf_powered:
                try:
                    audio_player.stop()
                except:
                    pass
                lrf_sensor.power_off()
            sys.exit(0)

# --- Mouse handler (включає HLS кнопки) ---
def mouse_event(event, x, y, flags, param):
    global mouse_pressed_name, mouse_pressed_rect, mouse_pressed_set, video_playing
    global close_x, close_y, close_w, close_h

   # Якщо відтворюється відео — кнопка Close
    if video_playing and video_cap:
        if event == cv2.EVENT_LBUTTONUP:
            if close_x <= x <= close_x + close_w and close_y <= y <= close_y + close_h:
                stop_video()
        return

    # HLS кнопки (зверху)
    if current_cam_idx == 2 and hls_streams:
        for i in range(len(hls_streams)):
            bx = HLS_BTN_X_START + i * (HLS_BTN_SIZE + HLS_BTN_SPACING)
            by = HLS_BTN_Y_START
            if by <= y <= by + HLS_BTN_SIZE and bx <= x <= bx + HLS_BTN_SIZE:
                if event == cv2.EVENT_LBUTTONUP:
                    switch_hls_stream(i)
                return

    if active_set not in button_sets:
        return

    if event == cv2.EVENT_LBUTTONDOWN:
        for name, data in button_sets[active_set].items():
            if len(data) != 5:
                continue
            bx, by, bw, bh, label = data
            if bx <= x <= bx + bw and by <= y <= by + bh:
                # Блокування всіх кнопок крім switch_cam при HLS
                if current_cam_idx == 2 and name != "switch_cam":
                    hud.show_message("Кнопка вимкнена в режимі HLS")
                    return
                mouse_pressed_name = name
                mouse_pressed_rect = (bx, by, bw, bh)
                mouse_pressed_set = active_set
                break
        return

    if event == cv2.EVENT_LBUTTONUP:
        if mouse_pressed_name and mouse_pressed_rect:
            bx, by, bw, bh = mouse_pressed_rect
            if bx <= x <= bx + bw and by <= y <= by + bh:
                button_callback(mouse_pressed_name, True, mouse_pressed_set)
            button_pressed[mouse_pressed_name] = False
        mouse_pressed_name = None
        mouse_pressed_rect = None
        mouse_pressed_set = None

# --- Малювання HLS кнопок ---
def draw_hls_buttons(frame):
    if current_cam_idx != 2 or not hls_streams:
        return frame
    for i, stream in enumerate(hls_streams):
        x = HLS_BTN_X_START + i * (HLS_BTN_SIZE + HLS_BTN_SPACING)
        y = HLS_BTN_Y_START
        color = (0, 200, 0) if i == current_hls_idx else (100, 100, 100)
        cv2.rectangle(frame, (x, y), (x + HLS_BTN_SIZE, y + HLS_BTN_SIZE), color, -1)
        # нумерація з 1
        cv2.putText(frame, str(i+1), (x + 12, y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
    # показати назву потоку
    name = hls_streams[current_hls_idx]["name"]
    cv2.putText(frame, name, (HLS_BTN_X_START, HLS_BTN_Y_START + HLS_BTN_SIZE + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)    
    return draw_text_pil(frame, name, (HLS_BTN_X_START, HLS_BTN_Y_START + HLS_BTN_SIZE + 5), FONT_HLS)


# --- Налаштування вікна та колбек миші ---
cv2.namedWindow("Camera HUD")
cv2.setWindowProperty("Camera HUD", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
cv2.setMouseCallback("Camera HUD", mouse_event)

# --- Основний цикл ---
try:
    while True:
        # Відтворення записаного відео
        if video_playing and video_cap:
            ret, frame = video_cap.read()
            if not ret:
                stop_video()
                continue
            frame = cv2.resize(frame, (FRAME_W, FRAME_H))
            # HUD overlay секунд/тайм
            fps = video_cap.get(cv2.CAP_PROP_FPS) or FPS
            frames = int(video_cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            total_sec = int(frames / fps) if fps > 0 else 0
            current_sec = int(video_cap.get(cv2.CAP_PROP_POS_MSEC) / 1000)
            overlay = frame.copy()
            hud_w, hud_h = 220, 80
            overlay_x, overlay_y = FRAME_W - hud_w - 10, FRAME_H - hud_h - 10
            cv2.rectangle(overlay, (overlay_x, overlay_y),
                          (overlay_x + hud_w, overlay_y + hud_h),
                          (0, 0, 0), -1)
            frame = cv2.addWeighted(overlay, 0.4, frame, 0.6, 0)
            time_text = f"{current_sec:02d}s / {total_sec:02d}s"
            cv2.putText(frame, time_text, (overlay_x + 10, overlay_y + 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
            frame = draw_text_pil(frame, time_text, (overlay_x + 10, overlay_y + 10), FONT_HUD_LARGE)
            # Close button
            close_w, close_h = 80, 25
            close_x, close_y = overlay_x + 10, overlay_y + 45
            cv2.rectangle(frame, (close_x, close_y),
                          (close_x + close_w, close_y + close_h),
                          (50,50,50), -1)
            cv2.putText(frame, "Close", (close_x + 10, close_y + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
            cv2.imshow("Camera HUD", frame)
            if cv2.waitKey(int(1000/FPS)) & 0xFF == ord('q'):
                stop_video()
            continue

        # Основна камера
        if cap is None:
            cap = open_camera(current_cam_idx)

        ret = False
        frame = None
        try:
            if cap:
                if hasattr(cap, "read"):
                    ret, frame = cap.read()
                elif hasattr(cap, "isOpened") and cap.isOpened():
                    ret, frame = cap.read()
        except Exception as e:
            print("Помилка читання кадру:", e)
            ret = False

        if not ret or frame is None:
            try:
                if cap: cap.release()
            except Exception:
                pass

            # Спеціальна обробка для недоступних HLS стрімів
            if current_cam_idx == 2 and hls_streams:
                initial_hls_idx = current_hls_idx
                switched = False
                for i in range(len(hls_streams)):
                    next_idx = (initial_hls_idx + 1 + i) % len(hls_streams)
                    
                    print(f"⚠️ HLS стрім '{hls_streams[current_hls_idx]['name']}' недоступний. Спроба переключення на '{hls_streams[next_idx]['name']}'...")
                    hud.show_message(f"Stream unavailable, trying next...")
                    
                    switch_hls_stream(next_idx) # Ця функція оновить `cap`
                    
                    # Перевіряємо, чи відкрився новий стрім
                    if cap and hasattr(cap, "isOpened") and cap.isOpened():
                        ret, frame = cap.read()
                        if ret and frame is not None:
                            switched = True
                            break # Знайшли робочий стрім, виходимо з циклу
                
                if not switched:
                     hud.show_message("All HLS streams failed, switching camera")
                     switch_camera()
            else:
                # Обробка для інших камер (CSI/USB)
                cam_name = camera_labels[current_cam_idx]
                print(f"⚠️ Камера {cam_name} недоступна.")
                hud.show_message(f"No stream from: {cam_name}")
                switch_camera()

            time.sleep(0.5)
            continue

        frame = cv2.resize(frame, (FRAME_W, FRAME_H))
        h, w, _ = frame.shape
        center_x, center_y = w//2, h//2

        # Zoom
        if zoom != 1.0:
            nh, nw = int(h / zoom), int(w / zoom)
            y1, y2 = center_y - nh//2, center_y + nh//2
            x1, x2 = center_x - nw//2, center_x + nw//2
            # захищені границі
            y1, y2 = max(0, y1), min(h, y2)
            x1, x2 = max(0, x1), min(w, x2)
            frame = frame[y1:y2, x1:x2]
            frame = cv2.resize(frame, (w, h))

        # Continuous measure
        continuous_off_msg = ""
        if continuous_measure:
            result = lrf_sensor.get_single_measurement()
            distance_text = f"Distance: {result:.1f} m" if result else "Distance: N/A"
            if continuous_start_time:
                elapsed = (time.time() - continuous_start_time) / 60.0
                if elapsed >= CONTINUOUS_AUTO_OFF_MINUTES:
                    continuous_measure = False
                    continuous_off_msg = f"⚠️ Авто вимкнення через {CONTINUOUS_AUTO_OFF_MINUTES} хв"
                    print(continuous_off_msg)

        # Enhance
        if enhance_active:
            frame = enhance_image(frame)

        # Motion Detection
        frame_count += 1
        if motion_detection_active and current_cam_idx != 2 and frame_count % MOTION_DETECT_FRAME_SKIP == 0:
            frame, motion_found = motion_detector.detect(frame)
            if motion_found:
                # Ось тут ми відтворюємо звук!
                audio_player_ondetect.play()

        # Crosshair
        if show_crosshair:
            cv2.line(frame, (center_x-20, center_y), (center_x+20, center_y), (0,0,255),2)
            cv2.line(frame, (center_x, center_y-20), (center_x, center_y+20), (0,0,255),2)
            cv2.circle(frame, (center_x, center_y), 5, (0,0,255), -1)
            if distance_text != "Distance: N/A":
                distance_display = distance_text.replace("Distance: ", "")
                cv2.putText(frame, f"{distance_display}", (center_x + 25, center_y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 2)

        # HUD overlay
        overlay = frame.copy()
        rect_w, rect_h = 300, 280
        rect_x, rect_y = w - rect_w - 10, 10
        cv2.rectangle(overlay, (rect_x, rect_y), (rect_x+rect_w, rect_y+rect_h), (50,50,50), -1)
        frame = cv2.addWeighted(overlay, 0.5, frame, 0.5, 0)

        # HUD Text
        line_y = rect_y + 30
        if current_cam_idx == 2:
           # cv2.putText(frame, "Streaming mode", (rect_x+10, line_y),
            #            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)
            frame = draw_text_pil(frame, "Режим стрімінгу", (rect_x+10, line_y - 15), FONT_STREAM_MODE, (255,0,0))
            
        else:
            frame = draw_text_pil(frame, distance_text, (rect_x+10, line_y - 15), FONT_HUD_LARGE)
            if continuous_measure and int(time.time()*2) % 2 == 0:
                cv2.circle(frame, (rect_x+250, line_y-10), 8, (0,255,0), -1)
            line_y += 30
            frame = draw_text_pil(frame, f"Роздільність: {FRAME_W}x{FRAME_H}", (rect_x+10, line_y - 15), FONT_HUD)
            if zoom > 1.0:
                line_y += 30
                frame = draw_text_pil(frame, f"Зум: {zoom:.2f}x", (rect_x+10, line_y - 15), FONT_HUD)
            if recording:
                line_y += 30
                frame = draw_text_pil(frame, "ЗАПИС", (rect_x+10, line_y - 15), FONT_HUD, (0,0,255))
            if continuous_off_msg:
                line_y += 30
                frame = draw_text_pil(frame, continuous_off_msg, (rect_x+10, line_y - 15), FONT_HUD, (0,200,255))

        # Draw HUD buttons
        prev_continuous_state = False
        if active_set in button_sets and not video_playing:
            for name, data in button_sets[active_set].items():
                if len(data) != 5:
                    continue
                bx, by, bw, bh, label = data
                active = button_pressed.get(name, False)

                # Блокування кнопок при HLS режимі
                if current_cam_idx == 2 and name != "switch_cam":
                    color = (80, 80, 80)
                    if mouse_pressed_name == name:
                        hud.show_message("Кнопка вимкнена в режимі HLS")

                elif (name == "crosshair" or name == "single_measure") and continuous_measure:
                    color = (80, 80, 80)
                    if mouse_pressed_name == name:
                        hud.show_message("Спочатку зупиніть безперервне вимірювання")

                elif (name == "single_measure" or name == "continuous_measure") and not show_crosshair:
                    color = (80, 80, 80)
                    if mouse_pressed_name == name:
                        hud.show_message("Спочатку увімкніть приціл")

                elif name == "switch_cam" and current_cam_idx == 2:
                    t = time.time() - blink_start_time
                    factor = (math.sin(t * 2 * math.pi / 1.5) + 1) / 2  # період 1.5 сек
                    base_color = np.array([0, 100, 200], dtype=np.float32)
                    red_color = np.array([0, 0, 255], dtype=np.float32)
                    color = (base_color * (1 - factor) + red_color * factor).astype(int)
                    color = tuple(color.tolist())
                else:
                    is_active_state = (
                        (name == "enhance" and enhance_active) or
                        (name == "record" and recording) or
                        (name == "continuous_measure" and continuous_measure) or
                        (name == "motion_detect" and motion_detection_active)
                    )
                    color = (0, 150, 0) if (active or is_active_state) else (0, 100, 200)
                cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), color, -1)
                cv2.putText(frame, label, (bx+5, by+30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

        # Малюємо HLS кнопки зверху (якщо в HLS режимі)
        frame = draw_hls_buttons(frame)

        # Малюємо HUD (custom)
        frame = hud.draw(frame)

        # Запис
        if recording and video_writer:
            video_writer.write(frame)

        cv2.imshow("Camera HUD", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except KeyboardInterrupt:
    print("Завершення по Ctrl+C")

# --- Завершення ---
try:
    if video_writer:
        video_writer.release()
    if video_cap:
        video_cap.release()
    if cap:

        cap.release()
except Exception:
    pass

cv2.destroyAllWindows()

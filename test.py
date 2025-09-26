import cv2
import numpy as np
import time
import os
from datetime import datetime
from ldtest import LRF  # Імпортуємо клас LRF із ldtest

# --- Ініціалізація далекоміра ---
lrf_sensor = LRF(port='/dev/ttyAMA0', enable_pin=17, mode=LRF.SINGLE)
lrf_sensor.power_on()

# --- Константи ---
FRAME_W, FRAME_H = 1024, 600
ZOOM_STEP = 0.06
ZOOM_MIN, ZOOM_MAX = 1.0, 5.0
CONTINUOUS_TIMEOUT_MINUTES = 2  # ⏱ авто-вимкнення безперервного вимірювання

# --- Камери ---
device_list = [
    "/dev/video0",  # USB/V4L2
    (
        "libcamerasrc ! "
        "video/x-raw,format=BGR,width=1024,height=600,framerate=30/1 ! "
        "videoconvert ! appsink"
    )  # CSI камера через GStreamer
]
current_cam_idx = 0

def open_camera(index):
    """Відкрити камеру за індексом із device_list"""
    source = device_list[index]
    if isinstance(source, str) and source.startswith("/dev/"):
        cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap = cv2.VideoCapture(source)  # fallback
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    else:
        cap = cv2.VideoCapture(source, cv2.CAP_GSTREAMER)
    return cap

# Відкриваємо першу камеру
cap = open_camera(current_cam_idx)
if not cap.isOpened():
    print("Камеру не знайдено:", device_list[current_cam_idx])
    exit()

# --- Стани ---
show_crosshair = True
zoom = 1.0
single_measure = False
continuous_measure = False
continuous_start_time = None
enhance_active = False
recording = False
video_writer = None
distance_text = "Distance: N/A"
video_filename = None

# --- Параметри запису ---
fps = 30.0
fourcc = cv2.VideoWriter_fourcc(*'mp4v')

# --- Кнопки ---
button_w, button_h = 150, 50
buttons = {
    "crosshair": (10, 10),
    "zoom_in": (10, 70),
    "zoom_out": (10, 130),
    "switch_cam": (10, 190),
    "single_measure": (10, 250),
    "continuous_measure": (10, 310),
    "enhance": (10, 370),
    "record": (10, 430)
}
button_pressed = {name: False for name in buttons.keys()}

# --- Покращення кадру ---
def enhance_image(frame):
    alpha, beta = 1.8, 20
    frame_enhanced = cv2.convertScaleAbs(frame, alpha=alpha, beta=beta)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    return cv2.filter2D(frame_enhanced, -1, kernel)

# --- Обробка миші ---
def mouse_event(event, x, y, flags, param):
    global show_crosshair, zoom, cap, current_cam_idx, device_list
    global single_measure, continuous_measure, continuous_start_time
    global enhance_active, recording, video_writer, video_filename

    if event in [cv2.EVENT_LBUTTONDOWN, cv2.EVENT_LBUTTONUP]:
        for name, (bx, by) in buttons.items():
            inside = bx <= x <= bx + button_w and by <= y <= by + button_h
            if inside:
                if event == cv2.EVENT_LBUTTONDOWN:
                    button_pressed[name] = True
                    if name == "crosshair":
                        show_crosshair = not show_crosshair
                    elif name == "switch_cam":
                        cap.release()
                        current_cam_idx = (current_cam_idx + 1) % len(device_list)
                        cap = open_camera(current_cam_idx)
                        if not cap.isOpened():
                            print("Камеру не знайдено:", device_list[current_cam_idx])
                    elif name == "single_measure":
                        single_measure = True
                        continuous_measure = False
                        continuous_start_time = None
                    elif name == "continuous_measure":
                        continuous_measure = not continuous_measure
                        single_measure = False
                        if continuous_measure:
                            continuous_start_time = time.time()
                        else:
                            continuous_start_time = None
                    elif name == "enhance":
                        enhance_active = not enhance_active
                    elif name == "record":
                        if not recording:
                            recording = True
                            # 📂 Одна папка "record"
                            folder_name = "record"
                            os.makedirs(folder_name, exist_ok=True)

                            # 🎥 Унікальна назва файлу
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            video_filename = os.path.join(folder_name, f"rec{timestamp}.mp4")

                            video_writer = cv2.VideoWriter(video_filename, fourcc, fps, (FRAME_W, FRAME_H))
                            print("▶️ Запис стартував... Файл:", video_filename)
                        else:
                            recording = False
                            if video_writer:
                                video_writer.release()
                                video_writer = None
                            print("⏹ Запис зупинено.")
                elif event == cv2.EVENT_LBUTTONUP:
                    button_pressed[name] = False

# --- Головне вікно ---
cv2.namedWindow("Camera HUD")
cv2.setWindowProperty("Camera HUD", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
cv2.setMouseCallback("Camera HUD", mouse_event)

# --- Основний цикл ---
while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.resize(frame, (FRAME_W, FRAME_H))
    h, w, _ = frame.shape
    center_x, center_y = w // 2, h // 2

    # --- Zoom ---
    if button_pressed["zoom_in"]:
        zoom = min(ZOOM_MAX, zoom + ZOOM_STEP)
    if button_pressed["zoom_out"]:
        zoom = max(ZOOM_MIN, zoom - ZOOM_STEP)
    if zoom != 1.0:
        nh, nw = int(h / zoom), int(w / zoom)
        y1, y2 = center_y - nh // 2, center_y + nh // 2
        x1, x2 = center_x - nw // 2, center_x + nw // 2
        frame = frame[y1:y2, x1:x2]
        frame = cv2.resize(frame, (w, h))

    # --- Разове вимірювання ---
    if single_measure:
        result = lrf_sensor.get_single_measurement()
        if result:
            distance_text = f"Distance: {result:.1f} m"
        else:
            distance_text = "Distance: N/A"
        single_measure = False

    # --- Безперервне вимірювання ---
    if continuous_measure:
        result = lrf_sensor.get_single_measurement()
        if result:
            distance_text = f"Distance: {result:.1f} m"
        else:
            distance_text = "Distance: N/A"

        elapsed_minutes = (time.time() - continuous_start_time) / 60
        if elapsed_minutes >= CONTINUOUS_TIMEOUT_MINUTES:
            continuous_measure = False
            continuous_start_time = None
            print("⚠️ Continuous Measure автоматично вимкнено (таймаут)")

    # --- Enhance ---
    if enhance_active:
        frame = enhance_image(frame)

    # --- Crosshair ---
    if show_crosshair:
        cv2.line(frame, (center_x - 20, center_y), (center_x + 20, center_y), (0, 0, 255), 2)
        cv2.line(frame, (center_x, center_y - 20), (center_x, center_y + 20), (0, 0, 255), 2)
        cv2.circle(frame, (center_x, center_y), 5, (0, 0, 255), -1)

    # --- HUD ---
    overlay = frame.copy()
    rect_w, rect_h = 253, 260
    rect_x, rect_y = w - rect_w - 10, 10
    cv2.rectangle(overlay, (rect_x, rect_y), (rect_x + rect_w, rect_y + rect_h), (50, 50, 50), -1)
    frame = cv2.addWeighted(overlay, 0.5, frame, 0.5, 0)

    # --- HUD Text ---
    line_y = rect_y + 30
    cv2.putText(frame, distance_text, (rect_x + 10, line_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    line_y += 30
    cv2.putText(frame, f"GPS Sat: 7", (rect_x + 10, line_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    line_y += 30
    cv2.putText(frame, f"Resolution: {FRAME_W}x{FRAME_H}", (rect_x + 10, line_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    if zoom > 1.0:
        line_y += 30
        cv2.putText(frame, f"Zoom: {zoom:.2f}x", (rect_x + 10, line_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    if recording:
        line_y += 30
        cv2.putText(frame, "REC", (rect_x + 10, line_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

    if continuous_measure:
        cv2.circle(frame, (rect_x + rect_w - 20, rect_y + 20), 10, (0, 255, 0), -1)
        if continuous_start_time:
            remaining = CONTINUOUS_TIMEOUT_MINUTES - (time.time() - continuous_start_time) / 60
            if remaining > 0:
                line_y += 30
                cv2.putText(frame, f"Auto-off in: {remaining:.1f} min", (rect_x + 10, line_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 255, 200), 2)

    # --- Buttons ---
    for name, (bx, by) in buttons.items():
        active = (
            button_pressed.get(name, False)
            or (name == "enhance" and enhance_active)
            or (name == "record" and recording)
            or (name == "continuous_measure" and continuous_measure)
        )
        color = (0, 150, 0) if active else (0, 100, 200)
        cv2.rectangle(frame, (bx, by), (bx + button_w, by + button_h), color, -1)
        label = {
            "crosshair": "Crosshair",
            "zoom_in": "Zoom +",
            "zoom_out": "Zoom -",
            "switch_cam": "Switch Cam",
            "single_measure": "Single Measure",
            "continuous_measure": "Cont. Measure",
            "enhance": "Enhance",
            "record": "Record"
        }[name]
        cv2.putText(frame, label, (bx + 5, by + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

    # --- Запис відео ---
    if recording and video_writer is not None:
        video_writer.write(frame)

    cv2.imshow("Camera HUD", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# --- Завершення ---
if video_writer:
    video_writer.release()
cap.release()
cv2.destroyAllWindows()

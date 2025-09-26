import serial
import time
import RPi.GPIO as GPIO


class LRF:
    SINGLE = 0
    CONTINUOUS = 1

    def __init__(self, port='/dev/ttyAMA0', enable_pin=17, mode=SINGLE):
        self.port = port
        self.enable_pin = enable_pin
        self.mode = mode

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.enable_pin, GPIO.OUT)

        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=115200,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=2
            )
        except serial.SerialException as e:
            print(f"Помилка: Не вдалося відкрити порт {self.port}. {e}")
            print("Перевірте, чи правильно налаштовано UART в 'sudo raspi-config'.")
            GPIO.cleanup()
            exit()

        print(f"LRF ініціалізовано на порту {self.port} з піном живлення {self.enable_pin}.")

    # --- Живлення ---
    def power_on(self):
        """Вмикає живлення модуля."""
        print("Вмикання модуля...")
        GPIO.output(self.enable_pin, GPIO.HIGH)
        time.sleep(0.3)  # Затримка >200 мс

        if self.mode == self.CONTINUOUS:
            print("▶ Автоматичний запуск continuous mode")
            self.start_continuous_measurement()

    def power_off(self):
        """Вимикає живлення модуля."""
        print("Вимикання модуля...")
        GPIO.output(self.enable_pin, GPIO.LOW)

    # --- Робота з UART ---
    def _calculate_checksum(self, command_data):
        """Розраховує контрольну суму (сума байтів по модулю 256)."""
        return sum(command_data) & 0xFF

    def _send_command(self, command_code, data_bytes=b'\xFF\xFF\xFF\xFF'):
        """Формує та відправляє команду на модуль."""
        frame_header = b'\x55\xAA'
        command_payload = bytes([command_code]) + data_bytes
        checksum = self._calculate_checksum(command_payload)
        full_command = frame_header + command_payload + bytes([checksum])
        self.ser.write(full_command)

    def _read_response(self):
        """Читає та перевіряє 8-байтову відповідь від модуля."""
        response = self.ser.read(8)
        if len(response) != 8:
            return None

        # Перевірка заголовка
        if response[0:2] != b'\x55\xAA':
            print("Помилка: Неправильний заголовок відповіді.")
            return None

        # Перевірка контрольної суми (без байта статусу [3])
        payload_for_checksum = response[2:3] + response[4:7]
        received_checksum = response[7]
        calculated_checksum = self._calculate_checksum(payload_for_checksum)

        if received_checksum != calculated_checksum:
            print(f"Помилка: Неправильна контрольна сума. "
                  f"Отримано: {received_checksum}, Розраховано: {calculated_checksum}")
            return None

        return response

    # --- Одиночне вимірювання ---
    def get_single_measurement(self):
        """
        Виконує одиночне вимірювання та повертає дистанцію (мін, макс) у метрах.
        """
        self._send_command(0x88)  # команда одиночного вимірювання
        response = self._read_response()

        if response is None:
            return None

        status = response[3]
        if status == 0x01:
            data_h = response[5]
            data_l = response[6]
            distance_raw = (data_h << 8) | data_l
            distance_meters = distance_raw / 10.0

            # похибка
            error = 1.0 if distance_meters <= 400 else distance_meters * 0.003

            return distance_meters - error
            
        else:
            print("Помилка вимірювання від модуля.")
            return None

    # --- Безперервне вимірювання ---
    def start_continuous_measurement(self):
        """Запускає безперервний режим вимірювань на пристрої."""
        self._send_command(0x89)
        resp = self._read_response() # Читаємо відповідь, щоб очистити буфер
        if resp and resp[2] == 0x89:
            print("▶ Continuous mode запущено")

    def stop_continuous_measurement(self):
        """Зупиняє безперервний режим вимірювань."""
        self._send_command(0x8E)
        resp = self._read_response()
        if resp and resp[2] == 0x8E:
            print("▶ Continuous mode зупинено")

    # --- Закриття ---
    def close(self):
        """Закриває серійний порт та очищує GPIO."""
        if self.ser.is_open:
            self.ser.close()
        self.power_off()
        GPIO.cleanup()
        print("Ресурси очищено.")
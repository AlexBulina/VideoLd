import serial
import time
import RPi.GPIO as GPIO

class LRF:
    """
    Клас для взаємодії з лазерним далекоміром PTYS-20X через UART.
    """

    # Константи режимів
    SINGLE = 0
    CONTINUOUS = 1

    def __init__(self, port='/dev/ttyAMA0', baudrate=115200, enable_pin=17, mode=CONTINUOUS):
        """
        Ініціалізація LRF.
        :param port: UART порт (за замовчуванням /dev/ttyAMA0 для Raspberry Pi).
        :param baudrate: Швидкість передачі (115200).
        :param enable_pin: GPIO пін для ввімкнення/вимкнення модуля (UART_ON).
        :param mode: Режим роботи (SINGLE або CONTINUOUS).
        """
        self.port = port
        self.baudrate = baudrate
        self.enable_pin = enable_pin
        self.mode = mode
        self.measurements = None  # генератор для continuous

        # Налаштування GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.enable_pin, GPIO.OUT)
        GPIO.setwarnings(False)

        # Ініціалізація серійного порту
        try:
            self.ser = serial.Serial(
                self.port,
                self.baudrate,
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

            return distance_meters - error, distance_meters + error
        else:
            print("Помилка вимірювання від модуля.")
            return None

    # --- Безперервне вимірювання ---
    def start_continuous_measurement(self):
        """Запускає безперервний режим вимірювань і створює генератор."""
        self._send_command(0x89)

        def generator():
            while True:
                response = self._read_response()
                if response is None:
                    yield None
                    continue

                status = response[3]
                if status == 0x01:  # успіх
                    data_h = response[5]
                    data_l = response[6]
                    distance_raw = (data_h << 8) | data_l
                    distance_meters = distance_raw / 10.0

                    error = 1.0 if distance_meters <= 400 else distance_meters * 0.003
                    yield distance_meters - error, distance_meters + error
                else:
                    yield None

        self.measurements = generator()

    def stop_continuous_measurement(self):
        """Зупиняє безперервний режим вимірювань."""
        self._send_command(0x8E)
        resp = self._read_response()
        if resp and resp[2] == 0x8E:
            print("▶ Continuous mode зупинено")
        self.measurements = None

    # --- Закриття ---
    def close(self):
        """Закриває серійний порт та очищує GPIO."""
        if self.ser.is_open:
            self.ser.close()
        self.power_off()
        GPIO.cleanup()
        print("Ресурси очищено.")


# --- Приклад використання ---
if __name__ == '__main__':
    # змінюй mode=LRF.SINGLE або mode=LRF.CONTINUOUS
    lrf_sensor = LRF(port='/dev/ttyAMA0', enable_pin=17, mode=LRF.CONTINUOUS)

    try:
        lrf_sensor.power_on()

        if lrf_sensor.mode == LRF.SINGLE:
            for i in range(1):
                result = lrf_sensor.get_single_measurement()
                if result:
                    min_d, max_d = result
                    print(f"✅ Відстань: {min_d:.1f} – {max_d:.1f} м")
                else:
                    print("❌ Помилка вимірювання")
                time.sleep(1)

        elif lrf_sensor.mode == LRF.CONTINUOUS:
            print("▶ Читання continuous вимірювань (Ctrl+C для виходу)")
            try:
                for dist_range in lrf_sensor.measurements:
                    if dist_range:
                        min_d, max_d = dist_range
                        print(f"✅ Відстань: {min_d:.1f} – {max_d:.1f} м")
                    else:
                        print("❌ Немає даних")
                    time.sleep(0.5)
            except KeyboardInterrupt:
                print("\nЗупинка continuous mode...")
                lrf_sensor.stop_continuous_measurement()

    finally:
        lrf_sensor.close()

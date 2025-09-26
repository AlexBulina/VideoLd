# wifi_hotspot.py
import os
from http.server import SimpleHTTPRequestHandler, HTTPServer
import threading

class WifiHotspotServer:
    def __init__(self, ssid="PiHotspot", password="12345678", folder="download", port=8000):
        self.ssid = ssid
        self.password = password
        self.folder = folder
        self.port = port
        self.http_thread = None
        self.httpd = None

    def start_hotspot(self):
        """Створює Wi-Fi хотспот через NetworkManager"""
        print(f"Запуск хотспоту '{self.ssid}' з паролем '{self.password}'...")
        os.system(f"nmcli device wifi hotspot ifname wlan0 con-name {self.ssid} ssid {self.ssid} password {self.password}")
        print("Hotspot запущено")

    def stop_hotspot(self):
        """Зупиняє хотспот"""
        os.system(f"nmcli connection down {self.ssid}")
        print("Hotspot зупинено")

    def start_http_server(self):
        """Запускає HTTP сервер для папки з відео"""
        if not os.path.exists(self.folder):
            os.makedirs(self.folder)
        os.chdir(self.folder)

        self.httpd = HTTPServer(("", self.port), SimpleHTTPRequestHandler)
        print(f"HTTP сервер запущено на http://<Pi_IP>:{self.port} (папка: {self.folder})")

        # Запускаємо сервер у окремому потоці, щоб не блокувати основний цикл
        self.http_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.http_thread.start()

    def stop_http_server(self):
        """Зупиняє HTTP сервер"""
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            print("HTTP сервер зупинено")

    def start_all(self):
        """Запуск хотспоту та HTTP сервера"""
        self.start_hotspot()
        self.start_http_server()

    def stop_all(self):
        """Зупинка всього"""
        self.stop_http_server()
        self.stop_hotspot()

import psutil
import time
import socket
import platform
from datetime import datetime

class SystemMonitor:
    def __init__(self):
        self.boot_time = datetime.fromtimestamp(psutil.boot_time())
        self.os_info = f"{platform.system()} {platform.release()}"
        self.hostname = socket.gethostname()

    def get_uptime_str(self) -> str:
        delta = datetime.now() - self.boot_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"

    def get_metrics(self) -> dict:
        """Returns instantaneous system health telemetry."""
        cpu_pct = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        cpu_ghz = round(cpu_freq.current / 1000, 2) if cpu_freq else 0.0

        mem = psutil.virtual_memory()
        ram_pct = mem.percent
        ram_used_gb = round(mem.used / (1024 ** 3), 1)
        ram_total_gb = round(mem.total / (1024 ** 3), 1)

        disk = psutil.disk_usage("C:")
        disk_pct = disk.percent
        disk_free_gb = round(disk.free / (1024 ** 3), 1)
        disk_total_gb = round(disk.total / (1024 ** 3), 1)

        battery = psutil.sensors_battery()
        battery_pct = round(battery.percent, 1) if battery else None
        battery_plugged = battery.power_plugged if battery else True

        # Network check
        net_io = psutil.net_io_counters()

        return {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "hostname": self.hostname,
            "os": self.os_info,
            "uptime": self.get_uptime_str(),
            "cpu_percent": cpu_pct,
            "cpu_ghz": cpu_ghz,
            "cpu_cores": cpu_count,
            "ram_percent": ram_pct,
            "ram_used_gb": ram_used_gb,
            "ram_total_gb": ram_total_gb,
            "disk_percent": disk_pct,
            "disk_free_gb": disk_free_gb,
            "disk_total_gb": disk_total_gb,
            "battery_percent": battery_pct,
            "battery_plugged": battery_plugged,
            "net_sent_mb": round(net_io.bytes_sent / (1024 ** 2), 1),
            "net_recv_mb": round(net_io.bytes_recv / (1024 ** 2), 1)
        }

    def get_status_speech(self) -> str:
        """Generates a natural spoken summary of the system status."""
        metrics = self.get_metrics()
        cpu = metrics["cpu_percent"]
        ram = metrics["ram_percent"]
        disk_free = metrics["disk_free_gb"]
        uptime = metrics["uptime"]

        speech = (
            f"Relatório de status do sistema, senhor: "
            f"Uso do processador em {int(cpu)} por cento. "
            f"Memória RAM operando em {int(ram)} por cento de capacidade. "
            f"Espaço livre no disco principal de {disk_free} gigabytes. "
            f"Tempo de atividade atual é de {uptime}."
        )
        return speech

system_monitor = SystemMonitor()

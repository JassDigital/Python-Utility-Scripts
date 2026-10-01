"""
JASS System Inspector v1.0
A lightweight Windows system-information dashboard built with PySide6.

No third-party system-information libraries are required.
Uses Windows commands and Python's standard library where practical.

Features:
- Windows/system overview
- CPU and RAM information
- Storage overview
- Network adapters
- Python / Git / Node / npm / PowerShell / Docker / Ollama detection
- Live CPU/RAM usage
- Refresh
- Copy diagnostics
- Export TXT and JSON reports
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget
)


APP_NAME = "JASS System Inspector"
VERSION = "1.0"


def run_command(command: list[str], timeout: int = 4) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def command_version(command: str, args: list[str] | None = None) -> str:
    path = shutil.which(command)
    if not path:
        return "Not installed"

    output = run_command([path] + (args or ["--version"]))
    if not output:
        return f"Installed\n{path}"

    first = output.splitlines()[0].strip()
    return f"{first}\n{path}"


def powershell(command: str) -> str:
    return run_command(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
    )


def format_bytes(value: int | float) -> str:
    value = float(value)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    for unit in units:
        if abs(value) < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def get_memory() -> dict:
    # Windows WMI/CIM gives reliable physical-memory figures without psutil.
    output = powershell(
        "(Get-CimInstance Win32_OperatingSystem | "
        "Select-Object TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json -Compress)"
    )
    try:
        data = json.loads(output)
        total_kb = int(data["TotalVisibleMemorySize"])
        free_kb = int(data["FreePhysicalMemory"])
        total = total_kb * 1024
        free = free_kb * 1024
        used = max(0, total - free)
        percent = (used / total * 100) if total else 0
        return {
            "total": total,
            "free": free,
            "used": used,
            "percent": percent,
        }
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {"total": 0, "free": 0, "used": 0, "percent": 0}


def get_cpu_usage() -> float | None:
    output = powershell(
        "(Get-Counter '\\Processor(_Total)\\% Processor Time').CounterSamples[0].CookedValue"
    )
    try:
        return float(output)
    except (TypeError, ValueError):
        return None


def get_cpu_info() -> dict:
    output = powershell(
        "Get-CimInstance Win32_Processor | "
        "Select-Object -First 1 Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed | "
        "ConvertTo-Json -Compress"
    )
    try:
        data = json.loads(output)
        return {
            "name": data.get("Name", "Unknown"),
            "cores": data.get("NumberOfCores", "Unknown"),
            "threads": data.get("NumberOfLogicalProcessors", "Unknown"),
            "clock": data.get("MaxClockSpeed", 0),
        }
    except Exception:
        return {
            "name": platform.processor() or "Unknown",
            "cores": os.cpu_count() or "Unknown",
            "threads": os.cpu_count() or "Unknown",
            "clock": 0,
        }


def get_gpu() -> str:
    output = powershell(
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json -Compress"
    )
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            data = [data]
        lines = []
        for item in data:
            name = item.get("Name", "Unknown")
            driver = item.get("DriverVersion", "")
            ram = item.get("AdapterRAM")
            ram_text = format_bytes(ram) if isinstance(ram, int) and ram else ""
            extra = " • ".join(x for x in [ram_text, driver] if x)
            lines.append(f"{name}" + (f"\n{extra}" if extra else ""))
        return "\n".join(lines) if lines else "Not detected"
    except Exception:
        return "Not detected"


def get_drives() -> list[dict]:
    drives = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{letter}:\\")
        if not root.exists():
            continue
        try:
            usage = shutil.disk_usage(root)
            used = usage.total - usage.free
            percent = used / usage.total * 100 if usage.total else 0
            drives.append({
                "drive": f"{letter}:",
                "total": usage.total,
                "free": usage.free,
                "used": used,
                "percent": percent,
            })
        except OSError:
            pass
    return drives


def get_network() -> list[dict]:
    output = powershell(
        "Get-NetAdapter | Where-Object Status -ne 'Disabled' | "
        "Select-Object Name,Status,LinkSpeed,MacAddress | "
        "ConvertTo-Json -Compress"
    )
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            data = [data]
        return data or []
    except Exception:
        return []


def get_system_info() -> dict:
    mem = get_memory()
    cpu = get_cpu_info()

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "windows": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "hostname": socket.gethostname(),
            "username": os.environ.get("USERNAME", ""),
        },
        "cpu": cpu,
        "memory": mem,
        "gpu": get_gpu(),
        "drives": get_drives(),
        "network": get_network(),
        "development": {
            "Python": command_version("python", ["--version"]),
            "Git": command_version("git", ["--version"]),
            "Node.js": command_version("node", ["--version"]),
            "npm": command_version("npm", ["--version"]),
            "PowerShell": command_version("powershell", ["$PSVersionTable.PSVersion.ToString()"]),
            "Docker": command_version("docker", ["--version"]),
            "Ollama": command_version("ollama", ["--version"]),
        },
    }


def flatten_report(info: dict) -> str:
    lines = [
        f"{APP_NAME} v{VERSION}",
        "=" * 70,
        f"Generated: {info['timestamp']}",
        "",
        "SYSTEM",
        "-" * 70,
    ]

    for key, value in info["windows"].items():
        lines.append(f"{key.title():18}: {value}")

    cpu = info["cpu"]
    lines += [
        "",
        "CPU",
        "-" * 70,
        f"Name               : {cpu['name']}",
        f"Cores              : {cpu['cores']}",
        f"Logical processors  : {cpu['threads']}",
    ]

    if cpu.get("clock"):
        lines.append(f"Max clock           : {cpu['clock']} MHz")

    mem = info["memory"]
    lines += [
        "",
        "MEMORY",
        "-" * 70,
        f"Installed           : {format_bytes(mem['total'])}",
        f"Used                : {format_bytes(mem['used'])}",
        f"Available           : {format_bytes(mem['free'])}",
        f"Usage               : {mem['percent']:.1f}%",
        "",
        "GPU",
        "-" * 70,
        info["gpu"],
        "",
        "STORAGE",
        "-" * 70,
    ]

    for drive in info["drives"]:
        lines.append(
            f"{drive['drive']:5}  "
            f"{format_bytes(drive['used'])} used / "
            f"{format_bytes(drive['total'])}  "
            f"({drive['percent']:.1f}%)  "
            f"free {format_bytes(drive['free'])}"
        )

    lines += ["", "NETWORK", "-" * 70]

    for adapter in info["network"]:
        lines.append(
            f"{adapter.get('Name', '')}  |  "
            f"{adapter.get('Status', '')}  |  "
            f"{adapter.get('LinkSpeed', '')}  |  "
            f"{adapter.get('MacAddress', '')}"
        )

    lines += ["", "DEVELOPMENT ENVIRONMENT", "-" * 70]

    for name, value in info["development"].items():
        lines.append(f"{name}:")
        lines.append(f"  {value}")

    return "\n".join(lines)


class InfoCard(QFrame):
    def __init__(self, title: str, value: str):
        super().__init__()
        self.setObjectName("InfoCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(7)

        title_label = QLabel(title.upper())
        title_label.setObjectName("CardTitle")
        layout.addWidget(title_label)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("CardValue")
        self.value_label.setWordWrap(True)
        layout.addWidget(self.value_label)

    def set_value(self, value: str):
        self.value_label.setText(value)


class SystemInspector(QMainWindow):
    def __init__(self):
        super().__init__()

        self.info = {}
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1250, 820)
        self.setMinimumSize(950, 650)

        self.build_ui()
        self.apply_theme()
        self.refresh()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_live)
        self.timer.start(3000)

    def build_ui(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(17)

        header = QHBoxLayout()

        title_box = QVBoxLayout()
        title = QLabel("JASS System Inspector")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "A lightweight diagnostic view of your Windows machine."
        )
        subtitle.setObjectName("PageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        header.addLayout(title_box)
        header.addStretch()

        refresh = QPushButton("↻  Refresh")
        refresh.setObjectName("PrimaryButton")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)

        export = QPushButton("Export Report")
        export.setObjectName("SecondaryButton")
        export.clicked.connect(self.export_report)
        header.addWidget(export)

        copy = QPushButton("Copy Diagnostics")
        copy.setObjectName("SecondaryButton")
        copy.clicked.connect(self.copy_report)
        header.addWidget(copy)

        layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        self.grid = QGridLayout(content)
        self.grid.setContentsMargins(2, 2, 2, 25)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(14)

        self.system_card = InfoCard("System", "")
        self.cpu_card = InfoCard("CPU", "")
        self.memory_card = InfoCard("Memory", "")
        self.gpu_card = InfoCard("Graphics", "")
        self.storage_card = InfoCard("Storage", "")
        self.network_card = InfoCard("Network", "")
        self.dev_card = InfoCard("Development Environment", "")

        self.grid.addWidget(self.system_card, 0, 0)
        self.grid.addWidget(self.cpu_card, 0, 1)
        self.grid.addWidget(self.memory_card, 1, 0)
        self.grid.addWidget(self.gpu_card, 1, 1)
        self.grid.addWidget(self.storage_card, 2, 0)
        self.grid.addWidget(self.network_card, 2, 1)
        self.grid.addWidget(self.dev_card, 3, 0, 1, 2)

        self.scroll.setWidget(content)
        layout.addWidget(self.scroll, 1)

        self.statusBar().showMessage("Ready")

    def refresh(self):
        self.info = get_system_info()
        self.render()
        self.statusBar().showMessage(
            f"Updated {datetime.now().strftime('%H:%M:%S')}"
        )

    def update_live(self):
        if not self.info:
            return

        usage = get_cpu_usage()
        mem = get_memory()

        if usage is not None:
            cpu = self.info.get("cpu", {})
            cpu_text = (
                f"{cpu.get('name', 'Unknown')}\n"
                f"Cores: {cpu.get('cores', '?')}  •  "
                f"Threads: {cpu.get('threads', '?')}\n"
                f"Live usage: {usage:.1f}%"
            )
            self.cpu_card.set_value(cpu_text)

        self.memory_card.set_value(
            f"Installed: {format_bytes(mem['total'])}\n"
            f"Used: {format_bytes(mem['used'])}  •  "
            f"Available: {format_bytes(mem['free'])}\n"
            f"Live usage: {mem['percent']:.1f}%"
        )

    def render(self):
        windows = self.info["windows"]
        cpu = self.info["cpu"]
        mem = self.info["memory"]

        self.system_card.set_value(
            f"{windows['system']} {windows['release']}\n"
            f"Version: {windows['version']}\n"
            f"Machine: {windows['hostname']}\n"
            f"Architecture: {windows['machine']}\n"
            f"User: {windows['username']}"
        )

        self.cpu_card.set_value(
            f"{cpu['name']}\n"
            f"Cores: {cpu['cores']}  •  Threads: {cpu['threads']}\n"
            f"Max clock: {cpu.get('clock', 0)} MHz"
        )

        self.memory_card.set_value(
            f"Installed: {format_bytes(mem['total'])}\n"
            f"Used: {format_bytes(mem['used'])}  •  "
            f"Available: {format_bytes(mem['free'])}\n"
            f"Usage: {mem['percent']:.1f}%"
        )

        self.gpu_card.set_value(self.info["gpu"])

        storage_lines = []
        for drive in self.info["drives"]:
            storage_lines.append(
                f"{drive['drive']}   "
                f"{format_bytes(drive['total'])}   "
                f"{drive['percent']:.1f}% used   "
                f"{format_bytes(drive['free'])} free"
            )
        self.storage_card.set_value(
            "\n".join(storage_lines) if storage_lines else "No drives detected"
        )

        network_lines = []
        for adapter in self.info["network"]:
            network_lines.append(
                f"{adapter.get('Name', 'Unknown')}  •  "
                f"{adapter.get('Status', '')}\n"
                f"{adapter.get('LinkSpeed', '')}  •  "
                f"{adapter.get('MacAddress', '')}"
            )
        self.network_card.set_value(
            "\n".join(network_lines) if network_lines else "No active adapters detected"
        )

        dev_lines = []
        for name, value in self.info["development"].items():
            first = value.splitlines()[0] if value else "Not installed"
            dev_lines.append(f"{name:14}  {first}")
        self.dev_card.set_value("\n".join(dev_lines))

    def report_text(self) -> str:
        return flatten_report(self.info)

    def copy_report(self):
        QApplication.clipboard().setText(self.report_text())
        self.statusBar().showMessage("Diagnostics copied to clipboard")

    def export_report(self):
        default = f"JASS_System_Diagnostics_{datetime.now():%Y-%m-%d_%H%M%S}.txt"
        path, selected = QFileDialog.getSaveFileName(
            self,
            "Export System Diagnostics",
            default,
            "Text Report (*.txt);;JSON Report (*.json)"
        )

        if not path:
            return

        try:
            if path.lower().endswith(".json"):
                Path(path).write_text(
                    json.dumps(self.info, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
            else:
                Path(path).write_text(
                    self.report_text(),
                    encoding="utf-8"
                )

            QMessageBox.information(
                self,
                "Report Exported",
                f"System diagnostics saved to:\n\n{path}"
            )
        except OSError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))

    def apply_theme(self):
        self.setStyleSheet("""
        * {
            font-family: "Segoe UI", Arial;
        }

        QMainWindow, QWidget#Root {
            background: #0d1117;
        }

        QLabel#PageTitle {
            color: #f4f8fb;
            font-size: 28px;
            font-weight: 750;
        }

        QLabel#PageSubtitle {
            color: #74889b;
            font-size: 13px;
        }

        QFrame#InfoCard {
            background: #111a23;
            border: 1px solid #22313e;
            border-radius: 12px;
            min-height: 125px;
        }

        QFrame#InfoCard:hover {
            border-color: #31566a;
        }

        QLabel#CardTitle {
            color: #55cbe9;
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 1px;
        }

        QLabel#CardValue {
            color: #dbe6ed;
            font-size: 13px;
            line-height: 1.4;
        }

        QPushButton#PrimaryButton {
            background: #174b61;
            color: #72ddff;
            border: 1px solid #28647d;
            border-radius: 8px;
            padding: 9px 15px;
            font-weight: 700;
        }

        QPushButton#PrimaryButton:hover {
            background: #1e5d76;
            color: #ffffff;
        }

        QPushButton#SecondaryButton {
            background: #151f29;
            color: #9db0bf;
            border: 1px solid #293946;
            border-radius: 8px;
            padding: 9px 15px;
        }

        QPushButton#SecondaryButton:hover {
            background: #1d2b37;
            color: #ffffff;
        }

        QScrollBar:vertical {
            background: #0d1117;
            width: 10px;
        }

        QScrollBar::handle:vertical {
            background: #263744;
            border-radius: 5px;
            min-height: 35px;
        }

        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 0;
        }

        QStatusBar {
            background: #0b1015;
            color: #607487;
            border-top: 1px solid #1c2731;
        }
        """)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("JASS")

    window = SystemInspector()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

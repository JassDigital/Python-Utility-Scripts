import sys
import os
import json
import csv
import subprocess
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QThread, QObject, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QComboBox, QFileDialog, QCheckBox,
    QAbstractItemView, QProgressBar, QDialog, QDialogButtonBox
)

APP_NAME = "JASS Windows Startup Manager"
APP_VERSION = "1.0"
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "JASS" / "StartupManager"
DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

STYLE = """
QWidget {
    background:#11151b; color:#e7edf5;
    font-family:"Segoe UI"; font-size:10pt;
}
QMainWindow { background:#0d1117; }
QLabel#Title { font-size:22pt; font-weight:700; color:#ffffff; }
QLabel#SubTitle { color:#8d99a8; }
QLineEdit,QComboBox,QTableWidget {
    background:#171c23; border:1px solid #303947;
    border-radius:7px; padding:7px; color:#e7edf5;
}
QComboBox QAbstractItemView {
    background:#171c23; color:#e7edf5;
    selection-background-color:#263d59;
}
QPushButton {
    background:#202936; border:1px solid #354254;
    border-radius:7px; padding:8px 13px;
}
QPushButton:hover { background:#293545; }
QPushButton#Primary {
    background:#245b8f; border-color:#347ab9; font-weight:700;
}
QPushButton#Danger { background:#44252a; border-color:#67353c; }
QTableWidget { gridline-color:#252d38; selection-background-color:#263d59; }
QHeaderView::section {
    background:#1c232d; color:#aeb9c7; padding:7px; border:0;
}
QProgressBar {
    background:#171c23; border:1px solid #303947;
    border-radius:6px; height:16px; text-align:center;
}
QProgressBar::chunk { background:#347ab9; border-radius:5px; }
QCheckBox { spacing:8px; }
"""

def ps_json(script):
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-Command", script
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "PowerShell command failed.")
    out = p.stdout.strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else [data]

def startup_folder_entries():
    result = []
    folders = [
        ("Startup Folder (User)", os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup")),
        ("Startup Folder (All Users)", os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs\Startup")),
    ]
    for source, folder in folders:
        p = Path(folder)
        if not p.exists():
            continue
        try:
            for item in p.iterdir():
                result.append({
                    "name": item.stem,
                    "command": str(item),
                    "path": str(item),
                    "source": source,
                    "status": "Enabled",
                    "type": "Startup Folder",
                    "can_toggle": False,
                })
        except OSError:
            pass
    return result

def registry_entries():
    script = r"""
$roots = @(
 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run',
 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run'
)
$out = @()
foreach ($root in $roots) {
  if (Test-Path $root) {
    $source = if ($root -like 'HKCU:*') { 'Registry (Current User)' } else { 'Registry (Local Machine)' }
    $p = Get-ItemProperty $root
    foreach ($prop in $p.PSObject.Properties) {
      if ($prop.Name -notmatch '^PS') {
        $out += [PSCustomObject]@{
          Name = [string]$prop.Name
          Command = [string]$prop.Value
          Path = $root
          Source = $source
          Status = 'Enabled'
          Type = 'Registry Run'
          CanToggle = $true
        }
      }
    }
  }
}
$out | ConvertTo-Json -Depth 4
"""
    return ps_json(script)

def task_entries():
    script = r"""
$items = @()
try {
  Get-ScheduledTask | ForEach-Object {
    $task = $_
    $triggers = $task.Triggers
    foreach ($trigger in $triggers) {
      if ($trigger.Enabled -and $trigger.TriggerType -eq 'Logon') {
        $items += [PSCustomObject]@{
          Name = $task.TaskName
          Command = (($task.Actions | ForEach-Object { $_.Execute + ' ' + $_.Arguments }) -join ' | ').Trim()
          Path = $task.TaskPath
          Source = 'Task Scheduler (Logon)'
          Status = if ($task.State -eq 'Disabled') { 'Disabled' } else { 'Enabled' }
          Type = 'Scheduled Task'
          CanToggle = $true
        }
        break
      }
    }
  }
} catch {}
$items | ConvertTo-Json -Depth 5
"""
    return ps_json(script)

class ScanWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    @Slot()
    def run(self):
        try:
            entries = []
            entries.extend(registry_entries())
            entries.extend(startup_folder_entries())
            entries.extend(task_entries())
            self.finished.emit(entries)
        except Exception as e:
            self.failed.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1320, 780)
        self.setMinimumSize(1000, 620)
        self.setStyleSheet(STYLE)
        self.entries = []
        self.filtered = []
        self.thread = None
        self.worker = None
        self.build_ui()
        self.scan()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20,18,20,15)
        root.setSpacing(11)

        title = QLabel(APP_NAME)
        title.setObjectName("Title")
        sub = QLabel("Inspect Windows startup locations and safely manage supported startup entries.")
        sub.setObjectName("SubTitle")
        root.addWidget(title)
        root.addWidget(sub)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search startup items, commands or locations…")
        self.search.textChanged.connect(self.apply_filter)
        bar.addWidget(self.search, 1)

        self.source = QComboBox()
        self.source.addItems(["All sources", "Registry", "Startup Folder", "Scheduled Task"])
        self.source.currentTextChanged.connect(self.apply_filter)
        bar.addWidget(self.source)

        refresh = QPushButton("Refresh")
        refresh.setObjectName("Primary")
        refresh.clicked.connect(self.scan)
        bar.addWidget(refresh)

        backup = QPushButton("Backup")
        backup.clicked.connect(self.backup_startup)
        bar.addWidget(backup)

        export = QPushButton("Export")
        export.clicked.connect(self.export_csv)
        bar.addWidget(export)
        root.addLayout(bar)

        self.progress = QProgressBar()
        self.progress.setRange(0,0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Startup Item","Status","Source","Type","Command","Location","Manage"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.status = QLabel("Scanning startup locations…")
        self.status.setObjectName("SubTitle")
        bottom.addWidget(self.status, 1)
        openloc = QPushButton("Open Selected Location")
        openloc.clicked.connect(self.open_selected_location)
        bottom.addWidget(openloc)
        details = QPushButton("Details")
        details.clicked.connect(self.show_details)
        bottom.addWidget(details)
        root.addLayout(bottom)

    def scan(self):
        if self.thread and self.thread.isRunning():
            return
        self.progress.setVisible(True)
        self.status.setText("Reading Windows startup locations…")
        self.thread = QThread()
        self.worker = ScanWorker()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.scan_finished)
        self.worker.failed.connect(self.scan_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.scan_done)
        self.thread.start()

    def scan_done(self):
        self.progress.setVisible(False)
        self.worker = None
        self.thread = None

    def scan_failed(self, msg):
        self.progress.setVisible(False)
        self.status.setText("Scan failed.")
        QMessageBox.critical(self, "Startup Scan Error", msg)

    def scan_finished(self, entries):
        self.entries = entries
        self.apply_filter()
        self.status.setText(f"{len(entries)} startup entries found.")

    def apply_filter(self):
        text = self.search.text().strip().lower()
        source = self.source.currentText()
        self.filtered = []
        for e in self.entries:
            source_ok = (
                source == "All sources" or
                (source == "Registry" and e["type"] == "Registry Run") or
                (source == "Startup Folder" and e["type"] == "Startup Folder") or
                (source == "Scheduled Task" and e["type"] == "Scheduled Task")
            )
            hay = " ".join(str(e.get(k,"")) for k in
                           ("name","command","path","source","type","status")).lower()
            if source_ok and (not text or text in hay):
                self.filtered.append(e)

        self.table.setRowCount(0)
        for e in self.filtered:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                e["name"], e["status"], e["source"], e["type"],
                e["command"], e["path"], ""
            ]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(val)))
            if e.get("can_toggle"):
                btn = QPushButton("Disable")
                btn.clicked.connect(lambda checked=False, entry=e: self.toggle_entry(entry))
                self.table.setCellWidget(row, 6, btn)
            else:
                item = QTableWidgetItem("View only")
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, 6, item)
        self.status.setText(f"{len(self.filtered)} shown • {len(self.entries)} total")

    def selected_entry(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.filtered):
            return None
        return self.filtered[row]

    def toggle_entry(self, entry):
        if entry["type"] == "Registry Run":
            self.toggle_registry(entry)
        elif entry["type"] == "Scheduled Task":
            self.toggle_task(entry)

    def toggle_registry(self, entry):
        # Conservative approach: move the value between Run and StartupApproved.
        # Windows itself may use StartupApproved for UI state, so we preserve the
        # original Run value in a JASS backup and ask before changing anything.
        QMessageBox.information(
            self, "Registry Startup Entry",
            "This v1.0 build keeps registry entries read-only.\n\n"
            "Use Backup and Details to inspect the item. "
            "A future version can add reversible enable/disable controls "
            "with a dedicated backup/restore workflow."
        )

    def toggle_task(self, entry):
        reply = QMessageBox.question(
            self, "Disable Startup Task",
            f"Disable this logon task?\n\n{entry['name']}\n{entry['command']}",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        script = f"Disable-ScheduledTask -TaskName {json.dumps(entry['name'])} -TaskPath {json.dumps(entry['path'])} | Out-Null"
        try:
            subprocess.run(
                ["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command",script],
                check=True, capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.scan()
        except Exception as e:
            QMessageBox.critical(self, "Task Error", str(e))

    def open_selected_location(self):
        e = self.selected_entry()
        if not e:
            return
        try:
            if e["type"] == "Startup Folder":
                target = e["path"]
            elif e["type"] == "Scheduled Task":
                subprocess.run(["explorer.exe", "shell:AppsFolder"], check=False)
                return
            else:
                target = e["path"]
            if target.startswith("HK"):
                subprocess.run(["regedit.exe"], check=False)
            else:
                subprocess.run(["explorer.exe", "/select,", target], check=False)
        except Exception as ex:
            QMessageBox.warning(self, "Open Location", str(ex))

    def show_details(self):
        e = self.selected_entry()
        if not e:
            QMessageBox.information(self, "Details", "Select a startup item first.")
            return
        text = (
            f"Name: {e['name']}\n\n"
            f"Status: {e['status']}\n"
            f"Source: {e['source']}\n"
            f"Type: {e['type']}\n\n"
            f"Command:\n{e['command']}\n\n"
            f"Location:\n{e['path']}"
        )
        QMessageBox.information(self, "Startup Item Details", text)

    def backup_startup(self):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = BACKUP_DIR / f"startup_backup_{stamp}.json"
        data = {
            "created": datetime.now().isoformat(timespec="seconds"),
            "computer": os.environ.get("COMPUTERNAME", ""),
            "entries": self.entries
        }
        try:
            out.write_text(json.dumps(data, indent=2), encoding="utf-8")
            QMessageBox.information(self, "Backup Created", f"Backup saved to:\n{out}")
        except Exception as e:
            QMessageBox.critical(self, "Backup Error", str(e))

    def export_csv(self):
        if not self.entries:
            QMessageBox.information(self, "Export", "No startup entries to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Startup Report", "JASS_Startup_Report.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["Name","Status","Source","Type","Command","Location"])
                for e in self.entries:
                    w.writerow([
                        e["name"], e["status"], e["source"], e["type"],
                        e["command"], e["path"]
                    ])
            QMessageBox.information(self, "Export Complete", f"Report saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

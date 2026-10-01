# JASS Folder Snapshot & Compare v1.0
import sys, os, json, csv, hashlib, subprocess
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFileDialog, QComboBox, QProgressBar, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QGroupBox, QSplitter,
    QListWidget, QListWidgetItem, QAbstractItemView, QTabWidget
)

APP_NAME = "JASS Folder Snapshot & Compare"
APP_VERSION = "1.0"
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "JASS" / "FolderSnapshotCompare"
SNAP_DIR = DATA_DIR / "snapshots"
SNAP_DIR.mkdir(parents=True, exist_ok=True)

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "build", "dist"}

STYLE = """
QWidget {
    background: #11151b;
    color: #e8edf3;
    font-family: Segoe UI;
    font-size: 10pt;
}
QMainWindow { background: #0d1117; }
QLabel#Title { font-size: 22pt; font-weight: 700; color: #ffffff; }
QLabel#SubTitle { color: #8e9aaa; font-size: 10pt; }
QGroupBox {
    border: 1px solid #29313d;
    border-radius: 10px;
    margin-top: 10px;
    padding: 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #aeb9c7;
}
QLineEdit, QComboBox, QListWidget, QTableWidget {
    background: #171c23;
    border: 1px solid #303947;
    border-radius: 7px;
    padding: 7px;
    color: #e8edf3;
}
QComboBox QAbstractItemView {
    background: #171c23;
    color: #e8edf3;
    selection-background-color: #263d59;
}
QPushButton {
    background: #202936;
    border: 1px solid #354254;
    border-radius: 7px;
    padding: 8px 14px;
    color: #e8edf3;
}
QPushButton:hover { background: #293545; }
QPushButton#Primary {
    background: #245b8f;
    border-color: #347ab9;
    font-weight: 700;
}
QPushButton#Primary:hover { background: #2d6da7; }
QPushButton#Danger { background: #44252a; border-color: #67353c; }
QProgressBar {
    background: #171c23;
    border: 1px solid #303947;
    border-radius: 6px;
    text-align: center;
    height: 16px;
}
QProgressBar::chunk { background: #347ab9; border-radius: 5px; }
QHeaderView::section {
    background: #1c232d;
    color: #aeb9c7;
    padding: 7px;
    border: 0;
    border-bottom: 1px solid #303947;
}
QTableWidget {
    gridline-color: #252d38;
    selection-background-color: #263d59;
}
QTabWidget::pane { border: 1px solid #29313d; border-radius: 7px; }
QTabBar::tab {
    background: #171c23;
    padding: 8px 15px;
    border: 1px solid #29313d;
    margin-right: 2px;
}
QTabBar::tab:selected { background: #263d59; }
"""

def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def safe_stat(path):
    try:
        st = path.stat()
        return st.st_size, st.st_mtime_ns
    except (OSError, PermissionError):
        return None, None

class ScanWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, root, mode):
        super().__init__()
        self.root = Path(root)
        self.mode = mode
        self.cancelled = False

    @Slot()
    def run(self):
        try:
            files = []
            for base, dirs, names in os.walk(self.root):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for name in names:
                    p = Path(base) / name
                    try:
                        rel = p.relative_to(self.root).as_posix()
                    except ValueError:
                        continue
                    files.append((p, rel))

            total = len(files)
            entries = {}
            total_size = 0

            for i, (p, rel) in enumerate(files, 1):
                if self.cancelled:
                    return
                size, mtime_ns = safe_stat(p)
                if size is None:
                    continue
                item = {"size": size, "mtime_ns": mtime_ns}
                total_size += size
                if self.mode == "sha256":
                    try:
                        item["sha256"] = sha256_file(p)
                    except (OSError, PermissionError):
                        item["sha256"] = None
                entries[rel] = item
                pct = int(i * 100 / total) if total else 100
                self.progress.emit(pct, rel)

            result = {
                "root": str(self.root),
                "created": datetime.now().isoformat(timespec="seconds"),
                "mode": self.mode,
                "file_count": len(entries),
                "total_size": total_size,
                "files": entries,
            }
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1250, 800)
        self.setMinimumSize(950, 620)
        self.setStyleSheet(STYLE)
        self.thread = None
        self.worker = None
        self.current_snapshot = None
        self.compare_result = None
        self.build_ui()
        self.load_snapshots()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 15)
        root.setSpacing(12)

        title = QLabel(APP_NAME)
        title.setObjectName("Title")
        subtitle = QLabel("Create read-only folder fingerprints and see exactly what changed.")
        subtitle.setObjectName("SubTitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        source = QGroupBox("Folder")
        sl = QHBoxLayout(source)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Choose a folder to snapshot or compare…")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.choose_folder)
        sl.addWidget(self.folder_edit, 1)
        sl.addWidget(browse)
        root.addWidget(source)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Scan mode:"))
        self.mode = QComboBox()
        self.mode.addItem("Fast — filename + size + modified time", "fast")
        self.mode.addItem("SHA-256 Verify — content fingerprint", "sha256")
        controls.addWidget(self.mode, 1)

        self.create_btn = QPushButton("Create Snapshot")
        self.create_btn.setObjectName("Primary")
        self.create_btn.clicked.connect(self.create_snapshot)
        controls.addWidget(self.create_btn)

        self.compare_btn = QPushButton("Compare With Snapshot")
        self.compare_btn.clicked.connect(self.compare_snapshot)
        controls.addWidget(self.compare_btn)

        export = QPushButton("Export Report")
        export.clicked.connect(self.export_report)
        controls.addWidget(export)
        root.addLayout(controls)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        root.addWidget(self.progress)
        self.status = QLabel("Ready.")
        self.status.setObjectName("SubTitle")
        root.addWidget(self.status)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Saved Snapshots"))
        self.snapshot_list = QListWidget()
        self.snapshot_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.snapshot_list.itemSelectionChanged.connect(self.snapshot_selected)
        ll.addWidget(self.snapshot_list, 1)
        self.delete_btn = QPushButton("Delete Selected Snapshot")
        self.delete_btn.setObjectName("Danger")
        self.delete_btn.clicked.connect(self.delete_snapshot)
        ll.addWidget(self.delete_btn)
        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        self.stats = QHBoxLayout()
        self.stat_labels = {}
        for key in ("Files", "New", "Deleted", "Modified", "Unchanged", "Renamed"):
            box = QGroupBox(key)
            lay = QVBoxLayout(box)
            lab = QLabel("0")
            lab.setAlignment(Qt.AlignCenter)
            lab.setFont(QFont("Segoe UI", 16, QFont.Bold))
            lay.addWidget(lab)
            self.stat_labels[key] = lab
            self.stats.addWidget(box)
        rl.addLayout(self.stats)

        self.tabs = QTabWidget()
        self.tables = {}
        for key in ("New", "Deleted", "Modified", "Renamed", "Unchanged"):
            table = QTableWidget(0, 3)
            table.setHorizontalHeaderLabels(["Path", "Size", "Details"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.tables[key] = table
            self.tabs.addTab(table, key)
        rl.addWidget(self.tabs, 1)
        splitter.addWidget(right)
        splitter.setSizes([320, 900])
        root.addWidget(splitter, 1)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.folder_edit.setText(folder)

    def snapshot_path(self, item):
        return Path(item.data(Qt.UserRole))

    def load_snapshots(self):
        self.snapshot_list.clear()
        for p in sorted(SNAP_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                text = f"{data.get('created','?')}  |  {Path(data.get('root','')).name or data.get('root','')}"
                item = QListWidgetItem(text)
                item.setToolTip(data.get("root", ""))
                item.setData(Qt.UserRole, str(p))
                self.snapshot_list.addItem(item)
            except Exception:
                continue

    def snapshot_selected(self):
        item = self.snapshot_list.currentItem()
        if not item:
            return
        try:
            self.current_snapshot = json.loads(self.snapshot_path(item).read_text(encoding="utf-8"))
            self.folder_edit.setText(self.current_snapshot.get("root", ""))
            self.status.setText(
                f"Snapshot loaded: {self.current_snapshot.get('file_count', 0):,} files • "
                f"{human_size(self.current_snapshot.get('total_size', 0))} • "
                f"{self.current_snapshot.get('mode', 'fast')}"
            )
        except Exception as e:
            QMessageBox.warning(self, "Snapshot Error", str(e))

    def start_scan(self, mode, callback):
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, "Busy", "A scan is already running.")
            return
        root = self.folder_edit.text().strip()
        if not root or not Path(root).is_dir():
            QMessageBox.warning(self, "Folder Required", "Please select a valid folder.")
            return

        self.create_btn.setEnabled(False)
        self.compare_btn.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText("Scanning…")
        self.thread = QThread()
        self.worker = ScanWorker(root, mode)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(lambda pct, name: self.scan_progress(pct, name))
        self.worker.finished.connect(callback)
        self.worker.failed.connect(self.scan_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.scan_done)
        self.thread.start()

    def scan_progress(self, pct, name):
        self.progress.setValue(pct)
        self.status.setText(f"Scanning {pct}% • {name}")

    def scan_done(self):
        self.create_btn.setEnabled(True)
        self.compare_btn.setEnabled(True)
        self.worker = None
        self.thread = None

    def scan_failed(self, message):
        QMessageBox.critical(self, "Scan Error", message)
        self.status.setText("Scan failed.")

    def create_snapshot(self):
        mode = self.mode.currentData()
        self.start_scan(mode, self.snapshot_created)

    def snapshot_created(self, data):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = SNAP_DIR / f"snapshot_{stamp}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.current_snapshot = data
        self.load_snapshots()
        self.progress.setValue(100)
        self.status.setText(
            f"Snapshot created: {data['file_count']:,} files • {human_size(data['total_size'])}"
        )
        QMessageBox.information(self, "Snapshot Created",
                                f"Snapshot saved.\n\nFiles: {data['file_count']:,}\n"
                                f"Total size: {human_size(data['total_size'])}")

    def compare_snapshot(self):
        if not self.current_snapshot:
            item = self.snapshot_list.currentItem()
            if item:
                self.snapshot_selected()
        if not self.current_snapshot:
            QMessageBox.information(self, "Select Snapshot",
                                    "Select a saved snapshot first.")
            return
        mode = self.mode.currentData()
        snap_mode = self.current_snapshot.get("mode", "fast")
        if mode != snap_mode:
            reply = QMessageBox.question(
                self, "Scan Mode",
                f"The selected snapshot was created in {snap_mode.upper()} mode, "
                f"but the current mode is {mode.upper()}.\n\n"
                "Continue anyway?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        self.start_scan(mode, self.comparison_finished)

    def comparison_finished(self, current):
        old = self.current_snapshot.get("files", {})
        new = current.get("files", {})
        added = sorted(set(new) - set(old))
        deleted = sorted(set(old) - set(new))
        common = set(old) & set(new)
        modified = []
        unchanged = []

        mode = current.get("mode", "fast")
        for path in sorted(common):
            a, b = old[path], new[path]
            if mode == "sha256" and a.get("sha256") and b.get("sha256"):
                same = a.get("sha256") == b.get("sha256")
            else:
                same = (a.get("size") == b.get("size") and
                        a.get("mtime_ns") == b.get("mtime_ns"))
            (unchanged if same else modified).append(path)

        renamed = []
        if mode == "sha256":
            old_deleted = {p: old[p].get("sha256") for p in deleted if old[p].get("sha256")}
            new_added = {p: new[p].get("sha256") for p in added if new[p].get("sha256")}
            used_new = set()
            for op, oh in old_deleted.items():
                for np, nh in new_added.items():
                    if np not in used_new and oh == nh:
                        renamed.append((op, np))
                        used_new.add(np)
                        break
            renamed_old = {x[0] for x in renamed}
            renamed_new = {x[1] for x in renamed}
            deleted = [x for x in deleted if x not in renamed_old]
            added = [x for x in added if x not in renamed_new]

        self.compare_result = {
            "root": current["root"],
            "snapshot_created": self.current_snapshot.get("created"),
            "compared": current["created"],
            "files": len(new),
            "new": added,
            "deleted": deleted,
            "modified": modified,
            "unchanged": unchanged,
            "renamed": renamed,
            "current": current,
        }
        self.populate_results()
        self.progress.setValue(100)
        self.status.setText(
            f"Comparison complete • {len(added)} new • {len(deleted)} deleted • "
            f"{len(modified)} modified • {len(renamed)} renamed"
        )

    def populate_results(self):
        r = self.compare_result
        self.stat_labels["Files"].setText(f"{r['files']:,}")
        for k in ("New", "Deleted", "Modified", "Unchanged", "Renamed"):
            self.stat_labels[k].setText(f"{len(r[k.lower()]):,}")

        for key in self.tables:
            self.tables[key].setRowCount(0)

        for path in r["new"]:
            self.add_row("New", path, r["current"]["files"].get(path, {}), "Added")
        for path in r["deleted"]:
            self.add_row("Deleted", path, self.current_snapshot["files"].get(path, {}), "Removed")
        for path in r["modified"]:
            self.add_row("Modified", path, r["current"]["files"].get(path, {}), "Changed")
        for path in r["unchanged"]:
            self.add_row("Unchanged", path, r["current"]["files"].get(path, {}), "No change")
        for old, new in r["renamed"]:
            table = self.tables["Renamed"]
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(new))
            table.setItem(row, 1, QTableWidgetItem(human_size(r["current"]["files"][new]["size"])))
            table.setItem(row, 2, QTableWidgetItem(f"From: {old}"))

    def add_row(self, category, path, info, detail):
        table = self.tables[category]
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(path))
        table.setItem(row, 1, QTableWidgetItem(human_size(info.get("size", 0))))
        table.setItem(row, 2, QTableWidgetItem(detail))

    def delete_snapshot(self):
        item = self.snapshot_list.currentItem()
        if not item:
            return
        reply = QMessageBox.question(self, "Delete Snapshot",
                                     "Delete the selected snapshot file?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            self.snapshot_path(item).unlink()
            self.current_snapshot = None
            self.load_snapshots()
            self.status.setText("Snapshot deleted.")
        except Exception as e:
            QMessageBox.warning(self, "Delete Error", str(e))

    def export_report(self):
        if not self.compare_result:
            QMessageBox.information(self, "Nothing to Export",
                                    "Run a comparison first.")
            return
        path, selected = QFileDialog.getSaveFileName(
            self, "Export Report", "", "JSON (*.json);;CSV (*.csv);;Text (*.txt)"
        )
        if not path:
            return
        try:
            r = self.compare_result
            if path.lower().endswith(".json"):
                Path(path).write_text(json.dumps(r, indent=2, default=str), encoding="utf-8")
            elif path.lower().endswith(".csv"):
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f)
                    w.writerow(["Status", "Path", "Size", "Details"])
                    for p in r["new"]:
                        w.writerow(["New", p, r["current"]["files"][p]["size"], "Added"])
                    for p in r["deleted"]:
                        w.writerow(["Deleted", p, self.current_snapshot["files"][p]["size"], "Removed"])
                    for p in r["modified"]:
                        w.writerow(["Modified", p, r["current"]["files"][p]["size"], "Changed"])
                    for p in r["unchanged"]:
                        w.writerow(["Unchanged", p, r["current"]["files"][p]["size"], "No change"])
                    for old, new in r["renamed"]:
                        w.writerow(["Renamed", new, r["current"]["files"][new]["size"], f"From: {old}"])
            else:
                lines = [
                    "JASS Folder Snapshot & Compare Report",
                    f"Folder: {r['root']}",
                    f"Snapshot: {r['snapshot_created']}",
                    f"Compared: {r['compared']}",
                    "",
                    f"Files: {r['files']}",
                    f"New: {len(r['new'])}",
                    f"Deleted: {len(r['deleted'])}",
                    f"Modified: {len(r['modified'])}",
                    f"Unchanged: {len(r['unchanged'])}",
                    f"Renamed: {len(r['renamed'])}",
                    "",
                    "=== NEW ===", *r["new"],
                    "",
                    "=== DELETED ===", *r["deleted"],
                    "",
                    "=== MODIFIED ===", *r["modified"],
                    "",
                    "=== RENAMED ===",
                ]
                lines += [f"{old}  ->  {new}" for old, new in r["renamed"]]
                Path(path).write_text("\n".join(lines), encoding="utf-8")
            self.status.setText(f"Report exported: {path}")
            QMessageBox.information(self, "Export Complete", f"Report saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

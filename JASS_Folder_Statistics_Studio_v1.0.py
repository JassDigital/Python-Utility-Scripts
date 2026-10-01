import sys, os, csv, json
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFileDialog, QComboBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QTabWidget,
    QAbstractItemView
)

APP_NAME = "JASS Folder Statistics Studio"
APP_VERSION = "1.0"

STYLE = """
QWidget { background:#11151b; color:#e7edf5; font-family:"Segoe UI"; font-size:10pt; }
QMainWindow { background:#0d1117; }
QLabel#Title { font-size:22pt; font-weight:700; color:#fff; }
QLabel#SubTitle { color:#8d99a8; }
QLineEdit,QComboBox,QTableWidget {
    background:#171c23; border:1px solid #303947; border-radius:7px;
    padding:7px; color:#e7edf5;
}
QComboBox QAbstractItemView { background:#171c23; color:#e7edf5; selection-background-color:#263d59; }
QPushButton {
    background:#202936; border:1px solid #354254; border-radius:7px; padding:8px 13px;
}
QPushButton:hover { background:#293545; }
QPushButton#Primary { background:#245b8f; border-color:#347ab9; font-weight:700; }
QTableWidget { gridline-color:#252d38; selection-background-color:#263d59; }
QHeaderView::section { background:#1c232d; color:#aeb9c7; padding:7px; border:0; }
QProgressBar {
    background:#171c23; border:1px solid #303947; border-radius:6px;
    height:16px; text-align:center;
}
QProgressBar::chunk { background:#347ab9; border-radius:5px; }
"""

SKIP = {".git", "__pycache__", ".venv", "venv", "node_modules", "build", "dist"}

def human(n):
    n = float(n)
    for u in ("B","KB","MB","GB","TB"):
        if n < 1024 or u == "TB":
            return f"{int(n)} B" if u == "B" else f"{n:.1f} {u}"
        n /= 1024

class StatsWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, root, include_hidden=True):
        super().__init__()
        self.root = Path(root)
        self.include_hidden = include_hidden
        self.cancelled = False

    @Slot()
    def run(self):
        try:
            ext_counts = {}
            ext_sizes = {}
            folder_counts = {}
            folder_sizes = {}
            largest = []
            total_files = 0
            total_dirs = 0
            total_size = 0
            hidden_files = 0
            hidden_dirs = 0
            errors = 0

            all_dirs = []
            for base, dirs, files in os.walk(self.root):
                dirs[:] = [d for d in dirs if d not in SKIP]
                all_dirs.append(Path(base))
                for name in files:
                    p = Path(base) / name
                    if not self.include_hidden and name.startswith("."):
                        continue
                    try:
                        size = p.stat().st_size
                    except (OSError, PermissionError):
                        errors += 1
                        continue
                    total_files += 1
                    total_size += size
                    ext = p.suffix.lower() or "[no extension]"
                    ext_counts[ext] = ext_counts.get(ext, 0) + 1
                    ext_sizes[ext] = ext_sizes.get(ext, 0) + size
                    rel_parent = p.parent.relative_to(self.root).as_posix()
                    if rel_parent == ".":
                        rel_parent = "[root]"
                    folder_counts[rel_parent] = folder_counts.get(rel_parent, 0) + 1
                    folder_sizes[rel_parent] = folder_sizes.get(rel_parent, 0) + size
                    largest.append((size, p.relative_to(self.root).as_posix()))
                    if name.startswith("."):
                        hidden_files += 1

                pct = min(99, int((total_files % 10000) / 100))
                self.progress.emit(pct, str(Path(base).relative_to(self.root) if Path(base) != self.root else "[root]"))

            total_dirs = max(0, len(all_dirs) - 1)
            for d in all_dirs:
                if d.name.startswith("."):
                    hidden_dirs += 1

            largest.sort(reverse=True)
            result = {
                "root": str(self.root),
                "created": datetime.now().isoformat(timespec="seconds"),
                "total_files": total_files,
                "total_dirs": total_dirs,
                "total_size": total_size,
                "hidden_files": hidden_files,
                "hidden_dirs": hidden_dirs,
                "errors": errors,
                "extensions": [
                    {"extension": k, "files": ext_counts[k], "size": ext_sizes[k]}
                    for k in sorted(ext_counts, key=lambda x: ext_sizes[x], reverse=True)
                ],
                "folders": [
                    {"folder": k, "files": folder_counts[k], "size": folder_sizes[k]}
                    for k in sorted(folder_counts, key=lambda x: folder_sizes[x], reverse=True)
                ],
                "largest": [
                    {"path": p, "size": s} for s, p in largest[:100]
                ],
            }
            self.progress.emit(100, "Complete")
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1350, 820)
        self.setMinimumSize(1000, 650)
        self.setStyleSheet(STYLE)
        self.result = None
        self.thread = None
        self.worker = None
        self.build_ui()

    def build_ui(self):
        c = QWidget()
        self.setCentralWidget(c)
        root = QVBoxLayout(c)
        root.setContentsMargins(20,18,20,15)
        root.setSpacing(11)

        title = QLabel(APP_NAME)
        title.setObjectName("Title")
        sub = QLabel("Analyze folder size, file types, directory usage and largest files.")
        sub.setObjectName("SubTitle")
        root.addWidget(title); root.addWidget(sub)

        bar = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("Choose a folder…")
        bar.addWidget(self.folder, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.choose)
        bar.addWidget(browse)

        self.hidden = QComboBox()
        self.hidden.addItem("Include hidden files", True)
        self.hidden.addItem("Skip hidden files", False)
        bar.addWidget(self.hidden)

        scan = QPushButton("Analyze")
        scan.setObjectName("Primary")
        scan.clicked.connect(self.start)
        bar.addWidget(scan)

        export = QPushButton("Export")
        export.clicked.connect(self.export)
        bar.addWidget(export)
        root.addLayout(bar)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        root.addWidget(self.progress)
        self.status = QLabel("Ready.")
        self.status.setObjectName("SubTitle")
        root.addWidget(self.status)

        stats = QHBoxLayout()
        self.cards = {}
        for key in ("Files","Folders","Total Size","Largest File","Errors"):
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(12,8,12,8)
            lab1 = QLabel(key); lab1.setObjectName("SubTitle")
            lab2 = QLabel("0"); lab2.setFont(QFont("Segoe UI",16,QFont.Bold))
            bl.addWidget(lab1); bl.addWidget(lab2)
            box.setStyleSheet("QWidget{background:#171c23;border:1px solid #29313d;border-radius:9px;}")
            stats.addWidget(box)
            self.cards[key] = lab2
        root.addLayout(stats)

        self.tabs = QTabWidget()
        self.ext_table = self.make_table(["Extension","Files","Size","Share"])
        self.folder_table = self.make_table(["Folder","Files","Size","Share"])
        self.large_table = self.make_table(["Relative Path","Size"])
        self.tabs.addTab(self.ext_table, "File Types")
        self.tabs.addTab(self.folder_table, "Folders")
        self.tabs.addTab(self.large_table, "Largest Files")
        root.addWidget(self.tabs, 1)

    def make_table(self, headers):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(headers)):
            t.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        return t

    def choose(self):
        p = QFileDialog.getExistingDirectory(self, "Select Folder")
        if p: self.folder.setText(p)

    def start(self):
        if self.thread and self.thread.isRunning(): return
        p = self.folder.text().strip()
        if not p or not Path(p).is_dir():
            QMessageBox.warning(self, "Folder Required", "Please select a valid folder.")
            return
        self.progress.setValue(0)
        self.status.setText("Analyzing folder…")
        self.thread = QThread()
        self.worker = StatsWorker(p, self.hidden.currentData())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.finished)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.done)
        self.thread.start()

    def update_progress(self, pct, name):
        self.progress.setValue(pct)
        self.status.setText(f"Scanning: {name}")

    def done(self):
        self.worker = None
        self.thread = None

    def failed(self, msg):
        QMessageBox.critical(self, "Analysis Error", msg)
        self.status.setText("Analysis failed.")

    def finished(self, r):
        self.result = r
        self.cards["Files"].setText(f"{r['total_files']:,}")
        self.cards["Folders"].setText(f"{r['total_dirs']:,}")
        self.cards["Total Size"].setText(human(r["total_size"]))
        self.cards["Largest File"].setText(human(r["largest"][0]["size"]) if r["largest"] else "0 B")
        self.cards["Errors"].setText(str(r["errors"]))
        self.fill_tables()
        self.status.setText(
            f"Analysis complete • {r['total_files']:,} files • {human(r['total_size'])} • "
            f"{r['errors']} access errors"
        )

    def fill_tables(self):
        r = self.result
        total = r["total_size"] or 1
        self.ext_table.setRowCount(0)
        for x in r["extensions"]:
            row = self.ext_table.rowCount(); self.ext_table.insertRow(row)
            vals = [x["extension"], f"{x['files']:,}", human(x["size"]), f"{x['size']/total*100:.1f}%"]
            for c,v in enumerate(vals): self.ext_table.setItem(row,c,QTableWidgetItem(v))

        self.folder_table.setRowCount(0)
        for x in r["folders"]:
            row = self.folder_table.rowCount(); self.folder_table.insertRow(row)
            vals = [x["folder"], f"{x['files']:,}", human(x["size"]), f"{x['size']/total*100:.1f}%"]
            for c,v in enumerate(vals): self.folder_table.setItem(row,c,QTableWidgetItem(v))

        self.large_table.setRowCount(0)
        for x in r["largest"]:
            row = self.large_table.rowCount(); self.large_table.insertRow(row)
            self.large_table.setItem(row,0,QTableWidgetItem(x["path"]))
            self.large_table.setItem(row,1,QTableWidgetItem(human(x["size"])))

    def export(self):
        if not self.result:
            QMessageBox.information(self, "Export", "Run an analysis first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Statistics", "JASS_Folder_Statistics.json",
            "JSON (*.json);;CSV (*.csv);;Text (*.txt)"
        )
        if not path: return
        try:
            if path.lower().endswith(".json"):
                Path(path).write_text(json.dumps(self.result, indent=2), encoding="utf-8")
            elif path.lower().endswith(".csv"):
                with open(path,"w",newline="",encoding="utf-8-sig") as f:
                    w=csv.writer(f)
                    w.writerow(["Section","Name","Files","Size","Share"])
                    total=self.result["total_size"] or 1
                    for x in self.result["extensions"]:
                        w.writerow(["File Type",x["extension"],x["files"],x["size"],f"{x['size']/total*100:.1f}%"])
                    for x in self.result["folders"]:
                        w.writerow(["Folder",x["folder"],x["files"],x["size"],f"{x['size']/total*100:.1f}%"])
                    for x in self.result["largest"]:
                        w.writerow(["Largest File",x["path"],"",x["size"],""])
            else:
                r=self.result
                lines=[
                    "JASS Folder Statistics Studio Report",
                    f"Folder: {r['root']}", f"Created: {r['created']}", "",
                    f"Files: {r['total_files']:,}", f"Folders: {r['total_dirs']:,}",
                    f"Total size: {human(r['total_size'])}", f"Access errors: {r['errors']}", "",
                    "=== FILE TYPES ==="
                ]
                lines += [f"{x['extension']} | {x['files']:,} | {human(x['size'])}" for x in r["extensions"]]
                lines += ["","=== FOLDERS ==="]
                lines += [f"{x['folder']} | {x['files']:,} | {human(x['size'])}" for x in r["folders"]]
                lines += ["","=== LARGEST FILES ==="]
                lines += [f"{x['path']} | {human(x['size'])}" for x in r["largest"]]
                Path(path).write_text("\n".join(lines),encoding="utf-8")
            QMessageBox.information(self,"Export Complete",f"Report saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self,"Export Error",str(e))

if __name__ == "__main__":
    app=QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w=MainWindow(); w.show()
    sys.exit(app.exec())

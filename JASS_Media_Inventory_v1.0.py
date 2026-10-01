import sys, os, csv, json, subprocess, re
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

APP_NAME = "JASS Media Inventory"
APP_VERSION = "1.0"

MEDIA_TYPES = {
    "Images": {
        ".jpg",".jpeg",".png",".gif",".bmp",".tif",".tiff",".webp",".ico",".svg",".heic",".heif",".avif"
    },
    "Videos": {
        ".mp4",".mkv",".avi",".mov",".wmv",".webm",".m4v",".mpeg",".mpg",".ts",".m2ts",".3gp"
    },
    "Audio": {
        ".mp3",".wav",".flac",".aac",".m4a",".ogg",".oga",".wma",".opus",".mid",".midi"
    }
}

ALL_EXTENSIONS = set().union(*MEDIA_TYPES.values())
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "build", "dist"}

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

def human(n):
    n = float(n)
    for u in ("B","KB","MB","GB","TB"):
        if n < 1024 or u == "TB":
            return f"{int(n)} B" if u == "B" else f"{n:.1f} {u}"
        n /= 1024

def classify(ext):
    ext = ext.lower()
    for kind, exts in MEDIA_TYPES.items():
        if ext in exts:
            return kind
    return "Other"

def ffprobe_info(path):
    """Optional metadata via ffprobe if installed. Returns a compact dict."""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration,format_name:stream=codec_name,width,height,channels,sample_rate",
            "-of", "json", str(path)
        ]
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           creationflags=subprocess.CREATE_NO_WINDOW)
        if p.returncode != 0:
            return {}
        data = json.loads(p.stdout or "{}")
        out = {}
        fmt = data.get("format", {})
        if fmt.get("duration"):
            try:
                out["duration"] = float(fmt["duration"])
            except ValueError:
                pass
        if fmt.get("format_name"):
            out["format"] = fmt["format_name"]
        streams = data.get("streams", [])
        video = next((x for x in streams if "width" in x), None)
        audio = next((x for x in streams if "channels" in x), None)
        if video:
            out["codec"] = video.get("codec_name", "")
            out["width"] = video.get("width")
            out["height"] = video.get("height")
        elif audio:
            out["codec"] = audio.get("codec_name", "")
            out["channels"] = audio.get("channels")
            out["sample_rate"] = audio.get("sample_rate")
        return out
    except Exception:
        return {}

def duration_text(seconds):
    if seconds is None:
        return ""
    seconds = int(round(float(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

class MediaWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, root, include_other, metadata):
        super().__init__()
        self.root = Path(root)
        self.include_other = include_other
        self.metadata = metadata

    @Slot()
    def run(self):
        try:
            rows = []
            total_size = 0
            counts = {"Images":0, "Videos":0, "Audio":0, "Other":0}
            sizes = {"Images":0, "Videos":0, "Audio":0, "Other":0}
            errors = 0
            candidates = []

            for base, dirs, files in os.walk(self.root):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for name in files:
                    p = Path(base) / name
                    ext = p.suffix.lower()
                    kind = classify(ext)
                    if kind == "Other" and not self.include_other:
                        continue
                    candidates.append((p, kind))

            total = len(candidates)
            for i, (p, kind) in enumerate(candidates, 1):
                try:
                    st = p.stat()
                    size = st.st_size
                    modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                except (OSError, PermissionError):
                    errors += 1
                    continue

                rel = p.relative_to(self.root).as_posix()
                meta = ffprobe_info(p) if self.metadata and kind in ("Videos", "Audio") else {}

                row = {
                    "name": p.name,
                    "relative_path": rel,
                    "full_path": str(p),
                    "type": kind,
                    "extension": ext or "[none]",
                    "size": size,
                    "modified": modified,
                    "duration": meta.get("duration"),
                    "codec": meta.get("codec", ""),
                    "width": meta.get("width"),
                    "height": meta.get("height"),
                    "format": meta.get("format", ""),
                    "channels": meta.get("channels"),
                    "sample_rate": meta.get("sample_rate"),
                }
                rows.append(row)
                counts[kind] += 1
                sizes[kind] += size
                total_size += size

                pct = int(i * 100 / total) if total else 100
                self.progress.emit(pct, rel)

            result = {
                "root": str(self.root),
                "created": datetime.now().isoformat(timespec="seconds"),
                "total_media": len(rows),
                "total_size": total_size,
                "counts": counts,
                "sizes": sizes,
                "errors": errors,
                "ffprobe_metadata": bool(self.metadata),
                "items": rows
            }
            self.progress.emit(100, "Complete")
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1450, 830)
        self.setMinimumSize(1050, 650)
        self.setStyleSheet(STYLE)
        self.result = None
        self.thread = None
        self.worker = None
        self.filtered = []
        self.build_ui()

    def build_ui(self):
        c = QWidget()
        self.setCentralWidget(c)
        root = QVBoxLayout(c)
        root.setContentsMargins(20,18,20,15)
        root.setSpacing(11)

        title = QLabel(APP_NAME)
        title.setObjectName("Title")
        sub = QLabel("Catalog images, videos and audio files without modifying your media.")
        sub.setObjectName("SubTitle")
        root.addWidget(title)
        root.addWidget(sub)

        bar = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("Choose a media folder…")
        bar.addWidget(self.folder, 1)

        browse = QPushButton("Browse…")
        browse.clicked.connect(self.choose_folder)
        bar.addWidget(browse)

        self.kind = QComboBox()
        self.kind.addItems(["All Media", "Images", "Videos", "Audio"])
        self.kind.currentTextChanged.connect(self.apply_filter)
        bar.addWidget(self.kind)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search filename or path…")
        self.search.textChanged.connect(self.apply_filter)
        bar.addWidget(self.search, 1)

        self.metadata = QComboBox()
        self.metadata.addItem("Basic metadata", False)
        self.metadata.addItem("FFprobe metadata", True)
        bar.addWidget(self.metadata)

        scan = QPushButton("Scan Media")
        scan.setObjectName("Primary")
        scan.clicked.connect(self.start_scan)
        bar.addWidget(scan)

        export = QPushButton("Export")
        export.clicked.connect(self.export)
        bar.addWidget(export)
        root.addLayout(bar)

        self.progress = QProgressBar()
        root.addWidget(self.progress)
        self.status = QLabel("Ready.")
        self.status.setObjectName("SubTitle")
        root.addWidget(self.status)

        cards = QHBoxLayout()
        self.cards = {}
        for key in ("Media", "Images", "Videos", "Audio", "Total Size"):
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(12,8,12,8)
            a = QLabel(key); a.setObjectName("SubTitle")
            b = QLabel("0"); b.setFont(QFont("Segoe UI",16,QFont.Bold))
            lay.addWidget(a); lay.addWidget(b)
            box.setStyleSheet("QWidget{background:#171c23;border:1px solid #29313d;border-radius:9px;}")
            cards.addWidget(box)
            self.cards[key] = b
        root.addLayout(cards)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Name","Type","Extension","Size","Duration","Resolution",
            "Modified","Path"
        ])
        h = self.table.horizontalHeader()
        for i in (0,1,2,3,4,5,6):
            h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(7, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.doubleClicked.connect(self.open_selected)
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Double-click a media item to open it."))
        bottom.addStretch()
        open_folder = QPushButton("Open Selected Folder")
        open_folder.clicked.connect(self.open_selected_folder)
        bottom.addWidget(open_folder)
        root.addLayout(bottom)

    def choose_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Select Media Folder")
        if p:
            self.folder.setText(p)

    def start_scan(self):
        if self.thread and self.thread.isRunning():
            return
        p = self.folder.text().strip()
        if not p or not Path(p).is_dir():
            QMessageBox.warning(self, "Folder Required", "Please select a valid folder.")
            return
        self.progress.setValue(0)
        self.status.setText("Scanning media…")
        self.thread = QThread()
        self.worker = MediaWorker(
            p,
            True,
            self.metadata.currentData()
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.scan_finished)
        self.worker.failed.connect(self.scan_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.scan_done)
        self.thread.start()

    def update_progress(self, pct, name):
        self.progress.setValue(pct)
        self.status.setText(f"Scanning {pct}% • {name}")

    def scan_done(self):
        self.worker = None
        self.thread = None

    def scan_failed(self, msg):
        QMessageBox.critical(self, "Media Scan Error", msg)
        self.status.setText("Scan failed.")

    def scan_finished(self, result):
        self.result = result
        self.apply_filter()
        self.cards["Media"].setText(f"{result['total_media']:,}")
        self.cards["Images"].setText(f"{result['counts']['Images']:,}")
        self.cards["Videos"].setText(f"{result['counts']['Videos']:,}")
        self.cards["Audio"].setText(f"{result['counts']['Audio']:,}")
        self.cards["Total Size"].setText(human(result["total_size"]))
        self.status.setText(
            f"Scan complete • {result['total_media']:,} media files • "
            f"{human(result['total_size'])} • {result['errors']} access errors"
        )

    def apply_filter(self):
        if not self.result:
            return
        text = self.search.text().strip().lower()
        kind = self.kind.currentText()
        self.filtered = []
        for x in self.result["items"]:
            kind_ok = kind == "All Media" or x["type"] == kind
            hay = (x["name"] + " " + x["relative_path"]).lower()
            if kind_ok and (not text or text in hay):
                self.filtered.append(x)

        self.table.setRowCount(0)
        for x in self.filtered:
            row = self.table.rowCount()
            self.table.insertRow(row)
            resolution = ""
            if x.get("width") and x.get("height"):
                resolution = f"{x['width']} × {x['height']}"
            values = [
                x["name"], x["type"], x["extension"], human(x["size"]),
                duration_text(x.get("duration")), resolution,
                x["modified"], x["relative_path"]
            ]
            for c,v in enumerate(values):
                self.table.setItem(row,c,QTableWidgetItem(str(v)))

        self.status.setText(
            f"{len(self.filtered):,} shown • {self.result['total_media']:,} total"
        )

    def selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.filtered):
            return None
        return self.filtered[row]

    def open_selected(self):
        x = self.selected()
        if not x:
            return
        subprocess.run(["explorer.exe", x["full_path"]], check=False)

    def open_selected_folder(self):
        x = self.selected()
        if not x:
            return
        subprocess.run(["explorer.exe", "/select,", x["full_path"]], check=False)

    def export(self):
        if not self.result:
            QMessageBox.information(self, "Export", "Run a media scan first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Media Inventory",
            "JASS_Media_Inventory.json",
            "JSON (*.json);;CSV (*.csv);;Text (*.txt)"
        )
        if not path:
            return
        try:
            if path.lower().endswith(".json"):
                Path(path).write_text(
                    json.dumps(self.result, indent=2, default=str),
                    encoding="utf-8"
                )
            elif path.lower().endswith(".csv"):
                with open(path,"w",newline="",encoding="utf-8-sig") as f:
                    w=csv.writer(f)
                    w.writerow([
                        "Name","Type","Extension","Size","Duration",
                        "Width","Height","Codec","Format","Modified","Path"
                    ])
                    for x in self.result["items"]:
                        w.writerow([
                            x["name"],x["type"],x["extension"],x["size"],
                            duration_text(x.get("duration")),x.get("width",""),
                            x.get("height",""),x.get("codec",""),
                            x.get("format",""),x["modified"],x["full_path"]
                        ])
            else:
                r=self.result
                lines=[
                    "JASS Media Inventory Report",
                    f"Folder: {r['root']}",
                    f"Created: {r['created']}",
                    f"Media files: {r['total_media']:,}",
                    f"Total size: {human(r['total_size'])}",
                    f"Images: {r['counts']['Images']:,}",
                    f"Videos: {r['counts']['Videos']:,}",
                    f"Audio: {r['counts']['Audio']:,}",
                    f"Other: {r['counts']['Other']:,}",
                    f"Access errors: {r['errors']}",
                    ""
                ]
                for x in r["items"]:
                    details = []
                    if x.get("duration") is not None:
                        details.append(duration_text(x["duration"]))
                    if x.get("width") and x.get("height"):
                        details.append(f"{x['width']}x{x['height']}")
                    if x.get("codec"):
                        details.append(x["codec"])
                    lines.append(
                        f"{x['type']} | {x['name']} | {human(x['size'])} | "
                        f"{' | '.join(details)} | {x['full_path']}"
                    )
                Path(path).write_text("\n".join(lines),encoding="utf-8")
            QMessageBox.information(self,"Export Complete",f"Inventory saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self,"Export Error",str(e))

if __name__ == "__main__":
    app=QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w=MainWindow()
    w.show()
    sys.exit(app.exec())

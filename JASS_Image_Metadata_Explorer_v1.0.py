import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ExifTags
except ImportError:
    Image = None
    ExifTags = None

from PySide6.QtCore import Qt, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QLineEdit, QComboBox, QProgressBar, QMessageBox, QSplitter,
    QGroupBox, QFormLayout, QAbstractItemView, QHeaderView, QListWidget,
    QListWidgetItem
)

APP_NAME = "JASS Image Metadata Explorer"
VERSION = "1.0"

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp",
    ".bmp", ".gif", ".ico", ".heic", ".heif", ".avif"
}

TAG_NAMES = {}
if ExifTags:
    TAG_NAMES = {value: key for key, value in ExifTags.TAGS.items()}


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def safe_text(value):
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", "replace")
        except Exception:
            return repr(value)
    try:
        return str(value)
    except Exception:
        return repr(value)


def gps_to_decimal(value):
    try:
        d, m, s = value
        def ratio(x):
            return float(x[0]) / float(x[1]) if hasattr(x, "__len__") else float(x)
        return ratio(d) + ratio(m) / 60 + ratio(s) / 3600
    except Exception:
        return None


def extract_metadata(path):
    stat = os.stat(path)
    record = {
        "file": Path(path).name,
        "path": str(Path(path).resolve()),
        "extension": Path(path).suffix.lower(),
        "size": stat.st_size,
        "size_display": human_size(stat.st_size),
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "width": "",
        "height": "",
        "format": "",
        "mode": "",
        "camera_make": "",
        "camera_model": "",
        "date_taken": "",
        "lens": "",
        "iso": "",
        "aperture": "",
        "shutter": "",
        "focal_length": "",
        "orientation": "",
        "software": "",
        "gps": "",
        "metadata": {}
    }

    with Image.open(path) as im:
        record["width"] = im.width
        record["height"] = im.height
        record["format"] = im.format or ""
        record["mode"] = im.mode

        exif = im.getexif()
        if exif:
            for tag_id, value in exif.items():
                name = ExifTags.TAGS.get(tag_id, str(tag_id))
                record["metadata"][name] = safe_text(value)

            def get(name):
                tag = TAG_NAMES.get(name)
                return exif.get(tag, "") if tag is not None else ""

            record["camera_make"] = safe_text(get("Make"))
            record["camera_model"] = safe_text(get("Model"))
            record["date_taken"] = safe_text(
                get("DateTimeOriginal") or get("DateTimeDigitized") or get("DateTime")
            )
            record["lens"] = safe_text(get("LensModel") or get("LensMake"))
            record["iso"] = safe_text(get("ISOSpeedRatings") or get("PhotographicSensitivity"))
            record["aperture"] = safe_text(get("FNumber"))
            record["shutter"] = safe_text(get("ExposureTime"))
            record["focal_length"] = safe_text(get("FocalLength"))
            record["orientation"] = safe_text(get("Orientation"))
            record["software"] = safe_text(get("Software"))

            gps = exif.get(TAG_NAMES.get("GPSInfo"))
            if gps:
                try:
                    gps_named = {
                        ExifTags.GPSIFD.get(k, str(k)): v for k, v in gps.items()
                    }
                    lat = gps_named.get("GPSLatitude")
                    lon = gps_named.get("GPSLongitude")
                    lat_ref = safe_text(gps_named.get("GPSLatitudeRef", ""))
                    lon_ref = safe_text(gps_named.get("GPSLongitudeRef", ""))
                    lat_dec = gps_to_decimal(lat) if lat else None
                    lon_dec = gps_to_decimal(lon) if lon else None
                    if lat_dec is not None and lon_dec is not None:
                        if lat_ref.upper() == "S":
                            lat_dec = -lat_dec
                        if lon_ref.upper() == "W":
                            lon_dec = -lon_dec
                        record["gps"] = f"{lat_dec:.6f}, {lon_dec:.6f}"
                    else:
                        record["gps"] = safe_text(gps)
                except Exception:
                    record["gps"] = safe_text(gps)

    return record


class WorkerSignals(QObject):
    progress = Signal(int)
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, fn, *args):
        super().__init__()
        self.fn = fn
        self.args = args
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            self.signals.result.emit(self.fn(*self.args, signals=self.signals))
        except Exception as e:
            self.signals.error.emit(f"{type(e).__name__}: {e}")
        finally:
            self.signals.finished.emit()


def scan_folder(folder, signals):
    files = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = [
            d for d in dirs
            if d not in {".git", "__pycache__", ".venv", "venv", "node_modules"}
        ]
        for name in names:
            if Path(name).suffix.lower() in IMAGE_EXTENSIONS:
                files.append(os.path.join(root, name))

    records = []
    total = max(1, len(files))
    errors = []
    for i, path in enumerate(files, 1):
        try:
            records.append(extract_metadata(path))
        except Exception as e:
            errors.append((path, str(e)))
        signals.progress.emit(int(i * 100 / total))

    return records, errors


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1350, 820)
        self.records = []
        self.filtered = []
        self.threadpool = QThreadPool.globalInstance()
        self.worker = None
        self.build_ui()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        header = QHBoxLayout()
        title = QLabel("JASS Image Metadata Explorer")
        title.setObjectName("Title")
        subtitle = QLabel("Image inventory • EXIF • camera metadata")
        subtitle.setObjectName("Muted")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch()
        layout.addLayout(header)

        controls = QHBoxLayout()
        scan_btn = QPushButton("Scan Folder")
        scan_btn.clicked.connect(self.scan_folder)
        controls.addWidget(scan_btn)

        open_btn = QPushButton("Open Image")
        open_btn.clicked.connect(self.open_image)
        controls.addWidget(open_btn)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search filename, path, camera, date, lens, GPS...")
        self.search.textChanged.connect(self.apply_filter)
        controls.addWidget(self.search, 1)

        self.type_box = QComboBox()
        self.type_box.addItems(["All", "JPEG", "PNG", "TIFF", "WebP", "BMP", "GIF", "Other"])
        self.type_box.currentIndexChanged.connect(self.apply_filter)
        controls.addWidget(self.type_box)

        export_csv = QPushButton("Export CSV")
        export_csv.clicked.connect(self.export_csv)
        controls.addWidget(export_csv)

        export_json = QPushButton("Export JSON")
        export_json.clicked.connect(self.export_json)
        controls.addWidget(export_json)

        layout.addLayout(controls)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "File", "Type", "Size", "Dimensions", "Camera",
            "Date Taken", "Lens", "ISO", "GPS", "Path"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.show_details)
        ll.addWidget(self.table)
        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)

        preview_box = QGroupBox("Preview")
        pv = QVBoxLayout(preview_box)
        self.preview = QLabel("Select an image")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(220)
        self.preview.setWordWrap(True)
        pv.addWidget(self.preview)
        rl.addWidget(preview_box)

        details_box = QGroupBox("Metadata")
        form = QFormLayout(details_box)
        self.detail_labels = {}
        fields = [
            ("File", "file"), ("Path", "path"), ("Format", "format"),
            ("Dimensions", "dimensions"), ("Size", "size_display"),
            ("Modified", "modified"), ("Camera", "camera"),
            ("Date Taken", "date_taken"), ("Lens", "lens"),
            ("ISO", "iso"), ("Aperture", "aperture"),
            ("Shutter", "shutter"), ("Focal Length", "focal_length"),
            ("Orientation", "orientation"), ("Software", "software"),
            ("GPS", "gps")
        ]
        for label, key in fields:
            value = QLabel("-")
            value.setWordWrap(True)
            self.detail_labels[key] = value
            form.addRow(label + ":", value)
        rl.addWidget(details_box, 1)

        splitter.addWidget(right)
        splitter.setSizes([850, 500])
        layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.progress = QProgressBar()
        self.status = QLabel("Ready")
        self.status.setObjectName("Muted")
        self.count = QLabel("0 images")
        footer.addWidget(self.progress, 1)
        footer.addWidget(self.status)
        footer.addWidget(self.count)
        layout.addLayout(footer)

        self.setStyleSheet("""
            QWidget { background:#151922; color:#e8edf5; font-size:10.5pt; }
            QLabel#Title { font-size:20pt; font-weight:700; }
            QLabel#Muted { color:#8e9aaa; }
            QGroupBox { border:1px solid #303746; border-radius:8px;
                        margin-top:10px; padding:10px; }
            QGroupBox::title { subcontrol-origin:margin; left:10px;
                                padding:0 5px; color:#aeb9ca; }
            QPushButton,QComboBox,QLineEdit {
                background:#222938; border:1px solid #3a4354;
                border-radius:6px; padding:7px 10px;
            }
            QPushButton:hover { background:#2b3445; }
            QLineEdit { background:#10141c; }
            QTableWidget {
                background:#10141c; alternate-background-color:#171d28;
                border:1px solid #303746; gridline-color:#2b3342;
            }
            QTableWidget::item:selected { background:#294766; }
            QHeaderView::section {
                background:#222938; color:#dce5f2; border:0;
                border-right:1px solid #303746;
                border-bottom:1px solid #303746; padding:7px;
            }
            QProgressBar { border:1px solid #303746; border-radius:5px;
                           text-align:center; background:#10141c; }
            QProgressBar::chunk { background:#4d8dcc; border-radius:4px; }
        """)

    def scan_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if not folder:
            return
        self.progress.setValue(0)
        self.status.setText("Scanning...")
        self.worker = Worker(scan_folder, folder)
        self.worker.signals.progress.connect(self.progress.setValue)
        self.worker.signals.result.connect(self.scan_complete)
        self.worker.signals.error.connect(self.scan_error)
        self.worker.signals.finished.connect(self.worker_finished)
        self.threadpool.start(self.worker)

    def scan_complete(self, result):
        self.records, errors = result
        self.filtered = list(self.records)
        self.render()
        self.status.setText(
            f"Scan complete • {len(errors)} unreadable file(s)"
            if errors else "Scan complete"
        )
        if errors:
            self.status.setToolTip("\n".join(f"{p}: {e}" for p, e in errors))
        self.progress.setValue(100)

    def scan_error(self, message):
        self.status.setText("Scan failed")
        QMessageBox.critical(self, "Scan error", message)

    def worker_finished(self):
        self.worker = None

    def apply_filter(self):
        term = self.search.text().strip().lower()
        selected_type = self.type_box.currentText()

        def matches(record):
            hay = " ".join([
                record["file"], record["path"], record["camera_make"],
                record["camera_model"], record["date_taken"], record["lens"],
                record["gps"], record["software"]
            ]).lower()
            if term and term not in hay:
                return False
            if selected_type != "All":
                ext = record["extension"]
                mapping = {
                    "JPEG": {".jpg", ".jpeg"},
                    "PNG": {".png"},
                    "TIFF": {".tif", ".tiff"},
                    "WebP": {".webp"},
                    "BMP": {".bmp"},
                    "GIF": {".gif"},
                }
                allowed = mapping.get(selected_type)
                if allowed:
                    return ext in allowed
                if selected_type == "Other":
                    return ext not in {
                        ".jpg", ".jpeg", ".png", ".tif", ".tiff",
                        ".webp", ".bmp", ".gif"
                    }
            return True

        self.filtered = [r for r in self.records if matches(r)]
        self.render()

    def render(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.filtered))
        for r, record in enumerate(self.filtered):
            camera = " ".join(
                x for x in [record["camera_make"], record["camera_model"]] if x
            )
            values = [
                record["file"],
                record["extension"].lstrip(".").upper(),
                record["size_display"],
                f'{record["width"]} × {record["height"]}',
                camera,
                record["date_taken"],
                record["lens"],
                record["iso"],
                record["gps"],
                record["path"]
            ]
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        for c in range(self.table.columnCount()):
            if self.table.columnWidth(c) > 360:
                self.table.setColumnWidth(c, 360)
        self.table.setSortingEnabled(True)
        self.count.setText(f"{len(self.filtered):,} / {len(self.records):,} images")

    def selected_record(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.filtered):
            return None
        return self.filtered[row]

    def show_details(self):
        record = self.selected_record()
        if not record:
            return

        camera = " ".join(
            x for x in [record["camera_make"], record["camera_model"]] if x
        ) or "-"
        values = {
            "file": record["file"],
            "path": record["path"],
            "format": record["format"] or "-",
            "dimensions": f'{record["width"]} × {record["height"]}',
            "size_display": record["size_display"],
            "modified": record["modified"],
            "camera": camera,
            "date_taken": record["date_taken"] or "-",
            "lens": record["lens"] or "-",
            "iso": record["iso"] or "-",
            "aperture": record["aperture"] or "-",
            "shutter": record["shutter"] or "-",
            "focal_length": record["focal_length"] or "-",
            "orientation": record["orientation"] or "-",
            "software": record["software"] or "-",
            "gps": record["gps"] or "-"
        }
        for key, label in self.detail_labels.items():
            label.setText(values.get(key, "-"))

        try:
            pix = QPixmap(record["path"])
            if not pix.isNull():
                self.preview.setPixmap(
                    pix.scaled(
                        self.preview.size(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                )
            else:
                self.preview.setText("Preview unavailable")
        except Exception:
            self.preview.setText("Preview unavailable")

    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Image", "",
            "Images (*.jpg *.jpeg *.png *.tif *.tiff *.webp *.bmp *.gif *.ico);;All Files (*.*)"
        )
        if not path:
            return
        try:
            record = extract_metadata(path)
            self.records = [record]
            self.filtered = [record]
            self.render()
            self.table.selectRow(0)
            self.status.setText("Image loaded")
        except Exception as e:
            QMessageBox.critical(self, "Image error", str(e))

    def export_csv(self):
        if not self.filtered:
            QMessageBox.information(self, "Export", "There are no records to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Metadata CSV", "", "CSV Files (*.csv)"
        )
        if not path:
            return

        fields = [
            "file", "path", "extension", "size", "size_display", "modified",
            "width", "height", "format", "mode", "camera_make",
            "camera_model", "date_taken", "lens", "iso", "aperture",
            "shutter", "focal_length", "orientation", "software", "gps"
        ]
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                for record in self.filtered:
                    writer.writerow({k: record.get(k, "") for k in fields})
            QMessageBox.information(self, "Export", f"Exported {len(self.filtered):,} records.")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def export_json(self):
        if not self.filtered:
            QMessageBox.information(self, "Export", "There are no records to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Metadata JSON", "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.filtered, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Export", f"Exported {len(self.filtered):,} records.")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))


def main():
    if Image is None:
        app = QApplication(sys.argv)
        QMessageBox.critical(
            None, "Missing Pillow",
            "Pillow is required.\n\nInstall it with:\npy -m pip install Pillow"
        )
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

import csv
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

try:
    from ebooklib import epub
except ImportError:
    epub = None

from PySide6.QtCore import Qt, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QLineEdit, QComboBox, QProgressBar, QMessageBox, QSplitter,
    QGroupBox, QFormLayout, QAbstractItemView
)

APP_NAME = "JASS EPUB Library Manager"
VERSION = "1.0"

DB_DIR = Path(os.environ.get("APPDATA", Path.home())) / "JASS" / "EPUBLibraryManager"
DB_PATH = DB_DIR / "epub_library.db"

EPUB_EXTENSIONS = {".epub"}
OTHER_EBOOK_EXTENSIONS = {".mobi", ".azw", ".azw3"}


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def clean_text(value):
    if value is None:
        return ""
    return " ".join(str(value).replace("\x00", " ").split())


def metadata_value(book, namespace, key):
    try:
        values = book.get_metadata(namespace, key)
        if values:
            return clean_text(values[0][0])
    except Exception:
        pass
    return ""


def calculate_sha256(path, signals=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def extract_epub(path):
    if epub is None:
        raise RuntimeError(
            "EbookLib is not installed.\n\n"
            "Install it with:\n"
            "py -m pip install EbookLib"
        )

    book = epub.read_epub(path, options={"ignore_ncx": True})

    title = metadata_value(book, "DC", "title")
    author = metadata_value(book, "DC", "creator")
    publisher = metadata_value(book, "DC", "publisher")
    language = metadata_value(book, "DC", "language")
    date = metadata_value(book, "DC", "date")
    identifier = metadata_value(book, "DC", "identifier")
    description = metadata_value(book, "DC", "description")

    subjects = []
    try:
        for value, _attrs in book.get_metadata("DC", "subject"):
            value = clean_text(value)
            if value:
                subjects.append(value)
    except Exception:
        pass

    chapters = 0
    try:
        chapters = sum(
            1 for item in book.get_items_of_type(9)
            if getattr(item, "get_name", lambda: "")()
        )
    except Exception:
        try:
            chapters = len(list(book.get_items_of_type(9)))
        except Exception:
            chapters = 0

    cover_path = ""
    try:
        for item in book.get_items():
            name = item.get_name().lower()
            if "cover" in name and name.endswith((".jpg", ".jpeg", ".png", ".webp")):
                cover_path = item.get_name()
                break
    except Exception:
        pass

    stat = os.stat(path)

    return {
        "path": str(Path(path).resolve()),
        "file": Path(path).name,
        "extension": Path(path).suffix.lower(),
        "size": stat.st_size,
        "size_display": human_size(stat.st_size),
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "title": title,
        "author": author,
        "publisher": publisher,
        "language": language,
        "date": date,
        "identifier": identifier,
        "description": description,
        "subjects": "; ".join(subjects),
        "chapters": chapters,
        "cover": cover_path,
        "sha256": calculate_sha256(path),
    }


class Database:
    def __init__(self):
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                path TEXT PRIMARY KEY,
                file TEXT,
                extension TEXT,
                size INTEGER,
                size_display TEXT,
                modified TEXT,
                title TEXT,
                author TEXT,
                publisher TEXT,
                language TEXT,
                date TEXT,
                identifier TEXT,
                description TEXT,
                subjects TEXT,
                chapters INTEGER,
                cover TEXT,
                sha256 TEXT,
                scanned_at TEXT
            )
        """)
        self.conn.commit()

    def upsert(self, record):
        fields = [
            "path", "file", "extension", "size", "size_display", "modified",
            "title", "author", "publisher", "language", "date", "identifier",
            "description", "subjects", "chapters", "cover", "sha256"
        ]
        values = [record.get(k, "") for k in fields]
        self.conn.execute(
            f"""
            INSERT OR REPLACE INTO books
            ({','.join(fields)}, scanned_at)
            VALUES ({','.join(['?'] * len(fields))}, ?)
            """,
            values + [datetime.now().isoformat(timespec="seconds")]
        )
        self.conn.commit()

    def all(self):
        cur = self.conn.execute(
            "SELECT path,file,extension,size,size_display,modified,title,author,"
            "publisher,language,date,identifier,description,subjects,chapters,"
            "cover,sha256 FROM books ORDER BY title COLLATE NOCASE"
        )
        columns = [
            "path", "file", "extension", "size", "size_display", "modified",
            "title", "author", "publisher", "language", "date", "identifier",
            "description", "subjects", "chapters", "cover", "sha256"
        ]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    def close(self):
        self.conn.close()


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
            ext = Path(name).suffix.lower()
            if ext in EPUB_EXTENSIONS or ext in OTHER_EBOOK_EXTENSIONS:
                files.append(os.path.join(root, name))

    records = []
    errors = []
    total = max(1, len(files))

    for i, path in enumerate(files, 1):
        try:
            if Path(path).suffix.lower() == ".epub":
                records.append(extract_epub(path))
            else:
                stat = os.stat(path)
                records.append({
                    "path": str(Path(path).resolve()),
                    "file": Path(path).name,
                    "extension": Path(path).suffix.lower(),
                    "size": stat.st_size,
                    "size_display": human_size(stat.st_size),
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "title": Path(path).stem,
                    "author": "",
                    "publisher": "",
                    "language": "",
                    "date": "",
                    "identifier": "",
                    "description": "",
                    "subjects": "",
                    "chapters": 0,
                    "cover": "",
                    "sha256": calculate_sha256(path),
                })
        except Exception as e:
            errors.append((path, str(e)))
        signals.progress.emit(int(i * 100 / total))

    return records, errors


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1400, 820)
        self.db = Database()
        self.records = self.db.all()
        self.filtered = list(self.records)
        self.worker = None
        self.threadpool = QThreadPool.globalInstance()
        self.build_ui()
        self.render()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        header = QHBoxLayout()
        title = QLabel("JASS EPUB Library Manager")
        title.setObjectName("Title")
        subtitle = QLabel("EPUB library • metadata • covers • search")
        subtitle.setObjectName("Muted")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch()
        layout.addLayout(header)

        controls = QHBoxLayout()

        scan_btn = QPushButton("Scan Folder")
        scan_btn.clicked.connect(self.scan_folder)
        controls.addWidget(scan_btn)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search title, author, ISBN, subject, description...")
        self.search.textChanged.connect(self.apply_filter)
        controls.addWidget(self.search, 1)

        self.language_box = QComboBox()
        self.language_box.addItem("All Languages")
        self.language_box.currentIndexChanged.connect(self.apply_filter)
        controls.addWidget(self.language_box)

        self.sort_box = QComboBox()
        self.sort_box.addItems(["Title", "Author", "Date", "Size"])
        self.sort_box.currentIndexChanged.connect(self.render)
        controls.addWidget(self.sort_box)

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
        ll.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Title", "Author", "Language", "Date", "Chapters",
            "Size", "Type", "Path"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self.show_details)
        self.table.horizontalHeader().setStretchLastSection(True)
        ll.addWidget(self.table)
        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)

        preview_box = QGroupBox("Cover")
        pv = QVBoxLayout(preview_box)
        self.cover = QLabel("No cover selected")
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setMinimumHeight(250)
        self.cover.setWordWrap(True)
        pv.addWidget(self.cover)
        rl.addWidget(preview_box)

        details = QGroupBox("Book Details")
        form = QFormLayout(details)
        self.detail = {}
        for label, key in [
            ("Title", "title"), ("Author", "author"), ("Publisher", "publisher"),
            ("Language", "language"), ("Date", "date"), ("ISBN / ID", "identifier"),
            ("Subjects", "subjects"), ("Chapters", "chapters"),
            ("File", "file"), ("Size", "size_display"), ("SHA-256", "sha256"),
            ("Path", "path")
        ]:
            value = QLabel("-")
            value.setWordWrap(True)
            self.detail[key] = value
            form.addRow(label + ":", value)
        rl.addWidget(details, 1)

        self.open_btn = QPushButton("Open Ebook")
        self.open_btn.clicked.connect(self.open_selected)
        rl.addWidget(self.open_btn)

        splitter.addWidget(right)
        splitter.setSizes([900, 500])
        layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.progress = QProgressBar()
        self.status = QLabel("Ready")
        self.status.setObjectName("Muted")
        self.count = QLabel("0 books")
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
        folder = QFileDialog.getExistingDirectory(self, "Select Ebook Folder")
        if not folder:
            return
        self.progress.setValue(0)
        self.status.setText("Scanning ebook library...")
        self.worker = Worker(scan_folder, folder)
        self.worker.signals.progress.connect(self.progress.setValue)
        self.worker.signals.result.connect(self.scan_complete)
        self.worker.signals.error.connect(self.scan_error)
        self.worker.signals.finished.connect(self.worker_finished)
        self.threadpool.start(self.worker)

    def scan_complete(self, result):
        records, errors = result
        for record in records:
            self.db.upsert(record)
        self.records = self.db.all()
        self.update_languages()
        self.apply_filter()
        self.progress.setValue(100)
        self.status.setText(
            f"Scan complete • {len(errors)} error(s)"
            if errors else f"Scan complete • {len(records)} ebook(s)"
        )
        if errors:
            self.status.setToolTip("\n".join(f"{p}: {e}" for p, e in errors))

    def scan_error(self, message):
        self.status.setText("Scan failed")
        QMessageBox.critical(self, "Scan error", message)

    def worker_finished(self):
        self.worker = None

    def update_languages(self):
        current = self.language_box.currentText()
        langs = sorted({
            r.get("language", "").strip()
            for r in self.records if r.get("language", "").strip()
        })
        self.language_box.blockSignals(True)
        self.language_box.clear()
        self.language_box.addItem("All Languages")
        self.language_box.addItems(langs)
        index = self.language_box.findText(current)
        if index >= 0:
            self.language_box.setCurrentIndex(index)
        self.language_box.blockSignals(False)

    def apply_filter(self):
        term = self.search.text().strip().lower()
        language = self.language_box.currentText()

        self.filtered = []
        for r in self.records:
            if language != "All Languages" and r.get("language", "") != language:
                continue
            hay = " ".join([
                r.get("title", ""), r.get("author", ""),
                r.get("identifier", ""), r.get("subjects", ""),
                r.get("description", ""), r.get("path", "")
            ]).lower()
            if term and term not in hay:
                continue
            self.filtered.append(r)
        self.render()

    def render(self):
        sort = self.sort_box.currentText()
        key = {
            "Title": "title",
            "Author": "author",
            "Date": "date",
            "Size": "size"
        }[sort]
        self.filtered.sort(
            key=lambda r: str(r.get(key, "")).lower()
            if key != "size" else r.get(key, 0)
        )

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.filtered))

        for row, r in enumerate(self.filtered):
            values = [
                r.get("title") or r.get("file"),
                r.get("author", ""),
                r.get("language", ""),
                r.get("date", ""),
                str(r.get("chapters", 0)),
                r.get("size_display", ""),
                r.get("extension", "").upper().lstrip("."),
                r.get("path", "")
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))

        self.table.resizeColumnsToContents()
        for c in range(self.table.columnCount()):
            if self.table.columnWidth(c) > 360:
                self.table.setColumnWidth(c, 360)
        self.table.setSortingEnabled(True)
        self.count.setText(f"{len(self.filtered):,} / {len(self.records):,} books")

    def selected_record(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.filtered):
            return None
        return self.filtered[row]

    def show_details(self):
        record = self.selected_record()
        if not record:
            return

        for key, label in self.detail.items():
            value = record.get(key, "")
            if key == "title" and not value:
                value = record.get("file", "")
            label.setText(str(value) if value else "-")

        # EPUB cover extraction is deliberately kept simple in v1.0.
        # If the file contains an embedded cover, EbookLib can expose it.
        self.cover.setText("Cover preview available for EPUBs with embedded covers.")
        if epub is not None and record.get("extension") == ".epub":
            try:
                book = epub.read_epub(record["path"], options={"ignore_ncx": True})
                image_item = None
                for item in book.get_items():
                    name = item.get_name().lower()
                    media = getattr(item, "media_type", "")
                    if ("cover" in name or media.startswith("image/")) and media.startswith("image/"):
                        image_item = item
                        if "cover" in name:
                            break
                if image_item:
                    data = image_item.get_content()
                    pix = QPixmap()
                    pix.loadFromData(data)
                    if not pix.isNull():
                        self.cover.setPixmap(
                            pix.scaled(
                                self.cover.size(),
                                Qt.KeepAspectRatio,
                                Qt.SmoothTransformation
                            )
                        )
            except Exception:
                self.cover.setText("Cover preview unavailable.")

    def open_selected(self):
        record = self.selected_record()
        if not record:
            return
        try:
            os.startfile(record["path"])
        except Exception as e:
            QMessageBox.warning(self, "Open ebook", str(e))

    def export_csv(self):
        if not self.filtered:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Library CSV", "", "CSV Files (*.csv)"
        )
        if not path:
            return
        fields = [
            "title", "author", "publisher", "language", "date", "identifier",
            "subjects", "chapters", "file", "extension", "size", "size_display",
            "modified", "sha256", "path"
        ]
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                for r in self.filtered:
                    writer.writerow({k: r.get(k, "") for k in fields})
            QMessageBox.information(self, "Export", "CSV library exported.")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def export_json(self):
        if not self.filtered:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Library JSON", "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps(self.filtered, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            QMessageBox.information(self, "Export", "JSON library exported.")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def closeEvent(self, event):
        self.db.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))

    if epub is None:
        QMessageBox.critical(
            None,
            "Missing EbookLib",
            "EbookLib is required.\n\nInstall it with:\n"
            "py -m pip install EbookLib"
        )
        sys.exit(1)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

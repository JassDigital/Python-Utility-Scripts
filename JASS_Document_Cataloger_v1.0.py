import sys
import os
import json
import csv
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QFileDialog, QComboBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QAbstractItemView, QCheckBox, QSplitter
)

APP_NAME = "JASS Document Cataloger"
APP_VERSION = "1.0"

DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "JASS" / "DocumentCataloger"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "document_catalog.db"

EXTENSIONS = {
    ".pdf": "PDF",
    ".doc": "Word",
    ".docx": "Word",
    ".odt": "OpenDocument",
    ".rtf": "Rich Text",
    ".txt": "Text",
    ".md": "Markdown",
    ".csv": "CSV",
    ".tsv": "TSV",
    ".xls": "Excel",
    ".xlsx": "Excel",
    ".ods": "OpenDocument",
    ".ppt": "PowerPoint",
    ".pptx": "PowerPoint",
    ".odp": "OpenDocument",
    ".epub": "EPUB",
    ".mobi": "Ebook",
    ".azw": "Ebook",
    ".azw3": "Ebook",
    ".html": "HTML",
    ".htm": "HTML",
    ".xml": "XML",
    ".json": "JSON",
}

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
    background:#202936; border:1px solid #354254;
    border-radius:7px; padding:8px 13px;
}
QPushButton:hover { background:#293545; }
QPushButton#Primary { background:#245b8f; border-color:#347ab9; font-weight:700; }
QTableWidget { gridline-color:#252d38; selection-background-color:#263d59; }
QHeaderView::section { background:#1c232d; color:#aeb9c7; padding:7px; border:0; }
QProgressBar {
    background:#171c23; border:1px solid #303947;
    border-radius:6px; height:16px; text-align:center;
}
QProgressBar::chunk { background:#347ab9; border-radius:5px; }
"""

def human(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{int(n)} B" if u == "B" else f"{n:.1f} {u}"
        n /= 1024

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            path TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            extension TEXT,
            category TEXT,
            size INTEGER,
            modified REAL,
            folder TEXT
        )
    """)
    con.commit()
    con.close()

def category_for(ext):
    return EXTENSIONS.get(ext.lower(), "Other")

class CatalogWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, root, include_other):
        super().__init__()
        self.root = Path(root)
        self.include_other = include_other

    @Slot()
    def run(self):
        try:
            files = []
            for base, dirs, names in os.walk(self.root):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for name in names:
                    p = Path(base) / name
                    ext = p.suffix.lower()
                    if not self.include_other and ext not in EXTENSIONS:
                        continue
                    files.append(p)

            total = len(files)
            records = []
            errors = 0

            for i, p in enumerate(files, 1):
                try:
                    st = p.stat()
                    records.append({
                        "path": str(p),
                        "name": p.name,
                        "extension": p.suffix.lower(),
                        "category": category_for(p.suffix),
                        "size": st.st_size,
                        "modified": st.st_mtime,
                        "folder": str(p.parent),
                    })
                except (OSError, PermissionError):
                    errors += 1
                self.progress.emit(
                    int(i * 100 / total) if total else 100,
                    str(p.relative_to(self.root))
                )

            self.finished.emit({
                "root": str(self.root),
                "records": records,
                "errors": errors,
                "created": datetime.now().isoformat(timespec="seconds")
            })
        except Exception as e:
            self.failed.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1450, 830)
        self.setMinimumSize(1050, 650)
        self.setStyleSheet(STYLE)

        init_db()
        self.records = []
        self.filtered = []
        self.thread = None
        self.worker = None
        self.build_ui()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20,18,20,15)
        root.setSpacing(10)

        title = QLabel(APP_NAME)
        title.setObjectName("Title")
        sub = QLabel("Build a searchable local catalog of PDFs, Office files, ebooks, text files and more.")
        sub.setObjectName("SubTitle")
        root.addWidget(title)
        root.addWidget(sub)

        source = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("Choose a document folder…")
        source.addWidget(self.folder, 1)

        browse = QPushButton("Browse…")
        browse.clicked.connect(self.choose_folder)
        source.addWidget(browse)

        scan = QPushButton("Scan / Update Catalog")
        scan.setObjectName("Primary")
        scan.clicked.connect(self.start_scan)
        source.addWidget(scan)

        export = QPushButton("Export CSV")
        export.clicked.connect(self.export_csv)
        source.addWidget(export)

        root.addLayout(source)

        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search document name, path or extension…")
        self.search.textChanged.connect(self.apply_filter)
        controls.addWidget(self.search, 1)

        self.category = QComboBox()
        self.category.addItem("All Categories")
        self.category.addItems(sorted(set(EXTENSIONS.values()) | {"Other"}))
        self.category.currentTextChanged.connect(self.apply_filter)
        controls.addWidget(self.category)

        self.include_other = QCheckBox("Include other files")
        self.include_other.setChecked(False)
        controls.addWidget(self.include_other)

        root.addLayout(controls)

        self.progress = QProgressBar()
        root.addWidget(self.progress)

        self.status = QLabel("Ready.")
        self.status.setObjectName("SubTitle")
        root.addWidget(self.status)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0,0,0,0)

        self.stats = QLabel("Catalog: 0 documents")
        self.stats.setFont(QFont("Segoe UI", 12, QFont.Bold))
        ll.addWidget(self.stats)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Name", "Category", "Extension", "Size", "Modified", "Folder"
        ])
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self.open_selected)
        ll.addWidget(self.table, 1)

        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0,0,0,0)
        rl.addWidget(QLabel("Selected Document"))

        self.detail = QTableWidget(0, 2)
        self.detail.setHorizontalHeaderLabels(["Property", "Value"])
        self.detail.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.detail.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.detail.setEditTriggers(QAbstractItemView.NoEditTriggers)
        rl.addWidget(self.detail, 1)

        open_btn = QPushButton("Open Document")
        open_btn.clicked.connect(self.open_selected)
        rl.addWidget(open_btn)

        locate_btn = QPushButton("Open Folder")
        locate_btn.clicked.connect(self.open_selected_folder)
        rl.addWidget(locate_btn)

        splitter.addWidget(right)
        splitter.setSizes([1000, 380])
        root.addWidget(splitter, 1)

    def choose_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Select Document Folder")
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
        self.status.setText("Scanning documents…")

        self.thread = QThread()
        self.worker = CatalogWorker(p, self.include_other.isChecked())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.scan_finished)
        self.worker.failed.connect(self.scan_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.scan_done)
        self.thread.start()

    def update_progress(self, pct, path):
        self.progress.setValue(pct)
        self.status.setText(f"Scanning {pct}% • {path}")

    def scan_done(self):
        self.worker = None
        self.thread = None

    def scan_failed(self, msg):
        QMessageBox.critical(self, "Catalog Error", msg)
        self.status.setText("Catalog scan failed.")

    def scan_finished(self, result):
        self.records = result["records"]
        con = sqlite3.connect(DB_PATH)
        con.execute("DELETE FROM documents")
        con.executemany("""
            INSERT OR REPLACE INTO documents
            (path,name,extension,category,size,modified,folder)
            VALUES (:path,:name,:extension,:category,:size,:modified,:folder)
        """, self.records)
        con.commit()
        con.close()

        self.apply_filter()
        self.status.setText(
            f"Catalog updated • {len(self.records):,} documents • "
            f"{result['errors']} access errors"
        )

    def apply_filter(self):
        text = self.search.text().strip().lower()
        cat = self.category.currentText()

        self.filtered = []
        for r in self.records:
            cat_ok = cat == "All Categories" or r["category"] == cat
            hay = f"{r['name']} {r['path']} {r['extension']}".lower()
            if cat_ok and (not text or text in hay):
                self.filtered.append(r)

        self.table.setRowCount(0)
        for r in self.filtered:
            row = self.table.rowCount()
            self.table.insertRow(row)
            modified = datetime.fromtimestamp(r["modified"]).strftime("%Y-%m-%d %H:%M:%S")
            vals = [
                r["name"], r["category"], r["extension"] or "[none]",
                human(r["size"]), modified, r["folder"]
            ]
            for c, v in enumerate(vals):
                self.table.setItem(row, c, QTableWidgetItem(str(v)))

        self.stats.setText(
            f"Showing {len(self.filtered):,} of {len(self.records):,} documents"
        )

    def selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.filtered):
            return None
        return self.filtered[row]

    def show_detail(self):
        r = self.selected()
        if not r:
            return

        self.detail.setRowCount(0)
        modified = datetime.fromtimestamp(r["modified"]).strftime("%Y-%m-%d %H:%M:%S")
        values = [
            ("Name", r["name"]),
            ("Category", r["category"]),
            ("Extension", r["extension"] or "[none]"),
            ("Size", human(r["size"])),
            ("Modified", modified),
            ("Folder", r["folder"]),
            ("Full Path", r["path"]),
        ]
        for k, v in values:
            row = self.detail.rowCount()
            self.detail.insertRow(row)
            self.detail.setItem(row, 0, QTableWidgetItem(k))
            self.detail.setItem(row, 1, QTableWidgetItem(str(v)))

    def open_selected(self):
        r = self.selected()
        if not r:
            return
        self.show_detail()
        subprocess.run(["explorer.exe", r["path"]], check=False)

    def open_selected_folder(self):
        r = self.selected()
        if not r:
            return
        self.show_detail()
        subprocess.run(["explorer.exe", "/select,", r["path"]], check=False)

    def export_csv(self):
        if not self.records:
            QMessageBox.information(self, "Export", "Scan a folder first.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Document Catalog",
            "JASS_Document_Catalog.csv", "CSV (*.csv)"
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["Name","Category","Extension","Size","Modified","Folder","Full Path"])
                for r in self.records:
                    w.writerow([
                        r["name"], r["category"], r["extension"], r["size"],
                        datetime.fromtimestamp(r["modified"]).strftime("%Y-%m-%d %H:%M:%S"),
                        r["folder"], r["path"]
                    ])
            QMessageBox.information(self, "Export Complete", f"Catalog saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

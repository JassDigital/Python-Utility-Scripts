import os
import sys
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QDir, QFileSystemWatcher, QThread, Signal, QSize
from PySide6.QtGui import (
    QAction, QColor, QFont, QIcon, QPixmap, QPainter, QPen
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QSplitter, QTreeView, QListWidget, QListWidgetItem, QTableWidget,
    QTableWidgetItem, QHeaderView, QLineEdit, QPushButton, QLabel, QFrame,
    QMessageBox, QFileDialog, QInputDialog, QPlainTextEdit, QTextEdit,
    QScrollArea, QStackedWidget, QComboBox, QMenu, QToolButton, QProgressBar,
    QAbstractItemView, QFileSystemModel, QDialog, QDialogButtonBox, QCheckBox
)

ROOT = Path(r"E:\Landsoft")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".ico"}
PDF_EXTS = {".pdf"}
TEXT_EXTS = {".txt", ".log", ".md", ".ini", ".rtf", ".xml", ".json", ".csv"}
EDITABLE_TEXT = TEXT_EXTS | {".py", ".yaml", ".yml", ".css", ".js", ".html"}
OFFICE_EXTS = {".xls", ".xlsx", ".xlsm", ".xlsb", ".doc", ".docx", ".odt", ".ppt", ".pptx"}

try:
    import fitz  # PyMuPDF, optional
except Exception:
    fitz = None


def human_size(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.1f} {u}"
        n /= 1024


def category(ext):
    ext = ext.lower()
    if ext in IMAGE_EXTS:
        return "Images"
    if ext in PDF_EXTS:
        return "PDF"
    if ext in {".xlsx", ".xls", ".xlsm", ".xlsb", ".csv"}:
        return "Excel / Data"
    if ext in {".doc", ".docx", ".odt", ".rtf"}:
        return "Documents"
    if ext in {".db", ".byte[]", ".opf", ".ttf"}:
        return "Other"
    if ext in EDITABLE_TEXT:
        return "Text"
    return "Other"


def icon_for(name, is_dir=False):
    if is_dir:
        return "▣"
    ext = Path(name).suffix.lower()
    return {
        ".pdf": "▤", ".jpg": "▧", ".jpeg": "▧", ".png": "▧",
        ".xlsx": "▥", ".xls": "▥", ".doc": "▥", ".docx": "▥",
        ".txt": "≡", ".csv": "≡", ".db": "◈"
    }.get(ext, "◇")


class StatsWorker(QThread):
    done = Signal(int, int, int, object)

    def __init__(self, root):
        super().__init__()
        self.root = Path(root)

    def run(self):
        files = folders = total = 0
        cats = {}
        try:
            for current, dirs, names in os.walk(self.root, followlinks=False):
                folders += len(dirs)
                for name in names:
                    p = Path(current) / name
                    try:
                        size = p.stat().st_size
                    except OSError:
                        continue
                    files += 1
                    total += size
                    c = category(p.suffix)
                    cats[c] = cats.get(c, 0) + 1
            self.done.emit(files, folders, total, cats)
        except Exception:
            self.done.emit(files, folders, total, cats)


class TextEditorDialog(QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.setWindowTitle(f"Edit • {self.path.name}")
        self.resize(900, 650)
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel(f"<b>{self.path.name}</b>"))
        top.addStretch()
        self.encoding = QLabel("UTF-8")
        top.addWidget(self.encoding)
        lay.addLayout(top)

        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Cascadia Mono", 11))
        lay.addWidget(self.editor)

        try:
            data = self.path.read_bytes()
            text = data.decode("utf-8")
            self.editor.setPlainText(text)
        except UnicodeDecodeError:
            try:
                self.editor.setPlainText(self.path.read_text(encoding="utf-8-sig"))
            except Exception as e:
                self.editor.setPlainText(f"Unable to decode this file as text.\n\n{e}")
        except Exception as e:
            self.editor.setPlainText(str(e))

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def save(self):
        try:
            self.path.write_text(self.editor.toPlainText(), encoding="utf-8")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))


class Preview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 18, 18, 18)

        self.title = QLabel("SELECT AN ITEM")
        self.title.setObjectName("previewTitle")
        self.layout.addWidget(self.title)

        self.meta = QLabel("Choose a file or folder to inspect it.")
        self.meta.setWordWrap(True)
        self.meta.setObjectName("muted")
        self.layout.addWidget(self.meta)

        self.stack = QStackedWidget()
        self.placeholder = QLabel("◈\n\nPREVIEW\n\nImages, PDFs and text files\nare shown here.")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setObjectName("previewPlaceholder")
        self.stack.addWidget(self.placeholder)

        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(200, 250)
        self.stack.addWidget(self.image)

        self.pdf = QLabel()
        self.pdf.setAlignment(Qt.AlignCenter)
        self.pdf.setMinimumSize(200, 250)
        self.stack.addWidget(self.pdf)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Cascadia Mono", 10))
        self.stack.addWidget(self.text)

        self.folder_info = QLabel()
        self.folder_info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.folder_info.setWordWrap(True)
        self.stack.addWidget(self.folder_info)

        self.layout.addWidget(self.stack, 1)

    def show_item(self, path):
        path = Path(path)
        self.title.setText(path.name.upper() if path.name else str(path))
        try:
            st = path.stat()
            if path.is_dir():
                self.meta.setText(f"FOLDER\n{path}\n\nModified: {datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M}")
                self.folder_info.setText("Folder selected.\n\nDouble-click to open.\nUse the toolbar to rename, create a subfolder, or remove it.")
                self.stack.setCurrentWidget(self.folder_info)
                return

            self.meta.setText(
                f"{category(path.suffix)}  •  {human_size(st.st_size)}\n"
                f"{path}\n\nModified: {datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M:%S}"
            )

            ext = path.suffix.lower()
            if ext in IMAGE_EXTS:
                pix = QPixmap(str(path))
                if not pix.isNull():
                    self.image.setPixmap(pix.scaled(
                        900, 650, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    ))
                    self.stack.setCurrentWidget(self.image)
                else:
                    self.stack.setCurrentWidget(self.placeholder)
            elif ext in PDF_EXTS and fitz:
                try:
                    doc = fitz.open(str(path))
                    page = doc.load_page(0)
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25), alpha=False)
                    qpix = QPixmap()
                    qpix.loadFromData(pix.tobytes("png"))
                    self.pdf.setPixmap(qpix.scaled(
                        850, 650, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    ))
                    doc.close()
                    self.stack.setCurrentWidget(self.pdf)
                except Exception:
                    self.pdf.setText("PDF preview unavailable.\nUse Open to view the document.")
                    self.stack.setCurrentWidget(self.pdf)
            elif ext in EDITABLE_TEXT:
                try:
                    text = path.read_text(encoding="utf-8-sig", errors="replace")
                    self.text.setPlainText(text[:200000])
                    self.stack.setCurrentWidget(self.text)
                except Exception:
                    self.stack.setCurrentWidget(self.placeholder)
            else:
                self.stack.setCurrentWidget(self.placeholder)
        except Exception as e:
            self.meta.setText(str(e))
            self.stack.setCurrentWidget(self.placeholder)


class LandsoftExplorer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JASS Landsoft Explorer • v1.0")
        self.resize(1500, 900)
        self.setMinimumSize(1100, 700)

        self.current_dir = ROOT
        self.search_results = []
        self.build_ui()
        self.apply_style()
        self.populate_root()
        self.refresh_stats()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main = QVBoxLayout(central)
        main.setContentsMargins(16, 14, 16, 12)
        main.setSpacing(10)

        # Header
        header = QHBoxLayout()
        brand = QLabel("JASS <span>LANDSOFT</span>")
        brand.setObjectName("brand")
        header.addWidget(brand)
        title = QLabel("DOCUMENT EXPLORER")
        title.setObjectName("eyebrow")
        header.addWidget(title)
        header.addStretch()

        self.search = QLineEdit()
        self.search.setPlaceholderText("⌕  Search files and folders in Landsoft…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(420)
        self.search.returnPressed.connect(self.search_now)
        header.addWidget(self.search)

        search_btn = QPushButton("SEARCH")
        search_btn.clicked.connect(self.search_now)
        header.addWidget(search_btn)
        main.addLayout(header)

        # Dashboard cards
        cards = QHBoxLayout()
        self.cards = {}
        for key, label in [
            ("files", "FILES"), ("folders", "FOLDERS"),
            ("size", "TOTAL SIZE"), ("pdf", "PDF"), ("images", "IMAGES"),
            ("excel", "EXCEL / DATA")
        ]:
            frame = QFrame()
            frame.setObjectName("card")
            l = QVBoxLayout(frame)
            value = QLabel("—")
            value.setObjectName("cardValue")
            cap = QLabel(label)
            cap.setObjectName("cardLabel")
            l.addWidget(value)
            l.addWidget(cap)
            cards.addWidget(frame)
            self.cards[key] = value
        main.addLayout(cards)

        # Toolbar
        toolbar = QHBoxLayout()
        for text, slot in [
            ("←", self.go_back),
            ("→", self.go_forward),
            ("↑  UP", self.go_up),
            ("↻  REFRESH", self.refresh_all),
            ("＋  NEW FOLDER", self.new_folder),
            ("✎  RENAME", self.rename_item),
            ("✕  DELETE", self.delete_item),
            ("OPEN", self.open_item),
            ("EDIT", self.edit_item),
        ]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            toolbar.addWidget(b)
        toolbar.addStretch()

        self.filter = QComboBox()
        self.filter.addItems(["All types", "Images", "PDF", "Excel / Data", "Documents", "Text", "Other"])
        self.filter.currentTextChanged.connect(self.populate_files)
        toolbar.addWidget(self.filter)
        main.addLayout(toolbar)

        # Breadcrumb
        self.breadcrumb = QLabel()
        self.breadcrumb.setObjectName("breadcrumb")
        main.addWidget(self.breadcrumb)

        # Main explorer
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Tree
        left = QFrame()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        lab = QLabel("FOLDERS")
        lab.setObjectName("sectionTitle")
        ll.addWidget(lab)

        self.model = QFileSystemModel()
        self.model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot)
        self.model.setRootPath(str(ROOT))

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(str(ROOT)))
        self.tree.setHeaderHidden(True)
        for col in range(1, 4):
            self.tree.hideColumn(col)
        self.tree.clicked.connect(self.folder_clicked)
        self.tree.doubleClicked.connect(self.folder_double_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        ll.addWidget(self.tree)
        splitter.addWidget(left)

        # Files
        middle = QFrame()
        ml = QVBoxLayout(middle)
        ml.setContentsMargins(0, 0, 0, 0)
        self.file_title = QLabel("FILES")
        self.file_title.setObjectName("sectionTitle")
        ml.addWidget(self.file_title)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["TYPE", "NAME", "SIZE", "MODIFIED", "LOCATION"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.table.doubleClicked.connect(lambda _: self.open_item())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.file_menu)
        ml.addWidget(self.table)
        splitter.addWidget(middle)

        # Preview
        self.preview = Preview()
        splitter.addWidget(self.preview)

        splitter.setSizes([260, 730, 430])
        main.addWidget(splitter, 1)

        # Status
        status = QHBoxLayout()
        self.status = QLabel("Ready")
        self.status.setObjectName("muted")
        status.addWidget(self.status)
        status.addStretch()
        self.location = QLabel(str(ROOT))
        self.location.setObjectName("muted")
        status.addWidget(self.location)
        main.addLayout(status)

    def apply_style(self):
        self.setStyleSheet("""
        * { font-family: "Segoe UI", Arial; }
        QMainWindow, QWidget { background: #0b1018; color: #e7eef8; }
        QFrame#card, QFrame { border: 1px solid #1e2b3b; border-radius: 12px; }
        QFrame#card { background: #101925; }
        QLabel#brand { font-size: 26px; font-weight: 800; letter-spacing: 2px; color: #f2f7ff; }
        QLabel#brand span { color: #45d9ff; }
        QLabel#eyebrow, QLabel#sectionTitle { color: #6d7f95; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
        QLabel#cardValue { font-size: 24px; font-weight: 800; color: #56ddff; }
        QLabel#cardLabel { color: #73849a; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
        QLabel#breadcrumb { background: #0e1722; border: 1px solid #1e2b3b; border-radius: 8px; padding: 8px 12px; color: #86a0ba; }
        QLabel#muted { color: #718399; }
        QLabel#previewTitle { color: #eaf4ff; font-size: 18px; font-weight: 700; }
        QLabel#previewPlaceholder { color: #53657b; font-size: 15px; border: 1px dashed #26384c; border-radius: 12px; }
        QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {
            background: #0e1722; border: 1px solid #25364a; border-radius: 8px;
            padding: 8px; color: #e8f2ff; selection-background-color: #155f82;
        }
        QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border: 1px solid #35cfff; }
        QPushButton {
            background: #111d2b; border: 1px solid #26394f; border-radius: 8px;
            padding: 8px 12px; color: #c9d8e8; font-weight: 600;
        }
        QPushButton:hover { background: #17283a; border-color: #36cfff; color: white; }
        QPushButton:pressed { background: #0c526c; }
        QTreeView, QTableWidget {
            background: #0d151f; alternate-background-color: #101b28;
            border: 1px solid #1e2b3b; border-radius: 10px;
            gridline-color: #172433; outline: none;
        }
        QTreeView::item, QTableWidget::item { padding: 7px; border: none; }
        QTreeView::item:hover, QTableWidget::item:hover { background: #142538; }
        QTreeView::item:selected, QTableWidget::item:selected { background: #123e55; color: #ffffff; }
        QHeaderView::section {
            background: #111d2b; color: #6f849b; border: none;
            border-bottom: 1px solid #26384b; padding: 8px; font-size: 10px; font-weight: 700;
        }
        QScrollBar:vertical { background: #0b1018; width: 10px; }
        QScrollBar::handle:vertical { background: #263b51; border-radius: 5px; min-height: 30px; }
        QMenu { background: #111c29; border: 1px solid #294057; padding: 5px; }
        QMenu::item { padding: 8px 22px; }
        QMenu::item:selected { background: #123e55; }
        QDialog { background: #0d151f; }
        """)

    def populate_root(self):
        self.current_dir = ROOT
        self.populate_files()
        self.update_breadcrumb()

    def update_breadcrumb(self):
        try:
            rel = self.current_dir.relative_to(ROOT)
            text = "LANDSOFT  /  " + ("  /  ".join(rel.parts) if rel.parts else "ROOT")
        except ValueError:
            text = str(self.current_dir)
        self.breadcrumb.setText(text)
        self.location.setText(str(self.current_dir))
        self.file_title.setText(f"FILES  •  {self.current_dir.name.upper()}")

    def populate_files(self):
        self.table.setRowCount(0)
        if not self.current_dir.exists():
            return
        selected_filter = self.filter.currentText()
        try:
            entries = sorted(self.current_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as e:
            self.status.setText(f"Cannot read folder: {e}")
            return

        for p in entries:
            if p.is_dir():
                self.add_row(p)
            elif selected_filter == "All types" or category(p.suffix) == selected_filter:
                self.add_row(p)

        self.status.setText(f"{self.table.rowCount():,} items")
        self.update_breadcrumb()

    def add_row(self, p):
        r = self.table.rowCount()
        self.table.insertRow(r)
        is_dir = p.is_dir()
        try:
            size = "—" if is_dir else human_size(p.stat().st_size)
            modified = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            size, modified = "?", "?"
        vals = [
            icon_for(p.name, is_dir),
            p.name,
            size,
            modified,
            str(p.parent.relative_to(ROOT)) if p.parent != ROOT else "LANDSOFT"
        ]
        for c, value in enumerate(vals):
            item = QTableWidgetItem(value)
            if c == 0:
                item.setTextAlignment(Qt.AlignCenter)
            item.setData(Qt.UserRole, str(p))
            self.table.setItem(r, c, item)

    def selected_path(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            item = self.table.item(rows[0].row(), 1)
            return Path(item.data(Qt.UserRole))
        return None

    def selection_changed(self):
        p = self.selected_path()
        if p:
            self.preview.show_item(p)

    def folder_clicked(self, index):
        p = Path(self.model.filePath(index))
        if p.is_dir():
            self.current_dir = p
            self.populate_files()

    def folder_double_clicked(self, index):
        self.folder_clicked(index)

    def go_up(self):
        if self.current_dir != ROOT and ROOT in self.current_dir.parents:
            self.current_dir = self.current_dir.parent
            self.tree.setCurrentIndex(self.model.index(str(self.current_dir)))
            self.populate_files()

    def go_back(self):
        # Simple history-free parent navigation keeps the app predictable.
        self.go_up()

    def go_forward(self):
        pass

    def refresh_all(self):
        self.populate_files()
        self.refresh_stats()
        self.status.setText("Refreshed")

    def refresh_stats(self):
        self.stats_worker = StatsWorker(ROOT)
        self.stats_worker.done.connect(self.stats_done)
        self.stats_worker.start()

    def stats_done(self, files, folders, total, cats):
        self.cards["files"].setText(f"{files:,}")
        self.cards["folders"].setText(f"{folders:,}")
        self.cards["size"].setText(human_size(total))
        self.cards["pdf"].setText(f"{cats.get('PDF', 0):,}")
        self.cards["images"].setText(f"{cats.get('Images', 0):,}")
        self.cards["excel"].setText(f"{cats.get('Excel / Data', 0):,}")

    def new_folder(self):
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if not ok or not name.strip():
            return
        target = self.current_dir / name.strip()
        try:
            target.mkdir()
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Cannot create folder", str(e))

    def rename_item(self):
        p = self.selected_path()
        if not p:
            QMessageBox.information(self, "Rename", "Select a file or folder first.")
            return
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=p.name)
        if not ok or not name.strip() or name.strip() == p.name:
            return
        try:
            p.rename(p.with_name(name.strip()))
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Rename failed", str(e))

    def delete_item(self):
        p = self.selected_path()
        if not p:
            QMessageBox.information(self, "Delete", "Select a file or folder first.")
            return
        msg = f"Delete this {'folder and its contents' if p.is_dir() else 'file'}?\n\n{p}"
        if QMessageBox.question(self, "Confirm deletion", msg,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Delete failed", str(e))

    def open_item(self):
        p = self.selected_path()
        if not p:
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(p))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))

    def edit_item(self):
        p = self.selected_path()
        if not p or p.is_dir():
            QMessageBox.information(self, "Edit", "Select a file to edit.")
            return
        if p.suffix.lower() in EDITABLE_TEXT:
            dlg = TextEditorDialog(p, self)
            if dlg.exec():
                self.refresh_all()
        else:
            # Office/PDF/binary formats are handed to their installed editor/viewer.
            self.open_item()

    def search_now(self):
        query = self.search.text().strip().lower()
        if not query:
            self.populate_files()
            return
        self.table.setRowCount(0)
        self.status.setText("Searching…")
        QApplication.processEvents()

        count = 0
        try:
            for current, dirs, files in os.walk(ROOT, followlinks=False):
                for name in dirs + files:
                    if query in name.lower():
                        self.add_row(Path(current) / name)
                        count += 1
        except Exception as e:
            self.status.setText(f"Search error: {e}")
            return
        self.file_title.setText(f"SEARCH RESULTS  •  {count:,}")
        self.breadcrumb.setText(f"SEARCH  /  {query}")
        self.status.setText(f"{count:,} matching items")

    def tree_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Open folder", self.go_to_tree_folder)
        menu.addAction("New folder", self.new_folder)
        menu.addAction("Rename", self.rename_tree_item)
        menu.addAction("Delete", self.delete_tree_item)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def tree_path(self):
        index = self.tree.currentIndex()
        return Path(self.model.filePath(index)) if index.isValid() else None

    def go_to_tree_folder(self):
        p = self.tree_path()
        if p and p.is_dir():
            self.current_dir = p
            self.populate_files()

    def rename_tree_item(self):
        p = self.tree_path()
        if not p or p == ROOT:
            return
        name, ok = QInputDialog.getText(self, "Rename folder", "New name:", text=p.name)
        if ok and name.strip():
            try:
                p.rename(p.with_name(name.strip()))
                self.refresh_all()
            except Exception as e:
                QMessageBox.critical(self, "Rename failed", str(e))

    def delete_tree_item(self):
        p = self.tree_path()
        if not p or p == ROOT:
            return
        if QMessageBox.question(self, "Delete folder", f"Delete folder and contents?\n\n{p}",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            shutil.rmtree(p)
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Delete failed", str(e))

    def file_menu(self, pos):
        p = self.selected_path()
        menu = QMenu(self)
        if p:
            menu.addAction("Open", self.open_item)
            if p.is_file():
                menu.addAction("Edit", self.edit_item)
            menu.addAction("Rename", self.rename_item)
            menu.addSeparator()
            menu.addAction("Delete", self.delete_item)
            menu.addAction("Open containing folder", lambda: self.open_containing(p))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def open_containing(self, p):
        try:
            os.startfile(str(p.parent))
        except Exception as e:
            QMessageBox.critical(self, "Open folder failed", str(e))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("JASS Landsoft Explorer")
    if not ROOT.exists():
        QMessageBox.critical(None, "Landsoft not found",
                             f"The configured folder does not exist:\n{ROOT}")
        sys.exit(1)
    win = LandsoftExplorer()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

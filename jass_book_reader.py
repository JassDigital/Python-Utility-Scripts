#!/usr/bin/env python3
"""
JASS Book Reader
Single-file PySide6 ebook reader.

Supported:
- EPUB (DRM-free)
- PDF
- TXT
- HTML / HTM

Dependencies:
    pip install PySide6 PyMuPDF

Run:
    python jass_book_reader.py
"""

import sys
import os
import re
import json
import html
import zipfile
import sqlite3
import mimetypes
from pathlib import Path
from datetime import datetime
from html.parser import HTMLParser

from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import (
    QAction, QFont, QIcon, QPixmap, QTextCursor, QTextCharFormat,
    QColor, QKeySequence, QShortcut
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QSplitter, QFrame, QStackedWidget,
    QLineEdit, QComboBox, QSlider, QToolButton, QScrollArea,
    QTextBrowser, QDialog, QDialogButtonBox, QFormLayout, QSpinBox
)

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


APP_NAME = "JASS Book Reader"
DATA_DIR = Path.home() / ".jass_book_reader"
DB_PATH = DATA_DIR / "library.db"
SUPPORTED = {".epub", ".pdf", ".txt", ".html", ".htm"}


# ---------- EPUB helpers ----------

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style", "svg"):
            self.skip += 1
        if tag in ("p", "div", "br", "li", "h1", "h2", "h3", "h4",
                   "h5", "h6", "blockquote", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style", "svg") and self.skip:
            self.skip -= 1
        if tag.lower() in ("p", "div", "li", "h1", "h2", "h3", "h4",
                           "h5", "h6", "blockquote", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def clean_text_from_html(raw):
    parser = TextExtractor()
    parser.feed(raw)
    text = "".join(parser.parts)
    text = html.unescape(text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_reader_html(raw):
    # Preserve basic formatting while making it safe to display.
    raw = re.sub(r"(?is)<script.*?</script>", "", raw)
    raw = re.sub(r"(?is)<style.*?</style>", "", raw)
    body = re.search(r"(?is)<body[^>]*>(.*?)</body>", raw)
    content = body.group(1) if body else raw
    return content


def epub_read(path):
    with zipfile.ZipFile(path, "r") as z:
        names = z.namelist()
        container_name = "META-INF/container.xml"
        if container_name not in names:
            raise ValueError("Invalid EPUB: container.xml is missing.")

        container = z.read(container_name).decode("utf-8", errors="ignore")
        m = re.search(r'full-path\s*=\s*["\']([^"\']+)["\']', container)
        if not m:
            raise ValueError("Could not locate EPUB package document.")
        opf_path = m.group(1)
        opf_dir = Path(opf_path).parent.as_posix()
        opf = z.read(opf_path).decode("utf-8", errors="ignore")

        title_m = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf, re.I | re.S)
        author_m = re.search(r"<dc:creator[^>]*>(.*?)</dc:creator>", opf, re.I | re.S)
        title = clean_text_from_html(title_m.group(1)) if title_m else Path(path).stem
        author = clean_text_from_html(author_m.group(1)) if author_m else "Unknown Author"

        manifest = {}
        for item in re.findall(r"<item\b[^>]*>", opf, re.I | re.S):
            iid = re.search(r'id=["\']([^"\']+)["\']', item, re.I)
            href = re.search(r'href=["\']([^"\']+)["\']', item, re.I)
            media = re.search(r'media-type=["\']([^"\']+)["\']', item, re.I)
            if iid and href:
                manifest[iid.group(1)] = (
                    href.group(1).replace("%20", " "),
                    media.group(1) if media else ""
                )

        spine = []
        spine_m = re.search(r"<spine\b[^>]*>(.*?)</spine>", opf, re.I | re.S)
        if spine_m:
            for itemref in re.findall(r"<itemref\b[^>]*>", spine_m.group(1), re.I | re.S):
                rid = re.search(r'idref=["\']([^"\']+)["\']', itemref, re.I)
                if rid and rid.group(1) in manifest:
                    spine.append(manifest[rid.group(1)][0])

        if not spine:
            spine = [v[0] for v in manifest.values()
                     if "html" in v[1] or "xhtml" in v[1]]

        chapters = []
        for href in spine:
            full = (Path(opf_dir) / href).as_posix()
            full = str(Path(full).as_posix())
            # Normalize ./ components.
            full = re.sub(r"^\./", "", full)
            if full in z.namelist():
                raw = z.read(full).decode("utf-8", errors="ignore")
                chapters.append((Path(href).stem.replace("_", " ").replace("-", " ").title(),
                                 html_to_reader_html(raw)))

        if not chapters:
            raise ValueError("EPUB contains no readable chapters.")

        return title, author, chapters


# ---------- Database ----------

class LibraryDB:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(DB_PATH)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS books (
                path TEXT PRIMARY KEY,
                title TEXT,
                author TEXT,
                ext TEXT,
                progress REAL DEFAULT 0,
                last_opened TEXT,
                added TEXT
            )
        """)
        self.con.commit()

    def upsert(self, path, title=None, author=None):
        p = str(Path(path).resolve())
        ext = Path(p).suffix.lower()
        now = datetime.now().isoformat(timespec="seconds")
        self.con.execute("""
            INSERT INTO books(path,title,author,ext,added)
            VALUES(?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
                title=COALESCE(excluded.title, books.title),
                author=COALESCE(excluded.author, books.author)
        """, (p, title or Path(p).stem, author or "Unknown Author", ext, now))
        self.con.commit()

    def set_progress(self, path, progress):
        self.con.execute(
            "UPDATE books SET progress=?, last_opened=? WHERE path=?",
            (float(progress), datetime.now().isoformat(timespec="seconds"), str(Path(path).resolve()))
        )
        self.con.commit()

    def get(self, path):
        return self.con.execute(
            "SELECT path,title,author,ext,progress,last_opened,added FROM books WHERE path=?",
            (str(Path(path).resolve()),)
        ).fetchone()

    def all(self):
        return self.con.execute(
            "SELECT path,title,author,ext,progress,last_opened,added FROM books ORDER BY last_opened DESC, added DESC"
        ).fetchall()

    def remove(self, path):
        self.con.execute("DELETE FROM books WHERE path=?", (str(Path(path).resolve()),))
        self.con.commit()


# ---------- Reader widget ----------

class ReaderWidget(QWidget):
    back_requested = Signal()
    progress_changed = Signal(float)

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.path = None
        self.title = ""
        self.author = ""
        self.chapters = []
        self.chapter_index = 0
        self.font_size = 19
        self.theme = "paper"
        self._loading = False

        self.build_ui()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.topbar = QFrame()
        self.topbar.setObjectName("readerTop")
        bar = QHBoxLayout(self.topbar)
        bar.setContentsMargins(18, 10, 18, 10)

        self.back_btn = QPushButton("‹  Library")
        self.back_btn.clicked.connect(self.back_requested.emit)
        bar.addWidget(self.back_btn)

        self.title_label = QLabel("No book open")
        self.title_label.setObjectName("readerTitle")
        bar.addWidget(self.title_label, 1)

        self.chapter_label = QLabel("")
        self.chapter_label.setObjectName("muted")
        bar.addWidget(self.chapter_label)

        self.theme_btn = QPushButton("☾")
        self.theme_btn.setToolTip("Toggle reading theme")
        self.theme_btn.clicked.connect(self.toggle_theme)
        bar.addWidget(self.theme_btn)

        self.text_size_btn = QPushButton("A")
        self.text_size_btn.clicked.connect(self.change_font_size)
        bar.addWidget(self.text_size_btn)

        root.addWidget(self.topbar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.toc = QListWidget()
        self.toc.setObjectName("toc")
        self.toc.setFixedWidth(270)
        self.toc.itemClicked.connect(self.go_to_item)
        body.addWidget(self.toc)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setReadOnly(True)
        self.browser.setFrameShape(QFrame.NoFrame)
        self.browser.verticalScrollBar().valueChanged.connect(self.on_scroll)
        body.addWidget(self.browser, 1)

        root.addLayout(body, 1)

        self.bottom = QFrame()
        self.bottom.setObjectName("readerBottom")
        b = QHBoxLayout(self.bottom)
        b.setContentsMargins(18, 8, 18, 8)

        self.prev_btn = QPushButton("← Previous")
        self.prev_btn.clicked.connect(self.previous_chapter)
        b.addWidget(self.prev_btn)

        self.progress = QSlider(Qt.Horizontal)
        self.progress.setRange(0, 1000)
        self.progress.sliderMoved.connect(self.slider_moved)
        b.addWidget(self.progress, 1)

        self.progress_label = QLabel("0%")
        b.addWidget(self.progress_label)

        self.next_btn = QPushButton("Next →")
        self.next_btn.clicked.connect(self.next_chapter)
        b.addWidget(self.next_btn)

        root.addWidget(self.bottom)

    def open_book(self, path):
        try:
            self._loading = True
            self.path = str(Path(path).resolve())
            ext = Path(path).suffix.lower()

            if ext == ".epub":
                self.title, self.author, self.chapters = epub_read(path)
                self.toc.clear()
                for name, _ in self.chapters:
                    self.toc.addItem(name)
                self.chapter_index = 0
                row = self.db.get(self.path)
                if row:
                    self.chapter_index = min(
                        int((row[4] or 0) / 100 * len(self.chapters)),
                        len(self.chapters) - 1
                    )
                self.show_chapter(self.chapter_index)

            elif ext in (".txt", ".html", ".htm"):
                raw = Path(path).read_text(encoding="utf-8", errors="replace")
                if ext in (".html", ".htm"):
                    content = html_to_reader_html(raw)
                else:
                    content = "<pre>" + html.escape(raw) + "</pre>"
                self.title = Path(path).stem
                self.author = "Text Document"
                self.chapters = [("Document", content)]
                self.toc.clear()
                self.toc.addItem("Document")
                self.show_chapter(0)

            elif ext == ".pdf":
                if fitz is None:
                    raise RuntimeError("PDF support requires PyMuPDF. Install it with: pip install PyMuPDF")
                doc = fitz.open(path)
                self.title = Path(path).stem
                self.author = "PDF Document"
                self.chapters = []
                for i, page in enumerate(doc):
                    txt = page.get_text("html")
                    self.chapters.append((f"Page {i + 1}", txt))
                doc.close()
                self.toc.clear()
                for name, _ in self.chapters:
                    self.toc.addItem(name)
                row = self.db.get(self.path)
                idx = int(((row[4] or 0) / 100) * len(self.chapters)) if row else 0
                self.chapter_index = min(idx, len(self.chapters) - 1)
                self.show_chapter(self.chapter_index)

            else:
                raise ValueError("Unsupported format.")

            self.db.upsert(self.path, self.title, self.author)
            self.title_label.setText(self.title)
            self.update_nav()
            self._loading = False

        except Exception as e:
            self._loading = False
            QMessageBox.critical(self, "Cannot Open Book", str(e))

    def show_chapter(self, index):
        if not self.chapters:
            return
        self.chapter_index = max(0, min(index, len(self.chapters) - 1))
        name, content = self.chapters[self.chapter_index]
        self.chapter_label.setText(name)
        self.browser.setHtml(self.reader_html(content))
        self.browser.verticalScrollBar().setValue(0)
        self.toc.setCurrentRow(self.chapter_index)
        self.update_nav()
        self.save_progress()

    def reader_html(self, content):
        if content.startswith("<pre>"):
            body = content
        else:
            body = content
        theme = self.theme
        if theme == "night":
            bg, fg, link, quote = "#171717", "#e9e4d8", "#9fc5ff", "#2b2b2b"
        elif theme == "dark":
            bg, fg, link, quote = "#242424", "#eeeeee", "#9fc5ff", "#343434"
        elif theme == "sepia":
            bg, fg, link, quote = "#f2e5c9", "#493b2b", "#6b4e2e", "#e7d7b5"
        else:
            bg, fg, link, quote = "#f7f3ea", "#29261f", "#355f91", "#ebe5d7"

        return f"""
        <html><head><style>
        body {{
            background:{bg};
            color:{fg};
            font-family:"Noto Sans","Segoe UI",Arial,sans-serif;
            font-size:{self.font_size}px;
            line-height:1.75;
            margin:50px auto;
            max-width:820px;
        }}
        p {{ margin:0 0 1.1em 0; }}
        h1,h2,h3,h4 {{ line-height:1.25; margin-top:1.4em; }}
        a {{ color:{link}; }}
        blockquote {{ background:{quote}; padding:16px 20px; border-left:4px solid {link}; }}
        pre {{ white-space:pre-wrap; font-family:"Noto Sans Mono","Consolas",monospace; }}
        img {{ max-width:100%; }}
        </style></head><body>{body}</body></html>
        """

    def update_nav(self):
        total = max(1, len(self.chapters))
        pct = ((self.chapter_index + 1) / total) * 100
        self.progress.setValue(int(pct * 10))
        self.progress_label.setText(f"{pct:.0f}%")
        self.prev_btn.setEnabled(self.chapter_index > 0)
        self.next_btn.setEnabled(self.chapter_index < total - 1)

    def save_progress(self):
        if self.path and self.chapters and not self._loading:
            pct = ((self.chapter_index + 1) / len(self.chapters)) * 100
            self.db.set_progress(self.path, pct)
            self.progress_changed.emit(pct)

    def on_scroll(self, value):
        if self._loading or not self.path or not self.chapters:
            return
        sb = self.browser.verticalScrollBar()
        if sb.maximum() > 0 and value >= sb.maximum() - 5:
            # Don't automatically change chapter; preserve predictable reading.
            pass

    def slider_moved(self, value):
        if not self.chapters:
            return
        idx = min(len(self.chapters) - 1, max(0, round((value / 1000) * len(self.chapters)) - 1))
        self.show_chapter(idx)

    def go_to_item(self, item):
        self.show_chapter(self.toc.row(item))

    def previous_chapter(self):
        if self.chapter_index > 0:
            self.show_chapter(self.chapter_index - 1)

    def next_chapter(self):
        if self.chapter_index < len(self.chapters) - 1:
            self.show_chapter(self.chapter_index + 1)

    def toggle_theme(self):
        order = ["paper", "sepia", "night", "dark"]
        self.theme = order[(order.index(self.theme) + 1) % len(order)]
        if self.chapters:
            self.show_chapter(self.chapter_index)

    def change_font_size(self):
        self.font_size += 2
        if self.font_size > 27:
            self.font_size = 15
        if self.chapters:
            name, content = self.chapters[self.chapter_index]
            self.browser.setHtml(self.reader_html(content))


# ---------- Library UI ----------

class BookCard(QFrame):
    clicked = Signal(str)

    def __init__(self, row):
        super().__init__()
        self.path, title, author, ext, progress, last_opened, added = row
        self.setObjectName("bookCard")
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(6)

        icon = QLabel({
            ".epub": "📖", ".pdf": "📕", ".txt": "📝",
            ".html": "🌐", ".htm": "🌐"
        }.get(ext, "📚"))
        icon.setObjectName("bookIcon")
        lay.addWidget(icon)

        title_label = QLabel(title or Path(self.path).stem)
        title_label.setObjectName("bookTitle")
        title_label.setWordWrap(True)
        lay.addWidget(title_label)

        author_label = QLabel(author or "Unknown Author")
        author_label.setObjectName("bookAuthor")
        lay.addWidget(author_label)

        bar = QSlider(Qt.Horizontal)
        bar.setEnabled(False)
        bar.setRange(0, 100)
        bar.setValue(int(progress or 0))
        lay.addWidget(bar)

        p = QLabel(f"{float(progress or 0):.0f}% read")
        p.setObjectName("muted")
        lay.addWidget(p)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.path)
        super().mousePressEvent(event)


class LibraryWidget(QWidget):
    open_requested = Signal(str)

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.cards = []
        self.build_ui()
        self.refresh()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        top = QHBoxLayout()
        heading = QVBoxLayout()
        h = QLabel("Your Library")
        h.setObjectName("pageTitle")
        heading.addWidget(h)
        self.subtitle = QLabel("Your books, ready to read.")
        self.subtitle.setObjectName("muted")
        heading.addWidget(self.subtitle)
        top.addLayout(heading)
        top.addStretch()

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search books or authors…")
        self.search.setFixedWidth(300)
        self.search.textChanged.connect(self.filter_cards)
        top.addWidget(self.search)

        add = QPushButton("+  Add Books")
        add.clicked.connect(self.add_books)
        top.addWidget(add)
        root.addLayout(top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.container = QWidget()
        self.grid = QGridLayout(self.container)
        self.grid.setAlignment(Qt.AlignTop)
        self.grid.setSpacing(18)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)

    def add_books(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add Books", str(Path.home()),
            "Books (*.epub *.pdf *.txt *.html *.htm)"
        )
        for f in files:
            self.db.upsert(f)
        self.refresh()
        if files:
            self.open_requested.emit(files[0])

    def refresh(self):
        for c in self.cards:
            c.deleteLater()
        self.cards.clear()
        rows = self.db.all()
        for i, row in enumerate(rows):
            card = BookCard(row)
            card.clicked.connect(self.open_requested.emit)
            self.cards.append(card)
            self.grid.addWidget(card, i // 4, i % 4)
        self.subtitle.setText(f"{len(rows)} book{'s' if len(rows) != 1 else ''} in your library.")

    def filter_cards(self, text):
        q = text.strip().lower()
        for card in self.cards:
            labels = card.findChildren(QLabel)
            title = labels[1].text().lower() if len(labels) > 1 else ""
            author = labels[2].text().lower() if len(labels) > 2 else ""
            visible = (not q) or q in card.path.lower() or q in title or q in author
            card.setVisible(visible)


# ---------- Main Window ----------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = LibraryDB()
        self.setWindowTitle(APP_NAME)
        self.resize(1250, 820)
        self.setMinimumSize(950, 650)
        self.setAcceptDrops(True)

        self.stack = QStackedWidget()
        self.library = LibraryWidget(self.db)
        self.reader = ReaderWidget(self.db)
        self.stack.addWidget(self.library)
        self.stack.addWidget(self.reader)
        self.setCentralWidget(self.stack)

        self.library.open_requested.connect(self.open_book)
        self.reader.back_requested.connect(self.show_library)

        self.build_menu()
        self.apply_theme()

        # Keyboard shortcuts
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.open_file)
        QShortcut(QKeySequence("Esc"), self, activated=self.show_library)
        QShortcut(QKeySequence("Left"), self, activated=self.reader.previous_chapter)
        QShortcut(QKeySequence("Right"), self, activated=self.reader.next_chapter)

    def build_menu(self):
        menu = self.menuBar()

        file_menu = menu.addMenu("&File")
        open_act = QAction("Open Book…", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self.open_file)
        file_menu.addAction(open_act)

        add_act = QAction("Add Books to Library…", self)
        add_act.triggered.connect(self.library.add_books)
        file_menu.addAction(add_act)
        file_menu.addSeparator()

        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        view_menu = menu.addMenu("&View")
        lib_act = QAction("Library", self)
        lib_act.setShortcut("Esc")
        lib_act.triggered.connect(self.show_library)
        view_menu.addAction(lib_act)

        reader_act = QAction("Reader", self)
        reader_act.triggered.connect(lambda: self.stack.setCurrentWidget(self.reader))
        view_menu.addAction(reader_act)

    def open_file(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Open Book", str(Path.home()),
            "Books (*.epub *.pdf *.txt *.html *.htm)"
        )
        if f:
            self.open_book(f)

    def open_book(self, path):
        self.reader.open_book(path)
        if self.reader.path:
            self.stack.setCurrentWidget(self.reader)

    def show_library(self):
        self.library.refresh()
        self.stack.setCurrentWidget(self.library)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for u in event.mimeData().urls():
                if Path(u.toLocalFile()).suffix.lower() in SUPPORTED:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        for u in event.mimeData().urls():
            p = u.toLocalFile()
            if Path(p).suffix.lower() in SUPPORTED:
                self.db.upsert(p)
                self.open_book(p)
                break
        event.acceptProposedAction()

    def apply_theme(self):
        self.setStyleSheet("""
        QMainWindow, QWidget {
            background: #f3f4f6;
            color: #202124;
            font-family: "Segoe UI", "Noto Sans", sans-serif;
            font-size: 14px;
        }
        QMenuBar {
            background: #ffffff;
            border-bottom: 1px solid #dedede;
            padding: 4px;
        }
        QMenuBar::item:selected, QMenu::item:selected {
            background: #e9edf4;
            border-radius: 5px;
        }
        QMenu {
            background: #ffffff;
            border: 1px solid #d8d8d8;
            padding: 5px;
        }
        QPushButton {
            background: #ffffff;
            border: 1px solid #d5d9df;
            border-radius: 9px;
            padding: 9px 14px;
        }
        QPushButton:hover {
            background: #edf1f7;
        }
        QLineEdit {
            background: #ffffff;
            border: 1px solid #d5d9df;
            border-radius: 10px;
            padding: 10px 13px;
        }
        #pageTitle {
            font-size: 30px;
            font-weight: 700;
        }
        #muted {
            color: #747b85;
        }
        #bookCard {
            background: #ffffff;
            border: 1px solid #e0e3e8;
            border-radius: 15px;
            min-width: 210px;
            max-width: 260px;
        }
        #bookCard:hover {
            border: 1px solid #aeb8c7;
            background: #fbfcfe;
        }
        #bookIcon {
            font-size: 52px;
        }
        #bookTitle {
            font-size: 17px;
            font-weight: 650;
        }
        #bookAuthor {
            color: #6d7480;
        }
        #readerTop, #readerBottom {
            background: #ffffff;
            border-bottom: 1px solid #dedede;
        }
        #readerBottom {
            border-top: 1px solid #dedede;
            border-bottom: none;
        }
        #readerTitle {
            font-size: 16px;
            font-weight: 650;
        }
        #toc {
            background: #f8f9fb;
            border: none;
            border-right: 1px solid #e1e4e8;
            padding: 10px;
        }
        #toc::item {
            padding: 10px;
            border-radius: 7px;
        }
        #toc::item:selected {
            background: #e4eaf3;
            color: #202124;
        }
        QSlider::groove:horizontal {
            height: 4px;
            background: #d9dde3;
            border-radius: 2px;
        }
        QSlider::handle:horizontal {
            width: 14px;
            margin: -5px 0;
            border-radius: 7px;
            background: #68758a;
        }
        """)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("JASS")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

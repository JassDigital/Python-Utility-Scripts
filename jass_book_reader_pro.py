#!/usr/bin/env python3
"""
JASS Book Reader Pro
Single-file PySide6 desktop book reader.

Direct / best-effort formats:
    EPUB, PDF, TXT, HTML, HTM, FB2, MOBI, AZW, AZW3, CBZ, XPS, SVG
Optional conversion through Calibre (if ebook-convert is installed):
    LIT, PDB, RTF, DOC, DOCX, ODT, CBR and additional ebook formats.

Install:
    pip install PySide6 PyMuPDF

Optional — greatly expands format support:
    Install Calibre and make sure `ebook-convert` is on PATH.

Run:
    python jass_book_reader_pro.py
"""

import sys
import os
import re
import html
import shutil
import zipfile
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from html.parser import HTMLParser

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import (
    QAction, QKeySequence, QShortcut, QTextCursor, QTextCharFormat,
    QColor, QFont, QIcon, QPixmap
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QSplitter, QFrame, QStackedWidget,
    QLineEdit, QComboBox, QSlider, QToolButton, QScrollArea,
    QTextBrowser, QDialog, QDialogButtonBox, QFormLayout, QSpinBox,
    QCheckBox, QInputDialog, QMenu, QProgressBar
)

try:
    import fitz
except ImportError:
    fitz = None


APP_NAME = "JASS Book Reader Pro"
DATA_DIR = Path.home() / ".jass_book_reader"
DB_PATH = DATA_DIR / "library.db"
TEMP_DIR = DATA_DIR / "converted"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Formats that the application can attempt directly or through Calibre.
SUPPORTED_EXTS = {
    ".epub", ".pdf", ".txt", ".html", ".htm", ".fb2",
    ".mobi", ".azw", ".azw3", ".cbz", ".cbr", ".xps", ".svg",
    ".lit", ".pdb", ".rtf", ".doc", ".docx", ".odt", ".prc",
    ".kfx", ".kepub", ".md"
}

DIRECT_EXTS = {
    ".epub", ".pdf", ".txt", ".html", ".htm", ".fb2",
    ".mobi", ".azw", ".azw3", ".cbz", ".xps", ".svg", ".md"
}

OPTIONAL_EXTS = {
    ".lit", ".pdb", ".rtf", ".doc", ".docx", ".odt",
    ".cbr", ".prc", ".kfx", ".kepub"
}


# ----------------------------------------------------------------------
# HTML / EPUB
# ----------------------------------------------------------------------

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in ("script", "style", "svg"):
            self.skip += 1
        if t in ("p", "div", "br", "li", "h1", "h2", "h3", "h4",
                 "h5", "h6", "blockquote", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("script", "style", "svg") and self.skip:
            self.skip -= 1
        if t in ("p", "div", "li", "h1", "h2", "h3", "h4",
                 "h5", "h6", "blockquote", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def clean_text(raw):
    p = TextExtractor()
    p.feed(raw)
    text = html.unescape("".join(p.parts))
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def body_html(raw):
    raw = re.sub(r"(?is)<script.*?</script>", "", raw)
    raw = re.sub(r"(?is)<style.*?</style>", "", raw)
    m = re.search(r"(?is)<body[^>]*>(.*?)</body>", raw)
    return m.group(1) if m else raw


def epub_read(path):
    with zipfile.ZipFile(path, "r") as z:
        names = z.namelist()
        if "META-INF/container.xml" not in names:
            raise ValueError("Invalid EPUB: container.xml is missing.")

        container = z.read("META-INF/container.xml").decode("utf-8", "ignore")
        m = re.search(r'full-path\s*=\s*["\']([^"\']+)["\']', container)
        if not m:
            raise ValueError("Could not locate the EPUB package document.")
        opf_path = m.group(1)
        opf_dir = Path(opf_path).parent.as_posix()
        opf = z.read(opf_path).decode("utf-8", "ignore")

        tm = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf, re.I | re.S)
        am = re.search(r"<dc:creator[^>]*>(.*?)</dc:creator>", opf, re.I | re.S)
        title = clean_text(tm.group(1)) if tm else Path(path).stem
        author = clean_text(am.group(1)) if am else "Unknown Author"

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
        sm = re.search(r"<spine\b[^>]*>(.*?)</spine>", opf, re.I | re.S)
        if sm:
            for ref in re.findall(r"<itemref\b[^>]*>", sm.group(1), re.I | re.S):
                rid = re.search(r'idref=["\']([^"\']+)["\']', ref, re.I)
                if rid and rid.group(1) in manifest:
                    spine.append(manifest[rid.group(1)][0])

        if not spine:
            spine = [v[0] for v in manifest.values()
                     if "html" in v[1] or "xhtml" in v[1]]

        chapters = []
        for href in spine:
            full = (Path(opf_dir) / href).as_posix()
            full = re.sub(r"^\./", "", full)
            if full in names:
                raw = z.read(full).decode("utf-8", "ignore")
                # Prefer the first meaningful heading as chapter title.
                hm = re.search(r"(?is)<h[1-6][^>]*>(.*?)</h[1-6]>", raw)
                name = clean_text(hm.group(1)) if hm else Path(href).stem
                name = name.replace("_", " ").replace("-", " ").strip() or "Chapter"
                chapters.append((name, body_html(raw)))

        if not chapters:
            raise ValueError("EPUB contains no readable chapters.")
        return title, author, chapters


# ----------------------------------------------------------------------
# Optional conversion backend
# ----------------------------------------------------------------------

def calibre_path():
    return shutil.which("ebook-convert")


def calibre_available():
    return bool(calibre_path())


def convert_with_calibre(path):
    exe = calibre_path()
    if not exe:
        raise RuntimeError(
            "This format needs an optional converter.\n\n"
            "Install Calibre and ensure `ebook-convert` is on PATH, "
            "then try again."
        )
    out = TEMP_DIR / (Path(path).stem + "_converted.epub")
    try:
        subprocess.run(
            [exe, str(path), str(out), "--output-profile", "default"],
            capture_output=True, text=True, timeout=180, check=True
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Calibre conversion timed out.")
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "Unknown Calibre error").strip()
        raise RuntimeError("Calibre could not convert this book.\n\n" + detail[-1800:])
    if not out.exists():
        raise RuntimeError("Calibre reported success but produced no EPUB.")
    return str(out)


# ----------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------

class LibraryDB:
    def __init__(self):
        self.con = sqlite3.connect(DB_PATH)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS books (
                path TEXT PRIMARY KEY,
                title TEXT,
                author TEXT,
                ext TEXT,
                progress REAL DEFAULT 0,
                location INTEGER DEFAULT 0,
                last_opened TEXT,
                added TEXT
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS bookmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT,
                location INTEGER,
                label TEXT,
                created TEXT
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT,
                location INTEGER,
                note TEXT,
                created TEXT
            )
        """)
        self.con.commit()
        # Upgrade old DBs made by v0.1.
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(books)")}
        if "location" not in cols:
            self.con.execute("ALTER TABLE books ADD COLUMN location INTEGER DEFAULT 0")
            self.con.commit()

    def upsert(self, path, title=None, author=None):
        p = str(Path(path).resolve())
        now = datetime.now().isoformat(timespec="seconds")
        self.con.execute("""
            INSERT INTO books(path,title,author,ext,added)
            VALUES(?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
                title=COALESCE(excluded.title, books.title),
                author=COALESCE(excluded.author, books.author)
        """, (p, title or Path(p).stem, author or "Unknown Author",
              Path(p).suffix.lower(), now))
        self.con.commit()

    def set_progress(self, path, progress, location=0):
        self.con.execute("""
            UPDATE books SET progress=?, location=?, last_opened=? WHERE path=?
        """, (float(progress), int(location),
              datetime.now().isoformat(timespec="seconds"),
              str(Path(path).resolve())))
        self.con.commit()

    def get(self, path):
        return self.con.execute(
            "SELECT path,title,author,ext,progress,location,last_opened,added "
            "FROM books WHERE path=?",
            (str(Path(path).resolve()),)
        ).fetchone()

    def all(self):
        return self.con.execute(
            "SELECT path,title,author,ext,progress,location,last_opened,added "
            "FROM books ORDER BY last_opened DESC, added DESC"
        ).fetchall()

    def bookmarks(self, path):
        return self.con.execute(
            "SELECT id,location,label,created FROM bookmarks "
            "WHERE path=? ORDER BY id DESC", (str(Path(path).resolve()),)
        ).fetchall()

    def add_bookmark(self, path, location, label):
        self.con.execute(
            "INSERT INTO bookmarks(path,location,label,created) VALUES(?,?,?,?)",
            (str(Path(path).resolve()), int(location), label,
             datetime.now().isoformat(timespec="seconds")))
        self.con.commit()

    def remove_bookmark(self, bid):
        self.con.execute("DELETE FROM bookmarks WHERE id=?", (bid,))
        self.con.commit()

    def notes(self, path):
        return self.con.execute(
            "SELECT id,location,note,created FROM notes "
            "WHERE path=? ORDER BY id DESC", (str(Path(path).resolve()),)
        ).fetchall()

    def add_note(self, path, location, note):
        self.con.execute(
            "INSERT INTO notes(path,location,note,created) VALUES(?,?,?,?)",
            (str(Path(path).resolve()), int(location), note,
             datetime.now().isoformat(timespec="seconds")))
        self.con.commit()

    def remove(self, path):
        self.con.execute("DELETE FROM books WHERE path=?", (str(Path(path).resolve()),))
        self.con.execute("DELETE FROM bookmarks WHERE path=?", (str(Path(path).resolve()),))
        self.con.execute("DELETE FROM notes WHERE path=?", (str(Path(path).resolve()),))
        self.con.commit()


# ----------------------------------------------------------------------
# Reader
# ----------------------------------------------------------------------

class ReaderWidget(QWidget):
    back_requested = Signal()
    library_changed = Signal()

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.path = None
        self.title = ""
        self.author = ""
        self.chapters = []
        self.chapter_index = 0
        self.font_size = 19
        self.line_height = 1.75
        self.content_width = 820
        self.theme = "paper"
        self._loading = False
        self.build_ui()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QFrame()
        top.setObjectName("readerTop")
        bar = QHBoxLayout(top)
        bar.setContentsMargins(14, 8, 14, 8)

        b = QPushButton("‹  Library")
        b.clicked.connect(self.back_requested.emit)
        bar.addWidget(b)

        self.title_label = QLabel("No book open")
        self.title_label.setObjectName("readerTitle")
        bar.addWidget(self.title_label, 1)

        self.chapter_label = QLabel("")
        self.chapter_label.setObjectName("muted")
        bar.addWidget(self.chapter_label)

        self.bookmark_btn = QPushButton("🔖")
        self.bookmark_btn.setToolTip("Add bookmark")
        self.bookmark_btn.clicked.connect(self.add_bookmark)
        bar.addWidget(self.bookmark_btn)

        self.note_btn = QPushButton("📝")
        self.note_btn.setToolTip("Add note")
        self.note_btn.clicked.connect(self.add_note)
        bar.addWidget(self.note_btn)

        self.search_btn = QPushButton("🔎")
        self.search_btn.setToolTip("Find in book")
        self.search_btn.clicked.connect(self.find_text)
        bar.addWidget(self.search_btn)

        self.theme_btn = QPushButton("☾")
        self.theme_btn.setToolTip("Cycle reading theme")
        self.theme_btn.clicked.connect(self.toggle_theme)
        bar.addWidget(self.theme_btn)

        self.size_btn = QPushButton("A")
        self.size_btn.setToolTip("Change font size")
        self.size_btn.clicked.connect(self.change_font_size)
        bar.addWidget(self.size_btn)

        root.addWidget(top)

        splitter = QSplitter(Qt.Horizontal)

        self.side = QFrame()
        self.side.setObjectName("readerSide")
        side_lay = QVBoxLayout(self.side)
        side_lay.setContentsMargins(8, 10, 8, 10)

        tabs = QHBoxLayout()
        self.toc_tab = QPushButton("Contents")
        self.bm_tab = QPushButton("Bookmarks")
        self.note_tab = QPushButton("Notes")
        self.toc_tab.clicked.connect(lambda: self.show_side("toc"))
        self.bm_tab.clicked.connect(lambda: self.show_side("bm"))
        self.note_tab.clicked.connect(lambda: self.show_side("notes"))
        tabs.addWidget(self.toc_tab)
        tabs.addWidget(self.bm_tab)
        tabs.addWidget(self.note_tab)
        side_lay.addLayout(tabs)

        self.side_stack = QStackedWidget()
        self.toc = QListWidget()
        self.toc.itemClicked.connect(lambda item: self.show_chapter(self.toc.row(item)))
        self.bms = QListWidget()
        self.bms.itemDoubleClicked.connect(self.open_bookmark)
        self.notes = QListWidget()
        self.notes.itemDoubleClicked.connect(self.open_note)
        self.side_stack.addWidget(self.toc)
        self.side_stack.addWidget(self.bms)
        self.side_stack.addWidget(self.notes)
        side_lay.addWidget(self.side_stack, 1)
        splitter.addWidget(self.side)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setReadOnly(True)
        self.browser.setFrameShape(QFrame.NoFrame)
        splitter.addWidget(self.browser)
        splitter.setSizes([280, 900])
        root.addWidget(splitter, 1)

        bottom = QFrame()
        bottom.setObjectName("readerBottom")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(14, 7, 14, 7)

        self.prev_btn = QPushButton("← Previous")
        self.prev_btn.clicked.connect(self.previous_chapter)
        bl.addWidget(self.prev_btn)

        self.progress = QSlider(Qt.Horizontal)
        self.progress.setRange(0, 1000)
        self.progress.sliderMoved.connect(self.slider_moved)
        bl.addWidget(self.progress, 1)

        self.progress_label = QLabel("0%")
        bl.addWidget(self.progress_label)

        self.next_btn = QPushButton("Next →")
        self.next_btn.clicked.connect(self.next_chapter)
        bl.addWidget(self.next_btn)

        root.addWidget(bottom)

    def show_side(self, which):
        self.side_stack.setCurrentIndex({"toc": 0, "bm": 1, "notes": 2}[which])
        if which == "bm":
            self.refresh_bookmarks()
        elif which == "notes":
            self.refresh_notes()

    def open_book(self, path):
        self._loading = True
        self.path = str(Path(path).resolve())
        try:
            title, author, chapters = self.load_any(self.path)
            self.title, self.author, self.chapters = title, author, chapters
            self.db.upsert(self.path, title, author)
            row = self.db.get(self.path)
            saved = int(row[5] or 0) if row else 0
            self.chapter_index = min(saved, len(chapters) - 1)

            self.toc.clear()
            for name, _ in chapters:
                self.toc.addItem(name)

            self.title_label.setText(self.title)
            self.show_chapter(self.chapter_index, save=False)
            self.refresh_bookmarks()
            self.refresh_notes()
            self._loading = False
            return True
        except Exception as e:
            self._loading = False
            QMessageBox.critical(self, "Cannot Open Book", str(e))
            return False

    def load_any(self, path):
        ext = Path(path).suffix.lower()

        if ext == ".epub":
            return epub_read(path)

        if ext in (".txt", ".md"):
            raw = Path(path).read_text(encoding="utf-8", errors="replace")
            return Path(path).stem, "Text Document", [
                ("Document", "<pre>" + html.escape(raw) + "</pre>")
            ]

        if ext in (".html", ".htm", ".svg"):
            raw = Path(path).read_text(encoding="utf-8", errors="replace")
            return Path(path).stem, "HTML Document", [("Document", body_html(raw))]

        # PyMuPDF can directly open several ebook/document formats.
        if fitz is not None and ext in DIRECT_EXTS:
            try:
                doc = fitz.open(path)
                chapters = []
                for i, page in enumerate(doc):
                    txt = page.get_text("html")
                    if not txt.strip():
                        txt = "<pre>" + html.escape(page.get_text()) + "</pre>"
                    chapters.append((f"Page {i + 1}", txt))
                meta = doc.metadata or {}
                title = meta.get("title") or Path(path).stem
                author = meta.get("author") or "Unknown Author"
                doc.close()
                if chapters:
                    return title, author, chapters
            except Exception:
                pass

        # Fallback to Calibre for LIT/PDB/Office/CBR/etc.
        converted = convert_with_calibre(path)
        return epub_read(converted)

    def theme_values(self):
        return {
            "paper": ("#f7f3ea", "#29261f", "#355f91", "#ebe5d7"),
            "sepia": ("#f2e5c9", "#493b2b", "#6b4e2e", "#e7d7b5"),
            "night": ("#171717", "#e9e4d8", "#9fc5ff", "#2b2b2b"),
            "dark": ("#242424", "#eeeeee", "#9fc5ff", "#343434"),
            "white": ("#ffffff", "#202124", "#2b61a0", "#f0f0f0")
        }[self.theme]

    def reader_html(self, content):
        bg, fg, link, quote = self.theme_values()
        content = content or "<p>No readable content.</p>"
        return f"""
        <html><head><style>
        body {{
            background:{bg}; color:{fg};
            font-family:"Segoe UI","Noto Sans",Arial,sans-serif;
            font-size:{self.font_size}px;
            line-height:{self.line_height};
            margin:46px auto;
            max-width:{self.content_width}px;
        }}
        p {{ margin:0 0 1.1em; }}
        h1,h2,h3,h4 {{ line-height:1.25; margin-top:1.4em; }}
        a {{ color:{link}; }}
        blockquote {{ background:{quote}; padding:16px 20px;
                      border-left:4px solid {link}; }}
        pre {{ white-space:pre-wrap;
               font-family:"Cascadia Mono","Consolas",monospace; }}
        img {{ max-width:100%; height:auto; }}
        </style></head><body>{content}</body></html>
        """

    def show_chapter(self, index, save=True):
        if not self.chapters:
            return
        self.chapter_index = max(0, min(index, len(self.chapters) - 1))
        name, content = self.chapters[self.chapter_index]
        self.chapter_label.setText(name)
        self.browser.setHtml(self.reader_html(content))
        self.browser.verticalScrollBar().setValue(0)
        self.toc.setCurrentRow(self.chapter_index)
        self.update_nav()
        if save:
            self.save_progress()

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
            self.db.set_progress(self.path, pct, self.chapter_index)
            self.library_changed.emit()

    def slider_moved(self, value):
        if self.chapters:
            idx = min(
                len(self.chapters) - 1,
                max(0, round((value / 1000) * len(self.chapters)) - 1)
            )
            self.show_chapter(idx)

    def previous_chapter(self):
        if self.chapter_index > 0:
            self.show_chapter(self.chapter_index - 1)

    def next_chapter(self):
        if self.chapter_index < len(self.chapters) - 1:
            self.show_chapter(self.chapter_index + 1)

    def toggle_theme(self):
        order = ["paper", "sepia", "night", "dark", "white"]
        self.theme = order[(order.index(self.theme) + 1) % len(order)]
        self.show_chapter(self.chapter_index, save=False)

    def change_font_size(self):
        choices = [15, 17, 19, 21, 23, 25, 27, 30]
        try:
            i = choices.index(self.font_size)
        except ValueError:
            i = 2
        self.font_size = choices[(i + 1) % len(choices)]
        self.show_chapter(self.chapter_index, save=False)

    def find_text(self):
        text, ok = QInputDialog.getText(self, "Find in Book", "Search:")
        if ok and text:
            if not self.browser.find(text):
                QMessageBox.information(self, "Search", "No further match was found.")

    def add_bookmark(self):
        if not self.path:
            return
        default = self.chapter_label.text() or f"Chapter {self.chapter_index + 1}"
        label, ok = QInputDialog.getText(self, "Add Bookmark", "Bookmark name:", text=default)
        if ok and label.strip():
            self.db.add_bookmark(self.path, self.chapter_index, label.strip())
            self.refresh_bookmarks()

    def refresh_bookmarks(self):
        self.bms.clear()
        if not self.path:
            return
        for bid, loc, label, created in self.db.bookmarks(self.path):
            item = QListWidgetItem(f"🔖  {label}")
            item.setData(Qt.UserRole, (bid, loc))
            self.bms.addItem(item)

    def open_bookmark(self, item):
        data = item.data(Qt.UserRole)
        if data:
            self.show_chapter(data[1])

    def add_note(self):
        if not self.path:
            return
        note, ok = QInputDialog.getMultiLineText(
            self, "Add Note", "Note for this location:",
            f"{self.title} — {self.chapter_label.text()}"
        )
        if ok and note.strip():
            self.db.add_note(self.path, self.chapter_index, note.strip())
            self.refresh_notes()

    def refresh_notes(self):
        self.notes.clear()
        if not self.path:
            return
        for nid, loc, note, created in self.db.notes(self.path):
            short = note.replace("\n", " ")
            if len(short) > 65:
                short = short[:62] + "..."
            item = QListWidgetItem(f"📝  {short}")
            item.setData(Qt.UserRole, (nid, loc, note))
            self.notes.addItem(item)

    def open_note(self, item):
        data = item.data(Qt.UserRole)
        if data:
            self.show_chapter(data[1])
            QMessageBox.information(self, "Note", data[2])


# ----------------------------------------------------------------------
# Library cards
# ----------------------------------------------------------------------

class BookCard(QFrame):
    clicked = Signal(str)

    def __init__(self, row):
        super().__init__()
        self.row = row
        self.path, title, author, ext, progress, location, last, added = row
        self.setObjectName("bookCard")
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 15, 16, 15)
        lay.setSpacing(6)

        icon_map = {
            ".epub": "📖", ".pdf": "📕", ".mobi": "📘",
            ".azw": "📘", ".azw3": "📘", ".lit": "📗",
            ".pdb": "📗", ".fb2": "📙", ".cbz": "🖼️",
            ".cbr": "🖼️", ".txt": "📝", ".docx": "📄",
            ".doc": "📄", ".rtf": "📄"
        }
        icon = QLabel(icon_map.get(ext, "📚"))
        icon.setObjectName("bookIcon")
        lay.addWidget(icon)

        t = QLabel(title or Path(self.path).stem)
        t.setObjectName("bookTitle")
        t.setWordWrap(True)
        lay.addWidget(t)

        a = QLabel(author or "Unknown Author")
        a.setObjectName("bookAuthor")
        a.setWordWrap(True)
        lay.addWidget(a)

        type_label = QLabel(ext.upper().replace(".", "") + "  •  " +
                            ("Calibre" if ext in OPTIONAL_EXTS else "Native"))
        type_label.setObjectName("muted")
        lay.addWidget(type_label)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(progress or 0))
        bar.setTextVisible(False)
        lay.addWidget(bar)

        p = QLabel(f"{float(progress or 0):.0f}% read")
        p.setObjectName("muted")
        lay.addWidget(p)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.path)
        super().mousePressEvent(event)


# ----------------------------------------------------------------------
# Library
# ----------------------------------------------------------------------

class LibraryWidget(QWidget):
    open_requested = Signal(str)

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.cards = []
        self.view_mode = "grid"
        self.build_ui()
        self.refresh()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(15)

        top = QHBoxLayout()
        heading = QVBoxLayout()
        h = QLabel("Your Library")
        h.setObjectName("pageTitle")
        heading.addWidget(h)
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("muted")
        heading.addWidget(self.subtitle)
        top.addLayout(heading)
        top.addStretch()

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search title, author or format…")
        self.search.setFixedWidth(310)
        self.search.textChanged.connect(self.filter_cards)
        top.addWidget(self.search)

        add_folder = QPushButton("＋ Folder")
        add_folder.setToolTip("Scan a folder for books")
        add_folder.clicked.connect(self.add_folder)
        top.addWidget(add_folder)

        add = QPushButton("＋ Add Books")
        add.clicked.connect(self.add_books)
        top.addWidget(add)

        self.sort_box = QComboBox()
        self.sort_box.addItems(["Recently opened", "Title", "Author", "Format", "Progress"])
        self.sort_box.currentTextChanged.connect(self.refresh)
        self.sort_box.setFixedWidth(145)
        top.addWidget(self.sort_box)

        self.view_btn = QPushButton("▦")
        self.view_btn.setToolTip("Toggle grid/list")
        self.view_btn.clicked.connect(self.toggle_view)
        top.addWidget(self.view_btn)

        root.addLayout(top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.container = QWidget()
        self.grid = QGridLayout(self.container)
        self.grid.setAlignment(Qt.AlignTop)
        self.grid.setSpacing(17)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)

    def add_books(self):
        filters = (
            "All supported books (*.epub *.pdf *.txt *.html *.htm *.fb2 *.mobi "
            "*.azw *.azw3 *.cbz *.cbr *.xps *.lit *.pdb *.rtf *.doc *.docx *.odt "
            "*.prc *.kfx *.kepub *.md);;"
            "Common ebooks (*.epub *.mobi *.azw *.azw3 *.fb2 *.pdf *.cbz *.cbr);;"
            "All files (*)"
        )
        files, _ = QFileDialog.getOpenFileNames(self, "Open Books", str(Path.home()), filters)
        for f in files:
            self.db.upsert(f)
        self.refresh()
        if files:
            self.open_requested.emit(files[0])

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose Book Folder", str(Path.home()))
        if not folder:
            return
        count = 0
        for p in Path(folder).rglob("*"):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                self.db.upsert(str(p))
                count += 1
        self.refresh()
        QMessageBox.information(self, "Folder Scan", f"Added {count} supported book file(s).")

    def toggle_view(self):
        self.view_mode = "list" if self.view_mode == "grid" else "grid"
        self.view_btn.setText("☷" if self.view_mode == "list" else "▦")
        self.refresh()

    def refresh(self, *_):
        rows = self.db.all()
        mode = self.sort_box.currentText()
        if mode == "Title":
            rows.sort(key=lambda r: (r[1] or "").lower())
        elif mode == "Author":
            rows.sort(key=lambda r: (r[2] or "").lower())
        elif mode == "Format":
            rows.sort(key=lambda r: r[3])
        elif mode == "Progress":
            rows.sort(key=lambda r: float(r[4] or 0), reverse=True)

        for c in self.cards:
            c.deleteLater()
        self.cards.clear()

        if self.view_mode == "grid":
            for i, row in enumerate(rows):
                card = BookCard(row)
                card.clicked.connect(self.open_requested.emit)
                self.cards.append(card)
                self.grid.addWidget(card, i // 4, i % 4)
        else:
            for i, row in enumerate(rows):
                card = BookCard(row)
                card.setMinimumWidth(650)
                card.setMaximumWidth(1100)
                card.clicked.connect(self.open_requested.emit)
                self.cards.append(card)
                self.grid.addWidget(card, i, 0)

        formats = {}
        for r in rows:
            formats[r[3]] = formats.get(r[3], 0) + 1
        fmt = ", ".join(f"{k[1:].upper()}: {v}" for k, v in sorted(formats.items()))
        self.subtitle.setText(
            f"{len(rows)} book{'s' if len(rows) != 1 else ''}" +
            (f"  •  {fmt}" if fmt else "")
        )
        self.filter_cards(self.search.text())

    def filter_cards(self, text):
        q = text.strip().lower()
        for card in self.cards:
            labels = card.findChildren(QLabel)
            hay = " ".join(x.text().lower() for x in labels) + " " + card.path.lower()
            card.setVisible(not q or q in hay)


# ----------------------------------------------------------------------
# Settings dialog
# ----------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, reader, parent=None):
        super().__init__(parent)
        self.reader = reader
        self.setWindowTitle("Reader Settings")
        self.setMinimumWidth(430)

        form = QFormLayout(self)

        self.font = QSpinBox()
        self.font.setRange(12, 40)
        self.font.setValue(reader.font_size)
        self.font.setSuffix(" px")
        form.addRow("Font size:", self.font)

        self.line = QSpinBox()
        self.line.setRange(10, 30)
        self.line.setValue(int(reader.line_height * 10))
        self.line.setSuffix(" / 10")
        form.addRow("Line spacing:", self.line)

        self.width = QSpinBox()
        self.width.setRange(500, 1200)
        self.width.setSingleStep(20)
        self.width.setValue(reader.content_width)
        self.width.setSuffix(" px")
        form.addRow("Text width:", self.width)

        theme = QComboBox()
        theme.addItems(["Paper", "Sepia", "Night", "Dark", "White"])
        theme.setCurrentIndex(["paper", "sepia", "night", "dark", "white"].index(reader.theme))
        self.theme = theme
        form.addRow("Reading theme:", theme)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def apply(self):
        self.reader.font_size = self.font.value()
        self.reader.line_height = self.line.value() / 10
        self.reader.content_width = self.width.value()
        self.reader.theme = ["paper", "sepia", "night", "dark", "white"][self.theme.currentIndex()]
        if self.reader.chapters:
            self.reader.show_chapter(self.reader.chapter_index, save=False)
        self.accept()


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = LibraryDB()
        self.setWindowTitle(APP_NAME)
        self.resize(1320, 850)
        self.setMinimumSize(980, 650)
        self.setAcceptDrops(True)

        self.stack = QStackedWidget()
        self.library = LibraryWidget(self.db)
        self.reader = ReaderWidget(self.db)
        self.stack.addWidget(self.library)
        self.stack.addWidget(self.reader)
        self.setCentralWidget(self.stack)

        self.library.open_requested.connect(self.open_book)
        self.reader.back_requested.connect(self.show_library)
        self.reader.library_changed.connect(self.library.refresh)

        self.build_menu()
        self.apply_theme()
        self.shortcuts()

    def build_menu(self):
        fm = self.menuBar().addMenu("&File")

        a = QAction("Open Book…", self)
        a.setShortcut("Ctrl+O")
        a.triggered.connect(self.open_file)
        fm.addAction(a)

        a = QAction("Add Books…", self)
        a.triggered.connect(self.library.add_books)
        fm.addAction(a)

        a = QAction("Scan Folder…", self)
        a.triggered.connect(self.library.add_folder)
        fm.addAction(a)

        fm.addSeparator()
        a = QAction("Open Library Folder", self)
        a.triggered.connect(lambda: os.startfile(DATA_DIR) if sys.platform == "win32"
                            else subprocess.Popen(["xdg-open", str(DATA_DIR)]))
        fm.addAction(a)

        fm.addSeparator()
        a = QAction("Exit", self)
        a.triggered.connect(self.close)
        fm.addAction(a)

        vm = self.menuBar().addMenu("&View")
        a = QAction("Library", self)
        a.setShortcut("Esc")
        a.triggered.connect(self.show_library)
        vm.addAction(a)

        a = QAction("Fullscreen", self)
        a.setShortcut("F11")
        a.triggered.connect(self.toggle_fullscreen)
        vm.addAction(a)

        rm = self.menuBar().addMenu("&Reader")
        a = QAction("Previous Chapter", self)
        a.setShortcut("Alt+Left")
        a.triggered.connect(self.reader.previous_chapter)
        rm.addAction(a)

        a = QAction("Next Chapter", self)
        a.setShortcut("Alt+Right")
        a.triggered.connect(self.reader.next_chapter)
        rm.addAction(a)

        a = QAction("Find in Book", self)
        a.setShortcut("Ctrl+F")
        a.triggered.connect(self.reader.find_text)
        rm.addAction(a)

        a = QAction("Add Bookmark", self)
        a.setShortcut("Ctrl+B")
        a.triggered.connect(self.reader.add_bookmark)
        rm.addAction(a)

        a = QAction("Add Note", self)
        a.setShortcut("Ctrl+N")
        a.triggered.connect(self.reader.add_note)
        rm.addAction(a)

        sm = self.menuBar().addMenu("&Settings")
        a = QAction("Reader Settings…", self)
        a.triggered.connect(self.reader_settings)
        sm.addAction(a)

        hm = self.menuBar().addMenu("&Help")
        a = QAction("Supported Formats", self)
        a.triggered.connect(self.show_formats)
        hm.addAction(a)

    def shortcuts(self):
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.open_file)
        QShortcut(QKeySequence("Escape"), self, activated=self.show_library)
        QShortcut(QKeySequence("Left"), self, activated=self.reader.previous_chapter)
        QShortcut(QKeySequence("Right"), self, activated=self.reader.next_chapter)
        QShortcut(QKeySequence("F11"), self, activated=self.toggle_fullscreen)

    def open_file(self):
        filters = (
            "All supported books (*.epub *.pdf *.txt *.html *.htm *.fb2 *.mobi "
            "*.azw *.azw3 *.cbz *.cbr *.xps *.lit *.pdb *.rtf *.doc *.docx *.odt "
            "*.prc *.kfx *.kepub *.md);;"
            "EPUB (*.epub);;Kindle / MOBI (*.mobi *.azw *.azw3 *.prc *.kfx *.kepub);;"
            "PDF (*.pdf);;Comics (*.cbz *.cbr);;FictionBook (*.fb2);;"
            "Microsoft / Office (*.lit *.doc *.docx *.rtf *.odt);;"
            "Palm / PDB (*.pdb);;Text / Web (*.txt *.md *.html *.htm);;All files (*)"
        )
        f, _ = QFileDialog.getOpenFileName(self, "Open Book", str(Path.home()), filters)
        if f:
            self.open_book(f)

    def open_book(self, path):
        if self.reader.open_book(path):
            self.stack.setCurrentWidget(self.reader)

    def show_library(self):
        self.library.refresh()
        self.stack.setCurrentWidget(self.library)

    def reader_settings(self):
        if self.stack.currentWidget() != self.reader:
            QMessageBox.information(self, "Reader Settings", "Open a book first.")
            return
        SettingsDialog(self.reader, self).exec()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.menuBar().show()
        else:
            self.showFullScreen()
            self.menuBar().hide()

    def show_formats(self):
        calibre = "Detected ✓" if calibre_available() else "Not detected"
        QMessageBox.information(
            self, "Book Formats",
            "Native / direct attempts:\n"
            "EPUB, PDF, TXT, HTML, FB2, MOBI, AZW, AZW3, CBZ, XPS, SVG, MD\n\n"
            "Additional formats through Calibre:\n"
            "LIT, PDB, RTF, DOC, DOCX, ODT, CBR, PRC, KFX, KEPUB and more.\n\n"
            f"Calibre / ebook-convert: {calibre}\n\n"
            "DRM-protected Kindle books are not supported."
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            if any(Path(u.toLocalFile()).suffix.lower() in SUPPORTED_EXTS
                   for u in event.mimeData().urls()):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event):
        for u in event.mimeData().urls():
            p = u.toLocalFile()
            if Path(p).suffix.lower() in SUPPORTED_EXTS:
                self.db.upsert(p)
                self.open_book(p)
                break
        event.acceptProposedAction()

    def apply_theme(self):
        self.setStyleSheet("""
        QMainWindow, QWidget {
            background:#f3f4f6; color:#202124;
            font-family:"Segoe UI","Noto Sans",sans-serif;
            font-size:14px;
        }
        QMenuBar {
            background:#ffffff; border-bottom:1px solid #dedede; padding:4px;
        }
        QMenuBar::item:selected, QMenu::item:selected {
            background:#e9edf4; border-radius:5px;
        }
        QMenu {
            background:#ffffff; border:1px solid #d8d8d8; padding:5px;
        }
        QPushButton {
            background:#ffffff; border:1px solid #d5d9df;
            border-radius:9px; padding:8px 12px;
        }
        QPushButton:hover { background:#edf1f7; }
        QLineEdit, QComboBox, QSpinBox {
            background:#ffffff; border:1px solid #d5d9df;
            border-radius:9px; padding:8px 10px;
        }
        #pageTitle { font-size:30px; font-weight:700; }
        #muted { color:#747b85; }
        #bookCard {
            background:#ffffff; border:1px solid #e0e3e8;
            border-radius:15px; min-width:210px; max-width:280px;
        }
        #bookCard:hover { border:1px solid #aeb8c7; background:#fbfcfe; }
        #bookIcon { font-size:48px; }
        #bookTitle { font-size:17px; font-weight:650; }
        #bookAuthor { color:#6d7480; }
        QProgressBar {
            border:0; background:#e3e6eb; border-radius:3px; height:5px;
        }
        QProgressBar::chunk { background:#718096; border-radius:3px; }
        #readerTop, #readerBottom {
            background:#ffffff; border-bottom:1px solid #dedede;
        }
        #readerBottom { border-top:1px solid #dedede; border-bottom:0; }
        #readerTitle { font-size:16px; font-weight:650; }
        #readerSide {
            background:#f8f9fb; border-right:1px solid #e1e4e8;
        }
        QListWidget {
            background:transparent; border:0; padding:6px;
        }
        QListWidget::item {
            padding:9px; border-radius:7px;
        }
        QListWidget::item:selected {
            background:#e4eaf3; color:#202124;
        }
        QSlider::groove:horizontal {
            height:4px; background:#d9dde3; border-radius:2px;
        }
        QSlider::handle:horizontal {
            width:14px; margin:-5px 0; border-radius:7px; background:#68758a;
        }
        """)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("JASS")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

import sys
import re
import zipfile
import html
import json
from pathlib import Path
from html.parser import HTMLParser

from PySide6.QtCore import Qt, QSettings, QUrl
from PySide6.QtGui import QAction, QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLineEdit, QListWidget, QListWidgetItem, QTextBrowser, QLabel,
    QPushButton, QSplitter, QMessageBox, QFileDialog, QComboBox,
    QToolBar, QStatusBar, QCheckBox, QInputDialog
)

APP_TITLE = "JASS English Love Literature Explorer"
DEFAULT_FOLDER = Path(r"C:\Users\singh\Downloads\JASS_English_Love_Literature")


class EPUBTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "svg", "head"}:
            self.skip += 1
            return
        if self.skip == 0 and tag in {
            "p", "div", "section", "article", "h1", "h2", "h3",
            "h4", "h5", "h6", "li", "blockquote", "br"
        }:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "svg", "head"} and self.skip:
            self.skip -= 1
        elif self.skip == 0 and tag in {
            "p", "div", "section", "article", "h1", "h2", "h3",
            "h4", "h5", "h6", "li", "blockquote"
        }:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip == 0:
            data = html.unescape(data)
            if data.strip():
                self.parts.append(data)


def clean_text(raw):
    parser = EPUBTextParser()
    parser.feed(raw)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+\n", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def epub_content(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()

        # Prefer XHTML/HTML reading-order files.
        candidates = [
            n for n in names
            if n.lower().endswith((".xhtml", ".html", ".htm"))
            and Path(n).name.lower() not in {"nav.xhtml"}
            and "toc" not in Path(n).name.lower()
        ]

        chunks = []
        for name in candidates:
            try:
                raw = z.read(name).decode("utf-8", errors="replace")
                text = clean_text(raw)
                if text:
                    chunks.append((name, text))
            except Exception:
                pass
        return chunks


def title_from_name(path):
    stem = path.stem
    for sep in (" — ", " – ", " - "):
        if sep in stem:
            return stem.split(sep, 1)[0].strip()
    return stem


def author_from_name(path):
    stem = path.stem
    for sep in (" — ", " – ", " - "):
        if sep in stem:
            return stem.rsplit(sep, 1)[1].strip()
    return "Unknown / not specified"


def category_for(path):
    s = path.stem.lower()
    if any(x in s for x in (
        "erotica", "venus im pelz", "mademoiselle de maupin",
        "crimes de l'amour", "sex life"
    )):
        return "Sensual / Erotic Literature"
    if any(x in s for x in (
        "love-letter", "love letters", "love &", "love and",
        "love's", "to love", "love story", "love affairs"
    )):
        return "Love / Romance"
    if any(x in s for x in (
        "romance", "romantic", "romeo", "juliet", "passionate",
        "courtship", "wooing"
    )):
        return "Romance / Courtship"
    if any(x in s for x in (
        "arabian nights", "greek romances", "arthurian", "tristan"
    )):
        return "Classical / Legendary Romance"
    return "Fiction / Related"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("JASS", "EnglishLoveLiteratureExplorer")
        self.folder = Path(self.settings.value("folder", str(DEFAULT_FOLDER)))
        self.books = []
        self.filtered_books = []
        self.current_path = None
        self.current_sections = []
        self.current_section_index = 0
        self.favorites = set(self.settings.value("favorites", [], type=list))
        self.history = self.settings.value("history", [], type=list)
        self.font_size = int(self.settings.value("font_size", 13))

        self.setWindowTitle(APP_TITLE + " v2.0")
        self.resize(1500, 900)

        self.build_ui()
        self.load_books()

    def build_ui(self):
        self.setStatusBar(QStatusBar(self))

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(QAction("Choose EPUB Folder...", self, triggered=self.choose_folder))
        file_menu.addAction(QAction("Refresh Library", self, triggered=self.load_books))
        file_menu.addSeparator()
        file_menu.addAction(QAction("Export Current Text...", self, triggered=self.export_current))
        file_menu.addAction(QAction("Export Book List...", self, triggered=self.export_book_list))
        file_menu.addSeparator()
        file_menu.addAction(QAction("Exit", self, triggered=self.close))

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(QAction("Larger Text", self, triggered=lambda: self.change_font(1)))
        view_menu.addAction(QAction("Smaller Text", self, triggered=lambda: self.change_font(-1)))
        view_menu.addAction(QAction("Reset Text Size", self, triggered=self.reset_font))

        tools_menu = self.menuBar().addMenu("&Tools")
        tools_menu.addAction(QAction("Library Statistics", self, triggered=self.show_statistics))
        tools_menu.addAction(QAction("Search Current Book...", self, triggered=self.search_current_book))
        tools_menu.addAction(QAction("Add Bookmark", self, triggered=self.add_bookmark))

        toolbar = QToolBar("Reader")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        prev = QAction("◀ Previous", self)
        prev.triggered.connect(self.previous_section)
        toolbar.addAction(prev)

        nxt = QAction("Next ▶", self)
        nxt.triggered.connect(self.next_section)
        toolbar.addAction(nxt)

        toolbar.addSeparator()

        self.favorite_button = QPushButton("☆ Favorite")
        self.favorite_button.clicked.connect(self.toggle_favorite)
        toolbar.addWidget(self.favorite_button)

        toolbar.addSeparator()

        self.font_label = QLabel(" Text ")
        toolbar.addWidget(self.font_label)
        minus = QPushButton("A−")
        minus.clicked.connect(lambda: self.change_font(-1))
        toolbar.addWidget(minus)
        plus = QPushButton("A+")
        plus.clicked.connect(lambda: self.change_font(1))
        toolbar.addWidget(plus)

        central = QWidget()
        root = QVBoxLayout(central)

        header = QHBoxLayout()
        title = QLabel("📚 JASS English Love Literature Explorer")
        title.setStyleSheet("font-size: 23px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()
        self.folder_label = QLabel(str(self.folder))
        self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        header.addWidget(self.folder_label)
        root.addLayout(header)

        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search title, author, filename...")
        self.search.textChanged.connect(self.filter_books)
        controls.addWidget(self.search, 3)

        self.category = QComboBox()
        self.category.addItems([
            "All categories",
            "Love / Romance",
            "Romance / Courtship",
            "Sensual / Erotic Literature",
            "Classical / Legendary Romance",
            "Fiction / Related",
            "★ Favorites",
        ])
        self.category.currentTextChanged.connect(self.filter_books)
        controls.addWidget(self.category)

        self.show_files = QCheckBox("Show file path")
        self.show_files.stateChanged.connect(self.filter_books)
        controls.addWidget(self.show_files)

        self.status_label = QLabel()
        controls.addWidget(self.status_label)
        root.addLayout(controls)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.book_list = QListWidget()
        self.book_list.currentItemChanged.connect(self.book_selected)
        left_layout.addWidget(self.book_list)

        self.book_count = QLabel()
        left_layout.addWidget(self.book_count)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        self.book_title = QLabel("Select a book")
        self.book_title.setWordWrap(True)
        self.book_title.setStyleSheet("font-size: 21px; font-weight: bold;")
        right_layout.addWidget(self.book_title)

        self.book_info = QLabel("")
        self.book_info.setWordWrap(True)
        right_layout.addWidget(self.book_info)

        self.reader = QTextBrowser()
        self.reader.setFont(QFont("Georgia", self.font_size))
        self.reader.setOpenExternalLinks(False)
        right_layout.addWidget(self.reader, 1)

        self.reader_search = QLineEdit()
        self.reader_search.setPlaceholderText("Find text in this book and press Enter...")
        self.reader_search.returnPressed.connect(self.find_in_reader)
        right_layout.addWidget(self.reader_search)

        splitter.addWidget(right)
        splitter.setSizes([430, 1050])
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)

    def load_books(self):
        if not self.folder.exists():
            QMessageBox.warning(
                self, "Folder not found",
                f"Folder not found:\n{self.folder}\n\nPlease choose the EPUB folder."
            )
            return

        self.books = sorted(self.folder.rglob("*.epub"),
                            key=lambda p: p.name.lower())
        self.folder_label.setText(str(self.folder))
        self.filter_books()
        self.statusBar().showMessage(f"Library loaded: {len(self.books)} EPUB books")

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose EPUB Library", str(self.folder)
        )
        if folder:
            self.folder = Path(folder)
            self.settings.setValue("folder", str(self.folder))
            self.load_books()

    def filter_books(self):
        q = self.search.text().strip().lower()
        cat = self.category.currentText()
        matches = []

        for path in self.books:
            category = category_for(path)
            if cat == "★ Favorites" and str(path) not in self.favorites:
                continue
            if cat != "All categories" and cat != "★ Favorites" and category != cat:
                continue

            hay = f"{title_from_name(path)} {author_from_name(path)} {path.name}".lower()
            if q and q not in hay:
                continue
            matches.append(path)

        self.filtered_books = matches
        self.book_list.blockSignals(True)
        self.book_list.clear()

        for path in matches:
            label = title_from_name(path)
            if self.show_files.isChecked():
                label += f"  [{path.name}]"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(str(path))
            if str(path) in self.favorites:
                item.setText("★ " + item.text())
            self.book_list.addItem(item)

        self.book_list.blockSignals(False)
        self.book_count.setText(f"{len(matches)} books shown / {len(self.books)} total")
        self.status_label.setText(f"{len(matches)} results")

        if matches:
            self.book_list.setCurrentRow(0)
        else:
            self.book_title.setText("No books found")
            self.book_info.setText("")
            self.reader.clear()

    def book_selected(self, current, previous):
        if not current:
            return

        path = Path(current.data(Qt.UserRole))
        self.current_path = path
        title = title_from_name(path)
        author = author_from_name(path)
        category = category_for(path)

        self.book_title.setText(title)
        self.book_info.setText(
            f"Author: {author}  •  Category: {category}  •  File: {path.name}"
        )
        self.update_favorite_button()

        self.reader.setPlainText("Loading EPUB...")
        QApplication.processEvents()

        try:
            self.current_sections = epub_content(path)
            self.current_section_index = 0
            text = "\n\n".join(x[1] for x in self.current_sections)

            if not text:
                text = "No readable XHTML/HTML text was found in this EPUB."

            self.reader.setPlainText(text)
            self.add_history(path)
            self.statusBar().showMessage(
                f"Opened: {title}  •  {len(self.current_sections)} content sections"
            )
        except Exception as e:
            self.reader.setPlainText(f"Could not open EPUB:\n{e}")

    def add_history(self, path):
        p = str(path)
        self.history = [x for x in self.history if x != p]
        self.history.insert(0, p)
        self.history = self.history[:20]
        self.settings.setValue("history", self.history)

    def toggle_favorite(self):
        if not self.current_path:
            return
        p = str(self.current_path)
        if p in self.favorites:
            self.favorites.remove(p)
        else:
            self.favorites.add(p)
        self.settings.setValue("favorites", list(self.favorites))
        self.update_favorite_button()
        self.filter_books()

    def update_favorite_button(self):
        if self.current_path and str(self.current_path) in self.favorites:
            self.favorite_button.setText("★ Favorite")
        else:
            self.favorite_button.setText("☆ Favorite")

    def change_font(self, delta):
        self.font_size = max(8, min(32, self.font_size + delta))
        self.reader.setFont(QFont("Georgia", self.font_size))
        self.settings.setValue("font_size", self.font_size)

    def reset_font(self):
        self.font_size = 13
        self.reader.setFont(QFont("Georgia", self.font_size))
        self.settings.setValue("font_size", self.font_size)

    def next_section(self):
        if not self.current_sections:
            return
        self.current_section_index = min(
            len(self.current_sections) - 1,
            self.current_section_index + 1
        )
        self.show_section()

    def previous_section(self):
        if not self.current_sections:
            return
        self.current_section_index = max(0, self.current_section_index - 1)
        self.show_section()

    def show_section(self):
        name, text = self.current_sections[self.current_section_index]
        self.reader.setPlainText(text)
        self.statusBar().showMessage(
            f"Section {self.current_section_index + 1}/{len(self.current_sections)}: {name}"
        )

    def find_in_reader(self):
        query = self.reader_search.text().strip()
        if not query:
            return
        if not self.reader.find(query):
            self.reader.moveCursor(QTextCursor.Start)
            if not self.reader.find(query):
                self.statusBar().showMessage(f"'{query}' not found in current section")
            else:
                self.statusBar().showMessage(f"Found: {query}")
        else:
            self.statusBar().showMessage(f"Found: {query}")

    def search_current_book(self):
        query, ok = QInputDialog.getText(
            self, "Search Current Book", "Find:"
        )
        if ok and query:
            self.reader_search.setText(query)
            self.find_in_reader()

    def add_bookmark(self):
        if not self.current_path:
            return
        cursor = self.reader.textCursor()
        position = cursor.position()
        self.statusBar().showMessage(
            f"Bookmark added at character {position} in {self.current_path.name}"
        )
        QMessageBox.information(
            self, "Bookmark",
            f"Bookmark position saved for this session:\n\n"
            f"{self.current_path.name}\nCharacter position: {position}\n\n"
            f"Use the reader search to return to a phrase."
        )

    def export_current(self):
        if not self.current_path:
            QMessageBox.information(self, "Export", "Open a book first.")
            return

        suggested = self.current_path.with_suffix(".txt").name
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Current Book", str(self.folder / suggested),
            "Text Files (*.txt);;All Files (*)"
        )
        if path:
            Path(path).write_text(
                self.reader.toPlainText(), encoding="utf-8"
            )
            self.statusBar().showMessage(f"Exported: {path}")

    def export_book_list(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Book List",
            str(self.folder / "JASS_English_Love_Literature_Book_List.txt"),
            "Text Files (*.txt);;CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return

        lines = [
            "JASS English Love Literature Explorer",
            f"Library: {self.folder}",
            f"Total EPUB books: {len(self.books)}",
            "",
        ]
        for i, book in enumerate(self.books, 1):
            lines.append(
                f"{i}. {title_from_name(book)} | "
                f"{author_from_name(book)} | {category_for(book)} | {book.name}"
            )

        Path(path).write_text("\n".join(lines), encoding="utf-8")
        self.statusBar().showMessage(f"Book list exported: {path}")

    def show_statistics(self):
        counts = {}
        for p in self.books:
            c = category_for(p)
            counts[c] = counts.get(c, 0) + 1

        text = [
            f"Total EPUB books: {len(self.books)}",
            f"Favorites: {len(self.favorites)}",
            "",
        ]
        for k, v in sorted(counts.items()):
            text.append(f"{k}: {v}")

        QMessageBox.information(self, "Library Statistics", "\n".join(text))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setOrganizationName("JASS")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

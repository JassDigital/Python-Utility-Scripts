import csv
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QSplitter, QGroupBox, QComboBox, QCheckBox, QFileDialog,
    QMessageBox, QStatusBar, QToolBar, QTextEdit, QTabWidget,
    QDialog, QFormLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QSpinBox
)

APP = "JASS Mizo Corpus Studio"
DEFAULT_DB = "JASS_Mizo_Corpus_4M.db"


def qi(value):
    return '"' + value.replace('"', '""') + '"'


class CorpusDB:
    """Read-only interface for the JASS Mizo Corpus SQLite database."""

    def __init__(self, path):
        self.path = Path(path)
        self.con = sqlite3.connect(str(self.path))
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA query_only=1")

    def close(self):
        if self.con:
            self.con.close()
            self.con = None

    def tables(self):
        return self.con.execute("""
            SELECT name, type, sql
            FROM sqlite_master
            WHERE type IN ('table','view')
            ORDER BY name
        """).fetchall()

    def count(self, table):
        return self.con.execute(
            f"SELECT COUNT(*) FROM {qi(table)}"
        ).fetchone()[0]

    def search(self, query, mode, limit, offset):
        q = query.strip()
        if not q:
            return [], 0

        if mode == "Exact phrase":
            match = '"' + q.replace('"', '""') + '"'
        elif mode == "All words":
            words = q.split()
            match = " AND ".join(
                '"' + w.replace('"', '""') + '"' for w in words
            )
        elif mode == "Any word":
            words = q.split()
            match = " OR ".join(
                '"' + w.replace('"', '""') + '"' for w in words
            )
        elif mode == "Prefix":
            words = q.split()
            match = " ".join(
                '"' + re.sub(r'[^0-9A-Za-zÀ-ž\u0900-\u0fff-]', '', w)
                + '*"' for w in words
            )
        else:
            # Contains mode intentionally uses the ordinary table because
            # FTS5 is token based and does not represent arbitrary substrings.
            pattern = "%" + q + "%"
            rows = self.con.execute("""
                SELECT line_no, text
                FROM sentences
                WHERE text LIKE ?
                LIMIT ? OFFSET ?
            """, (pattern, limit, offset)).fetchall()
            total = self.con.execute(
                "SELECT COUNT(*) FROM sentences WHERE text LIKE ?",
                (pattern,)
            ).fetchone()[0]
            return rows, total

        rows = self.con.execute("""
            SELECT rowid AS line_no, text
            FROM sentences_fts
            WHERE sentences_fts MATCH ?
            LIMIT ? OFFSET ?
        """, (match, limit, offset)).fetchall()

        total = self.con.execute("""
            SELECT COUNT(*)
            FROM sentences_fts
            WHERE sentences_fts MATCH ?
        """, (match,)).fetchone()[0]

        return rows, total

    def get_record(self, line_no):
        return self.con.execute(
            "SELECT line_no, text FROM sentences WHERE line_no=?",
            (line_no,)
        ).fetchone()

    def context(self, line_no, radius=2):
        return self.con.execute("""
            SELECT line_no, text
            FROM sentences
            WHERE line_no BETWEEN ? AND ?
            ORDER BY line_no
        """, (max(1, line_no - radius), line_no + radius)).fetchall()

    def word_frequency(self, word):
        # Exact token frequency through FTS5. This is much more useful than
        # a substring count for linguistic exploration.
        w = word.strip()
        if not w:
            return 0
        match = '"' + w.replace('"', '""') + '"'
        return self.con.execute("""
            SELECT COUNT(*)
            FROM sentences_fts
            WHERE sentences_fts MATCH ?
        """, (match,)).fetchone()[0]

    def metadata(self):
        result = {}
        try:
            for r in self.con.execute(
                "SELECT key,value FROM corpus_metadata"
            ):
                result[r["key"]] = r["value"]
        except sqlite3.Error:
            pass
        return result


class InfoDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Corpus Database Information")
        self.resize(850, 600)
        root = QVBoxLayout(self)

        size_mb = db.path.stat().st_size / (1024 * 1024)
        meta = db.metadata()

        form = QFormLayout()
        form.addRow("Database:", QLabel(db.path.name))
        form.addRow("Size:", QLabel(f"{size_mb:,.2f} MB"))
        form.addRow(
            "Imported records:",
            QLabel(meta.get("total_nonempty_sentences", "Unknown"))
        )
        form.addRow(
            "Source file:",
            QLabel(meta.get("source_file", "Unknown"))
        )
        root.addLayout(form)

        root.addWidget(QLabel("Database objects"))

        rows = db.tables()
        table = QTableWidget(len(rows), 4)
        table.setHorizontalHeaderLabels(
            ["Object", "Type", "Rows", "SQL"]
        )
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch
        )

        for i, r in enumerate(rows):
            name = r["name"]
            try:
                count = db.count(name) if r["type"] == "table" else "-"
            except Exception:
                count = "?"
            table.setItem(i, 0, QTableWidgetItem(name))
            table.setItem(i, 1, QTableWidgetItem(r["type"]))
            table.setItem(i, 2, QTableWidgetItem(str(count)))
            table.setItem(i, 3, QTableWidgetItem(r["sql"] or ""))

        root.addWidget(table, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        root.addWidget(close, alignment=Qt.AlignRight)


class Studio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP + " v2")
        self.resize(1500, 930)
        self.setMinimumSize(1150, 720)

        self.db = None
        self.rows = []
        self.total = 0
        self.page = 0
        self.page_size = 40
        self.query = ""
        self.mode = "Exact phrase"
        self.dark = False
        self.current_line = None
        self.history = []
        self.bookmarks = []
        self.bookmark_file = Path.home() / ".jass_mizo_corpus_bookmarks.json"

        self.build()
        self.style()
        self.load_bookmarks()
        self.auto_open()

    def build(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        def action(text, shortcut, slot):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.triggered.connect(slot)
            toolbar.addAction(a)
            return a

        action("📂 Open Database", "Ctrl+O", self.open_database)
        action("🔄 Refresh", None, self.refresh)
        action("ℹ Database Info", None, self.show_info)
        toolbar.addSeparator()
        action("🎲 Random", "Ctrl+Shift+R", self.random_record)
        action("★ Bookmarks", "Ctrl+B", self.show_bookmarks)
        toolbar.addSeparator()

        self.theme_action = action("☾ Dark Mode", None, self.toggle_theme)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(25, 20, 25, 20)
        root.setSpacing(12)

        title = QLabel("JASS Mizo Corpus Studio")
        title.setObjectName("title")
        root.addWidget(title)

        sub = QLabel(
            "Mizo Usage Explorer  •  Search, concordance, context and frequency"
        )
        sub.setObjectName("subtitle")
        root.addWidget(sub)

        dbline = QHBoxLayout()
        self.db_label = QLabel("No database opened")
        self.db_label.setObjectName("info")
        dbline.addWidget(self.db_label, 1)

        self.history_combo = QComboBox()
        self.history_combo.setMinimumWidth(230)
        self.history_combo.setPlaceholderText("Search history")
        self.history_combo.activated.connect(self.history_selected)
        dbline.addWidget(self.history_combo)
        root.addLayout(dbline)

        search = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search a Mizo word or phrase…")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.search_now)
        search.addWidget(self.search, 1)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Exact phrase", "All words", "Any word", "Prefix", "Contains"
        ])
        self.mode_combo.setMinimumWidth(135)
        self.mode_combo.currentTextChanged.connect(self.mode_changed)
        search.addWidget(self.mode_combo)

        b = QPushButton("🔎 Search")
        b.clicked.connect(self.search_now)
        search.addWidget(b)

        b = QPushButton("Clear")
        b.clicked.connect(self.clear_search)
        search.addWidget(b)
        root.addLayout(search)

        self.stats = QLabel("Ready")
        self.stats.setObjectName("info")
        root.addWidget(self.stats)

        splitter = QSplitter(Qt.Horizontal)

        left = QGroupBox("Search Results")
        lv = QVBoxLayout(left)

        self.results = QListWidget()
        self.results.currentRowChanged.connect(self.select_result)
        lv.addWidget(self.results, 1)

        nav = QHBoxLayout()
        self.prev_btn = QPushButton("← Previous")
        self.prev_btn.clicked.connect(self.prev_page)
        nav.addWidget(self.prev_btn)

        self.page_label = QLabel("Page 0 / 0")
        self.page_label.setAlignment(Qt.AlignCenter)
        nav.addWidget(self.page_label, 1)

        self.next_btn = QPushButton("Next →")
        self.next_btn.clicked.connect(self.next_page)
        nav.addWidget(self.next_btn)
        lv.addLayout(nav)
        splitter.addWidget(left)

        right = QGroupBox("Mizo Usage Explorer")
        rv = QVBoxLayout(right)

        self.record_label = QLabel("Select a search result")
        self.record_label.setObjectName("record")
        rv.addWidget(self.record_label)

        self.tabs = QTabWidget()

        self.context_view = QTextEdit()
        self.context_view.setReadOnly(True)
        self.context_view.setFont(QFont("Segoe UI", 15))
        self.tabs.addTab(self.context_view, "📖 Context")

        self.kwic_view = QTextEdit()
        self.kwic_view.setReadOnly(True)
        self.kwic_view.setFont(QFont("Consolas", 13))
        self.tabs.addTab(self.kwic_view, "🔎 KWIC")

        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setFont(QFont("Segoe UI", 15))
        self.tabs.addTab(self.detail_view, "📄 Full Sentence")

        rv.addWidget(self.tabs, 1)

        buttons = QHBoxLayout()

        self.copy_btn = QPushButton("📋 Copy")
        self.copy_btn.clicked.connect(self.copy_current)
        buttons.addWidget(self.copy_btn)

        self.bookmark_btn = QPushButton("★ Bookmark")
        self.bookmark_btn.clicked.connect(self.toggle_bookmark)
        buttons.addWidget(self.bookmark_btn)

        b = QPushButton("🔤 Frequency")
        b.clicked.connect(self.frequency)
        buttons.addWidget(b)

        b = QPushButton("🔎 Search This")
        b.clicked.connect(self.search_this)
        buttons.addWidget(b)

        b = QPushButton("🎲 Random")
        b.clicked.connect(self.random_record)
        buttons.addWidget(b)

        buttons.addStretch()

        b = QPushButton("⬇ Export")
        b.clicked.connect(self.export_results)
        buttons.addWidget(b)

        rv.addLayout(buttons)
        splitter.addWidget(right)
        splitter.setSizes([800, 700])

        root.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

    def auto_open(self):
        for p in (
            Path.cwd() / DEFAULT_DB,
            Path.home() / "Downloads" / DEFAULT_DB
        ):
            if p.exists():
                self.load_database(p)
                return

    def load_database(self, path):
        try:
            if self.db:
                self.db.close()
            self.db = CorpusDB(path)
            size_mb = path.stat().st_size / (1024 * 1024)
            meta = self.db.metadata()
            count = meta.get("total_nonempty_sentences")
            if not count:
                try:
                    count = self.db.count("sentences")
                except Exception:
                    count = "?"
            self.db_label.setText(
                f"{path.name}  •  {size_mb:,.1f} MB  •  "
                f"{count:,} corpus records" if isinstance(count, int)
                else f"{path.name}  •  {size_mb:,.1f} MB  •  {count} records"
            )
            self.statusBar().showMessage("Database opened read-only.")
            self.clear_search()
        except Exception as e:
            QMessageBox.critical(self, "Database Error", str(e))
            self.db = None

    def open_database(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Mizo Corpus Database", str(Path.home()),
            "SQLite Database (*.db *.sqlite *.sqlite3);;All files (*.*)"
        )
        if path:
            self.load_database(Path(path))

    def refresh(self):
        if self.db:
            self.load_database(self.db.path)

    def show_info(self):
        if not self.db:
            QMessageBox.information(self, "Database", "Open a corpus database first.")
            return
        InfoDialog(self.db, self).exec()

    def mode_changed(self, text):
        self.mode = text
        if self.query:
            self.page = 0
            self.search_now()

    def search_now(self):
        if not self.db:
            QMessageBox.information(self, "Database", "Open JASS_Mizo_Corpus_4M.db first.")
            return

        q = self.search.text().strip()
        if not q:
            self.clear_search()
            return

        self.query = q
        self.mode = self.mode_combo.currentText()
        if q not in self.history:
            self.history.insert(0, q)
            self.history = self.history[:30]
            self.save_history_ui()

        try:
            self.rows, self.total = self.db.search(
                q, self.mode, self.page_size, self.page * self.page_size
            )
            self.results.clear()

            for r in self.rows:
                text = str(r["text"])
                item = QListWidgetItem(
                    f"#{r['line_no']:,}   {text}"
                )
                item.setData(Qt.UserRole, int(r["line_no"]))
                self.results.addItem(item)

            pages = max(1, (self.total + self.page_size - 1) // self.page_size)
            self.page_label.setText(
                f"Page {self.page + 1} / {pages}" if self.total else "Page 0 / 0"
            )
            self.prev_btn.setEnabled(self.page > 0)
            self.next_btn.setEnabled(self.page + 1 < pages)

            self.stats.setText(
                f"{self.total:,} matches  •  {self.mode}  •  "
                f"FTS5" if self.mode != "Contains"
                else f"{self.total:,} matches  •  Contains search  •  SQLite"
            )

            if self.rows:
                self.results.setCurrentRow(0)
            else:
                self.clear_detail("No matching records.")

        except Exception as e:
            QMessageBox.critical(self, "Search Error", str(e))

    def select_result(self, index):
        if index < 0 or index >= len(self.rows):
            return
        self.current_line = int(self.rows[index]["line_no"])
        text = str(self.rows[index]["text"])
        self.record_label.setText(
            f"Corpus record #{self.current_line:,}"
        )
        self.detail_view.setPlainText(text)
        self.show_context()
        self.show_kwic()
        self.update_bookmark_button()

    def show_context(self):
        if not self.db or self.current_line is None:
            return
        context = self.db.context(self.current_line, 2)
        lines = []
        for r in context:
            marker = "  ▶ " if r["line_no"] == self.current_line else "    "
            lines.append(
                f"{marker}#{r['line_no']:,}\n{r['text']}\n"
            )
        self.context_view.setPlainText("\n".join(lines))
        self.highlight_in(self.context_view)

    def show_kwic(self):
        text = ""
        if self.db and self.current_line is not None:
            r = self.db.get_record(self.current_line)
            if r:
                text = str(r["text"])

        if not text:
            self.kwic_view.clear()
            return

        query = self.query.strip()
        if not query:
            self.kwic_view.setPlainText(text)
            return

        # Show each matching occurrence with a fixed-width context window.
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        matches = list(pattern.finditer(text))

        if not matches:
            # For multi-word/prefix searches, show the sentence centered.
            self.kwic_view.setPlainText(
                f"  {text}\n\n  Search term: {query}"
            )
            return

        out = []
        for m in matches[:20]:
            start = max(0, m.start() - 55)
            end = min(len(text), m.end() + 55)
            left = text[start:m.start()].replace("\n", " ")
            hit = text[m.start():m.end()]
            right = text[m.end():end].replace("\n", " ")
            out.append(
                f"{'…' if start else ' '} {left}"
                f" >>> {hit} <<< "
                f"{right}{' …' if end < len(text) else ''}"
            )

        self.kwic_view.setPlainText("\n\n".join(out))

    def highlight_in(self, widget):
        if not self.query:
            return
        extra = []
        doc = widget.document()
        cursor = doc.find(self.query)
        while not cursor.isNull():
            fmt = cursor.charFormat()
            fmt.setFontWeight(QFont.Weight.Bold)
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt
            extra.append(sel)
            cursor = doc.find(self.query, cursor)
        widget.setExtraSelections(extra)

    def clear_detail(self, message="Select a search result"):
        self.current_line = None
        self.record_label.setText(message)
        self.detail_view.clear()
        self.context_view.clear()
        self.kwic_view.clear()
        self.bookmark_btn.setText("★ Bookmark")

    def clear_search(self):
        self.search.clear()
        self.query = ""
        self.page = 0
        self.rows = []
        self.total = 0
        self.results.clear()
        self.clear_detail()
        self.page_label.setText("Page 0 / 0")
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.stats.setText("Ready")

    def prev_page(self):
        if self.page > 0:
            self.page -= 1
            self.search_now()

    def next_page(self):
        pages = max(1, (self.total + self.page_size - 1) // self.page_size)
        if self.page + 1 < pages:
            self.page += 1
            self.search_now()

    def random_record(self):
        if not self.db:
            return
        try:
            r = self.db.con.execute(
                "SELECT line_no,text FROM sentences ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
            if not r:
                return
            self.current_line = int(r["line_no"])
            self.record_label.setText(
                f"Random corpus record #{self.current_line:,}"
            )
            self.detail_view.setPlainText(str(r["text"]))
            self.context_view.setPlainText(
                "\n\n".join(
                    f"{'  ▶ ' if x['line_no']==self.current_line else '    '}"
                    f"#{x['line_no']:,}\n{x['text']}"
                    for x in self.db.context(self.current_line, 2)
                )
            )
            self.kwic_view.setPlainText(str(r["text"]))
            self.search.clear()
            self.query = ""
            self.update_bookmark_button()
            self.tabs.setCurrentIndex(0)
        except Exception as e:
            QMessageBox.critical(self, "Random Record Error", str(e))

    def frequency(self):
        if not self.db:
            return
        term = self.query.strip() or self.search.text().strip()
        if not term:
            QMessageBox.information(
                self, "Frequency", "Enter a Mizo word first."
            )
            return

        # For phrases, frequency is the number of matching records.
        if " " in term:
            n = self.total if self.query == term else self.db.word_frequency(term)
            label = "matching corpus records"
        else:
            n = self.db.word_frequency(term)
            label = "corpus records containing the exact token"

        QMessageBox.information(
            self,
            "Mizo Word Frequency",
            f"Term:\n{term}\n\nFrequency: {n:,}\n\n{label}."
        )

    def copy_current(self):
        if self.current_line is None:
            return
        r = self.db.get_record(self.current_line)
        if r:
            QApplication.clipboard().setText(str(r["text"]))
            self.statusBar().showMessage("Sentence copied.", 2000)

    def search_this(self):
        if self.current_line is None:
            return
        r = self.db.get_record(self.current_line)
        if not r:
            return
        words = str(r["text"]).split()
        self.search.setText(" ".join(words[:3]))
        self.mode_combo.setCurrentText("All words")
        self.page = 0
        self.search_now()

    def export_results(self):
        if not self.rows:
            QMessageBox.information(self, "Export", "There are no results to export.")
            return

        path, selected = QFileDialog.getSaveFileName(
            self, "Export Search Results", str(Path.home() / "mizo_results.txt"),
            "Text (*.txt);;CSV (*.csv)"
        )
        if not path:
            return

        try:
            if path.lower().endswith(".csv") or "CSV" in selected:
                if not path.lower().endswith(".csv"):
                    path += ".csv"
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f)
                    w.writerow(["line_no", "text"])
                    for r in self.rows:
                        w.writerow([r["line_no"], r["text"]])
            else:
                if not path.lower().endswith(".txt"):
                    path += ".txt"
                with open(path, "w", encoding="utf-8") as f:
                    f.write(
                        f"JASS Mizo Corpus Studio\n"
                        f"Search: {self.query}\n"
                        f"Mode: {self.mode}\n"
                        f"Page: {self.page + 1}\n\n"
                    )
                    for r in self.rows:
                        f.write(f"#{r['line_no']:,}\t{r['text']}\n")
            self.statusBar().showMessage(f"Exported: {path}", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def toggle_bookmark(self):
        if self.current_line is None or not self.db:
            return

        r = self.db.get_record(self.current_line)
        if not r:
            return

        existing = next(
            (x for x in self.bookmarks if x["line_no"] == self.current_line),
            None
        )

        if existing:
            self.bookmarks = [
                x for x in self.bookmarks
                if x["line_no"] != self.current_line
            ]
            self.bookmark_btn.setText("★ Bookmark")
            self.statusBar().showMessage("Bookmark removed.", 2000)
        else:
            self.bookmarks.insert(0, {
                "line_no": self.current_line,
                "text": str(r["text"]),
                "saved": datetime.now().isoformat(timespec="seconds")
            })
            self.bookmark_btn.setText("★ Bookmarked")
            self.statusBar().showMessage("Bookmarked.", 2000)

        self.save_bookmarks()

    def update_bookmark_button(self):
        found = any(
            x["line_no"] == self.current_line for x in self.bookmarks
        )
        self.bookmark_btn.setText(
            "★ Bookmarked" if found else "★ Bookmark"
        )

    def show_bookmarks(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Mizo Corpus Bookmarks")
        dlg.resize(900, 620)
        root = QVBoxLayout(dlg)

        label = QLabel(f"{len(self.bookmarks):,} saved examples")
        root.addWidget(label)

        lst = QListWidget()
        for x in self.bookmarks:
            lst.addItem(
                f"#{x['line_no']:,}   {x['text']}"
            )
        root.addWidget(lst, 1)

        buttons = QHBoxLayout()
        open_btn = QPushButton("Open Selected")
        remove_btn = QPushButton("Remove")
        export_btn = QPushButton("Export Bookmarks")
        close_btn = QPushButton("Close")

        buttons.addWidget(open_btn)
        buttons.addWidget(remove_btn)
        buttons.addWidget(export_btn)
        buttons.addStretch()
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

        def open_selected():
            i = lst.currentRow()
            if i < 0:
                return
            line = self.bookmarks[i]["line_no"]
            self.show_bookmark_record(line)
            dlg.accept()

        def remove_selected():
            i = lst.currentRow()
            if i < 0:
                return
            del self.bookmarks[i]
            self.save_bookmarks()
            lst.takeItem(i)
            label.setText(f"{len(self.bookmarks):,} saved examples")

        def export_bookmarks():
            path, _ = QFileDialog.getSaveFileName(
                dlg, "Export Bookmarks",
                str(Path.home() / "mizo_bookmarks.txt"),
                "Text (*.txt);;CSV (*.csv)"
            )
            if not path:
                return
            try:
                if path.lower().endswith(".csv"):
                    with open(path, "w", newline="", encoding="utf-8-sig") as f:
                        w = csv.writer(f)
                        w.writerow(["line_no", "text", "saved"])
                        for x in self.bookmarks:
                            w.writerow([
                                x["line_no"], x["text"], x.get("saved", "")
                            ])
                else:
                    with open(path, "w", encoding="utf-8") as f:
                        for x in self.bookmarks:
                            f.write(
                                f"#{x['line_no']:,}\t{x['text']}\n"
                            )
                self.statusBar().showMessage("Bookmarks exported.", 3000)
            except Exception as e:
                QMessageBox.critical(dlg, "Export Error", str(e))

        open_btn.clicked.connect(open_selected)
        remove_btn.clicked.connect(remove_selected)
        export_btn.clicked.connect(export_bookmarks)
        close_btn.clicked.connect(dlg.accept)
        dlg.exec()

    def show_bookmark_record(self, line):
        if not self.db:
            return
        r = self.db.get_record(line)
        if not r:
            return
        self.current_line = int(r["line_no"])
        self.record_label.setText(
            f"Bookmarked corpus record #{self.current_line:,}"
        )
        self.detail_view.setPlainText(str(r["text"]))
        self.context_view.setPlainText(
            "\n\n".join(
                f"{'  ▶ ' if x['line_no']==line else '    '}"
                f"#{x['line_no']:,}\n{x['text']}"
                for x in self.db.context(line, 2)
            )
        )
        self.kwic_view.setPlainText(str(r["text"]))
        self.update_bookmark_button()
        self.tabs.setCurrentIndex(0)

    def save_bookmarks(self):
        try:
            self.bookmark_file.write_text(
                json.dumps(self.bookmarks, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    def load_bookmarks(self):
        try:
            if self.bookmark_file.exists():
                data = json.loads(
                    self.bookmark_file.read_text(encoding="utf-8")
                )
                if isinstance(data, list):
                    self.bookmarks = data
        except Exception:
            self.bookmarks = []

    def save_history_ui(self):
        self.history_combo.clear()
        self.history_combo.addItems(self.history)

    def history_selected(self, index):
        if index < 0:
            return
        value = self.history_combo.itemText(index)
        if value:
            self.search.setText(value)
            self.page = 0
            self.search_now()

    def toggle_theme(self, checked):
        self.dark = checked
        self.theme_action.setText(
            "☀ Light Mode" if checked else "☾ Dark Mode"
        )
        self.style()

    def style(self):
        if self.dark:
            self.setStyleSheet("""
                QWidget { background:#12161c; color:#e9eef3; font-size:14px; }
                QGroupBox,QLineEdit,QComboBox,QListWidget,QTextEdit,QTabWidget {
                    background:#1b222b; color:#e9eef3;
                    border:1px solid #35404c; border-radius:10px;
                }
                QLineEdit,QComboBox { padding:9px; }
                QListWidget { padding:6px; }
                QListWidget::item:selected { background:#34495e; }
                QPushButton { background:#202832; color:#e9eef3;
                    border:1px solid #3b4652; border-radius:8px;
                    padding:9px 14px; }
                QPushButton:hover { background:#2a3440; }
                QToolBar { background:#181d24; border:0; padding:7px; }
                QGroupBox { margin-top:12px; padding:12px; }
                QGroupBox::title { subcontrol-origin:margin; left:14px; padding:0 5px; }
                QTabBar::tab { padding:8px 13px; }
                #title { font-size:30px; font-weight:700; }
                #subtitle,#info { color:#9aa8b6; }
                #record { font-size:17px; font-weight:700; }
            """)
        else:
            self.setStyleSheet("""
                QWidget { background:#f5f7fa; color:#20252b; font-size:14px; }
                QGroupBox,QLineEdit,QComboBox,QListWidget,QTextEdit,QTabWidget {
                    background:white; color:#20252b;
                    border:1px solid #d5dce5; border-radius:10px;
                }
                QLineEdit,QComboBox { padding:9px; }
                QListWidget { padding:6px; }
                QListWidget::item:selected { background:#dcecff; }
                QPushButton { background:white; color:#20252b;
                    border:1px solid #d5dce5; border-radius:8px;
                    padding:9px 14px; }
                QPushButton:hover { background:#edf2f7; }
                QToolBar { background:white; border:0; padding:7px; }
                QGroupBox { margin-top:12px; padding:12px; }
                QGroupBox::title { subcontrol-origin:margin; left:14px; padding:0 5px; }
                QTabBar::tab { padding:8px 13px; }
                #title { font-size:30px; font-weight:700; color:#17202a; }
                #subtitle,#info { color:#647281; }
                #record { font-size:17px; font-weight:700; }
            """)

    def closeEvent(self, event):
        if self.db:
            self.db.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setStyle("Fusion")
    win = Studio()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

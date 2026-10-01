import os
import sys
import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QTextCharFormat, QTextCursor, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QSplitter, QGroupBox, QComboBox, QSpinBox, QCheckBox,
    QFileDialog, QMessageBox, QStatusBar, QToolBar, QTextEdit,
    QDialog, QFormLayout, QTableWidget, QTableWidgetItem,
    QHeaderView
)

APP = "JASS Mizo Corpus Studio"
DEFAULT_DB = "JASS_Mizo_Corpus_4M.db"


def qident(value):
    return '"' + value.replace('"', '""') + '"'


class CorpusDB:
    def __init__(self, path):
        self.path = Path(path)
        self.con = None
        self.tables = []
        self.fts_tables = []
        self.open()

    def open(self):
        self.close()
        self.con = sqlite3.connect(str(self.path))
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA query_only=1")
        self.inspect()

    def close(self):
        if self.con:
            self.con.close()
            self.con = None

    def inspect(self):
        self.tables = self.con.execute("""
            SELECT name, type, sql
            FROM sqlite_master
            WHERE type IN ('table','view')
            ORDER BY name
        """).fetchall()

        self.fts_tables = []
        for row in self.tables:
            sql = (row["sql"] or "").lower()
            if "using fts" in sql or "fts5" in sql:
                self.fts_tables.append(row["name"])

    def columns(self, table):
        return self.con.execute(
            f"PRAGMA table_info({qident(table)})"
        ).fetchall()

    def row_count(self, table):
        return self.con.execute(
            f"SELECT COUNT(*) FROM {qident(table)}"
        ).fetchone()[0]

    def text_column(self, table):
        cols = self.columns(table)
        preferred = {
            "text", "sentence", "content", "mizo", "mizo_text",
            "text_content", "body", "sentence_text", "entry"
        }
        for c in cols:
            if c["name"].lower() in preferred:
                return c["name"]
        for c in cols:
            if "TEXT" in (c["type"] or "").upper():
                return c["name"]
        return cols[0]["name"] if cols else None

    def best_source(self):
        # Prefer an FTS table with a text column; otherwise use the sentences table.
        for name in self.fts_tables:
            col = self.text_column(name)
            if col:
                return name, col
        for row in self.tables:
            if row["type"] == "table":
                col = self.text_column(row["name"])
                if col:
                    return row["name"], col
        return None, None

    def search(self, table, column, query, phrase, limit, offset):
        qt, qc = qident(table), qident(column)

        if table in self.fts_tables:
            fts_query = (
                '"' + query.replace('"', '""') + '"'
                if phrase else query
            )
            try:
                rows = self.con.execute(
                    f"""
                    SELECT rowid AS _rowid, *
                    FROM {qt}
                    WHERE {qt} MATCH ?
                    LIMIT ? OFFSET ?
                    """,
                    (fts_query, limit, offset)
                ).fetchall()
                total = self.con.execute(
                    f"SELECT COUNT(*) FROM {qt} WHERE {qt} MATCH ?",
                    (fts_query,)
                ).fetchone()[0]
                return rows, total, "FTS5"
            except sqlite3.Error:
                pass

        # Fallback for ordinary SQLite tables.
        if phrase:
            pattern = "%" + query + "%"
            where = f"lower(CAST({qc} AS TEXT)) LIKE lower(?)"
            params = [pattern]
        else:
            terms = [x for x in query.split() if x]
            if not terms:
                return [], 0, "SQLite"
            where = " AND ".join(
                f"lower(CAST({qc} AS TEXT)) LIKE lower(?)"
                for _ in terms
            )
            params = [f"%{x}%" for x in terms]

        rows = self.con.execute(
            f"""
            SELECT rowid AS _rowid, *
            FROM {qt}
            WHERE {where}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset)
        ).fetchall()

        total = self.con.execute(
            f"SELECT COUNT(*) FROM {qt} WHERE {where}",
            params
        ).fetchone()[0]

        return rows, total, "SQLite"

    def random_record(self, table):
        return self.con.execute(
            f"SELECT rowid AS _rowid, * FROM {qident(table)} "
            f"ORDER BY RANDOM() LIMIT 1"
        ).fetchone()


class DatabaseInfoDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Corpus Database Information")
        self.resize(780, 600)

        root = QVBoxLayout(self)

        form = QFormLayout()
        size_mb = db.path.stat().st_size / (1024 * 1024)

        form.addRow("Database:", QLabel(db.path.name))
        form.addRow("Location:", QLabel(str(db.path)))
        form.addRow("Size:", QLabel(f"{size_mb:,.2f} MB"))
        form.addRow("Tables / views:", QLabel(str(len(db.tables))))
        form.addRow(
            "FTS5 tables:",
            QLabel(", ".join(db.fts_tables) if db.fts_tables else "None detected")
        )
        root.addLayout(form)

        root.addWidget(QLabel("Schema"))

        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Object", "Type", "Rows", "Columns"])
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

        table.setRowCount(len(db.tables))
        for i, row in enumerate(db.tables):
            name = row["name"]
            typ = row["type"]
            try:
                count = db.row_count(name) if typ == "table" else "-"
            except Exception:
                count = "?"
            cols = ", ".join(c["name"] for c in db.columns(name))
            table.setItem(i, 0, QTableWidgetItem(name))
            table.setItem(i, 1, QTableWidgetItem(typ))
            table.setItem(i, 2, QTableWidgetItem(str(count)))
            table.setItem(i, 3, QTableWidgetItem(cols))

        root.addWidget(table, 1)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        root.addWidget(close, alignment=Qt.AlignRight)


class CorpusStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.resize(1450, 900)
        self.setMinimumSize(1100, 700)

        self.db = None
        self.source = None
        self.column = None
        self.rows = []
        self.total = 0
        self.page = 0
        self.page_size = 40
        self.query = ""
        self.dark = False

        self.build_ui()
        self.apply_style()
        self.auto_open()

    def build_ui(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        a = QAction("📂 Open Database", self)
        a.setShortcut(QKeySequence.Open)
        a.triggered.connect(self.open_database)
        toolbar.addAction(a)

        a = QAction("🔄 Refresh", self)
        a.triggered.connect(self.refresh_database)
        toolbar.addAction(a)

        a = QAction("ℹ Database Info", self)
        a.triggered.connect(self.show_db_info)
        toolbar.addAction(a)

        toolbar.addSeparator()

        a = QAction("🎲 Random Record", self)
        a.setShortcut("Ctrl+Shift+R")
        a.triggered.connect(self.random_record)
        toolbar.addAction(a)

        toolbar.addSeparator()

        self.theme_action = QAction("☾ Dark Mode", self)
        self.theme_action.setCheckable(True)
        self.theme_action.triggered.connect(self.toggle_theme)
        toolbar.addAction(self.theme_action)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(25, 21, 25, 21)
        root.setSpacing(13)

        title = QLabel("JASS Mizo Corpus Studio")
        title.setObjectName("title")
        root.addWidget(title)

        subtitle = QLabel(
            "Explore your 4-million-line Mizo corpus with fast offline search."
        )
        subtitle.setObjectName("subtitle")
        root.addWidget(subtitle)

        dbline = QHBoxLayout()
        self.db_label = QLabel("No database opened")
        self.db_label.setObjectName("info")
        dbline.addWidget(self.db_label, 1)

        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(250)
        self.source_combo.currentIndexChanged.connect(self.source_changed)
        dbline.addWidget(QLabel("Search source:"))
        dbline.addWidget(self.source_combo)
        root.addLayout(dbline)

        search = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a Mizo word or phrase…")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.do_search)
        search.addWidget(self.search, 1)

        self.phrase = QCheckBox("Exact phrase")
        self.phrase.setChecked(True)
        search.addWidget(self.phrase)

        b = QPushButton("🔎 Search")
        b.setDefault(True)
        b.clicked.connect(self.do_search)
        search.addWidget(b)

        b = QPushButton("Clear")
        b.clicked.connect(self.clear_search)
        search.addWidget(b)

        root.addLayout(search)

        self.stats = QLabel("Ready")
        self.stats.setObjectName("info")
        root.addWidget(self.stats)

        split = QSplitter(Qt.Horizontal)

        left = QGroupBox("Search Results")
        ll = QVBoxLayout(left)

        self.results = QListWidget()
        self.results.currentRowChanged.connect(self.result_selected)
        ll.addWidget(self.results, 1)

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
        ll.addLayout(nav)

        right = QGroupBox("Mizo Context")
        rr = QVBoxLayout(right)

        self.record_label = QLabel("Select a corpus result")
        self.record_label.setObjectName("record")
        rr.addWidget(self.record_label)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont("Segoe UI", 15))
        rr.addWidget(self.detail, 1)

        actions = QHBoxLayout()
        b = QPushButton("📋 Copy")
        b.clicked.connect(self.copy_text)
        actions.addWidget(b)

        b = QPushButton("🔎 Search This")
        b.clicked.connect(self.search_this)
        actions.addWidget(b)

        b = QPushButton("🎲 Random")
        b.clicked.connect(self.random_record)
        actions.addWidget(b)

        actions.addStretch()
        rr.addLayout(actions)

        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([790, 590])
        root.addWidget(split, 1)

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

    def open_database(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open JASS Mizo Corpus Database",
            str(Path.home()),
            "SQLite database (*.db *.sqlite *.sqlite3);;All files (*.*)"
        )
        if path:
            self.load_database(Path(path))

    def load_database(self, path):
        try:
            self.db = CorpusDB(path)
            self.populate_sources()
            size_mb = path.stat().st_size / (1024 * 1024)
            self.db_label.setText(
                f"{path.name}   •   {size_mb:,.1f} MB   •   "
                f"{len(self.db.tables)} objects"
            )
            self.statusBar().showMessage(f"Opened {path}")
        except Exception as e:
            QMessageBox.critical(self, "Database Error", str(e))
            self.db = None

    def populate_sources(self):
        self.source_combo.blockSignals(True)
        self.source_combo.clear()

        names = []
        for n in self.db.fts_tables:
            names.append(n)

        for row in self.db.tables:
            if row["type"] == "table":
                name = row["name"]
                if name not in names and self.db.text_column(name):
                    names.append(name)

        for name in names:
            try:
                count = self.db.row_count(name)
                self.source_combo.addItem(f"{name}  ({count:,})", name)
            except Exception:
                self.source_combo.addItem(name, name)

        self.source_combo.blockSignals(False)

        if names:
            self.source_combo.setCurrentIndex(0)
            self.source_changed(0)

    def source_changed(self, index):
        if not self.db or index < 0:
            return
        self.source = self.source_combo.itemData(index)
        self.column = self.db.text_column(self.source)

        self.stats.setText(
            f"Source: {self.source}   •   Text column: {self.column}"
        )

        if self.query:
            self.page = 0
            self.do_search()

    def refresh_database(self):
        if self.db:
            path = self.db.path
            self.load_database(path)

    def show_db_info(self):
        if not self.db:
            QMessageBox.information(
                self, "Database Info", "Open JASS_Mizo_Corpus_4M.db first."
            )
            return
        DatabaseInfoDialog(self.db, self).exec()

    def do_search(self):
        if not self.db:
            QMessageBox.information(
                self, "Open Database",
                "Open JASS_Mizo_Corpus_4M.db first."
            )
            return

        query = self.search.text().strip()
        if not query:
            self.clear_search()
            return

        if not self.source or not self.column:
            return

        self.query = query

        try:
            self.rows, self.total, engine = self.db.search(
                self.source, self.column, query, self.phrase.isChecked(),
                self.page_size, self.page * self.page_size
            )

            self.results.clear()

            for row in self.rows:
                value = row[self.column]
                text = "" if value is None else str(value)
                item = QListWidgetItem(
                    f"#{row['_rowid']:,}   {text}"
                )
                item.setData(Qt.UserRole, dict(row))
                self.results.addItem(item)

            pages = max(1, (self.total + self.page_size - 1) // self.page_size)
            self.page_label.setText(
                f"Page {self.page + 1} / {pages}"
                if self.total else "Page 0 / 0"
            )
            self.prev_btn.setEnabled(self.page > 0)
            self.next_btn.setEnabled(self.page + 1 < pages)

            self.stats.setText(
                f"{self.total:,} matches   •   {engine}   •   "
                f"{self.source}.{self.column}"
            )

            if self.rows:
                self.results.setCurrentRow(0)
            else:
                self.detail.clear()
                self.record_label.setText("No matching records")

        except Exception as e:
            QMessageBox.critical(self, "Search Error", str(e))

    def result_selected(self, index):
        if index < 0 or index >= len(self.rows):
            return

        row = self.rows[index]
        value = row[self.column]
        text = "" if value is None else str(value)

        self.record_label.setText(
            f"Corpus record #{row['_rowid']:,}"
        )
        self.detail.setPlainText(text)
        self.highlight()

    def highlight(self):
        if not self.query:
            return

        doc = self.detail.document()
        selections = []
        cursor = QTextCursor(doc)

        while True:
            cursor = doc.find(self.query, cursor)
            if cursor.isNull():
                break
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Weight.Bold)
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt
            selections.append(sel)

        self.detail.setExtraSelections(selections)

    def copy_text(self):
        text = self.detail.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage("Copied to clipboard", 2000)

    def search_this(self):
        text = self.detail.toPlainText().strip()
        if text:
            # Search the first few Unicode words from the selected sentence.
            words = text.split()
            self.search.setText(" ".join(words[:3]))
            self.page = 0
            self.do_search()

    def random_record(self):
        if not self.db or not self.source:
            return
        try:
            row = self.db.random_record(self.source)
            if not row:
                return
            text = row[self.column]
            text = "" if text is None else str(text)
            self.record_label.setText(
                f"Random corpus record #{row['_rowid']:,}"
            )
            self.detail.setPlainText(text)
            self.detail.setExtraSelections([])
            self.search.clear()
            self.query = ""
            self.stats.setText(
                f"Random record from {self.source}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Random Record Error", str(e))

    def clear_search(self):
        self.search.clear()
        self.query = ""
        self.page = 0
        self.rows = []
        self.total = 0
        self.results.clear()
        self.detail.clear()
        self.record_label.setText("Select a corpus result")
        self.page_label.setText("Page 0 / 0")
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)

    def prev_page(self):
        if self.page > 0:
            self.page -= 1
            self.do_search()

    def next_page(self):
        pages = max(1, (self.total + self.page_size - 1) // self.page_size)
        if self.page + 1 < pages:
            self.page += 1
            self.do_search()

    def toggle_theme(self, checked):
        self.dark = checked
        self.apply_style()
        self.theme_action.setText(
            "☀ Light Mode" if checked else "☾ Dark Mode"
        )

    def apply_style(self):
        if self.dark:
            self.setStyleSheet("""
                QWidget { background:#13171d; color:#e8edf2; font-size:14px; }
                QGroupBox,QLineEdit,QComboBox,QListWidget,QTextEdit {
                    background:#1c222a; color:#e8edf2;
                    border:1px solid #37414d; border-radius:10px;
                }
                QLineEdit,QComboBox { padding:9px; }
                QListWidget { padding:7px; }
                QPushButton { background:#202731; color:#e8edf2;
                    border:1px solid #3b4653; border-radius:8px;
                    padding:9px 14px; }
                QPushButton:hover { background:#2a3440; }
                QToolBar { background:#191e25; border:0;
                    padding:7px; spacing:5px; }
                QGroupBox { margin-top:12px; padding:12px; }
                QGroupBox::title { subcontrol-origin:margin;
                    left:14px; padding:0 5px; }
                #title { font-size:30px; font-weight:700; }
                #subtitle,#info { color:#99a7b5; }
                #record { font-size:17px; font-weight:700; }
            """)
        else:
            self.setStyleSheet("""
                QWidget { background:#f5f7fa; color:#20252b; font-size:14px; }
                QGroupBox,QLineEdit,QComboBox,QListWidget,QTextEdit {
                    background:white; color:#20252b;
                    border:1px solid #d5dce5; border-radius:10px;
                }
                QLineEdit,QComboBox { padding:9px; }
                QListWidget { padding:7px; }
                QPushButton { background:white; color:#20252b;
                    border:1px solid #d5dce5; border-radius:8px;
                    padding:9px 14px; }
                QPushButton:hover { background:#edf2f7; }
                QToolBar { background:white; border:0;
                    padding:7px; spacing:5px; }
                QGroupBox { margin-top:12px; padding:12px; }
                QGroupBox::title { subcontrol-origin:margin;
                    left:14px; padding:0 5px; }
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
    win = CorpusStudio()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

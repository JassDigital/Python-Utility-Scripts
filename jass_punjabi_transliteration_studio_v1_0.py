import sys
import sqlite3
import csv
import random
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QFrame, QTextEdit, QStatusBar, QMessageBox,
    QFileDialog, QDialog, QFormLayout, QSpinBox
)

APP = "JASS Punjabi Transliteration Studio"
DEFAULT_DB = Path(__file__).with_name("JASS_Punjabi_Aksharantar.db")


class StatsDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Corpus Statistics")
        self.resize(520, 360)
        lay = QVBoxLayout(self)

        rows = [
            ("Total entries", "SELECT COUNT(*) FROM entries"),
            ("Train", "SELECT COUNT(*) FROM entries WHERE split='train'"),
            ("Validation", "SELECT COUNT(*) FROM entries WHERE split='valid'"),
            ("Test", "SELECT COUNT(*) FROM entries WHERE split='test'"),
            ("Unique Punjabi words", "SELECT COUNT(DISTINCT native_word) FROM entries"),
            ("Unique Romanized forms", "SELECT COUNT(DISTINCT romanized_word) FROM entries"),
            ("Sources", "SELECT COUNT(DISTINCT source) FROM entries"),
        ]
        grid = QGridLayout()
        for r, (label, sql) in enumerate(rows):
            value = db.execute(sql).fetchone()[0]
            grid.addWidget(QLabel(label), r, 0)
            grid.addWidget(QLabel(f"{value:,}"), r, 1)
        lay.addLayout(grid)

        lay.addWidget(QLabel("Sources"))
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Source", "Entries"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        for source, count in db.execute(
            "SELECT COALESCE(source,''), COUNT(*) FROM entries GROUP BY source ORDER BY COUNT(*) DESC"
        ):
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(source))
            table.setItem(r, 1, QTableWidgetItem(f"{count:,}"))
        lay.addWidget(table)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addWidget(close)


class DictionaryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.resize(1320, 820)
        self.setMinimumSize(1050, 680)
        self.db = None
        self.bookmarks = set()
        self.history = []
        self.history_pos = -1
        self.current_rows = []
        self.current_index = -1
        self.dark = False
        self.build()
        self.load_database()

    def build(self):
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(18, 16, 18, 14)
        main.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("ਪੰਜਾਬੀ  |  JASS Punjabi Transliteration Studio")
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch()

        self.stats_btn = QPushButton("📊 Statistics")
        self.theme_btn = QPushButton("☾ Dark")
        self.stats_btn.clicked.connect(self.show_stats)
        self.theme_btn.clicked.connect(self.toggle_theme)
        top.addWidget(self.stats_btn)
        top.addWidget(self.theme_btn)
        main.addLayout(top)

        controls = QHBoxLayout()
        self.direction = QComboBox()
        self.direction.addItems(["Punjabi → Roman", "Roman → Punjabi", "Both"])
        self.mode = QComboBox()
        self.mode.addItems(["FTS Search", "Exact", "Starts With", "Contains"])
        self.split = QComboBox()
        self.split.addItems(["All splits", "train", "valid", "test"])
        controls.addWidget(QLabel("Direction"))
        controls.addWidget(self.direction)
        controls.addWidget(QLabel("Mode"))
        controls.addWidget(self.mode)
        controls.addWidget(QLabel("Split"))
        controls.addWidget(self.split)
        main.addLayout(controls)

        search = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search Punjabi or Romanized Punjabi…")
        self.query.setClearButtonEnabled(True)
        self.search_btn = QPushButton("🔎 Search")
        self.random_btn = QPushButton("🎲 Random")
        self.back_btn = QPushButton("←")
        self.forward_btn = QPushButton("→")
        self.search_btn.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        self.random_btn.clicked.connect(self.random_entry)
        self.back_btn.clicked.connect(self.go_back)
        self.forward_btn.clicked.connect(self.go_forward)
        search.addWidget(self.back_btn)
        search.addWidget(self.forward_btn)
        search.addWidget(self.query, 1)
        search.addWidget(self.search_btn)
        search.addWidget(self.random_btn)
        main.addLayout(search)

        self.splitter = QSplitter(Qt.Horizontal)

        left = QFrame()
        left.setObjectName("panel")
        ll = QVBoxLayout(left)
        self.results_label = QLabel("Results")
        self.results_label.setObjectName("section")
        ll.addWidget(self.results_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Punjabi", "Romanized", "Source", "Split"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.show_selected)
        ll.addWidget(self.table)

        right = QFrame()
        right.setObjectName("panel")
        rl = QVBoxLayout(right)
        self.detail_title = QLabel("Entry")
        self.detail_title.setObjectName("section")
        rl.addWidget(self.detail_title)

        self.punjabi = QLabel("—")
        self.punjabi.setObjectName("punjabi")
        self.punjabi.setWordWrap(True)
        self.roman = QLabel("—")
        self.roman.setObjectName("roman")
        self.roman.setWordWrap(True)
        rl.addWidget(QLabel("Punjabi / Gurmukhi"))
        rl.addWidget(self.punjabi)
        rl.addWidget(QLabel("Romanized"))
        rl.addWidget(self.roman)

        self.meta = QTextEdit()
        self.meta.setReadOnly(True)
        self.meta.setMaximumHeight(180)
        rl.addWidget(self.meta)

        actions = QHBoxLayout()
        self.copy_native = QPushButton("Copy Punjabi")
        self.copy_roman = QPushButton("Copy Roman")
        self.bookmark_btn = QPushButton("☆ Bookmark")
        self.copy_native.clicked.connect(lambda: QApplication.clipboard().setText(self.punjabi.text()))
        self.copy_roman.clicked.connect(lambda: QApplication.clipboard().setText(self.roman.text()))
        self.bookmark_btn.clicked.connect(self.toggle_bookmark)
        actions.addWidget(self.copy_native)
        actions.addWidget(self.copy_roman)
        actions.addWidget(self.bookmark_btn)
        rl.addLayout(actions)

        nav = QHBoxLayout()
        self.prev_btn = QPushButton("← Previous")
        self.next_btn = QPushButton("Next →")
        self.prev_btn.clicked.connect(self.previous_entry)
        self.next_btn.clicked.connect(self.next_entry)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        rl.addLayout(nav)
        rl.addStretch()

        self.splitter.addWidget(left)
        self.splitter.addWidget(right)
        self.splitter.setSizes([760, 460])
        main.addWidget(self.splitter, 1)

        bottom = QHBoxLayout()
        self.export_btn = QPushButton("⬇ Export Results")
        self.bookmarks_btn = QPushButton("★ Bookmarks")
        self.clear_btn = QPushButton("Clear")
        self.export_btn.clicked.connect(self.export_results)
        self.bookmarks_btn.clicked.connect(self.show_bookmarks)
        self.clear_btn.clicked.connect(self.clear_search)
        bottom.addWidget(self.export_btn)
        bottom.addWidget(self.bookmarks_btn)
        bottom.addStretch()
        bottom.addWidget(self.clear_btn)
        main.addLayout(bottom)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

        self.create_menu()

    def create_menu(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        export_action = QAction("Export Results…", self)
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.triggered.connect(self.export_results)
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        quit_action = QAction("Exit", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        tools = bar.addMenu("&Tools")
        stats = QAction("Corpus Statistics", self)
        stats.triggered.connect(self.show_stats)
        tools.addAction(stats)
        random_a = QAction("Random Entry", self)
        random_a.setShortcut(QKeySequence("Ctrl+R"))
        random_a.triggered.connect(self.random_entry)
        tools.addAction(random_a)

    def load_database(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Punjabi Aksharantar Database",
            str(DEFAULT_DB), "SQLite Database (*.db);;All Files (*)"
        )
        if not path:
            if DEFAULT_DB.exists():
                path = str(DEFAULT_DB)
            else:
                QMessageBox.warning(self, APP, "No database selected.")
                return
        try:
            self.db = sqlite3.connect(path)
            self.db.row_factory = sqlite3.Row
            self.db.execute("SELECT COUNT(*) FROM entries").fetchone()
            self.status.showMessage(f"Database: {Path(path).name}")
            self.search()
        except Exception as e:
            QMessageBox.critical(self, APP, f"Could not open database:\n{e}")

    def add_history(self, q):
        if not q:
            return
        if self.history_pos >= 0 and self.history[self.history_pos] == q:
            return
        self.history = self.history[:self.history_pos + 1]
        self.history.append(q)
        self.history_pos = len(self.history) - 1

    def search(self):
        if not self.db:
            return
        q = self.query.text().strip()
        if not q:
            self.table.setRowCount(0)
            self.results_label.setText("Results")
            self.status.showMessage("Enter a word or phrase to search.")
            return

        direction = self.direction.currentIndex()
        mode = self.mode.currentText()
        split = self.split.currentText()

        if direction == 0:
            cols = ["native_word"]
        elif direction == 1:
            cols = ["romanized_word"]
        else:
            cols = ["native_word", "romanized_word"]

        where = []
        args = []

        if mode == "FTS Search":
            # FTS5 MATCH cannot safely represent arbitrary punctuation, so quote the query.
            terms = []
            for c in cols:
                terms.append(f"entries_fts.{c} : ?")
            where.append("(" + " OR ".join(terms) + ")")
            args.extend([q] * len(cols))
            sql = f"""
                SELECT e.id,e.native_word,e.romanized_word,e.source,e.split
                FROM entries e JOIN entries_fts
                ON entries_fts.rowid=e.id
                WHERE {where[0]}
            """
        else:
            patterns = []
            for c in cols:
                if mode == "Exact":
                    patterns.append(f"e.{c} = ?")
                    args.append(q)
                elif mode == "Starts With":
                    patterns.append(f"e.{c} LIKE ?")
                    args.append(q + "%")
                else:
                    patterns.append(f"e.{c} LIKE ?")
                    args.append("%" + q + "%")
            sql = f"""
                SELECT e.id,e.native_word,e.romanized_word,e.source,e.split
                FROM entries e
                WHERE ({' OR '.join(patterns)})
            """

        if split != "All splits":
            sql += " AND e.split = ?"
            args.append(split)

        sql += " ORDER BY e.native_word LIMIT 2000"

        try:
            rows = self.db.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            # Fallback for FTS syntax-sensitive input.
            if mode == "FTS Search":
                patterns = []
                args = []
                for c in cols:
                    patterns.append(f"e.{c} LIKE ?")
                    args.append("%" + q + "%")
                sql = f"""
                    SELECT e.id,e.native_word,e.romanized_word,e.source,e.split
                    FROM entries e
                    WHERE ({' OR '.join(patterns)})
                """
                if split != "All splits":
                    sql += " AND e.split = ?"
                    args.append(split)
                sql += " ORDER BY e.native_word LIMIT 2000"
                rows = self.db.execute(sql, args).fetchall()
            else:
                raise

        self.current_rows = rows
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [row["native_word"], row["romanized_word"], row["source"] or "", row["split"]]
            for c, value in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(str(value)))
            self.table.item(r, 0).setData(Qt.UserRole, row["id"])

        self.results_label.setText(f"Results  •  {len(rows):,}")
        self.status.showMessage(f"{len(rows):,} result(s)")
        if rows:
            self.table.selectRow(0)
        self.add_history(q)

    def show_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.current_rows):
            return
        data = self.current_rows[row]
        self.current_index = row
        self.punjabi.setText(data["native_word"])
        self.roman.setText(data["romanized_word"])
        self.meta.setPlainText(
            f"Source: {data['source'] or '—'}\n"
            f"Split: {data['split']}\n"
            f"Original ID: {data['unique_identifier']}\n"
            f"Database ID: {data['id']}"
        )
        self.bookmark_btn.setText(
            "★ Bookmarked" if data["id"] in self.bookmarks else "☆ Bookmark"
        )

    def previous_entry(self):
        if self.current_index > 0:
            self.table.selectRow(self.current_index - 1)

    def next_entry(self):
        if self.current_index + 1 < len(self.current_rows):
            self.table.selectRow(self.current_index + 1)

    def random_entry(self):
        if not self.db:
            return
        split = self.split.currentText()
        if split == "All splits":
            row = self.db.execute(
                "SELECT * FROM entries ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
        else:
            row = self.db.execute(
                "SELECT * FROM entries WHERE split=? ORDER BY RANDOM() LIMIT 1",
                (split,)
            ).fetchone()
        if row:
            self.query.setText(row["native_word"])
            self.search()
            for i, r in enumerate(self.current_rows):
                if r["id"] == row["id"]:
                    self.table.selectRow(i)
                    break

    def toggle_bookmark(self):
        if self.current_index < 0 or self.current_index >= len(self.current_rows):
            return
        ident = self.current_rows[self.current_index]["id"]
        if ident in self.bookmarks:
            self.bookmarks.remove(ident)
        else:
            self.bookmarks.add(ident)
        self.show_selected()

    def show_bookmarks(self):
        if not self.bookmarks:
            QMessageBox.information(self, APP, "No bookmarks yet.")
            return
        ids = list(self.bookmarks)
        placeholders = ",".join("?" for _ in ids)
        rows = self.db.execute(
            f"SELECT id,native_word,romanized_word,source,split "
            f"FROM entries WHERE id IN ({placeholders}) ORDER BY native_word",
            ids
        ).fetchall()
        self.current_rows = rows
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, value in enumerate(
                [row["native_word"], row["romanized_word"], row["source"] or "", row["split"]]
            ):
                self.table.setItem(r, c, QTableWidgetItem(str(value)))
        self.results_label.setText(f"Bookmarks  •  {len(rows):,}")
        if rows:
            self.table.selectRow(0)

    def export_results(self):
        if not self.current_rows:
            QMessageBox.information(self, APP, "There are no results to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Results", "punjabi_transliteration_results.csv",
            "CSV Files (*.csv);;Text Files (*.txt)"
        )
        if not path:
            return
        if path.lower().endswith(".txt"):
            with open(path, "w", encoding="utf-8") as f:
                for r in self.current_rows:
                    f.write(f"{r['native_word']}\t{r['romanized_word']}\t{r['source'] or ''}\t{r['split']}\n")
        else:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["Punjabi", "Romanized", "Source", "Split", "Original ID"])
                for r in self.current_rows:
                    w.writerow([r["native_word"], r["romanized_word"], r["source"] or "", r["split"], r["unique_identifier"]])
        self.status.showMessage(f"Exported {len(self.current_rows):,} rows")

    def clear_search(self):
        self.query.clear()
        self.table.setRowCount(0)
        self.current_rows = []
        self.punjabi.setText("—")
        self.roman.setText("—")
        self.meta.clear()
        self.results_label.setText("Results")
        self.status.showMessage("Cleared")

    def go_back(self):
        if self.history_pos > 0:
            self.history_pos -= 1
            self.query.setText(self.history[self.history_pos])
            self.search()

    def go_forward(self):
        if self.history_pos + 1 < len(self.history):
            self.history_pos += 1
            self.query.setText(self.history[self.history_pos])
            self.search()

    def show_stats(self):
        if self.db:
            StatsDialog(self.db, self).exec()

    def toggle_theme(self):
        self.dark = not self.dark
        self.apply_style()

    def apply_style(self):
        if self.dark:
            self.setStyleSheet("""
                QWidget { background:#18202a; color:#e8edf3; font-size:14px; }
                QLineEdit,QComboBox,QTextEdit,QTableWidget {
                    background:#202a36; color:#f2f5f8; border:1px solid #3b4a5a;
                    border-radius:8px; padding:7px;
                }
                QPushButton { background:#2b3948; color:#f2f5f8; border:1px solid #46576a;
                    border-radius:8px; padding:8px 12px; }
                QPushButton:hover { background:#35475a; }
                QHeaderView::section { background:#273444; color:#f2f5f8; padding:7px; }
                QTableWidget::item:selected { background:#3b5875; }
                #panel { background:#1e2833; border:1px solid #354555; border-radius:12px; }
                #title { font-size:25px; font-weight:700; }
                #section { font-size:17px; font-weight:700; }
                #punjabi { font-size:34px; font-weight:700; padding:14px; }
                #roman { font-size:24px; font-weight:600; padding:10px; }
            """)
            self.theme_btn.setText("☀ Light")
        else:
            self.setStyleSheet("""
                QWidget { font-size:14px; }
                QLineEdit,QComboBox,QTextEdit,QTableWidget {
                    border:1px solid #cfd6df; border-radius:8px; padding:7px;
                }
                QPushButton { border:1px solid #c7d0da; border-radius:8px; padding:8px 12px; }
                QPushButton:hover { background:#eef3f8; }
                QHeaderView::section { padding:7px; }
                #panel { border:1px solid #d9e0e7; border-radius:12px; }
                #title { font-size:25px; font-weight:700; }
                #section { font-size:17px; font-weight:700; }
                #punjabi { font-size:34px; font-weight:700; padding:14px; }
                #roman { font-size:24px; font-weight:600; padding:10px; }
            """)
            self.theme_btn.setText("☾ Dark")

    def closeEvent(self, event):
        if self.db:
            self.db.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setStyle("Fusion")
    win = DictionaryWindow()
    win.apply_style()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

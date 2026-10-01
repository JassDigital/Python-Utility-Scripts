import sys
import sqlite3
from pathlib import Path
from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTextEdit, QLabel, QPushButton, QComboBox, QCheckBox,
    QSpinBox, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QStatusBar, QFrame
)

APP = "JASS Punjabi Transliterator"
DB_NAME = "JASS_Punjabi_Aksharantar.db"


class PunjabiTransliterator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = None
        self.dark = False
        self.font_size = 22
        self.last_candidates = {}
        self.setWindowTitle(APP)
        self.resize(1400, 900)
        self.setMinimumSize(1050, 700)
        self.build_ui()
        self.apply_style()
        self.open_database()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(18, 16, 18, 14)
        main.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("JASS Punjabi Transliterator")
        title.setObjectName("title")
        subtitle = QLabel("Roman Punjabi → ਪੰਜਾਬੀ Gurmukhi")
        subtitle.setObjectName("subtitle")
        header.addWidget(title)
        header.addSpacing(14)
        header.addWidget(subtitle)
        header.addStretch()

        self.theme_btn = QPushButton("☾ Dark")
        self.stats_btn = QPushButton("📊 Corpus")
        self.theme_btn.clicked.connect(self.toggle_theme)
        self.stats_btn.clicked.connect(self.show_stats)
        header.addWidget(self.stats_btn)
        header.addWidget(self.theme_btn)
        main.addLayout(header)

        tabs = QTabWidget()
        tabs.addTab(self.writer_tab(), "✍ Text Writer")
        tabs.addTab(self.corpus_tab(), "🔎 Corpus")
        main.addWidget(tabs, 1)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

        self.create_menu()

    def writer_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 10, 4, 4)

        controls = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Roman → Gurmukhi", "Gurmukhi → Roman"])
        self.auto = QCheckBox("Convert as you type")
        self.auto.setChecked(False)
        self.font_spin = QSpinBox()
        self.font_spin.setRange(14, 48)
        self.font_spin.setValue(self.font_size)
        self.font_spin.valueChanged.connect(self.change_font)

        controls.addWidget(QLabel("Direction"))
        controls.addWidget(self.mode)
        controls.addSpacing(10)
        controls.addWidget(self.auto)
        controls.addStretch()
        controls.addWidget(QLabel("Text size"))
        controls.addWidget(self.font_spin)
        lay.addLayout(controls)

        splitter = QSplitter(Qt.Horizontal)

        left = QFrame()
        left.setObjectName("editorPanel")
        ll = QVBoxLayout(left)
        lhead = QHBoxLayout()
        lhead.addWidget(QLabel("Roman Punjabi"))
        lhead.addStretch()
        self.input_count = QLabel("0 words • 0 characters")
        lhead.addWidget(self.input_count)
        ll.addLayout(lhead)

        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText(
            "Write or paste Roman Punjabi here…\n\n"
            "Example:\n"
            "mera naam jass hai\n"
            "main punjabi likh reha haan"
        )
        self.input_edit.textChanged.connect(self.input_changed)
        ll.addWidget(self.input_edit, 1)

        right = QFrame()
        right.setObjectName("editorPanel")
        rl = QVBoxLayout(right)
        rhead = QHBoxLayout()
        rhead.addWidget(QLabel("ਪੰਜਾਬੀ  Gurmukhi"))
        rhead.addStretch()
        self.output_count = QLabel("0 words • 0 characters")
        rhead.addWidget(self.output_count)
        rl.addLayout(rhead)

        self.output_edit = QTextEdit()
        self.output_edit.setPlaceholderText("Converted Gurmukhi text will appear here…")
        rl.addWidget(self.output_edit, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([680, 680])
        lay.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        self.convert_btn = QPushButton("→  Convert")
        self.copy_btn = QPushButton("📋 Copy Gurmukhi")
        self.copy_input_btn = QPushButton("Copy Input")
        self.save_btn = QPushButton("💾 Save")
        self.open_btn = QPushButton("📂 Open")
        self.clear_btn = QPushButton("✕ Clear")

        self.convert_btn.clicked.connect(self.convert_text)
        self.copy_btn.clicked.connect(self.copy_output)
        self.copy_input_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.input_edit.toPlainText()))
        self.save_btn.clicked.connect(self.save_document)
        self.open_btn.clicked.connect(self.open_document)
        self.clear_btn.clicked.connect(self.clear_writer)

        for b in [self.convert_btn, self.copy_btn, self.copy_input_btn,
                  self.open_btn, self.save_btn, self.clear_btn]:
            buttons.addWidget(b)
        buttons.addStretch()
        lay.addLayout(buttons)

        self.suggestion_label = QLabel("Suggestions appear here after conversion.")
        self.suggestion_label.setObjectName("suggestion")
        lay.addWidget(self.suggestion_label)

        return page

    def corpus_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)

        bar = QHBoxLayout()
        self.corpus_query = QTextEdit()
        self.corpus_query.setFixedHeight(42)
        self.corpus_query.setPlaceholderText("Search a Punjabi or Roman word…")
        self.corpus_direction = QComboBox()
        self.corpus_direction.addItems(["Romanized", "Punjabi", "Both"])
        search = QPushButton("🔎 Search")
        search.clicked.connect(self.corpus_search)
        self.corpus_query.textChanged.connect(
            lambda: self.corpus_query.setFixedHeight(42)
        )
        bar.addWidget(self.corpus_query, 1)
        bar.addWidget(self.corpus_direction)
        bar.addWidget(search)
        lay.addLayout(bar)

        self.corpus_table = QTableWidget(0, 4)
        self.corpus_table.setHorizontalHeaderLabels(
            ["Punjabi", "Romanized", "Source", "Split"]
        )
        self.corpus_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.corpus_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.corpus_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.corpus_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.corpus_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.corpus_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.corpus_table.itemDoubleClicked.connect(self.use_corpus_entry)
        lay.addWidget(self.corpus_table, 1)

        note = QLabel("Double-click an entry to send it to the writer.")
        note.setObjectName("muted")
        lay.addWidget(note)
        return page

    def create_menu(self):
        file_menu = self.menuBar().addMenu("&File")

        new_action = QAction("New Writer", self)
        new_action.setShortcut(QKeySequence("Ctrl+N"))
        new_action.triggered.connect(self.clear_writer)
        file_menu.addAction(new_action)

        open_action = QAction("Open Text…", self)
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self.open_document)
        file_menu.addAction(open_action)

        save_action = QAction("Save Text…", self)
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        save_action.triggered.connect(self.save_document)
        file_menu.addAction(save_action)

        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        tools = self.menuBar().addMenu("&Tools")
        convert_action = QAction("Convert", self)
        convert_action.setShortcut(QKeySequence("Ctrl+Enter"))
        convert_action.triggered.connect(self.convert_text)
        tools.addAction(convert_action)

    def open_database(self):
        path = Path(__file__).with_name(DB_NAME)
        if not path.exists():
            path_str, _ = QFileDialog.getOpenFileName(
                self, "Select Punjabi Aksharantar Database",
                str(path.parent), "SQLite Database (*.db)"
            )
            if not path_str:
                QMessageBox.warning(
                    self, APP,
                    f"Place {DB_NAME} beside this application or select the database."
                )
                return
            path = Path(path_str)

        try:
            self.db = sqlite3.connect(str(path))
            self.db.row_factory = sqlite3.Row
            self.db.execute("SELECT COUNT(*) FROM entries").fetchone()
            total = self.db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            self.status.showMessage(f"Database loaded • {total:,} transliteration records")
        except Exception as e:
            QMessageBox.critical(self, APP, f"Could not open database:\n{e}")

    def lookup(self, word, direction):
        if not self.db or not word.strip():
            return []

        word = word.strip()
        if direction == "roman":
            rows = self.db.execute(
                """SELECT native_word, romanized_word, source, split
                   FROM entries
                   WHERE romanized_word = ?
                   ORDER BY native_word
                   LIMIT 20""", (word,)
            ).fetchall()
            if not rows:
                rows = self.db.execute(
                    """SELECT native_word, romanized_word, source, split
                       FROM entries
                       WHERE romanized_word LIKE ?
                       ORDER BY native_word
                       LIMIT 20""", (word + "%",)
                ).fetchall()
        else:
            rows = self.db.execute(
                """SELECT native_word, romanized_word, source, split
                   FROM entries
                   WHERE native_word = ?
                   ORDER BY romanized_word
                   LIMIT 20""", (word,)
            ).fetchall()
            if not rows:
                rows = self.db.execute(
                    """SELECT native_word, romanized_word, source, split
                       FROM entries
                       WHERE native_word LIKE ?
                       ORDER BY romanized_word
                       LIMIT 20""", (word + "%",)
                ).fetchall()
        return rows

    def convert_text(self):
        text = self.input_edit.toPlainText()
        if not text.strip():
            self.output_edit.clear()
            return

        reverse = self.mode.currentIndex() == 1
        direction = "gurmukhi" if reverse else "roman"

        # Preserve whitespace and punctuation while replacing word-like tokens.
        import re
        pattern = re.compile(r"\S+")

        pieces = []
        suggestions = []
        cache = {}

        for match in pattern.finditer(text):
            token = match.group(0)
            leading = ""
            trailing = ""

            while token and not token[0].isalnum() and token[0] not in "ਅ-ਹ":
                leading += token[0]
                token = token[1:]
            while token and not token[-1].isalnum() and token[-1] not in "ਅ-ਹ":
                trailing = token[-1] + trailing
                token = token[:-1]

            if not token:
                pieces.append(match.group(0))
                continue

            key = (token.lower(), direction)
            if key not in cache:
                cache[key] = self.lookup(token, direction)
            rows = cache[key]

            if rows:
                chosen = rows[0]["romanized_word"] if reverse else rows[0]["native_word"]
                if reverse:
                    chosen = rows[0]["romanized_word"]
                pieces.append(leading + chosen + trailing)
                unique = []
                for r in rows:
                    val = r["romanized_word"] if reverse else r["native_word"]
                    if val not in unique:
                        unique.append(val)
                if len(unique) > 1:
                    suggestions.append(f"{token} → {', '.join(unique[:6])}")
            else:
                pieces.append(match.group(0))

        # Reconstruct exactly, including spaces/newlines.
        out = []
        pos = 0
        for match, replacement in zip(pattern.finditer(text), pieces):
            out.append(text[pos:match.start()])
            out.append(replacement)
            pos = match.end()
        out.append(text[pos:])
        result = "".join(out)

        self.output_edit.setPlainText(result)
        self.update_counts()
        if suggestions:
            self.suggestion_label.setText(
                "Multiple matches: " + "   •   ".join(suggestions[:8])
            )
        else:
            self.suggestion_label.setText(
                "Converted using the Aksharantar corpus. Unmatched words are preserved."
            )

    def input_changed(self):
        self.update_counts()
        if self.auto.isChecked():
            self.convert_text()

    def update_counts(self):
        a = self.input_edit.toPlainText()
        b = self.output_edit.toPlainText()
        self.input_count.setText(f"{len(a.split()):,} words • {len(a):,} characters")
        self.output_count.setText(f"{len(b.split()):,} words • {len(b):,} characters")

    def copy_output(self):
        QApplication.clipboard().setText(self.output_edit.toPlainText())
        self.status.showMessage("Gurmukhi text copied to clipboard")

    def save_document(self):
        text = self.output_edit.toPlainText()
        if not text:
            text = self.input_edit.toPlainText()
        if not text:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Text", "punjabi_document.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        if path:
            Path(path).write_text(text, encoding="utf-8")
            self.status.showMessage(f"Saved: {Path(path).name}")

    def open_document(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Text", "", "Text Files (*.txt);;All Files (*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = Path(path).read_text(encoding="utf-8-sig")
        self.input_edit.setPlainText(text)
        self.status.showMessage(f"Opened: {Path(path).name}")

    def clear_writer(self):
        self.input_edit.clear()
        self.output_edit.clear()
        self.suggestion_label.setText("Suggestions appear here after conversion.")
        self.status.showMessage("Writer cleared")

    def corpus_search(self):
        if not self.db:
            return
        q = self.corpus_query.toPlainText().strip()
        if not q:
            return

        direction = self.corpus_direction.currentText()
        if direction == "Romanized":
            cond = "romanized_word LIKE ?"
        elif direction == "Punjabi":
            cond = "native_word LIKE ?"
        else:
            cond = "(native_word LIKE ? OR romanized_word LIKE ?)"

        args = [q + "%"] if direction != "Both" else [q + "%", q + "%"]
        rows = self.db.execute(
            f"""SELECT native_word, romanized_word, source, split
                FROM entries WHERE {cond}
                ORDER BY native_word LIMIT 500""", args
        ).fetchall()

        self.corpus_table.setRowCount(0)
        for row in rows:
            r = self.corpus_table.rowCount()
            self.corpus_table.insertRow(r)
            for c, val in enumerate(
                [row["native_word"], row["romanized_word"],
                 row["source"] or "", row["split"]]
            ):
                self.corpus_table.setItem(r, c, QTableWidgetItem(str(val)))
        self.status.showMessage(f"{len(rows):,} corpus result(s)")

    def use_corpus_entry(self, item):
        row = item.row()
        punjabi = self.corpus_table.item(row, 0).text()
        roman = self.corpus_table.item(row, 1).text()
        self.input_edit.setPlainText(roman)
        self.output_edit.setPlainText(punjabi)
        self.update_counts()
        self.status.showMessage("Corpus entry sent to writer")

    def change_font(self, value):
        self.font_size = value
        f1 = QFont()
        f1.setPointSize(value)
        self.input_edit.setFont(f1)
        f2 = QFont()
        f2.setPointSize(value)
        f2.setBold(True)
        self.output_edit.setFont(f2)

    def show_stats(self):
        if not self.db:
            return
        total = self.db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        train = self.db.execute("SELECT COUNT(*) FROM entries WHERE split='train'").fetchone()[0]
        valid = self.db.execute("SELECT COUNT(*) FROM entries WHERE split='valid'").fetchone()[0]
        test = self.db.execute("SELECT COUNT(*) FROM entries WHERE split='test'").fetchone()[0]
        sources = self.db.execute("SELECT COUNT(DISTINCT source) FROM entries").fetchone()[0]
        QMessageBox.information(
            self, "Corpus Statistics",
            f"JASS Punjabi Aksharantar Corpus\n\n"
            f"Total records: {total:,}\n"
            f"Train: {train:,}\n"
            f"Validation: {valid:,}\n"
            f"Test: {test:,}\n"
            f"Sources: {sources:,}\n\n"
            f"Database: {DB_NAME}"
        )

    def toggle_theme(self):
        self.dark = not self.dark
        self.apply_style()

    def apply_style(self):
        if self.dark:
            self.setStyleSheet("""
                QWidget { background:#18212b; color:#edf2f7; font-size:14px; }
                QLineEdit,QTextEdit,QComboBox,QSpinBox,QTableWidget {
                    background:#202b38; color:#edf2f7;
                    border:1px solid #405064; border-radius:9px; padding:7px;
                }
                QPushButton { background:#2c3a4b; color:#f5f7fa;
                    border:1px solid #4a5d72; border-radius:9px; padding:9px 14px; }
                QPushButton:hover { background:#374a60; }
                QTabBar::tab { padding:10px 18px; }
                QHeaderView::section { background:#293747; color:#edf2f7; padding:8px; }
                QTableWidget::item:selected { background:#3e5c7c; }
                QSplitter::handle { background:#314052; }
                #title { font-size:27px; font-weight:800; }
                #subtitle { font-size:16px; }
                #editorPanel { border:1px solid #3a4a5d; border-radius:13px; padding:4px; }
                #suggestion { padding:8px; border-radius:8px; }
                #muted { color:#9eabb9; }
            """)
            self.theme_btn.setText("☀ Light")
        else:
            self.setStyleSheet("""
                QWidget { font-size:14px; }
                QLineEdit,QTextEdit,QComboBox,QSpinBox,QTableWidget {
                    border:1px solid #cfd7df; border-radius:9px; padding:7px;
                }
                QPushButton { border:1px solid #c8d1db; border-radius:9px; padding:9px 14px; }
                QPushButton:hover { background:#eef3f7; }
                QTabBar::tab { padding:10px 18px; }
                QHeaderView::section { padding:8px; }
                QTableWidget::item:selected { background:#dce9f5; }
                #title { font-size:27px; font-weight:800; }
                #subtitle { font-size:16px; }
                #editorPanel { border:1px solid #d7dee6; border-radius:13px; padding:4px; }
                #suggestion { padding:8px; border-radius:8px; }
                #muted { color:#6c7782; }
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
    win = PunjabiTransliterator()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

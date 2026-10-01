import csv
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QFont, QTextCursor, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QPlainTextEdit, QLineEdit,
    QCheckBox, QProgressBar, QMessageBox, QSplitter, QGroupBox,
    QFormLayout, QTableWidget, QTableWidgetItem, QTabWidget
)

APP_NAME = "JASS Text File Analyzer"
VERSION = "1.0"


def detect_encoding(path):
    raw = Path(path).read_bytes()[:1024 * 1024]
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            pass
    return "utf-8"


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def analyze_text(path, encoding, signals):
    size = os.path.getsize(path)
    text = Path(path).read_text(encoding=encoding, errors="replace")
    lines = text.splitlines()

    line_count = len(lines)
    empty_lines = sum(1 for line in lines if not line.strip())
    nonempty = [line for line in lines if line.strip()]
    word_list = re.findall(r"\b[\w'’-]+\b", text, flags=re.UNICODE)

    paragraphs = len(re.findall(r"(?:^|\n)\s*\S(?:.*\S)?(?:\n\s*\S(?:.*\S)?)*", text))
    duplicate_counts = Counter(lines)
    duplicates = [(line, count) for line, count in duplicate_counts.items()
                  if line.strip() and count > 1]
    duplicates.sort(key=lambda x: (-x[1], x[0].lower()))

    word_counts = Counter(w.lower() for w in word_list)
    common_words = word_counts.most_common(50)

    lengths = [len(line) for line in lines]
    result = {
        "file": Path(path).name,
        "path": str(Path(path).resolve()),
        "size": size,
        "size_display": human_size(size),
        "encoding": encoding,
        "lines": line_count,
        "nonempty_lines": len(nonempty),
        "empty_lines": empty_lines,
        "words": len(word_list),
        "unique_words": len(word_counts),
        "characters": len(text),
        "characters_no_spaces": len(re.sub(r"\s", "", text)),
        "paragraphs": paragraphs,
        "average_line_length": (sum(lengths) / len(lengths)) if lengths else 0,
        "longest_line": max(lengths, default=0),
        "shortest_line": min(lengths, default=0),
        "duplicate_lines": len(duplicates),
        "duplicate_line_occurrences": sum(c - 1 for _, c in duplicates),
        "common_words": common_words,
        "duplicate_examples": duplicates[:100],
        "lines_data": lines,
        "text": text,
    }
    signals.progress.emit(100)
    return result


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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1350, 850)
        self.path = None
        self.result = None
        self.worker = None
        self.threadpool = QThreadPool.globalInstance()
        self.build_ui()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        header = QHBoxLayout()
        title = QLabel("JASS Text File Analyzer")
        title.setObjectName("Title")
        subtitle = QLabel("Text statistics • duplicate lines • word analysis • search")
        subtitle.setObjectName("Muted")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch()
        layout.addLayout(header)

        controls = QHBoxLayout()
        open_btn = QPushButton("Open Text File")
        open_btn.clicked.connect(self.open_file)
        controls.addWidget(open_btn)

        self.encoding_label = QLabel("Encoding: Auto")
        controls.addWidget(self.encoding_label)

        controls.addStretch()

        export_json = QPushButton("Export JSON")
        export_json.clicked.connect(self.export_json)
        controls.addWidget(export_json)

        export_csv = QPushButton("Export CSV")
        export_csv.clicked.connect(self.export_csv)
        controls.addWidget(export_csv)

        export_txt = QPushButton("Export Report")
        export_txt.clicked.connect(self.export_txt)
        controls.addWidget(export_txt)

        layout.addLayout(controls)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search text or regular expression...")
        self.search.returnPressed.connect(self.search_text)
        search_row.addWidget(self.search, 1)

        self.regex_box = QCheckBox("Regex")
        search_row.addWidget(self.regex_box)

        self.case_box = QCheckBox("Case sensitive")
        search_row.addWidget(self.case_box)

        find_btn = QPushButton("Find")
        find_btn.clicked.connect(self.search_text)
        search_row.addWidget(find_btn)
        ll.addLayout(search_row)

        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setPlaceholderText("Open a text file to view it.")
        ll.addWidget(self.editor, 1)

        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)

        info_box = QGroupBox("File Statistics")
        form = QFormLayout(info_box)
        self.labels = {}
        for label, key in [
            ("File", "file"), ("Size", "size_display"),
            ("Encoding", "encoding"), ("Lines", "lines"),
            ("Non-empty lines", "nonempty_lines"), ("Empty lines", "empty_lines"),
            ("Words", "words"), ("Unique words", "unique_words"),
            ("Characters", "characters"),
            ("Characters without spaces", "characters_no_spaces"),
            ("Paragraphs", "paragraphs"),
            ("Average line length", "average_line_length"),
            ("Longest line", "longest_line"),
            ("Shortest line", "shortest_line"),
            ("Duplicate lines", "duplicate_lines"),
        ]:
            value = QLabel("-")
            value.setWordWrap(True)
            self.labels[key] = value
            form.addRow(label + ":", value)
        rl.addWidget(info_box)

        tabs = QTabWidget()

        words_tab = QWidget()
        wl = QVBoxLayout(words_tab)
        self.words_table = QTableWidget(0, 2)
        self.words_table.setHorizontalHeaderLabels(["Word", "Count"])
        self.words_table.setEditTriggers(QTableWidget.NoEditTriggers)
        wl.addWidget(self.words_table)
        tabs.addTab(words_tab, "Frequent Words")

        dup_tab = QWidget()
        dl = QVBoxLayout(dup_tab)
        self.dup_table = QTableWidget(0, 2)
        self.dup_table.setHorizontalHeaderLabels(["Duplicate Line", "Occurrences"])
        self.dup_table.setEditTriggers(QTableWidget.NoEditTriggers)
        dl.addWidget(self.dup_table)
        tabs.addTab(dup_tab, "Duplicate Lines")

        rl.addWidget(tabs, 1)
        splitter.addWidget(right)
        splitter.setSizes([820, 480])

        layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.progress = QProgressBar()
        self.status = QLabel("Ready")
        self.status.setObjectName("Muted")
        self.match_label = QLabel("")
        footer.addWidget(self.progress, 1)
        footer.addWidget(self.status)
        footer.addWidget(self.match_label)
        layout.addLayout(footer)

        self.setStyleSheet("""
            QWidget { background:#151922; color:#e8edf5; font-size:10.5pt; }
            QLabel#Title { font-size:20pt; font-weight:700; }
            QLabel#Muted { color:#8e9aaa; }
            QGroupBox { border:1px solid #303746; border-radius:8px;
                        margin-top:10px; padding:10px; }
            QGroupBox::title { subcontrol-origin:margin; left:10px;
                                padding:0 5px; color:#aeb9ca; }
            QPushButton,QLineEdit {
                background:#222938; border:1px solid #3a4354;
                border-radius:6px; padding:7px 10px;
            }
            QPushButton:hover { background:#2b3445; }
            QLineEdit { background:#10141c; }
            QPlainTextEdit,QTableWidget {
                background:#10141c; border:1px solid #303746;
                gridline-color:#2b3342;
            }
            QTableWidget::item:selected { background:#294766; }
            QHeaderView::section {
                background:#222938; color:#dce5f2; border:0;
                border-right:1px solid #303746;
                border-bottom:1px solid #303746; padding:7px;
            }
            QTabWidget::pane { border:1px solid #303746; }
            QProgressBar { border:1px solid #303746; border-radius:5px;
                           text-align:center; background:#10141c; }
            QProgressBar::chunk { background:#4d8dcc; border-radius:4px; }
        """)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Text File", "",
            "Text Files (*.txt *.md *.log *.csv *.tsv *.ini *.cfg *.json *.xml *.html *.htm *.py *.ps1 *.bat *.cmd *.yaml *.yml);;All Files (*.*)"
        )
        if not path:
            return

        self.path = path
        encoding = detect_encoding(path)
        self.encoding_label.setText(f"Encoding: {encoding}")
        self.progress.setValue(0)
        self.status.setText("Analyzing...")
        self.editor.clear()

        self.worker = Worker(analyze_text, path, encoding)
        self.worker.signals.progress.connect(self.progress.setValue)
        self.worker.signals.result.connect(self.analysis_complete)
        self.worker.signals.error.connect(self.analysis_error)
        self.worker.signals.finished.connect(self.worker_finished)
        self.threadpool.start(self.worker)

    def analysis_complete(self, result):
        self.result = result
        self.editor.setPlainText(result["text"])
        self.editor.moveCursor(QTextCursor.Start)

        for key, label in self.labels.items():
            value = result.get(key, "-")
            if key == "average_line_length":
                value = f"{value:.2f}"
            label.setText(f"{value:,}" if isinstance(value, int) else str(value))

        self.populate_words()
        self.populate_duplicates()
        self.status.setText("Analysis complete")
        self.progress.setValue(100)

    def analysis_error(self, message):
        self.status.setText("Analysis failed")
        QMessageBox.critical(self, "Text analysis error", message)

    def worker_finished(self):
        self.worker = None

    def populate_words(self):
        rows = self.result["common_words"]
        self.words_table.setRowCount(len(rows))
        for r, (word, count) in enumerate(rows):
            self.words_table.setItem(r, 0, QTableWidgetItem(word))
            self.words_table.setItem(r, 1, QTableWidgetItem(str(count)))
        self.words_table.resizeColumnsToContents()

    def populate_duplicates(self):
        rows = self.result["duplicate_examples"]
        self.dup_table.setRowCount(len(rows))
        for r, (line, count) in enumerate(rows):
            self.dup_table.setItem(r, 0, QTableWidgetItem(line))
            self.dup_table.setItem(r, 1, QTableWidgetItem(str(count)))
        self.dup_table.resizeColumnsToContents()

    def search_text(self):
        if not self.result:
            return
        query = self.search.text()
        if not query:
            return

        text = self.result["text"]
        flags = 0 if self.case_box.isChecked() else re.IGNORECASE
        cursor = self.editor.textCursor()

        try:
            if self.regex_box.isChecked():
                pattern = re.compile(query, flags)
                match = pattern.search(text, cursor.position())
                if not match:
                    match = pattern.search(text, 0)
            else:
                haystack = text if self.case_box.isChecked() else text.lower()
                needle = query if self.case_box.isChecked() else query.lower()
                start = cursor.position()
                pos = haystack.find(needle, start)
                if pos < 0:
                    pos = haystack.find(needle, 0)
                match = None if pos < 0 else (pos, pos + len(query))

            if match is None:
                self.status.setText("No match found")
                self.match_label.setText("")
                return

            if self.regex_box.isChecked():
                start, end = match.start(), match.end()
            else:
                start, end = match

            cursor = self.editor.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            self.editor.setTextCursor(cursor)
            self.editor.ensureCursorVisible()
            self.status.setText("Match found")
        except re.error as e:
            QMessageBox.warning(self, "Regex error", str(e))

    def export_json(self):
        if not self.result:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export JSON", "", "JSON Files (*.json)"
        )
        if not path:
            return
        data = {k: v for k, v in self.result.items()
                if k not in {"text", "lines_data"}}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Export", "JSON report exported.")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def export_csv(self):
        if not self.result:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "", "CSV Files (*.csv)"
        )
        if not path:
            return
        fields = [
            "file", "path", "size", "size_display", "encoding", "lines",
            "nonempty_lines", "empty_lines", "words", "unique_words",
            "characters", "characters_no_spaces", "paragraphs",
            "average_line_length", "longest_line", "shortest_line",
            "duplicate_lines", "duplicate_line_occurrences"
        ]
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerow({k: self.result.get(k, "") for k in fields})
            QMessageBox.information(self, "Export", "CSV report exported.")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def export_txt(self):
        if not self.result:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Text Report", "", "Text Files (*.txt)"
        )
        if not path:
            return

        r = self.result
        lines = [
            "JASS Text File Analyzer Report",
            "=" * 32,
            f"File: {r['file']}",
            f"Path: {r['path']}",
            f"Size: {r['size_display']}",
            f"Encoding: {r['encoding']}",
            f"Lines: {r['lines']}",
            f"Non-empty lines: {r['nonempty_lines']}",
            f"Empty lines: {r['empty_lines']}",
            f"Words: {r['words']}",
            f"Unique words: {r['unique_words']}",
            f"Characters: {r['characters']}",
            f"Characters without spaces: {r['characters_no_spaces']}",
            f"Paragraphs: {r['paragraphs']}",
            f"Average line length: {r['average_line_length']:.2f}",
            f"Longest line: {r['longest_line']}",
            f"Shortest line: {r['shortest_line']}",
            f"Duplicate lines: {r['duplicate_lines']}",
            "",
            "Most Frequent Words",
            "--------------------",
        ]
        lines.extend(f"{word}: {count}" for word, count in r["common_words"])
        lines.extend(["", "Duplicate Lines", "---------------"])
        for line, count in r["duplicate_examples"]:
            lines.append(f"[{count}x] {line}")

        try:
            Path(path).write_text("\n".join(lines), encoding="utf-8")
            QMessageBox.information(self, "Export", "Text report exported.")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

import csv
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QLineEdit, QComboBox, QCheckBox, QProgressBar, QMessageBox,
    QSplitter, QGroupBox, QFormLayout, QAbstractItemView
)

APP_NAME = "JASS CSV Explorer"
VERSION = "1.1"


def detect_encoding(path):
    raw = Path(path).read_bytes()[:1024 * 1024]
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            pass
    return "utf-8"


def detect_delimiter(path, encoding):
    with open(path, "r", encoding=encoding, errors="replace", newline="") as f:
        sample = f.read(8192)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except csv.Error:
        return ","


def display_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


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


def load_csv(path, encoding, delimiter, max_rows, signals):
    rows = []
    total = max(1, os.path.getsize(path))
    with open(path, "r", encoding=encoding, errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        header = next(reader, [])
        for row in reader:
            rows.append(row)
            if len(rows) >= max_rows:
                break
            if len(rows) % 1000 == 0:
                signals.progress.emit(min(99, int(len(rows) * 100 / max_rows)))
    signals.progress.emit(100)
    return header, rows


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1280, 780)
        self.path = None
        self.encoding = "utf-8"
        self.delimiter = ","
        self.headers = []
        self.original_rows = []
        self.filtered_rows = []
        self.threadpool = QThreadPool.globalInstance()
        self.worker = None
        self.build_ui()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        header = QHBoxLayout()
        title = QLabel("JASS CSV Explorer")
        title.setObjectName("Title")
        subtitle = QLabel("CSV / TSV inspection and analysis")
        subtitle.setObjectName("Muted")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch()
        layout.addLayout(header)

        controls = QHBoxLayout()
        open_btn = QPushButton("Open CSV / TSV")
        open_btn.clicked.connect(self.open_file)
        controls.addWidget(open_btn)

        self.delimiter_box = QComboBox()
        self.delimiter_box.addItems(
            ["Auto", "Comma (,)", "Tab", "Semicolon (;)", "Pipe (|)"]
        )
        self.delimiter_box.currentIndexChanged.connect(self.reload_current)
        controls.addWidget(self.delimiter_box)

        self.encoding_box = QComboBox()
        self.encoding_box.addItems(
            ["Auto", "UTF-8", "UTF-8-SIG", "Windows-1252", "Latin-1"]
        )
        self.encoding_box.currentIndexChanged.connect(self.reload_current)
        controls.addWidget(self.encoding_box)

        controls.addStretch()
        self.export_btn = QPushButton("Export Filtered")
        self.export_btn.clicked.connect(self.export_filtered)
        self.export_btn.setEnabled(False)
        controls.addWidget(self.export_btn)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Vertical)

        table_box = QWidget()
        tl = QVBoxLayout(table_box)
        tl.setContentsMargins(0, 0, 0, 0)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search all columns...")
        self.search.textChanged.connect(self.apply_filter)
        search_row.addWidget(self.search, 1)

        self.case_box = QCheckBox("Case sensitive")
        self.case_box.stateChanged.connect(self.apply_filter)
        search_row.addWidget(self.case_box)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.search.clear)
        search_row.addWidget(clear_btn)
        tl.addLayout(search_row)

        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        tl.addWidget(self.table, 1)
        splitter.addWidget(table_box)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)

        stats_box = QGroupBox("Dataset Information")
        form = QFormLayout(stats_box)
        self.file_info = QLabel("No file loaded")
        self.rows_info = QLabel("-")
        self.columns_info = QLabel("-")
        self.encoding_info = QLabel("-")
        self.delimiter_info = QLabel("-")
        self.filter_info = QLabel("-")
        form.addRow("File:", self.file_info)
        form.addRow("Rows:", self.rows_info)
        form.addRow("Columns:", self.columns_info)
        form.addRow("Encoding:", self.encoding_info)
        form.addRow("Delimiter:", self.delimiter_info)
        form.addRow("Visible rows:", self.filter_info)
        bl.addWidget(stats_box)

        analysis = QHBoxLayout()
        analysis.addWidget(QLabel("Column:"))
        self.column_box = QComboBox()
        self.column_box.currentIndexChanged.connect(self.update_column_stats)
        analysis.addWidget(self.column_box, 1)
        self.stats_label = QLabel("Select a column for statistics.")
        self.stats_label.setWordWrap(True)
        analysis.addWidget(self.stats_label, 3)
        bl.addLayout(analysis)

        splitter.addWidget(bottom)
        splitter.setSizes([570, 180])
        layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.progress = QProgressBar()
        self.status = QLabel("Ready")
        self.status.setObjectName("Muted")
        footer.addWidget(self.progress, 1)
        footer.addWidget(self.status)
        layout.addLayout(footer)

        self.setStyleSheet("""
            QWidget { background:#151922; color:#e8edf5; font-size:10.5pt; }
            QLabel#Title { font-size:20pt; font-weight:700; }
            QLabel#Muted { color:#8e9aaa; }
            QGroupBox { border:1px solid #303746; border-radius:8px;
                        margin-top:10px; padding:10px; }
            QGroupBox::title { subcontrol-origin:margin; left:10px;
                                padding:0 5px; color:#aeb9ca; }
            QPushButton,QComboBox,QLineEdit {
                background:#222938; border:1px solid #3a4354;
                border-radius:6px; padding:7px 10px;
            }
            QPushButton:hover { background:#2b3445; }
            QLineEdit { background:#10141c; }
            QTableWidget {
                background:#10141c; alternate-background-color:#171d28;
                border:1px solid #303746; gridline-color:#2b3342;
            }
            QHeaderView::section {
                background:#222938; color:#dce5f2;
                border:0; border-right:1px solid #303746;
                border-bottom:1px solid #303746; padding:7px;
            }
            QProgressBar { border:1px solid #303746; border-radius:5px;
                           text-align:center; background:#10141c; }
            QProgressBar::chunk { background:#4d8dcc; border-radius:4px; }
        """)

    def selected_encoding(self):
        return {
            "UTF-8": "utf-8",
            "UTF-8-SIG": "utf-8-sig",
            "Windows-1252": "cp1252",
            "Latin-1": "latin-1",
        }.get(self.encoding_box.currentText(), detect_encoding(self.path))

    def selected_delimiter(self):
        return {
            "Comma (,)": ",",
            "Tab": "\t",
            "Semicolon (;)": ";",
            "Pipe (|)": "|",
        }.get(
            self.delimiter_box.currentText(),
            detect_delimiter(self.path, self.selected_encoding())
        )

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open CSV or TSV", "",
            "CSV/TSV Files (*.csv *.tsv *.txt);;All Files (*.*)"
        )
        if path:
            self.path = path
            self.load_current()

    def reload_current(self):
        if self.path and self.worker is None:
            self.load_current()

    def load_current(self):
        self.encoding = self.selected_encoding()
        self.delimiter = self.selected_delimiter()
        self.progress.setValue(0)
        self.status.setText("Loading...")
        self.worker = Worker(
            load_csv, self.path, self.encoding, self.delimiter, 100000
        )
        self.worker.signals.progress.connect(self.progress.setValue)
        self.worker.signals.result.connect(self.loaded)
        self.worker.signals.error.connect(self.load_error)
        self.worker.signals.finished.connect(self.worker_finished)
        self.threadpool.start(self.worker)

    def loaded(self, result):
        self.headers, self.original_rows = result
        self.filtered_rows = list(self.original_rows)
        self.file_info.setText(
            f"{Path(self.path).name} ({display_size(os.path.getsize(self.path))})"
        )
        self.rows_info.setText(f"{len(self.original_rows):,} loaded")
        self.columns_info.setText(f"{len(self.headers):,}")
        self.encoding_info.setText(self.encoding)
        self.delimiter_info.setText(
            "\\t (TAB)" if self.delimiter == "\t" else repr(self.delimiter)
        )
        self.populate_columns()
        self.render_table(self.filtered_rows)
        self.export_btn.setEnabled(True)
        self.status.setText(
            "Loaded first 100,000 rows"
            if os.path.getsize(self.path) > 20 * 1024 * 1024
            else "Loaded"
        )

    def worker_finished(self):
        self.worker = None

    def load_error(self, message):
        self.status.setText("Load failed")
        QMessageBox.critical(self, "CSV load error", message)

    def populate_columns(self):
        self.column_box.blockSignals(True)
        self.column_box.clear()
        for i, name in enumerate(self.headers):
            self.column_box.addItem(str(name) or f"Column {i + 1}", i)
        self.column_box.blockSignals(False)
        self.update_column_stats()

    def render_table(self, rows):
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setColumnCount(len(self.headers))
        self.table.setHorizontalHeaderLabels([
            str(x) or f"Column {i + 1}" for i, x in enumerate(self.headers)
        ])
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c in range(len(self.headers)):
                value = row[c] if c < len(row) else ""
                self.table.setItem(r, c, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        for c in range(self.table.columnCount()):
            if self.table.columnWidth(c) > 350:
                self.table.setColumnWidth(c, 350)
        self.table.setSortingEnabled(True)
        self.filter_info.setText(f"{len(rows):,}")

    def apply_filter(self):
        if not self.headers:
            return
        term = self.search.text()
        if not term:
            rows = list(self.original_rows)
        else:
            needle = term if self.case_box.isChecked() else term.lower()
            rows = []
            for row in self.original_rows:
                hay = " | ".join(str(v) for v in row)
                target = hay if self.case_box.isChecked() else hay.lower()
                if needle in target:
                    rows.append(row)
        self.filtered_rows = rows
        self.render_table(rows)
        self.status.setText(
            f"Showing {len(rows):,} of {len(self.original_rows):,} rows"
        )

    def update_column_stats(self):
        idx = self.column_box.currentData()
        if idx is None:
            self.stats_label.setText("Select a column for statistics.")
            return
        values = [
            row[idx] if idx < len(row) else "" for row in self.original_rows
        ]
        nonempty = [str(v).strip() for v in values if str(v).strip()]
        numeric = []
        for value in nonempty:
            try:
                numeric.append(float(value.replace(",", "")))
            except ValueError:
                pass
        text = (
            f"Values: {len(values):,} • Non-empty: {len(nonempty):,} • "
            f"Empty: {len(values)-len(nonempty):,} • "
            f"Unique: {len(set(nonempty)):,}"
        )
        if numeric and len(numeric) == len(nonempty):
            text += (
                f" • Min: {min(numeric):g} • Max: {max(numeric):g}"
                f" • Average: {sum(numeric)/len(numeric):g}"
            )
        self.stats_label.setText(text)

    def export_filtered(self):
        if not self.headers:
            return
        output, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "", "CSV Files (*.csv);;TSV Files (*.tsv)"
        )
        if not output:
            return
        delimiter = "\t" if output.lower().endswith(".tsv") else ","
        try:
            with open(output, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f, delimiter=delimiter)
                writer.writerow(self.headers)
                writer.writerows(self.filtered_rows)
            QMessageBox.information(
                self, "Export complete",
                f"Exported {len(self.filtered_rows):,} rows.\n\n{output}"
            )
            self.status.setText("Export complete")
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

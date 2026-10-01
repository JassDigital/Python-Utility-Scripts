import csv
import json
import os
import sqlite3
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QLineEdit, QComboBox, QProgressBar, QMessageBox, QSplitter,
    QListWidget, QListWidgetItem, QAbstractItemView, QInputDialog,
    QTabWidget
)

APP_NAME = "JASS SQLite Explorer"
VERSION = "1.0"


def quote_identifier(name):
    return '"' + str(name).replace('"', '""') + '"'


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, fn, *args):
        super().__init__()
        self.fn = fn
        self.args = args
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.signals.result.emit(self.fn(*self.args))
        except Exception as e:
            self.signals.error.emit(f"{type(e).__name__}: {e}")
        finally:
            self.signals.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1450, 850)
        self.db_path = None
        self.conn = None
        self.tables = []
        self.current_table = None
        self.current_columns = []
        self.current_rows = []
        self.threadpool = QThreadPool.globalInstance()
        self.build_ui()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        header = QHBoxLayout()
        title = QLabel("JASS SQLite Explorer")
        title.setObjectName("Title")
        subtitle = QLabel("Inspect • query • export SQLite databases")
        subtitle.setObjectName("Muted")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch()

        open_btn = QPushButton("Open Database")
        open_btn.clicked.connect(self.open_database)
        header.addWidget(open_btn)

        new_btn = QPushButton("New Database")
        new_btn.clicked.connect(self.new_database)
        header.addWidget(new_btn)

        layout.addLayout(header)

        self.db_label = QLabel("No database opened")
        self.db_label.setObjectName("Muted")
        layout.addWidget(self.db_label)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(QLabel("Tables"))
        self.table_search = QLineEdit()
        self.table_search.setPlaceholderText("Filter tables...")
        self.table_search.textChanged.connect(self.filter_tables)
        left_layout.addWidget(self.table_search)

        self.table_list = QListWidget()
        self.table_list.itemClicked.connect(self.select_table)
        left_layout.addWidget(self.table_list, 1)

        refresh_btn = QPushButton("Refresh Schema")
        refresh_btn.clicked.connect(self.refresh_schema)
        left_layout.addWidget(refresh_btn)

        splitter.addWidget(left)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)

        bar = QHBoxLayout()
        self.row_search = QLineEdit()
        self.row_search.setPlaceholderText("Search loaded rows...")
        self.row_search.textChanged.connect(self.filter_rows)
        bar.addWidget(self.row_search, 1)

        self.limit_box = QComboBox()
        self.limit_box.addItems(["100", "500", "1000", "5000", "10000"])
        self.limit_box.setCurrentText("1000")
        bar.addWidget(self.limit_box)

        load_btn = QPushButton("Load Table")
        load_btn.clicked.connect(self.load_current_table)
        bar.addWidget(load_btn)

        export_btn = QPushButton("Export CSV")
        export_btn.clicked.connect(self.export_csv)
        bar.addWidget(export_btn)

        center_layout.addLayout(bar)

        self.tabs = QTabWidget()
        data_tab = QWidget()
        data_layout = QVBoxLayout(data_tab)
        data_layout.setContentsMargins(0, 0, 0, 0)

        self.data_table = QTableWidget()
        self.data_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.data_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setSortingEnabled(True)
        data_layout.addWidget(self.data_table)
        self.tabs.addTab(data_tab, "Data")

        sql_tab = QWidget()
        sql_layout = QVBoxLayout(sql_tab)
        self.sql_edit = QLineEdit()
        self.sql_edit.setPlaceholderText(
            "Example: SELECT * FROM my_table LIMIT 100"
        )
        sql_layout.addWidget(self.sql_edit)

        sql_buttons = QHBoxLayout()
        run_sql = QPushButton("Run SELECT")
        run_sql.clicked.connect(self.run_sql)
        sql_buttons.addWidget(run_sql)

        schema_btn = QPushButton("Show Schema SQL")
        schema_btn.clicked.connect(self.show_schema_sql)
        sql_buttons.addWidget(schema_btn)
        sql_buttons.addStretch()
        sql_layout.addLayout(sql_buttons)

        self.sql_result = QTableWidget()
        self.sql_result.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sql_result.setAlternatingRowColors(True)
        sql_layout.addWidget(self.sql_result, 1)
        self.tabs.addTab(sql_tab, "SQL Query")

        center_layout.addWidget(self.tabs, 1)
        splitter.addWidget(center)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_layout.addWidget(QLabel("Database Information"))
        self.info = QLabel("Open a database to inspect it.")
        self.info.setWordWrap(True)
        right_layout.addWidget(self.info)

        right_layout.addWidget(QLabel("Selected Table Schema"))
        self.schema = QTableWidget()
        self.schema.setColumnCount(5)
        self.schema.setHorizontalHeaderLabels(
            ["Column", "Type", "Not Null", "Default", "PK"]
        )
        self.schema.setEditTriggers(QAbstractItemView.NoEditTriggers)
        right_layout.addWidget(self.schema, 1)

        copy_schema = QPushButton("Copy Schema")
        copy_schema.clicked.connect(self.copy_schema)
        right_layout.addWidget(copy_schema)

        splitter.addWidget(right)
        splitter.setSizes([260, 850, 360])
        layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.status = QLabel("Ready")
        self.status.setObjectName("Muted")
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        footer.addWidget(self.status)
        footer.addStretch()
        footer.addWidget(self.progress)
        layout.addLayout(footer)

        self.setStyleSheet("""
            QWidget {
                background:#151922;
                color:#e8edf5;
                font-size:10.5pt;
            }
            QLabel#Title {
                font-size:20pt;
                font-weight:700;
            }
            QLabel#Muted {
                color:#8e9aaa;
            }
            QPushButton,QComboBox,QLineEdit {
                background:#222938;
                border:1px solid #3a4354;
                border-radius:6px;
                padding:7px 10px;
            }
            QPushButton:hover {
                background:#2b3445;
            }
            QLineEdit {
                background:#10141c;
            }
            QListWidget,QTableWidget {
                background:#10141c;
                alternate-background-color:#171d28;
                border:1px solid #303746;
                gridline-color:#2b3342;
            }
            QListWidget::item:selected,QTableWidget::item:selected {
                background:#294766;
            }
            QHeaderView::section {
                background:#222938;
                color:#dce5f2;
                border:0;
                border-right:1px solid #303746;
                border-bottom:1px solid #303746;
                padding:7px;
            }
            QTabWidget::pane {
                border:1px solid #303746;
            }
            QTabBar::tab {
                background:#222938;
                padding:8px 14px;
                margin-right:2px;
            }
            QTabBar::tab:selected {
                background:#2b3445;
            }
            QProgressBar {
                border:1px solid #303746;
                border-radius:5px;
                text-align:center;
                background:#10141c;
                min-width:180px;
            }
            QProgressBar::chunk {
                background:#4d8dcc;
                border-radius:4px;
            }
        """)

    def open_database(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open SQLite Database",
            "",
            "SQLite Databases (*.db *.sqlite *.sqlite3);;All Files (*.*)"
        )
        if path:
            self.load_database(path)

    def new_database(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Create SQLite Database",
            "",
            "SQLite Databases (*.db)"
        )
        if not path:
            return
        try:
            conn = sqlite3.connect(path)
            conn.close()
            self.load_database(path)
        except Exception as e:
            QMessageBox.critical(self, "Create database", str(e))

    def load_database(self, path):
        if self.conn:
            self.conn.close()

        try:
            self.conn = sqlite3.connect(path)
            self.conn.row_factory = sqlite3.Row
            self.db_path = str(Path(path).resolve())
            self.db_label.setText(self.db_path)
            self.refresh_schema()
            self.status.setText("Database opened")
        except Exception as e:
            self.conn = None
            QMessageBox.critical(self, "Open database", str(e))

    def refresh_schema(self):
        if not self.conn:
            return
        try:
            rows = self.conn.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name COLLATE NOCASE
            """).fetchall()
            self.tables = [r[0] for r in rows]
            self.populate_table_list()

            size = os.path.getsize(self.db_path) if self.db_path else 0
            self.info.setText(
                f"<b>File:</b> {Path(self.db_path).name}<br>"
                f"<b>Size:</b> {self.human_size(size)}<br>"
                f"<b>Tables:</b> {len(self.tables)}<br>"
                f"<b>Path:</b> {self.db_path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Schema", str(e))

    def populate_table_list(self):
        term = self.table_search.text().lower()
        self.table_list.clear()
        for name in self.tables:
            if term in name.lower():
                item = QListWidgetItem(name)
                self.table_list.addItem(item)

    def filter_tables(self):
        self.populate_table_list()

    def select_table(self, item):
        self.current_table = item.text()
        self.load_schema(self.current_table)
        self.load_current_table()

    def load_schema(self, table):
        self.schema.setRowCount(0)
        try:
            rows = self.conn.execute(
                f"PRAGMA table_info({quote_identifier(table)})"
            ).fetchall()
            self.schema.setRowCount(len(rows))
            self.current_columns = [r["name"] for r in rows]
            for i, r in enumerate(rows):
                values = [
                    r["name"], r["type"], "YES" if r["notnull"] else "NO",
                    "" if r["dflt_value"] is None else str(r["dflt_value"]),
                    "YES" if r["pk"] else ""
                ]
                for j, value in enumerate(values):
                    self.schema.setItem(i, j, QTableWidgetItem(value))
            self.schema.resizeColumnsToContents()
        except Exception as e:
            QMessageBox.warning(self, "Schema", str(e))

    def load_current_table(self):
        if not self.conn or not self.current_table:
            return
        try:
            limit = int(self.limit_box.currentText())
            rows = self.conn.execute(
                f"SELECT * FROM {quote_identifier(self.current_table)} LIMIT ?",
                (limit,)
            ).fetchall()
            self.current_rows = [dict(r) for r in rows]
            self.display_rows(self.current_rows, self.data_table)
            self.status.setText(
                f"Loaded {len(self.current_rows):,} row(s) from {self.current_table}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Load table", str(e))

    def display_rows(self, rows, widget):
        widget.setSortingEnabled(False)
        widget.clear()
        if not rows:
            widget.setRowCount(0)
            widget.setColumnCount(0)
            return

        columns = list(rows[0].keys())
        widget.setColumnCount(len(columns))
        widget.setHorizontalHeaderLabels(columns)
        widget.setRowCount(len(rows))

        for i, row in enumerate(rows):
            for j, col in enumerate(columns):
                value = row.get(col)
                if value is None:
                    text = "NULL"
                elif isinstance(value, bytes):
                    text = f"<BLOB {len(value)} bytes>"
                else:
                    text = str(value)
                widget.setItem(i, j, QTableWidgetItem(text))

        widget.resizeColumnsToContents()
        for c in range(widget.columnCount()):
            if widget.columnWidth(c) > 360:
                widget.setColumnWidth(c, 360)
        widget.setSortingEnabled(True)

    def filter_rows(self):
        term = self.row_search.text().lower()
        if not term:
            self.display_rows(self.current_rows, self.data_table)
            return

        rows = []
        for row in self.current_rows:
            if term in " ".join(
                "" if v is None else str(v) for v in row.values()
            ).lower():
                rows.append(row)
        self.display_rows(rows, self.data_table)

    def run_sql(self):
        if not self.conn:
            QMessageBox.warning(self, "SQL", "Open a database first.")
            return

        sql = self.sql_edit.text().strip()
        if not sql:
            return

        if not sql.lower().lstrip().startswith("select"):
            QMessageBox.warning(
                self,
                "Read-only SQL",
                "v1.0 only permits SELECT queries."
            )
            return

        try:
            cur = self.conn.execute(sql)
            rows = cur.fetchall()
            self.display_rows([dict(r) for r in rows], self.sql_result)
            self.tabs.setCurrentIndex(1)
            self.status.setText(f"Query returned {len(rows):,} row(s)")
        except Exception as e:
            QMessageBox.critical(self, "SQL query", str(e))

    def show_schema_sql(self):
        if not self.conn or not self.current_table:
            return
        try:
            row = self.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (self.current_table,)
            ).fetchone()
            sql = row[0] if row and row[0] else ""
            self.sql_edit.setText(sql)
            QApplication.clipboard().setText(sql)
            self.status.setText("Schema SQL copied to clipboard")
        except Exception as e:
            QMessageBox.warning(self, "Schema SQL", str(e))

    def copy_schema(self):
        if not self.current_table:
            return
        lines = [f"Schema: {self.current_table}"]
        for r in range(self.schema.rowCount()):
            vals = [
                self.schema.item(r, c).text()
                if self.schema.item(r, c) else ""
                for c in range(self.schema.columnCount())
            ]
            lines.append(" | ".join(vals))
        QApplication.clipboard().setText("\n".join(lines))
        self.status.setText("Schema copied to clipboard")

    def export_csv(self):
        if not self.current_rows:
            QMessageBox.information(self, "Export CSV", "Load a table first.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "", "CSV Files (*.csv)"
        )
        if not path:
            return

        try:
            fields = list(self.current_rows[0].keys())
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(self.current_rows)
            QMessageBox.information(self, "Export CSV", "CSV exported successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Export CSV", str(e))

    @staticmethod
    def human_size(n):
        n = float(n)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} PB"

    def closeEvent(self, event):
        if self.conn:
            self.conn.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

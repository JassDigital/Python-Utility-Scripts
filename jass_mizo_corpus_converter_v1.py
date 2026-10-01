import sys
import sqlite3
import time
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QProgressBar,
    QMessageBox, QGroupBox, QFormLayout, QStatusBar, QToolBar
)

APP = "JASS Mizo Corpus Converter"
DEFAULT_INPUT = "mizo_language_corpus_4m.txt"
DEFAULT_OUTPUT = "JASS_Mizo_Corpus_4M.db"


class ImportWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(int, int, float, str)
    failed = Signal(str)

    def __init__(self, source, destination):
        super().__init__()
        self.source = Path(source)
        self.destination = Path(destination)
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

    @staticmethod
    def clean(line):
        return " ".join(line.replace("\ufeff", "").split()).strip()

    def run(self):
        start = time.time()
        temp = Path(str(self.destination) + ".part")
        con = None

        try:
            if not self.source.exists():
                raise FileNotFoundError(self.source)

            if temp.exists():
                temp.unlink()

            total_bytes = self.source.stat().st_size
            con = sqlite3.connect(str(temp))
            con.execute("PRAGMA journal_mode=DELETE")
            con.execute("PRAGMA synchronous=NORMAL")
            con.execute("PRAGMA temp_store=MEMORY")
            con.execute("PRAGMA cache_size=-65536")

            con.executescript("""
                CREATE TABLE corpus_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE sentences (
                    line_no INTEGER PRIMARY KEY,
                    text TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE sentences_fts USING fts5(
                    text,
                    content='sentences',
                    content_rowid='line_no',
                    tokenize='unicode61 remove_diacritics 0'
                );
            """)

            con.execute(
                "INSERT INTO corpus_metadata(key,value) VALUES (?,?)",
                ("source_file", self.source.name)
            )
            con.execute(
                "INSERT INTO corpus_metadata(key,value) VALUES (?,?)",
                ("source_size_bytes", str(total_bytes))
            )
            con.execute(
                "INSERT INTO corpus_metadata(key,value) VALUES (?,?)",
                ("created_utc", datetime.utcnow().isoformat(timespec="seconds") + "Z")
            )

            batch = []
            line_no = 0
            imported = 0
            last_pct = -1

            with self.source.open(
                "r", encoding="utf-8", errors="replace", newline=""
            ) as f:
                for raw in f:
                    if self.stop_requested:
                        raise InterruptedError("Import cancelled by user.")

                    line_no += 1
                    text = self.clean(raw)
                    if not text:
                        continue

                    batch.append((line_no, text))

                    if len(batch) >= 10000:
                        con.executemany(
                            "INSERT INTO sentences(line_no,text) VALUES (?,?)",
                            batch
                        )
                        imported += len(batch)
                        batch.clear()

                    try:
                        position = f.tell()
                        pct = int((position / total_bytes) * 100) if total_bytes else 0
                    except Exception:
                        pct = last_pct

                    if pct != last_pct:
                        last_pct = pct
                        self.progress.emit(
                            pct,
                            f"Reading corpus… {imported:,} non-empty lines"
                        )

            if batch:
                con.executemany(
                    "INSERT INTO sentences(line_no,text) VALUES (?,?)",
                    batch
                )
                imported += len(batch)
                batch.clear()

            con.commit()

            self.progress.emit(
                100,
                f"Imported {imported:,} sentences. Building FTS5 search index…"
            )

            con.execute("""
                INSERT INTO sentences_fts(rowid, text)
                SELECT line_no, text FROM sentences
            """)
            con.execute(
                "INSERT INTO corpus_metadata(key,value) VALUES (?,?)",
                ("total_source_lines", str(line_no))
            )
            con.execute(
                "INSERT INTO corpus_metadata(key,value) VALUES (?,?)",
                ("total_nonempty_sentences", str(imported))
            )
            con.commit()

            # Compact and optimize the finished database.
            con.execute("PRAGMA optimize")
            con.commit()
            con.close()
            con = None

            if self.destination.exists():
                self.destination.unlink()
            temp.replace(self.destination)

            elapsed = time.time() - start
            self.finished_ok.emit(
                line_no, imported, elapsed, str(self.destination)
            )

        except InterruptedError:
            if con:
                con.close()
            if temp.exists():
                temp.unlink()
            self.failed.emit("Import cancelled.")
        except Exception as e:
            if con:
                con.close()
            if temp.exists():
                temp.unlink()
            self.failed.emit(f"{type(e).__name__}: {e}")


class Converter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.resize(900, 560)
        self.setMinimumSize(760, 480)

        self.worker = None
        self.build_ui()
        self.apply_style()

        # Convenient defaults.
        for candidate in (
            Path.cwd() / DEFAULT_INPUT,
            Path.home() / "Downloads" / DEFAULT_INPUT,
        ):
            if candidate.exists():
                self.input_edit.setText(str(candidate))
                self.output_edit.setText(
                    str(candidate.with_name(DEFAULT_OUTPUT))
                )
                break

    def build_ui(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_action = QAction("📂 Select Corpus", self)
        open_action.triggered.connect(self.select_input)
        toolbar.addAction(open_action)

        output_action = QAction("💾 Select Database", self)
        output_action.triggered.connect(self.select_output)
        toolbar.addAction(output_action)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 25, 28, 25)
        root.setSpacing(16)

        title = QLabel("JASS Mizo Corpus Converter")
        title.setObjectName("title")
        root.addWidget(title)

        subtitle = QLabel(
            "Convert the 396 MB Mizo text corpus into a standalone SQLite + "
            "FTS5 database for fast offline searching."
        )
        subtitle.setObjectName("subtitle")
        root.addWidget(subtitle)

        box = QGroupBox("Corpus → SQLite Database")
        form = QFormLayout(box)
        form.setSpacing(14)

        in_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(
            "Select mizo_language_corpus_4m.txt"
        )
        in_row.addWidget(self.input_edit, 1)
        b = QPushButton("Browse…")
        b.clicked.connect(self.select_input)
        in_row.addWidget(b)
        form.addRow("Source TXT:", in_row)

        out_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText(
            "JASS_Mizo_Corpus_4M.db"
        )
        out_row.addWidget(self.output_edit, 1)
        b = QPushButton("Browse…")
        b.clicked.connect(self.select_output)
        out_row.addWidget(b)
        form.addRow("Output DB:", out_row)

        root.addWidget(box)

        info = QGroupBox("What will be created")
        il = QVBoxLayout(info)
        for text in (
            "• sentences table — preserves every non-empty source line",
            "• sentences_fts — Unicode-aware FTS5 search index",
            "• corpus_metadata — source and import statistics",
            "• Existing TXT file is never modified",
            "• No PyTorch, Transformers or GPU required",
        ):
            il.addWidget(QLabel(text))
        root.addWidget(info)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("status")
        root.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        buttons.addWidget(self.cancel_btn)

        self.convert_btn = QPushButton("🚀 Convert to Database")
        self.convert_btn.clicked.connect(self.start)
        buttons.addWidget(self.convert_btn)

        root.addLayout(buttons)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

    def select_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Mizo Corpus TXT",
            str(Path.home()),
            "Text files (*.txt);;All files (*.*)"
        )
        if path:
            self.input_edit.setText(path)
            p = Path(path)
            self.output_edit.setText(str(p.with_name(DEFAULT_OUTPUT)))

    def select_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Select Output Database",
            str(Path.home() / DEFAULT_OUTPUT),
            "SQLite Database (*.db);;All files (*.*)"
        )
        if path:
            if not path.lower().endswith(".db"):
                path += ".db"
            self.output_edit.setText(path)

    def start(self):
        source = Path(self.input_edit.text().strip())
        destination = Path(self.output_edit.text().strip())

        if not source.exists():
            QMessageBox.warning(
                self, "Source Not Found",
                "Please select the downloaded mizo_language_corpus_4m.txt file."
            )
            return

        if not destination.parent.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)

        if destination.exists():
            reply = QMessageBox.question(
                self, "Database Already Exists",
                f"{destination.name} already exists.\n\n"
                "Replace it with a fresh conversion?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        self.progress.setValue(0)
        self.status_label.setText("Starting conversion…")
        self.convert_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        self.worker = ImportWorker(source, destination)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.completed)
        self.worker.failed.connect(self.failed)
        self.worker.start()

    def on_progress(self, value, message):
        self.progress.setValue(value)
        self.status_label.setText(message)
        self.statusBar().showMessage(message)

    def completed(self, source_lines, imported, seconds, destination):
        self.worker = None
        self.convert_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setValue(100)

        size_mb = Path(destination).stat().st_size / (1024 * 1024)

        self.status_label.setText(
            f"Complete — {imported:,} non-empty sentences indexed."
        )
        self.statusBar().showMessage(
            f"Created {Path(destination).name} ({size_mb:,.1f} MB)"
        )

        QMessageBox.information(
            self,
            "Conversion Complete",
            f"Database created successfully.\n\n"
            f"Source lines: {source_lines:,}\n"
            f"Non-empty sentences: {imported:,}\n"
            f"Database size: {size_mb:,.1f} MB\n"
            f"Time: {seconds:,.1f} seconds\n\n"
            f"{destination}"
        )

    def failed(self, message):
        self.worker = None
        self.convert_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status_label.setText(message)

        if message == "Import cancelled.":
            self.statusBar().showMessage(message)
            return

        QMessageBox.critical(self, "Conversion Error", message)

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.status_label.setText("Cancelling…")
            self.cancel_btn.setEnabled(False)
            self.worker.stop()

    def apply_style(self):
        self.setStyleSheet("""
            QWidget {
                background: #f5f7fa;
                color: #20252b;
                font-size: 14px;
            }
            QGroupBox {
                background: white;
                border: 1px solid #d7dee7;
                border-radius: 12px;
                margin-top: 12px;
                padding: 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 6px;
                font-weight: 600;
            }
            QLineEdit {
                background: white;
                border: 1px solid #cfd7e1;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton {
                background: white;
                border: 1px solid #cfd7e1;
                border-radius: 8px;
                padding: 10px 16px;
            }
            QPushButton:hover {
                background: #edf2f7;
            }
            QPushButton:disabled {
                color: #9aa4af;
            }
            QToolBar {
                background: white;
                border: 0;
                padding: 7px;
                spacing: 6px;
            }
            QProgressBar {
                background: white;
                border: 1px solid #d1d9e2;
                border-radius: 7px;
                height: 20px;
                text-align: center;
            }
            #title {
                font-size: 30px;
                font-weight: 700;
                color: #17202a;
            }
            #subtitle {
                color: #647281;
                font-size: 15px;
            }
            #status {
                color: #536170;
                padding: 5px;
            }
            QStatusBar {
                background: white;
            }
        """)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(5000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setStyle("Fusion")
    win = Converter()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

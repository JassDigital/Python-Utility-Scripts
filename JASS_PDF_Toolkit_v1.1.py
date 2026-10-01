import sys
import os
import subprocess
from pathlib import Path

try:
    import pymupdf  # PyMuPDF
except ImportError:
    pymupdf = None

from PySide6.QtCore import Qt, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QListWidget, QListWidgetItem,
    QMessageBox, QLineEdit, QSpinBox, QGroupBox, QFormLayout,
    QPlainTextEdit, QProgressBar, QSplitter, QCheckBox
)


APP_NAME = "JASS PDF Toolkit"
VERSION = "1.1"


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def open_path(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        QMessageBox.warning(None, "Open", str(e))


class WorkerSignals(QObject):
    progress = Signal(int)
    status = Signal(str)
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, action, args):
        super().__init__()
        self.action = action
        self.args = args
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            if pymupdf is None:
                raise RuntimeError("PyMuPDF is not installed.\n\nInstall it with:\npy -m pip install PyMuPDF")
            result = self.action(self.args, self)
            self.signals.result.emit(result)
        except Exception as e:
            self.signals.error.emit(f"{type(e).__name__}: {e}")
        finally:
            self.signals.finished.emit()


def action_merge(args, worker):
    files, output = args
    out = pymupdf.open()
    try:
        for i, path in enumerate(files):
            worker.signals.status.emit(f"Adding {Path(path).name}")
            src = pymupdf.open(path)
            try:
                out.insert_pdf(src)
            finally:
                src.close()
            worker.signals.progress.emit(int((i + 1) * 100 / len(files)))
        out.save(output)
    finally:
        out.close()
    return output


def action_extract(args, worker):
    source, output, pages = args
    src = pymupdf.open(source)
    out = pymupdf.open()
    try:
        total = len(pages)
        for i, p in enumerate(pages):
            if p < 0 or p >= len(src):
                raise ValueError(f"Page {p + 1} is outside the PDF.")
            out.insert_pdf(src, from_page=p, to_page=p)
            worker.signals.progress.emit(int((i + 1) * 100 / total))
        out.save(output)
    finally:
        out.close()
        src.close()
    return output


def action_rotate(args, worker):
    source, output, pages, angle = args
    doc = pymupdf.open(source)
    try:
        for i, p in enumerate(pages):
            if p < 0 or p >= len(doc):
                raise ValueError(f"Page {p + 1} is outside the PDF.")
            page = doc[p]
            page.set_rotation((page.rotation + angle) % 360)
            worker.signals.progress.emit(int((i + 1) * 100 / len(pages)))
        doc.save(output)
    finally:
        doc.close()
    return output


def action_remove(args, worker):
    source, output, pages = args
    doc = pymupdf.open(source)
    try:
        remove_set = set(pages)
        for p in sorted(remove_set, reverse=True):
            if p < 0 or p >= len(doc):
                raise ValueError(f"Page {p + 1} is outside the PDF.")
            doc.delete_page(p)
            worker.signals.progress.emit(int((len(remove_set) - len([x for x in pages if x >= p])) * 100 / max(1, len(remove_set))))
        if len(doc) == 0:
            raise ValueError("The operation would create an empty PDF.")
        doc.save(output)
    finally:
        doc.close()
    return output


def action_reorder(args, worker):
    source, output, order = args
    doc = pymupdf.open(source)
    try:
        if sorted(order) != list(range(len(doc))):
            raise ValueError("Page order must contain every page exactly once.")
        doc.select(order)
        doc.save(output)
    finally:
        doc.close()
    return output


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1200, 760)
        self.current_pdf = None
        self._active_worker = None
        self.build_ui()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        header = QHBoxLayout()
        title = QLabel("JASS PDF Toolkit")
        title.setObjectName("Title")
        version = QLabel("v1.0  •  PDF utility workspace")
        version.setObjectName("Muted")
        header.addWidget(title)
        header.addWidget(version)
        header.addStretch()
        layout.addLayout(header)

        top = QHBoxLayout()
        self.open_btn = QPushButton("Open PDF")
        self.open_btn.clicked.connect(self.open_pdf)
        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.clicked.connect(self.open_folder)
        top.addWidget(self.open_btn)
        top.addWidget(self.open_folder_btn)
        top.addStretch()
        layout.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        left = QWidget()
        ll = QVBoxLayout(left)

        self.file_label = QLabel("No PDF selected")
        self.file_label.setObjectName("PathLabel")
        self.info = QLabel("Open a PDF to inspect it.")
        self.info.setWordWrap(True)
        ll.addWidget(self.file_label)
        ll.addWidget(self.info)

        pages_box = QGroupBox("Pages")
        pl = QVBoxLayout(pages_box)
        self.pages = QListWidget()
        self.pages.setSelectionMode(QListWidget.ExtendedSelection)
        self.pages.itemSelectionChanged.connect(self.show_selected_page)
        pl.addWidget(self.pages)

        btnrow = QHBoxLayout()
        select_all = QPushButton("Select All")
        select_all.clicked.connect(self.pages.selectAll)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.pages.clearSelection)
        btnrow.addWidget(select_all)
        btnrow.addWidget(clear)
        pl.addLayout(btnrow)
        ll.addWidget(pages_box, 1)

        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)

        ops = QGroupBox("Operations")
        ol = QVBoxLayout(ops)

        row = QHBoxLayout()
        self.merge_btn = QPushButton("Merge PDFs")
        self.merge_btn.clicked.connect(self.merge_pdfs)
        self.extract_btn = QPushButton("Extract Selected")
        self.extract_btn.clicked.connect(self.extract_selected)
        row.addWidget(self.merge_btn)
        row.addWidget(self.extract_btn)
        ol.addLayout(row)

        row = QHBoxLayout()
        self.rotate_left = QPushButton("Rotate Left")
        self.rotate_left.clicked.connect(lambda: self.rotate_selected(-90))
        self.rotate_right = QPushButton("Rotate Right")
        self.rotate_right.clicked.connect(lambda: self.rotate_selected(90))
        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.clicked.connect(self.remove_selected)
        row.addWidget(self.rotate_left)
        row.addWidget(self.rotate_right)
        row.addWidget(self.remove_btn)
        ol.addLayout(row)

        row = QHBoxLayout()
        self.reorder_edit = QLineEdit()
        self.reorder_edit.setPlaceholderText("New page order, e.g. 3,1,2,4")
        self.reorder_btn = QPushButton("Reorder")
        self.reorder_btn.clicked.connect(self.reorder_pages)
        row.addWidget(self.reorder_edit, 1)
        row.addWidget(self.reorder_btn)
        ol.addLayout(row)

        rl.addWidget(ops)

        search_box = QGroupBox("Text Search")
        sl = QHBoxLayout(search_box)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search text in this PDF...")
        self.search_btn = QPushButton("Find")
        self.search_btn.clicked.connect(self.search_text)
        sl.addWidget(self.search_edit, 1)
        sl.addWidget(self.search_btn)
        rl.addWidget(search_box)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("PDF metadata and selected-page information will appear here.")
        rl.addWidget(self.detail, 1)

        splitter.addWidget(right)
        splitter.setSizes([470, 730])

        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status = QLabel("Ready")
        self.status.setObjectName("Muted")
        bottom.addWidget(self.progress, 1)
        bottom.addWidget(self.status)
        layout.addLayout(bottom)

        self.setStyleSheet("""
            QWidget {
                background: #151922;
                color: #e8edf5;
                font-size: 10.5pt;
            }
            QMainWindow, QGroupBox {
                background: #151922;
            }
            QLabel#Title {
                font-size: 20pt;
                font-weight: 700;
            }
            QLabel#Muted {
                color: #8e9aaa;
            }
            QLabel#PathLabel {
                color: #79b8ff;
                font-weight: 600;
            }
            QGroupBox {
                border: 1px solid #303746;
                border-radius: 8px;
                margin-top: 10px;
                padding: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #aeb9ca;
            }
            QPushButton {
                background: #222938;
                border: 1px solid #3a4354;
                border-radius: 6px;
                padding: 8px 12px;
            }
            QPushButton:hover {
                background: #2b3445;
            }
            QPushButton:pressed {
                background: #18202d;
            }
            QLineEdit, QPlainTextEdit, QListWidget {
                background: #10141c;
                border: 1px solid #303746;
                border-radius: 6px;
                padding: 6px;
            }
            QListWidget::item:selected {
                background: #294766;
            }
            QProgressBar {
                border: 1px solid #303746;
                border-radius: 5px;
                text-align: center;
                background: #10141c;
            }
            QProgressBar::chunk {
                background: #4d8dcc;
                border-radius: 4px;
            }
        """)

    def require_pdf(self):
        if not self.current_pdf:
            QMessageBox.information(self, "PDF", "Open a PDF first.")
            return False
        return True

    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", "", "PDF Files (*.pdf)"
        )
        if path:
            self.load_pdf(path)

    def load_pdf(self, path):
        if pymupdf is None:
            QMessageBox.critical(
                self, "Missing dependency",
                "PyMuPDF is required.\n\nInstall with:\npy -m pip install PyMuPDF"
            )
            return
        try:
            doc = pymupdf.open(path)
            self.current_pdf = path
            self.file_label.setText(path)
            self.pages.clear()
            for i in range(len(doc)):
                page = doc[i]
                text = page.get_text("text").strip().replace("\n", " ")
                preview = text[:90] if text else "(no text)"
                item = QListWidgetItem(f"Page {i + 1}   •   {preview}")
                item.setData(Qt.UserRole, i)
                self.pages.addItem(item)
            meta = doc.metadata
            self.info.setText(
                f"{len(doc)} pages  •  {human_size(os.path.getsize(path))}  •  "
                f"{Path(path).suffix.lower()}"
            )
            self.detail.setPlainText(
                f"File: {path}\n"
                f"Pages: {len(doc)}\n"
                f"Title: {meta.get('title', '')}\n"
                f"Author: {meta.get('author', '')}\n"
                f"Subject: {meta.get('subject', '')}\n"
                f"Creator: {meta.get('creator', '')}\n"
                f"Producer: {meta.get('producer', '')}\n"
                f"Creation date: {meta.get('creationDate', '')}\n"
                f"Modification date: {meta.get('modDate', '')}"
            )
            doc.close()
            self.status.setText("PDF loaded")
        except Exception as e:
            QMessageBox.critical(self, "Open PDF", str(e))

    def open_folder(self):
        if self.current_pdf:
            open_path(Path(self.current_pdf).parent)
        else:
            folder = QFileDialog.getExistingDirectory(self, "Open Folder")
            if folder:
                open_path(folder)

    def selected_pages(self):
        return sorted({item.data(Qt.UserRole) for item in self.pages.selectedItems()})

    def show_selected_page(self):
        pages = self.selected_pages()
        if not pages or not self.current_pdf:
            return
        try:
            doc = pymupdf.open(self.current_pdf)
            p = pages[0]
            page = doc[p]
            text = page.get_text("text")
            self.detail.setPlainText(
                f"Selected page: {p + 1}\n"
                f"Size: {page.rect.width:.1f} × {page.rect.height:.1f} pt\n"
                f"Rotation: {page.rotation}°\n\n"
                f"{text[:12000]}"
            )
            doc.close()
        except Exception as e:
            self.status.setText(str(e))

    def output_path(self, suffix):
        base = Path(self.current_pdf)
        default = base.with_name(base.stem + suffix + ".pdf")
        return QFileDialog.getSaveFileName(
            self, "Save PDF", str(default), "PDF Files (*.pdf)"
        )[0]

    def start_worker(self, action, args, success_text):
        self.set_busy(True)
        self.progress.setValue(0)
        self.status.setText("Working...")
        worker = Worker(action, args)
        self._active_worker = worker
        worker.signals.progress.connect(self.progress.setValue)
        worker.signals.status.connect(self.status.setText)
        worker.signals.result.connect(lambda p: self.operation_done(p, success_text))
        worker.signals.error.connect(self.operation_error)
        worker.signals.finished.connect(self.worker_finished)
        QThreadPool.globalInstance().start(worker)

    def worker_finished(self):
        self.set_busy(False)
        self._active_worker = None

    def operation_done(self, path, message):
        self.progress.setValue(100)
        self.status.setText(message)
        QMessageBox.information(self, "JASS PDF Toolkit", f"{message}\n\n{path}")

    def operation_error(self, message):
        self.status.setText("Operation failed")
        QMessageBox.critical(self, "PDF operation failed", message)

    def set_busy(self, busy):
        for w in (
            self.open_btn, self.open_folder_btn, self.merge_btn,
            self.extract_btn, self.rotate_left, self.rotate_right,
            self.remove_btn, self.reorder_btn, self.search_btn
        ):
            w.setEnabled(not busy)

    def merge_pdfs(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select PDFs to Merge", "", "PDF Files (*.pdf)"
        )
        if len(files) < 2:
            return
        output, _ = QFileDialog.getSaveFileName(
            self, "Save Merged PDF",
            str(Path(files[0]).with_name(Path(files[0]).stem + "_merged.pdf")),
            "PDF Files (*.pdf)"
        )
        if output:
            self.start_worker(action_merge, (files, output), "PDFs merged successfully.")

    def extract_selected(self):
        if not self.require_pdf():
            return
        pages = self.selected_pages()
        if not pages:
            QMessageBox.information(self, "Extract", "Select one or more pages.")
            return
        output = self.output_path("_extracted")
        if output:
            self.start_worker(
                action_extract, (self.current_pdf, output, pages),
                "Selected pages extracted successfully."
            )

    def rotate_selected(self, angle):
        if not self.require_pdf():
            return
        pages = self.selected_pages()
        if not pages:
            QMessageBox.information(self, "Rotate", "Select one or more pages.")
            return
        direction = "left" if angle < 0 else "right"
        output = self.output_path(f"_rotated_{direction}")
        if output:
            self.start_worker(
                action_rotate, (self.current_pdf, output, pages, angle),
                f"Pages rotated {direction} successfully."
            )

    def remove_selected(self):
        if not self.require_pdf():
            return
        pages = self.selected_pages()
        if not pages:
            QMessageBox.information(self, "Remove", "Select one or more pages.")
            return
        answer = QMessageBox.question(
            self, "Confirm Remove",
            f"Remove {len(pages)} selected page(s) and save a new PDF?",
            QMessageBox.Yes | QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return
        output = self.output_path("_without_selected")
        if output:
            self.start_worker(
                action_remove, (self.current_pdf, output, pages),
                "Selected pages removed successfully."
            )

    def reorder_pages(self):
        if not self.require_pdf():
            return
        text = self.reorder_edit.text().strip()
        if not text:
            QMessageBox.information(self, "Reorder", "Enter a page order, e.g. 3,1,2,4.")
            return
        try:
            order = [int(x.strip()) - 1 for x in text.split(",") if x.strip()]
            if any(x < 0 for x in order):
                raise ValueError
            output = self.output_path("_reordered")
            if output:
                self.start_worker(
                    action_reorder, (self.current_pdf, output, order),
                    "Pages reordered successfully."
                )
        except ValueError:
            QMessageBox.warning(self, "Reorder", "Use page numbers such as 3,1,2,4.")

    def search_text(self):
        if not self.require_pdf():
            return
        term = self.search_edit.text().strip()
        if not term:
            return
        try:
            doc = pymupdf.open(self.current_pdf)
            hits = []
            for i, page in enumerate(doc):
                if term.lower() in page.get_text("text").lower():
                    hits.append(i + 1)
            doc.close()
            if hits:
                self.detail.setPlainText(
                    f"Search: {term}\nFound on pages: {', '.join(map(str, hits))}"
                )
                self.status.setText(f"Found on {len(hits)} page(s)")
            else:
                self.detail.setPlainText(f"Search: {term}\nNo matches found.")
                self.status.setText("No matches")
        except Exception as e:
            QMessageBox.critical(self, "Search", str(e))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

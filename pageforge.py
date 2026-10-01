#!/usr/bin/env python3
"""PageForge - beautiful PySide6 Image Folder to PDF GUI."""

import re
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout, QWidget
)

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def natural_key(p: Path):
    return [int(x) if x.isdigit() else x.lower()
            for x in re.split(r"(\d+)", p.name)]


def find_images(folder: Path):
    return sorted(
        [p for p in folder.iterdir()
         if p.is_file() and p.suffix.lower() in SUPPORTED],
        key=natural_key
    )


class Worker(QThread):
    progress = Signal(int, str)
    success = Signal(str, int)
    error = Signal(str)

    def __init__(self, paths, output):
        super().__init__()
        self.paths, self.output = paths, output

    def run(self):
        images = []
        try:
            total = len(self.paths)
            for i, path in enumerate(self.paths, 1):
                self.progress.emit(
                    int((i - 1) * 92 / total),
                    f"Preparing page {i} of {total}  •  {path.name}"
                )
                with Image.open(path) as src:
                    src.seek(0)
                    if src.mode in ("RGBA", "LA"):
                        rgba = src.convert("RGBA")
                        img = Image.new("RGB", rgba.size, "white")
                        img.paste(rgba, mask=rgba.getchannel("A"))
                    else:
                        img = src.convert("RGB")
                    images.append(img)

            self.progress.emit(96, "Writing PDF…")
            images[0].save(
                self.output, "PDF", resolution=100.0,
                save_all=True, append_images=images[1:]
            )
            for img in images:
                img.close()
            self.progress.emit(100, "Complete")
            self.success.emit(self.output, total)
        except Exception as exc:
            for img in images:
                try:
                    img.close()
                except Exception:
                    pass
            self.error.emit(str(exc))


class StatCard(QFrame):
    def __init__(self, title, value="0"):
        super().__init__()
        self.setObjectName("StatCard")
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 13, 18, 13)
        self.value = QLabel(value)
        self.value.setObjectName("StatValue")
        label = QLabel(title.upper())
        label.setObjectName("StatTitle")
        box.addWidget(self.value)
        box.addWidget(label)

    def setValue(self, value):
        self.value.setText(str(value))


class PageForge(QMainWindow):
    def __init__(self):
        super().__init__()
        self.images = []
        self.worker = None
        self.setWindowTitle("PageForge — Image Folder to PDF")
        self.resize(1080, 760)
        self.setMinimumSize(900, 650)
        self.build_ui()
        self.setStyleSheet("""
        QWidget#Root { background:#f4f7fb; color:#172033; }
        QLabel#AppIcon { background:#315efb; color:white; border-radius:14px;
            font-size:27px; font-weight:800; }
        QLabel#Title { font-size:28px; font-weight:800; color:#172033; }
        QLabel#Subtitle { font-size:13px; color:#697386; }
        QLabel#Badge { background:#e8f7ef; color:#147a45; border-radius:10px;
            padding:8px 12px; font-size:10px; font-weight:800; }
        QFrame#Card, QFrame#StatCard { background:white;
            border:1px solid #e3e8f0; border-radius:16px; }
        QLabel#SectionLabel { color:#7a8496; font-size:10px;
            font-weight:800; letter-spacing:1px; }
        QLabel#Hint, QLabel#Status { color:#697386; font-size:12px; }
        QLabel#StatValue { color:#172033; font-size:22px; font-weight:800; }
        QLabel#StatTitle { color:#8992a3; font-size:9px;
            font-weight:800; letter-spacing:1px; }
        QLineEdit { background:#f8fafc; border:1px solid #dbe1ea;
            border-radius:10px; padding:11px 13px; font-size:13px; }
        QLineEdit:focus { border:1px solid #315efb; background:white; }
        QPushButton { border:none; border-radius:10px; padding:10px 16px;
            font-size:12px; font-weight:700; }
        QPushButton#Secondary { background:#eef2f7; color:#334057; }
        QPushButton#Secondary:hover { background:#e3e9f2; }
        QPushButton#Primary { background:#315efb; color:white; }
        QPushButton#Primary:hover { background:#254bd1; }
        QPushButton#Primary:disabled { background:#aeb8ce; }
        QPushButton#Refresh { background:#eef2f7; color:#334057;
            font-size:19px; padding:6px; min-width:42px; }
        QListWidget#Pages { background:#f8fafc; border:1px solid #e6ebf2;
            border-radius:11px; padding:7px; outline:none; }
        QListWidget#Pages::item { background:white; border:1px solid #edf0f5;
            border-radius:8px; padding:9px; margin:1px; color:#344054; }
        QProgressBar { background:#e5eaf2; border:none; border-radius:5px; height:8px; }
        QProgressBar::chunk { background:#315efb; border-radius:5px; }
        """)

    def build_ui(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(28, 24, 28, 22)
        main.setSpacing(16)

        head = QHBoxLayout()
        icon = QLabel("▣")
        icon.setObjectName("AppIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(52, 52)
        head.addWidget(icon)

        texts = QVBoxLayout()
        title = QLabel("PageForge")
        title.setObjectName("Title")
        sub = QLabel("Turn a folder of images into a clean, perfectly ordered PDF")
        sub.setObjectName("Subtitle")
        texts.addWidget(title)
        texts.addWidget(sub)
        head.addLayout(texts)
        head.addStretch()

        badge = QLabel("NO CROP  •  NO DISTORTION")
        badge.setObjectName("Badge")
        head.addWidget(badge)
        main.addLayout(head)

        card = QFrame()
        card.setObjectName("Card")
        box = QVBoxLayout(card)
        box.setContentsMargins(20, 16, 20, 16)
        label = QLabel("SOURCE FOLDER")
        label.setObjectName("SectionLabel")
        box.addWidget(label)

        row = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("Choose the folder containing your pages…")
        self.folder.returnPressed.connect(self.refresh)
        row.addWidget(self.folder, 1)
        b = QPushButton("Browse")
        b.setObjectName("Secondary")
        b.clicked.connect(self.choose_folder)
        row.addWidget(b)
        r = QPushButton("↻")
        r.setObjectName("Refresh")
        r.setToolTip("Refresh")
        r.clicked.connect(self.refresh)
        row.addWidget(r)
        box.addLayout(row)
        main.addWidget(card)

        stats = QHBoxLayout()
        self.pages = StatCard("Pages found")
        self.formats = StatCard("Image formats", "—")
        self.order = StatCard("Order", "Natural")
        stats.addWidget(self.pages)
        stats.addWidget(self.formats)
        stats.addWidget(self.order)
        main.addLayout(stats)

        card2 = QFrame()
        card2.setObjectName("Card")
        box2 = QVBoxLayout(card2)
        box2.setContentsMargins(20, 16, 20, 16)
        h = QHBoxLayout()
        lab = QLabel("PAGES")
        lab.setObjectName("SectionLabel")
        h.addWidget(lab)
        h.addStretch()
        self.hint = QLabel("Select a source folder")
        self.hint.setObjectName("Hint")
        h.addWidget(self.hint)
        box2.addLayout(h)

        self.list = QListWidget()
        self.list.setObjectName("Pages")
        self.list.setUniformItemSizes(True)
        box2.addWidget(self.list, 1)
        main.addWidget(card2, 1)

        out = QFrame()
        out.setObjectName("Card")
        ob = QVBoxLayout(out)
        ob.setContentsMargins(20, 14, 20, 14)
        ol = QLabel("OUTPUT PDF")
        ol.setObjectName("SectionLabel")
        ob.addWidget(ol)
        rr = QHBoxLayout()
        self.output = QLineEdit()
        self.output.setPlaceholderText("Where should the PDF be saved?")
        rr.addWidget(self.output, 1)
        choose = QPushButton("Choose")
        choose.setObjectName("Secondary")
        choose.clicked.connect(self.choose_output)
        rr.addWidget(choose)
        ob.addLayout(rr)
        main.addWidget(out)

        footer = QHBoxLayout()
        self.status = QLabel("Ready — choose a source folder.")
        self.status.setObjectName("Status")
        footer.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(210)
        self.progress.setTextVisible(False)
        footer.addWidget(self.progress)
        self.create = QPushButton("Create PDF  →")
        self.create.setObjectName("Primary")
        self.create.setMinimumSize(170, 46)
        self.create.clicked.connect(self.create_pdf)
        footer.addWidget(self.create)
        main.addLayout(footer)

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if path:
            self.folder.setText(path)
            p = Path(path)
            if not self.output.text().strip():
                self.output.setText(str(p / f"{p.name}.pdf"))
            self.refresh()

    def choose_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF", self.output.text() or "combined.pdf",
            "PDF Files (*.pdf)"
        )
        if path:
            self.output.setText(path if path.lower().endswith(".pdf") else path + ".pdf")

    def refresh(self):
        self.list.clear()
        self.images = []
        p = Path(self.folder.text().strip())
        if not p.is_dir():
            self.pages.setValue("0")
            self.formats.setValue("—")
            self.hint.setText("Select a source folder")
            return

        self.images = find_images(p)
        for i, path in enumerate(self.images, 1):
            try:
                with Image.open(path) as im:
                    size = f"{im.width} × {im.height} px"
                    ratio = f"{im.width / im.height:.2f}:1"
            except Exception:
                size, ratio = "Unreadable", "—"
            self.list.addItem(
                QListWidgetItem(f"  {i:03d}    {path.name}    •    {size}    •    {ratio}")
            )

        self.pages.setValue(len(self.images))
        self.formats.setValue(", ".join(sorted({x.suffix[1:].lower() for x in self.images})) or "—")
        self.hint.setText(f"{len(self.images)} page(s)  •  original dimensions preserved")
        self.status.setText(
            f"Ready — {len(self.images)} image(s) found."
            if self.images else "No supported images found."
        )

    def create_pdf(self):
        self.refresh()
        if not self.images:
            QMessageBox.warning(self, "No images", "No supported images were found.")
            return

        output = self.output.text().strip()
        if not output:
            QMessageBox.warning(self, "Output required", "Choose an output PDF file.")
            return

        out = Path(output)
        if out.suffix.lower() != ".pdf":
            out = out.with_suffix(".pdf")
        out.parent.mkdir(parents=True, exist_ok=True)

        if out.exists():
            if QMessageBox.question(
                self, "Replace existing PDF?",
                f"{out}\n\nReplace this file?"
            ) != QMessageBox.StandardButton.Yes:
                return

        self.create.setEnabled(False)
        self.folder.setEnabled(False)
        self.progress.setValue(0)
        self.worker = Worker(self.images, str(out))
        self.worker.progress.connect(
            lambda v, s: (self.progress.setValue(v), self.status.setText(s))
        )
        self.worker.success.connect(self.done)
        self.worker.error.connect(self.failed)
        self.worker.start()

    def done(self, path, count):
        self.create.setEnabled(True)
        self.folder.setEnabled(True)
        self.worker = None
        self.status.setText(f"Finished — {count} pages written to PDF.")
        QMessageBox.information(
            self, "PDF created",
            f"PDF created successfully.\n\nPages: {count}\n\n{path}"
        )

    def failed(self, message):
        self.create.setEnabled(True)
        self.folder.setEnabled(True)
        self.worker = None
        self.status.setText("PDF creation failed.")
        QMessageBox.critical(self, "PDF creation failed", message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("PageForge")
    window = PageForge()
    window.show()
    sys.exit(app.exec())

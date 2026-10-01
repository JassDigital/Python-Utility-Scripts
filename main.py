
import sys, time, re
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QDoubleSpinBox, QLineEdit, QFileDialog, QMessageBox, QGroupBox,
    QFormLayout, QCheckBox
)

try:
    import mss
    import pyautogui
    import pygetwindow as gw
except ImportError as e:
    raise SystemExit(f"Missing package: {e}")


def natural_key(s):
    return [int(x) if x.isdigit() else x.lower()
            for x in re.split(r"(\d+)", s)]


class CaptureWorker(QThread):
    status = Signal(str)
    preview = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, left, top, width, height, pages, delay, outdir,
                 click_x, click_y, page_down_count, test_mode):
        super().__init__()
        self.left, self.top = left, top
        self.width, self.height = width, height
        self.pages = pages
        self.delay = delay
        self.outdir = Path(outdir)
        self.click_x, self.click_y = click_x, click_y
        self.page_down_count = page_down_count
        self.test_mode = test_mode

    def find_edge(self):
        wins = []
        try:
            wins = gw.getWindowsWithTitle("Microsoft Edge")
        except Exception:
            pass
        if not wins:
            try:
                wins = [w for w in gw.getAllWindows()
                        if "edge" in (w.title or "").lower()]
            except Exception:
                wins = []
        visible = [w for w in wins if w.width > 500 and w.height > 400]
        return visible[0] if visible else None

    def run(self):
        try:
            self.outdir.mkdir(parents=True, exist_ok=True)
            edge = self.find_edge()
            if not edge:
                raise RuntimeError(
                    "Microsoft Edge window was not found. Keep the Jamabandi tab open."
                )

            self.status.emit("Bringing the existing Edge window to the front…")
            try:
                if edge.isMinimized:
                    edge.restore()
                edge.activate()
            except Exception:
                pass
            time.sleep(1)

            # Test mode captures only the requested number of pages.
            count = min(self.pages, 3) if self.test_mode else self.pages

            with mss.mss() as sct:
                for i in range(count):
                    # Keep Edge visible; the capture app is not activated during capture.
                    time.sleep(self.delay)
                    mon = {
                        "left": self.left, "top": self.top,
                        "width": self.width, "height": self.height
                    }
                    img = sct.grab(mon)
                    path = self.outdir / f"page-{i+1:03d}.png"
                    mss.tools.to_png(img.rgb, img.size, output=str(path))
                    self.preview.emit(str(path))
                    self.status.emit(f"Captured page {i+1} of {count}")

                    if i + 1 < count:
                        # Click inside Edge so PageDown definitely goes to the Jamabandi.
                        pyautogui.click(self.click_x, self.click_y)
                        time.sleep(0.25)
                        for _ in range(max(1, self.page_down_count)):
                            pyautogui.press("pagedown")
                            time.sleep(0.35)

            self.finished_ok.emit(str(self.outdir))
        except Exception as e:
            self.failed.emit(str(e))


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JASS Jamabandi Native Edge Capture v3.0.0")
        self.resize(760, 650)
        self.worker = None

        root = QVBoxLayout(self)

        intro = QLabel(
            "<b>Capture the already-open Jamabandi in Microsoft Edge</b><br>"
            "No Print, PDF, download, remote debugging, or website debugging. "
            "The program captures exactly what Edge displays."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        g = QGroupBox("Capture rectangle (screen pixels)")
        form = QFormLayout(g)
        self.left = QSpinBox(); self.left.setRange(0, 10000); self.left.setValue(23)
        self.top = QSpinBox(); self.top.setRange(0, 10000); self.top.setValue(0)
        self.width = QSpinBox(); self.width.setRange(100, 10000); self.width.setValue(1078)
        self.height = QSpinBox(); self.height.setRange(100, 10000); self.height.setValue(735)
        form.addRow("Left:", self.left)
        form.addRow("Top:", self.top)
        form.addRow("Width:", self.width)
        form.addRow("Height:", self.height)
        root.addWidget(g)

        g2 = QGroupBox("Page advance")
        f2 = QFormLayout(g2)
        self.pages = QSpinBox(); self.pages.setRange(1, 500); self.pages.setValue(86)
        self.delay = QDoubleSpinBox(); self.delay.setRange(0.5, 10); self.delay.setSingleStep(0.25); self.delay.setValue(1.5)
        self.click_x = QSpinBox(); self.click_x.setRange(0, 10000); self.click_x.setValue(600)
        self.click_y = QSpinBox(); self.click_y.setRange(0, 10000); self.click_y.setValue(300)
        self.pd = QSpinBox(); self.pd.setRange(1, 5); self.pd.setValue(1)
        f2.addRow("Pages:", self.pages)
        f2.addRow("Wait after advance (sec):", self.delay)
        f2.addRow("Edge click X:", self.click_x)
        f2.addRow("Edge click Y:", self.click_y)
        f2.addRow("PageDown presses:", self.pd)
        root.addWidget(g2)

        outrow = QHBoxLayout()
        self.out = QLineEdit(str(Path.home() / "Pictures" / "Jamabandi-Captures"))
        b = QPushButton("Browse…")
        b.clicked.connect(self.choose_out)
        outrow.addWidget(self.out); outrow.addWidget(b)
        root.addWidget(QLabel("Output folder:"))
        root.addLayout(outrow)

        self.test = QCheckBox("Test mode — capture only first 3 pages")
        self.test.setChecked(True)
        root.addWidget(self.test)

        btns = QHBoxLayout()
        self.start = QPushButton("Start Capture")
        self.start.clicked.connect(self.start_capture)
        self.open_edge = QPushButton("Activate Edge")
        self.open_edge.clicked.connect(self.activate_edge)
        btns.addWidget(self.start); btns.addWidget(self.open_edge)
        root.addLayout(btns)

        self.status = QLabel("Keep the readable 86-page Jamabandi open in Edge.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(260)
        root.addWidget(self.preview, 1)

    def choose_out(self):
        d = QFileDialog.getExistingDirectory(self, "Select output folder")
        if d:
            self.out.setText(d)

    def activate_edge(self):
        try:
            wins = gw.getWindowsWithTitle("Microsoft Edge")
            if not wins:
                raise RuntimeError("Microsoft Edge window not found.")
            w = [x for x in wins if x.width > 500 and x.height > 400][0]
            if w.isMinimized:
                w.restore()
            w.activate()
            self.status.setText("Edge activated. Do not refresh or close the Jamabandi.")
        except Exception as e:
            QMessageBox.warning(self, "Edge", str(e))

    def start_capture(self):
        self.start.setEnabled(False)
        self.test.setEnabled(False)
        self.status.setText(
            "Starting… Edge must remain visible. Do not touch the mouse/keyboard."
        )
        self.worker = CaptureWorker(
            self.left.value(), self.top.value(),
            self.width.value(), self.height.value(),
            self.pages.value(), self.delay.value(),
            self.out.text(),
            self.click_x.value(), self.click_y.value(),
            self.pd.value(), self.test.isChecked()
        )
        self.worker.status.connect(self.status.setText)
        self.worker.preview.connect(self.show_preview)
        self.worker.finished_ok.connect(self.done)
        self.worker.failed.connect(self.error)
        self.worker.start()

    def show_preview(self, path):
        pix = QPixmap(path)
        if not pix.isNull():
            self.preview.setPixmap(
                pix.scaled(self.preview.size(), Qt.KeepAspectRatio,
                           Qt.SmoothTransformation)
            )

    def done(self, folder):
        self.start.setEnabled(True)
        self.test.setEnabled(True)
        self.status.setText(f"Finished. PNG pages saved in: {folder}")
        QMessageBox.information(self, "Capture complete",
                                 f"Captured pages are in:\n{folder}")

    def error(self, msg):
        self.start.setEnabled(True)
        self.test.setEnabled(True)
        QMessageBox.critical(self, "Capture error", msg)
        self.status.setText(msg)


def main():
    app = QApplication(sys.argv)
    w = App()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

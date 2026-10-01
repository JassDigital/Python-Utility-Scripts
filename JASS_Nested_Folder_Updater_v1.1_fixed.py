
import os
import sys
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QPushButton, QLabel, QLineEdit,
    QCheckBox, QMessageBox, QProgressBar, QPlainTextEdit, QHeaderView,
    QAbstractItemView, QFileDialog, QSplitter
)

ROOT = Path(r"F:\\")


def candidate(parent):
    try:
        items = list(parent.iterdir())
        return items[0] if len(items) == 1 and items[0].is_dir() else None
    except OSError:
        return None


def scan(root):
    out = []
    for base, dirs, files in os.walk(root, topdown=False, followlinks=False):
        p = Path(base)
        c = candidate(p)
        if c:
            out.append((p, c))
    return out


def unique_target(p):
    if not p.exists():
        return p
    if p.is_dir():
        stem, suffix = p.name, ""
    else:
        stem, suffix = p.stem, p.suffix

    n = 1
    while True:
        q = p.parent / f"{stem} ({n}){suffix}"
        if not q.exists():
            return q
        n += 1


def flatten(parent, child):
    problems, moved = [], 0

    try:
        contents = list(child.iterdir())
    except Exception as e:
        return 0, [str(e)]

    for item in contents:
        target = unique_target(parent / item.name)
        try:
            shutil.move(str(item), str(target))
            moved += 1
        except Exception as e:
            problems.append(f"{item.name}: {e}")

    try:
        if not any(child.iterdir()):
            child.rmdir()
    except Exception as e:
        problems.append(f"Could not remove {child}: {e}")

    return moved, problems


class Worker(QThread):
    done = Signal(object)

    def __init__(self, root):
        super().__init__()
        self.root = root

    def run(self):
        self.done.emit(scan(self.root))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JASS NESTED FOLDER UPDATER v1.1")
        self.resize(1350, 820)

        self.candidates = []
        self.worker = None

        self.build_ui()
        self.apply_style()

    def build_ui(self):
        w = QWidget()
        self.setCentralWidget(w)
        layout = QVBoxLayout(w)

        header = QHBoxLayout()

        title = QLabel("JASS NESTED FOLDER  •  FOLDER FLATTENER")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()

        self.path = QLineEdit(str(ROOT))
        self.path.setMinimumWidth(360)
        header.addWidget(self.path)

        browse = QPushButton("BROWSE")
        browse.clicked.connect(self.browse)
        header.addWidget(browse)

        layout.addLayout(header)

        info = QLabel(
            "Automatic candidates: a folder containing exactly one nested folder. "
            "You can ALSO select any individual folder and move its contents upward."
        )
        info.setObjectName("info")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Create the tree BEFORE connecting buttons that reference it.
        splitter = QSplitter(Qt.Vertical)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels([
            "PARENT FOLDER",
            "NESTED / SELECTED FOLDER",
            "DEPTH",
            "TYPE",
            "STATUS"
        ])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(4, QHeaderView.ResizeToContents)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)

        splitter.addWidget(self.tree)
        splitter.addWidget(self.log)
        splitter.setSizes([550, 180])

        controls = QHBoxLayout()

        scan_btn = QPushButton("SCAN")
        scan_btn.clicked.connect(self.scan_now)
        controls.addWidget(scan_btn)

        select_btn = QPushButton("SELECT ALL")
        select_btn.clicked.connect(self.tree.selectAll)
        controls.addWidget(select_btn)

        clear_btn = QPushButton("CLEAR")
        clear_btn.clicked.connect(self.tree.clearSelection)
        controls.addWidget(clear_btn)

        add_btn = QPushButton("ADD FOLDER")
        add_btn.clicked.connect(self.add_individual_folder)
        controls.addWidget(add_btn)

        self.dry = QCheckBox("DRY RUN")
        self.dry.setChecked(True)
        controls.addWidget(self.dry)

        controls.addStretch()

        move_btn = QPushButton("MOVE SELECTED UP")
        move_btn.setObjectName("move")
        move_btn.clicked.connect(self.execute)
        controls.addWidget(move_btn)

        layout.addLayout(controls)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        layout.addWidget(splitter, 1)

        self.statusBar().showMessage(
            "Ready — scan a root folder or add an individual folder."
        )

    def apply_style(self):
        self.setStyleSheet("""
        QWidget {
            background: #090e14;
            color: #d9e6ed;
            font-family: "Segoe UI";
        }
        QMainWindow {
            background: #070b10;
        }
        #title {
            color: #39e6ff;
            font-size: 22px;
            font-weight: 700;
        }
        #info {
            background: #0e1821;
            border: 1px solid #244656;
            border-radius: 7px;
            padding: 9px;
            color: #9bc0ce;
        }
        QPushButton {
            background: #111d27;
            border: 1px solid #2b596b;
            border-radius: 5px;
            padding: 8px 13px;
        }
        QPushButton:hover {
            background: #173342;
            border-color: #39e6ff;
        }
        QPushButton#move {
            color: #39e6ff;
            font-weight: 700;
        }
        QLineEdit, QPlainTextEdit, QTreeWidget {
            background: #0c141b;
            border: 1px solid #214554;
            border-radius: 5px;
        }
        QTreeWidget::item:selected {
            background: #155066;
            color: white;
        }
        QHeaderView::section {
            background: #101d27;
            color: #6de5f6;
            padding: 7px;
            border: 0;
        }
        QProgressBar {
            border: 1px solid #285467;
            height: 8px;
        }
        QProgressBar::chunk {
            background: #39e6ff;
        }
        """)

    def browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select root folder", self.path.text()
        )
        if folder:
            self.path.setText(folder)

    def scan_now(self):
        root = Path(self.path.text().strip())

        if not root.is_dir():
            QMessageBox.warning(
                self,
                "Invalid folder",
                f"Folder does not exist:\n{root}"
            )
            return

        self.tree.clear()
        self.log.clear()
        self.candidates = []

        self.progress.setVisible(True)
        self.statusBar().showMessage("Scanning...")

        self.worker = Worker(root)
        self.worker.done.connect(self.scanned)
        self.worker.start()

    def scanned(self, items):
        self.progress.setVisible(False)
        self.candidates = items

        for n, (parent, child) in enumerate(items):
            row = QTreeWidgetItem([
                str(parent),
                child.name,
                str(len(parent.parts)),
                "AUTO CANDIDATE",
                "READY"
            ])
            row.setData(0, Qt.UserRole, n)
            row.setData(0, Qt.UserRole + 1, "candidate")
            self.tree.addTopLevelItem(row)

        self.log.appendPlainText(
            f"Scan complete: {len(items):,} automatic candidate(s) found."
        )

        self.statusBar().showMessage(
            f"{len(items):,} automatic candidate(s) found."
        )

    def add_individual_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select individual folder to move upward",
            self.path.text()
        )

        if not folder:
            return

        child = Path(folder)
        root = Path(self.path.text().strip())

        if child == root:
            QMessageBox.warning(
                self,
                "Invalid selection",
                "Select a folder inside the root, not the root itself."
            )
            return

        parent = child.parent

        for p, c in self.candidates:
            if c == child:
                QMessageBox.information(
                    self,
                    "Already listed",
                    "This folder is already present in the list."
                )
                return

        self.candidates.append((parent, child))
        idx = len(self.candidates) - 1

        row = QTreeWidgetItem([
            str(parent),
            child.name,
            str(len(parent.parts)),
            "INDIVIDUAL",
            "READY"
        ])

        row.setData(0, Qt.UserRole, idx)
        row.setData(0, Qt.UserRole + 1, "individual")

        self.tree.addTopLevelItem(row)
        row.setSelected(True)

        self.log.appendPlainText(
            f"ADDED INDIVIDUAL FOLDER: {child}\n"
            f"  Destination parent: {parent}"
        )

        self.statusBar().showMessage(
            f"Individual folder added: {child.name}"
        )

    def execute(self):
        selected = []

        for row in self.tree.selectedItems():
            idx = row.data(0, Qt.UserRole)

            if idx is not None and 0 <= idx < len(self.candidates):
                selected.append((idx, self.candidates[idx], row))

        if not selected:
            QMessageBox.information(
                self,
                "Nothing selected",
                "Select folders from the list, or use ADD FOLDER."
            )
            return

        if not self.dry.isChecked():
            answer = QMessageBox.question(
                self,
                "Confirm Move",
                f"Move the contents of {len(selected)} selected folder(s) "
                "into their parent folder(s)?\n\n"
                "Existing names will NOT be overwritten. "
                "Collisions receive (1), (2), etc.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if answer != QMessageBox.Yes:
                return

        selected.sort(
            key=lambda x: len(x[1][1].parts),
            reverse=True
        )

        for idx, (parent, child), row in selected:

            if not child.exists():
                row.setText(4, "MISSING")
                continue

            try:
                contents = list(child.iterdir())
            except Exception as e:
                row.setText(4, "ERROR")
                self.log.appendPlainText(
                    f"ERROR: {child}: {e}"
                )
                continue

            if self.dry.isChecked():
                row.setText(4, "DRY RUN")

                self.log.appendPlainText(
                    f"WOULD MOVE: {child} → {parent} "
                    f"({len(contents)} item(s))"
                )

                for item in contents:
                    self.log.appendPlainText(
                        f"  {item.name}"
                    )

                continue

            moved, problems = flatten(parent, child)

            row.setText(
                4,
                "DONE" if not problems else "PARTIAL"
            )

            self.log.appendPlainText(
                f"MOVED: {child} → {parent} "
                f"({moved} item(s))"
            )

            for problem in problems:
                self.log.appendPlainText(
                    "  " + problem
                )

        if not self.dry.isChecked():
            self.scan_now()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("JASS Nested Folder Updater")

    window = Window()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

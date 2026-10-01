
import os, sys, shutil
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QCheckBox, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QAbstractItemView, QProgressBar, QPlainTextEdit,
    QMessageBox, QFileDialog, QSplitter, QSpinBox
)

ROOT = Path(r"F:\\")

def unique_name(target: Path):
    """Return a collision-safe path. Never silently overwrite an existing item."""
    if not target.exists():
        return target
    if target.is_dir():
        stem, suffix = target.name, ""
    else:
        stem, suffix = target.stem, target.suffix
    n = 1
    while True:
        candidate = target.parent / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
        n += 1

def scan_subfolders(root: Path):
    """Return all folders below root, deepest first."""
    folders = []
    for base, dirs, files in os.walk(root, topdown=False, followlinks=False):
        folders.append(Path(base))
    return folders

def consolidate(root: Path, include_root: bool, remove_empty: bool, rename_collisions: bool, log):
    """
    Move contents of subfolders upward, one level at a time.
    A folder's files/subfolders are moved into its parent.
    Empty folders are removed.
    """
    folders = scan_subfolders(root)
    if not include_root:
        folders = [f for f in folders if f != root]

    moved = 0
    renamed = 0
    removed = 0
    errors = []

    # Deepest first is important so nested contents reach their eventual parent.
    for folder in folders:
        if folder == root:
            continue
        parent = folder.parent
        if not parent.exists():
            continue

        try:
            items = list(folder.iterdir())
        except Exception as e:
            errors.append(f"Cannot read {folder}: {e}")
            continue

        for item in items:
            target = parent / item.name
            original_target = target

            if target.exists():
                if rename_collisions:
                    target = unique_name(target)
                    renamed += 1
                    log(f"RENAME: {item.name} -> {target.name}")
                else:
                    errors.append(f"COLLISION: {target}")
                    continue

            try:
                shutil.move(str(item), str(target))
                moved += 1
                log(f"MOVE: {item} -> {target}")
            except Exception as e:
                errors.append(f"FAILED: {item} -> {e}")

        if remove_empty:
            try:
                if not any(folder.iterdir()):
                    folder.rmdir()
                    removed += 1
                    log(f"REMOVE EMPTY FOLDER: {folder}")
            except Exception as e:
                errors.append(f"Could not remove {folder}: {e}")

    return moved, renamed, removed, errors

class Worker(QThread):
    log_signal = Signal(str)
    done = Signal(object)

    def __init__(self, root, dry_run, remove_empty, rename_collisions):
        super().__init__()
        self.root = root
        self.dry_run = dry_run
        self.remove_empty = remove_empty
        self.rename_collisions = rename_collisions

    def log(self, text):
        self.log_signal.emit(text)

    def run(self):
        folders = scan_subfolders(self.root)
        candidates = [f for f in folders if f != self.root]

        if self.dry_run:
            self.log(f"DRY RUN — {len(candidates):,} subfolder(s) examined")
            planned = 0
            for folder in candidates:
                parent = folder.parent
                try:
                    items = list(folder.iterdir())
                except Exception as e:
                    self.log(f"ERROR: {folder}: {e}")
                    continue
                for item in items:
                    target = parent / item.name
                    if target.exists() and self.rename_collisions:
                        target = unique_name(target)
                        self.log(f"WOULD RENAME: {item.name} -> {target.name}")
                    elif target.exists():
                        self.log(f"WOULD SKIP COLLISION: {item}")
                    else:
                        self.log(f"WOULD MOVE: {item} -> {target}")
                    planned += 1
                if self.remove_empty and not items:
                    self.log(f"WOULD REMOVE EMPTY: {folder}")
            self.done.emit({
                "moved": 0, "renamed": 0, "removed": 0,
                "errors": [], "planned": planned, "dry_run": True
            })
            return

        self.log(f"LIVE MODE — consolidating {len(candidates):,} subfolder(s)")
        result = consolidate(
            self.root, False, self.remove_empty,
            self.rename_collisions, self.log
        )
        moved, renamed, removed, errors = result
        self.done.emit({
            "moved": moved, "renamed": renamed, "removed": removed,
            "errors": errors, "planned": 0, "dry_run": False
        })

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JASS SUBFOLDER CONSOLIDATOR v1.0")
        self.resize(1400, 850)
        self.worker = None
        self.preview_ready = False
        self.build_ui()
        self.apply_style()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        header = QHBoxLayout()
        title = QLabel("JASS SUBFOLDER  •  CONTENT CONSOLIDATOR")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()

        self.path = QLineEdit(str(ROOT))
        self.path.setMinimumWidth(420)
        header.addWidget(self.path)

        browse = QPushButton("BROWSE")
        browse.clicked.connect(self.browse)
        header.addWidget(browse)
        layout.addLayout(header)

        info = QLabel(
            "Moves the contents of subfolders into their immediate parent, "
            "processes deepest folders first, renames collisions safely, "
            "and removes folders only after they are empty."
        )
        info.setObjectName("info")
        info.setWordWrap(True)
        layout.addWidget(info)

        controls = QHBoxLayout()

        self.scan_btn = QPushButton("ANALYZE")
        self.scan_btn.clicked.connect(self.analyze)
        controls.addWidget(self.scan_btn)

        self.dry = QCheckBox("DRY RUN")
        self.dry.setChecked(True)
        controls.addWidget(self.dry)

        self.remove_empty = QCheckBox("REMOVE EMPTY FOLDERS")
        self.remove_empty.setChecked(True)
        controls.addWidget(self.remove_empty)

        self.rename = QCheckBox("RENAME COLLISIONS")
        self.rename.setChecked(True)
        controls.addWidget(self.rename)

        controls.addStretch()

        self.preview_btn = QPushButton("PREVIEW CONSOLIDATION")
        self.preview_btn.setObjectName("preview")
        self.preview_btn.clicked.connect(self.preview_consolidation)
        controls.addWidget(self.preview_btn)

        self.run_btn = QPushButton("CONSOLIDATE NOW")
        self.run_btn.setObjectName("run")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self.consolidate_now)
        controls.addWidget(self.run_btn)

        layout.addLayout(controls)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter, 1)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels([
            "SUBFOLDER", "PARENT", "ITEMS", "STATUS"
        ])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        splitter.addWidget(self.tree)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        splitter.addWidget(self.log)
        splitter.setSizes([540, 220])

        self.statusBar().showMessage("Ready")

    def apply_style(self):
        self.setStyleSheet("""
        QWidget { background:#090e14; color:#d9e6ed; font-family:"Segoe UI"; }
        QMainWindow { background:#070b10; }
        #title { color:#39e6ff; font-size:22px; font-weight:700; }
        #info { background:#0e1821; border:1px solid #244656; border-radius:7px;
                padding:10px; color:#9bc0ce; }
        QPushButton { background:#111d27; border:1px solid #2b596b;
                      border-radius:5px; padding:8px 13px; }
        QPushButton:hover { background:#173342; border-color:#39e6ff; }
        QPushButton#run { color:#39e6ff; font-weight:700; }
        QPushButton#preview { color:#9bdff0; font-weight:700; }
        QPushButton:disabled { color:#536772; border-color:#1a303b; }
        QLineEdit,QPlainTextEdit,QTreeWidget {
            background:#0c141b; border:1px solid #214554; border-radius:5px; }
        QTreeWidget::item:selected { background:#155066; color:white; }
        QHeaderView::section { background:#101d27; color:#6de5f6;
                                padding:7px; border:0; }
        QProgressBar { border:1px solid #285467; height:8px; }
        QProgressBar::chunk { background:#39e6ff; }
        QCheckBox { spacing:7px; }
        """)

    def browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select root folder", self.path.text()
        )
        if folder:
            self.path.setText(folder)

    def analyze(self):
        root = Path(self.path.text().strip())
        if not root.is_dir():
            QMessageBox.warning(self, "Invalid folder", f"Folder does not exist:\n{root}")
            return

        self.tree.clear()
        self.log.clear()
        self.progress.setVisible(True)
        self.statusBar().showMessage("Analyzing subfolders...")

        try:
            folders = [f for f in scan_subfolders(root) if f != root]
            for folder in folders:
                try:
                    items = list(folder.iterdir())
                    count = len(items)
                except Exception:
                    count = -1
                row = QTreeWidgetItem([
                    str(folder), str(folder.parent),
                    "ERROR" if count < 0 else str(count),
                    "READY"
                ])
                row.setData(0, Qt.UserRole, str(folder))
                self.tree.addTopLevelItem(row)

            self.log.appendPlainText(
                f"Analysis complete: {len(folders):,} subfolder(s)."
            )
            self.statusBar().showMessage(
                f"{len(folders):,} subfolder(s) found."
            )
        except Exception as e:
            QMessageBox.critical(self, "Analysis failed", str(e))
        finally:
            self.progress.setVisible(False)

    def preview_consolidation(self):
        """Run a dry-run preview and unlock the final consolidation button."""
        root = Path(self.path.text().strip())
        if not root.is_dir():
            QMessageBox.warning(
                self, "Invalid folder", f"Folder does not exist:\n{root}"
            )
            return

        self.dry.setChecked(True)
        self.preview_ready = False
        self.run_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.log.clear()
        self.log.appendPlainText("=== CONSOLIDATION PREVIEW ===")
        self.log.appendPlainText(
            "Nothing has been changed. Review the planned operations below."
        )

        self.worker = Worker(
            root, True,
            self.remove_empty.isChecked(),
            self.rename.isChecked()
        )
        self.worker.log_signal.connect(self.log.appendPlainText)
        self.worker.done.connect(self.finished)
        self.worker.start()

    def consolidate_now(self):
        """Perform the live operation after the user has reviewed the preview."""
        root = Path(self.path.text().strip())
        if not root.is_dir():
            QMessageBox.warning(
                self, "Invalid folder", f"Folder does not exist:\n{root}"
            )
            return

        answer = QMessageBox.warning(
            self,
            "FINAL CONFIRMATION",
            "The preview has been completed.\n\n"
            "This will now MOVE the contents of subfolders upward, "
            "rename collisions when enabled, and remove empty folders "
            "when enabled.\n\n"
            "This changes the folder structure and cannot be automatically undone.\n\n"
            "Do you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        self.preview_ready = False
        self.run_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.progress.setVisible(True)

        self.log.appendPlainText("\n=== FINAL CONSOLIDATION STARTED ===")

        self.worker = Worker(
            root, False,
            self.remove_empty.isChecked(),
            self.rename.isChecked()
        )
        self.worker.log_signal.connect(self.log.appendPlainText)
        self.worker.done.connect(self.finished)
        self.worker.start()

    def finished(self, result):
        self.progress.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.preview_btn.setEnabled(True)

        if result["dry_run"]:
            text = (
                f"PREVIEW COMPLETE — Planned item operations: "
                f"{result['planned']:,}"
            )

            self.preview_ready = True
            self.run_btn.setEnabled(result["planned"] > 0)

            self.log.appendPlainText("\n" + "=" * 65)
            self.log.appendPlainText(text)
            self.log.appendPlainText(
                "\nReview the log above. "
                "When satisfied, click  CONSOLIDATE NOW."
            )

            self.statusBar().showMessage(
                "Preview complete — CONSOLIDATE NOW is ready."
            )

            if result["planned"] > 0:
                QMessageBox.information(
                    self,
                    "Preview Complete",
                    f"Planned operations: {result['planned']:,}\n\n"
                    "Review the log, then click CONSOLIDATE NOW to perform "
                    "the actual operation."
                )
            else:
                QMessageBox.information(
                    self,
                    "Nothing to Consolidate",
                    "The scan found no item operations to perform."
                )
            return

        self.run_btn.setEnabled(False)
        self.preview_ready = False

        text = (
            f"CONSOLIDATION COMPLETE — "
            f"Moved: {result['moved']:,}   |   "
            f"Renamed: {result['renamed']:,}   |   "
            f"Empty folders removed: {result['removed']:,}   |   "
            f"Errors: {len(result['errors']):,}"
        )

        self.log.appendPlainText("\n" + "=" * 65)
        self.log.appendPlainText(text)

        for e in result["errors"][:100]:
            self.log.appendPlainText("ERROR: " + e)

        self.statusBar().showMessage(text)

        if result["errors"]:
            QMessageBox.warning(
                self,
                "Completed with errors",
                text + "\n\nSee the log for details."
            )
        else:
            QMessageBox.information(
                self,
                "Consolidation Complete",
                text
            )

        # Refresh the analysis after the live operation.
        self.analyze()

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("JASS Subfolder Consolidator")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

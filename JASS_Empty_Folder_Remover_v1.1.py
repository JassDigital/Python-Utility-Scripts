import sys
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QLabel, QLineEdit, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QGroupBox, QMessageBox, QProgressBar, QAbstractItemView
)

APP_NAME = "JASS Empty Folder Remover"
APP_VERSION = "1.1"


def is_effectively_empty(path: Path) -> bool:
    """Return True when a directory contains no files or subdirectories."""
    try:
        return not any(path.iterdir())
    except (OSError, PermissionError):
        return False


class ScanWorker(QThread):
    progress = Signal(int, str)
    finished_scan = Signal(object, int)
    error = Signal(str)

    def __init__(self, root: Path):
        super().__init__()
        self.root = root
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            # Walk bottom-up so nested empty directories are discovered too.
            folders = []
            for current, dirs, files in os.walk(self.root, topdown=False):
                if self._stop:
                    return
                folders.append(Path(current))

            empty = []
            total = len(folders)

            for i, folder in enumerate(folders, 1):
                if self._stop:
                    return

                try:
                    if folder != self.root and not any(folder.iterdir()):
                        empty.append(folder)
                except (OSError, PermissionError):
                    continue

                if total:
                    self.progress.emit(
                        int(i * 100 / total),
                        f"Checking folders: {i:,} / {total:,}"
                    )

            self.finished_scan.emit(empty, total)

        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1150, 720)

        self.empty_folders = []
        self.worker = None

        self.build_ui()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)

        title = QLabel(f"{APP_NAME}  •  v{APP_VERSION}")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        root.addWidget(title)

        subtitle = QLabel(
            "Find empty folders, review them, and safely remove them. "
            "Nested empty folders are handled from the deepest level upward, including newly-empty parents up to 5 levels."
        )
        subtitle.setStyleSheet("color: #666;")
        root.addWidget(subtitle)

        # Scan location
        box = QGroupBox("Scan Location")
        grid = QGridLayout(box)

        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Select a folder...")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_folder)

        self.include_hidden = QCheckBox("Include hidden/system folders")
        self.include_hidden.setChecked(False)

        grid.addWidget(QLabel("Folder:"), 0, 0)
        grid.addWidget(self.folder_edit, 0, 1)
        grid.addWidget(browse, 0, 2)
        grid.addWidget(self.include_hidden, 1, 1)

        root.addWidget(box)

        # Actions
        actions = QHBoxLayout()

        self.scan_btn = QPushButton("🔎 Scan for Empty Folders")
        self.scan_btn.clicked.connect(self.start_scan)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_scan)

        self.select_btn = QPushButton("Select ALL Empty Folders")
        self.select_btn.clicked.connect(self.select_all)

        self.clear_btn = QPushButton("Clear Selection")
        self.clear_btn.clicked.connect(self.clear_selection)

        self.delete_btn = QPushButton("🗑 Delete ALL Selected")
        self.delete_btn.clicked.connect(self.delete_selected)
        self.delete_btn.setToolTip(
            "Delete the selected empty folders. The selected folders are empty."
        )

        actions.addWidget(self.scan_btn)
        actions.addWidget(self.stop_btn)
        actions.addStretch()
        actions.addWidget(self.select_btn)
        actions.addWidget(self.clear_btn)
        actions.addWidget(self.delete_btn)

        root.addLayout(actions)

        options = QHBoxLayout()

        self.recycle_bin = QCheckBox("Send deleted folders to Recycle Bin")
        self.recycle_bin.setChecked(True)

        options.addWidget(self.recycle_bin)
        options.addStretch()
        root.addLayout(options)

        status = QHBoxLayout()

        self.status = QLabel(
            "Ready. Choose a folder and scan for empty folders."
        )

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        status.addWidget(self.status, 2)
        status.addWidget(self.progress, 1)
        root.addLayout(status)

        # Results
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            "Folder", "Parent Location", "Status"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.MultiSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)

        root.addWidget(self.table, 1)

        self.summary = QLabel(
            "No scan performed."
        )
        self.summary.setStyleSheet("font-weight: 600;")
        root.addWidget(self.summary)

        self.setStyleSheet("""
            QMainWindow {
                background: #f7f7f7;
            }
            QGroupBox {
                font-weight: 600;
                border: 1px solid #d0d0d0;
                border-radius: 7px;
                margin-top: 8px;
                padding-top: 8px;
                background: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton {
                padding: 7px 12px;
                border-radius: 5px;
            }
            QTableWidget {
                background: white;
                gridline-color: #dddddd;
            }
        """)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose folder to scan"
        )
        if folder:
            self.folder_edit.setText(folder)

    def start_scan(self):
        folder = self.folder_edit.text().strip()

        if not folder:
            QMessageBox.warning(
                self, "Folder required",
                "Please choose a folder first."
            )
            return

        root = Path(folder)

        if not root.is_dir():
            QMessageBox.warning(
                self, "Invalid folder",
                "The selected folder does not exist."
            )
            return

        self.table.setRowCount(0)
        self.empty_folders = []

        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.select_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText("Starting scan…")

        self.worker = ScanWorker(root)
        self.worker.progress.connect(self.scan_progress)
        self.worker.finished_scan.connect(self.scan_finished)
        self.worker.error.connect(self.scan_error)
        self.worker.finished.connect(self.worker_done)
        self.worker.start()

    def stop_scan(self):
        if self.worker:
            self.worker.stop()
            self.status.setText("Stopping scan…")

    def scan_progress(self, value, text):
        self.progress.setValue(value)
        self.status.setText(text)

    def scan_error(self, message):
        self.status.setText("Some folders could not be checked.")
        QMessageBox.warning(self, "Scan error", message)

    def worker_done(self):
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.select_btn.setEnabled(bool(self.empty_folders))
        self.delete_btn.setEnabled(bool(self.empty_folders))

    def scan_finished(self, empty, total):
        # Deepest folders first is useful for deletion.
        empty.sort(key=lambda p: len(p.parts), reverse=True)
        self.empty_folders = empty

        self.table.setRowCount(0)

        for folder in empty:
            row = self.table.rowCount()
            self.table.insertRow(row)

            self.table.setItem(row, 0, QTableWidgetItem(folder.name))
            self.table.setItem(row, 1, QTableWidgetItem(str(folder.parent)))

            status = QTableWidgetItem("EMPTY")
            status.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table.setItem(row, 2, status)

            # Store the real path on the first cell.
            self.table.item(row, 0).setData(Qt.UserRole, str(folder))

        self.progress.setValue(100)
        self.status.setText("Scan complete.")

        if empty:
            self.summary.setText(
                f"Found {len(empty):,} empty folders "
                f"out of {total:,} folders scanned."
            )
        else:
            self.summary.setText(
                f"Scanned {total:,} folders • No empty folders found."
            )

    def select_all(self):
        if not self.empty_folders:
            return

        self.table.selectAll()
        self.status.setText(
            f"Selected all {len(self.empty_folders):,} empty folders."
        )

    def clear_selection(self):
        self.table.clearSelection()
        self.status.setText("Selection cleared.")

    def delete_selected(self):
        selected_rows = {
            index.row()
            for index in self.table.selectionModel().selectedRows()
        }

        if not selected_rows:
            QMessageBox.information(
                self,
                "Nothing selected",
                "Select the empty folders you want to remove."
            )
            return

        initial_paths = []
        for row in sorted(selected_rows):
            item = self.table.item(row, 0)
            if item:
                initial_paths.append(Path(item.data(Qt.UserRole)))

        if not initial_paths:
            return

        # IMPORTANT:
        # A parent may not have been empty during the initial scan because it
        # contained an empty child. After the child is deleted, the parent can
        # become empty. We therefore continue upward, for at least 5 levels,
        # removing newly-empty parents.
        #
        # We use a set to avoid processing the same directory twice.
        candidates = set(initial_paths)

        # Add up to 5 parent levels for every selected empty folder.
        # The root scan folder is deliberately excluded later.
        scan_root = Path(self.folder_edit.text().strip()).resolve()

        for path in initial_paths:
            current = path.parent
            for _ in range(5):
                try:
                    current_resolved = current.resolve()
                except OSError:
                    current_resolved = current

                if current_resolved == scan_root:
                    break

                candidates.add(current)
                current = current.parent

        # Deepest directories must be deleted first.
        candidates = sorted(
            candidates,
            key=lambda p: len(p.parts),
            reverse=True
        )

        safe_paths = []

        # Only directories that are actually empty at this moment are
        # candidates. This is intentionally checked dynamically.
        for path in candidates:
            try:
                resolved = path.resolve()
                if resolved == scan_root:
                    continue

                if path.is_dir() and not any(path.iterdir()):
                    safe_paths.append(path)
            except (OSError, PermissionError):
                continue

        if not safe_paths:
            QMessageBox.information(
                self,
                "Nothing to delete",
                "None of the selected folders are currently empty."
            )
            return

        mode = (
            "Recycle Bin"
            if self.recycle_bin.isChecked()
            else "permanently"
        )

        reply = QMessageBox.warning(
            self,
            "Confirm deletion",
            f"Up to 5 parent levels will also be cleaned when they become "
            f"empty.\n\n"
            f"Potential empty folders to remove: {len(safe_paths):,}\n"
            f"Mode: {mode}\n\n"
            "The root scan folder will NEVER be deleted.\n"
            "Folders are checked again immediately before removal.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        deleted = 0
        failed = []

        self.delete_btn.setEnabled(False)
        self.select_btn.setEnabled(False)

        for i, path in enumerate(safe_paths, 1):
            try:
                # Re-check immediately before deletion.
                if not path.is_dir() or any(path.iterdir()):
                    continue

                if path.resolve() == scan_root:
                    continue

                if self.recycle_bin.isChecked():
                    self.move_to_recycle_bin(path)
                else:
                    path.rmdir()

                deleted += 1

            except Exception as e:
                failed.append(f"{path}: {e}")

            self.progress.setValue(
                int(i * 100 / len(safe_paths))
            )
            self.status.setText(
                f"Removing empty folders: {i:,} / {len(safe_paths):,}"
            )
            QApplication.processEvents()

        self.delete_btn.setEnabled(True)
        self.select_btn.setEnabled(bool(self.empty_folders))

        message = (
            f"Removed {deleted:,} empty folders, including newly-empty "
            f"parent folders up to 5 levels above the selected folders."
        )

        if failed:
            message += f"\\nCould not remove {len(failed):,} folders."

        QMessageBox.information(
            self,
            "Deletion complete",
            message
        )

        self.start_scan()

    @staticmethod
    def move_to_recycle_bin(path: Path):
        if sys.platform.startswith("win"):
            # Use Windows' native Recycle Bin API through PowerShell.
            escaped = str(path).replace("'", "''")
            ps = (
                "Add-Type -AssemblyName Microsoft.VisualBasic; "
                f"[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory("
                f"'{escaped}', "
                "[Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs, "
                "[Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)"
            )

            subprocess.run(
                [
                    "powershell", "-NoProfile",
                    "-ExecutionPolicy", "Bypass",
                    "-Command", ps
                ],
                check=True,
                creationflags=getattr(
                    subprocess, "CREATE_NO_WINDOW", 0
                )
            )
        else:
            # Linux does not have one universal recycle-bin API.
            # Keep the operation explicit rather than pretending rmdir is
            # a recycle-bin operation.
            path.rmdir()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

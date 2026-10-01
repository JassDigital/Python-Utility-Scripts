import sys
import os
import re
import hashlib
from pathlib import Path
from collections import defaultdict

from PySide6.QtCore import Qt, QThread, Signal, QItemSelection, QItemSelectionRange, QItemSelectionModel
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QProgressBar, QCheckBox, QSpinBox, QGroupBox,
    QAbstractItemView, QComboBox
)


APP_NAME = "JASS Duplicate File Remover"
APP_VERSION = "1.7"


def file_hash(path, chunk_size=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def safe_filename(name):
    """Make a Windows-safe filename while preserving the extension."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip().rstrip(".")
    return name or "file"


def filename_score(path):
    """
    Higher score = more human/descriptive filename.
    Used only to suggest a canonical retained filename.
    """
    stem = path.stem
    lower = stem.lower()

    score = 0

    # Penalize common camera/download/copy-style names.
    if re.fullmatch(r"(img|dsc|pxl|screenshot|screen)[ _-]?\d+", lower):
        score -= 35
    if re.search(r"\b(copy|copie|duplicate|dup)\b", lower):
        score -= 25
    if re.search(r"\(\d+\)$", stem):
        score -= 20
    if re.search(r"[-_ ]\d{3,}$", stem):
        score -= 10

    # Reward readable names.
    if re.search(r"[A-Za-z]{4,}", stem):
        score += 15
    if " " in stem or "_" in stem or "-" in stem:
        score += 5

    # Extremely long names are less convenient.
    if len(stem) > 100:
        score -= 10
    elif 10 <= len(stem) <= 60:
        score += 5

    # Prefer names with fewer weird characters.
    score -= len(re.findall(r"[^A-Za-z0-9 _().-]", stem))

    return score


def choose_canonical(group):
    """Return the most suitable existing name from a duplicate group."""
    return max(
        group,
        key=lambda p: (
            filename_score(p),
            len(p.name) * -1,
            p.name.lower()
        )
    )


def path_identity(path):
    """
    Return an identity that distinguishes the actual scanned path spelling
    when possible, while also protecting against the same physical file being
    discovered more than once through aliases/junctions.
    """
    try:
        st = path.stat()
        # Windows/Linux both expose st_dev/st_ino. On normal filesystems this
        # identifies the physical directory entry.
        return ("inode", st.st_dev, st.st_ino)
    except OSError:
        # Fallback for inaccessible files.
        return ("path", str(path))


def unique_target(directory, desired_name, current_path):
    """Avoid overwriting any existing file."""
    desired_name = safe_filename(desired_name)
    target = directory / desired_name

    if target == current_path:
        return target

    if not target.exists():
        return target

    stem = target.stem
    suffix = target.suffix
    n = 2
    while True:
        candidate = directory / f"{stem} ({n}){suffix}"
        if candidate == current_path or not candidate.exists():
            return candidate
        n += 1


class ScanWorker(QThread):
    progress = Signal(int, str)
    finished_scan = Signal(object, object, object)
    error = Signal(str)

    def __init__(self, root, recursive=True, min_size=0):
        super().__init__()
        self.root = Path(root)
        self.recursive = recursive
        self.min_size = min_size
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            files = []
            iterator = self.root.rglob("*") if self.recursive else self.root.glob("*")

            for p in iterator:
                if self._stop:
                    return
                try:
                    if p.is_file() and p.stat().st_size >= self.min_size:
                        files.append(p)
                except (OSError, PermissionError):
                    continue

            total = len(files)
            size_groups = defaultdict(list)

            for i, p in enumerate(files):
                if self._stop:
                    return
                try:
                    size_groups[p.stat().st_size].append(p)
                except (OSError, PermissionError):
                    pass

                if total:
                    self.progress.emit(
                        int((i + 1) * 35 / total),
                        f"Indexing files: {i + 1:,} / {total:,}"
                    )

            candidates = [
                (size, paths) for size, paths in size_groups.items()
                if len(paths) > 1
            ]

            hash_groups = defaultdict(list)
            candidate_count = sum(len(x[1]) for x in candidates)
            done = 0

            for size, paths in candidates:
                for p in paths:
                    if self._stop:
                        return
                    try:
                        digest = file_hash(p)
                        hash_groups[(size, digest)].append(p)
                    except (OSError, PermissionError) as e:
                        self.error.emit(f"Could not read:\n{p}\n\n{e}")

                    done += 1
                    if candidate_count:
                        self.progress.emit(
                            35 + int(done * 65 / candidate_count),
                            f"Comparing duplicates: {done:,} / {candidate_count:,}"
                        )

            duplicates = {
                key: paths for key, paths in hash_groups.items()
                if len(paths) > 1
            }

            duplicate_files = sum(len(v) - 1 for v in duplicates.values())
            wasted = sum(key[0] * (len(v) - 1) for key, v in duplicates.items())

            self.finished_scan.emit(duplicates, files, wasted)

        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1250, 760)

        self.duplicate_groups = {}
        self.all_files = []
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
            "Find exact duplicate files using SHA-256, keep one copy, "
            "optionally give the retained file the most suitable name, "
            "and safely remove the extras."
        )
        subtitle.setStyleSheet("color: #666;")
        root.addWidget(subtitle)

        # Folder controls
        folder_box = QGroupBox("Scan Location")
        folder_layout = QGridLayout(folder_box)

        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Select a folder...")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_folder)

        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(True)

        self.min_size = QSpinBox()
        self.min_size.setRange(0, 10_000_000)
        self.min_size.setSuffix(" KB minimum")
        self.min_size.setValue(0)

        folder_layout.addWidget(QLabel("Folder:"), 0, 0)
        folder_layout.addWidget(self.folder_edit, 0, 1)
        folder_layout.addWidget(browse, 0, 2)
        folder_layout.addWidget(self.recursive, 1, 1)
        folder_layout.addWidget(QLabel("Ignore files smaller than:"), 1, 0)
        folder_layout.addWidget(self.min_size, 1, 2)

        root.addWidget(folder_box)

        # Actions
        action_layout = QHBoxLayout()

        self.scan_btn = QPushButton("🔎 Scan for Duplicates")
        self.scan_btn.clicked.connect(self.start_scan)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_scan)

        self.select_btn = QPushButton("Select ALL Duplicates")
        self.select_btn.clicked.connect(self.select_duplicates)

        self.rename_btn = QPushButton("Suggest / Rename Retained Files")
        self.rename_btn.clicked.connect(self.rename_retained)

        self.delete_btn = QPushButton("Delete ALL Duplicates")
        self.delete_btn.setToolTip("Delete every file marked DUPLICATE. KEEP files are always preserved.")
        self.delete_btn.clicked.connect(self.delete_selected)

        action_layout.addWidget(self.scan_btn)
        action_layout.addWidget(self.stop_btn)
        action_layout.addStretch()
        action_layout.addWidget(self.select_btn)
        action_layout.addWidget(self.rename_btn)
        action_layout.addWidget(self.delete_btn)

        root.addLayout(action_layout)

        # Options
        options = QHBoxLayout()

        self.auto_rename = QCheckBox(
            "When renaming, use the most descriptive existing duplicate name"
        )
        self.auto_rename.setChecked(True)

        self.trash_mode = QCheckBox(
            "Send deleted files to Recycle Bin"
        )
        self.trash_mode.setChecked(True)

        options.addWidget(self.auto_rename)
        options.addWidget(self.trash_mode)
        options.addStretch()
        root.addLayout(options)

        # Progress/status
        status_layout = QHBoxLayout()
        self.status = QLabel("Ready.")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        status_layout.addWidget(self.status, 2)
        status_layout.addWidget(self.progress, 1)
        root.addLayout(status_layout)

        # Table
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Keep", "Action", "Filename", "Location",
            "Size", "Duplicate Group", "SHA-256"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.MultiSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)

        root.addWidget(self.table, 1)

        # Bottom summary
        self.summary = QLabel(
            "No scan performed. Exact duplicates are detected by file size + SHA-256."
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
        folder = QFileDialog.getExistingDirectory(self, "Choose folder")
        if folder:
            self.folder_edit.setText(folder)

    def start_scan(self):
        folder = self.folder_edit.text().strip()
        if not folder:
            QMessageBox.warning(self, "Folder required", "Please choose a folder first.")
            return

        root = Path(folder)
        if not root.is_dir():
            QMessageBox.warning(self, "Invalid folder", "The selected folder does not exist.")
            return

        self.table.setRowCount(0)
        self.duplicate_groups = {}
        self.all_files = []

        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status.setText("Starting scan…")
        self.progress.setValue(0)

        min_bytes = self.min_size.value() * 1024

        self.worker = ScanWorker(
            root,
            recursive=self.recursive.isChecked(),
            min_size=min_bytes
        )
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
        # Keep scanning even if one inaccessible file was encountered.
        self.status.setText("Some files could not be read.")

    def worker_done(self):
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def scan_finished(self, duplicates, files, wasted):
        self.duplicate_groups = duplicates
        self.all_files = files
        self.populate_table()

        groups = 0
        duplicate_files = 0

        for (size, digest), raw_paths in duplicates.items():
            identities = {path_identity(p) for p in raw_paths}
            if len(identities) > 1:
                groups += 1
                duplicate_files += len(identities) - 1

        if groups:
            self.status.setText(
                f"Found {duplicate_files:,} removable duplicate files."
            )
            self.summary.setText(
                f"Found {groups:,} duplicate groups • "
                f"{duplicate_files:,} removable duplicate files • "
                f"{self.human_size(wasted)} potential space recovery"
            )
        else:
            self.status.setText("Scan complete.")
            self.summary.setText(
                f"Scanned {len(files):,} files • No exact duplicates found."
            )

        self.progress.setValue(100)

    def populate_table(self):
        self.table.setRowCount(0)

        group_no = 0

        for (size, digest), raw_paths in sorted(
            self.duplicate_groups.items(),
            key=lambda x: str(x[1][0]).lower()
        ):
            # A scanner can encounter the same physical file through an
            # alias/junction. Do not display that same physical file twice.
            paths = []
            seen_identities = set()

            for p in raw_paths:
                identity = path_identity(p)
                if identity in seen_identities:
                    continue
                seen_identities.add(identity)
                paths.append(p)

            if len(paths) < 2:
                continue

            group_no += 1

            # Choose exactly ONE retained physical file.
            keep = choose_canonical(paths)
            keep_identity = path_identity(keep)

            for p in paths:
                row = self.table.rowCount()
                self.table.insertRow(row)

                is_keep = path_identity(p) == keep_identity

                keep_box = QCheckBox()
                keep_box.setChecked(is_keep)
                keep_box.setEnabled(False)

                keep_widget = QWidget()
                keep_layout = QHBoxLayout(keep_widget)
                keep_layout.setContentsMargins(0, 0, 0, 0)
                keep_layout.setAlignment(Qt.AlignCenter)
                keep_layout.addWidget(keep_box)

                action = "KEEP" if is_keep else "DUPLICATE"
                action_item = QTableWidgetItem(action)

                if is_keep:
                    action_item.setFont(
                        QFont("Segoe UI", 9, QFont.Bold)
                    )

                self.table.setCellWidget(row, 0, keep_widget)
                self.table.setItem(row, 1, action_item)
                self.table.setItem(row, 2, QTableWidgetItem(p.name))
                self.table.setItem(row, 3, QTableWidgetItem(str(p.parent)))
                self.table.setItem(
                    row, 4, QTableWidgetItem(self.human_size(size))
                )
                self.table.setItem(
                    row, 5, QTableWidgetItem(str(group_no))
                )
                self.table.setItem(
                    row, 6, QTableWidgetItem(digest[:16] + "…")
                )

                # Store the actual path and explicit keep flag.
                action_item.setData(Qt.UserRole, str(p))
                action_item.setData(Qt.UserRole + 1, is_keep)

        # Keep the application's duplicate count synchronized with what is
        # actually shown in the table.
        visible_duplicate_files = sum(
            1
            for row in range(self.table.rowCount())
            if self.table.item(row, 1)
            and not bool(self.table.item(row, 1).data(Qt.UserRole + 1))
        )

        self.status.setText(
            f"Found {visible_duplicate_files:,} removable duplicate files."
        )

    def select_duplicates(self):
        if not self.duplicate_groups:
            return

        # QTableWidget.selectRow() can leave only the last row selected
        # depending on the active selection behavior. Build one explicit
        # multi-row selection instead.
        selection = QItemSelection()

        duplicate_count = 0

        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)

            if item and not bool(item.data(Qt.UserRole + 1)):
                left = self.table.model().index(row, 0)
                right = self.table.model().index(
                    row, self.table.columnCount() - 1
                )
                selection.select(left, right)
                duplicate_count += 1

        self.table.selectionModel().clearSelection()

        if not selection.isEmpty():
            self.table.selectionModel().select(
                selection,
                QItemSelectionModel.Select | QItemSelectionModel.Rows
            )

        actual_selected = len(
            self.table.selectionModel().selectedRows()
        )

        self.status.setText(
            f"Selected {actual_selected:,} of "
            f"{duplicate_count:,} removable duplicate files."
        )

    def rename_retained(self):
        if not self.duplicate_groups:
            QMessageBox.information(self, "Nothing to rename", "Scan for duplicates first.")
            return

        renamed = 0
        skipped = 0
        details = []

        # Each group has one retained file. The best existing filename becomes
        # the desired name. If the retained file already has it, nothing happens.
        for key, paths in self.duplicate_groups.items():
            keep = choose_canonical(paths)

            if not self.auto_rename.isChecked():
                continue

            desired = choose_canonical(paths).name

            # The canonical candidate may be the file we are keeping already.
            if keep.name == desired:
                continue

            target = unique_target(keep.parent, desired, keep)

            try:
                if target == keep:
                    continue

                # If the target is one of the duplicate copies, remove that
                # duplicate first only when it is an exact duplicate.
                if target.exists() and target in paths and target != keep:
                    try:
                        target.unlink()
                    except OSError:
                        skipped += 1
                        continue

                keep.rename(target)
                renamed += 1
                details.append(f"{keep.name}  →  {target.name}")
            except OSError:
                skipped += 1

        if renamed:
            self.populate_table()

        QMessageBox.information(
            self,
            "Rename result",
            f"Retained files renamed: {renamed}\n"
            f"Skipped: {skipped}\n\n"
            + ("\n".join(details[:20]) if details else "No retained files needed renaming.")
        )

    def delete_selected(self):
        if not self.duplicate_groups:
            QMessageBox.information(
                self, "Nothing to delete", "Scan for duplicates first."
            )
            return

        # IMPORTANT:
        # This is deliberately an ALL-DUPLICATES operation.
        # It does NOT depend on the visual table selection. Every row
        # marked DUPLICATE is included, while KEEP rows are protected.
        paths = []

        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item and not item.data(Qt.UserRole + 1):
                paths.append(Path(item.data(Qt.UserRole)))

        if not paths:
            QMessageBox.information(
                self,
                "No duplicates",
                "There are no removable duplicate files."
            )
            return

        total_size = 0
        for p in paths:
            try:
                total_size += p.stat().st_size
            except OSError:
                pass

        mode = "Recycle Bin" if self.trash_mode.isChecked() else "permanently"

        reply = QMessageBox.warning(
            self,
            "Confirm deletion",
            f"You are about to remove ALL {len(paths):,} exact duplicate files "
            f"({self.human_size(total_size)}).\n\n"
            f"Mode: {mode}\n\n"
            "Every KEEP file will be preserved.\n"
            "Only files marked DUPLICATE will be removed.\n\n"
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

        for i, p in enumerate(paths, 1):
            try:
                if self.trash_mode.isChecked():
                    self.move_to_recycle_bin(p)
                else:
                    p.unlink()
                deleted += 1
            except Exception as e:
                failed.append(f"{p}: {e}")

            if len(paths):
                self.progress.setValue(int(i * 100 / len(paths)))
                self.status.setText(
                    f"Removing duplicates: {i:,} / {len(paths):,}"
                )
                QApplication.processEvents()

        self.delete_btn.setEnabled(True)
        self.select_btn.setEnabled(True)

        if failed:
            QMessageBox.warning(
                self,
                "Deletion completed with errors",
                f"Removed {deleted:,} of {len(paths):,} duplicate files.\n"
                f"Could not remove {len(failed):,} files."
            )
        else:
            QMessageBox.information(
                self,
                "Deletion complete",
                f"Successfully removed ALL {deleted:,} duplicate files."
            )

        self.rescan_after_delete()

    @staticmethod
    def move_to_recycle_bin(path):
        """
        Windows: use PowerShell's Microsoft.VisualBasic.FileIO recycle-bin API.
        Other OSes: fall back to permanent deletion because a universal
        recycle-bin API is not guaranteed.
        """
        if sys.platform.startswith("win"):
            import subprocess
            escaped = str(path).replace("'", "''")
            ps = (
                "Add-Type -AssemblyName Microsoft.VisualBasic; "
                f"[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
                f"'{escaped}', "
                "[Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs, "
                "[Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        else:
            # On Linux this is deliberately explicit rather than pretending
            # that unlink() is a recycle-bin operation.
            path.unlink()

    def rescan_after_delete(self):
        # The easiest way to keep the table authoritative is to rescan.
        self.start_scan()

    @staticmethod
    def human_size(n):
        n = float(n)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024 or unit == "TB":
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    win = MainWindow()
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

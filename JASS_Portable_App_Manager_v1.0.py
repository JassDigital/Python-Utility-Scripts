"""
JASS Portable App Manager v1.0
A lightweight PySide6 manager for Windows portable applications.

Features:
- Add one or more portable-app folders
- Recursive scan for .exe files
- Automatic display-name detection
- Search/filter
- Category assignment
- Favorites
- Launch application
- Open application folder
- Rescan selected/all locations
- Add/edit/remove app entries
- Persistent JSON database
- Export inventory to CSV
- Windows-friendly, no admin rights required

This program does not install applications. It manages portable applications
that already exist on disk.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QSplitter, QStatusBar,
    QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget
)
from PySide6.QtCore import QUrl


APP_NAME = "JASS Portable App Manager"
VERSION = "1.0"
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "JASS" / "PortableAppManager"
DATA_FILE = DATA_DIR / "portable_apps.json"

DEFAULT_CATEGORIES = [
    "All",
    "Browsers",
    "Development",
    "Graphics",
    "Media",
    "Office",
    "Utilities",
    "System",
    "Games",
    "Other",
]


@dataclass
class PortableApp:
    name: str
    exe: str
    folder: str
    category: str = "Other"
    favorite: bool = False
    notes: str = ""


def clean_name(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or filename


def safe_read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return None


def guess_category(name: str) -> str:
    n = name.lower()
    rules = {
        "Browsers": ["chrome", "firefox", "opera", "brave", "vivaldi", "browser"],
        "Development": ["code", "vscode", "notepad++", "python", "git", "editor",
                        "studio", "terminal", "putty", "winscp"],
        "Graphics": ["gimp", "inkscape", "paint", "image", "krita", "viewer"],
        "Media": ["vlc", "audacity", "ffmpeg", "music", "video", "player", "handbrake"],
        "Office": ["libreoffice", "office", "writer", "calc", "pdf", "sumatra"],
        "System": ["cpu", "disk", "system", "process", "hardware", "monitor"],
        "Games": ["game", "steam", "dosbox"],
        "Utilities": ["7zip", "zip", "file", "manager", "tool", "utility"],
    }
    for category, words in rules.items():
        if any(word in n for word in words):
            return category
    return "Other"


class AppDialog(QDialog):
    def __init__(self, parent=None, app: PortableApp | None = None):
        super().__init__(parent)
        self.setWindowTitle("Portable Application")
        self.setMinimumWidth(600)

        self.name_edit = QLineEdit()
        self.exe_edit = QLineEdit()
        self.folder_edit = QLineEdit()
        self.category_combo = QComboBox()
        self.category_combo.addItems(DEFAULT_CATEGORIES[1:])
        self.favorite_check = QCheckBox("Favorite")
        self.notes_edit = QLineEdit()

        browse_exe = QPushButton("Browse…")
        browse_exe.clicked.connect(self.browse_exe)

        browse_folder = QPushButton("Browse…")
        browse_folder.clicked.connect(self.browse_folder)

        exe_row = QGridLayout()
        exe_row.addWidget(self.exe_edit, 0, 0)
        exe_row.addWidget(browse_exe, 0, 1)

        folder_row = QGridLayout()
        folder_row.addWidget(self.folder_edit, 0, 0)
        folder_row.addWidget(browse_folder, 0, 1)

        form = QFormLayout()
        form.addRow("Name:", self.name_edit)
        form.addRow("Executable:", exe_row)
        form.addRow("Application folder:", folder_row)
        form.addRow("Category:", self.category_combo)
        form.addRow("", self.favorite_check)
        form.addRow("Notes:", self.notes_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if app:
            self.name_edit.setText(app.name)
            self.exe_edit.setText(app.exe)
            self.folder_edit.setText(app.folder)
            idx = self.category_combo.findText(app.category)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            self.favorite_check.setChecked(app.favorite)
            self.notes_edit.setText(app.notes)

    def browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Portable Application", "", "Executable (*.exe)"
        )
        if path:
            self.exe_edit.setText(path)
            if not self.name_edit.text().strip():
                self.name_edit.setText(clean_name(path))

            if not self.folder_edit.text().strip():
                self.folder_edit.setText(str(Path(path).parent))

    def browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Application Folder")
        if path:
            self.folder_edit.setText(path)

    def get_app(self) -> PortableApp:
        exe = self.exe_edit.text().strip()
        folder = self.folder_edit.text().strip() or (
            str(Path(exe).parent) if exe else ""
        )
        name = self.name_edit.text().strip() or clean_name(exe)
        return PortableApp(
            name=name,
            exe=exe,
            folder=folder,
            category=self.category_combo.currentText(),
            favorite=self.favorite_check.isChecked(),
            notes=self.notes_edit.text().strip(),
        )


class PortableManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.apps: list[PortableApp] = []
        self.roots: list[str] = []
        self.current_category = "All"
        self._loading = False

        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1250, 760)
        self.setMinimumSize(QSize(900, 600))

        self.load_data()
        self.build_ui()
        self.refresh_categories()
        self.refresh_table()

    # ---------- persistence ----------

    def load_data(self):
        data = safe_read_json(DATA_FILE)
        if not isinstance(data, dict):
            return

        self.roots = [
            str(Path(p))
            for p in data.get("roots", [])
            if isinstance(p, str)
        ]

        for item in data.get("apps", []):
            if not isinstance(item, dict):
                continue
            try:
                self.apps.append(PortableApp(
                    name=str(item.get("name", "")),
                    exe=str(item.get("exe", "")),
                    folder=str(item.get("folder", "")),
                    category=str(item.get("category", "Other")),
                    favorite=bool(item.get("favorite", False)),
                    notes=str(item.get("notes", "")),
                ))
            except Exception:
                pass

    def save_data(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": VERSION,
            "roots": self.roots,
            "apps": [asdict(a) for a in self.apps],
        }
        tmp = DATA_FILE.with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            tmp.replace(DATA_FILE)
        except OSError as exc:
            QMessageBox.warning(self, "Save Error", str(exc))

    # ---------- UI ----------

    def build_ui(self):
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        def add_action(text, slot):
            action = QAction(text, self)
            action.triggered.connect(slot)
            toolbar.addAction(action)

        add_action("Add Folder", self.add_root)
        add_action("Scan", self.scan_all)
        add_action("Add App", self.add_app)
        add_action("Edit", self.edit_app)
        add_action("Remove", self.remove_app)
        add_action("Launch", self.launch_selected)
        add_action("Open Folder", self.open_folder)
        toolbar.addSeparator()
        add_action("Export CSV", self.export_csv)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        top = QGroupBox()
        top_layout = QGridLayout(top)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search applications, folders or notes…")
        self.search.textChanged.connect(self.refresh_table)

        self.category = QComboBox()
        self.category.currentTextChanged.connect(self.category_changed)

        self.favorites_only = QCheckBox("Favorites only")
        self.favorites_only.stateChanged.connect(self.refresh_table)

        top_layout.addWidget(QLabel("Search:"), 0, 0)
        top_layout.addWidget(self.search, 0, 1, 1, 3)
        top_layout.addWidget(QLabel("Category:"), 0, 4)
        top_layout.addWidget(self.category, 0, 5)
        top_layout.addWidget(self.favorites_only, 0, 6)

        main_layout.addWidget(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.root_list = QListWidget()
        self.root_list.setAlternatingRowColors(True)
        self.root_list.itemSelectionChanged.connect(self.root_filter_changed)
        splitter.addWidget(self.root_list)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Application", "Category", "Executable", "Folder", "Favorite"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(lambda _: self.launch_selected())
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        splitter.addWidget(self.table)

        splitter.setSizes([260, 940])
        main_layout.addWidget(splitter)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self.root_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.root_list.customContextMenuRequested.connect(self.root_context_menu)

    def refresh_categories(self):
        current = self.category.currentText() or "All"
        categories = ["All"] + sorted({
            a.category for a in self.apps
            if a.category and a.category != "All"
        })
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItems(categories)
        idx = self.category.findText(current)
        self.category.setCurrentIndex(max(0, idx))
        self.category.blockSignals(False)

        self.root_list.clear()
        self.root_list.addItem("All Locations")
        for root in self.roots:
            self.root_list.addItem(root)

    def category_changed(self, value):
        self.current_category = value
        self.refresh_table()

    def root_filter_changed(self):
        self.refresh_table()

    def selected_root(self) -> str | None:
        items = self.root_list.selectedItems()
        if not items or items[0].text() == "All Locations":
            return None
        return items[0].text()

    def filtered_apps(self):
        query = self.search.text().strip().lower()
        category = self.category.currentText()
        root = self.selected_root()
        fav = self.favorites_only.isChecked()

        result = []
        for app in self.apps:
            if category != "All" and app.category != category:
                continue
            if root and not Path(app.exe).as_posix().lower().startswith(
                Path(root).as_posix().lower()
            ):
                continue
            if fav and not app.favorite:
                continue
            haystack = " ".join([
                app.name, app.exe, app.folder, app.category, app.notes
            ]).lower()
            if query and query not in haystack:
                continue
            result.append(app)

        return sorted(result, key=lambda x: (not x.favorite, x.name.lower()))

    def refresh_table(self):
        apps = self.filtered_apps()
        self._loading = True
        self.table.setRowCount(0)

        for app in apps:
            row = self.table.rowCount()
            self.table.insertRow(row)

            name = QTableWidgetItem(("★ " if app.favorite else "") + app.name)
            name.setData(Qt.ItemDataRole.UserRole, app.exe)

            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(app.category))
            self.table.setItem(row, 2, QTableWidgetItem(app.exe))
            self.table.setItem(row, 3, QTableWidgetItem(app.folder))
            self.table.setItem(row, 4, QTableWidgetItem("Yes" if app.favorite else ""))

        self._loading = False
        self.status.showMessage(
            f"{len(apps)} application(s) shown  •  {len(self.apps)} total"
        )

    def selected_app(self) -> PortableApp | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        exe = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        for app in self.apps:
            if app.exe == exe:
                return app
        return None

    # ---------- roots / scanning ----------

    def add_root(self):
        path = QFileDialog.getExistingDirectory(self, "Add Portable Apps Folder")
        if not path:
            return
        path = str(Path(path).resolve())
        if path not in self.roots:
            self.roots.append(path)
            self.save_data()
            self.refresh_categories()
        self.scan_root(path)

    def scan_all(self):
        if not self.roots:
            QMessageBox.information(
                self, "No Locations",
                "Add a folder containing your portable applications first."
            )
            return

        total = 0
        for root in self.roots:
            total += self.scan_root(root, show_message=False)

        self.save_data()
        self.refresh_categories()
        self.refresh_table()
        self.status.showMessage(f"Scan complete: {total} executable(s) found.")

    def scan_root(self, root: str, show_message=True) -> int:
        root_path = Path(root)
        if not root_path.exists():
            if show_message:
                QMessageBox.warning(self, "Folder Not Found", root)
            return 0

        found = 0
        known = {str(Path(a.exe).resolve()).lower() for a in self.apps}

        ignored_dirs = {
            ".git", "__pycache__", "node_modules", ".venv",
            "venv", "cache", "caches", "temp", "tmp"
        }

        for path in root_path.rglob("*.exe"):
            try:
                if not path.is_file():
                    continue
                if any(part.lower() in ignored_dirs for part in path.parts):
                    continue

                resolved = str(path.resolve())
                if resolved.lower() in known:
                    continue

                # Skip obvious uninstallers and helper binaries.
                lname = path.name.lower()
                if any(token in lname for token in (
                    "uninstall", "unins", "setup", "installer"
                )):
                    continue

                app = PortableApp(
                    name=clean_name(path.name),
                    exe=resolved,
                    folder=str(path.parent.resolve()),
                    category=guess_category(path.name),
                )
                self.apps.append(app)
                known.add(resolved.lower())
                found += 1
            except (OSError, PermissionError):
                continue

        self.save_data()
        self.refresh_categories()
        self.refresh_table()

        if show_message:
            QMessageBox.information(
                self, "Scan Complete",
                f"Found {found} new portable application(s).\n\n{root}"
            )
        return found

    def root_context_menu(self, pos):
        item = self.root_list.itemAt(pos)
        if not item or item.text() == "All Locations":
            return

        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        scan = menu.addAction("Scan This Folder")
        remove = menu.addAction("Remove Location")
        action = menu.exec(self.root_list.mapToGlobal(pos))

        if action == scan:
            self.scan_root(item.text())
        elif action == remove:
            path = item.text()
            if QMessageBox.question(
                self, "Remove Location",
                f"Remove this location from the manager?\n\n{path}\n\n"
                "The actual files will NOT be deleted."
            ) == QMessageBox.StandardButton.Yes:
                self.roots = [r for r in self.roots if r != path]
                self.save_data()
                self.refresh_categories()
                self.refresh_table()

    # ---------- app operations ----------

    def add_app(self):
        dlg = AppDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        app = dlg.get_app()
        if not app.exe:
            QMessageBox.warning(self, "Missing Executable",
                                "Please select an executable.")
            return

        if any(Path(a.exe).resolve() == Path(app.exe).resolve()
               for a in self.apps if Path(a.exe).exists()):
            QMessageBox.information(self, "Already Added",
                                    "This executable is already in the manager.")
            return

        self.apps.append(app)
        if app.folder and app.folder not in self.roots:
            # Do not automatically add every individual application folder as a root.
            pass
        self.save_data()
        self.refresh_categories()
        self.refresh_table()

    def edit_app(self):
        app = self.selected_app()
        if not app:
            QMessageBox.information(self, "Select Application",
                                    "Select an application first.")
            return

        old_exe = app.exe
        dlg = AppDialog(self, app)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        updated = dlg.get_app()
        app.name = updated.name
        app.exe = updated.exe
        app.folder = updated.folder
        app.category = updated.category
        app.favorite = updated.favorite
        app.notes = updated.notes

        if old_exe != app.exe:
            # Ensure no duplicate executable was introduced.
            duplicates = [a for a in self.apps if a is not app and
                          a.exe.lower() == app.exe.lower()]
            if duplicates:
                QMessageBox.warning(
                    self, "Duplicate",
                    "Another application already uses this executable."
                )
                app.exe = old_exe

        self.save_data()
        self.refresh_categories()
        self.refresh_table()

    def remove_app(self):
        app = self.selected_app()
        if not app:
            QMessageBox.information(self, "Select Application",
                                    "Select an application first.")
            return

        answer = QMessageBox.question(
            self, "Remove Application",
            f"Remove '{app.name}' from JASS Portable App Manager?\n\n"
            "The actual application files will NOT be deleted."
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.apps.remove(app)
        self.save_data()
        self.refresh_categories()
        self.refresh_table()

    def launch_selected(self):
        app = self.selected_app()
        if not app:
            QMessageBox.information(self, "Select Application",
                                    "Select an application first.")
            return

        exe = Path(app.exe)
        if not exe.exists():
            QMessageBox.warning(
                self, "Executable Not Found",
                f"The executable no longer exists:\n\n{exe}\n\n"
                "Use Edit to correct the path or remove the entry."
            )
            return

        try:
            subprocess.Popen(
                [str(exe)],
                cwd=str(Path(app.folder) if Path(app.folder).exists()
                         else exe.parent),
                shell=False
            )
            self.status.showMessage(f"Launched: {app.name}")
        except OSError as exc:
            QMessageBox.critical(self, "Launch Failed", str(exc))

    def open_folder(self):
        app = self.selected_app()
        if not app:
            QMessageBox.information(self, "Select Application",
                                    "Select an application first.")
            return

        folder = Path(app.folder)
        if not folder.exists():
            folder = Path(app.exe).parent

        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        else:
            QMessageBox.warning(self, "Folder Not Found", str(folder))

    # ---------- export ----------

    def export_csv(self):
        if not self.apps:
            QMessageBox.information(self, "Nothing to Export",
                                    "There are no applications to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Inventory", "JASS_Portable_Apps.csv",
            "CSV Files (*.csv)"
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Name", "Category", "Executable", "Folder",
                    "Favorite", "Notes"
                ])
                for app in sorted(self.apps, key=lambda a: a.name.lower()):
                    writer.writerow([
                        app.name, app.category, app.exe, app.folder,
                        "Yes" if app.favorite else "", app.notes
                    ])
            QMessageBox.information(
                self, "Export Complete",
                f"Inventory exported to:\n\n{path}"
            )
        except OSError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))

    def closeEvent(self, event):
        self.save_data()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("JASS")

    window = PortableManager()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

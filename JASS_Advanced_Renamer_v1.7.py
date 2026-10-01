import sys
import os
import re
import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QMimeData, QUrl, Signal, QObject, QThread, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QListWidget, QListWidgetItem, QTableView, QHeaderView,
    QFileDialog, QMessageBox, QSplitter, QGroupBox, QFormLayout, QAbstractItemView,
    QProgressBar, QStatusBar, QToolButton, QMenu, QDialog, QTextEdit,
    QScrollArea, QSizePolicy
)

APP_NAME = "JASS Advanced Renamer"
VERSION = "1.7"


# ----------------------------- utilities -----------------------------

def human_size(n):
    try:
        n = float(n)
    except Exception:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{n:.1f} {units[i]}" if i else f"{int(n)} B"


def unique_name(path, used):
    """Return a collision-free name by adding _1, _2 ..."""
    base = path.stem
    ext = path.suffix
    candidate = path
    i = 1
    while str(candidate).lower() in used or candidate.exists():
        candidate = path.with_name(f"{base}_{i}{ext}")
        i += 1
    return candidate


def sanitize_filename(name, replacement="_"):
    # Windows-invalid characters and control chars
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', replacement, name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(". ")
    return name or "Unnamed"


def safe_ext(p):
    return p.suffix[1:] if p.suffix else ""


def format_tag_value(tag, p, index, total):
    try:
        st = p.stat()
    except Exception:
        st = None

    created = ""
    modified = ""
    if st:
        try:
            created = datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d")
            modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")
        except Exception:
            pass

    values = {
        "name": p.stem,
        "ext": safe_ext(p),
        "filename": p.name,
        "parent": p.parent.name,
        "folder": str(p.parent),
        "num": str(index),
        "num2": f"{index:02d}",
        "num3": f"{index:03d}",
        "num4": f"{index:04d}",
        "size": human_size(st.st_size) if st else "",
        "bytes": str(st.st_size) if st else "",
        "created": created,
        "modified": modified,
    }
    return values.get(tag.lower(), "{" + tag + "}")


def apply_tags(text, p, index, total):
    def repl(m):
        return format_tag_value(m.group(1), p, index, total)
    return re.sub(r"\{([A-Za-z0-9_]+)\}", repl, text)


# ----------------------------- method engine -----------------------------

class Method:
    def __init__(self, kind="Prefix / Suffix", data=None, enabled=True):
        self.kind = kind
        self.data = data or {}
        self.enabled = enabled

    def label(self):
        if self.kind == "Prefix / Suffix":
            return f"Prefix: {self.data.get('prefix','')} | Suffix: {self.data.get('suffix','')}"
        if self.kind == "Replace":
            return f"Replace: {self.data.get('find','')} → {self.data.get('replace','')}"
        if self.kind == "Regex Replace":
            return f"Regex: {self.data.get('pattern','')} → {self.data.get('replace','')}"
        if self.kind == "Change Case":
            return f"Case: {self.data.get('mode','lower')}"
        if self.kind == "Trim":
            return f"Trim: {self.data.get('chars','')} ({self.data.get('side','both')})"
        if self.kind == "Sequential Name":
            base = self.data.get("base","Fanu")
            pos = self.data.get("position","after")
            return f"Sequential Name: {base} + number ({pos})"
        if self.kind == "Number Only":
            return f"Number Only: start {self.data.get('start',1)}, pad {self.data.get('width',1)}"
        if self.kind == "Numbering":
            return f"Number: start {self.data.get('start',1)}, pad {self.data.get('width',3)}, sep '{self.data.get('separator','_')}'"
        if self.kind == "Remove Characters":
            return f"Remove: {self.data.get('chars','')}"
        if self.kind == "Extension":
            return f"Extension: .{self.data.get('extension','')}"
        if self.kind == "New Name":
            return f"New name: {self.data.get('pattern','')}"
        if self.kind == "Sanitize":
            return "Windows filename cleanup"
        return self.kind

    def apply(self, stem, original, index, total):
        if not self.enabled:
            return stem

        d = self.data
        if self.kind == "Prefix / Suffix":
            return f"{d.get('prefix','')}{stem}{d.get('suffix','')}"
        if self.kind == "Replace":
            find = apply_tags(d.get("find",""), original, index, total)
            repl = apply_tags(d.get("replace",""), original, index, total)
            if d.get("case_sensitive", False):
                return stem.replace(find, repl)
            if not find:
                return stem
            return re.sub(re.escape(find), lambda m: repl, stem, flags=re.IGNORECASE)
        if self.kind == "Regex Replace":
            pattern = apply_tags(d.get("pattern",""), original, index, total)
            repl = apply_tags(d.get("replace",""), original, index, total)
            try:
                flags = 0 if d.get("case_sensitive", False) else re.IGNORECASE
                return re.sub(pattern, repl, stem, flags=flags)
            except re.error:
                return stem
        if self.kind == "Change Case":
            mode = d.get("mode","lower")
            if mode == "UPPER":
                return stem.upper()
            if mode == "lower":
                return stem.lower()
            if mode == "Title":
                return stem.title()
            if mode == "Sentence":
                return stem[:1].upper() + stem[1:].lower()
            return stem
        if self.kind == "Trim":
            chars = d.get("chars","")
            side = d.get("side","both")
            if not chars:
                return stem.strip() if side == "both" else (stem.lstrip() if side == "left" else stem.rstrip())
            if side == "left":
                return stem.lstrip(chars)
            if side == "right":
                return stem.rstrip(chars)
            return stem.strip(chars)
        if self.kind == "Sequential Name":
            base = apply_tags(d.get("base", ""), original, index, total)
            start = int(d.get("start", 1))
            step = int(d.get("step", 1))
            width = int(d.get("width", 0))
            separator = d.get("separator", "")
            position = d.get("position", "after")
            number = start + ((index - 1) * step)
            num = str(number).zfill(width) if width > 0 else str(number)
            if position == "before":
                return f"{num}{separator}{base}"
            return f"{base}{separator}{num}"
        if self.kind == "Number Only":
            start = int(d.get("start", 1))
            width = int(d.get("width", 1))
            num = str(start + index - 1).zfill(width)
            return num
        if self.kind == "Numbering":
            start = int(d.get("start", 1))
            width = int(d.get("width", 3))
            sep = d.get("separator", "_")
            position = d.get("position", "prefix")
            num = str(start + index - 1).zfill(width)
            return f"{num}{sep}{stem}" if position == "prefix" else f"{stem}{sep}{num}"
        if self.kind == "Remove Characters":
            chars = d.get("chars","")
            return "".join(c for c in stem if c not in chars)
        if self.kind == "Extension":
            return stem
        if self.kind == "New Name":
            return apply_tags(d.get("pattern",""), original, index, total)
        if self.kind == "Sanitize":
            return sanitize_filename(stem, d.get("replacement","_"))
        return stem


# ----------------------------- method editor -----------------------------

class MethodEditor(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.method = Method()
        self._building = False
        self.form = QFormLayout(self)
        self.controls = {}
        self.setMinimumWidth(260)
        self.setMinimumHeight(0)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.build()

    def clear_form(self):
        while self.form.count():
            item = self.form.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.controls = {}

    def add_row(self, label, widget):
        self.form.addRow(label, widget)
        self.controls[label] = widget
        if hasattr(widget, "textChanged"):
            widget.textChanged.connect(self.emit_changed)
        elif hasattr(widget, "valueChanged"):
            widget.valueChanged.connect(self.emit_changed)
        elif hasattr(widget, "currentIndexChanged"):
            widget.currentIndexChanged.connect(self.emit_changed)
        elif hasattr(widget, "stateChanged"):
            widget.stateChanged.connect(self.emit_changed)

    def build(self):
        self._building = True
        self.blockSignals(True)
        self.clear_form()
        kind = self.method.kind
        d = self.method.data

        if kind == "Prefix / Suffix":
            self.add_row("Prefix", QLineEdit(d.get("prefix","")))
            self.add_row("Suffix", QLineEdit(d.get("suffix","")))
        elif kind == "Replace":
            self.add_row("Find", QLineEdit(d.get("find","")))
            self.add_row("Replace with", QLineEdit(d.get("replace","")))
            self.add_row("Case sensitive", QCheckBox())
            self.controls["Case sensitive"].setChecked(d.get("case_sensitive", False))
        elif kind == "Regex Replace":
            self.add_row("Pattern", QLineEdit(d.get("pattern","")))
            self.add_row("Replace with", QLineEdit(d.get("replace","")))
            self.add_row("Case sensitive", QCheckBox())
            self.controls["Case sensitive"].setChecked(d.get("case_sensitive", False))
        elif kind == "Change Case":
            c = QComboBox()
            c.addItems(["UPPER","lower","Title","Sentence"])
            c.setCurrentText(d.get("mode","lower"))
            self.add_row("Mode", c)
        elif kind == "Trim":
            self.add_row("Characters", QLineEdit(d.get("chars","")))
            c = QComboBox(); c.addItems(["both","left","right"])
            c.setCurrentText(d.get("side","both"))
            self.add_row("Side", c)
        elif kind == "Sequential Name":
            base = QLineEdit(d.get("base", "Fanu"))
            s = QSpinBox(); s.setRange(-999999, 999999); s.setValue(int(d.get("start", 1)))
            step = QSpinBox(); step.setRange(-999999, 999999); step.setValue(int(d.get("step", 1)))
            w = QSpinBox(); w.setRange(0, 10); w.setValue(int(d.get("width", 0)))
            sep = QLineEdit(d.get("separator", ""))
            pos = QComboBox(); pos.addItems(["after", "before"]); pos.setCurrentText(d.get("position", "after"))
            self.add_row("Base name", base)
            self.add_row("Start", s)
            self.add_row("Step", step)
            self.add_row("Zero padding", w)
            self.add_row("Separator", sep)
            self.add_row("Position", pos)
        elif kind == "Number Only":
            s = QSpinBox(); s.setRange(-999999, 999999); s.setValue(int(d.get("start",1)))
            w = QSpinBox(); w.setRange(0, 10); w.setValue(int(d.get("width",1)))
            self.add_row("Start", s)
            self.add_row("Zero padding", w)
        elif kind == "Numbering":
            s = QSpinBox(); s.setRange(-999999, 999999); s.setValue(int(d.get("start",1)))
            w = QSpinBox(); w.setRange(0, 10); w.setValue(int(d.get("width",3)))
            sep = QLineEdit(d.get("separator","_"))
            pos = QComboBox(); pos.addItems(["prefix","suffix"]); pos.setCurrentText(d.get("position","prefix"))
            self.add_row("Start", s); self.add_row("Zero padding", w)
            self.add_row("Separator", sep); self.add_row("Position", pos)
        elif kind == "Remove Characters":
            self.add_row("Characters", QLineEdit(d.get("chars","")))
        elif kind == "Extension":
            self.add_row("Extension", QLineEdit(d.get("extension","")))
        elif kind == "New Name":
            e = QLineEdit(d.get("pattern","{num3}_{name}"))
            self.add_row("Pattern", e)
        elif kind == "Sanitize":
            self.add_row("Replacement", QLineEdit(d.get("replacement","_")))

        self._building = False
        self.blockSignals(False)

    def emit_changed(self, *args):
        if not self._building:
            self.read_into_method()
            self.changed.emit()

    def read_into_method(self):
        kind = self.method.kind
        d = {}
        for label, w in self.controls.items():
            if isinstance(w, QLineEdit):
                d[label] = w.text()
            elif isinstance(w, QComboBox):
                d[label] = w.currentText()
            elif isinstance(w, QSpinBox):
                d[label] = w.value()
            elif isinstance(w, QCheckBox):
                d[label] = w.isChecked()

        mapping = {
            "Prefix": "prefix", "Suffix": "suffix",
            "Find": "find", "Replace with": "replace",
            "Pattern": "pattern", "Case sensitive": "case_sensitive",
            "Mode": "mode", "Characters": "chars", "Side": "side",
            "Base name": "base", "Start": "start", "Step": "step",
            "Zero padding": "width", "Separator": "separator",
            "Position": "position", "Extension": "extension",
            "Replacement": "replacement",
        }
        self.method.data = {mapping[k]: v for k, v in d.items() if k in mapping}

    def set_method(self, method):
        self.method = method
        self.build()


# ----------------------------- main window -----------------------------



class PreviewModel(QAbstractTableModel):
    HEADERS = ["✓", "Original Name", "New Name", "Path", "Size", "Status"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.rows)):
            return None
        row = self.rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return "✓" if row["checked"] else ""
            return row["values"][col]
        if role == Qt.ItemDataRole.CheckStateRole and col == 0:
            return Qt.CheckState.Checked if row["checked"] else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ToolTipRole and col in (1, 2, 3):
            return row["values"][col]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.column() != 0 or role != Qt.ItemDataRole.CheckStateRole:
            return False
        self.rows[index.row()]["checked"] = value == Qt.CheckState.Checked or value == 2
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole, Qt.ItemDataRole.DisplayRole])
        return True

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def set_all_checked(self, checked):
        if not self.rows:
            return
        for row in self.rows:
            row["checked"] = checked
        self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows)-1, 0),
                              [Qt.ItemDataRole.CheckStateRole, Qt.ItemDataRole.DisplayRole])


class PreviewWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, files, methods, sanitize):
        super().__init__()
        self.files = files
        self.methods = methods
        self.sanitize = sanitize

    def calculate_name(self, p, index, total):
        stem = p.stem
        ext = p.suffix
        for m in self.methods:
            stem = m.apply(stem, p, index, total)
        for m in self.methods:
            if m.enabled and m.kind == "Extension":
                x = apply_tags(m.data.get("extension", ""), p, index, total).strip()
                if x:
                    ext = "." + x.lstrip(".")
        if self.sanitize:
            stem = sanitize_filename(stem)
        return stem + ext

    def run(self):
        try:
            total = len(self.files)
            used = set()
            rows = []
            changes = 0
            conflicts = 0
            for i, p in enumerate(self.files, 1):
                newname = self.calculate_name(p, i, total)
                target = p.with_name(newname)
                key = str(target).lower()
                conflict = False
                if target != p:
                    changes += 1
                    try:
                        if target.exists() and target.resolve() != p.resolve():
                            conflict = True
                    except Exception:
                        if target.exists():
                            conflict = True
                    if key in used:
                        conflict = True
                used.add(key)
                try:
                    size = human_size(p.stat().st_size) if p.exists() else ""
                except Exception:
                    size = ""
                status = "CONFLICT" if conflict else ("CHANGE" if target != p else "UNCHANGED")
                if conflict:
                    conflicts += 1
                rows.append({
                    "path": p,
                    "newname": newname,
                    "checked": True,
                    "values": ["", p.name, newname, str(p.parent), size, status],
                })
            self.finished.emit({"rows": rows, "files": total, "changes": changes, "conflicts": conflicts})
        except Exception as e:
            self.failed.emit(str(e))

class RenamerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1500, 820)
        self.setMinimumSize(1000, 620)
        self.setAcceptDrops(True)

        self.folder = None
        self.files = []
        self.rows = []
        self.history = []
        self.methods = [Method("Prefix / Suffix", {"prefix":"","suffix":""})]
        self.current_method = -1
        self.preview_thread = None
        self.preview_worker = None
        self.preview_running = False
        self.preview_model = PreviewModel(self)
        self.build_ui()
        self.apply_theme()
        self.update_preview()

    # ----- UI -----

    def build_ui(self):
        central = QWidget()
        central.setMinimumSize(0, 0)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10,10,10,10)
        root.setSpacing(8)

        # top toolbar
        bar = QHBoxLayout()
        title = QLabel("JASS <b>ADVANCED RENAMER</b>")
        title.setObjectName("title")
        bar.addWidget(title)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Choose a folder or drag one here...")
        bar.addWidget(self.folder_edit, 1)
        b = QPushButton("📁 ADD FOLDER")
        b.clicked.connect(self.choose_folder)
        bar.addWidget(b)
        b = QPushButton("📄 ADD FILES")
        b.clicked.connect(self.add_files)
        bar.addWidget(b)
        root.addLayout(bar)

        # quick controls
        quick = QHBoxLayout()
        self.recursive = QCheckBox("Include subfolders")
        quick.addWidget(self.recursive)
        self.files_only = QCheckBox("Files only")
        self.files_only.setChecked(True)
        quick.addWidget(self.files_only)
        self.hidden = QCheckBox("Include hidden")
        quick.addWidget(self.hidden)
        quick.addStretch()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter loaded files...")
        self.filter_edit.textChanged.connect(
            lambda: self.statusBar().showMessage("Filter changed — click UPDATE PREVIEW.")
        )
        self.filter_edit.setMaximumWidth(320)
        quick.addWidget(self.filter_edit)
        root.addLayout(quick)

        split = QSplitter(Qt.Horizontal)
        split.setMinimumSize(0, 0)
        split.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(split, 1)

        # left: methods
        left = QWidget()
        left.setMinimumSize(0, 0)
        ll = QVBoxLayout(left)
        box = QGroupBox("RENAME METHODS")
        bl = QVBoxLayout(box)
        self.method_list = QListWidget()
        self.method_list.setMinimumSize(0, 0)
        self.method_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.method_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.method_list.currentRowChanged.connect(self.method_selected)
        bl.addWidget(self.method_list)
        mb = QHBoxLayout()
        add = QPushButton("+ ADD")
        add.clicked.connect(self.add_method)
        rm = QPushButton("− REMOVE")
        rm.clicked.connect(self.remove_method)
        up = QPushButton("▲")
        up.clicked.connect(lambda: self.move_method(-1))
        dn = QPushButton("▼")
        dn.clicked.connect(lambda: self.move_method(1))
        for x in (add,rm,up,dn):
            mb.addWidget(x)
        bl.addLayout(mb)
        ll.addWidget(box)

        presets = QHBoxLayout()
        save = QPushButton("SAVE PRESET")
        save.clicked.connect(self.save_preset)
        load = QPushButton("LOAD PRESET")
        load.clicked.connect(self.load_preset)
        clear = QPushButton("CLEAR")
        clear.clicked.connect(self.clear_methods)
        presets.addWidget(save); presets.addWidget(load); presets.addWidget(clear)
        ll.addLayout(presets)
        split.addWidget(left)

        # center: file preview
        center = QWidget()
        center.setMinimumSize(0, 0)
        cl = QVBoxLayout(center)
        stats = QHBoxLayout()
        self.stat_files = QLabel("0 files")
        self.stat_changes = QLabel("0 changes")
        self.stat_conflicts = QLabel("0 conflicts")
        stats.addWidget(self.stat_files); stats.addWidget(self.stat_changes); stats.addWidget(self.stat_conflicts)
        stats.addStretch()
        cl.addLayout(stats)

        self.table = QTableView()
        self.table.setMinimumSize(0, 0)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setModel(self.preview_model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setDefaultSectionSize(28)
        cl.addWidget(self.table, 1)

        actionbar = QHBoxLayout()
        selall = QPushButton("SELECT ALL")
        selall.clicked.connect(self.select_all)
        selnone = QPushButton("CLEAR SELECTION")
        selnone.clicked.connect(self.clear_selection)
        refresh = QPushButton("↻ REFRESH")
        refresh.clicked.connect(self.refresh_folder)
        preview_btn = QPushButton("▶ UPDATE PREVIEW")
        preview_btn.setObjectName("preview")
        preview_btn.clicked.connect(self.update_preview)
        self.preview_btn = preview_btn
        actionbar.addWidget(selall); actionbar.addWidget(selnone); actionbar.addWidget(refresh)
        actionbar.addWidget(preview_btn)
        actionbar.addStretch()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setMaximumWidth(260)
        actionbar.addWidget(self.progress)
        cl.addLayout(actionbar)
        split.addWidget(center)

        # right: editor
        right = QWidget()
        right.setMinimumSize(0, 0)
        right.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        rl = QVBoxLayout(right)
        editbox = QGroupBox("METHOD SETTINGS")
        el = QVBoxLayout(editbox)
        self.editor = MethodEditor(self)
        self.editor.changed.connect(self.method_changed)
        el.addWidget(self.editor)
        rl.addWidget(editbox)

        tagbox = QGroupBox("TAGS")
        tl = QVBoxLayout(tagbox)
        tags = QLabel(
            "<b>Available tags</b><br>"
            "{name}  filename stem<br>"
            "{ext}  extension<br>"
            "{num}/{num2}/{num3}/{num4}  sequence<br>"
            "{parent}  parent folder<br>"
            "{created}  created date<br>"
            "{modified}  modified date<br>"
            "{size} / {bytes}  file size<br><br>"
            "<b>Simple numbering:</b> add <i>Number Only</i> first, then "
            "<i>Prefix / Suffix</i>. Example: Prefix <b>IMG_</b> → "
            "Number Only → 1,2,3 produces IMG_1, IMG_2, IMG_3."
        )
        tags.setWordWrap(True)
        tl.addWidget(tags)
        rl.addWidget(tagbox)

        safety = QGroupBox("BATCH OPTIONS")
        sl = QFormLayout(safety)
        self.mode = QComboBox()
        self.mode.addItems(["Rename", "Copy", "Move"])
        self.collision = QComboBox()
        self.collision.addItems(["Stop on conflict", "Auto-number conflicts", "Skip conflicts"])
        self.sanitize = QCheckBox("Clean invalid Windows characters")
        self.sanitize.setChecked(True)
        sl.addRow("Mode", self.mode)
        sl.addRow("Conflict", self.collision)
        sl.addRow(self.sanitize)
        rl.addWidget(safety)

        self.rename_btn = QPushButton("⚡  RENAME SELECTED")
        self.rename_btn.setObjectName("primary")
        self.rename_btn.clicked.connect(self.perform_batch)
        rl.addWidget(self.rename_btn)
        undo = QPushButton("↶ UNDO LAST BATCH")
        undo.clicked.connect(self.undo_last)
        rl.addWidget(undo)
        rl.addStretch()
        # The settings panel can grow vertically as methods become more complex.
        # Keep it scrollable so the main window never requires a taller-than-screen
        # minimum size on Windows.
        right.setMinimumWidth(300)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QScrollArea.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll.setWidget(right)
        split.addWidget(right_scroll)

        split.setSizes([280, 850, 350])
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 1)

        # menu
        menu = self.menuBar()
        filem = menu.addMenu("File")
        a = QAction("Open Folder", self); a.triggered.connect(self.choose_folder); filem.addAction(a)
        a = QAction("Add Files", self); a.triggered.connect(self.add_files); filem.addAction(a)
        filem.addSeparator()
        a = QAction("Exit", self); a.triggered.connect(self.close); filem.addAction(a)

        tools = menu.addMenu("Tools")
        preview_action = QAction("Update Preview", self)
        preview_action.setShortcut("Ctrl+R")
        preview_action.triggered.connect(self.update_preview)
        tools.addAction(preview_action)
        tools.addSeparator()
        a = QAction("Undo Last Batch", self); a.triggered.connect(self.undo_last); tools.addAction(a)
        a = QAction("Clear Methods", self); a.triggered.connect(self.clear_methods); tools.addAction(a)

        self.setStatusBar(QStatusBar())
        self.refresh_method_list()

    def apply_theme(self):
        self.setStyleSheet("""
        QWidget { background:#081018; color:#dbeafe; font-size:13px; }
        QMainWindow { background:#060b11; }
        QMenuBar { background:#0a1722; color:#cdefff; padding:4px; }
        QMenuBar::item:selected, QMenu::item:selected { background:#0f617e; }
        QMenu { background:#0b1720; border:1px solid #1d5064; }
        QLineEdit, QComboBox, QSpinBox, QListWidget, QTableWidget, QTextEdit {
            background:#0a141d; color:#dcefff; border:1px solid #1c5064;
            border-radius:5px; padding:6px;
        }
        QPushButton {
            background:#0b1d28; color:#cdefff; border:1px solid #1e6178;
            border-radius:5px; padding:8px 12px;
        }
        QPushButton:hover { background:#103b4d; border-color:#29c5f6; }
        QPushButton#primary {
            background:#087ea3; border:1px solid #4edcff; color:white;
            font-weight:bold; padding:12px;
        }
        QPushButton#preview {
            background:#0b3544; border:1px solid #28b8df; color:#bfefff;
            font-weight:bold;
        }
        QPushButton#primary:hover { background:#0a9bc8; }
        QLabel#title { color:#33d6ff; font-size:20px; letter-spacing:1px; }
        QGroupBox {
            border:1px solid #1b4a5d; border-radius:6px; margin-top:10px;
            padding-top:8px; font-weight:bold; color:#6fddff;
        }
        QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; }
        QListWidget::item { padding:8px; border-bottom:1px solid #122b38; }
        QListWidget::item:selected { background:#125b74; }
        QTableWidget { gridline-color:#14313e; }
        QTableWidget::item:selected { background:#125b74; }
        QHeaderView::section { background:#0e2430; color:#8de7ff; padding:7px; border:0; }
        QProgressBar { border:1px solid #1c5064; background:#09131b; text-align:center; }
        QProgressBar::chunk { background:#11a8d4; }
        QCheckBox { spacing:6px; }
        """)

    # ----- file loading -----

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.load_folder(Path(folder))

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select Files")
        if files:
            self.files = [Path(x) for x in files]
            self.folder = self.files[0].parent if self.files else None
            self.folder_edit.setText(str(self.folder) if self.folder else "")
            self.update_preview()

    def load_folder(self, folder):
        if not folder.exists():
            return
        self.folder = folder
        self.folder_edit.setText(str(folder))
        self.scan_folder()
        self.statusBar().showMessage(f"Loaded {len(self.files)} files")

    def scan_folder(self):
        if not self.folder:
            return
        pattern = "**/*" if self.recursive.isChecked() else "*"
        items = []
        try:
            for p in self.folder.glob(pattern):
                if p.is_file():
                    if not self.hidden.isChecked() and p.name.startswith("."):
                        continue
                    items.append(p)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Could not scan folder:\n{e}")
            return
        # Stable alphabetical order determines sequence numbers.
        self.files = sorted(items, key=lambda p: str(p).lower())
        self.update_preview()

    def refresh_folder(self):
        if self.folder:
            self.scan_folder()

    # ----- methods -----

    def add_method(self):
        kinds = [
            "Prefix / Suffix", "Replace", "Regex Replace", "Change Case",
            "Trim", "Sequential Name", "Number Only", "Numbering", "Remove Characters", "Extension",
            "New Name", "Sanitize"
        ]
        menu = QMenu(self)
        for kind in kinds:
            a = menu.addAction(kind)
            a.triggered.connect(lambda checked=False, k=kind: self.insert_method(k))
        menu.exec(self.sender().mapToGlobal(self.sender().rect().bottomLeft()))

    def insert_method(self, kind):
        defaults = {
            "Prefix / Suffix": {"prefix":"","suffix":""},
            "Replace": {"find":"","replace":"","case_sensitive":False},
            "Regex Replace": {"pattern":"","replace":"","case_sensitive":False},
            "Change Case": {"mode":"lower"},
            "Trim": {"chars":"","side":"both"},
            "Sequential Name": {"base":"Fanu","start":1,"step":1,"width":0,"separator":"","position":"after"},
            "Number Only": {"start":1,"width":1},
            "Numbering": {"start":1,"width":3,"separator":"_","position":"prefix"},
            "Remove Characters": {"chars":""},
            "Extension": {"extension":""},
            "New Name": {"pattern":"{num3}_{name}"},
            "Sanitize": {"replacement":"_"},
        }
        m = Method(kind, defaults[kind])
        row = self.method_list.currentRow() + 1
        self.methods.insert(max(0,row), m)
        self.refresh_method_list()
        self.method_list.setCurrentRow(max(0,row))
        self.statusBar().showMessage("Method added — click UPDATE PREVIEW.")

    def remove_method(self):
        row = self.method_list.currentRow()
        if 0 <= row < len(self.methods):
            self.methods.pop(row)
            self.refresh_method_list()
            self.editor.set_method(Method())
            self.statusBar().showMessage("Method removed — click UPDATE PREVIEW.")

    def move_method(self, delta):
        row = self.method_list.currentRow()
        nr = row + delta
        if 0 <= row < len(self.methods) and 0 <= nr < len(self.methods):
            self.methods[row], self.methods[nr] = self.methods[nr], self.methods[row]
            self.refresh_method_list()
            self.method_list.setCurrentRow(nr)
            self.statusBar().showMessage("Method order changed — click UPDATE PREVIEW.")

    def clear_methods(self):
        self.methods = []
        self.refresh_method_list()
        self.editor.set_method(Method())
        self.statusBar().showMessage("Methods cleared — click UPDATE PREVIEW.")

    def refresh_method_list(self):
        self.method_list.blockSignals(True)
        self.method_list.clear()
        for m in self.methods:
            item = QListWidgetItem(m.label())
            item.setCheckState(Qt.Checked if m.enabled else Qt.Unchecked)
            self.method_list.addItem(item)
        self.method_list.blockSignals(False)
        if self.methods:
            row = min(max(self.current_method,0), len(self.methods)-1)
            self.method_list.setCurrentRow(row)
            self.editor.set_method(self.methods[row])
        else:
            self.current_method = -1

    def method_selected(self, row):
        if 0 <= row < len(self.methods):
            self.current_method = row
            self.editor.set_method(self.methods[row])

    def method_changed(self):
        row = self.method_list.currentRow()
        if 0 <= row < len(self.methods):
            self.methods[row] = self.editor.method
            self.method_list.item(row).setText(self.editor.method.label())
            self.statusBar().showMessage("Method changed — click UPDATE PREVIEW to recalculate.")

    # ----- preview -----

    def schedule_preview(self):
        return

    def filtered_files(self):
        q = self.filter_edit.text().strip().lower()
        if not q:
            return list(self.files)
        return [p for p in self.files if q in p.name.lower() or q in str(p.parent).lower()]

    def calculate_name(self, p, index, total):
        stem = p.stem
        ext = p.suffix
        for m in self.methods:
            stem = m.apply(stem, p, index, total)
        for m in self.methods:
            if m.enabled and m.kind == "Extension":
                x = apply_tags(m.data.get("extension", ""), p, index, total).strip()
                if x:
                    ext = "." + x.lstrip(".")
        if self.sanitize.isChecked():
            stem = sanitize_filename(stem)
        return stem + ext

    def update_preview(self):
        if self.preview_running:
            return
        files = self.filtered_files()
        # Snapshot methods so background calculation never touches widgets.
        methods = [Method(m.kind, dict(m.data), m.enabled) for m in self.methods]
        sanitize = self.sanitize.isChecked()
        self.preview_running = True
        self.preview_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.statusBar().showMessage(f"Previewing {len(files)} file(s) in background…")

        self.preview_thread = QThread(self)
        self.preview_worker = PreviewWorker(files, methods, sanitize)
        self.preview_worker.moveToThread(self.preview_thread)
        self.preview_thread.started.connect(self.preview_worker.run)
        self.preview_worker.finished.connect(self.preview_finished)
        self.preview_worker.failed.connect(self.preview_failed)
        self.preview_worker.finished.connect(self.preview_thread.quit)
        self.preview_worker.failed.connect(self.preview_thread.quit)
        self.preview_thread.finished.connect(self.preview_thread.deleteLater)
        self.preview_thread.finished.connect(self.preview_worker.deleteLater)
        self.preview_thread.finished.connect(self.preview_cleanup)
        self.preview_thread.start()

    def preview_finished(self, result):
        rows = result["rows"]
        self.preview_model.set_rows(rows)
        self.stat_files.setText(f'{result["files"]} files')
        self.stat_changes.setText(f'{result["changes"]} changes')
        self.stat_conflicts.setText(f'{result["conflicts"]} conflicts')
        self.statusBar().showMessage(
            f'Preview updated: {result["files"]} file(s), {result["changes"]} change(s), {result["conflicts"]} conflict(s)'
        )

    def preview_failed(self, message):
        self.preview_model.set_rows([])
        self.stat_files.setText("0 files")
        self.stat_changes.setText("0 changes")
        self.stat_conflicts.setText("0 conflicts")
        self.statusBar().showMessage("Preview failed")
        QMessageBox.warning(self, APP_NAME, f"Preview could not be generated:\n{message}")

    def preview_cleanup(self):
        self.preview_running = False
        self.progress.setVisible(False)
        self.progress.setRange(0, 100)
        self.preview_btn.setEnabled(True)
        self.preview_worker = None
        self.preview_thread = None

    def selected_paths(self):
        files = self.filtered_files()
        checked = [i for i, row in enumerate(self.preview_model.rows) if row.get("checked")]
        if checked:
            return [files[r] for r in checked if 0 <= r < len(files)]
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        return [files[r] for r in rows if 0 <= r < len(files)]

    def select_all(self):
        self.preview_model.set_all_checked(True)

    def clear_selection(self):
        self.preview_model.set_all_checked(False)

    # ----- batch operations -----

    def perform_batch(self):
        paths = self.selected_paths()
        if not paths:
            QMessageBox.information(self, APP_NAME, "Select at least one file.")
            return

        total = len(paths)
        operations = []
        used = set()

        for i, p in enumerate(paths, 1):
            newname = self.calculate_name(p, i, total)
            target = p.with_name(newname)
            if target == p:
                continue

            if str(target).lower() in used:
                if self.collision.currentText() == "Auto-number conflicts":
                    target = unique_name(target, used)
                elif self.collision.currentText() == "Skip conflicts":
                    continue
                else:
                    QMessageBox.warning(self, APP_NAME, f"Name conflict:\n{target.name}")
                    return

            if target.exists() and target.resolve() != p.resolve():
                if self.collision.currentText() == "Auto-number conflicts":
                    target = unique_name(target, used)
                elif self.collision.currentText() == "Skip conflicts":
                    continue
                else:
                    QMessageBox.warning(self, APP_NAME, f"Target already exists:\n{target}")
                    return

            used.add(str(target).lower())
            operations.append((p, target))

        if not operations:
            QMessageBox.information(self, APP_NAME, "There are no changes to perform.")
            return

        mode = self.mode.currentText()
        preview = "\n".join(f"{a.name}  →  {b.name}" for a,b in operations[:20])
        if len(operations) > 20:
            preview += f"\n... and {len(operations)-20} more"

        ans = QMessageBox.question(
            self, f"{APP_NAME} — Confirm {mode}",
            f"{len(operations)} operation(s) will be performed.\n\n{preview}\n\nContinue?"
        )
        if ans != QMessageBox.Yes:
            return

        self.progress.setVisible(True)
        self.progress.setMaximum(len(operations))
        self.progress.setValue(0)
        completed = []

        try:
            for i, (src, dst) in enumerate(operations, 1):
                if mode == "Rename":
                    src.rename(dst)
                    completed.append((src, dst, "rename"))
                elif mode == "Copy":
                    shutil.copy2(src, dst)
                    completed.append((src, dst, "copy"))
                else:
                    shutil.move(str(src), str(dst))
                    completed.append((src, dst, "move"))
                self.progress.setValue(i)
                QApplication.processEvents()
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Batch stopped:\n{e}")
        else:
            self.history.append(completed)
            QMessageBox.information(self, APP_NAME, f"{len(completed)} operation(s) completed.")
        finally:
            self.progress.setVisible(False)
            self.scan_folder()

    def undo_last(self):
        if not self.history:
            QMessageBox.information(self, APP_NAME, "Nothing to undo.")
            return
        batch = self.history.pop()
        done = 0
        errors = []
        for src, dst, mode in reversed(batch):
            try:
                if mode == "rename":
                    if dst.exists():
                        dst.rename(src)
                elif mode == "move":
                    if dst.exists():
                        shutil.move(str(dst), str(src))
                elif mode == "copy":
                    if dst.exists():
                        dst.unlink()
                done += 1
            except Exception as e:
                errors.append(f"{dst.name}: {e}")
        self.scan_folder()
        msg = f"Undid {done} operation(s)."
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors[:10])
        QMessageBox.information(self, APP_NAME, msg)

    # ----- presets -----

    def save_preset(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Preset", "", "JASS Renamer Preset (*.json)")
        if not path:
            return
        data = {
            "version": VERSION,
            "methods": [{"kind":m.kind, "data":m.data, "enabled":m.enabled} for m in self.methods],
            "recursive": self.recursive.isChecked(),
            "files_only": self.files_only.isChecked(),
            "sanitize": self.sanitize.isChecked(),
            "mode": self.mode.currentText(),
            "collision": self.collision.currentText(),
        }
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self.statusBar().showMessage(f"Preset saved: {path}")

    def load_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Preset", "", "JASS Renamer Preset (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.methods = [Method(x["kind"], x.get("data",{}), x.get("enabled",True)) for x in data.get("methods",[])]
            self.recursive.setChecked(data.get("recursive", False))
            self.files_only.setChecked(data.get("files_only", True))
            self.sanitize.setChecked(data.get("sanitize", True))
            if data.get("mode") in [self.mode.itemText(i) for i in range(self.mode.count())]:
                self.mode.setCurrentText(data["mode"])
            if data.get("collision") in [self.collision.itemText(i) for i in range(self.collision.count())]:
                self.collision.setCurrentText(data["collision"])
            self.refresh_method_list()
            self.update_preview()
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Could not load preset:\n{e}")

    # ----- drag/drop -----


    def closeEvent(self, event):
        if self.preview_thread and self.preview_thread.isRunning():
            self.preview_thread.quit()
            self.preview_thread.wait(1500)
        event.accept()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        paths = [Path(u.toLocalFile()) for u in urls if u.isLocalFile()]
        dirs = [p for p in paths if p.is_dir()]
        files = [p for p in paths if p.is_file()]
        if dirs:
            self.load_folder(dirs[0])
        elif files:
            self.files = files
            self.folder = files[0].parent
            self.folder_edit.setText(str(self.folder))
            self.update_preview()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    win = RenamerWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

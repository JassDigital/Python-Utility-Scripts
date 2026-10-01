import sys
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QFileDialog, QMessageBox,
    QPlainTextEdit, QSplitter, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QComboBox, QCheckBox, QTabWidget
)

APP_NAME = "JASS JSON Explorer"
APP_VERSION = "1.0"

STYLE = """
QWidget {
    background:#11151b; color:#e7edf5;
    font-family:"Segoe UI"; font-size:10pt;
}
QMainWindow { background:#0d1117; }
QLabel#Title { font-size:22pt; font-weight:700; color:#ffffff; }
QLabel#SubTitle { color:#8d99a8; }
QLineEdit, QComboBox, QPlainTextEdit, QTreeWidget {
    background:#171c23; border:1px solid #303947;
    border-radius:7px; color:#e7edf5;
}
QLineEdit, QComboBox { padding:7px; }
QPlainTextEdit { padding:9px; font-family:"Cascadia Mono","Consolas",monospace; }
QComboBox QAbstractItemView {
    background:#171c23; color:#e7edf5;
    selection-background-color:#263d59;
}
QPushButton {
    background:#202936; border:1px solid #354254;
    border-radius:7px; padding:8px 13px;
}
QPushButton:hover { background:#293545; }
QPushButton#Primary {
    background:#245b8f; border-color:#347ab9; font-weight:700;
}
QTreeWidget {
    alternate-background-color:#141a21;
}
QTreeWidget::item { padding:4px; }
QTreeWidget::item:selected { background:#263d59; }
QHeaderView::section {
    background:#1c232d; color:#aeb9c7; padding:7px; border:0;
}
QTabWidget::pane { border:1px solid #29313d; border-radius:7px; }
QTabBar::tab {
    background:#171c23; padding:8px 15px;
    border:1px solid #29313d; margin-right:2px;
}
QTabBar::tab:selected { background:#263d59; }
"""

def value_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return f"object ({len(value)})"
    if isinstance(value, list):
        return f"array ({len(value)})"
    if isinstance(value, (int, float)):
        return "number"
    return "string"

def preview(value, limit=180):
    if isinstance(value, (dict, list)):
        s = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        s = str(value)
    return s if len(s) <= limit else s[:limit-1] + "…"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1450, 850)
        self.setMinimumSize(1050, 650)
        self.setStyleSheet(STYLE)

        self.data = None
        self.file_path = None
        self.dirty = False
        self.matches = []
        self.match_index = -1

        self.build_ui()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20,18,20,15)
        root.setSpacing(10)

        title = QLabel(APP_NAME)
        title.setObjectName("Title")
        sub = QLabel("Open, inspect, search, format, validate and edit JSON files locally.")
        sub.setObjectName("SubTitle")
        root.addWidget(title)
        root.addWidget(sub)

        bar = QHBoxLayout()

        open_btn = QPushButton("Open JSON")
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(self.open_file)
        bar.addWidget(open_btn)

        new_btn = QPushButton("New")
        new_btn.clicked.connect(self.new_document)
        bar.addWidget(new_btn)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_file)
        bar.addWidget(save_btn)

        save_as_btn = QPushButton("Save As…")
        save_as_btn.clicked.connect(self.save_as)
        bar.addWidget(save_as_btn)

        format_btn = QPushButton("Format")
        format_btn.clicked.connect(self.format_json)
        bar.addWidget(format_btn)

        compact_btn = QPushButton("Compact")
        compact_btn.clicked.connect(self.compact_json)
        bar.addWidget(compact_btn)

        validate_btn = QPushButton("Validate")
        validate_btn.clicked.connect(self.validate_json)
        bar.addWidget(validate_btn)

        bar.addStretch()

        self.status = QLabel("Ready.")
        self.status.setObjectName("SubTitle")
        bar.addWidget(self.status)
        root.addLayout(bar)

        search_bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search keys and values…")
        self.search.returnPressed.connect(self.find_next)
        search_bar.addWidget(self.search, 1)

        find_btn = QPushButton("Find")
        find_btn.clicked.connect(self.find_matches)
        search_bar.addWidget(find_btn)

        next_btn = QPushButton("Next")
        next_btn.clicked.connect(self.find_next)
        search_bar.addWidget(next_btn)

        self.case_sensitive = QCheckBox("Case sensitive")
        search_bar.addWidget(self.case_sensitive)

        self.search_count = QLabel("")
        self.search_count.setObjectName("SubTitle")
        search_bar.addWidget(self.search_count)
        root.addLayout(search_bar)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0,0,0,0)
        ll.addWidget(QLabel("JSON Structure"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Key / Index", "Type", "Value"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tree.itemClicked.connect(self.tree_selected)
        ll.addWidget(self.tree)
        splitter.addWidget(left)

        right = QTabWidget()

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("JSON document…")
        self.editor.textChanged.connect(self.editor_changed)
        right.addTab(self.editor, "JSON")

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        right.addTab(self.detail, "Selected Value")

        splitter.addWidget(right)
        splitter.setSizes([520,900])
        root.addWidget(splitter,1)

        footer = QHBoxLayout()
        self.info = QLabel("No document loaded.")
        self.info.setObjectName("SubTitle")
        footer.addWidget(self.info,1)

        copy_btn = QPushButton("Copy Selected Value")
        copy_btn.clicked.connect(self.copy_selected)
        footer.addWidget(copy_btn)

        root.addLayout(footer)

    def set_status(self, text):
        self.status.setText(text)

    def editor_changed(self):
        self.dirty = True
        self.info.setText("Unsaved changes")

    def maybe_save(self):
        if not self.dirty:
            return True
        reply = QMessageBox.question(
            self, "Unsaved Changes",
            "The JSON document has unsaved changes. Save them first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
        )
        if reply == QMessageBox.Save:
            return self.save_file()
        return reply == QMessageBox.Discard

    def new_document(self):
        if not self.maybe_save():
            return
        self.file_path = None
        self.data = {}
        self.editor.blockSignals(True)
        self.editor.setPlainText("{}")
        self.editor.blockSignals(False)
        self.dirty = False
        self.rebuild_tree()
        self.info.setText("New JSON document")
        self.set_status("New document.")

    def open_file(self):
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open JSON File", "", "JSON Files (*.json);;All Files (*.*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
            data = json.loads(text)
        except Exception as e:
            QMessageBox.critical(self, "Open JSON Error", str(e))
            return
        self.file_path = Path(path)
        self.data = data
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self.dirty = False
        self.rebuild_tree()
        self.update_info()
        self.set_status(f"Opened: {self.file_path.name}")

    def parse_editor(self):
        try:
            return json.loads(self.editor.toPlainText())
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON error at line {e.lineno}, column {e.colno}: {e.msg}")

    def save_file(self):
        try:
            data = self.parse_editor()
        except Exception as e:
            QMessageBox.warning(self, "Invalid JSON", str(e))
            return False

        if not self.file_path:
            return self.save_as()

        try:
            self.file_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8"
            )
            self.data = data
            self.dirty = False
            self.rebuild_tree()
            self.update_info()
            self.set_status(f"Saved: {self.file_path.name}")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))
            return False

    def save_as(self):
        try:
            data = self.parse_editor()
        except Exception as e:
            QMessageBox.warning(self, "Invalid JSON", str(e))
            return False

        path, _ = QFileDialog.getSaveFileName(
            self, "Save JSON File", "document.json", "JSON Files (*.json)"
        )
        if not path:
            return False
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            self.file_path = Path(path)
            self.file_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8"
            )
            self.data = data
            self.dirty = False
            self.rebuild_tree()
            self.update_info()
            self.set_status(f"Saved: {self.file_path.name}")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))
            return False

    def format_json(self):
        try:
            data = self.parse_editor()
            self.editor.blockSignals(True)
            self.editor.setPlainText(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            self.editor.blockSignals(False)
            self.dirty = True
            self.rebuild_tree()
            self.set_status("JSON formatted.")
        except Exception as e:
            QMessageBox.warning(self, "Format Error", str(e))

    def compact_json(self):
        try:
            data = self.parse_editor()
            self.editor.blockSignals(True)
            self.editor.setPlainText(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
            self.editor.blockSignals(False)
            self.dirty = True
            self.rebuild_tree()
            self.set_status("JSON compacted.")
        except Exception as e:
            QMessageBox.warning(self, "Compact Error", str(e))

    def validate_json(self):
        try:
            data = self.parse_editor()
            self.data = data
            self.rebuild_tree()
            self.set_status("Valid JSON ✓")
            QMessageBox.information(self, "JSON Validation", "The document is valid JSON.")
        except Exception as e:
            self.set_status("Invalid JSON")
            QMessageBox.warning(self, "JSON Validation", str(e))

    def rebuild_tree(self):
        self.tree.clear()
        try:
            data = self.parse_editor()
        except Exception:
            return
        root = QTreeWidgetItem(["$","object" if isinstance(data,dict) else "array", preview(data)])
        self.tree.addTopLevelItem(root)
        root.setExpanded(True)
        self.add_children(root, data)

    def add_children(self, parent, value):
        if isinstance(value, dict):
            for key, child in value.items():
                item = QTreeWidgetItem([str(key), value_type(child), preview(child)])
                parent.addChild(item)
                if isinstance(child, (dict,list)):
                    self.add_children(item, child)
                    item.setExpanded(True)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                item = QTreeWidgetItem([f"[{i}]", value_type(child), preview(child)])
                parent.addChild(item)
                if isinstance(child, (dict,list)):
                    self.add_children(item, child)
                    item.setExpanded(True)

    def tree_selected(self, item, column):
        self.detail.setPlainText(item.text(2))
        self.status.setText(f"Selected: {item.text(0)}")

    def copy_selected(self):
        item = self.tree.currentItem()
        if not item:
            return
        QApplication.clipboard().setText(item.text(2))
        self.set_status("Selected value copied.")

    def update_info(self):
        if self.file_path:
            self.info.setText(f"{self.file_path} • {len(self.editor.toPlainText()):,} characters")
        else:
            self.info.setText(f"Unsaved document • {len(self.editor.toPlainText()):,} characters")

    def find_matches(self):
        query = self.search.text()
        self.matches = []
        self.match_index = -1
        if not query:
            self.search_count.setText("")
            return
        flags = 0 if self.case_sensitive.isChecked() else 0
        text = self.editor.toPlainText()
        hay = text if self.case_sensitive.isChecked() else text.lower()
        needle = query if self.case_sensitive.isChecked() else query.lower()
        start = 0
        while True:
            pos = hay.find(needle, start)
            if pos < 0:
                break
            self.matches.append(pos)
            start = pos + max(1, len(needle))
        self.search_count.setText(f"{len(self.matches)} match(es)")
        if self.matches:
            self.find_next()
        else:
            self.set_status("No matches found.")

    def find_next(self):
        if not self.matches:
            self.find_matches()
            return
        if not self.matches:
            return
        self.match_index = (self.match_index + 1) % len(self.matches)
        pos = self.matches[self.match_index]
        cursor = self.editor.textCursor()
        cursor.setPosition(pos)
        cursor.setPosition(pos + len(self.search.text()), cursor.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        self.set_status(f"Match {self.match_index + 1} of {len(self.matches)}")

    def closeEvent(self, event):
        if self.maybe_save():
            event.accept()
        else:
            event.ignore()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

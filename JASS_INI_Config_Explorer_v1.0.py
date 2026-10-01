import configparser
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTreeWidget, QTreeWidgetItem,
    QLineEdit, QTextEdit, QSplitter, QMessageBox, QCheckBox,
    QInputDialog
)

APP_NAME = "JASS INI Config Explorer"
VERSION = "1.0"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1350, 820)
        self.path = None
        self.parser = configparser.ConfigParser(
            interpolation=None,
            strict=False,
            allow_no_value=True
        )
        self.build_ui()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        header = QHBoxLayout()
        title = QLabel("JASS INI Config Explorer")
        title.setObjectName("Title")
        subtitle = QLabel("Inspect • search • edit configuration files")
        subtitle.setObjectName("Muted")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch()

        open_btn = QPushButton("Open INI")
        open_btn.clicked.connect(self.open_ini)
        header.addWidget(open_btn)

        new_btn = QPushButton("New INI")
        new_btn.clicked.connect(self.new_ini)
        header.addWidget(new_btn)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_ini)
        header.addWidget(save_btn)

        save_as_btn = QPushButton("Save As")
        save_as_btn.clicked.connect(self.save_as)
        header.addWidget(save_as_btn)

        layout.addLayout(header)

        self.file_label = QLabel("No configuration file opened")
        self.file_label.setObjectName("Muted")
        layout.addWidget(self.file_label)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search section, key or value...")
        self.search.textChanged.connect(self.filter_tree)
        search_row.addWidget(self.search)

        self.case_sensitive = QCheckBox("Case sensitive")
        self.case_sensitive.toggled.connect(self.filter_tree)
        search_row.addWidget(self.case_sensitive)
        left_layout.addLayout(search_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Section / Key", "Value"])
        self.tree.itemClicked.connect(self.select_item)
        left_layout.addWidget(self.tree, 1)

        add_section = QPushButton("Add Section")
        add_section.clicked.connect(self.add_section)
        left_layout.addWidget(add_section)

        add_key = QPushButton("Add Key")
        add_key.clicked.connect(self.add_key)
        left_layout.addWidget(add_key)

        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_layout.addWidget(QLabel("Selected Entry"))

        self.section_edit = QLineEdit()
        self.section_edit.setPlaceholderText("Section")
        right_layout.addWidget(self.section_edit)

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("Key")
        right_layout.addWidget(self.key_edit)

        self.value_edit = QTextEdit()
        self.value_edit.setPlaceholderText("Value")
        right_layout.addWidget(self.value_edit, 2)

        button_row = QHBoxLayout()

        apply_btn = QPushButton("Apply Change")
        apply_btn.clicked.connect(self.apply_change)
        button_row.addWidget(apply_btn)

        delete_btn = QPushButton("Delete Key")
        delete_btn.clicked.connect(self.delete_key)
        button_row.addWidget(delete_btn)

        format_btn = QPushButton("Normalize")
        format_btn.clicked.connect(self.normalize)
        button_row.addWidget(format_btn)

        copy_btn = QPushButton("Copy Value")
        copy_btn.clicked.connect(self.copy_value)
        button_row.addWidget(copy_btn)

        button_row.addStretch()
        right_layout.addLayout(button_row)

        right_layout.addWidget(QLabel("Raw INI"))

        self.raw = QTextEdit()
        self.raw.setPlaceholderText("Raw configuration text...")
        right_layout.addWidget(self.raw, 3)

        raw_row = QHBoxLayout()
        parse_btn = QPushButton("Parse Raw")
        parse_btn.clicked.connect(self.parse_raw)
        raw_row.addWidget(parse_btn)

        copy_raw = QPushButton("Copy Raw")
        copy_raw.clicked.connect(self.copy_raw)
        raw_row.addWidget(copy_raw)
        raw_row.addStretch()
        right_layout.addLayout(raw_row)

        splitter.addWidget(right)
        splitter.setSizes([600, 750])
        layout.addWidget(splitter, 1)

        self.status = QLabel("Ready")
        self.status.setObjectName("Muted")
        layout.addWidget(self.status)

        self.setStyleSheet("""
            QWidget {
                background:#151922;
                color:#e8edf5;
                font-size:10.5pt;
            }
            QLabel#Title {
                font-size:20pt;
                font-weight:700;
            }
            QLabel#Muted {
                color:#8e9aaa;
            }
            QPushButton,QLineEdit,QCheckBox {
                background:#222938;
                border:1px solid #3a4354;
                border-radius:6px;
                padding:7px 10px;
            }
            QPushButton:hover {
                background:#2b3445;
            }
            QLineEdit,QTextEdit {
                background:#10141c;
                border:1px solid #303746;
                border-radius:6px;
            }
            QTreeWidget {
                background:#10141c;
                alternate-background-color:#171d28;
                border:1px solid #303746;
            }
            QTreeWidget::item:selected {
                background:#294766;
            }
            QHeaderView::section {
                background:#222938;
                padding:7px;
                border:0;
                border-right:1px solid #303746;
            }
        """)

    def read_file(self, path):
        text = Path(path).read_text(encoding="utf-8-sig")
        self.parser = configparser.ConfigParser(
            interpolation=None,
            strict=False,
            allow_no_value=True
        )
        self.parser.optionxform = str
        self.parser.read_string(text)
        self.raw.setPlainText(text)
        self.path = path
        self.file_label.setText(str(Path(path).resolve()))
        self.refresh_tree()
        self.status.setText("Configuration loaded")

    def open_ini(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open INI Configuration",
            "",
            "INI/Config Files (*.ini *.cfg *.conf *.config);;All Files (*.*)"
        )
        if not path:
            return
        try:
            self.read_file(path)
        except Exception as e:
            QMessageBox.critical(self, "Open configuration", str(e))

    def new_ini(self):
        self.path = None
        self.parser = configparser.ConfigParser(
            interpolation=None, strict=False, allow_no_value=True
        )
        self.parser.optionxform = str
        self.parser.add_section("Settings")
        self.parser.set("Settings", "example", "value")
        self.refresh_raw()
        self.refresh_tree()
        self.file_label.setText("New configuration")
        self.status.setText("New INI configuration created")

    def refresh_tree(self):
        self.tree.clear()
        for section in self.parser.sections():
            sec_item = QTreeWidgetItem(self.tree, [f"[{section}]", ""])
            sec_item.setData(0, Qt.UserRole, ("section", section))
            for key, value in self.parser.items(section, raw=True):
                display = "" if value is None else str(value)
                item = QTreeWidgetItem(sec_item, [key, display])
                item.setData(0, Qt.UserRole, ("key", section, key))
        self.tree.expandAll()
        self.filter_tree()

    def filter_tree(self):
        term = self.search.text()
        if not term:
            self.show_all(self.tree.invisibleRootItem())
            return
        if not self.case_sensitive.isChecked():
            term = term.lower()
        self.filter_item(self.tree.invisibleRootItem(), term)

    def filter_item(self, parent, term):
        for i in range(parent.childCount()):
            item = parent.child(i)
            hay = " ".join(item.text(c) for c in range(2))
            if not self.case_sensitive.isChecked():
                hay = hay.lower()
            own_match = term in hay
            child_match = self.filter_item(item, term)
            item.setHidden(not (own_match or child_match))
        return any(
            not parent.child(i).isHidden()
            for i in range(parent.childCount())
        )

    def show_all(self, parent):
        for i in range(parent.childCount()):
            item = parent.child(i)
            item.setHidden(False)
            self.show_all(item)

    def select_item(self, item, _column):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        if data[0] == "section":
            self.section_edit.setText(data[1])
            self.key_edit.clear()
            self.value_edit.clear()
            return
        _, section, key = data
        self.section_edit.setText(section)
        self.key_edit.setText(key)
        value = self.parser.get(section, key, raw=True, fallback="")
        self.value_edit.setPlainText("" if value is None else str(value))

    def add_section(self):
        name, ok = QInputDialog.getText(self, "Add Section", "Section name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if self.parser.has_section(name):
            QMessageBox.warning(self, "Add Section", "That section already exists.")
            return
        self.parser.add_section(name)
        self.refresh_raw()
        self.refresh_tree()
        self.status.setText(f"Added section [{name}]")

    def add_key(self):
        section = self.section_edit.text().strip()
        if not section:
            QMessageBox.warning(self, "Add Key", "Enter a section first.")
            return
        if not self.parser.has_section(section):
            self.parser.add_section(section)

        key, ok = QInputDialog.getText(self, "Add Key", "Key name:")
        if not ok or not key.strip():
            return

        value, ok = QInputDialog.getText(self, "Add Key", "Value:")
        if not ok:
            return

        self.parser.set(section, key.strip(), value)
        self.refresh_raw()
        self.refresh_tree()
        self.status.setText(f"Added {key.strip()}")

    def apply_change(self):
        section = self.section_edit.text().strip()
        key = self.key_edit.text().strip()
        if not section or not key:
            QMessageBox.warning(self, "Apply Change", "Section and key are required.")
            return
        if not self.parser.has_section(section):
            self.parser.add_section(section)
        self.parser.set(section, key, self.value_edit.toPlainText())
        self.refresh_raw()
        self.refresh_tree()
        self.status.setText(f"Updated [{section}] {key}")

    def delete_key(self):
        section = self.section_edit.text().strip()
        key = self.key_edit.text().strip()
        if not section or not key:
            return
        if not self.parser.has_section(section) or not self.parser.has_option(section, key):
            return
        reply = QMessageBox.question(
            self, "Delete Key",
            f"Delete [{section}] {key}?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self.parser.remove_option(section, key)
        self.refresh_raw()
        self.refresh_tree()
        self.status.setText(f"Deleted {key}")

    def refresh_raw(self):
        import io
        buf = io.StringIO()
        self.parser.write(buf, space_around_delimiters=True)
        self.raw.setPlainText(buf.getvalue())

    def parse_raw(self):
        try:
            parser = configparser.ConfigParser(
                interpolation=None, strict=False, allow_no_value=True
            )
            parser.optionxform = str
            parser.read_string(self.raw.toPlainText())
            self.parser = parser
            self.refresh_tree()
            self.status.setText("Raw INI parsed successfully")
        except Exception as e:
            QMessageBox.critical(self, "Parse INI", str(e))

    def normalize(self):
        self.refresh_raw()
        self.status.setText("INI normalized")

    def save_ini(self):
        if not self.path:
            self.save_as()
            return
        try:
            self.refresh_raw()
            Path(self.path).write_text(
                self.raw.toPlainText(), encoding="utf-8"
            )
            self.file_label.setText(str(Path(self.path).resolve()))
            self.status.setText("Configuration saved")
        except Exception as e:
            QMessageBox.critical(self, "Save", str(e))

    def save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Configuration",
            "",
            "INI Files (*.ini);;Config Files (*.cfg *.conf *.config);;All Files (*.*)"
        )
        if not path:
            return
        self.path = path
        self.save_ini()

    def copy_value(self):
        QApplication.clipboard().setText(self.value_edit.toPlainText())
        self.status.setText("Value copied")

    def copy_raw(self):
        QApplication.clipboard().setText(self.raw.toPlainText())
        self.status.setText("Raw INI copied")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

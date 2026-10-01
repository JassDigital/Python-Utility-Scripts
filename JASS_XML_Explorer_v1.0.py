import os
import sys
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QLineEdit, QTreeWidget,
    QTreeWidgetItem, QTextEdit, QSplitter, QMessageBox, QCheckBox
)

APP_NAME = "JASS XML Explorer"
VERSION = "1.0"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1400, 850)
        self.root = None
        self.path = None
        self.build_ui()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        header = QHBoxLayout()
        title = QLabel("JASS XML Explorer")
        title.setObjectName("Title")
        subtitle = QLabel("Inspect • search • format XML documents")
        subtitle.setObjectName("Muted")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch()

        open_btn = QPushButton("Open XML")
        open_btn.clicked.connect(self.open_xml)
        header.addWidget(open_btn)

        new_btn = QPushButton("New XML")
        new_btn.clicked.connect(self.new_xml)
        header.addWidget(new_btn)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_xml)
        header.addWidget(save_btn)

        layout.addLayout(header)

        self.file_label = QLabel("No XML document opened")
        self.file_label.setObjectName("Muted")
        layout.addWidget(self.file_label)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        search_bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search element, attribute or text...")
        self.search.textChanged.connect(self.search_tree)
        search_bar.addWidget(self.search)

        self.case_box = QCheckBox("Case sensitive")
        search_bar.addWidget(self.case_box)
        left_layout.addLayout(search_bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["XML Structure", "Value"])
        self.tree.itemClicked.connect(self.show_node)
        left_layout.addWidget(self.tree, 1)

        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_layout.addWidget(QLabel("Selected Node"))

        self.node_info = QTextEdit()
        self.node_info.setReadOnly(True)
        right_layout.addWidget(self.node_info, 1)

        self.xml_editor = QTextEdit()
        self.xml_editor.setPlaceholderText("XML source...")
        right_layout.addWidget(QLabel("XML Source"))
        right_layout.addWidget(self.xml_editor, 2)

        buttons = QHBoxLayout()
        format_btn = QPushButton("Format XML")
        format_btn.clicked.connect(self.format_xml)
        buttons.addWidget(format_btn)

        validate_btn = QPushButton("Validate")
        validate_btn.clicked.connect(self.validate_xml)
        buttons.addWidget(validate_btn)

        copy_btn = QPushButton("Copy XML")
        copy_btn.clicked.connect(self.copy_xml)
        buttons.addWidget(copy_btn)

        buttons.addStretch()
        right_layout.addLayout(buttons)

        splitter.addWidget(right)
        splitter.setSizes([600, 800])
        layout.addWidget(splitter, 1)

        self.status = QLabel("Ready")
        self.status.setObjectName("Muted")
        layout.addWidget(self.status)

        self.setStyleSheet("""
            QWidget { background:#151922; color:#e8edf5; font-size:10.5pt; }
            QLabel#Title { font-size:20pt; font-weight:700; }
            QLabel#Muted { color:#8e9aaa; }
            QPushButton,QLineEdit,QCheckBox {
                background:#222938; border:1px solid #3a4354;
                border-radius:6px; padding:7px 10px;
            }
            QPushButton:hover { background:#2b3445; }
            QLineEdit,QTextEdit {
                background:#10141c; border:1px solid #303746;
                border-radius:6px;
            }
            QTreeWidget {
                background:#10141c; alternate-background-color:#171d28;
                border:1px solid #303746;
            }
            QTreeWidget::item:selected { background:#294766; }
            QHeaderView::section {
                background:#222938; padding:7px; border:0;
                border-right:1px solid #303746;
            }
        """)

    def open_xml(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open XML", "", "XML Files (*.xml *.xsd *.svg *.rss *.atom);;All Files (*.*)"
        )
        if path:
            try:
                text = Path(path).read_text(encoding="utf-8")
                ET.fromstring(text)
                self.path = path
                self.xml_editor.setPlainText(text)
                self.load_tree(text)
                self.file_label.setText(str(Path(path).resolve()))
                self.status.setText("XML loaded successfully")
            except UnicodeDecodeError:
                QMessageBox.critical(self, "Open XML", "The file is not valid UTF-8.")
            except ET.ParseError as e:
                QMessageBox.critical(self, "Invalid XML", str(e))
            except Exception as e:
                QMessageBox.critical(self, "Open XML", str(e))

    def new_xml(self):
        self.path = None
        sample = '<?xml version="1.0" encoding="UTF-8"?>\n<root>\n    <item id="1">Example</item>\n</root>\n'
        self.xml_editor.setPlainText(sample)
        self.load_tree(sample)
        self.file_label.setText("New XML document")
        self.status.setText("New XML document created")

    def save_xml(self):
        text = self.xml_editor.toPlainText()
        try:
            ET.fromstring(text)
        except ET.ParseError as e:
            QMessageBox.critical(self, "Invalid XML", str(e))
            return

        path = self.path
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save XML", "", "XML Files (*.xml)"
            )
        if not path:
            return

        try:
            Path(path).write_text(text, encoding="utf-8")
            self.path = path
            self.file_label.setText(str(Path(path).resolve()))
            self.status.setText("XML saved")
        except Exception as e:
            QMessageBox.critical(self, "Save XML", str(e))

    def load_tree(self, text):
        self.root = ET.fromstring(text)
        self.tree.clear()
        self.add_element(self.root, self.tree.invisibleRootItem())
        self.tree.expandToDepth(1)

    def add_element(self, elem, parent):
        attrs = " ".join(f'{k}="{v}"' for k, v in elem.attrib.items())
        label = elem.tag + (f"  [{attrs}]" if attrs else "")
        value = (elem.text or "").strip()
        item = QTreeWidgetItem(parent, [label, value])
        item.setData(0, Qt.UserRole, elem)

        for child in list(elem):
            self.add_element(child, item)
        return item

    def show_node(self, item, _column):
        elem = item.data(0, Qt.UserRole)
        if elem is None:
            return

        lines = [
            f"Element: {elem.tag}",
            f"Text: {(elem.text or '').strip() or '(none)'}",
            "",
            "Attributes:"
        ]
        if elem.attrib:
            lines.extend(f"  {k} = {v}" for k, v in elem.attrib.items())
        else:
            lines.append("  (none)")

        lines.append("")
        lines.append(f"Children: {len(list(elem))}")
        self.node_info.setPlainText("\n".join(lines))

    def search_tree(self):
        term = self.search.text()
        if not term:
            self.clear_highlight(self.tree.invisibleRootItem())
            return

        if not self.case_box.isChecked():
            term = term.lower()

        self.mark_matches(self.tree.invisibleRootItem(), term)

    def mark_matches(self, parent, term):
        for i in range(parent.childCount()):
            item = parent.child(i)
            text = " ".join(item.text(c) for c in range(item.columnCount()))
            hay = text if self.case_box.isChecked() else text.lower()
            matched = term in hay
            item.setHidden(not matched)
            if matched:
                ancestor = item.parent()
                while ancestor:
                    ancestor.setHidden(False)
                    ancestor = ancestor.parent()
            self.mark_matches(item, term)

    def clear_highlight(self, parent):
        for i in range(parent.childCount()):
            item = parent.child(i)
            item.setHidden(False)
            self.clear_highlight(item)

    def format_xml(self):
        text = self.xml_editor.toPlainText()
        try:
            root = ET.fromstring(text)
            ET.indent(root, space="    ")
            declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
            formatted = declaration + ET.tostring(
                root, encoding="unicode", short_empty_elements=True
            )
            self.xml_editor.setPlainText(formatted)
            self.load_tree(formatted)
            self.status.setText("XML formatted")
        except ET.ParseError as e:
            QMessageBox.critical(self, "Invalid XML", str(e))

    def validate_xml(self):
        try:
            ET.fromstring(self.xml_editor.toPlainText())
            self.status.setText("XML is valid")
            QMessageBox.information(self, "XML Validation", "XML is well-formed.")
        except ET.ParseError as e:
            self.status.setText("XML validation failed")
            QMessageBox.warning(self, "XML Validation", str(e))

    def copy_xml(self):
        QApplication.clipboard().setText(self.xml_editor.toPlainText())
        self.status.setText("XML copied to clipboard")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

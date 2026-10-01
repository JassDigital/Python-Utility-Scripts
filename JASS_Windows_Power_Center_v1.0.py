"""
JASS Windows Power Center v1.0
A beautiful PySide6 launcher/dashboard for the JASS Windows Toolkit.

Design goals:
- Modern dark desktop dashboard
- Automatically discovers JASS Python applications in the same folder
- Categorizes tools
- Search and category filtering
- Favorites
- Recent applications
- Launch Python scripts and Windows executables
- Open application location
- Rescan toolkit
- Lightweight: PySide6 + Python standard library
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QStatusBar,
    QToolButton, QVBoxLayout, QWidget
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl


APP_NAME = "JASS Windows Power Center"
VERSION = "1.0"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "JASS" / "WindowsPowerCenter"
DATA_FILE = DATA_DIR / "power_center.json"


@dataclass
class Tool:
    name: str
    path: str
    category: str
    icon: str
    description: str
    favorite: bool = False


CATEGORY_INFO = {
    "All Tools": ("⌂", "Everything in your JASS toolkit"),
    "File & Folder": ("▣", "Organize, inspect and manage files"),
    "System": ("⚙", "Windows and system utilities"),
    "Data & Database": ("▤", "Databases, datasets and documents"),
    "Creative": ("✦", "Images, text and creative tools"),
    "Privacy & Security": ("◈", "Privacy and security utilities"),
    "Developer": ("⌘", "Developer and project tools"),
    "Android & Apps": ("▰", "Android and application utilities"),
    "Research": ("⌕", "Research and knowledge tools"),
    "Other": ("•", "Other JASS utilities"),
}

CATEGORY_ORDER = list(CATEGORY_INFO.keys())


def humanize(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"_v\d+(?:\.\d+)*.*$", "", stem, flags=re.I)
    stem = stem.replace("JASS_", "").replace("_", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or Path(filename).stem


def category_for(name: str) -> str:
    n = name.lower()

    if any(x in n for x in [
        "duplicate", "empty_folder", "file_organizer", "file_analyzer",
        "folder_intelligence", "nested_folder", "subfolder",
        "disk_space", "archive_explorer", "renamer"
    ]):
        return "File & Folder"

    if any(x in n for x in [
        "disk", "system", "process", "startup", "network", "drive",
        "windows", "service", "portable_app", "appimage"
    ]):
        return "System"

    if any(x in n for x in [
        "sqlite", "dataset", "document", "database", "data"
    ]):
        return "Data & Database"

    if any(x in n for x in [
        "image", "quote", "poster", "textlab", "gurbani", "video",
        "subtitle", "book_reader", "literature"
    ]):
        return "Creative"

    if any(x in n for x in [
        "privacy", "password", "vault", "offline_facebook"
    ]):
        return "Privacy & Security"

    if any(x in n for x in [
        "developer", "project_archaeologist", "toolbox", "python",
        "code", "git"
    ]):
        return "Developer"

    if any(x in n for x in ["android", "portable_app", "appimage"]):
        return "Android & Apps"

    if any(x in n for x in [
        "healthspan", "literature", "corpus", "research", "dataset"
    ]):
        return "Research"

    return "Other"


def description_for(name: str, category: str) -> str:
    descriptions = {
        "File & Folder": "Manage, inspect or organize files and folders.",
        "System": "Windows system and desktop utility.",
        "Data & Database": "Explore documents, databases or structured data.",
        "Creative": "Create, view or work with creative content.",
        "Privacy & Security": "Privacy, vault and security-oriented utility.",
        "Developer": "Developer and project productivity utility.",
        "Android & Apps": "Manage applications and portable software.",
        "Research": "Research, literature and knowledge utility.",
        "Other": "JASS desktop utility.",
    }
    return descriptions.get(category, "JASS desktop utility.")


def icon_for(category: str) -> str:
    return CATEGORY_INFO.get(category, CATEGORY_INFO["Other"])[0]


def load_state() -> dict:
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state: dict):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(DATA_FILE)
    except OSError:
        pass


class ToolCard(QFrame):
    def __init__(self, tool: Tool, manager):
        super().__init__()
        self.tool = tool
        self.manager = manager
        self.setObjectName("ToolCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(168)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        top = QHBoxLayout()
        icon = QLabel(tool.icon)
        icon.setObjectName("CardIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(44, 44)

        top.addWidget(icon)
        top.addStretch()

        self.star = QToolButton()
        self.star.setText("★" if tool.favorite else "☆")
        self.star.setObjectName("FavoriteButton")
        self.star.setToolTip("Remove from favorites" if tool.favorite else "Add to favorites")
        self.star.clicked.connect(self.toggle_favorite)
        top.addWidget(self.star)

        layout.addLayout(top)

        title = QLabel(tool.name)
        title.setObjectName("CardTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        desc = QLabel(tool.description)
        desc.setObjectName("CardDescription")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        bottom = QHBoxLayout()
        cat = QLabel(tool.category)
        cat.setObjectName("CardCategory")
        bottom.addWidget(cat)
        bottom.addStretch()

        launch = QPushButton("Launch")
        launch.setObjectName("LaunchButton")
        launch.clicked.connect(self.launch)
        bottom.addWidget(launch)
        layout.addLayout(bottom)

    def toggle_favorite(self):
        self.manager.toggle_favorite(self.tool.path)

    def launch(self):
        self.manager.launch_tool(self.tool)

    def mouseDoubleClickEvent(self, event):
        self.launch()
        super().mouseDoubleClickEvent(event)


class PowerCenter(QMainWindow):
    def __init__(self):
        super().__init__()

        self.state = load_state()
        self.tools: list[Tool] = []
        self.current_category = "All Tools"

        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.setMinimumSize(1050, 700)
        self.resize(1380, 850)

        self.build_ui()
        self.apply_theme()
        self.scan_tools()
        self.update_clock()

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)

    # ---------------- discovery ----------------

    def scan_tools(self):
        self.tools.clear()

        for path in sorted(BASE_DIR.iterdir(), key=lambda p: p.name.lower()):
            if not path.is_file():
                continue

            if not path.name.startswith("JASS_"):
                continue

            if path.suffix.lower() not in {".py", ".exe"}:
                continue

            # Do not make the Power Center itself a launcher card.
            if path.resolve() == Path(__file__).resolve():
                continue

            category = category_for(path.name)
            key = str(path.resolve())

            favorites = self.state.get("favorites", [])
            tool = Tool(
                name=humanize(path.name),
                path=key,
                category=category,
                icon=icon_for(category),
                description=description_for(humanize(path.name), category),
                favorite=key in favorites,
            )
            self.tools.append(tool)

        self.refresh_sidebar()
        self.refresh_cards()

    # ---------------- UI ----------------

    def build_ui(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Sidebar
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(245)

        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(18, 22, 18, 18)
        side.setSpacing(7)

        brand = QLabel("JASS")
        brand.setObjectName("Brand")
        side.addWidget(brand)

        sub = QLabel("WINDOWS POWER CENTER")
        sub.setObjectName("BrandSub")
        side.addWidget(sub)

        side.addSpacing(22)

        self.nav = QListWidget()
        self.nav.setObjectName("NavList")
        self.nav.setSpacing(4)
        self.nav.currentItemChanged.connect(self.nav_changed)
        side.addWidget(self.nav, 1)

        side.addSpacing(10)

        scan_btn = QPushButton("↻  Scan Toolkit")
        scan_btn.setObjectName("SidebarButton")
        scan_btn.clicked.connect(self.scan_tools)
        side.addWidget(scan_btn)

        about_btn = QPushButton("ⓘ  About")
        about_btn.setObjectName("SidebarButton")
        about_btn.clicked.connect(self.show_about)
        side.addWidget(about_btn)

        root_layout.addWidget(self.sidebar)

        # Main
        main = QWidget()
        main.setObjectName("Main")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(30, 24, 30, 24)
        main_layout.setSpacing(18)

        header = QHBoxLayout()

        heading_box = QVBoxLayout()
        heading_box.setSpacing(2)

        self.page_title = QLabel("Windows Power Center")
        self.page_title.setObjectName("PageTitle")
        heading_box.addWidget(self.page_title)

        self.page_subtitle = QLabel("Your JASS toolkit, one beautiful control center.")
        self.page_subtitle.setObjectName("PageSubtitle")
        heading_box.addWidget(self.page_subtitle)

        header.addLayout(heading_box)
        header.addStretch()

        self.clock = QLabel()
        self.clock.setObjectName("Clock")
        header.addWidget(self.clock)

        main_layout.addLayout(header)

        # Search row
        search_row = QHBoxLayout()
        search_row.setSpacing(10)

        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("⌕   Search JASS tools...")
        self.search.textChanged.connect(self.refresh_cards)
        search_row.addWidget(self.search, 1)

        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("SortCombo")
        self.sort_combo.addItems(["Name", "Favorites first", "Category"])
        self.sort_combo.currentTextChanged.connect(self.refresh_cards)
        search_row.addWidget(self.sort_combo)

        main_layout.addLayout(search_row)

        # Hero stats
        stats = QHBoxLayout()
        stats.setSpacing(12)

        self.total_stat = self.make_stat("TOOLS", "0")
        self.favorite_stat = self.make_stat("FAVORITES", "0")
        self.category_stat = self.make_stat("CATEGORIES", "0")

        stats.addWidget(self.total_stat)
        stats.addWidget(self.favorite_stat)
        stats.addWidget(self.category_stat)
        stats.addStretch()

        main_layout.addLayout(stats)

        # Scrollable cards
        self.scroll = QScrollArea()
        self.scroll.setObjectName("ToolScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.cards_host = QWidget()
        self.cards_layout = QGridLayout(self.cards_host)
        self.cards_layout.setContentsMargins(2, 2, 2, 20)
        self.cards_layout.setHorizontalSpacing(14)
        self.cards_layout.setVerticalSpacing(14)

        self.scroll.setWidget(self.cards_host)
        main_layout.addWidget(self.scroll, 1)

        root_layout.addWidget(main, 1)

        self.status = QStatusBar()
        self.status.setObjectName("Status")
        self.setStatusBar(self.status)

    def make_stat(self, title, value):
        frame = QFrame()
        frame.setObjectName("StatCard")
        frame.setFixedSize(175, 70)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 9, 15, 9)

        value_label = QLabel(value)
        value_label.setObjectName("StatValue")
        title_label = QLabel(title)
        title_label.setObjectName("StatTitle")

        layout.addWidget(value_label)
        layout.addWidget(title_label)

        frame.value_label = value_label
        return frame

    def refresh_sidebar(self):
        current = self.current_category
        self.nav.blockSignals(True)
        self.nav.clear()

        counts = {"All Tools": len(self.tools)}
        for category in CATEGORY_ORDER[1:]:
            counts[category] = sum(t.category == category for t in self.tools)

        for category in CATEGORY_ORDER:
            if category != "All Tools" and counts.get(category, 0) == 0:
                continue

            icon, _ = CATEGORY_INFO[category]
            item = QListWidgetItem(f"{icon}   {category}   ·  {counts[category]}")
            item.setData(Qt.ItemDataRole.UserRole, category)
            self.nav.addItem(item)

        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.ItemDataRole.UserRole) == current:
                self.nav.setCurrentRow(i)
                break

        if self.nav.currentRow() < 0 and self.nav.count():
            self.nav.setCurrentRow(0)

        self.nav.blockSignals(False)

    def nav_changed(self, current, previous):
        if not current:
            return
        self.current_category = current.data(Qt.ItemDataRole.UserRole)
        self.page_title.setText(self.current_category)
        self.page_subtitle.setText(
            CATEGORY_INFO.get(self.current_category, ("•", ""))[1]
        )
        self.refresh_cards()

    # ---------------- cards ----------------

    def refresh_cards(self):
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        query = self.search.text().strip().lower()
        category = self.current_category

        visible = []
        for tool in self.tools:
            if category != "All Tools" and tool.category != category:
                continue

            if query:
                haystack = f"{tool.name} {tool.category} {tool.description}".lower()
                if query not in haystack:
                    continue

            visible.append(tool)

        sort_mode = self.sort_combo.currentText()
        if sort_mode == "Favorites first":
            visible.sort(key=lambda t: (not t.favorite, t.name.lower()))
        elif sort_mode == "Category":
            visible.sort(key=lambda t: (t.category.lower(), t.name.lower()))
        else:
            visible.sort(key=lambda t: t.name.lower())

        columns = 3
        for i, tool in enumerate(visible):
            card = ToolCard(tool, self)
            self.cards_layout.addWidget(card, i // columns, i % columns)

        self.update_stats()
        self.status.showMessage(
            f"{len(visible)} tool(s) shown  •  {len(self.tools)} discovered"
        )

    def update_stats(self):
        self.total_stat.value_label.setText(str(len(self.tools)))
        self.favorite_stat.value_label.setText(
            str(sum(t.favorite for t in self.tools))
        )
        self.category_stat.value_label.setText(
            str(len({t.category for t in self.tools}))
        )

    # ---------------- actions ----------------

    def launch_tool(self, tool: Tool):
        path = Path(tool.path)

        if not path.exists():
            QMessageBox.warning(
                self,
                "Tool Not Found",
                f"The application no longer exists:\n\n{path}\n\n"
                "Use 'Scan Toolkit' after restoring the file."
            )
            return

        try:
            if path.suffix.lower() == ".py":
                subprocess.Popen(
                    [sys.executable, str(path)],
                    cwd=str(path.parent),
                    creationflags=0
                )
            else:
                os.startfile(str(path))  # type: ignore[attr-defined]

            self.add_recent(tool.path)
            self.status.showMessage(f"Launched {tool.name}")
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Launch Failed",
                f"Could not launch:\n{path}\n\n{exc}"
            )

    def toggle_favorite(self, path: str):
        favorites = set(self.state.get("favorites", []))

        if path in favorites:
            favorites.remove(path)
        else:
            favorites.add(path)

        self.state["favorites"] = sorted(favorites)
        save_state(self.state)

        for tool in self.tools:
            if tool.path == path:
                tool.favorite = path in favorites

        self.refresh_sidebar()
        self.refresh_cards()

    def add_recent(self, path: str):
        recent = self.state.get("recent", [])
        recent = [p for p in recent if p != path]
        recent.insert(0, path)
        self.state["recent"] = recent[:12]
        save_state(self.state)

    def open_tool_location(self):
        pass

    def show_about(self):
        QMessageBox.about(
            self,
            "About JASS Windows Power Center",
            f"<h2>JASS Windows Power Center</h2>"
            f"<p>Version {VERSION}</p>"
            "<p>A beautiful launcher and control center for the "
            "JASS Windows Toolkit.</p>"
            "<p><b>Lightweight • Local • Practical</b></p>"
            "<p>The Power Center discovers JASS applications in its "
            "own directory and launches them without requiring a "
            "central installation system.</p>"
        )

    def update_clock(self):
        from datetime import datetime
        self.clock.setText(datetime.now().strftime("%a  %d %b  •  %I:%M %p"))

    # ---------------- theme ----------------

    def apply_theme(self):
        self.setStyleSheet("""
        * {
            font-family: "Segoe UI", "Inter", Arial;
        }

        QMainWindow, QWidget#Root {
            background: #0d1117;
        }

        QWidget#Main {
            background: #0d1117;
        }

        QFrame#Sidebar {
            background: #111820;
            border-right: 1px solid #202a35;
        }

        QLabel#Brand {
            color: #f2f6fa;
            font-size: 28px;
            font-weight: 800;
            letter-spacing: 2px;
        }

        QLabel#BrandSub {
            color: #6f8295;
            font-size: 9px;
            font-weight: 700;
            letter-spacing: 2px;
        }

        QListWidget#NavList {
            background: transparent;
            border: none;
            outline: none;
            color: #a9b7c5;
            font-size: 13px;
        }

        QListWidget#NavList::item {
            padding: 12px 10px;
            border-radius: 8px;
            margin: 1px 0;
        }

        QListWidget#NavList::item:hover {
            background: #19232e;
            color: #eaf2f8;
        }

        QListWidget#NavList::item:selected {
            background: #173b4d;
            color: #67d9ff;
            font-weight: 700;
        }

        QPushButton#SidebarButton {
            background: #17212b;
            color: #9eafbf;
            border: 1px solid #263442;
            border-radius: 8px;
            padding: 10px;
            text-align: left;
        }

        QPushButton#SidebarButton:hover {
            background: #1d2a36;
            color: #ffffff;
            border-color: #345266;
        }

        QLabel#PageTitle {
            color: #f4f8fb;
            font-size: 28px;
            font-weight: 750;
        }

        QLabel#PageSubtitle {
            color: #74889b;
            font-size: 13px;
        }

        QLabel#Clock {
            color: #71879a;
            font-size: 12px;
            padding: 8px 12px;
        }

        QLineEdit#Search {
            background: #111a23;
            color: #dce7ef;
            border: 1px solid #263542;
            border-radius: 10px;
            padding: 12px 15px;
            font-size: 13px;
            selection-background-color: #15536b;
        }

        QLineEdit#Search:focus {
            border-color: #39b9df;
        }

        QComboBox#SortCombo {
            background: #111a23;
            color: #aebdca;
            border: 1px solid #263542;
            border-radius: 10px;
            padding: 10px 13px;
            min-width: 145px;
        }

        QComboBox QAbstractItemView {
            background: #151f29;
            color: #dbe7ef;
            selection-background-color: #17465b;
        }

        QFrame#StatCard {
            background: #111a23;
            border: 1px solid #202e3b;
            border-radius: 10px;
        }

        QLabel#StatValue {
            color: #65d8ff;
            font-size: 22px;
            font-weight: 800;
        }

        QLabel#StatTitle {
            color: #657a8d;
            font-size: 9px;
            font-weight: 700;
            letter-spacing: 1px;
        }

        QScrollArea#ToolScroll {
            background: transparent;
        }

        QFrame#ToolCard {
            background: #111a23;
            border: 1px solid #22313e;
            border-radius: 12px;
        }

        QFrame#ToolCard:hover {
            background: #141f29;
            border-color: #31566a;
        }

        QLabel#CardIcon {
            background: #172d3a;
            color: #65d8ff;
            border-radius: 10px;
            font-size: 21px;
            font-weight: 700;
        }

        QLabel#CardTitle {
            color: #e8f0f5;
            font-size: 15px;
            font-weight: 700;
        }

        QLabel#CardDescription {
            color: #718697;
            font-size: 11px;
            line-height: 1.3;
        }

        QLabel#CardCategory {
            color: #4d9bb7;
            font-size: 10px;
            font-weight: 700;
        }

        QToolButton#FavoriteButton {
            background: transparent;
            border: none;
            color: #617789;
            font-size: 18px;
        }

        QToolButton#FavoriteButton:hover {
            color: #ffd76a;
        }

        QPushButton#LaunchButton {
            background: #173e4f;
            color: #70ddff;
            border: 1px solid #255a70;
            border-radius: 7px;
            padding: 6px 13px;
            font-weight: 700;
        }

        QPushButton#LaunchButton:hover {
            background: #1e5368;
            color: #ffffff;
        }

        QStatusBar#Status {
            background: #0b1015;
            color: #607487;
            border-top: 1px solid #1c2731;
            padding-left: 10px;
        }

        QScrollBar:vertical {
            background: #0d1117;
            width: 10px;
            margin: 0;
        }

        QScrollBar::handle:vertical {
            background: #263744;
            border-radius: 5px;
            min-height: 35px;
        }

        QScrollBar::handle:vertical:hover {
            background: #355365;
        }

        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 0;
        }
        """)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("JASS")

    window = PowerCenter()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

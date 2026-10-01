import json
import random
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox,
    QListWidget, QListWidgetItem, QSplitter, QFileDialog, QMessageBox,
    QSpinBox, QGroupBox, QFormLayout
)

APP_NAME = "JASS Romance Studio"
VERSION = "1.0"

MOODS = ["Tender", "Romantic", "Flirty", "Sensual", "Intimate"]
SETTINGS = [
    "Candlelit Apartment", "Rainy Evening", "Quiet Café",
    "Moonlit Garden", "Beach at Sunset", "Mountain Retreat",
    "Bookshop After Hours", "Cozy Living Room"
]
SCENE_TYPES = [
    "First Meeting", "Quiet Conversation", "Date Night",
    "Slow Dance", "Confession", "Reunion", "Late-Night Conversation",
    "Morning Together"
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1400, 850)
        self.history = []
        self.current_story = {
            "title": "Untitled Romance",
            "character_a": "Alex",
            "character_b": "Maya",
            "relationship": "New acquaintances",
            "mood": "Romantic",
            "setting": "Rainy Evening",
            "scene_type": "Quiet Conversation",
            "tension": 45,
            "scenes": []
        }
        self.build_ui()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)

        header = QHBoxLayout()
        title = QLabel("JASS Romance Studio")
        title.setObjectName("Title")
        subtitle = QLabel("Create • play • save romantic interactive stories")
        subtitle.setObjectName("Muted")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch()

        new_btn = QPushButton("New Story")
        new_btn.clicked.connect(self.new_story)
        header.addWidget(new_btn)

        load_btn = QPushButton("Open Story")
        load_btn.clicked.connect(self.open_story)
        header.addWidget(load_btn)

        save_btn = QPushButton("Save Story")
        save_btn.clicked.connect(self.save_story)
        header.addWidget(save_btn)

        export_btn = QPushButton("Export TXT")
        export_btn.clicked.connect(self.export_txt)
        header.addWidget(export_btn)
        main.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)

        # Left: story controls
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        character_box = QGroupBox("Characters")
        form = QFormLayout(character_box)

        self.name_a = QLineEdit("Alex")
        self.name_b = QLineEdit("Maya")
        self.relationship = QLineEdit("New acquaintances")
        form.addRow("Character A:", self.name_a)
        form.addRow("Character B:", self.name_b)
        form.addRow("Relationship:", self.relationship)
        left_layout.addWidget(character_box)

        scene_box = QGroupBox("Scene")
        sf = QFormLayout(scene_box)

        self.setting = QComboBox()
        self.setting.addItems(SETTINGS)

        self.scene_type = QComboBox()
        self.scene_type.addItems(SCENE_TYPES)

        self.mood = QComboBox()
        self.mood.addItems(MOODS)
        self.mood.setCurrentText("Romantic")

        self.tension = QSpinBox()
        self.tension.setRange(0, 100)
        self.tension.setValue(45)
        self.tension.setSuffix(" / 100")

        sf.addRow("Setting:", self.setting)
        sf.addRow("Scene:", self.scene_type)
        sf.addRow("Mood:", self.mood)
        sf.addRow("Tension:", self.tension)
        left_layout.addWidget(scene_box)

        generate_btn = QPushButton("Create Scene")
        generate_btn.clicked.connect(self.create_scene)
        left_layout.addWidget(generate_btn)

        suggestion_btn = QPushButton("Suggest What Happens Next")
        suggestion_btn.clicked.connect(self.suggest_next)
        left_layout.addWidget(suggestion_btn)

        left_layout.addWidget(QLabel("Scene History"))
        self.scene_list = QListWidget()
        self.scene_list.currentRowChanged.connect(self.load_scene)
        left_layout.addWidget(self.scene_list, 1)

        splitter.addWidget(left)

        # Center: story
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)

        self.story_title = QLineEdit("Untitled Romance")
        self.story_title.setPlaceholderText("Story title")
        center_layout.addWidget(self.story_title)

        self.story_view = QTextEdit()
        self.story_view.setReadOnly(True)
        self.story_view.setPlaceholderText(
            "Your romantic story will appear here..."
        )
        center_layout.addWidget(self.story_view, 1)

        center_layout.addWidget(QLabel("Your response"))
        self.user_input = QTextEdit()
        self.user_input.setPlaceholderText(
            "Write what your character says, thinks, or does..."
        )
        self.user_input.setMaximumHeight(120)
        center_layout.addWidget(self.user_input)

        response_row = QHBoxLayout()
        continue_btn = QPushButton("Continue Scene")
        continue_btn.clicked.connect(self.continue_scene)
        response_row.addWidget(continue_btn)

        clear_btn = QPushButton("Clear Response")
        clear_btn.clicked.connect(self.user_input.clear)
        response_row.addWidget(clear_btn)

        response_row.addStretch()
        center_layout.addLayout(response_row)

        splitter.addWidget(center)

        # Right: creative prompts
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_layout.addWidget(QLabel("Romance Prompt Deck"))

        prompts = [
            "A lingering glance lasts a little longer than expected.",
            "They discover they have the same favorite song.",
            "One character finally admits what they have been feeling.",
            "A quiet walk becomes unexpectedly meaningful.",
            "They share a memory neither has told anyone else.",
            "A playful challenge creates romantic tension.",
            "Rain changes the plans for the evening.",
            "A goodbye becomes difficult because neither wants to leave."
        ]

        self.prompt_list = QListWidget()
        for prompt in prompts:
            self.prompt_list.addItem(prompt)
        self.prompt_list.itemDoubleClicked.connect(self.use_prompt)
        right_layout.addWidget(self.prompt_list, 1)

        use_btn = QPushButton("Use Selected Prompt")
        use_btn.clicked.connect(self.use_prompt)
        right_layout.addWidget(use_btn)

        letter_btn = QPushButton("Write a Love Letter")
        letter_btn.clicked.connect(self.create_letter)
        right_layout.addWidget(letter_btn)

        date_btn = QPushButton("Generate Date Idea")
        date_btn.clicked.connect(self.date_idea)
        right_layout.addWidget(date_btn)

        splitter.addWidget(right)
        splitter.setSizes([330, 720, 350])
        main.addWidget(splitter, 1)

        self.status = QLabel("Ready — this is a local creative writing studio.")
        self.status.setObjectName("Muted")
        main.addWidget(self.status)

        self.setStyleSheet("""
            QWidget {
                background:#151922;
                color:#eeeaf0;
                font-size:10.5pt;
            }
            QLabel#Title {
                font-size:21pt;
                font-weight:700;
            }
            QLabel#Muted {
                color:#a59ca8;
            }
            QGroupBox {
                border:1px solid #3b3440;
                border-radius:9px;
                margin-top:10px;
                padding:10px;
            }
            QGroupBox::title {
                subcontrol-origin:margin;
                left:10px;
                padding:0 5px;
                color:#d8cbd8;
            }
            QPushButton,QComboBox,QLineEdit,QSpinBox {
                background:#24202a;
                border:1px solid #493f4c;
                border-radius:6px;
                padding:7px 10px;
            }
            QPushButton:hover {
                background:#302936;
            }
            QLineEdit,QTextEdit {
                background:#111017;
                border:1px solid #39323e;
                border-radius:7px;
            }
            QListWidget {
                background:#111017;
                border:1px solid #39323e;
                border-radius:7px;
            }
            QListWidget::item:selected {
                background:#4b3549;
            }
            QComboBox QAbstractItemView {
                background:#24202a;
                selection-background-color:#4b3549;
            }
        """)

    def names(self):
        a = self.name_a.text().strip() or "Alex"
        b = self.name_b.text().strip() or "Maya"
        return a, b

    def create_scene(self):
        a, b = self.names()
        setting = self.setting.currentText()
        scene_type = self.scene_type.currentText()
        mood = self.mood.currentText()
        tension = self.tension.value()

        openings = {
            "Tender": f"The evening began quietly in the {setting.lower()}. {a} noticed the gentle way {b} smiled whenever their eyes met.",
            "Romantic": f"Rain softened the world outside the {setting.lower()}, leaving {a} and {b} with a little more time together than either had expected.",
            "Flirty": f"{a} caught {b}'s amused expression and smiled. There was something playful in the silence between them.",
            "Sensual": f"The room felt warm and private. {a} and {b} stood close, both aware of the quiet tension between them.",
            "Intimate": f"For a while neither of them spoke. In the stillness of the {setting.lower()}, simply being together felt unexpectedly meaningful."
        }

        text = (
            f"Scene: {scene_type}\n"
            f"Setting: {setting}\n"
            f"Mood: {mood} • Romantic tension: {tension}/100\n\n"
            f"{openings[mood]}\n\n"
            f"{self.next_paragraph(a, b, mood, tension)}"
        )

        self.add_scene(text)
        self.status.setText("New scene created.")

    def next_paragraph(self, a, b, mood, tension):
        if mood == "Tender":
            return f"{b} looked at {a}. “I like moments like this,” {b} said softly. “They feel easy.”"
        if mood == "Flirty":
            return f"{b} raised an eyebrow. “You know,” {b} said, “you make it surprisingly difficult to concentrate.”"
        if mood == "Sensual":
            return f"{a} noticed how close they were. Neither stepped away. The silence carried a warmth that needed no explanation."
        if mood == "Intimate":
            return f"{b} reached for {a}'s hand. “Stay a little longer,” {b} whispered."
        return f"{b} smiled. “Maybe this is the part of the evening I'll remember,” {b} said."

    def continue_scene(self):
        response = self.user_input.toPlainText().strip()
        if not response:
            QMessageBox.information(self, "Continue Scene", "Write your character's response first.")
            return

        a, b = self.names()
        mood = self.mood.currentText()
        followups = {
            "Tender": f"{b} listened carefully. The honesty in {a}'s words brought a quiet smile.",
            "Romantic": f"{b} held {a}'s gaze for a moment. “I'm glad you said that.”",
            "Flirty": f"{b} smiled knowingly. “Is that your way of making me blush?”",
            "Sensual": f"The space between them seemed smaller now, filled with anticipation and an unmistakable warmth.",
            "Intimate": f"{b} squeezed {a}'s hand gently. Neither needed to explain what the moment meant."
        }
        text = f"{a}: {response}\n\n{followups[mood]}"
        self.add_scene(text)
        self.user_input.clear()
        self.status.setText("Scene continued.")

    def suggest_next(self):
        a, b = self.names()
        suggestions = [
            f"{a} asks {b} about a dream they have never told anyone.",
            f"{b} suggests taking a quiet walk together.",
            f"{a} puts on a favorite song and invites {b} to dance.",
            f"{b} asks the question both of them have been avoiding.",
            f"{a} reveals a small secret, hoping {b} will understand.",
            f"{b} says they are not ready for the evening to end."
        ]
        suggestion = random.choice(suggestions)
        self.user_input.setPlainText(suggestion)
        self.status.setText("A possible next moment has been suggested.")

    def use_prompt(self, _item=None):
        item = self.prompt_list.currentItem()
        if item:
            self.user_input.setPlainText(item.text())
            self.user_input.setFocus()

    def create_letter(self):
        a, b = self.names()
        text = (
            f"Dear {b},\n\n"
            f"I don't know exactly when ordinary moments with you began "
            f"feeling extraordinary. Maybe it was one of our conversations, "
            f"or one of those quiet pauses when neither of us needed to speak.\n\n"
            f"I only know that being near you makes the world feel a little softer. "
            f"I hope we get many more evenings like this — unhurried, honest, and ours.\n\n"
            f"Yours,\n{a}"
        )
        self.add_scene(text)
        self.status.setText("Love letter added to the story.")

    def date_idea(self):
        ideas = [
            "Cook dinner together, then choose one song each for a slow-dance playlist.",
            "Visit a quiet bookshop and choose a book for each other.",
            "Take a late-evening walk and stop somewhere for dessert.",
            "Have a no-phones coffee date and ask each other five unexpected questions.",
            "Watch the sunset with a shared playlist and a thermos of something warm."
        ]
        self.add_scene("Date idea:\n\n" + random.choice(ideas))
        self.status.setText("Date idea added.")

    def add_scene(self, text):
        self.history.append(text)
        self.scene_list.addItem(QListWidgetItem(f"Scene {len(self.history)}"))
        self.scene_list.setCurrentRow(len(self.history) - 1)
        self.story_view.setPlainText("\n\n".join(self.history))

    def load_scene(self, index):
        if 0 <= index < len(self.history):
            self.story_view.setPlainText(self.history[index])

    def new_story(self):
        self.history.clear()
        self.scene_list.clear()
        self.story_view.clear()
        self.story_title.setText("Untitled Romance")
        self.status.setText("New story started.")

    def save_story(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Romance Story", "", "JASS Romance Story (*.jrs.json)"
        )
        if not path:
            return
        if not path.lower().endswith(".jrs.json"):
            path += ".jrs.json"

        data = {
            "title": self.story_title.text().strip() or "Untitled Romance",
            "character_a": self.name_a.text(),
            "character_b": self.name_b.text(),
            "relationship": self.relationship.text(),
            "mood": self.mood.currentText(),
            "setting": self.setting.currentText(),
            "scene_type": self.scene_type.currentText(),
            "tension": self.tension.value(),
            "scenes": self.history
        }

        try:
            Path(path).write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            self.status.setText("Story saved.")
        except Exception as e:
            QMessageBox.critical(self, "Save Story", str(e))

    def open_story(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Romance Story", "", "JASS Romance Story (*.jrs.json)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.story_title.setText(data.get("title", "Untitled Romance"))
            self.name_a.setText(data.get("character_a", "Alex"))
            self.name_b.setText(data.get("character_b", "Maya"))
            self.relationship.setText(data.get("relationship", ""))
            self.mood.setCurrentText(data.get("mood", "Romantic"))
            self.setting.setCurrentText(data.get("setting", SETTINGS[0]))
            self.scene_type.setCurrentText(data.get("scene_type", SCENE_TYPES[0]))
            self.tension.setValue(int(data.get("tension", 45)))
            self.history = list(data.get("scenes", []))
            self.scene_list.clear()
            for i in range(len(self.history)):
                self.scene_list.addItem(f"Scene {i + 1}")
            self.story_view.setPlainText("\n\n".join(self.history))
            self.status.setText("Story opened.")
        except Exception as e:
            QMessageBox.critical(self, "Open Story", str(e))

    def export_txt(self):
        if not self.history:
            QMessageBox.information(self, "Export", "There is no story content to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Romance Story", "", "Text Files (*.txt)"
        )
        if not path:
            return

        text = (
            f"{self.story_title.text().strip() or 'Untitled Romance'}\n"
            f"{'=' * 60}\n\n"
            f"Characters: {self.name_a.text()} & {self.name_b.text()}\n"
            f"Relationship: {self.relationship.text()}\n\n"
            + "\n\n".join(self.history)
        )

        try:
            Path(path).write_text(text, encoding="utf-8")
            self.status.setText("Story exported.")
        except Exception as e:
            QMessageBox.critical(self, "Export", str(e))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

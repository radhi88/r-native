"""Assistant interaction panel."""
from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QPlainTextEdit, QVBoxLayout, QWidget

from qader_app.assistant.qader_brain import QaderBrain
from qader_app.assistant.qader_voice import QaderVoice


class AssistantView(QWidget):
    def __init__(self, brain: QaderBrain | None = None, voice: QaderVoice | None = None, parent=None):
        super().__init__(parent)
        self.brain = brain or QaderBrain()
        self.voice = voice or QaderVoice()
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask Qader...")
        self.send_button = QPushButton("Send")
        self.speak_button = QPushButton("Speak intro")
        self.listen_button = QPushButton("Listen once")
        self.send_button.clicked.connect(self.send)
        self.speak_button.clicked.connect(lambda: self.voice.speak(self.brain.introduction()))
        self.listen_button.clicked.connect(self.listen_once)
        row = QHBoxLayout()
        row.addWidget(self.input)
        row.addWidget(self.send_button)
        row.addWidget(self.speak_button)
        row.addWidget(self.listen_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.output)
        layout.addLayout(row)
        self.output.appendPlainText(self.brain.introduction())

    def send(self) -> None:
        text = self.input.text()
        result = self.brain.handle_text(text)
        self.output.appendPlainText(f"> {text}\n{result.get('message')}")
        self.input.clear()

    def listen_once(self) -> None:
        result = self.voice.listen_once()
        if result.get("ok"):
            self.input.setText(result.get("text", ""))
            self.send()
        else:
            self.output.appendPlainText(f"Voice unavailable: {result.get('reason')}")


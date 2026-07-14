"""Audit log and report viewer."""
from __future__ import annotations

import json

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QComboBox, QPushButton, QPlainTextEdit, QVBoxLayout, QWidget

from qader_app.paths import dna_dir, logs_dir
from qader_app.storage.audit_log import read_recent


class LogsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.source = QComboBox()
        self.source.addItems(["Audit log", "Realtime loop", "Execution log", "DNA live journal"])
        self.refresh_button = QPushButton("Refresh logs")
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.refresh_button.clicked.connect(self.refresh)
        self.source.currentIndexChanged.connect(self.refresh)
        layout = QVBoxLayout(self)
        layout.addWidget(self.source)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.output)
        self.setStyleSheet("""
            QWidget { background:#050816; color:#dbeafe; font-family: Segoe UI, Arial; }
            QComboBox, QPushButton { background:#102033; border:1px solid #245071; border-radius:6px; padding:8px; color:#e0f2fe; font-weight:700; }
            QPlainTextEdit { background:#020617; border:1px solid #1f2a44; border-radius:6px; color:#a7f3d0; font-family: Consolas, monospace; }
        """)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)
        self.refresh()

    def refresh(self) -> None:
        self.output.clear()
        source = self.source.currentText()
        if source == "Audit log":
            for record in read_recent(200):
                self.output.appendPlainText(json.dumps(record, ensure_ascii=False))
            return
        paths = {
            "Realtime loop": logs_dir() / "qader_realtime_loop.jsonl",
            "Execution log": logs_dir() / "execution_log.jsonl",
            "DNA live journal": dna_dir() / "live_performance_journal.jsonl",
        }
        path = paths.get(source)
        if not path or not path.exists():
            self.output.appendPlainText(f"Log file not found: {path}")
            return
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]:
            try:
                self.output.appendPlainText(json.dumps(json.loads(line), ensure_ascii=False))
            except Exception:
                self.output.appendPlainText(line)

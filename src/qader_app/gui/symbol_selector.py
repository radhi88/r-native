"""Symbol selection widget."""
from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from qader_app.storage.settings_store import SettingsStore


class SymbolSelectorView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = SettingsStore()
        selected = ",".join(self.settings.load().get("selected_symbols", ["XAUUSDm"]))
        self.symbols = QLineEdit(selected)
        self.timeframes = QLineEdit(",".join(self.settings.load().get("selected_timeframes", ["M1"])))
        self.save_button = QPushButton("Save symbols")
        self.save_button.clicked.connect(self.save)
        row = QHBoxLayout()
        row.addWidget(QLabel("Symbols"))
        row.addWidget(self.symbols)
        row.addWidget(QLabel("Timeframes"))
        row.addWidget(self.timeframes)
        row.addWidget(self.save_button)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addStretch(1)

    def values(self) -> tuple[list[str], list[str]]:
        symbols = [s.strip() for s in self.symbols.text().split(",") if s.strip()]
        timeframes = [t.strip() for t in self.timeframes.text().split(",") if t.strip()]
        return symbols or ["XAUUSDm"], timeframes or ["M1"]

    def save(self) -> None:
        symbols, timeframes = self.values()
        self.settings.save({"selected_symbols": symbols, "selected_timeframes": timeframes})


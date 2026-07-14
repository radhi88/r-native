"""Settings export/import panel."""
from __future__ import annotations

from PyQt6.QtWidgets import QFileDialog, QPushButton, QPlainTextEdit, QVBoxLayout, QWidget

from qader_app.services.config_service import ConfigService


class SettingsView(QWidget):
    def __init__(self, config: ConfigService | None = None, parent=None):
        super().__init__(parent)
        self.config = config or ConfigService()
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.export_button = QPushButton("Export settings")
        self.import_button = QPushButton("Import settings")
        self.export_button.clicked.connect(self.export_settings)
        self.import_button.clicked.connect(self.import_settings)
        layout = QVBoxLayout(self)
        layout.addWidget(self.export_button)
        layout.addWidget(self.import_button)
        layout.addWidget(self.output)

    def export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Qader settings", "qader_settings_export.json", "JSON Files (*.json)")
        if path:
            output = self.config.export_settings(path)
            self.output.appendPlainText(f"Exported to {output}")

    def import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Qader settings", "", "JSON Files (*.json)")
        if path:
            self.config.import_settings(path)
            self.output.appendPlainText(f"Imported from {path}")


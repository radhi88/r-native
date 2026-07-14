"""Permissions center UI."""
from __future__ import annotations

from PyQt6.QtWidgets import QCheckBox, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from qader_app.services.real_mode_service import RealModeService
from qader_app.storage.settings_store import LOCKED_PERMISSIONS, PermissionsStore


class PermissionsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = PermissionsStore()
        self.real_mode = RealModeService(self.store)
        self.boxes: dict[str, QCheckBox] = {}
        self.save_button = QPushButton("Save permissions")
        self.save_button.clicked.connect(self.save)
        self.real_phrase = QLineEdit()
        self.real_phrase.setPlaceholderText(self.real_mode.unlock_phrase())
        self.real_unlock_button = QPushButton("Unlock REAL CONTROLLED MODE")
        self.real_lock_button = QPushButton("Lock real trading")
        self.real_status = QLabel("REAL CONTROLLED MODE is locked by default.")
        self.real_unlock_button.clicked.connect(self.unlock_real_mode)
        self.real_lock_button.clicked.connect(self.lock_real_mode)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        for key, value in self.store.load().items():
            if key.startswith("_") or key == "updated_at":
                continue
            box = QCheckBox(key)
            box.setChecked(bool(value))
            if key in LOCKED_PERMISSIONS:
                box.setEnabled(False)
                body_layout.addWidget(QLabel(f"{key}: locked - {LOCKED_PERMISSIONS[key]}"))
            self.boxes[key] = box
            body_layout.addWidget(box)
        body_layout.addWidget(self.save_button)
        body_layout.addWidget(QLabel("REAL CONTROLLED MODE requires typed confirmation and a clean MT5 lockdown check."))
        body_layout.addWidget(self.real_phrase)
        body_layout.addWidget(self.real_unlock_button)
        body_layout.addWidget(self.real_lock_button)
        body_layout.addWidget(self.real_status)
        body_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)

    def save(self) -> None:
        self.store.save({key: box.isChecked() for key, box in self.boxes.items()})

    def unlock_real_mode(self) -> None:
        result = self.real_mode.unlock(self.real_phrase.text())
        self.real_status.setText("REAL CONTROLLED MODE unlocked." if result.get("ok") else "Unlock failed; real trading remains locked.")
        permissions = self.store.load()
        for key, box in self.boxes.items():
            box.setChecked(bool(permissions.get(key, False)))

    def lock_real_mode(self) -> None:
        self.real_mode.lock("permissions_screen_lock")
        self.real_status.setText("REAL CONTROLLED MODE locked.")
        permissions = self.store.load()
        for key, box in self.boxes.items():
            box.setChecked(bool(permissions.get(key, False)))

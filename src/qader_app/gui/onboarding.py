"""First-run onboarding wizard."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from qader_app.storage.profile_store import ProfileStore
from qader_app.storage.settings_store import PermissionsStore, SettingsStore


class OnboardingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Qader first-run setup")
        self.name_input = QLineEdit()
        self.language = QComboBox()
        self.language.addItems(["bilingual", "Arabic", "English"])
        self.tone = QComboBox()
        self.tone.addItems(["professional", "friendly", "direct", "detailed", "concise"])
        self.symbols = QLineEdit("XAUUSDm")
        self.mode = QComboBox()
        self.mode.addItems(["observe_only", "market_scan_analysis", "dry_run_simulation", "demo_controlled_locked"])

        self.permission_boxes: dict[str, QCheckBox] = {}
        permission_labels = {
            "can_read_mt5": "Read MT5 data",
            "can_scan_market": "Scan selected symbols",
            "can_run_dry_run": "Run dry-run simulations",
            "can_run_demo_controlled": "Demo controlled mode",
            "can_use_microphone": "Listen to microphone",
            "can_use_speaker": "Speak using voice",
            "can_save_memory": "Save local memory",
            "can_write_reports": "Write reports",
            "can_modify_strategy_dna": "Modify strategy DNA",
            "can_apply_code_updates": "Apply updates only after approval",
            "can_archive_files": "Archive clearly obsolete files",
        }
        permissions_group = QGroupBox("Permissions")
        permissions_layout = QVBoxLayout(permissions_group)
        for key, label in permission_labels.items():
            box = QCheckBox(label)
            if key in {"can_save_memory", "can_write_reports"}:
                box.setChecked(True)
            self.permission_boxes[key] = box
            permissions_layout.addWidget(box)
        locked = QCheckBox("Place live orders (locked)")
        locked.setEnabled(False)
        locked.setChecked(False)
        self.permission_boxes["can_place_live_orders"] = locked
        permissions_layout.addWidget(locked)

        form = QFormLayout()
        form.addRow("Preferred name", self.name_input)
        form.addRow("Language", self.language)
        form.addRow("Tone", self.tone)
        form.addRow("Symbols", self.symbols)
        form.addRow("Mode", self.mode)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("أنا قادر. Before I start, I will only act within your approved permissions."))
        layout.addLayout(form)
        layout.addWidget(permissions_group)
        layout.addWidget(buttons)

    def save_answers(self) -> None:
        ProfileStore().save(
            {
                "preferred_name": self.name_input.text().strip(),
                "language": self.language.currentText(),
                "tone": self.tone.currentText(),
            }
        )
        symbols = [s.strip() for s in self.symbols.text().split(",") if s.strip()]
        SettingsStore().save({"selected_symbols": symbols or ["XAUUSDm"], "mode": self.mode.currentText()})
        PermissionsStore().save({key: box.isChecked() for key, box in self.permission_boxes.items()})

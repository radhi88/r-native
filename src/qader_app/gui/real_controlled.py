"""REAL CONTROLLED MODE screen."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qader_app.services.real_mode_service import RealModeService
from qader_app.services.real_time_loop_service import RealTimeLoopService
from qader_app.storage.settings_store import PermissionsStore
from qader_app.paths import app_root


class RealControlledModeView(QWidget):
    def __init__(self, service: RealModeService | None = None, loop_service: RealTimeLoopService | None = None, parent=None):
        super().__init__(parent)
        self.service = service or RealModeService()
        self.permissions = PermissionsStore()
        self.loop_service = loop_service or RealTimeLoopService(self.permissions)
        self.status = QLabel("DEMO EXECUTION LOCKED")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet("background:#7f1d1d;color:white;font-weight:700;padding:8px;border-radius:4px;")

        self.warning = QLabel(
            "DEMO_ONLY execution may place bounded market orders only on a connected MT5 demo/trial account "
            "after typed unlock, clean lockdown verification, pipeline approval, and final GUI confirmation."
        )
        self.warning.setWordWrap(True)

        self.account_labels = {
            "login": QLabel("-"),
            "server": QLabel("-"),
            "balance": QLabel("-"),
            "equity": QLabel("-"),
            "margin": QLabel("-"),
            "open_positions": QLabel("-"),
            "pending_orders": QLabel("-"),
        }
        account_box = QGroupBox("Connected MT5 account")
        account_form = QFormLayout(account_box)
        for key, label in self.account_labels.items():
            account_form.addRow(key, label)

        self.phrase = QLineEdit()
        self.phrase.setPlaceholderText(self.service.unlock_phrase())
        self.phrase.setEchoMode(QLineEdit.EchoMode.Normal)

        self.auto_start_toggle = QCheckBox("Auto-start realtime demo controlled mode on launch (if unlocked)")
        perms = self.permissions.load()
        self.auto_start_toggle.setChecked(bool(perms.get("_auto_start_real_controlled_mode", False)))

        self.refresh_button = QPushButton("Refresh account")
        self.lockdown_button = QPushButton("Run lockdown check")
        self.unlock_button = QPushButton("Unlock DEMO CONTROLLED MODE")
        self.validation_button = QPushButton("Validation only")
        self.arm_start_button = QPushButton("Arm Demo Mode & Start Now")
        self.lock_button = QPushButton("Lock Demo Mode")
        self.emergency_button = QPushButton("Emergency stop")
        self.arm_start_button.setStyleSheet("background:#991b1b;color:white;font-weight:700;padding:6px;border-radius:4px;")
        self.lock_button.setStyleSheet("background:#7f1d1d;color:white;font-weight:700;padding:6px;border-radius:4px;")
        self.emergency_button.setStyleSheet("background:#111827;color:white;font-weight:700;padding:6px;border-radius:4px;")

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)

        buttons_row1 = QHBoxLayout()
        for button in (self.refresh_button, self.lockdown_button, self.unlock_button, self.validation_button):
            buttons_row1.addWidget(button)

        buttons_row2 = QHBoxLayout()
        for button in (self.arm_start_button, self.lock_button, self.emergency_button):
            buttons_row2.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.warning)
        layout.addWidget(account_box)
        layout.addWidget(QLabel("Typed confirmation phrase"))
        layout.addWidget(self.phrase)
        layout.addWidget(self.auto_start_toggle)
        layout.addLayout(buttons_row1)
        layout.addLayout(buttons_row2)
        layout.addWidget(QLabel("Live execution log"))
        layout.addWidget(self.output)

        self.refresh_button.clicked.connect(self.refresh_account)
        self.lockdown_button.clicked.connect(self.run_lockdown)
        self.unlock_button.clicked.connect(self.unlock)
        self.validation_button.clicked.connect(self.validation_only)
        self.arm_start_button.clicked.connect(self.arm_and_start)
        self.lock_button.clicked.connect(self.lock_real_mode)
        self.emergency_button.clicked.connect(self.emergency_stop)
        self.auto_start_toggle.stateChanged.connect(self.save_auto_start_setting)

    def append(self, payload) -> None:
        self.output.appendPlainText(json.dumps(payload, ensure_ascii=False, default=str, indent=2))

    def refresh_account(self) -> None:
        details = self.service.account_details()
        if details.get("ok"):
            for key, label in self.account_labels.items():
                label.setText(str(details.get(key, "-")))
        self.append({"account": details})

    def run_lockdown(self) -> None:
        result = self.service.run_lockdown_check()
        self.append({"lockdown": {k: v for k, v in result.items() if k not in {"stdout", "stderr"}}})

    def unlock(self) -> None:
        result = self.service.unlock(self.phrase.text())
        if result.get("ok"):
            self.status.setText("DEMO CONTROLLED MODE UNLOCKED")
            self.status.setStyleSheet("background:#b91c1c;color:white;font-weight:800;padding:8px;border-radius:4px;")
        else:
            self.status.setText("DEMO EXECUTION LOCKED")
            self.status.setStyleSheet("background:#7f1d1d;color:white;font-weight:700;padding:8px;border-radius:4px;")
        self.append({"unlock": {"ok": result.get("ok"), "lockdown": {k: v for k, v in result.get("lockdown", {}).items() if k not in {"stdout", "stderr"}}}})

    def validation_only(self) -> None:
        result = self.service.validation_mode_without_order()
        self.append({"validation_only_no_order": result})

    def arm_and_start(self) -> None:
        if self._external_loop_state_active():
            self.append({"arm_and_start": {"ok": True, "reason": "external_realtime_loop_already_running"}})
            self.status.setText("DEMO CONTROLLED MODE - EXTERNAL LOOP RUNNING")
            self.status.setStyleSheet("background:#059669;color:white;font-weight:800;padding:8px;border-radius:4px;")
            return
        confirm = QMessageBox.warning(
            self,
            "Arm Demo Mode & Start Now",
            "This will unlock demo mode and start the existing bounded Qader execution path on the connected demo/trial account. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            self.append({"arm_and_start": {"ok": False, "reason": "user_cancelled"}})
            return
        unlock_result = self.service.unlock(self.phrase.text())
        if not unlock_result.get("ok"):
            self.append({"arm_and_start": {"ok": False, "reason": "unlock_failed"}})
            return
        result = self.loop_service.start(final_confirmation=True)
        self.append({"arm_and_start": result})
        if result.get("ok"):
            self.status.setText("DEMO CONTROLLED MODE - REALTIME LOOP RUNNING")
            self.status.setStyleSheet("background:#059669;color:white;font-weight:800;padding:8px;border-radius:4px;")

    def _external_loop_state_active(self) -> bool:
        path = app_root() / "dashboard" / "qader_live_state.json"
        if not path.exists():
            return False
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            loop = state.get("loop", {})
            if not bool(loop.get("thread_alive")):
                return False
            stamp = datetime.fromisoformat(str(state.get("timestamp", "")).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()
            return age <= 10
        except Exception:
            return False

    def lock_real_mode(self) -> None:
        self.service.lock("manual_lock_via_gui")
        self.status.setText("DEMO EXECUTION LOCKED")
        self.status.setStyleSheet("background:#7f1d1d;color:white;font-weight:700;padding:8px;border-radius:4px;")
        self.append({"lock_real_mode": "real mode locked via button"})

    def emergency_stop(self) -> None:
        self.loop_service.emergency_stop()
        self.service.lock("emergency_stop")
        self.status.setText("DEMO EXECUTION LOCKED - EMERGENCY STOP")
        self.status.setStyleSheet("background:#111827;color:white;font-weight:800;padding:8px;border-radius:4px;")
        self.append({"emergency_stop": "real mode locked"})

    def save_auto_start_setting(self) -> None:
        perms = self.permissions.load()
        perms["_auto_start_real_controlled_mode"] = self.auto_start_toggle.isChecked()
        self.permissions.save(perms)
        self.append({"auto_start_setting": self.auto_start_toggle.isChecked()})

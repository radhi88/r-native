"""Main Qader desktop window."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from PyQt6.QtWidgets import QMainWindow, QTabWidget

from qader_app.paths import app_root
from qader_app.assistant.qader_brain import QaderBrain
from qader_app.assistant.qader_voice import QaderVoice
from qader_app.gui.assistant_view import AssistantView
from qader_app.gui.dashboard import DashboardView, WebDashboardView
from qader_app.gui.logs_view import LogsView
from qader_app.gui.permissions import PermissionsView
from qader_app.gui.real_controlled import RealControlledModeView
from qader_app.gui.scanner_view import ScannerView
from qader_app.gui.settings_view import SettingsView
from qader_app.gui.symbol_selector import SymbolSelectorView
from qader_app.services.config_service import ConfigService
from qader_app.services.mt5_service import MT5Service
from qader_app.services.real_mode_service import RealModeService
from qader_app.services.real_time_loop_service import RealTimeLoopService
from qader_app.services.runner_service import RunnerService
from qader_app.services.scanner_service import ScannerService
from qader_app.storage.settings_store import SettingsStore


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qader - قادر")
        self.resize(1200, 760)
        self.config = ConfigService()
        self.settings = SettingsStore()
        self.runner = RunnerService()
        self.real_mode = RealModeService()
        self.real_time_loop = RealTimeLoopService()
        self.mt5 = MT5Service()
        self.scanner = ScannerService(self.mt5)
        self.brain = QaderBrain()
        self.voice = QaderVoice()

        self.tabs = QTabWidget()
        self.dashboard = DashboardView(self.real_time_loop)
        self.symbols = SymbolSelectorView()
        self.scanner_view = ScannerView(self.scanner)
        self.assistant = AssistantView(self.brain, self.voice)
        self.permissions = PermissionsView()
        self.real_controlled = RealControlledModeView(self.real_mode, self.real_time_loop)
        self.logs = LogsView()
        self.settings_view = SettingsView(self.config)

        self.tabs.addTab(self.dashboard, "Dashboard")
        self.tabs.addTab(WebDashboardView(), "Web dashboard")
        self.tabs.addTab(self.scanner_view, "Market scanner")
        self.tabs.addTab(self.assistant, "Qader assistant")
        self.tabs.addTab(self.symbols, "Symbols")
        self.tabs.addTab(self.permissions, "Permissions")
        self.tabs.addTab(self.real_controlled, "REAL CONTROLLED MODE")
        self.tabs.addTab(self.logs, "Logs")
        self.tabs.addTab(self.settings_view, "Settings")
        self.setCentralWidget(self.tabs)

        self.dashboard.emergency_button.clicked.connect(self.emergency_stop)
        self.dashboard.pause_button.clicked.connect(self.pause_loop)
        self.dashboard.resume_button.clicked.connect(self.resume_loop)
        self.dashboard.stop_entries_button.clicked.connect(self.stop_new_entries)
        self._maybe_auto_start_loop()
        self.refresh_status()

    def refresh_status(self) -> None:
        status = self.mt5.status()
        settings = self.settings.load()
        self.dashboard.set_status(status.message, settings.get("mode", "observe_only"), settings.get("safety_status", "DRY_RUN_ONLY"))

    def _maybe_auto_start_loop(self) -> None:
        if os.environ.get("QADER_DISABLE_AUTOSTART"):
            return
        if self._external_loop_state_active():
            self.dashboard.status_label.setText("Qader realtime: external loop already running")
            return
        perms = self.real_time_loop.permissions.load()
        if not bool(perms.get("_auto_start_real_controlled_mode", False)):
            return
        if not (bool(perms.get("_real_controlled_mode_unlocked")) and bool(perms.get("_real_unlock_phrase_confirmed"))):
            return
        lockdown = self.real_mode.run_lockdown_check()
        if lockdown.get("ok"):
            result = self.real_time_loop.start(final_confirmation=True)
            self.dashboard.status_label.setText(f"Qader realtime auto-start: {result}")

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

    def emergency_stop(self) -> None:
        self.real_time_loop.emergency_stop()
        self.runner.emergency_stop()
        self.real_mode.lock("dashboard_emergency_stop")
        self.voice.listening = False
        self.dashboard.status_label.setText("Qader status: emergency stop applied")
        self.logs.refresh()

    def pause_loop(self) -> None:
        self.real_time_loop.pause()
        self.dashboard.status_label.setText("Qader realtime: paused")

    def resume_loop(self) -> None:
        self.real_time_loop.resume()
        self.dashboard.status_label.setText("Qader realtime: running")

    def stop_new_entries(self) -> None:
        self.real_time_loop.stop_new_entries()
        self.dashboard.status_label.setText("Qader realtime: managing only, new entries stopped")

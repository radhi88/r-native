"""Qader desktop application entry point."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for path in (str(SRC), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from qader_app.services.config_service import ConfigService
from qader_app.storage.profile_store import ProfileStore


def check_and_auto_start_real_mode() -> bool:
    from qader_app.storage.settings_store import PermissionsStore

    try:
        permissions = PermissionsStore()
        perms = permissions.load()
        should_auto_start = bool(perms.get("_auto_start_real_controlled_mode", False))
        already_unlocked = bool(perms.get("_real_controlled_mode_unlocked")) and bool(
            perms.get("_real_unlock_phrase_confirmed")
        )
        return should_auto_start and already_unlocked
    except Exception:
        pass
    return False


def run_gui() -> int:
    try:
        from PyQt6.QtWidgets import QApplication
    except Exception as exc:
        print(f"PyQt6 is required to run Qader GUI: {exc}")
        return 2

    from qader_app.gui.main_window import MainWindow
    from qader_app.gui.onboarding import OnboardingDialog

    config = ConfigService()
    config.bootstrap()
    app = QApplication(sys.argv)

    profile_store = ProfileStore()
    if not profile_store.exists():
        dialog = OnboardingDialog()
        if dialog.exec():
            dialog.save_answers()
        else:
            return 0

    window = MainWindow()
    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qader desktop assistant")
    parser.add_argument("--no-gui", action="store_true", help="Bootstrap files and exit without opening the GUI.")
    args = parser.parse_args(argv)
    ConfigService().bootstrap()
    if args.no_gui:
        print("Qader bootstrap complete.")
        return 0
    if os.environ.get("QADER_QT_OFFSCREEN"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())

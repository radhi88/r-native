"""Local Qader settings and permission persistence."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qader_app.paths import data_dir, ensure_runtime_dirs


REAL_CONTROLLED_MODE = "REAL_CONTROLLED_MODE"
REAL_UNLOCK_PHRASE = "I ACCEPT REAL TRADING RISK"

DEFAULT_SETTINGS = {
    "mode": "observe_only",
    "selected_symbols": ["XAUUSDm"],
    "selected_timeframes": ["M1"],
    "mt5_terminal_path": "",
    "last_genome": "active_genome.json",
    "safety_status": "DRY_RUN_ONLY",
}

DEFAULT_PERMISSIONS = {
    "can_read_mt5": False,
    "can_scan_market": False,
    "can_run_dry_run": False,
    "can_run_demo_controlled": False,
    "can_place_live_orders": False,
    "can_use_microphone": False,
    "can_use_speaker": False,
    "can_save_memory": True,
    "can_modify_strategy_dna": False,
    "can_write_reports": True,
    "can_archive_files": False,
    "can_apply_code_updates": False,
    "_auto_start_real_controlled_mode": False,
}

LOCKED_PERMISSIONS = {
    "can_place_live_orders": (
        "Locked by default. Unlock requires REAL_CONTROLLED_MODE, a clean "
        "verify_mt5_lockdown.py result, and the typed risk phrase."
    ),
}


def settings_path() -> Path:
    ensure_runtime_dirs()
    return data_dir() / "settings.json"


def permissions_path() -> Path:
    ensure_runtime_dirs()
    return data_dir() / "permissions.json"


class SettingsStore:
    def load(self) -> dict[str, Any]:
        path = settings_path()
        if not path.exists():
            return dict(DEFAULT_SETTINGS)
        try:
            return {**DEFAULT_SETTINGS, **json.loads(path.read_text(encoding="utf-8"))}
        except Exception:
            return dict(DEFAULT_SETTINGS)

    def save(self, settings: dict[str, Any]) -> dict[str, Any]:
        data = {**self.load(), **settings, "updated_at": datetime.now(timezone.utc).isoformat()}
        settings_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return data


class PermissionsStore:
    @staticmethod
    def _real_mode_unlocked(data: dict[str, Any]) -> bool:
        lockdown_value = data.get("_real_lockdown_exit_code", 1)
        return (
            bool(data.get("_real_controlled_mode_unlocked"))
            and bool(data.get("_real_unlock_phrase_confirmed"))
            and int(1 if lockdown_value is None else lockdown_value) == 0
        )

    def _write_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = {
            **data,
            "_locked": LOCKED_PERMISSIONS,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        permissions_path().write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return payload

    def load(self) -> dict[str, Any]:
        path = permissions_path()
        if not path.exists():
            return dict(DEFAULT_PERMISSIONS)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            data = {**DEFAULT_PERMISSIONS, **raw}
        except Exception:
            data = dict(DEFAULT_PERMISSIONS)
        if not self._real_mode_unlocked(data):
            data["can_place_live_orders"] = False
        return data

    def save(self, permissions: dict[str, Any]) -> dict[str, Any]:
        data = {**self.load(), **permissions}
        if not self._real_mode_unlocked(data):
            data["can_place_live_orders"] = False
        payload = self._write_payload(data)
        return {k: v for k, v in payload.items() if k != "_locked"}

    def unlock_real_controlled_mode(self, phrase: str, lockdown_summary: dict[str, Any]) -> dict[str, Any]:
        phrase_ok = str(phrase or "").strip() == REAL_UNLOCK_PHRASE
        exit_code = lockdown_summary.get("exit_code", 1)
        open_positions = lockdown_summary.get("open_positions", 1)
        pending_orders = lockdown_summary.get("pending_orders", 1)
        clean_lockdown = (
            int(1 if exit_code is None else exit_code) == 0
            and int(1 if open_positions is None else open_positions) == 0
            and int(1 if pending_orders is None else pending_orders) == 0
            and not bool(lockdown_summary.get("external_magic0_exposure", True))
        )
        current_data = self.load()
        already_unlocked = self._real_mode_unlocked(current_data)

        if not phrase_ok:
            if already_unlocked:
                current_data["_unlock_error"] = "confirmation_phrase_mismatch"
                return self._write_payload(current_data)
            else:
                data = self.lock_real_controlled_mode("unlock_phrase_mismatch")
                data["_unlock_error"] = "confirmation_phrase_mismatch"
                return data
        if not clean_lockdown:
            data = self.lock_real_controlled_mode("lockdown_not_clean")
            data["_unlock_error"] = "verify_mt5_lockdown_not_clean"
            data["_lockdown_summary"] = lockdown_summary
            return data

        data = {
            **self.load(),
            "can_place_live_orders": True,
            "_real_controlled_mode_unlocked": True,
            "_real_unlock_phrase_confirmed": True,
            "_real_unlock_warning_acknowledged": True,
            "_real_lockdown_exit_code": int(lockdown_summary.get("exit_code", 0)),
            "_real_lockdown_verified_at": datetime.now(timezone.utc).isoformat(),
            "_real_lockdown_summary": lockdown_summary,
            "_real_mode": REAL_CONTROLLED_MODE,
        }
        return self._write_payload(data)

    def lock_real_controlled_mode(self, reason: str = "manual_lock") -> dict[str, Any]:
        data = {
            **self.load(),
            "can_place_live_orders": False,
            "_real_controlled_mode_unlocked": False,
            "_real_unlock_phrase_confirmed": False,
            "_real_unlock_warning_acknowledged": False,
            "_real_lock_reason": reason,
            "_real_mode": REAL_CONTROLLED_MODE,
        }
        return self._write_payload(data)


def __getattr__(name: str):
    if name == "RealModeService":
        from qader_app.services.real_mode_service import RealModeService

        return RealModeService
    raise AttributeError(name)

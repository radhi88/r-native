"""Settings export/import and app bootstrap."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qader_app.genome.gene_store import GeneStore
from qader_app.paths import data_dir, ensure_runtime_dirs
from qader_app.storage.audit_log import log_action
from qader_app.storage.profile_store import ProfileStore
from qader_app.storage.settings_store import PermissionsStore, SettingsStore


class ConfigService:
    def __init__(self):
        self.profile = ProfileStore()
        self.settings = SettingsStore()
        self.permissions = PermissionsStore()
        self.genes = GeneStore()

    def bootstrap(self) -> None:
        ensure_runtime_dirs()
        self.genes.ensure_defaults()
        if not (data_dir() / "permissions.json").exists():
            self.permissions.save(self.permissions.load())
        if not (data_dir() / "settings.json").exists():
            self.settings.save(self.settings.load())
        log_action("bootstrap", None, True, "runtime_dirs_ready", "config_service")

    def export_settings(self, output_path: str | Path) -> Path:
        output = Path(output_path)
        payload: dict[str, Any] = {
            "profile": self.profile.load(),
            "settings": self.settings.load(),
            "permissions": self.permissions.load(),
            "active_genome": self.genes.load_active(),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        log_action("export_settings", None, True, "exported", "config_service", result=str(output))
        return output

    def import_settings(self, input_path: str | Path) -> dict[str, Any]:
        path = Path(input_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "profile" in payload:
            self.profile.save(payload["profile"])
        if "settings" in payload:
            self.settings.save(payload["settings"])
        if "permissions" in payload:
            self.permissions.save(payload["permissions"])
        if "active_genome" in payload:
            self.genes.save_active(payload["active_genome"], "settings_import")
        log_action("import_settings", None, True, "imported", "config_service", result=str(path))
        return payload


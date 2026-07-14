"""kill_switch.py — Global emergency stop. Sets kill_switch=true in config."""
from __future__ import annotations
import yaml

def _active_config():
    from .config_loader import active_config_path
    return active_config_path()

def activate(reason: str = "manual") -> None:
    cfg = _active_config()
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["runtime"]["kill_switch"] = True
    cfg.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    from .config_loader import load
    load(force=True)
    print(f"[KILL SWITCH ACTIVATED] reason={reason}")

def deactivate() -> None:
    cfg = _active_config()
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["runtime"]["kill_switch"] = False
    cfg.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    from .config_loader import load
    load(force=True)
    print("[KILL SWITCH DEACTIVATED]")

def is_active() -> bool:
    from .config_loader import is_kill_switch
    return is_kill_switch()

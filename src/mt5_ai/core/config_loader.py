"""config_loader.py — Loads and validates trading_runtime.yaml."""
from __future__ import annotations
import os
import yaml
from pathlib import Path

def _default_config_path() -> Path:
    # 1. Explicit env-var override — try all known root env vars
    for env_key in ("FRIDAY_PROJECT_ROOT", "FRIDAY_ROOT", "JARVIS_PROJECT_ROOT", "QADER_ROOT"):
        env = os.getenv(env_key)
        if env:
            candidate = Path(env).resolve() / "config" / "trading_runtime.yaml"
            if candidate.exists():
                return candidate

    # 2. Walk up directory tree from this file
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "trading_runtime.yaml"
        if candidate.exists():
            return candidate
    return here.parents[3] / "config" / "trading_runtime.yaml"

_DEFAULT_CONFIG = _default_config_path()
_CONFIG_FILE = _DEFAULT_CONFIG
_cache: dict | None = None

def use_config(path: str | Path) -> None:
    """Override active config file. Call before any pipeline use."""
    global _CONFIG_FILE, _cache
    _CONFIG_FILE = Path(path)
    _cache = None

def reset_config() -> None:
    """Restore default config file."""
    global _CONFIG_FILE, _cache
    _CONFIG_FILE = _DEFAULT_CONFIG
    _cache = None

def active_config_path() -> Path:
    """Return the config file currently used by the runtime."""
    return _CONFIG_FILE

def load(force: bool = False) -> dict:
    global _cache
    if _cache is None or force:
        with _CONFIG_FILE.open(encoding="utf-8") as f:
            _cache = yaml.safe_load(f)
    return _cache

def get(key: str, default=None):
    """Dot-notation access: get('risk.max_lot')"""
    parts = key.split(".")
    node = load()
    for p in parts:
        if not isinstance(node, dict):
            return default
        node = node.get(p, default)
    return node

def is_live_allowed() -> bool:
    cfg = load()
    return (cfg.get("runtime", {}).get("mode") == "LIVE" and
            cfg.get("runtime", {}).get("allow_live_trading") is True and
            not cfg.get("runtime", {}).get("kill_switch", False))

def is_real_controlled_mode() -> bool:
    cfg = load()
    return cfg.get("runtime", {}).get("mode") == "REAL_CONTROLLED_MODE"

def is_real_controlled_allowed() -> bool:
    cfg = load()
    runtime = cfg.get("runtime", {})
    execution = cfg.get("execution", {})
    return (
        runtime.get("mode") == "REAL_CONTROLLED_MODE"
        and runtime.get("allow_live_trading") is True
        and execution.get("simulate_only") is False
        and execution.get("dry_run") is False
        and not runtime.get("kill_switch", False)
    )

def is_kill_switch() -> bool:
    return load().get("runtime", {}).get("kill_switch", False)

def is_dry_run() -> bool:
    cfg = load()
    return (cfg.get("runtime", {}).get("mode") == "DRY_RUN" or
            cfg.get("execution", {}).get("simulate_only") is True or
            cfg.get("execution", {}).get("dry_run") is True)

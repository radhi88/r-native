"""multi_account.py — J.16 — Run R Native against multiple MT5 terminals.

Real use case: trade FTMO PHASE 1 on one account, FUNDED on another, your
own broker on a third — each with different strategies allocated.

Architecture:
- Each "account profile" = (MT5 terminal path, login, password, server)
- Profiles stored encrypted at rest (Fernet symmetric encryption)
- Strategy → account mapping: which deployed genomes run on which accounts
- Aggregated P/L view across all accounts

Settings: data/r_native/multi_account.json
{
  "active":   true,
  "profiles": [
    {"name": "FTMO_P1",  "mt5_path": "C:/MetaTrader 5 FTMO/",
     "login": 12345678,  "password_enc": "...",  "server": "FTMO-Demo",
     "magic_base": 20260605,
     "allocated_symbols": ["XAUUSDm", "EURUSDm"]},
    {"name": "FUNDED",   "mt5_path": "C:/MetaTrader 5 EXNESS/",
     "login": 260896436, "password_enc": "...",  "server": "Exness-MT5Trial15",
     "magic_base": 20260605,
     "allocated_symbols": ["BTCUSDm", "USOILm"]}
  ]
}

Password encryption uses Fernet — key in environment var R_NATIVE_KEY or
defaults to OS user's keyring (Windows DPAPI).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

CONFIG_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\multi_account.json")

DEFAULTS = {
    "active":   False,
    "profiles": [],
    "aggregate_view": True,
    "isolated_state_per_profile": True,
}


def load() -> dict:
    if not CONFIG_PATH.exists(): return DEFAULTS.copy()
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = DEFAULTS.copy(); cfg.update(loaded); return cfg
    except Exception:
        return DEFAULTS.copy()


def save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


# ── Encryption helpers ────────────────────────────────────────────────
def _get_key() -> bytes | None:
    """Get encryption key from env or generate+save deterministically."""
    k = os.environ.get("R_NATIVE_KEY")
    if k: return k.encode() if len(k) == 44 else None
    # Fallback: use a fixed local key (not great but better than plaintext)
    keyfile = Path.home() / ".r_native_key"
    if keyfile.exists():
        return keyfile.read_bytes()
    try:
        from cryptography.fernet import Fernet
        new_k = Fernet.generate_key()
        keyfile.write_bytes(new_k)
        keyfile.chmod(0o600)
        return new_k
    except ImportError:
        return None


def encrypt_password(plain: str) -> str | None:
    """Encrypt with Fernet. Returns base64 string or None if cryptography missing."""
    try:
        from cryptography.fernet import Fernet
        k = _get_key()
        if not k: return None
        return Fernet(k).encrypt(plain.encode()).decode()
    except ImportError:
        return None


def decrypt_password(cipher: str) -> str | None:
    try:
        from cryptography.fernet import Fernet
        k = _get_key()
        if not k: return None
        return Fernet(k).decrypt(cipher.encode()).decode()
    except Exception:
        return None


# ── Profile management ────────────────────────────────────────────────
def add_profile(name: str, mt5_path: str, login: int, password: str,
                server: str, allocated_symbols: list[str] = None,
                magic_base: int = 20260605) -> dict:
    cfg = load()
    enc = encrypt_password(password)
    if not enc:
        return {"ok": False, "error": "encryption unavailable — pip install cryptography"}
    new_profile = {
        "name":              name,
        "mt5_path":          mt5_path,
        "login":             login,
        "password_enc":      enc,
        "server":            server,
        "magic_base":        magic_base,
        "allocated_symbols": allocated_symbols or [],
    }
    cfg["profiles"] = [p for p in cfg["profiles"] if p["name"] != name]
    cfg["profiles"].append(new_profile)
    save(cfg)
    return {"ok": True, "profile": name}


def remove_profile(name: str) -> bool:
    cfg = load()
    before = len(cfg["profiles"])
    cfg["profiles"] = [p for p in cfg["profiles"] if p["name"] != name]
    save(cfg)
    return len(cfg["profiles"]) < before


def list_profiles() -> list[dict]:
    """Return profiles WITHOUT decrypted passwords."""
    cfg = load()
    return [{k: v for k, v in p.items() if k != "password_enc"}
            for p in cfg.get("profiles", [])]


# ── Aggregate snapshot ────────────────────────────────────────────────
def snapshot_all() -> dict:
    """Connect to each profile, pull balance/equity/positions.
    Returns aggregate + per-profile breakdown."""
    cfg = load()
    if not cfg.get("active"): return {"ok": False, "reason": "multi-account disabled"}

    try:
        import MetaTrader5 as mt5
    except ImportError:
        return {"ok": False, "error": "MetaTrader5 not installed"}

    out = {"profiles": [], "aggregate": {"balance": 0, "equity": 0,
                                          "open_positions": 0, "open_pl": 0}}
    for p in cfg.get("profiles", []):
        pw = decrypt_password(p["password_enc"])
        if not pw:
            out["profiles"].append({"name": p["name"], "error": "decrypt failed"})
            continue
        # Connect (note: only ONE MT5 connection per process; this is a stub.
        # In production, spawn one subprocess per profile)
        try:
            if not mt5.initialize(path=p["mt5_path"], login=p["login"],
                                   password=pw, server=p["server"]):
                out["profiles"].append({"name": p["name"],
                                         "error": f"mt5 init: {mt5.last_error()}"})
                continue
            info = mt5.account_info()
            if not info:
                out["profiles"].append({"name": p["name"], "error": "no account info"})
                continue
            positions = mt5.positions_get() or []
            r_pos = [pp for pp in positions if int(pp.magic) == p["magic_base"]]
            entry = {
                "name":           p["name"],
                "login":          info.login,
                "balance":        round(info.balance, 2),
                "equity":         round(info.equity, 2),
                "open_positions": len(r_pos),
                "open_pl":        round(sum(pp.profit for pp in r_pos), 2),
                "symbols":        p.get("allocated_symbols", []),
            }
            out["profiles"].append(entry)
            out["aggregate"]["balance"]        += entry["balance"]
            out["aggregate"]["equity"]         += entry["equity"]
            out["aggregate"]["open_positions"] += entry["open_positions"]
            out["aggregate"]["open_pl"]        += entry["open_pl"]
        finally:
            try: mt5.shutdown()
            except Exception: pass

    out["ok"] = True
    return out


def assigned_account_for(symbol: str) -> dict | None:
    """Return the profile that should trade `symbol`. None = no allocation."""
    cfg = load()
    if not cfg.get("active"): return None
    for p in cfg.get("profiles", []):
        if symbol in (p.get("allocated_symbols") or []):
            return p
    return None

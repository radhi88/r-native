"""smart_modes.py — Algory-style auto-tuning for campaign config.

When user enables a smart mode, the campaign engine chooses parameters
based on the symbol/TF/data context instead of fixed values.

Used by CampaignWorker.run() before instantiating CampaignConfig.

Settings stored in data/r_native/smart_modes.json:
{
  "auto_bars":   true,   // pick bar count from symbol activity
  "auto_trades": true,   // adapt purge.min_trades to TF
  "auto_oos":    true,   // pick OOS window from data length
  "power_mode":  "Medium"   // Low/Medium/High → 33/66/95% CPU
}
"""
from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

CONFIG_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\smart_modes.json")

DEFAULTS = {
    "auto_bars":   True,
    "auto_trades": True,
    "auto_oos":    True,
    "power_mode":  "Medium",  # Low / Medium / High
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


# ── Auto-tuners ─────────────────────────────────────────────────────────
def auto_bars(symbol: str, tf: str, base: int = 4000) -> int:
    """Pick a sensible bar count from TF granularity.
    Smaller TFs → more bars; H1+ → fewer bars cover same calendar span."""
    tf_bars = {
        "M1":  10000, "M5":  6000, "M15": 4000,
        "M30": 3000,  "H1":  2000, "H2":  1500,
        "H4":  1000,  "D1":  500,
    }
    n = tf_bars.get(tf, base)
    # Crypto: a bit less since spread/slippage is brutal — campaigns saturate fast
    if "BTC" in symbol or "ETH" in symbol: n = int(n * 0.6)
    # Indices: more conservative (lower trade frequency)
    if any(x in symbol for x in ("US30", "USTEC", "US500", "DE30")): n = int(n * 0.7)
    return n


def auto_min_trades(tf: str, base: int = 40) -> int:
    """Smaller TFs require MORE trades for statistical significance."""
    return {
        "M1": 100, "M5": 60, "M15": 40,
        "M30": 30, "H1": 25, "H2": 20, "H4": 15, "D1": 10,
    }.get(tf, base)


def auto_oos_split(bars_available: int) -> float:
    """Pick OOS fraction based on data length.
    More data → can afford larger OOS portion."""
    if bars_available < 1000: return 0.20   # tiny data: tiny OOS to keep IS viable
    if bars_available < 3000: return 0.30
    if bars_available < 6000: return 0.33   # Algory default
    return 0.40                              # plenty of data: bigger OOS test


def workers_for_power(power_mode: str | None = None) -> int:
    """Map Low/Medium/High to N CPU cores."""
    if power_mode is None:
        power_mode = load().get("power_mode", "Medium")
    cores = mp.cpu_count() or 4
    pct = {"Low": 0.33, "Medium": 0.66, "High": 0.95}.get(power_mode, 0.66)
    n = max(1, int(cores * pct))
    return n


# ── Apply smart config to a base CampaignConfig ──────────────────────
def apply_smart(symbol: str, tf: str, base_pg: int = 200, base_gens: int = 3,
                cfg: dict | None = None) -> dict:
    """Return a dict of overrides ready to splat into CampaignConfig."""
    cfg = cfg or load()
    out = {
        "n_workers": workers_for_power(cfg.get("power_mode")),
    }
    if cfg.get("auto_bars"):
        out["bars"] = auto_bars(symbol, tf)
    if cfg.get("auto_trades"):
        # CampaignConfig doesn't directly have min_trades — it's in purge.
        # Just expose for downstream use
        out["_auto_min_trades"] = auto_min_trades(tf)
    if cfg.get("auto_oos"):
        out["train_split"] = round(1.0 - auto_oos_split(out.get("bars", 4000)), 2)
    return out

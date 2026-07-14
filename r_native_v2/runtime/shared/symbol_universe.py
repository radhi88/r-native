"""
symbol_universe.py — the SINGLE source of truth reader for the tradable symbol set (F2-a.1).

Replaces the 4+ divergent hardcoded symbol lists (genome_academy / brain_v1 /
chart_signal_writer / footprint_feeder). Engines should import this instead of a local list.

F2-a.1 scope: this module is created but NOT yet wired into any engine — zero behavior change.
Per-engine migration happens later, each step gated + parallel-run (set-equality) via agent_bus.

Read-only: never writes the universe file (writes are F2-b discovery / manual edits).
Fail-safe: if symbol_universe.json is missing or corrupt, returns a built-in DEFAULT so
nothing breaks.
"""
from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent          # .../MT5/r_native_v2
UNIVERSE_FILE = _ROOT / "data" / "symbol_universe.json"

# Built-in fallback = the legacy genome_academy gauntlet list (so evolution still has a set
# to work on even if the universe file is absent). All treated enabled in the fallback ONLY
# to preserve prior behavior; the real policy lives in symbol_universe.json.
_DEFAULT = [
    {"symbol": s, "market": "MT5", "enabled": True, "always_open": (s == "BTCUSDm")}
    for s in ["XAUUSDm", "EURUSDm", "GBPUSDm", "GBPJPYm", "BTCUSDm", "USDJPYm", "XAGUSDm"]
]


def _load_raw() -> list[dict]:
    try:
        data = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))
        syms = data.get("symbols")
        if isinstance(syms, list) and syms:
            return syms
    except (OSError, ValueError):
        pass
    return _DEFAULT


def get_symbols(market: str | None = None, enabled_only: bool = True,
                always_open: bool | None = None, signals: bool | None = None,
                gauntlet: bool | None = None) -> list[dict]:
    """Return symbol dicts, filtered.
    enabled_only=True (default) => only TRADABLE symbols (enabled flag).
    signals=True => only symbols whose analysis is DISPLAYED (separate from trading).
    gauntlet=True => only symbols in genome_academy's GA fitness basket (separate from trading).
    Pass enabled_only=False with signals/gauntlet=True to get that set regardless of trading."""
    out = []
    for s in _load_raw():
        if enabled_only and not s.get("enabled", False):
            continue
        if signals is not None and bool(s.get("signals", False)) != signals:
            continue
        if gauntlet is not None and bool(s.get("gauntlet", False)) != gauntlet:
            continue
        if market is not None and s.get("market") != market:
            continue
        if always_open is not None and bool(s.get("always_open", False)) != always_open:
            continue
        out.append(s)
    return out


def signal_symbols(market: str | None = None) -> list[str]:
    """Symbols whose analysis/signal is displayed (chart_signal_writer set) — NOT trading."""
    return [s["symbol"] for s in get_symbols(market=market, enabled_only=False, signals=True)]


def gauntlet_symbols(market: str | None = None) -> list[str]:
    """Symbols in genome_academy's GA fitness basket (generalization benchmark) — NOT trading."""
    return [s["symbol"] for s in get_symbols(market=market, enabled_only=False, gauntlet=True)]


def get_symbol(symbol: str) -> dict | None:
    for s in _load_raw():
        if s.get("symbol") == symbol:
            return s
    return None


def trading_symbols(market: str | None = None) -> list[str]:
    """Convenience: the list of enabled symbol names (what should actually trade)."""
    return [s["symbol"] for s in get_symbols(market=market, enabled_only=True)]


def all_symbols() -> list[str]:
    """Every symbol in the universe (enabled or not) — for display/gauntlet enumeration."""
    return [s["symbol"] for s in _load_raw()]


if __name__ == "__main__":  # quick self-check
    print("universe file:", UNIVERSE_FILE, "exists:", UNIVERSE_FILE.exists())
    print("trading (enabled):", trading_symbols())
    print("all:", all_symbols())
    print("crypto 24/7:", [s["symbol"] for s in get_symbols(always_open=True, enabled_only=False)])

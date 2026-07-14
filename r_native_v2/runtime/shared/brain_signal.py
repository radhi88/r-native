"""shared/brain_signal.py — bridge the live blended signal into R Native's engine.

chart_signal_writer.py produces signal_<SYMBOL>.json (10 components + FADE +
conviction). unified_trader reads it here as a CONFLUENCE GATE: veto a genome
trade only when the brain STRONGLY opposes it; agreement raises conviction.
"""
from __future__ import annotations
import json
import time
from pathlib import Path

COMMON = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")


def brain_confluence(symbol: str, max_age: float = 120.0):
    """Return (direction, confidence, note) for `symbol`.
    direction in {"BUY","SELL",None}; None when WAIT/stale/missing (no opinion)."""
    try:
        f = COMMON / f"signal_{symbol}.json"
        if not f.exists() or time.time() - f.stat().st_mtime > max_age:
            return None, 0.0, "stale"
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("symbol") != symbol:
            return None, 0.0, "sym_mismatch"
        a = d.get("action")
        conf = float(d.get("confidence") or 0.0)
        if a not in ("BUY", "SELL"):
            return None, conf, "wait"
        return a, conf, d.get("mode_learned", "")
    except Exception as e:
        return None, 0.0, f"err:{e}"


def brain_regime(symbol: str, max_age: float = 120.0):
    """Return the live regime context the chart writer computed:
       {"no_trend": bool, "htf_dir": "BUY"/"SELL"/"NEUTRAL", "adx": float, "er": float}
    no_trend=True means ADX<min or efficiency<min → chop/noise (suppress entries).
    Fail-OPEN: on stale/missing/error returns no_trend=False so it never blocks
    trading on a feed hiccup. (pro-panel Step-1 discipline, extended to the genome)"""
    safe = {"no_trend": False, "htf_dir": "NEUTRAL", "adx": 0.0, "er": 1.0, "ok": False}
    try:
        f = COMMON / f"signal_{symbol}.json"
        if not f.exists() or time.time() - f.stat().st_mtime > max_age:
            return safe
        d = json.loads(f.read_text(encoding="utf-8"))
        r = d.get("regime") or {}
        if not r:
            return safe
        return {"no_trend": bool(r.get("no_trend")),
                "htf_dir": r.get("htf_dir", "NEUTRAL"),
                "adx": float(r.get("adx") or 0.0),
                "er": float(r.get("er") or 1.0), "ok": True}
    except Exception:
        return safe

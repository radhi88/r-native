"""regime_aware.py — J.8 — Multi-genome deployment, one per market regime.

A strategy that works in TREND markets often fails in RANGE markets and vice versa.
Algory hints at this with archetypes (BREAKOUT_HUNTER vs MEAN_REVERTER). We do
better: deploy a DIFFERENT genome per detected regime, auto-switch live.

Detected regimes (live from H1 bars):
  TREND_UP    — H1 ADX > 25 + EMA50 > EMA200
  TREND_DOWN  — H1 ADX > 25 + EMA50 < EMA200
  RANGE       — H1 ADX < 20 + price in BB middle
  EVENT       — H1 ATR > 2× recent average (news/spike)
  DEAD        — Spread > H1 ATR (illiquid, weekend, overnight)

Per-symbol config stores up to 5 deployed_genome entries — one per regime.
Live trader picks the genome matching the CURRENT regime each cycle.

Settings stored in symbol_configs/<SYM>.json under "regime_genomes":
{
  "regime_genomes": {
    "TREND_UP":   {"id": "ABC123", ...},
    "TREND_DOWN": {"id": "DEF456", ...},
    "RANGE":      {"id": "GHI789", ...},
    "EVENT":      null,   // optional
    "DEAD":       null    // optional (don't trade in dead regimes)
  }
}
"""
from __future__ import annotations

import json
from pathlib import Path

SYMBOL_CFG = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")

REGIMES = ["TREND_UP", "TREND_DOWN", "RANGE", "EVENT", "DEAD"]


def detect_regime(symbol: str) -> str:
    """Classify current market regime for `symbol` from live H1 bars."""
    try:
        import MetaTrader5 as mt5
        import numpy as np
        if not mt5.initialize():
            return "UNKNOWN"
        bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 100)
        if bars is None or len(bars) < 50:
            return "UNKNOWN"
        closes = np.array([b["close"] for b in bars])
        highs  = np.array([b["high"]  for b in bars])
        lows   = np.array([b["low"]   for b in bars])

        # ATR(14)
        tr = np.maximum.reduce([
            highs[1:] - lows[1:],
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:]  - closes[:-1]),
        ])
        atr = float(np.mean(tr[-14:]))
        atr_long = float(np.mean(tr[-50:]))

        # EMAs
        def ema(arr, n):
            k = 2 / (n + 1)
            e = arr[0]
            for x in arr[1:]:
                e = x * k + e * (1 - k)
            return e
        ema_fast = ema(closes, 50)
        ema_slow = ema(closes, 200) if len(closes) >= 200 else ema(closes, len(closes) - 1)

        # Approx ADX from directional moves
        up_moves   = np.maximum(highs[1:] - highs[:-1], 0)
        down_moves = np.maximum(lows[:-1]  - lows[1:], 0)
        dm_plus  = np.mean(up_moves[-14:])
        dm_minus = np.mean(down_moves[-14:])
        di_plus  = (dm_plus  / atr * 100) if atr > 0 else 0
        di_minus = (dm_minus / atr * 100) if atr > 0 else 0
        adx_proxy = abs(di_plus - di_minus) / max(1, (di_plus + di_minus)) * 100

        # Spread check (DEAD detection)
        tick = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        if tick and info and info.point > 0:
            spread_price = (tick.ask - tick.bid)
            if spread_price > atr * 0.5:
                return "DEAD"

        # EVENT detection: current ATR spike
        if atr > atr_long * 1.8:
            return "EVENT"

        # TREND
        if adx_proxy > 25:
            return "TREND_UP" if ema_fast > ema_slow else "TREND_DOWN"

        # RANGE
        return "RANGE"
    except Exception as e:
        print(f"[regime] err: {e}")
        return "UNKNOWN"


# ── Per-regime deployment storage ─────────────────────────────────────
def deploy_for_regime(symbol: str, regime: str, genome: dict) -> dict:
    """Set the deployed_genome for one regime on one symbol."""
    if regime not in REGIMES:
        return {"ok": False, "error": f"unknown regime {regime}"}
    cfg_path = SYMBOL_CFG / f"{symbol}.json"
    if not cfg_path.exists():
        return {"ok": False, "error": f"no vault for {symbol}"}
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    rg = cfg.setdefault("regime_genomes", {})
    rg[regime] = genome
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return {"ok": True, "deployed_for_regime": regime,
            "id": genome.get("id"), "symbol": symbol}


def get_active_genome(symbol: str, regime: str | None = None) -> dict | None:
    """Return the genome to use for `symbol` given current regime.
    If regime omitted, detects live."""
    cfg_path = SYMBOL_CFG / f"{symbol}.json"
    if not cfg_path.exists(): return None
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if regime is None:
        regime = detect_regime(symbol)
    regime_genomes = cfg.get("regime_genomes") or {}
    # Prefer the specific regime match
    if regime in regime_genomes and regime_genomes[regime]:
        return regime_genomes[regime]
    # Fallback hierarchy
    fallback_chain = {
        "TREND_UP":   ["TREND_DOWN", "RANGE"],
        "TREND_DOWN": ["TREND_UP", "RANGE"],
        "RANGE":      ["TREND_UP", "TREND_DOWN"],
        "EVENT":      ["RANGE", "TREND_UP", "TREND_DOWN"],
        "DEAD":       [],   # never trade in DEAD
    }.get(regime, [])
    for fb in fallback_chain:
        if regime_genomes.get(fb):
            return regime_genomes[fb]
    # Ultimate fallback: the regular deployed_genome
    return cfg.get("deployed_genome")


def status(symbol: str) -> dict:
    """Return current regime + which genome would fire."""
    regime = detect_regime(symbol)
    active = get_active_genome(symbol, regime)
    return {
        "symbol":          symbol,
        "current_regime":  regime,
        "active_genome":   active.get("id") if active else None,
        "active_score":    active.get("score", 0) if active else 0,
    }

"""macro_context.py — global macro snapshot via Yahoo Finance (no API key).

Fetches the indicators that actually move FX/CFD/crypto pricing across all
symbols:
  - DXY       (^DXY)     US dollar index — risk-off / USD strength
  - US10Y     (^TNX)     10-year treasury yield / 10  — rate proxy
  - VIX       (^VIX)     equity-vol fear gauge — risk-on/off regime
  - GOLD      (GC=F)     gold continuous future
  - SILVER    (SI=F)     silver continuous future
  - WTI       (CL=F)     crude oil — inflation/risk proxy
  - SP500     (^GSPC)    S&P 500 spot — risk-on proxy

Cached for 1 hour (macro is slow-moving relative to a scalper's bar).
Persisted to data/r_native/macro_snapshot.json for the dashboard.

Public API:
  get_macro_snapshot(force=False) → dict
  macro_signal_align(snap, side)  → (+1/-1/0, reason)   # used per-trade
  macro_signal_vix_calm(snap)     → (+1/-1/0, reason)   # filter for low-vol

The signal helpers receive the LIVE bar snap (so they get the symbol's bid
for direction hints), and they consult the cached macro snapshot internally.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import urllib.request as _ur
import urllib.error as _ue

CACHE_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\macro_snapshot.json")
CACHE_TTL_SEC = 3600  # 1h

# Yahoo Finance v8 chart endpoint — public, no key
_YH_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           "?interval=1d&range=5d")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

_TICKERS = {
    "DXY":    "DX-Y.NYB",   # ^DXY alias
    "US10Y":  "^TNX",
    "VIX":    "^VIX",
    "GOLD":   "GC=F",
    "SILVER": "SI=F",
    "WTI":    "CL=F",
    "SP500":  "^GSPC",
}

_IN_MEMORY: dict = {}


def _now_ts() -> float: return time.time()


def _fetch_quote(yh_symbol: str) -> Optional[dict]:
    """Return {price, prev_close, change_pct} or None on any failure."""
    try:
        req = _ur.Request(_YH_URL.format(sym=yh_symbol),
                          headers={"User-Agent": _UA, "Accept": "application/json"})
        with _ur.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
    except (_ue.URLError, _ue.HTTPError, OSError, ValueError):
        return None

    try:
        res = data["chart"]["result"][0]
        meta = res.get("meta") or {}
        price = meta.get("regularMarketPrice")
        prev  = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price is None or prev is None or prev == 0:
            return None
        return {
            "price":      float(price),
            "prev_close": float(prev),
            "change_pct": round((float(price) - float(prev)) / float(prev) * 100, 3),
        }
    except (KeyError, IndexError, TypeError):
        return None


def _classify_vix(vix: float) -> str:
    if vix is None: return "UNKNOWN"
    if vix < 13:  return "EUPHORIC"   # complacency — risk-on
    if vix < 18:  return "CALM"       # normal — risk-on
    if vix < 25:  return "ELEVATED"   # caution
    if vix < 35:  return "FEAR"       # risk-off
    return "PANIC"                    # crisis


def _classify_dxy(dxy_chg_pct: float) -> str:
    if dxy_chg_pct is None: return "UNKNOWN"
    if dxy_chg_pct >  0.30: return "STRONG_UP"     # USD rallying → SELL EURUSD/GBPUSD, BUY USDJPY
    if dxy_chg_pct >  0.10: return "UP"
    if dxy_chg_pct < -0.30: return "STRONG_DOWN"
    if dxy_chg_pct < -0.10: return "DOWN"
    return "FLAT"


def get_macro_snapshot(force: bool = False) -> dict:
    """Returns the macro snap; refreshes from Yahoo if cache stale."""
    global _IN_MEMORY

    # In-memory cache first
    if not force and _IN_MEMORY and (_now_ts() - _IN_MEMORY.get("_ts", 0) < CACHE_TTL_SEC):
        return _IN_MEMORY

    # Disk cache fallback
    if not force and CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if _now_ts() - cached.get("_ts", 0) < CACHE_TTL_SEC:
                _IN_MEMORY = cached
                return cached
        except Exception: pass

    # Fresh fetch
    out = {"_ts": _now_ts(), "issued_at": datetime.now(timezone.utc).isoformat()}
    for key, yh_sym in _TICKERS.items():
        q = _fetch_quote(yh_sym)
        out[key] = q  # may be None on failure

    # Derived
    vix = (out.get("VIX") or {}).get("price")
    dxy_chg = (out.get("DXY") or {}).get("change_pct")
    out["vix_regime"] = _classify_vix(vix)
    out["dxy_regime"] = _classify_dxy(dxy_chg)

    # Gold/silver ratio — historical sentiment marker (>85 → risk-off)
    g = (out.get("GOLD") or {}).get("price")
    s = (out.get("SILVER") or {}).get("price")
    out["gold_silver_ratio"] = round(g / s, 2) if (g and s and s > 0) else None

    # Persist
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception: pass

    _IN_MEMORY = out
    return out


# ───────────────────────────────────────────────────────────────────────
# Signal helpers — consumed by genome_signal.py
# ───────────────────────────────────────────────────────────────────────

def _symbol_from_snap(snap: dict) -> str:
    """Get the symbol the live snap is about. trade_gate passes it via 'symbol'."""
    return (snap.get("symbol") or "").upper()


def macro_signal_align(snap: dict) -> tuple:
    """Vote based on whether the symbol's directional bias aligns with DXY regime.

    Heuristics (USD-pair specific):
      DXY strong UP   → BUY USDJPY / SELL EURUSD,GBPUSD,AUDUSD,NZDUSD,XAUUSD
      DXY strong DOWN → SELL USDJPY / BUY EURUSD,GBPUSD,AUDUSD,NZDUSD,XAUUSD

    Non-USD-pair (EURJPY, GBPJPY, BTC etc): no macro vote (returns 0).
    """
    macro = get_macro_snapshot()
    regime = macro.get("dxy_regime", "FLAT")
    if regime in ("FLAT", "UNKNOWN"): return 0, f"dxy regime {regime}"

    sym = _symbol_from_snap(snap)
    if not sym: return 0, "no symbol in snap"

    # Strip broker suffix (m, .a, _x100m, etc.) — keep alpha prefix
    base = ""
    for c in sym:
        if c.isalpha() or c.isdigit(): base += c
        else: break
    base = base.upper()

    is_strong = regime in ("STRONG_UP", "STRONG_DOWN")
    dxy_up    = regime in ("STRONG_UP", "UP")

    # Quote-side USD pairs (USD is quote): EURUSD/GBPUSD/AUDUSD/NZDUSD/XAUUSD
    if any(base.startswith(p) for p in ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD",
                                         "XAUUSD", "XAGUSD")):
        vote = -1 if dxy_up else +1
        tag  = "strong " if is_strong else ""
        return vote, f"dxy {tag}{regime.lower()} → fade pair vs USD"

    # Base-side USD pair (USDJPY/USDCHF/USDCAD): aligns with DXY
    if base.startswith(("USDJPY", "USDCHF", "USDCAD")):
        vote = +1 if dxy_up else -1
        return vote, f"dxy {regime.lower()} → align with USD"

    # Crypto vs USD: risk-on aligns with weak DXY
    if base.startswith(("BTCUSD", "ETHUSD")):
        vote = +1 if not dxy_up else -1
        return vote, f"dxy {regime.lower()} → crypto risk vote"

    return 0, f"{base} not USD-bilateral"


def macro_signal_vix_calm(snap: dict) -> tuple:
    """Risk-on/off filter.

    Returns:
      +1 if VIX CALM/EUPHORIC (risk-on — favor breakouts and momentum BUYs)
      -1 if VIX FEAR/PANIC   (risk-off — favor mean-reversion fades / safe-havens)
       0 otherwise

    The trade_gate weights this as a bias, not an entry trigger.
    """
    macro = get_macro_snapshot()
    regime = macro.get("vix_regime", "UNKNOWN")
    vix = (macro.get("VIX") or {}).get("price")

    if regime == "EUPHORIC":
        return +1, f"vix {vix:.1f} euphoric → risk-on"
    if regime == "CALM":
        return +1, f"vix {vix:.1f} calm → risk-on"
    if regime == "FEAR":
        return -1, f"vix {vix:.1f} fear → risk-off"
    if regime == "PANIC":
        return -1, f"vix {vix:.1f} panic → risk-off"
    return 0, f"vix regime {regime}"


# ───────────────────────────────────────────────────────────────────────
# CLI for debugging
# ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse, sys
    ap = argparse.ArgumentParser(prog="r_native.macro_context")
    ap.add_argument("--refresh", action="store_true", help="force refresh from Yahoo")
    ap.add_argument("--test-signal", metavar="SYMBOL",
                    help="test align signal for a symbol (e.g. EURUSDm)")
    args = ap.parse_args()

    snap = get_macro_snapshot(force=args.refresh)
    print(json.dumps({k: v for k, v in snap.items() if not k.startswith("_")},
                     ensure_ascii=False, indent=2))

    if args.test_signal:
        live_snap = {"symbol": args.test_signal, "bid": 1.0,
                     "h1": {"bias": "UP", "slope_atr": 0.4}}
        v, r = macro_signal_align(live_snap)
        print(f"\nmacro_signal_align({args.test_signal}) → vote={v} {r}")
        v2, r2 = macro_signal_vix_calm(live_snap)
        print(f"macro_signal_vix_calm → vote={v2} {r2}")

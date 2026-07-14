"""vol_regime.py — the ONE secondary signal that tested REAL out-of-sample.

OOS study (see memory project_fractal_analog_oos): DIRECTION is a coin-flip (~50-53%),
but VOLATILITY/RANGE regime separates ~2:1 on XAU M15 (+0.05 R2 over naive). So we predict
HOW MUCH price will move, NOT which way. Use it to size the TARGET only:
  • expansion (هبوب)  → widen TP, let it run
  • contraction (انكماش) → tighten TP, take quick profit
  • normal (طبيعي)    → leave TP as-is

HONEST: this is NOT a buy/sell signal. It never decides direction. It only scales the
take-profit distance. Stop and risk are untouched by default. Reversible: delete the
advisory file and every reader falls back to ×1.0.
"""
from __future__ import annotations
import json, time
from pathlib import Path

_DD = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")


def _atr_series(rows, n: int = 14):
    """Wilder ATR series. rows: oldest->newest, each supports ['high']/['low']/['close']."""
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = float(rows[i]["high"]), float(rows[i]["low"]), float(rows[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < n:
        return []
    a = sum(trs[:n]) / n
    out = [a]
    for i in range(n, len(trs)):
        a = (a * (n - 1) + trs[i]) / n
        out.append(a)
    return out


def classify(rows, n: int = 14, lookback: int = 100) -> dict:
    """Classify the current volatility regime from OHLC rows (oldest->newest)."""
    atr = _atr_series(rows, n)
    if len(atr) < 20:
        return {"state": "unknown", "target_mult": 1.0, "stop_mult": 1.0,
                "note": "بيانات غير كافية", "n": n}
    cur = atr[-1]
    window = atr[-lookback:] if len(atr) >= lookback else atr
    srt = sorted(window)
    pct = sum(1 for x in srt if x <= cur) / len(srt)          # percentile rank of current ATR
    prior = atr[-11:-1] if len(atr) >= 11 else atr[:-1]
    med = sorted(prior)[len(prior) // 2] if prior else cur
    rising = cur > med * 1.05
    falling = cur < med * 0.95
    if pct >= 0.70 or (pct >= 0.55 and rising):
        state = "expansion"; tmult = 1.6 if pct >= 0.85 else 1.3; smult = 1.15
        note = "هبوب — وسّع الهدف، دعه يركض"
    elif pct <= 0.30 or (pct <= 0.45 and falling):
        state = "contraction"; tmult = 0.7; smult = 0.9
        note = "انكماش — خذ ربح سريع، هدف أضيق"
    else:
        state = "normal"; tmult = 1.0; smult = 1.0
        note = "مدى طبيعي"
    return {"state": state, "atr": round(cur, 5), "pctile": round(pct, 2),
            "rising": rising, "falling": falling,
            "target_mult": tmult, "stop_mult": smult, "note": note,
            "n": n, "lookback": len(window)}


def write_advisory(symbol: str, regime: dict) -> None:
    """Write a per-symbol advisory the live traders can optionally read (target scaling only)."""
    try:
        _DD.mkdir(parents=True, exist_ok=True)
        (_DD / f"vol_regime_{symbol}.json").write_text(
            json.dumps({**regime, "symbol": symbol, "ts": time.time()}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


def read_advisory(symbol: str, max_age: int = 600) -> dict:
    """Trader-side read. Returns the regime dict, or a neutral ×1.0 if missing/stale.
    Callers should apply ONLY target_mult to the take-profit distance."""
    try:
        d = json.loads((_DD / f"vol_regime_{symbol}.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("ts", 0)) > max_age:
            return {"state": "stale", "target_mult": 1.0, "stop_mult": 1.0}
        return d
    except Exception:
        return {"state": "none", "target_mult": 1.0, "stop_mult": 1.0}


def target_mult(symbol: str, max_age: int = 600) -> float:
    """Convenience: just the target multiplier (1.0 if missing/stale)."""
    try:
        return float(read_advisory(symbol, max_age).get("target_mult", 1.0))
    except Exception:
        return 1.0


if __name__ == "__main__":
    # quick self-test against live MT5 (XAU + BTC)
    import MetaTrader5 as mt5
    mt5.initialize()
    for sym, tf in (("XAUUSDm", mt5.TIMEFRAME_M15), ("BTCUSDm", mt5.TIMEFRAME_M5)):
        r = mt5.copy_rates_from_pos(sym, tf, 0, 200)
        if r is None:
            print(sym, "no bars"); continue
        rows = [{"high": x["high"], "low": x["low"], "close": x["close"]} for x in r]
        reg = classify(rows); write_advisory(sym, reg)
        print(sym, reg)
    mt5.shutdown()

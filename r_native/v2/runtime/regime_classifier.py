"""runtime/regime_classifier.py — Market Regime Detection.

Born 2026-05-28 after $30 loss in chop session.
Detects what market state we're in so traders can adapt.

REGIMES:
  TREND_UP    — ADX > 25, +DI > -DI, EMA 9>21>50
  TREND_DOWN  — ADX > 25, -DI > +DI, EMA 9<21<50
  CHOP        — ADX < 20, bouncing in range
  SPIKE       — Vol > 200% avg, ATR > 1.5× normal
  TRANSITION  — between regimes, ambiguous

Updates data/market_regime.json every 5s.
Traders read this and adjust strategy.

Run as background service alongside brain_v1.
"""
from __future__ import annotations
import MetaTrader5 as mt5
import json
import time
from datetime import datetime, timezone
from pathlib import Path

SYMBOL = "XAUUSDm"
OUTPUT = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\market_regime.json")
HISTORY = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\regime_history.jsonl")
POLL = 5.0


def _save(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(p)


def _append(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def calc_atr(rates, period=14):
    if len(rates) < period + 2: return 0
    trs = []
    for i in range(1, period + 1):
        if i + 1 >= len(rates): break
        tr1 = rates[i]["high"] - rates[i]["low"]
        tr2 = abs(rates[i]["high"] - rates[i+1]["close"])
        tr3 = abs(rates[i]["low"] - rates[i+1]["close"])
        trs.append(max(tr1, max(tr2, tr3)))
    return sum(trs) / len(trs) if trs else 0


def calc_adx(rates, period=14):
    if len(rates) < period * 2: return (0, 0, 0)
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, period + 1):
        if i + 1 >= len(rates): break
        up_move = rates[i]["high"] - rates[i+1]["high"]
        dn_move = rates[i+1]["low"] - rates[i]["low"]
        pdm = up_move if up_move > dn_move and up_move > 0 else 0
        mdm = dn_move if dn_move > up_move and dn_move > 0 else 0
        h, l, pc = rates[i]["high"], rates[i]["low"], rates[i+1]["close"]
        tr = max(h-l, abs(h-pc), abs(l-pc))
        plus_dm.append(pdm); minus_dm.append(mdm); trs.append(tr)
    atr = sum(trs) / period if trs else 0
    if atr == 0: return (0, 0, 0)
    p_di = 100 * sum(plus_dm) / period / atr
    m_di = 100 * sum(minus_dm) / period / atr
    dx = 100 * abs(p_di - m_di) / max(p_di + m_di, 1e-9)
    return (round(dx, 1), round(p_di, 1), round(m_di, 1))


def calc_ema(rates, period):
    if len(rates) < period: return 0
    k = 2 / (period + 1)
    ema = rates[period - 1]["close"]
    for i in range(period - 2, -1, -1):
        ema = rates[i]["close"] * k + ema * (1 - k)
    return ema


def classify():
    rates_m5 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 60)
    rates_m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 30)
    if rates_m5 is None or rates_m1 is None: return None
    rates_m5 = [dict(b._asdict()) if hasattr(b, '_asdict') else {k: b[k] for k in b.dtype.names} for b in rates_m5]
    rates_m1 = [dict(b._asdict()) if hasattr(b, '_asdict') else {k: b[k] for k in b.dtype.names} for b in rates_m1]

    adx_m5, plus_di, minus_di = calc_adx(rates_m5, 14)
    atr_m5 = calc_atr(rates_m5, 14)
    atr_m1 = calc_atr(rates_m1, 14)

    # EMA alignment
    ema9_m5 = calc_ema(rates_m5, 9)
    ema21_m5 = calc_ema(rates_m5, 21)
    ema50_m5 = calc_ema(rates_m5, 50)
    ema_up = (ema9_m5 > ema21_m5 > ema50_m5)
    ema_dn = (ema9_m5 < ema21_m5 < ema50_m5)

    # Volume spike
    recent_vol = sum(b["tick_volume"] for b in rates_m1[:5]) / 5
    prior_vol = sum(b["tick_volume"] for b in rates_m1[5:15]) / 10 if len(rates_m1) >= 15 else recent_vol
    vol_ratio = recent_vol / max(prior_vol, 1)

    # Range
    recent_range = max(b["high"] for b in rates_m5[:20]) - min(b["low"] for b in rates_m5[:20])

    # CLASSIFY
    regime = "TRANSITION"
    reason = ""

    if vol_ratio > 2.0 and atr_m1 > 0:
        regime = "SPIKE"
        reason = f"vol spike {vol_ratio:.1f}× + ATR_M1 {atr_m1:.2f}"
    elif adx_m5 >= 25:
        if plus_di > minus_di and ema_up:
            regime = "TREND_UP"
            reason = f"ADX {adx_m5}, +DI {plus_di}>{-minus_di} -DI, EMA stacked UP"
        elif minus_di > plus_di and ema_dn:
            regime = "TREND_DOWN"
            reason = f"ADX {adx_m5}, -DI {minus_di}>{plus_di} +DI, EMA stacked DOWN"
        else:
            regime = "TRANSITION"
            reason = f"ADX {adx_m5} but mixed DI/EMA"
    elif adx_m5 < 18:
        regime = "CHOP"
        reason = f"ADX {adx_m5} < 18, range {recent_range:.2f}"
    else:
        regime = "TRANSITION"
        reason = f"ADX {adx_m5} in 18-25 band"

    # Trader recommendation per regime
    advice = {
        "TREND_UP":    "Aggressive longs OK, no counter-trend",
        "TREND_DOWN":  "Aggressive shorts OK, no counter-trend",
        "CHOP":        "STAY OUT — high SL whipsaw risk",
        "SPIKE":       "WAIT — wait for stabilization 10min",
        "TRANSITION":  "Reduced size, confirmed setups only",
    }.get(regime, "Use discretion")

    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "regime": regime,
        "reason": reason,
        "advice": advice,
        "metrics": {
            "adx_m5": adx_m5,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "atr_m5": round(atr_m5, 3),
            "atr_m1": round(atr_m1, 3),
            "vol_ratio": round(vol_ratio, 2),
            "ema9_m5": round(ema9_m5, 2),
            "ema21_m5": round(ema21_m5, 2),
            "ema50_m5": round(ema50_m5, 2),
            "range_m5_20": round(recent_range, 2),
        },
        "recommended_traders": {
            "TREND_UP":    ["genome", "smart", "simple"],
            "TREND_DOWN":  ["genome", "smart", "simple"],
            "CHOP":        [],
            "SPIKE":       [],
            "TRANSITION":  ["smart"],
        }.get(regime, []),
    }


def main():
    if not mt5.initialize(): mt5.initialize()
    print("[regime_classifier] ONLINE")
    last_regime = ""
    while True:
        try:
            r = classify()
            if r:
                _save(OUTPUT, r)
                if r["regime"] != last_regime:
                    print(f"[{datetime.now():%H:%M:%S}] REGIME CHANGE: {last_regime} → {r['regime']}")
                    print(f"  {r['reason']}")
                    print(f"  → {r['advice']}")
                    print(f"  Recommended: {r['recommended_traders']}")
                    _append(HISTORY, r)
                    last_regime = r["regime"]
            time.sleep(POLL)
        except KeyboardInterrupt:
            print("[regime_classifier] stopped"); break
        except Exception as e:
            print(f"[regime_classifier] err: {e}")
            time.sleep(POLL)


if __name__ == "__main__":
    main()

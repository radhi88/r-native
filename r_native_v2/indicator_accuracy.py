"""indicator_accuracy.py — measure how ACCURATE each indicator actually is (no-lookahead).

Answers the user's question honestly: "are these indicators accurate, and does the system
learn from experience?" For each of the 15 consolidated indicators it measures the REAL
directional hit-rate out-of-sample: at each past bar, the indicator votes BUY/SELL using only
data up to that bar; we then check whether price actually moved that way over the next H bars.

Output per indicator: votes, hit-rate, and LIFT over 50% (a coin flip). Indicators near 50%
have NO edge; ones clearly above are worth weighting up. This produces learned weights
(weight ∝ measured lift) that chart_read can consume — self-improvement from real history.

Read-only. Writes data/indicator_accuracy_<SYM>.json + data/indicator_weights_<SYM>.json.
Run:  python indicator_accuracy.py [SYMBOL] [TF]   (default BTCUSDm M5)
"""
from __future__ import annotations
import json, sys
from pathlib import Path

_V2 = Path(__file__).resolve().parent
_MT5 = _V2.parent
for p in (str(_MT5), str(_V2)):
    if p not in sys.path:
        sys.path.insert(0, p)

from chart_read import (_ema, _rsi, _adx_di, _bollinger, _cci, _williams_r,
                        _ichimoku, _obv_slope, _vwap_vote, _roc, _supertrend,
                        _donchian, _keltner, _mfi, _aroon, _cmo, _momentum,
                        _sr_zone, _liq_sweep)

DATA = _V2 / "data"
WIN = 120          # rolling window per decision
HORIZON = 8        # bars ahead to judge the vote
DEADBAND = 0.0     # min move to count as a directional outcome (0 = any)


def _votes(close, high, low, vol):
    """Per-indicator vote at the end of the window (+1/-1/0). Same logic as chart_read."""
    price = close[-1]
    ema50 = _ema(close, 50)[-1]
    ef = _ema(close, 12); es = _ema(close, 26)
    ml = [a - b for a, b in zip(ef, es)]; sig = _ema(ml, 9)
    macd_hist = ml[-1] - sig[-1]
    rsi = _rsi(close)
    kp = 14; lo = min(low[-kp:]); hi = max(high[-kp:])
    sk = 100 * (price - lo) / (hi - lo + 1e-10)
    sks = []
    for j in range(len(close) - 3, len(close)):
        loj = min(low[max(0, j - kp + 1):j + 1]); hij = max(high[max(0, j - kp + 1):j + 1])
        sks.append(100 * (close[j] - loj) / (hij - loj + 1e-10))
    sd = sum(sks) / len(sks)
    v = {}
    v["trend"] = 1 if price > ema50 else -1
    v["rsi"] = 1 if rsi > 55 else -1 if rsi < 45 else 0
    v["macd"] = 1 if macd_hist > 0 else -1 if macd_hist < 0 else 0
    v["stoch"] = 1 if (sk > sd and sk < 80) else -1 if (sk < sd and sk > 20) else 0
    try: v["adx"] = _adx_di(high, low, close)[1]
    except Exception: v["adx"] = 0
    try: v["ema_cross"] = 1 if _ema(close, 9)[-1] > _ema(close, 21)[-1] else -1
    except Exception: v["ema_cross"] = 0
    try: v["supertrend"] = _supertrend(high, low, close)
    except Exception: v["supertrend"] = 0
    try: v["ichimoku"] = _ichimoku(high, low, close)
    except Exception: v["ichimoku"] = 0
    try: v["vwap"] = _vwap_vote(high, low, close, vol)
    except Exception: v["vwap"] = 0
    try: v["bollinger"] = _bollinger(close)
    except Exception: v["bollinger"] = 0
    try: v["cci"] = _cci(high, low, close)
    except Exception: v["cci"] = 0
    try: v["williams"] = _williams_r(high, low, close)
    except Exception: v["williams"] = 0
    try: v["obv"] = _obv_slope(close, vol)
    except Exception: v["obv"] = 0
    try: v["roc"] = _roc(close)
    except Exception: v["roc"] = 0
    # auto-discovery candidates (measured like the rest; accurate ones get weighted up)
    for nm, fn in (("donchian", lambda: _donchian(high, low, close)),
                   ("keltner", lambda: _keltner(high, low, close)),
                   ("mfi", lambda: _mfi(high, low, close, vol)),
                   ("aroon", lambda: _aroon(high, low)),
                   ("cmo", lambda: _cmo(close)),
                   ("momentum", lambda: _momentum(close)),
                   ("sr_zone", lambda: _sr_zone(high, low, close)),
                   ("liq_sweep", lambda: _liq_sweep(high, low, close))):
        try: v[nm] = fn()
        except Exception: v[nm] = 0
    # 🧩 SMC + library voters من REGISTRY (نفس نداء chart_read) — نقيسها كي تكسب وزناً مُتعلّماً
    # حقيقياً بدل التصويت الأعمى 1.0 (cisd/choch/ifvg/swing_profile/candles...). ~50% تُدفَن لأرضية 0.2.
    try:
        import advanced_indicators as _ai
        for _nm, _k, _w in _ai.REGISTRY:
            if _nm in v:
                continue
            try: v[_nm] = int(_ai.vote(_nm, high, low, close, vol))
            except Exception: v[_nm] = 0
    except Exception:
        pass
    return v


def measure(close, high, low, vol):
    n = len(close)
    start = max(WIN + 1, int(n * 0.45))
    stats = {}     # name -> [hits, total]
    for i in range(start, n - HORIZON):
        c = close[:i + 1]; h = high[:i + 1]; l = low[:i + 1]; vv = vol[:i + 1]
        votes = _votes(c[-WIN:], h[-WIN:], l[-WIN:], vv[-WIN:])
        fwd = close[i + HORIZON] - close[i]
        if abs(fwd) <= DEADBAND:
            continue
        outcome = 1 if fwd > 0 else -1
        for name, vote in votes.items():
            if vote == 0:
                continue
            st = stats.setdefault(name, [0, 0])
            st[1] += 1
            if vote == outcome:
                st[0] += 1
    res = {}
    for name, (hits, tot) in stats.items():
        hr = hits / tot if tot else 0.0
        res[name] = {"hit_rate": round(hr, 3), "lift": round(hr - 0.5, 3), "votes": tot}
    return dict(sorted(res.items(), key=lambda kv: -kv[1]["hit_rate"]))


def learned_weights(acc):
    """Weight ∝ measured edge above 50% (clamped >=0). Indicators with no edge get ~0.
    Floor so trend/markov keep some anchor weight even if a window is noisy."""
    w = {}
    for name, d in acc.items():
        lift = d["lift"]
        # only credit edge with enough samples; weight = lift*10, floored at 0, capped at 2.5
        wt = max(0.0, min(2.5, lift * 12)) if d["votes"] >= 40 else 0.0
        w[name] = round(wt, 2)
    return w


def main(argv):
    import MetaTrader5 as mt5
    sym = argv[0] if argv else "BTCUSDm"
    tf = argv[1] if len(argv) > 1 else "M5"
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    tfc = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}.get(tf, mt5.TIMEFRAME_M5)
    r = mt5.copy_rates_from_pos(sym, tfc, 0, 2000)
    if r is None or len(r) < 400:
        print("insufficient bars"); return 1
    close = [float(x["close"]) for x in r]; high = [float(x["high"]) for x in r]; low = [float(x["low"]) for x in r]
    try: vol = [float(x["tick_volume"]) for x in r]
    except Exception: vol = [1.0] * len(close)
    acc = measure(close, high, low, vol)
    w = learned_weights(acc)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / f"indicator_accuracy_{sym}.json").write_text(
        json.dumps({"symbol": sym, "tf": tf, "horizon": HORIZON, "accuracy": acc,
                    "note": "OOS no-lookahead directional hit-rate per indicator. ~0.50 = no edge."},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / f"indicator_weights_{sym}.json").write_text(
        json.dumps({"symbol": sym, "tf": tf, "weights": w, "source": "learned from measured lift"},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"=== {sym} {tf} — per-indicator OOS accuracy (horizon {HORIZON} bars) ===")
    print(f"{'indicator':12s} {'hit%':>6s} {'lift':>6s} {'votes':>6s} {'learned_w':>9s}")
    for name, d in acc.items():
        flag = "✓" if d["hit_rate"] >= 0.53 else ("·" if d["hit_rate"] >= 0.50 else "✗")
        print(f"{name:12s} {d['hit_rate']*100:5.1f}% {d['lift']:+.3f} {d['votes']:6d} {w.get(name,0):8.2f}  {flag}")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

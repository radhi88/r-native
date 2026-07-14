"""market_gate.py — F2-b slice 2: the OOS efficiency gate (HONEST, no-lookahead).

The discipline thesis (memory): NO strategy has a robust out-of-sample edge — direction is
~50%. So before ANY discovered market is allowed to trade live, it must PROVE an edge on
out-of-sample bars with a strict, no-lookahead walk-forward test. Most markets will FAIL —
that's the point. This is what makes "test every market" honest instead of reckless.

Method (per symbol × timeframe):
  • Decision at bar i uses ONLY close[:i+1] (the same 13 window-computable indicators as the
    live consolidated read — markov/sentiment excluded since they need D1/270-bar context).
  • Enter at bar i's close with ATR stop/target; outcome measured on bars i+1.. (forward only).
  • Tally trades / win-rate / profit-factor / net (in R = ATR units) over the OOS region only.
  • PASS gate: trades >= 30  AND  profit_factor >= 1.2  AND  net_R > 0.

Read-only · no order_send · no symbol_universe mutation. A PASS makes a symbol *eligible*;
promotion to live still needs explicit user approval.

Run:  python market_gate.py                 (test top candidates + live symbols)
      python market_gate.py SYMBOL [SYMBOL...]
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path

_V2 = Path(__file__).resolve().parent
_MT5 = _V2.parent
for p in (str(_MT5), str(_V2)):
    if p not in sys.path:
        sys.path.insert(0, p)

from chart_read import (_ema, _rsi, _adx_di, _bollinger, _cci, _williams_r,
                        _ichimoku, _obv_slope, _vwap_vote, _roc, _supertrend)

DATA = _V2 / "data"
OUT = DATA / "market_gate.json"

# gate thresholds (strict, honest)
MIN_TRADES = 30
MIN_PF = 1.2
# generic test trade params (in ATR units)
STOP_ATR = 2.0
TGT_ATR = 3.0
MAX_HOLD = 48          # bars
CONF_GATE = 0.60
WIN = 120              # rolling window for indicator computation


def _atr(high, low, close, i, n=14):
    if i < n + 1:
        return 0.0
    s = 0.0
    for k in range(i - n + 1, i + 1):
        s += max(high[k] - low[k], abs(high[k] - close[k - 1]), abs(low[k] - close[k - 1]))
    return s / n


def _vote(close, high, low, vol):
    """Consolidated direction from the window-computable indicators (no MT5, no lookahead)."""
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
    V = {}; W = {}
    def c(n, v, w): V[n] = int(v); W[n] = float(w)
    c("trend", 1 if price > ema50 else -1, 2.0)
    c("rsi", 1 if rsi > 55 else -1 if rsi < 45 else 0, 1.0)
    c("macd", 1 if macd_hist > 0 else -1 if macd_hist < 0 else 0, 1.0)
    c("stoch", 1 if (sk > sd and sk < 80) else -1 if (sk < sd and sk > 20) else 0, 1.0)
    try: c("adx", _adx_di(high, low, close)[1], 1.5)
    except Exception: pass
    try: c("ema_cross", 1 if _ema(close, 9)[-1] > _ema(close, 21)[-1] else -1, 1.5)
    except Exception: pass
    try: c("supertrend", _supertrend(high, low, close), 1.5)
    except Exception: pass
    try: c("ichimoku", _ichimoku(high, low, close), 1.5)
    except Exception: pass
    try: c("vwap", _vwap_vote(high, low, close, vol), 1.5)
    except Exception: pass
    try: c("bollinger", _bollinger(close), 1.0)
    except Exception: pass
    try: c("cci", _cci(high, low, close), 1.0)
    except Exception: pass
    try: c("williams", _williams_r(high, low, close), 1.0)
    except Exception: pass
    try: c("obv", _obv_slope(close, vol), 1.0)
    except Exception: pass
    try: c("roc", _roc(close), 1.0)
    except Exception: pass
    # ── advanced indicators (Fisher/Vortex/TSI/Gann/Hurst-fractal/candle-geo/Chaikin/Elder) ──
    # the SAME set the live trader uses, so the gene is trained on what it actually trades.
    try:
        import advanced_indicators as _ai
        for _nm, _k, _w in _ai.REGISTRY:
            try: c(_nm, _ai.vote(_nm, high, low, close, vol), _w)
            except Exception: pass
    except Exception: pass
    net = sum(V[k] * W[k] for k in V)
    direction = 1 if net > 0 else -1 if net < 0 else 0
    agree = sum(W[k] for k in V if direction != 0 and V[k] == direction)
    total = sum(W.values())
    conf = agree / total if total > 0 else 0.0
    return direction, conf


FOLDS = 4               # walk-forward folds across the OOS region
MIN_FOLDS_POS = 3       # edge must survive in >= this many folds (anti data-mining)


def backtest(close, high, low, vol, spread_price=0.0):
    """No-lookahead walk-forward over OOS (latter 55%), split into FOLDS. Subtracts REAL
    spread cost per round trip. Returns stats incl. per-fold net so we can demand consistency."""
    n = len(close)
    start = max(WIN + 1, int(n * 0.45))     # OOS = last ~55%
    span = n - start
    trades = []                              # list of (outcome_R, fold_index)
    i = start
    while i < n - 2:
        c = close[:i + 1]; h = high[:i + 1]; l = low[:i + 1]; v = vol[:i + 1]
        if len(c) < WIN:
            i += 1; continue
        d, conf = _vote(c[-WIN:], h[-WIN:], l[-WIN:], v[-WIN:])
        if d == 0 or conf < CONF_GATE:
            i += 1; continue
        atr = _atr(high, low, close, i)
        if atr <= 0:
            i += 1; continue
        cost_R = (spread_price / atr) if atr > 0 else 0.0   # round-trip cost in R units
        entry = close[i]
        if d > 0:
            sl = entry - STOP_ATR * atr; tp = entry + TGT_ATR * atr
        else:
            sl = entry + STOP_ATR * atr; tp = entry - TGT_ATR * atr
        outcome = None; exit_i = min(i + MAX_HOLD, n - 1)
        for j in range(i + 1, min(i + MAX_HOLD + 1, n)):
            if d > 0:
                if low[j] <= sl: outcome = -STOP_ATR; exit_i = j; break
                if high[j] >= tp: outcome = TGT_ATR; exit_i = j; break
            else:
                if high[j] >= sl: outcome = -STOP_ATR; exit_i = j; break
                if low[j] <= tp: outcome = TGT_ATR; exit_i = j; break
        if outcome is None:
            outcome = ((close[exit_i] - entry) if d > 0 else (entry - close[exit_i])) / atr
        outcome -= cost_R                    # pay the spread
        fold = min(FOLDS - 1, int((i - start) / span * FOLDS))
        trades.append((outcome, fold))
        i = exit_i + 1
    if not trades:
        return {"trades": 0, "pass": False}
    outs = [t for t, _ in trades]
    wins = [t for t in outs if t > 0]; losses = [t for t in outs if t <= 0]
    gross_w = sum(wins); gross_l = abs(sum(losses))
    pf = gross_w / gross_l if gross_l > 0 else (99.9 if gross_w > 0 else 0.0)
    net = sum(outs); wr = len(wins) / len(outs)
    fold_net = [0.0] * FOLDS
    for o, f in trades:
        fold_net[f] += o
    folds_pos = sum(1 for x in fold_net if x > 0)
    # STRICT honest gate: enough trades, real PF edge, AND consistent across folds
    passed = (len(outs) >= MIN_TRADES and pf >= MIN_PF and net > 0 and folds_pos >= MIN_FOLDS_POS)
    return {"trades": len(outs), "win_rate": round(wr, 3), "pf": round(pf, 2),
            "net_R": round(net, 2), "folds_pos": folds_pos,
            "fold_net": [round(x, 1) for x in fold_net], "pass": passed}


def test_symbol(mt5, sym):
    res = {}
    tfmap = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    mt5.symbol_select(sym, True)
    info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
    spread_price = (tick.ask - tick.bid) if (tick and tick.ask and tick.bid) else 0.0
    if spread_price <= 0 and info:           # fallback: spread (points) * point
        spread_price = getattr(info, "spread", 0) * (info.point or 0.0)
    for tfn, tfc in tfmap.items():
        r = mt5.copy_rates_from_pos(sym, tfc, 0, 2000)
        if r is None or len(r) < 400:
            res[tfn] = {"trades": 0, "pass": False, "note": "insufficient bars"}; continue
        close = [float(x["close"]) for x in r]; high = [float(x["high"]) for x in r]
        low = [float(x["low"]) for x in r]
        try: vol = [float(x["tick_volume"]) for x in r]
        except Exception: vol = [1.0] * len(close)
        res[tfn] = backtest(close, high, low, vol, spread_price)
    best = max(res.values(), key=lambda d: (d.get("pass", False), d.get("folds_pos", 0), d.get("pf", 0)))
    # tier: robust = a passing TF with ALL folds positive & PF>=1.3; marginal = passed 3/4
    robust = any(v.get("pass") and v.get("folds_pos", 0) == FOLDS and v.get("pf", 0) >= 1.3
                 for v in res.values())
    eligible = any(v.get("pass") for v in res.values())
    tier = "robust" if robust else "marginal" if eligible else "fail"
    return {"tf": res, "eligible": eligible, "tier": tier, "best_pf": best.get("pf", 0)}


def main(argv=None):
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    syms = list(argv) if argv else []
    if syms == ["--all"]:                       # test EVERY tradable symbol (the full universe)
        syms = []
        for s in (mt5.symbols_get() or []):
            try:
                if getattr(s, "trade_mode", 0) != 0:
                    syms.append(s.name)
            except Exception:
                pass
        # de-dupe scaled variants (_x10/_x100 trade identically to the base)
        seen = set(); uniq = []
        for s in syms:
            base = s.replace("_x100m", "m").replace("_x10m", "m").replace("_x100", "").replace("_x10", "")
            if base not in seen:
                seen.add(base); uniq.append(s)
        syms = uniq
    elif not syms:
        try:
            cand = json.loads((DATA / "market_candidates.json").read_text(encoding="utf-8"))
            syms = [c["symbol"] for c in cand.get("top", [])[:12]]
        except Exception:
            syms = ["XAUUSDm", "BTCUSDm"]
        for s in ("XAUUSDm", "BTCUSDm"):
            if s not in syms: syms.append(s)
    print(f"[GATE] OOS efficiency test — {len(syms)} symbols (need >={MIN_TRADES} trades, PF>={MIN_PF}, net_R>0)\n")
    out = {}
    for s in syms:
        try:
            r = test_symbol(mt5, s); out[s] = r
            tag = "PASS ✓" if r["eligible"] else "fail ✗"
            tfs = " · ".join(f"{tf}:{d.get('pf',0)}pf/{d.get('trades',0)}t/{d.get('net_R',0)}R"
                             for tf, d in r["tf"].items())
            print(f"  {tag}  {s:10s}  {tfs}", flush=True)
        except Exception as e:
            out[s] = {"error": str(e)[:60]}; print(f"  ERR  {s}: {e}", flush=True)
    eligible = [s for s, r in out.items() if r.get("eligible")]
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"ts": time.time(), "results": out, "eligible": eligible,
                               "gate": {"min_trades": MIN_TRADES, "min_pf": MIN_PF},
                               "note": "OOS no-lookahead. PASS = eligible only; live needs approval."},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[GATE] eligible (passed OOS): {eligible or 'NONE — honest: no proven edge'}")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))

"""runtime/brain_v1.py — The Smart Brain.

User mandate (2026-05-27):
  "ابيك اذكى مني وتعرف وش تسوي وكل المؤشرات اللي دخلنا فيها نحفظها
   بقراءات لحظية لشموع واشكالها وتشكلها والخ"

This is the FULL real-time brain. Every 2s it:

  1. CAPTURES — full indicator stack snapshot (every M1 close gets
     immortalized in brain_memory.jsonl). Each snapshot includes:
       • Per-bar anatomy (M1 last 5, M5 last 3, M15 last 3)
       • RSI M1/M5/M15 (closed-bar only)
       • ATR M1/M5/M15
       • MTF bias (M1/M5/M15/H1 vs EMA20)
       • Pressure 10-M1 net body $
       • CVD 30-M1 (tick-rule aggressor)
       • All active OBs M5+M15 + distance from price
       • All active FVGs M1+M5+M15 + distance
       • ZigZag last 6 pivots
       • S/R clusters (2+ pivot confluence within ±$10)
       • Recent swings (last 4 highs + 4 lows)
       • Pivot levels PP/R1/R2/S1/S2
       • Round numbers in play (every $5)
       • Liquidity sweep detection (wick beyond prior swing + reversal)
       • BOS / CHoCH state
       • ADX M5/M15
       • Volume trend M5 (rising/dry/falling)
       • Engulfing detection
       • Session

  2. DECIDES — applies the USER'S edge from USER_EDGE_BOOK.md:
       Rule 1 (counter-trend BUY): NY_OVERLAP + bias_m5=DOWN +
              RSI_M1 30-55 + price within $2 of round# + Pressure
              flipped positive (>0 after being negative)
       Rule 2 (with-trend SELL): NY_OVERLAP + bias_m5=DOWN +
              shooting_star or marubozu_bear + RSI_M1 not <30 +
              price rejected at S/R cluster
       Rule 3 (exit alert): user has open longs + close breaks the
              nearest round-down + Vol Trend rising bear + ADX>20

     Each cycle emits a DECISION with: action, confidence,
     rationale, contributing indicators. Logged to
     brain_decisions.jsonl. High-conviction (≥0.70) decisions
     trigger an audible alert via console + push.

  3. PROTECTS — watches open user positions in real-time. If
     floating PnL drops by $5 in a 60s window OR price punches
     a round-number floor with Vol≥150%, emits HEDGE_ALERT.

OUTPUT FILES:
  data/brain_memory.jsonl    — append-only per-cycle snapshots
  data/brain_live.json       — current snapshot (overwritten)
  data/brain_decisions.jsonl — every decision with rationale
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import deque

SYMBOL = "XAUUSDm"
# Multi-symbol: our son now watches more than gold. Gold stays PRIMARY (writes
# brain_live.json exactly as before — zero regression); each extra symbol writes
# its own brain_live__<SYM>.json that the trader reads per-symbol. لنطلع على باقي العملات.
SYMBOLS = ["XAUUSDm", "EURUSDm", "GBPUSDm", "USDJPYm",
           "USDCADm", "AUDUSDm", "NZDUSDm", "USDCHFm", "EURJPYm", "XAGUSDm"]
# Price-unit per "1 pt" and display digits, so gold-tuned rounding/indicators
# stay correct per instrument (EURUSD must NOT be rounded to 2 decimals).
_DIGITS = {"XAUUSDm": 2, "XAGUSDm": 3, "BTCUSDm": 1, "EURUSDm": 5,
           "GBPUSDm": 5, "USDJPYm": 3, "GBPJPYm": 3,
           "USDCADm": 5, "AUDUSDm": 5, "NZDUSDm": 5, "USDCHFm": 5,
           "EURJPYm": 3}
POLL = 0.2          # sub-second snapshots — full 4-sym capture ≈25ms, so 0.2s ≈12% duty. حساس جداً، ما يغفي
MEMORY     = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\brain_memory.jsonl")
LIVE       = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\brain_live.json")
DECISIONS  = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\brain_decisions.jsonl")
EDGE_BOOK  = Path(r"C:\Users\Radhi\MT5\r_native_v2\docs\USER_EDGE_BOOK.md")

# Memory-lite rolling state for protection logic
_pressure_history: deque = deque(maxlen=30)   # last 30 pressures
_pnl_history: deque = deque(maxlen=60)        # last 60s of floating pnl
_last_decision_key = None                      # dedup chatty decisions


def _save_atomic(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    tmp.replace(p)


def _append(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


# ───────────── CANDLE ANATOMY ─────────────
def classify_bar(b) -> dict:
    o, h, l, c = b["open"], b["high"], b["low"], b["close"]
    rng = max(h - l, 1e-9)
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    body_pct = round(body / rng * 100)
    upper_pct = round(upper / rng * 100)
    lower_pct = round(lower / rng * 100)
    is_bull = c > o
    kind = "doji"
    if body_pct >= 80:        kind = "marubozu_bull" if is_bull else "marubozu_bear"
    elif upper_pct >= 60 and body_pct <= 30: kind = "shooting_star" if not is_bull else "inverted_hammer"
    elif lower_pct >= 60 and body_pct <= 30: kind = "hammer" if is_bull else "hanging_man"
    elif body_pct >= 60:      kind = "strong_bull" if is_bull else "strong_bear"
    elif body_pct >= 35:      kind = "normal_bull" if is_bull else "normal_bear"
    elif body_pct >= 15:      kind = "weak_bull" if is_bull else "weak_bear"
    return {
        "ts": int(b["time"]),
        "o": round(o, 2), "h": round(h, 2), "l": round(l, 2), "c": round(c, 2),
        "kind": kind, "body_pct": body_pct,
        "upper_wick": round(upper, 2), "lower_wick": round(lower, 2),
        "v": int(b.get("tick_volume", 0)),
    }


# ───────────── INDICATORS ─────────────
def _atr(bars, p=14):
    if len(bars) < p + 1: return 0
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:p]) / p
    for t in trs[p:]: a = (a * (p-1) + t) / p
    return round(a, 4)


def _rsi(closes, p=14):
    if len(closes) < p + 1: return 50
    g = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    l = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(g[:p]) / p; al = sum(l[:p]) / p
    for i in range(p, len(g)):
        ag = (ag*(p-1)+g[i])/p; al = (al*(p-1)+l[i])/p
    return 100 if al == 0 else round(100 - 100/(1 + ag/al), 1)


def _ema(vals, p):
    if not vals: return 0
    k = 2/(p+1); e = vals[0]
    for v in vals[1:]: e = v*k + e*(1-k)
    return e


def _bias(bars, p=20):
    if len(bars) < p+1: return "?"
    e = _ema([b["close"] for b in bars[-p-1:-1]], p)
    return "UP" if bars[-2]["close"] > e else "DOWN"


def _zigzag(bars, depth=5):
    """Return last 6 swing pivots."""
    if len(bars) < depth*2+1: return []
    pivots = []
    for i in range(depth, len(bars)-depth):
        win = bars[i-depth:i+depth+1]
        if bars[i]["high"] == max(b["high"] for b in win):
            pivots.append({"i": i, "price": bars[i]["high"], "type": "H", "ts": int(bars[i]["time"])})
        elif bars[i]["low"] == min(b["low"] for b in win):
            pivots.append({"i": i, "price": bars[i]["low"], "type": "L", "ts": int(bars[i]["time"])})
    return pivots[-6:]


def _find_obs(bars, lookback=40):
    """Last bull/bear OB from M5/M15."""
    bull = bear = None
    n = min(lookback, len(bars)-2)
    for i in range(len(bars)-2, len(bars)-n-2, -1):
        if i < 1: continue
        b = bars[i]; nxt = bars[i+1]
        body = abs(nxt["close"] - nxt["open"])
        rng = max(nxt["high"] - nxt["low"], 1e-9)
        # bull OB: last bearish bar before strong bull move
        if not bull and b["close"] < b["open"] and nxt["close"] > nxt["open"] and body/rng > 0.6:
            bull = {"bot": b["low"], "top": b["high"], "ts": int(b["time"]), "age": len(bars)-1-i}
        # bear OB: last bullish bar before strong bear move
        if not bear and b["close"] > b["open"] and nxt["close"] < nxt["open"] and body/rng > 0.6:
            bear = {"bot": b["low"], "top": b["high"], "ts": int(b["time"]), "age": len(bars)-1-i}
        if bull and bear: break
    return {"bull": bull, "bear": bear}


def _find_fvgs(bars, lookback=30):
    bull, bear = [], []
    n = min(lookback, len(bars) - 2)
    for i in range(len(bars) - 2, len(bars) - n - 2, -1):
        if i < 1: continue
        a, c = bars[i-1], bars[i+1]
        if c["low"] > a["high"]:
            top, bot = c["low"], a["high"]
            min_after = min((b["low"] for b in bars[i+2:]), default=top)
            if min_after > bot:
                bull.append({"bot": round(bot,2), "top": round(top,2), "mid": round((top+bot)/2,2),
                              "size": round(top-bot,2), "age": len(bars)-1-(i+1)})
        if c["high"] < a["low"]:
            top, bot = a["low"], c["high"]
            max_after = max((b["high"] for b in bars[i+2:]), default=bot)
            if max_after < top:
                bear.append({"bot": round(bot,2), "top": round(top,2), "mid": round((top+bot)/2,2),
                              "size": round(top-bot,2), "age": len(bars)-1-(i+1)})
    return {"bull": bull[:3], "bear": bear[:3]}


def _sr_clusters(pivots, price, tolerance=2.0):
    """Find S/R clusters: prices where 2+ pivots stack within tolerance."""
    if len(pivots) < 2: return []
    used = set()
    clusters = []
    for i, p in enumerate(pivots):
        if i in used: continue
        group = [p]
        for j, q in enumerate(pivots[i+1:], start=i+1):
            if abs(q["price"] - p["price"]) <= tolerance:
                group.append(q); used.add(j)
        if len(group) >= 2:
            avg = sum(g["price"] for g in group) / len(group)
            clusters.append({"price": round(avg,2), "count": len(group),
                              "dist": round(avg - price, 2),
                              "kind": "R" if avg > price else "S"})
    return sorted(clusters, key=lambda c: abs(c["dist"]))[:5]


def _macd(closes, fast=12, slow=26, sig=9):
    if len(closes) < slow + sig: return {"macd": 0, "signal": 0, "hist": 0}
    ef = _ema(closes, fast); es = _ema(closes, slow)
    macd = ef - es
    # signal needs macd series — approximate from last 9 values
    macd_series = []
    for i in range(slow, len(closes)+1):
        e1 = _ema(closes[:i], fast); e2 = _ema(closes[:i], slow)
        macd_series.append(e1 - e2)
    signal = _ema(macd_series[-sig:], sig) if len(macd_series) >= sig else macd_series[-1]
    return {"macd": round(macd, 3), "signal": round(signal, 3),
            "hist": round(macd - signal, 3)}


def _adx(bars, p=14):
    if len(bars) < p*2: return 0
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(bars)):
        up_move = bars[i]["high"] - bars[i-1]["high"]
        dn_move = bars[i-1]["low"] - bars[i]["low"]
        plus_dm.append(up_move if up_move > dn_move and up_move > 0 else 0)
        minus_dm.append(dn_move if dn_move > up_move and dn_move > 0 else 0)
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i-1]["close"]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    atr_val = sum(trs[-p:]) / p
    if atr_val == 0: return 0
    p_di = 100 * (sum(plus_dm[-p:]) / p) / atr_val
    m_di = 100 * (sum(minus_dm[-p:]) / p) / atr_val
    dx = 100 * abs(p_di - m_di) / max(p_di + m_di, 1e-9)
    return round(dx, 1)


def _liquidity_sweep(bars):
    """Detect: last bar swept prior 10-bar high/low + reversed."""
    if len(bars) < 12: return None
    last = bars[-2]   # closed bar
    prior = bars[-12:-2]
    prior_hi = max(b["high"] for b in prior)
    prior_lo = min(b["low"] for b in prior)
    if last["high"] > prior_hi and last["close"] < prior_hi:
        return {"type": "swept_high", "level": round(prior_hi, 2)}
    if last["low"] < prior_lo and last["close"] > prior_lo:
        return {"type": "swept_low", "level": round(prior_lo, 2)}
    return None


def _round_numbers_in_play(price, tolerance=1.5):
    base = int(price)
    near = []
    for k in (5, 10, 25, 50, 100):
        low = (base // k) * k
        for cand in (low, low + k):
            if abs(cand - price) <= tolerance:
                near.append({"level": cand, "dist": round(cand - price, 2)})
    return near


def _pressure_10m1(m1):
    if len(m1) < 11: return 0
    last10 = m1[-11:-1]
    bull = sum(b["close"]-b["open"] for b in last10 if b["close"] > b["open"])
    bear = sum(b["open"]-b["close"] for b in last10 if b["close"] < b["open"])
    return round(bull - bear, 2)


def _cvd_30m1(mt5, m1, sym=SYMBOL):
    if len(m1) < 31: return 0
    from datetime import datetime as _dt, timezone as _tz
    cvd = 0
    for i in range(len(m1)-31, len(m1)-1):
        bar_start = int(m1[i]["time"])
        try:
            ticks = mt5.copy_ticks_range(sym,
                _dt.fromtimestamp(bar_start, tz=_tz.utc),
                _dt.fromtimestamp(bar_start+60, tz=_tz.utc),
                mt5.COPY_TICKS_ALL)
            if ticks is None or len(ticks) < 2: continue
            prev_mid = None
            for t in ticks:
                mid = (float(t["bid"]) + float(t["ask"])) / 2
                if prev_mid is not None:
                    if mid > prev_mid:   cvd += 1
                    elif mid < prev_mid: cvd -= 1
                prev_mid = mid
        except Exception: pass
    return cvd


def _vol_trend(m5):
    """Last 5 bars vs prior 5 bars avg volume."""
    if len(m5) < 11: return "?"
    recent = sum(b["tick_volume"] for b in m5[-6:-1]) / 5
    prior  = sum(b["tick_volume"] for b in m5[-11:-6]) / 5
    ratio = recent / max(prior, 1)
    if ratio > 1.5: return "RISING"
    if ratio < 0.7: return "DRY"
    return "STEADY"


def _vwap(bars):
    """Volume-Weighted Average Price over the supplied bars (typical price ×
    tick_volume). Used as a fair-value anchor: longs prefer price ≤ VWAP
    (discount), shorts prefer ≥ VWAP (premium). Returns (vwap, bands±1σ)."""
    if not bars or len(bars) < 5:
        return None
    num = den = 0.0
    tps, vols = [], []
    for b in bars:
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        v  = max(float(b.get("tick_volume", 1)), 1.0)
        num += tp * v; den += v
        tps.append(tp); vols.append(v)
    if den <= 0:
        return None
    vwap = num / den
    # volume-weighted std-dev band
    var = sum(v * (tp - vwap) ** 2 for tp, v in zip(tps, vols)) / den
    sd = var ** 0.5
    return {"vwap": vwap, "upper": vwap + sd, "lower": vwap - sd, "sd": sd}


def _volume_profile(bars, bins=24):
    """Lightweight volume profile over recent bars → POC + value-area edges.
    Distributes each bar's tick_volume across its high-low range. Returns price
    levels (POC, VAH, VAL) the structure engine treats as magnets/shelves."""
    if not bars or len(bars) < 10:
        return None
    lo = min(b["low"] for b in bars); hi = max(b["high"] for b in bars)
    if hi <= lo:
        return None
    step = (hi - lo) / bins
    vol = [0.0] * bins
    for b in bars:
        b_lo, b_hi = b["low"], b["high"]
        v = max(float(b.get("tick_volume", 1)), 1.0)
        i0 = max(0, int((b_lo - lo) / step))
        i1 = min(bins - 1, int((b_hi - lo) / step))
        span = max(i1 - i0 + 1, 1)
        for i in range(i0, i1 + 1):
            vol[i] += v / span
    poc_i = max(range(bins), key=lambda i: vol[i])
    poc = lo + (poc_i + 0.5) * step
    # value area = 70% of volume around POC
    total = sum(vol); target = total * 0.70
    lo_i = hi_i = poc_i; acc = vol[poc_i]
    while acc < target and (lo_i > 0 or hi_i < bins - 1):
        left  = vol[lo_i - 1] if lo_i > 0 else -1
        right = vol[hi_i + 1] if hi_i < bins - 1 else -1
        if right >= left:
            hi_i += 1; acc += max(right, 0)
        else:
            lo_i -= 1; acc += max(left, 0)
    return {"poc": round(poc, 3),
            "vah": round(lo + (hi_i + 1) * step, 3),
            "val": round(lo + lo_i * step, 3)}


def _session(now: datetime):
    h = now.hour
    if 13 <= h < 17: return "NY_OVERLAP"
    if 8  <= h < 13: return "LONDON"
    if 17 <= h < 21: return "NY_LATE"
    if h >= 22 or h < 8: return "ASIAN"
    return "TRANSITION"


# ───────────── CAPTURE ─────────────
def capture(mt5, sym=SYMBOL) -> dict:
    """Full indicator stack snapshot for `sym` (gold by default)."""
    dg = _DIGITS.get(sym, 2)
    def _bars(tf, n):
        r = mt5.copy_rates_from_pos(sym, tf, 0, n)
        return [dict(b._asdict()) if hasattr(b, "_asdict")
                else {k: b[k] for k in b.dtype.names} for b in r] if r is not None else []

    m1  = _bars(mt5.TIMEFRAME_M1, 60)
    m5  = _bars(mt5.TIMEFRAME_M5, 60)
    m15 = _bars(mt5.TIMEFRAME_M15, 40)
    h1  = _bars(mt5.TIMEFRAME_H1, 24)
    if not m1 or not m5: return {}

    tick = mt5.symbol_info_tick(sym)
    bid, ask = float(tick.bid), float(tick.ask)
    mid = (bid + ask) / 2
    closes_m1  = [b["close"] for b in m1[:-1]]
    closes_m5  = [b["close"] for b in m5[:-1]]
    closes_m15 = [b["close"] for b in m15[:-1]]

    pivots = _zigzag(m5)
    snap = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": sym,
        "bid": round(bid, dg), "ask": round(ask, dg),
        "spread": round(ask-bid, dg + 1),
        "session": _session(datetime.now(timezone.utc)),

        # candle anatomies
        "m1_last5":  [classify_bar(b) for b in m1[-5:]],
        "m5_last3":  [classify_bar(b) for b in m5[-3:]],
        "m15_last3": [classify_bar(b) for b in m15[-3:]],

        # momentum / volatility
        "rsi": {"m1": _rsi(closes_m1), "m5": _rsi(closes_m5), "m15": _rsi(closes_m15)},
        "atr": {"m1": _atr(m1), "m5": _atr(m5), "m15": _atr(m15)},
        "bias": {"m1": _bias(m1), "m5": _bias(m5), "m15": _bias(m15), "h1": _bias(h1)},
        "adx": {"m5": _adx(m5), "m15": _adx(m15)},
        "macd_m5": _macd(closes_m5),

        # SMC
        "ob_m5":   _find_obs(m5),
        "ob_m15":  _find_obs(m15),
        "fvg_m5":  _find_fvgs(m5),
        "fvg_m15": _find_fvgs(m15),
        "zigzag_m5": pivots,

        # flow
        "pressure_10m1": _pressure_10m1(m1),
        "cvd_30m1": _cvd_30m1(mt5, m1, sym),
        "vol_trend_m5": _vol_trend(m5),
        "vwap_m5":  _vwap(m5),                 # fair-value anchor (intraday)
        "vwap_m1":  _vwap(m1[-30:]),           # fast VWAP for scalp timing
        "vol_profile_m15": _volume_profile(m15),  # POC / value-area levels

        # levels
        "sr_clusters": _sr_clusters(pivots, mid),
        "round_numbers": _round_numbers_in_play(mid),
        "liquidity_sweep_m5": _liquidity_sweep(m5),
    }

    # MTF alignment score
    biases = [snap["bias"]["m1"], snap["bias"]["m5"], snap["bias"]["m15"], snap["bias"]["h1"]]
    up = biases.count("UP"); dn = biases.count("DOWN")
    snap["mtf_align"] = "UP" if up >= 3 else ("DOWN" if dn >= 3 else "MIXED")

    # Regime — gold pulls the dedicated regime_classifier output; other symbols
    # derive their own lightweight regime from their ADX (no per-symbol classifier yet).
    if sym == SYMBOL:
        try:
            import json as _json
            from pathlib import Path as _P
            rp = _P(r"C:\Users\Radhi\MT5\r_native_v2\data\market_regime.json")
            if rp.exists():
                rd = _json.loads(rp.read_text(encoding="utf-8"))
                snap["regime"] = rd.get("regime", "?")
                snap["regime_adx_m5"] = rd.get("metrics", {}).get("adx_m5")
        except Exception:
            snap["regime"] = "?"
    else:
        _adx5 = (snap.get("adx") or {}).get("m5") or 0
        snap["regime_adx_m5"] = _adx5
        snap["regime"] = ("TREND_UP" if _adx5 >= 22 and snap.get("mtf_align") == "UP"
                          else "TREND_DOWN" if _adx5 >= 22 and snap.get("mtf_align") == "DOWN"
                          else "RANGE" if _adx5 >= 14 else "CHOP")

    # Inter-market: gold↔oil divergence (user's insight — gold/oil inverse)
    try:
        import sys as _sys
        from pathlib import Path as _P2
        _sys.path.insert(0, str(_P2(__file__).resolve().parent.parent))
        from runtime.shared.intermarket import intermarket as _im
        snap["intermarket"] = _im()
    except Exception:
        snap["intermarket"] = {}

    # Deep footprint (CLAUDE_FOOTPRINT_v4 order-flow: POC, value-area, delta div)
    try:
        from runtime.shared.footprint_features import footprint_features as _ff
        _atr_m5 = (snap.get("atr") or {}).get("m5", 1) or 1
        snap["footprint"] = _ff(snap.get("bid", 0), _atr_m5)
    except Exception:
        snap["footprint"] = {}

    return snap


# ───────────── DECIDE ─────────────
def decide(snap: dict, positions: list) -> dict:
    """Apply user's edge from USER_EDGE_BOOK to current state."""
    global _last_decision_key

    if not snap: return {"action": "WAIT", "confidence": 0, "rationale": "no data"}

    rationale = []
    confidence = 0.0
    action = "WAIT"

    last_m1 = snap["m1_last5"][-1] if snap.get("m1_last5") else {}
    rsi_m1 = snap["rsi"]["m1"]
    pressure = snap["pressure_10m1"]
    _pressure_history.append(pressure)
    pressure_flipped_pos = (len(_pressure_history) >= 5 and
                             pressure > 0 and
                             min(list(_pressure_history)[-5:-1]) < -2)

    near_round = next((r for r in snap.get("round_numbers", []) if abs(r["dist"]) < 2), None)
    near_sr = snap["sr_clusters"][0] if snap.get("sr_clusters") else None
    is_ny = snap["session"] == "NY_OVERLAP"

    # ───── RULE 1: User's counter-trend BUY signature
    if (is_ny and snap["bias"]["m5"] == "DOWN"
        and 30 <= rsi_m1 <= 55
        and near_round and near_round["level"] <= snap["bid"]
        and pressure_flipped_pos):
        confidence = 0.75
        action = "BUY_MARKET"
        rationale.append(f"NY+M5↓+RSI{rsi_m1}+Round${near_round['level']}+Pressure flipped {pressure:+.2f}")

    # Boost with marubozu_bull or hammer at level
    if action == "BUY_MARKET" and last_m1.get("kind") in ("marubozu_bull", "hammer", "strong_bull"):
        confidence = min(0.90, confidence + 0.15)
        rationale.append(f"M1 {last_m1['kind']} confirmation")

    # ───── RULE 2: User's with-trend SELL signature
    if (action == "WAIT" and is_ny and snap["bias"]["m5"] == "DOWN"
        and last_m1.get("kind") in ("shooting_star", "marubozu_bear", "strong_bear")
        and rsi_m1 > 35
        and near_sr and near_sr["kind"] == "R" and abs(near_sr["dist"]) < 3):
        confidence = 0.70
        action = "SELL_MARKET"
        rationale.append(f"NY+M5↓+{last_m1['kind']}+RSI{rsi_m1}+R@${near_sr['price']}")
        if snap["adx"]["m5"] > 20:
            confidence = min(0.85, confidence + 0.10)
            rationale.append(f"ADX_M5 {snap['adx']['m5']} (trending)")

    # ───── RULE 3: Protection for open longs
    long_positions = [p for p in positions if int(p.type) == 0]
    if long_positions:
        total_lot = sum(float(p.volume) for p in long_positions)
        avg_entry = sum(float(p.price_open) * float(p.volume) for p in long_positions) / total_lot
        # find nearest round-down
        floor_round = (int(snap["bid"]) // 5) * 5
        floor_dist = snap["bid"] - floor_round
        bear_strong = last_m1.get("kind") in ("marubozu_bear", "strong_bear", "shooting_star")
        if (bear_strong and floor_dist < 1.0
            and snap["vol_trend_m5"] == "RISING"
            and snap["adx"]["m5"] > 18):
            action = "HEDGE_ALERT"
            confidence = 0.80
            rationale.append(f"⚠️ ${total_lot:.2f} long avg ${avg_entry:.2f}, "
                              f"floor ${floor_round} {floor_dist:.2f} away, "
                              f"{last_m1['kind']} + Vol RISING + ADX {snap['adx']['m5']}")

    # ───── RULE 4: Liquidity sweep reversal
    sweep = snap.get("liquidity_sweep_m5")
    if action == "WAIT" and sweep:
        if sweep["type"] == "swept_low" and snap["bias"]["m5"] == "DOWN" and is_ny:
            confidence = 0.65
            action = "BUY_MARKET"
            rationale.append(f"M5 swept low ${sweep['level']} + reclaimed (liquidity grab)")
        elif sweep["type"] == "swept_high" and snap["bias"]["m5"] == "UP" and is_ny:
            confidence = 0.65
            action = "SELL_MARKET"
            rationale.append(f"M5 swept high ${sweep['level']} + rejected (liquidity grab)")

    decision = {
        "ts": snap["ts"],
        "action": action,
        "confidence": round(confidence, 2),
        "rationale": " · ".join(rationale) if rationale else "no edge match",
        "price": snap["bid"],
        "context": {
            "rsi_m1": rsi_m1, "pressure": pressure,
            "bias_m5": snap["bias"]["m5"], "vol_trend": snap["vol_trend_m5"],
            "round": near_round, "sr": near_sr,
            "last_m1_kind": last_m1.get("kind"),
            "mtf_align": snap.get("mtf_align"),
        },
    }

    # Dedup chatter (only print if action or rationale changes meaningfully)
    key = (action, tuple(rationale[:2]))
    if key != _last_decision_key and (confidence >= 0.65 or action in ("HEDGE_ALERT",)):
        _last_decision_key = key
        mark = {"BUY_MARKET":"🟢", "SELL_MARKET":"🔴", "HEDGE_ALERT":"🚨", "WAIT":"⏸"}.get(action, "•")
        print(f"[{datetime.now():%H:%M:%S}] {mark} {action} conf={confidence:.2f} · {decision['rationale']}")
        _append(DECISIONS, decision)
    elif confidence > 0:
        # Still log to file but don't print
        _append(DECISIONS, decision)

    return decision


# ───────────── MAIN LOOP ─────────────
def main_loop():
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
    except Exception as e:
        print(f"mt5 init err: {e}"); return

    print(f"[brain_v1] ONLINE · {' '.join(SYMBOLS)} · poll {POLL}s")
    print(f"[brain_v1] memory → {MEMORY.name}")
    print(f"[brain_v1] decisions → {DECISIONS.name}")
    print(f"[brain_v1] live snapshot → {LIVE.name}")
    print(f"[brain_v1] applying USER_EDGE_BOOK rules (4 active)")
    last_m1_close_ts = None

    while True:
        try:
            # PRIMARY: gold — unchanged path (brain_live.json + memory + decide)
            snap = capture(mt5, SYMBOL)
            if snap:
                _save_atomic(LIVE, snap)
                _save_atomic(LIVE.parent / f"brain_live__{SYMBOL}.json", snap)
                # Only commit to memory on M1 close transition (avoid 30 dupes/min)
                cur_m1_ts = snap["m1_last5"][-1]["ts"] if snap.get("m1_last5") else None
                if cur_m1_ts != last_m1_close_ts:
                    _append(MEMORY, snap)
                    last_m1_close_ts = cur_m1_ts

                positions = mt5.positions_get(symbol=SYMBOL) or []
                decision = decide(snap, positions)

            # EXTRA SYMBOLS: lightweight per-symbol snapshot for the trader only.
            for _sym in SYMBOLS:
                if _sym == SYMBOL:
                    continue
                try:
                    s2 = capture(mt5, _sym)
                    if s2:
                        _save_atomic(LIVE.parent / f"brain_live__{_sym}.json", s2)
                except Exception as _e:
                    print(f"[brain_v1] {_sym} capture err: {_e}")

        except KeyboardInterrupt:
            print("[brain_v1] stopped"); break
        except Exception as e:
            print(f"[brain_v1] err: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main_loop()

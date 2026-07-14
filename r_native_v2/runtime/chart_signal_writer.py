"""chart_signal_writer.py — REVERSE bridge: brain decision -> on-chart BUY/SELL.

The pipflow dashboards (/r/indicators confluence + SMC zones) compute a clear
directional read. This writes that read to <Common>/Files/signal_<SYMBOL>.json so
CLAUDE_FOOTPRINT_v4.mq5 can draw a BUY / SELL arrow + label right on the candles.

It uses the SAME logic as the dashboards:
  • 11-indicator confluence  (r_native.live_indicators.compute_indicator_panel)
  • real SMC zones           (runtime.shared.order_blocks.detect_order_blocks)

Run:  python -m runtime.chart_signal_writer --once
      python -m runtime.chart_signal_writer --loop     (every Interval s)
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

# make both packages importable (r_native pipflow modules + our v2 shared)
_V2 = Path(__file__).resolve().parent.parent          # ...\r_native_v2
_MT5 = _V2.parent                                       # ...\MT5  (has r_native package)
for p in (str(_MT5), str(_V2)):
    if p not in sys.path:
        sys.path.insert(0, p)

COMMON = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
# F2-a.2: symbol list now comes from the single source of truth (symbol_universe, signals=True),
# which is a SUPERSET of the legacy list (no visual-signal loss). Fail-safe to the legacy literal
# if the universe/loader is unavailable — never breaks the chart signal path.
_LEGACY_DEFAULT_SYMBOLS = ["XAUUSDm", "BTCUSDm", "EURUSDm", "GBPUSDm", "XAGUSDm"]
try:
    from runtime.shared.symbol_universe import signal_symbols as _signal_symbols
    DEFAULT_SYMBOLS = _signal_symbols() or _LEGACY_DEFAULT_SYMBOLS
except Exception:  # noqa: BLE001 — display path must never crash on universe import
    DEFAULT_SYMBOLS = _LEGACY_DEFAULT_SYMBOLS
TF = "15m"
INTERVAL = 1                 # ultra-fast: refresh the % every second (flow+spread)

# --- Sensitivity / blend tuning (the "more sensitive + squeeze all indicators" knobs) ---
# Lower SENSITIVITY  = MORE BUY/SELL arrows (more reactive, more noise).
# Higher SENSITIVITY = fewer, higher-conviction arrows.
SENSITIVITY = 22.0          # |score| >= this -> BUY/SELL ; below -> WAIT
# (removed dead W_CONFLUENCE/W_FLOW constants — pro-panel audit flagged them as
#  leftover config that contradicted the live DEFAULT_WEIGHTS["flow"]=0.20.)

# --- Regime gate (pro-panel Step-1): don't trade when there is NO trend. ---
# ADX<ADX_MIN or efficiency<ER_MIN = chop/noise -> suppress directional signals.
ADX_MIN = 18.0              # Wilder ADX(14) below this = no trend on exec TF
ER_MIN = 0.20               # Kaufman efficiency ratio below this = pure noise
HTF_VETO = True             # veto a signal that fights the D1/H4 trend

# Score weights — AUTO-OPTIMIZED by signal_optimizer.py (grid/genetic over
# recorded outcomes, train/test split). Falls back to these defaults.
# Leading/real-time components: vel (M1 momentum), vwap (vs volume-weighted avg),
# imb (footprint aggressive imbalance), accel (delta acceleration). tf/ind LAG -> low weight.
DEFAULT_WEIGHTS = {"tf": 0.10, "ind": 0.06, "flow": 0.20, "zone": 0.06,
                   "wick": 0.10, "rev": 0.14, "vel": 0.20,
                   "vwap": 0.12, "imb": 0.12, "accel": 0.08,
                   "stoch": 0.16, "intermarket": 0.0, "sensitivity": 22.0}
# intermarket weight = 0.0: the complex test (intermarket_test.py) showed USD-inverse
# + silver does NOT predict gold direction at any horizon (30m/2h/6h ≈ 50% hit, corr≈0
# — correlation is contemporaneous, not predictive). Kept as DISPLAY-ONLY macro context;
# zero weight so an unvalidated signal can't drive trades. (Discipline: validate, don't assume.)

# --- Stochastic (8,3,3) reversal — USER's tested edge (his exact chart levels). ---
# The oscillator only ARMS the trade; it fires ONLY with candle-level CONFIRMATION
# (cross-back / rejection wick / zone touch / swing break / gap fill) — exactly
# what the user asked for ("تأكيد ... ذيل او ملامسة منطقة او اغلاق فجوة او كسر قمة/قاع").
STOCH_K, STOCH_SLOW, STOCH_D = 14, 3, 3   # matches the user's proven chart (14,3,3)
STOCH_OB, STOCH_OB_DEEP = 75.0, 88.0      # overbought (SELL zone) — widened 80→75 for MORE entries (user relies on bot to avoid manual tilt); 88 = deep
STOCH_OS, STOCH_OS_DEEP = 25.0, 12.0      # oversold  (BUY zone)  — widened 20→25; 12 = deep
# STRICT STOCH GATE (user's choice 2026-06-02): the signal fires ONLY at confirmed
# Stoch extremes — BUY only when %K<=15, SELL only when %K>=85 — matching Radhi's
# proven manual edge ($158 win). No entries in the mid-range, regardless of the
# blended score. Set False to revert to the 11-component blended action.
STOCH_GATE = True


def _load_weights():
    try:
        import json as _j
        w = _j.loads((Path(__file__).resolve().parent.parent / "data" / "signal_weights.json").read_text(encoding="utf-8"))
        return {k: float(w.get(k, DEFAULT_WEIGHTS[k])) for k in DEFAULT_WEIGHTS}
    except Exception:
        return dict(DEFAULT_WEIGHTS)

_TF_MT5 = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 16385}  # mt5 enum filled at runtime

LABEL = {"BUY": "اشترِ", "SELL": "بِع", "WAIT": "انتظر"}


def _action_from_confluence(dominant: str) -> str:
    return {"LONG": "BUY", "SHORT": "SELL"}.get(dominant, "WAIT")


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _flip_action(a: str) -> str:
    return "SELL" if a == "BUY" else "BUY" if a == "SELL" else a


def _signal_mode():
    """FOLLOW or FADE — learned by signal_learn. In FADE the signal is
    inverse-predictive so we FLIP it here (one source of truth: chart arrow +
    executor both show/trade the corrected direction)."""
    try:
        import json as _j
        t = _j.loads((Path(__file__).resolve().parent.parent / "data" / "signal_tuning.json").read_text(encoding="utf-8"))
        return t.get("mode", "FOLLOW")
    except Exception:
        return "FOLLOW"


def _velocity_signal(mt5, symbol):
    """Fast M1 price MOMENTUM — leads the signal so it moves WITH price in real
    time instead of lagging behind slow timeframes. Normalized by ATR."""
    try:
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 6)
        if r is None or len(r) < 5:
            return 0.0
        import numpy as np
        c = np.array([float(x["close"]) for x in r])
        h = np.array([float(x["high"]) for x in r]); l = np.array([float(x["low"]) for x in r])
        atr1 = float(np.mean(h - l)) or 1e-9
        chg = c[-1] - c[-5]                     # last ~4-5 min move
        return _clip(chg / (2.5 * atr1))        # ±1 when move ~2.5x avg M1 range
    except Exception:
        return 0.0


def _vwap_signal(mt5, symbol):
    """Price vs intraday VWAP (volume-weighted avg) — the institutional fair-value
    line. Above VWAP = bullish bias, below = bearish. Leading/real-time."""
    try:
        import numpy as np
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 240)
        if r is None or len(r) < 30:
            return 0.0
        h = np.array([float(x["high"]) for x in r]); l = np.array([float(x["low"]) for x in r])
        c = np.array([float(x["close"]) for x in r]); v = np.array([float(x["tick_volume"]) for x in r])
        tp = (h + l + c) / 3.0
        vw = float((tp * v).sum() / max(v.sum(), 1e-9))
        atr = float(np.mean(h - l)) or 1e-9
        return _clip((c[-1] - vw) / (2.0 * atr))
    except Exception:
        return 0.0


def _delta_scale(bars):
    """Pro-panel Step-2: per-symbol ROLLING scale for delta-based pillars so they
    self-normalize instead of using fixed magic divisors (cvd/1500, tape/1200,
    accel/800) that saturate ~the whole session and carry zero information.
    Returns (delta_std, dchg_std) from the recent FINALIZED footprint bars."""
    try:
        ds = [float(b.get("delta", 0) or 0) for b in bars[-24:-1]]       # exclude forming bar
        if len(ds) < 4:
            return 0.0, 0.0
        import statistics as _st
        dstd = _st.pstdev(ds)
        dchg = [ds[i] - ds[i - 1] for i in range(1, len(ds))]
        cstd = _st.pstdev(dchg) if len(dchg) >= 3 else dstd
        return float(dstd), float(cstd)
    except Exception:
        return 0.0, 0.0


def _imb_accel(symbol):
    """From the footprint export: (1) diagonal IMBALANCE of the last bar
    (aggressive buyers vs sellers), (2) delta ACCELERATION (is pressure growing)."""
    try:
        from runtime.shared import footprint_features as _ff
        raw = _ff._load(symbol)
        if not raw:
            return 0.0, 0.0
        bars = raw.get("bars") or []
        if len(bars) < 3:
            return 0.0, 0.0
        # BUGFIX (pro-panel): bars[-1] is the UNFINALIZED forming bar -> imb was
        # ~always 0.0 (dead pillar). Read the last FINALIZED bar (bars[-2]); use
        # bars[-3] as its predecessor so accel compares like-for-like full bars.
        last, prev = bars[-2], bars[-3]
        ib = float(last.get("imb_buy", 0) or 0); isl = float(last.get("imb_sell", 0) or 0)
        imb_n = _clip((ib - isl) / 6.0)                                  # aggressive flow imbalance (wider divisor)
        d_now = float(last.get("delta", 0) or 0); d_prev = float(prev.get("delta", 0) or 0)
        # accel = delta 2nd-derivative, z-scored by the rolling std of per-bar
        # delta-changes (Step-2 de-saturation; falls back to the old 800 divisor
        # when there isn't enough history yet).
        _, cstd = _delta_scale(bars)
        denom = (2.0 * cstd) if cstd > 1.0 else 800.0
        accel_n = _clip((d_now - d_prev) / denom)
        return imb_n, accel_n
    except Exception:
        return 0.0, 0.0


def _wick_signal(mt5, symbol):
    """Read the REJECTION WICK of the last 2 closed candles (M5 + M1).
    Long LOWER wick = buyers rejected lower prices -> BULLISH reversal (+).
    Long UPPER wick = sellers rejected higher prices -> BEARISH reversal (-).
    This is the 'tail' the user saw push price up against a SELL."""
    try:
        best = 0.0; desc = "no wick"
        for tf, tag in ((mt5.TIMEFRAME_M5, "M5"), (mt5.TIMEFRAME_M1, "M1")):
            r = mt5.copy_rates_from_pos(symbol, tf, 1, 2)   # last 2 CLOSED bars
            if r is None or len(r) < 1:
                continue
            b = r[-1]
            hi, lo, op, cl = float(b["high"]), float(b["low"]), float(b["open"]), float(b["close"])
            rng = hi - lo
            if rng <= 0:
                continue
            body_hi = max(op, cl); body_lo = min(op, cl)
            lower_wick = (body_lo - lo) / rng     # 0..1
            upper_wick = (hi - body_hi) / rng     # 0..1
            # net rejection: lower wick bullish (+), upper wick bearish (-)
            w = lower_wick - upper_wick           # -1..1
            if abs(w) > abs(best):
                best = w
                side = "lower(bullish reject)" if w > 0 else "upper(bearish reject)"
                desc = f"{tag} {side} {abs(w)*100:.0f}%"
        # only count a MEANINGFUL rejection wick (>40% of range one side)
        return (_clip(best) if abs(best) >= 0.40 else 0.0), desc
    except Exception:
        return 0.0, "wick_err"


# Timeframes the confidence is computed across (multi-timeframe agreement).
TIMEFRAMES = ["5m", "15m", "1h"]

# SPEED: the multi-TF confluence barely changes intra-minute (15m/1h bars are
# slow), so cache it; the FAST part (footprint delta/CVD/tape + spread) is
# recomputed every cycle so the % moves in near-real-time.
_TF_CACHE: dict = {}        # symbol -> (result, ts)
CONFLUENCE_TTL = 45.0       # recompute multi-TF indicators at most this often
SPREAD_MAX = {              # per-symbol "wide spread" reference (price units)
    "XAUUSDm": 0.45, "XAGUSDm": 0.05, "BTCUSDm": 30.0,
    "EURUSDm": 0.00025, "GBPUSDm": 0.00030,
}


def _multi_tf(symbol):
    """Cached multi-timeframe 11-indicator confluence (slow part)."""
    import time as _t
    hit = _TF_CACHE.get(symbol)
    if hit and _t.time() - hit[1] < CONFLUENCE_TTL:
        return hit[0]
    from r_native.live_indicators import compute_indicator_panel
    tf_detail = {}; tot_bull = tot_bear = tot_en = 0; tf_dirs = []
    for tf in TIMEFRAMES:
        p = compute_indicator_panel(symbol, tf)
        c = p.get("confluence", {}) if isinstance(p, dict) else {}
        b = int(c.get("bullish", 0)); be = int(c.get("bearish", 0)); en = int(c.get("enabled", 11))
        tot_bull += b; tot_bear += be; tot_en += en
        tdir = "BUY" if b > be else "SELL" if be > b else "NEUTRAL"
        tf_dirs.append(tdir); tf_detail[tf] = f"{tdir} ({b}↑/{be}↓)"
    res = (tf_detail, tot_bull, tot_bear, tot_en, tf_dirs)
    _TF_CACHE[symbol] = (res, _t.time())
    return res


def _genome_bias(symbol: str) -> tuple[str, str]:
    """Read the live genome's side_bias for `symbol` -> (bias, name).
    bias in {BUY_ONLY, SELL_ONLY, ""}. Connects 'the genes' to the on-chart call."""
    try:
        import pathlib
        f = pathlib.Path(_V2) / "data" / f"live_genome__{symbol}.json"
        if not f.exists():
            return "", ""
        d = json.loads(f.read_text(encoding="utf-8"))
        g = d.get("params", d)
        sb = g.get("side_bias")
        name = d.get("name", g.get("name", ""))
        return (sb or ""), name
    except Exception:
        return "", ""


def _zones_near(symbol: str, price: float, mt5) -> tuple[list, str]:
    """Real SMC supply/demand zones near price (no LLM). Returns (zones, note)."""
    try:
        from runtime.shared.order_blocks import detect_order_blocks, in_zone
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 400)
        if rates is None or len(rates) < 60:
            return [], ""
        obs = detect_order_blocks(rates) or []
        zones = []
        for z in obs:
            if z.get("mitigated"):
                continue
            hi = float(z.get("hi", z.get("top", 0)))
            lo = float(z.get("lo", z.get("bot", 0)))
            kind = z.get("type", z.get("kind", "supply"))
            zones.append({"top": round(hi, 5), "bot": round(lo, 5), "kind": kind})
        zones = zones[-6:]                       # most recent few
        note = ""
        here = in_zone(price, obs) if obs else []
        for z in here:
            k = z.get("type", z.get("kind", ""))
            if k == "demand":
                note = "price at DEMAND zone (buy support)"
            elif k == "supply":
                note = "price at SUPPLY zone (sell pressure)"
        return zones, note
    except Exception as e:
        return [], f"zones_err:{e}"


def _stochastic(mt5, symbol, tf, kp=STOCH_K, ks=STOCH_SLOW, dp=STOCH_D, n=80):
    """Stochastic(kp, ks, dp). Returns (%K_last, %D_last, %K_prev, %D_prev) on
    CLOSED bars so the cross is real (not repainting on the forming bar)."""
    try:
        import numpy as np
        r = mt5.copy_rates_from_pos(symbol, tf, 1, n)      # closed bars only
        if r is None or len(r) < kp + ks + dp + 2:
            return None
        h = np.array([x["high"] for x in r], float)
        l = np.array([x["low"] for x in r], float)
        c = np.array([x["close"] for x in r], float)
        rawk = []
        for i in range(kp - 1, len(c)):
            hh = h[i - kp + 1:i + 1].max(); ll = l[i - kp + 1:i + 1].min()
            rawk.append(100.0 * (c[i] - ll) / (hh - ll) if hh > ll else 50.0)
        rawk = np.array(rawk)
        k = np.convolve(rawk, np.ones(ks) / ks, "valid")   # %K = SMA(ks) of rawk
        d = np.convolve(k, np.ones(dp) / dp, "valid")      # %D = SMA(dp) of %K
        if len(d) < 2 or len(k) < 2:
            return None
        return float(k[-1]), float(d[-1]), float(k[-2]), float(d[-2])
    except Exception:
        return None


def _swing_break(mt5, symbol, tf, lookback=20):
    """Did the last CLOSED candle BREAK a recent swing high/low?
    +1 = closed above prior high (bullish breakout), -1 = below prior low."""
    try:
        import numpy as np
        r = mt5.copy_rates_from_pos(symbol, tf, 1, lookback + 2)
        if r is None or len(r) < lookback:
            return 0, ""
        h = np.array([x["high"] for x in r], float)
        l = np.array([x["low"] for x in r], float)
        c = np.array([x["close"] for x in r], float)
        if c[-1] > h[:-1].max():
            return 1, f"كسر قمة {lookback} شمعة"
        if c[-1] < l[:-1].min():
            return -1, f"كسر قاع {lookback} شمعة"
        return 0, ""
    except Exception:
        return 0, ""


def _gap_fill(mt5, symbol, tf):
    """Light gap detector: did the last closed bar FILL a gap left by the bar
    before it? +1 = down-gap filled & closed up (bullish), -1 = up-gap filled
    & closed down (bearish). Gaps are rare intrabar on CFDs but matter at
    session/weekend opens — the user explicitly asked for 'اغلاق فجوة'."""
    try:
        import numpy as np
        r = mt5.copy_rates_from_pos(symbol, tf, 1, 4)
        if r is None or len(r) < 3:
            return 0, ""
        prev2, prev1, last = r[-3], r[-2], r[-1]
        o, c = float(last["open"]), float(last["close"])
        # down gap: prev1 opened below prev2 low; bullish if last closed back above it
        if float(prev1["open"]) < float(prev2["low"]) and c > float(prev2["low"]) and c > o:
            return 1, "إغلاق فجوة هابطة"
        if float(prev1["open"]) > float(prev2["high"]) and c < float(prev2["high"]) and c < o:
            return -1, "إغلاق فجوة صاعدة"
        return 0, ""
    except Exception:
        return 0, ""


def _stoch_signal(mt5, symbol, tf, wick_n, zone_n):
    """USER's Stochastic(8,3,3) reversal WITH candle-level confirmation.
    Returns (stoch_n in [-1,1], confirmed: bool, detail: str).

    Logic: the oscillator must be in the user's extreme zone (≥85 sell / ≤15 buy),
    THEN at least one CONFIRMATION must fire on the candle:
      • %K crosses back out of the zone (crosses %D) — the classic stoch trigger
      • rejection wick (ذيل) in the reversal direction
      • price at a demand/supply ZONE (ملامسة منطقة)
      • swing break (كسر قمة/قاع)  • gap fill (إغلاق فجوة)
    Strength = depth-in-zone × (1 + #confirmations). NEVER fires on the bare
    extreme — confirmation is mandatory (exactly the user's request)."""
    st = _stochastic(mt5, symbol, tf)
    if not st:
        return 0.0, False, "no stoch"
    k, d, k0, d0 = st
    confs = []
    direction = 0
    if k <= STOCH_OS:                                   # OVERSOLD -> look for BUY
        direction = 1
        depth = (STOCH_OS - k) / STOCH_OS               # 0..1, deeper = stronger
        if k > d and k0 <= d0:        confs.append("تقاطع %K↑ صاعد")    # cross up
        elif k > k0:                  confs.append("%K ينعطف صاعد")      # turning up
        if wick_n > 0.30:             confs.append("ذيل سفلي (رفض)")
        if zone_n > 0:                confs.append("عند منطقة طلب")
    elif k >= STOCH_OB:                                  # OVERBOUGHT -> look for SELL
        direction = -1
        depth = (k - STOCH_OB) / (100.0 - STOCH_OB)
        if k < d and k0 >= d0:        confs.append("تقاطع %K↓ هابط")
        elif k < k0:                  confs.append("%K ينعطف هابط")
        if wick_n < -0.30:            confs.append("ذيل علوي (رفض)")
        if zone_n < 0:                confs.append("عند منطقة عرض")
    else:
        return 0.0, False, f"%K {k:.0f} mid"

    sb, sb_desc = _swing_break(mt5, symbol, tf)
    if sb == direction and sb_desc:   confs.append(sb_desc)
    gf, gf_desc = _gap_fill(mt5, symbol, tf)
    if gf == direction and gf_desc:   confs.append(gf_desc)

    # a %K turn alone is the weakest confirmation; require a REAL trigger
    # (cross / wick / zone / break / gap) for the signal to count as confirmed.
    strong_confs = [c for c in confs if "ينعطف" not in c]
    confirmed = len(strong_confs) >= 1
    deep = (k <= STOCH_OS_DEEP) or (k >= STOCH_OB_DEEP)
    if not confirmed:
        # armed but unconfirmed -> tiny lean only (does not trigger entry)
        lean = 0.15 * direction * (1.2 if deep else 1.0)
        return _clip(lean), False, f"%K {k:.0f} {'مفرط شراء' if direction<0 else 'مفرط بيع'} — ينتظر تأكيد"
    base = max(0.45, min(1.0, 0.45 + 0.20 * depth + 0.18 * len(strong_confs) + (0.12 if deep else 0.0)))
    detail = f"%K {k:.0f}/%D {d:.0f} {'⤴BUY' if direction>0 else '⤵SELL'} | " + "، ".join(strong_confs)
    return _clip(direction * base), True, detail


_INTERMKT_CACHE: dict = {}      # cache the cross-market read (changes slowly)


def _intermarket_align(mt5, symbol):
    """INVERSE-CORRELATION (intermarket) context for GOLD — NEW orthogonal info
    (USD flows + metals), NOT another oscillator on gold's own price.
    Returns (signed [-1,1], detail): + = bullish-gold macro context.
      • USD strength (DXY proxy from EUR/JPY/GBP/CHF — DXY not on broker): gold
        is INVERSE to the dollar, so usd_strong -> bearish gold.
      • Silver (XAG) confirmation: precious-metals move together (positive corr).
    Only meaningful for XAUUSDm; 0 for other symbols."""
    if symbol != "XAUUSDm":
        return 0.0, ""
    import time as _t
    hit = _INTERMKT_CACHE.get(symbol)
    if hit and _t.time() - hit[1] < 20.0:
        return hit[0]
    out = (0.0, "")
    try:
        import numpy as np
        def _ret(sym, n=12):
            r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 1, n + 1)
            if r is None or len(r) < n + 1:
                return None
            c = np.array([x["close"] for x in r], float)
            return (c[-1] - c[0]) / c[0] if c[0] else None
        eur = _ret("EURUSDm"); jpy = _ret("USDJPYm"); gbp = _ret("GBPUSDm"); chf = _ret("USDCHFm")
        usd_parts = []
        if eur is not None: usd_parts.append(-eur)   # EURUSD down => USD up
        if gbp is not None: usd_parts.append(-gbp)
        if jpy is not None: usd_parts.append(jpy)     # USDJPY up => USD up
        if chf is not None: usd_parts.append(chf)     # USDCHF up => USD up
        if not usd_parts:
            return out
        usd = sum(usd_parts) / len(usd_parts)
        usd_n = max(-1.0, min(1.0, usd / 0.003))      # ~0.3% M5x12 move = full scale
        gold_ctx = -usd_n                              # gold INVERSE to USD
        sil = _ret("XAGUSDm")
        sil_n = max(-1.0, min(1.0, sil / 0.004)) if sil is not None else 0.0
        val = max(-1.0, min(1.0, 0.6 * gold_ctx + 0.4 * sil_n))
        detail = (f"USD {usd*100:+.2f}% → ذهب {'صاعد' if gold_ctx > 0 else 'هابط'} | "
                  f"فضة {(sil*100 if sil else 0):+.2f}%")
        out = (round(val, 3), detail)
    except Exception as e:
        out = (0.0, f"err:{e}")
    _INTERMKT_CACHE[symbol] = (out, _t.time())
    return out


_REGIME_CACHE: dict = {}        # symbol -> (result, ts) — ADX/ER/HTF change slowly


def _regime_filter(mt5, symbol):
    """Pro-panel Step-1 gate. Returns dict:
       adx   : Wilder ADX(14) on the execution TF (M15) — trend STRENGTH
       er    : Kaufman efficiency ratio (0..1) — signal vs noise
       no_trend : True when ADX<ADX_MIN or er<ER_MIN (chop -> suppress signals)
       htf_dir  : 'BUY'/'SELL'/'NEUTRAL' from D1+H4 EMA50/EMA200 regime
    The two trending facts the brain was previously BLIND to (it only ran 5m/15m/1h).
    Cached 45s — these barely move intrabar."""
    import time as _t
    hit = _REGIME_CACHE.get(symbol)
    if hit and _t.time() - hit[1] < 45.0:
        return hit[0]
    res = {"adx": 0.0, "er": 1.0, "no_trend": False, "htf_dir": "NEUTRAL"}
    try:
        import numpy as np
        # --- ADX(14) + efficiency ratio on the execution TF (M15) ---
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 60)
        if r is not None and len(r) >= 30:
            h = np.array([x["high"] for x in r], float)
            l = np.array([x["low"] for x in r], float)
            c = np.array([x["close"] for x in r], float)
            pc = np.roll(c, 1); pc[0] = c[0]
            tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
            up = h[1:] - h[:-1]; dn = l[:-1] - l[1:]
            plus = np.where((up > dn) & (up > 0), up, 0.0)
            minus = np.where((dn > up) & (dn > 0), dn, 0.0)
            n = 14
            atr = tr[1:][-n:].mean() or 1e-9
            pdi = 100 * plus[-n:].mean() / atr
            mdi = 100 * minus[-n:].mean() / atr
            dx = 100 * abs(pdi - mdi) / max(pdi + mdi, 1e-9)
            res["adx"] = round(float(dx), 1)
            # efficiency ratio over last n bars
            n2 = min(n, len(c) - 1)
            direction = abs(c[-1] - c[-1 - n2])
            volatility = np.abs(np.diff(c[-1 - n2:])).sum() or 1e-9
            res["er"] = round(float(direction / volatility), 3)
        # A STRONG ADX (>=25, the classic trend threshold) means a real trend
        # exists even if the path was choppy (low efficiency) — so a high ADX
        # OVERRIDES the ER chop filter. Without this, an obvious strong downtrend
        # (ADX 38.8) was wrongly tagged "no-trend" just because ER<0.2, blocking
        # legitimate with-trend signals (caught on the user's screen recording).
        strong_adx = res["adx"] >= 25.0
        res["no_trend"] = (res["adx"] < ADX_MIN) or (res["er"] < ER_MIN and not strong_adx)
        # --- HTF trend: D1 + H4 EMA50/EMA200 regime ---
        votes = []
        for tf in (mt5.TIMEFRAME_D1, mt5.TIMEFRAME_H4):
            rr = mt5.copy_rates_from_pos(symbol, tf, 0, 220)
            if rr is None or len(rr) < 60:
                continue
            cl = np.array([x["close"] for x in rr], float)
            def _ema(a, p):
                k = 2.0 / (p + 1.0); e = a[0]
                for v in a[1:]:
                    e = v * k + e * (1 - k)
                return e
            e50 = _ema(cl, 50); e200 = _ema(cl, min(200, len(cl) - 1)); px = cl[-1]
            if px > e50 and px > e200:
                votes.append(1)
            elif px < e50 and px < e200:
                votes.append(-1)
            else:
                votes.append(0)
        s = sum(votes)
        res["htf_dir"] = "BUY" if s > 0 else "SELL" if s < 0 else "NEUTRAL"
    except Exception as e:
        res["err"] = str(e)
    _REGIME_CACHE[symbol] = (res, _t.time())
    return res


def _atr_m15(mt5, symbol, n=14):
    try:
        import numpy as np
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, n + 2)
        if r is None or len(r) < n + 1:
            return 0.0
        h = np.array([x["high"] for x in r], float); l = np.array([x["low"] for x in r], float)
        c = np.array([x["close"] for x in r], float); pc = np.roll(c, 1); pc[0] = c[0]
        tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
        return float(np.mean(tr[-n:]))
    except Exception:
        return 0.0


def _signal_levels(mt5, symbol, price, action, zones):
    """Concrete on-chart price LEVELS for the trade: entry / target / stop, plus
    the nearest supply & demand. Target/stop snap to the nearest SMC zone in the
    trade direction, else fall back to ATR multiples (2R target / 1.2R stop)."""
    out = {"entry": round(price, 5)}
    try:
        atr = _atr_m15(mt5, symbol) or (price * 0.001)
        sup = [ (z.get("bot") or z.get("top")) for z in zones if z.get("kind") == "supply" ]
        dem = [ (z.get("top") or z.get("bot")) for z in zones if z.get("kind") == "demand" ]
        sup_above = sorted([s for s in sup if s and s > price])
        dem_below = sorted([d for d in dem if d and d < price], reverse=True)
        nearest_supply = sup_above[0] if sup_above else None
        nearest_demand = dem_below[0] if dem_below else None
        out["nearest_supply"] = round(nearest_supply, 5) if nearest_supply else None
        out["nearest_demand"] = round(nearest_demand, 5) if nearest_demand else None
        # Radhi's management table: stop BEYOND the zone by 1xATR; TP1 = 1:2 R:R
        # (close half there); TP2 = the next opposite zone (let the rest run).
        tp = tp1 = tp2 = sl = None
        if action == "BUY":
            sl = (nearest_demand - 1.0 * atr) if nearest_demand else (price - 1.2 * atr)
            R = max(price - sl, atr * 0.3)
            tp1 = price + 2.0 * R
            tp2 = nearest_supply if (nearest_supply and nearest_supply > tp1) else price + 4.0 * R
            tp = tp1
        elif action == "SELL":
            sl = (nearest_supply + 1.0 * atr) if nearest_supply else (price + 1.2 * atr)
            R = max(sl - price, atr * 0.3)
            tp1 = price - 2.0 * R
            tp2 = nearest_demand if (nearest_demand and nearest_demand < tp1) else price - 4.0 * R
            tp = tp1
        out["tp"] = round(tp, 5) if tp else None
        out["tp1"] = round(tp1, 5) if tp1 else None
        out["tp2"] = round(tp2, 5) if tp2 else None
        out["sl"] = round(sl, 5) if sl else None
        out["rr"] = 2.0 if tp1 else None
        out["atr"] = round(atr, 5)
        # STOCH guide levels: the PRICE at which raw %K would hit the user's 15/85
        # lines, from the Stoch high/low range — "where price must reach to trigger".
        import numpy as np
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 1, STOCH_K)   # M1 to match chart Stoch
        if r is not None and len(r) >= STOCH_K:
            hh = float(np.max([x["high"] for x in r])); ll = float(np.min([x["low"] for x in r]))
            if hh > ll:
                out["stoch_buy_px"] = round(ll + (STOCH_OS / 100.0) * (hh - ll), 5)   # %K=15 → BUY
                out["stoch_sell_px"] = round(ll + (STOCH_OB / 100.0) * (hh - ll), 5)  # %K=85 → SELL
    except Exception as e:
        out["err"] = str(e)
    return out


def compute_signal(symbol: str, mt5) -> dict:
    """Confluence + SMC -> {action, confidence, label, zones, ...} for one symbol."""
    out = {"schema_version": 1, "source": "r_native_brain", "symbol": symbol,
           "ts": int(time.time()), "tf": TF, "action": "WAIT", "confidence": 0.0,
           "label": LABEL["WAIT"], "dominant": "NONE", "bullish": 0, "bearish": 0,
           "price": 0.0, "zones": [], "reason": ""}
    try:
        tick = mt5.symbol_info_tick(symbol)
        price = float(tick.bid) if tick else 0.0
        out["price"] = round(price, 5)

        # ===== SPREAD (fast) — wide spread = bad conditions -> damps the % =====
        spread = (float(tick.ask) - float(tick.bid)) if tick else 0.0
        smax = SPREAD_MAX.get(symbol, 0.0) or (price * 0.0002 if price else 1.0)
        # softer damp: at spread==smax quality~0.55 (reduce, don't annihilate)
        spread_quality = max(0.55, min(1.0, 1.0 - 0.5 * (spread / smax))) if smax > 0 else 1.0
        out["spread"] = round(spread, 5)
        out["spread_quality"] = round(spread_quality, 2)

        # ===== REGIME GATE (pro-panel Step-1): trend-strength + HTF context =====
        reg = _regime_filter(mt5, symbol)
        out["regime"] = {"adx": reg["adx"], "er": reg["er"],
                         "no_trend": reg["no_trend"], "htf_dir": reg["htf_dir"]}

        # ===== PILLARS 1+2: MULTI-TIMEFRAME indicator agreement (CACHED/slow) =====
        tf_detail, tot_bull, tot_bear, tot_en, tf_dirs = _multi_tf(symbol)
        n_buy = tf_dirs.count("BUY"); n_sell = tf_dirs.count("SELL")
        tf_n = _clip((n_buy - n_sell) / len(TIMEFRAMES))       # timeframe consensus
        ind_n = _clip((tot_bull - tot_bear) / max(tot_en, 1))  # indicator consensus across TFs
        out["bullish"] = tot_bull; out["bearish"] = tot_bear
        out["dominant"] = "LONG" if n_buy > n_sell else "SHORT" if n_sell > n_buy else "NONE"

        # ===== PILLAR 3: ORDER FLOW (footprint meter + CVD + tape) =====
        sig_n = cvd_n = tape_n = 0.0
        flow_fresh = False
        try:
            from runtime.shared import footprint_features as _ffmod
            raw = _ffmod._load(symbol)
            if raw:
                flow_fresh = True
                sig_n = _clip(float(raw.get("signal_value") or 0) / 100.0)
                bars = raw.get("bars") or []
                # Step-2 de-saturation: normalize CVD + tape by the symbol's own
                # rolling delta scale instead of fixed /1500 and /1200 (which
                # pinned cvd at -1.0 nearly the whole session = dead weight).
                dstd, _ = _delta_scale(bars)
                cvd_div = (dstd * (max(len(bars), 1) ** 0.5) * 1.5) if dstd > 1.0 else 1500.0
                tape_div = (2.0 * dstd) if dstd > 1.0 else 1200.0
                cvd_n = _clip(float(raw.get("cum_delta") or 0) / max(cvd_div, 1.0))
                if len(bars) >= 2:   # last FINALIZED bar (bars[-1] is forming)
                    tape_n = _clip(float(bars[-2].get("delta", bars[-2].get("d", 0)) or 0) / max(tape_div, 1.0))
        except Exception:
            pass
        flow_n = _clip(0.35 * sig_n + 0.30 * cvd_n + 0.35 * tape_n)
        flow_dir = "BUY" if flow_n > 0.12 else "SELL" if flow_n < -0.12 else "NEUTRAL"
        out["footprint_signal"] = round(sig_n * 100, 0)
        out["cvd_norm"] = round(cvd_n, 2); out["tape_norm"] = round(tape_n, 2)

        # ===== PILLAR 4: SMC ZONE touch =====
        zones, note = _zones_near(symbol, price, mt5)
        out["zones"] = zones
        zone_n = 1.0 if "DEMAND" in note else -1.0 if "SUPPLY" in note else 0.0

        # ===== PILLAR 5: REJECTION WICK (the 'tail') =====
        wick_n, wick_desc = _wick_signal(mt5, symbol)
        out["wick"] = wick_desc

        # ===== PILLAR 6: FAST PRICE VELOCITY (leads, doesn't lag) =====
        vel_n = _velocity_signal(mt5, symbol)
        out["velocity"] = round(vel_n, 3)

        # ===== PILLARS 7-9: VWAP position · footprint IMBALANCE · delta ACCEL =====
        vwap_n = _vwap_signal(mt5, symbol)
        imb_n, accel_n = _imb_accel(symbol)
        out["vwap"] = round(vwap_n, 3); out["imb"] = round(imb_n, 3); out["accel"] = round(accel_n, 3)

        # ===== PILLAR 10: STOCHASTIC(14,3,3) REVERSAL + CONFIRMATION (user's edge) =====
        # MUST match the user's CHART timeframe (M1) — he scalps M1 and his Stoch
        # subwindow is M1. Computing it on M15 made the panel say %K91 (overbought)
        # while his M1 chart showed %K~10 (oversold) → bot SOLD as price was
        # bouncing UP = the contradiction Radhi circled. Stoch is now M1.
        _stf = getattr(mt5, "TIMEFRAME_M1", None) or mt5.TIMEFRAME_M1
        stoch_n, stoch_confirmed, stoch_detail = _stoch_signal(mt5, symbol, _stf, wick_n, zone_n)
        out["stoch"] = stoch_detail; out["stoch_confirmed"] = stoch_confirmed

        # ===== PILLAR 12: INTERMARKET (inverse correlation — USD/metals) =====
        intermkt_n, intermkt_detail = _intermarket_align(mt5, symbol)
        out["intermarket"] = intermkt_detail

        # ===== REVERSAL SYNERGY: rejection wick + (zone OR flow) agree =====
        # A strong tail at a level/flow = high-prob TURN. This lets a reversal
        # candle TRIGGER an entry even while the slow multi-TF still says WAIT
        # (the user's "wick appears, price reverses, but it doesn't enter" case).
        rev_n = 0.0
        if abs(wick_n) >= 0.35:
            up = wick_n > 0
            if (up and (zone_n > 0 or flow_n > 0.10)) or ((not up) and (zone_n < 0 or flow_n < -0.10)):
                rev_n = wick_n
        out["reversal"] = ("BUY-reversal" if rev_n > 0 else "SELL-reversal" if rev_n < 0 else "none")

        # ===== GENOME =====
        gbias, gname = _genome_bias(symbol)
        out["genome"] = gname; out["genome_bias"] = gbias or "none"

        # ===== BLENDED SCORE (-100..+100) =====  (weights AUTO-OPTIMIZED)
        W = _load_weights()
        out["components"] = {"tf": round(tf_n, 3), "ind": round(ind_n, 3), "flow": round(flow_n, 3),
                             "zone": round(zone_n, 3), "wick": round(wick_n, 3), "rev": round(rev_n, 3),
                             "vel": round(vel_n, 3), "vwap": round(vwap_n, 3),
                             "imb": round(imb_n, 3), "accel": round(accel_n, 3),
                             "stoch": round(stoch_n, 3), "intermarket": round(intermkt_n, 3)}
        score = 100.0 * (W["tf"] * tf_n + W["ind"] * ind_n + W["flow"] * flow_n +
                         W["zone"] * zone_n + W["wick"] * wick_n + W["rev"] * rev_n +
                         W.get("vel", 0.20) * vel_n + W.get("vwap", 0.12) * vwap_n +
                         W.get("imb", 0.12) * imb_n + W.get("accel", 0.08) * accel_n +
                         W.get("stoch", 0.16) * stoch_n + W.get("intermarket", 0.10) * intermkt_n)
        if gbias == "BUY_ONLY":
            score += 12
        elif gbias == "SELL_ONLY":
            score -= 12
        # REVERSAL OVERRIDE: a strong rejection AT a level/flow forces the score
        # past WAIT in the reversal direction — so it ENTERS the turn instead of
        # waiting for the lagging multi-TF to catch up.
        strong_rev = abs(rev_n) >= 0.45 and not (gbias == "BUY_ONLY" and rev_n < 0) and not (gbias == "SELL_ONLY" and rev_n > 0)
        if strong_rev:
            floor = 30.0 if rev_n > 0 else -30.0
            score = max(score, floor) if rev_n > 0 else min(score, floor)
        # CONFIRMED STOCH REVERSAL — the user's tested edge. A Stoch extreme WITH
        # candle confirmation is a high-prob TURN: floor the score so it ENTERS
        # (and below, it is allowed past the no-trend chop gate — range is exactly
        # where stochastic mean-reversion works). Genome side_bias still respected.
        stoch_rev = bool(stoch_confirmed) and abs(stoch_n) >= 0.45 and \
            not (gbias == "BUY_ONLY" and stoch_n < 0) and not (gbias == "SELL_ONLY" and stoch_n > 0)
        if stoch_rev:
            floor = 28.0 if stoch_n > 0 else -28.0
            score = max(score, floor) if stoch_n > 0 else min(score, floor)
        score = max(-100.0, min(100.0, score))
        out["score"] = round(score, 0)
        sdir = 1 if score > 0 else (-1 if score < 0 else 0)

        # ===== TRANSPARENT CONFIDENCE: count agreeing PILLARS =====
        # pillars = each timeframe (3) + order-flow (1) + zone (1 if touched).
        agree = 0; total_p = 0; pill = []
        for tf in TIMEFRAMES:
            td = tf_dirs[TIMEFRAMES.index(tf)]
            total_p += 1
            if sdir != 0 and td != "NEUTRAL" and (td == "BUY") == (sdir > 0):
                agree += 1; pill.append(f"{tf}✓")
            else:
                pill.append(f"{tf}:{td.lower()}")
        total_p += 1
        if sdir != 0 and flow_dir != "NEUTRAL" and (flow_dir == "BUY") == (sdir > 0):
            agree += 1; pill.append("flow✓")
        else:
            pill.append(f"flow:{flow_dir.lower()}")
        if zone_n != 0:
            total_p += 1
            if sdir != 0 and (zone_n > 0) == (sdir > 0):
                agree += 1; pill.append("zone✓")
            else:
                pill.append("zone✗")
        if wick_n != 0:
            total_p += 1
            if sdir != 0 and (wick_n > 0) == (sdir > 0):
                agree += 1; pill.append("wick✓")
            else:
                pill.append("wick✗")
        if rev_n != 0:
            total_p += 1
            if sdir != 0 and (rev_n > 0) == (sdir > 0):
                agree += 2; total_p += 1; pill.append("REVERSAL✓✓")   # high-prob -> counts double
            else:
                pill.append("rev✗")
        if stoch_confirmed and stoch_n != 0:
            total_p += 1
            if sdir != 0 and (stoch_n > 0) == (sdir > 0):
                agree += 2; total_p += 1; pill.append("STOCH✓✓")      # confirmed reversal -> counts double
            else:
                pill.append("stoch✗")
        agree_ratio = agree / max(total_p, 1)
        strength = min(1.0, abs(score) / 60.0)
        # SPREAD damps the % — wide spread (bad fills, edge-killer) lowers conviction
        conviction = round(min(95.0, 100.0 * agree_ratio * (0.5 + 0.5 * strength) * spread_quality), 0)
        # strong confirmed reversal -> floor the conviction so it actually ENTERS the turn
        if strong_rev and (sdir > 0) == (rev_n > 0):
            conviction = max(conviction, round(58.0 * spread_quality + 0.5))
        # confirmed STOCH reversal (user's edge) -> floor conviction too
        if stoch_rev and sdir != 0 and (sdir > 0) == (stoch_n > 0):
            conviction = max(conviction, round(58.0 * spread_quality + 0.5))
        out["conviction"] = conviction
        out["agree"] = f"{agree}/{total_p}"
        out["breakdown"] = {
            "timeframes": tf_detail,
            "tf_consensus": f"{n_buy} BUY / {n_sell} SELL of {len(TIMEFRAMES)}",
            "indicators_total": f"{tot_bull}↑ / {tot_bear}↓ across {len(TIMEFRAMES)} TFs",
            "order_flow": f"meter {out['footprint_signal']:+.0f} · CVD {cvd_n:+.2f} · tape {tape_n:+.2f} → {flow_dir}",
            "zone": note or "no zone touch",
            "wick": wick_desc,
            "stoch": stoch_detail + (" ✅مؤكَّد" if stoch_confirmed else ""),
            "reversal": out.get("reversal", "none"),
            "spread": f"{spread:.5f} (quality {spread_quality:.2f})",
            "genome": gbias or "none",
            "pillars_agree": f"{agree}/{total_p}  [{' '.join(pill)}]",
        }

        # ===== ACTION =====
        genome_vetoes = (gbias == "BUY_ONLY" and score < 0) or (gbias == "SELL_ONLY" and score > 0)
        # REGIME GATE: in chop (no trend) suppress directional signals unless a
        # STRONG confirmed reversal is firing (a turn at a level is the one edge
        # worth taking in a range). HTF VETO: don't fight the D1/H4 trend.
        chop_blocks = reg["no_trend"] and not strong_rev and not stoch_rev
        # A CONFIRMED stochastic reversal (the user's PROVEN edge: buy 10/15
        # oversold, sell 85/90 overbought) is a mean-reversion SCALP and is
        # allowed to fire AGAINST the HTF trend — that bounce-from-extreme is
        # exactly the trade Radhi profits from. strong_rev (wick synergy) also bypasses.
        htf_vetoes = HTF_VETO and reg["htf_dir"] in ("BUY", "SELL") and (
            (reg["htf_dir"] == "SELL" and score > 0) or (reg["htf_dir"] == "BUY" and score < 0)
        ) and not strong_rev and not stoch_rev
        head = (f"{agree}/{total_p} pillars · TF {n_buy}↑/{n_sell}↓ · ind {tot_bull}/{tot_bear} · "
                f"flow {flow_dir} · zone {note or '—'} · ADX {reg['adx']} ER {reg['er']} · HTF {reg['htf_dir']}")
        sens = W.get("sensitivity", SENSITIVITY)
        stoch_gated = False
        if STOCH_GATE:
            # PURE STOCH method — the user's proven edge. Direction is dictated by
            # the confirmed Stoch extreme (buy oversold / sell overbought); the
            # blend only sets conviction. No mid-range entries; no FADE.
            stoch_gated = True
            sconv = round(min(95.0, (50.0 + 45.0 * abs(stoch_n)) * spread_quality)) if stoch_confirmed else 0.0
            # let agreeing components lift conviction a touch
            if stoch_confirmed and sdir != 0 and (sdir > 0) == (stoch_n > 0):
                sconv = round(min(95.0, sconv + 8.0 * agree_ratio))
            if genome_vetoes and stoch_confirmed and (
                    (gbias == "BUY_ONLY" and stoch_n < 0) or (gbias == "SELL_ONLY" and stoch_n > 0)):
                out["action"] = "WAIT"; out["mode"] = "GENOME_VETO"; out["confidence"] = 0.0
                reason = f"WAIT: genome {gbias} vs Stoch | {head}"
            elif stoch_confirmed and stoch_n > 0:
                out["action"] = "BUY"; out["mode"] = "STOCH_GATE"; out["confidence"] = sconv
                reason = f"BUY {sconv:.0f}% [STOCH≤{STOCH_OS:.0f} مؤكَّد] | {out.get('stoch','')} | {head}"
            elif stoch_confirmed and stoch_n < 0:
                out["action"] = "SELL"; out["mode"] = "STOCH_GATE"; out["confidence"] = sconv
                reason = f"SELL {sconv:.0f}% [STOCH≥{STOCH_OB:.0f} مؤكَّد] | {out.get('stoch','')} | {head}"
            else:
                out["action"] = "WAIT"; out["mode"] = "STOCH_WAIT"; out["confidence"] = 0.0
                reason = f"WAIT: ينتظر مستوى ستوكاستك (≤{STOCH_OS:.0f} شراء / ≥{STOCH_OB:.0f} بيع) | {out.get('stoch','')}"
        if stoch_gated:
            pass
        elif genome_vetoes:
            out["action"] = "WAIT"; out["mode"] = "GENOME_VETO"; out["confidence"] = 0.0
            reason = f"WAIT: genome {gbias} vs score {score:+.0f}"
        elif chop_blocks:
            out["action"] = "WAIT"; out["mode"] = "REGIME_CHOP"; out["confidence"] = 0.0
            why = []
            if reg["adx"] < ADX_MIN: why.append(f"ADX {reg['adx']}<{ADX_MIN:.0f}")
            if reg["er"] < ER_MIN: why.append(f"ER {reg['er']}<{ER_MIN}")
            reason = f"WAIT: no-trend ({', '.join(why)}) | {head}"
        elif htf_vetoes:
            out["action"] = "WAIT"; out["mode"] = "HTF_VETO"; out["confidence"] = 0.0
            reason = f"WAIT: HTF {reg['htf_dir']} vetoes score {score:+.0f} (don't fight D1/H4) | {head}"
        elif score >= sens:
            out["action"] = "BUY"; out["mode"] = "SCORE"; out["confidence"] = conviction
            reason = f"BUY {conviction:.0f}% | {head}"
        elif score <= -sens:
            out["action"] = "SELL"; out["mode"] = "SCORE"; out["confidence"] = conviction
            reason = f"SELL {conviction:.0f}% | {head}"
        else:
            out["action"] = "WAIT"; out["mode"] = "WEAK"; out["confidence"] = conviction
            reason = f"WAIT score {score:+.0f} (<{sens:.0f}) | {head}"
        out["label"] = LABEL[out["action"]]
        # ===== FADE: flip here so the CHART ARROW and the EXECUTOR agree =====
        # If the learner found the raw signal inverse-predictive, the corrected
        # (traded) direction is the OPPOSITE — show THAT on the chart too.
        mode = _signal_mode()
        out["mode_learned"] = mode
        # FADE GATE (pro-panel): a reliably-inverse blend means the WEIGHTS are
        # mis-specified, not that fading is an edge. Only fade in confirmed
        # range/no-trend, and NEVER fade a signal that AGREES with the HTF trend
        # (that is the worst-case error the panel caught: SELL aligned with the
        # daily downtrend got flipped to BUY into supply).
        fade_ok = (mode == "FADE" and out["action"] in ("BUY", "SELL") and not STOCH_GATE)
        if fade_ok and reg["htf_dir"] in ("BUY", "SELL") and out["action"] == reg["htf_dir"]:
            fade_ok = False
            reason = f"[FADE skipped: signal agrees with HTF {reg['htf_dir']}] " + reason
        if fade_ok:
            out["orig_action"] = out["action"]
            out["faded"] = True
            out["action"] = _flip_action(out["action"])
            out["label"] = LABEL[out["action"]]
            reason = f"FADE(عكس {out['orig_action']}→{out['action']}): " + reason
        if not flow_fresh:
            reason += " | no live footprint"
        out["reason"] = reason
        # Concrete on-chart trade LEVELS (entry/target/stop + nearest zones) so the
        # indicator can draw them as horizontal lines at the right price locations.
        out["levels"] = _signal_levels(mt5, symbol, price, out["action"], zones)
    except Exception as e:
        out["reason"] = f"err:{e}"
    return out


_PROJ_ENGINE = None   # lazy-loaded (analyse_structure, generate_projection)


def _build_projection(mt5, symbol: str) -> dict:
    """Structural FORECAST for the indicator to draw future candles + target ladder.
    Runs the fractal engine (BOS/CHoCH/sweeps → direction + laddered targets + stop)
    on M15. Returns a compact, JSON-safe dict. Never raises (returns {} on any issue)."""
    global _PROJ_ENGINE
    try:
        if _PROJ_ENGINE is None:
            from src.mt5_ai.fractal_structure_engine import analyse_structure
            from src.mt5_ai.market_projection_engine import generate_projection
            _PROJ_ENGINE = (analyse_structure, generate_projection)
        analyse_structure, generate_projection = _PROJ_ENGINE
        import pandas as pd
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 300)
        if r is None or len(r) < 40:
            return {}
        df = pd.DataFrame(r)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        fs = analyse_structure(df)
        pr = generate_projection(df, fs, symbol, "M15")
        return {
            "direction":  pr.get("direction", "SIDEWAYS"),
            "confidence": pr.get("confidence", 0.0),
            "entry":      pr.get("entry", 0.0),
            "stop_loss":  pr.get("stop_loss", 0.0),
            "targets":    pr.get("targets", []),       # [{price, r}, …] TP1..TP4
            "bias":       pr.get("bias", "neutral"),
            "quality":    pr.get("quality", "choppy"),
            "reason":     pr.get("reason", ""),
        }
    except Exception as e:
        return {"err": str(e)[:80]}


def write_signal(symbol: str, mt5) -> dict:
    sig = compute_signal(symbol, mt5)
    try:
        sig["projection"] = _build_projection(mt5, symbol)
    except Exception as e:
        sig["projection"] = {"err": str(e)[:80]}
    try:
        COMMON.mkdir(parents=True, exist_ok=True)
        (COMMON / f"signal_{symbol}.json").write_text(
            json.dumps(sig, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        sig["write_err"] = str(e)
    return sig


def run(symbols: list[str], loop: bool):
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed")
        return
    # resolve tf enum once
    try:
        _TF_MT5["15m"] = mt5.TIMEFRAME_M15
    except Exception:
        pass
    try:
        while True:
            for s in symbols:
                sig = write_signal(s, mt5)
                print(f"[signal] {s}: {sig['action']} {sig['confidence']:.0f}% "
                      f"({sig['dominant']}) zones={len(sig['zones'])} {sig.get('reason','')[:50]}")
            if not loop:
                break
            time.sleep(INTERVAL)
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write brain BUY/SELL signal for the chart indicator")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    args = ap.parse_args(argv)
    run(args.symbols, loop=args.loop and not args.once)


if __name__ == "__main__":
    main()

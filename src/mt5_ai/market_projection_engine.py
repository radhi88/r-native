"""
market_projection_engine.py
---------------------------
Market Projection Engine — probabilistic path forecasting.

Combines:
- FractalStructure (BOS, CHoCH, sweeps, protected levels)
- EMA direction
- ATR volatility
- Genome win rate
- Historical projection memory (learns which patterns work)

Output:
  direction:    "UP" | "DOWN" | "SIDEWAYS"
  confidence:   0.0 → 1.0
  path:         [{time, price}, …]  — expected next 6 steps
  target:       float
  target_zone:  {high, low}
  invalidation: float
  reason:       str
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from .fractal_structure_engine import FractalStructure, _safe

from .core.project_root import APPDATA_FRIDAY as _APPDATA_FRIDAY
_DATA = _APPDATA_FRIDAY
_MEM  = _DATA / "fractal_projection_memory.json"

_TF_SECS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400,
}


# ─────────────────────────────────────────────────────────────────────────────
#  Projection memory (self-improving)
# ─────────────────────────────────────────────────────────────────────────────

def _load_mem() -> dict:
    if not _MEM.exists():
        return {}
    try:
        return json.loads(_MEM.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_mem(mem: dict) -> None:
    try:
        _MEM.write_text(json.dumps(mem, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    except Exception:
        pass


def _mem_key(symbol: str, tf: str, fs: FractalStructure) -> str:
    parts = [symbol, tf, fs.structure_bias, fs.trend_quality]
    if fs.bos_recent:   parts.append("bos")
    if fs.choch_recent: parts.append("choch")
    if fs.sweep_recent: parts.append("sw")
    return "|".join(parts)


def memory_confidence(symbol: str, tf: str, fs: FractalStructure) -> float:
    mem = _load_mem()
    rec = mem.get(_mem_key(symbol, tf, fs), {})
    w, l = rec.get("wins", 0), rec.get("losses", 0)
    return round(w / (w + l), 3) if w + l >= 3 else 0.5


def record_projection_outcome(
    symbol: str, tf: str, fs: FractalStructure,
    projected_dir: str, actual_dir: str,
) -> None:
    mem = _load_mem()
    key = _mem_key(symbol, tf, fs)
    rec = mem.setdefault(key, {"wins": 0, "losses": 0})
    if projected_dir == actual_dir:
        rec["wins"] += 1
    else:
        rec["losses"] += 1
    if len(mem) > 500:
        oldest = sorted(mem.keys())[:100]
        for k in oldest:
            del mem[k]
    _save_mem(mem)


# ─────────────────────────────────────────────────────────────────────────────
#  Main projection function
# ─────────────────────────────────────────────────────────────────────────────

def generate_projection(
    df: pd.DataFrame,
    fs: FractalStructure,
    symbol: str = "",
    tf: str = "",
    ema_series: "pd.Series | None" = None,
    genome_win_rate: float = 0.5,
) -> dict[str, Any]:
    """Returns full projection dict — all values JSON-safe, no NaN."""
    null_result: dict[str, Any] = {
        "direction": "SIDEWAYS", "confidence": 0.0, "path": [],
        "target": 0.0, "target_zone": {"high": 0.0, "low": 0.0},
        "invalidation": 0.0, "reason": "insufficient_data",
        "bias": "neutral", "quality": "choppy",
        "bull_score": 0.0, "bear_score": 0.0,
    }
    if df is None or len(df) < 20:
        return null_result

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    c = df["close"]
    h = df["high"]; lo = df["low"]
    cur = float(c.iloc[-1])
    tr  = (h-lo).combine((h-c.shift()).abs(),max).combine((lo-c.shift()).abs(),max)
    atr = max(_safe(tr.ewm(span=14, adjust=False).mean().iloc[-1]), 1e-7)
    tf_sec  = _TF_SECS.get(tf.upper(), 3600)
    last_ts = int(df.index[-1].timestamp())

    bull = 0.0
    bear = 0.0
    why:  list[str] = []

    # 1. Structure bias
    if fs.structure_bias == "bullish":
        bull += 0.22 * fs.structure_strength
        why.append(f"bull_struct({fs.structure_strength:.2f})")
    elif fs.structure_bias == "bearish":
        bear += 0.22 * fs.structure_strength
        why.append(f"bear_struct({fs.structure_strength:.2f})")

    # 2. BOS
    if fs.bos_recent and fs.last_bos:
        if "bull" in fs.last_bos.kind: bull += 0.18; why.append("BOS_bull")
        else:                           bear += 0.18; why.append("BOS_bear")

    # 3. CHoCH (stronger signal — reversal)
    if fs.choch_recent and fs.last_choch:
        if "bull" in fs.last_choch.kind: bull += 0.25; why.append("CHoCH_bull")
        else:                             bear += 0.25; why.append("CHoCH_bear")

    # 4. Liquidity sweep (reversal after sweep)
    if fs.sweep_recent and fs.last_sweep:
        sw = fs.last_sweep
        if sw.kind == "bull_sweep" and sw.recovered:
            bull += 0.14 * sw.strength; why.append(f"bull_sweep({sw.strength:.2f})")
        elif sw.kind == "bear_sweep" and sw.recovered:
            bear += 0.14 * sw.strength; why.append(f"bear_sweep({sw.strength:.2f})")

    # 5. EMA slope
    if ema_series is not None and len(ema_series) >= 4:
        slope = _safe(ema_series.iloc[-1]) - _safe(ema_series.iloc[-4])
        if slope >  atr * 0.08: bull += 0.10; why.append("ema_up")
        elif slope < -atr * 0.08: bear += 0.10; why.append("ema_dn")

    # 6. Swing direction alignment
    if fs.swing_direction == "up":   bull += 0.08
    elif fs.swing_direction == "down": bear += 0.08

    # 7. Trend quality
    if fs.trend_quality == "impulsive":
        if bull > bear: bull *= 1.15
        else:           bear *= 1.15
        why.append("impulsive")
    elif fs.trend_quality == "choppy":
        bull *= 0.65; bear *= 0.65

    # 8. Memory (historical accuracy for this pattern)
    mem_conf = memory_confidence(symbol, tf, fs)
    adj = (mem_conf - 0.5) * 0.18
    if bull >= bear: bull = max(0, bull + adj)
    else:            bear = max(0, bear + adj)

    # 9. Genome win rate boost
    if genome_win_rate > 0.55:
        if bull >= bear: bull += 0.04
        else:            bear += 0.04

    # 10. Stop hunt dampening
    if fs.stop_hunt_probability > 0.55:
        bull *= (1 - fs.stop_hunt_probability * 0.25)
        bear *= (1 - fs.stop_hunt_probability * 0.25)
        why.append(f"sth({fs.stop_hunt_probability:.2f})")

    # ── Direction ──────────────────────────────────────────────────────────
    total = bull + bear
    if total < 0.05:
        direction = "SIDEWAYS"; confidence = 0.0
    elif bull > bear * 1.18:
        direction = "UP";   confidence = min(0.95, bull / (total + 1e-8))
    elif bear > bull * 1.18:
        direction = "DOWN"; confidence = min(0.95, bear / (total + 1e-8))
    else:
        direction = "SIDEWAYS"; confidence = min(0.48, total / 2)

    # ── Target ladder + invalidation ────────────────────────────────────────
    # `targets` = successive UNBROKEN fractal levels in the trade direction,
    # nearest-first (TP1, TP2, TP3 …) — exactly the laddered targets in a
    # TradingView projection. Each carries its R-multiple vs the SL.
    def _ladder(levels: list[float], up: bool, sl: float) -> list[dict]:
        # de-dupe levels within 0.3·ATR of each other, keep up to 4
        levels = sorted(set(round(p, 5) for p in levels), reverse=not up)
        out: list[dict] = []
        risk = max(abs(cur - sl), atr * 0.5)
        for p in levels:
            if out and abs(p - out[-1]["price"]) < atr * 0.3:
                continue
            r = round(abs(p - cur) / risk, 2)
            out.append({"price": round(float(p), 5), "r": r})
            if len(out) >= 4:
                break
        return out

    if direction == "UP":
        cands = [fh.price for fh in fs.fractal_highs if fh.price > cur]
        if fs.protected_high > cur: cands.append(fs.protected_high)
        inval  = round(fs.protected_low  if fs.protected_low  > 0
                       else cur - atr * 2, 5)
        targets = _ladder(cands, up=True, sl=inval)
        if not targets:
            targets = [{"price": round(cur + atr * 3, 5), "r": round(atr*3/max(abs(cur-inval),atr*0.5),2)}]
        target = targets[0]["price"]
    elif direction == "DOWN":
        cands = [fl.price for fl in fs.fractal_lows if fl.price < cur]
        if 0 < fs.protected_low < cur: cands.append(fs.protected_low)
        inval  = round(fs.protected_high if fs.protected_high > 0
                       else cur + atr * 2, 5)
        targets = _ladder(cands, up=False, sl=inval)
        if not targets:
            targets = [{"price": round(cur - atr * 3, 5), "r": round(atr*3/max(abs(cur-inval),atr*0.5),2)}]
        target = targets[0]["price"]
    else:
        target = round(cur, 5)
        inval  = round(cur + atr * 1.5, 5)
        targets = []

    target = round(float(target), 5)
    inval  = round(float(inval),  5)

    # ── Projection path (6 steps, exponential approach) ────────────────────
    path = [{"time": last_ts, "price": round(cur, 5)}]
    for i in range(1, 7):
        step_ts = last_ts + tf_sec * i * 2
        if direction == "SIDEWAYS":
            osc = atr * 0.25 * math.sin(i * 1.3)
            p   = round(cur + osc, 5)
        else:
            prog = 1.0 - math.exp(-i * 0.42)
            p    = round(cur + (target - cur) * prog, 5)
        path.append({"time": step_ts, "price": p})

    # Target zone band
    band = atr * 0.6 * (1 + (1 - confidence))
    tzone = {"high": round(target + band, 5), "low": round(target - band, 5)}

    return {
        "direction":    direction,
        "confidence":   round(confidence, 3),
        "path":         path,
        "entry":        round(cur, 5),
        "stop_loss":    inval,
        "target":       target,
        "targets":      targets,          # [{price, r}, …]  TP1, TP2, TP3 (laddered)
        "target_zone":  tzone,
        "invalidation": inval,
        "reason":       " | ".join(why[:5]),
        "bias":         fs.structure_bias,
        "quality":      fs.trend_quality,
        "bull_score":   round(bull, 3),
        "bear_score":   round(bear, 3),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  FRACTAL ANALOG forecast — self-similar projection (the pattern repeats)
# ─────────────────────────────────────────────────────────────────────────────

def fractal_analog_forecast(
    df: "pd.DataFrame",
    window: int = 30,
    horizon: int = 14,
    min_history: int = 400,
    min_corr: float = 0.55,
    top_k: int = 5,
) -> dict[str, Any]:
    """Project the future by REPLAYING the most similar PAST fractal pattern(s).

    HONESTY NOTE (validated OOS, walk-forward, no-lookahead — see fractal_research_log.md):
      This forecast does NOT predict DIRECTION. Across XAU/EUR/GBP on M1/M5/M15/H1/H4/D1
      and every window/horizon/metric/ensemble tried, OOS directional hit-rate is a
      coin-flip (~50-53%, best robust case XAU H1 ~53.5%, below any usable bar) and
      projected-path correlation to the actual path is ~0. What the analog DOES carry is
      a modest, genuine VOLATILITY/RANGE signal: the projected range correlates with the
      realised range (XAU M15 ~0.45-0.50; high-pred vs low-pred realised range ~2:1),
      though much of that is already captured by recent ATR. Treat the returned candles
      as a *range/context* sketch, NOT a directional prediction. `direction_predictive`
      is therefore always False.

    Method:
      1. take the last `window` bars (the query shape),
      2. slide over earlier history, score each candidate window by Pearson correlation
         of its z-normalised closes vs the query (shape self-similarity),
      3. ENSEMBLE the `top_k` best non-overlapping matches (averaging their continuations
         reduces overfit to a single fluke match and sharpens the range estimate),
      4. replay the averaged bar-to-bar moves, anchored at current price and SCALED to
         current volatility (ATR ratio).

    Returns {candles:[{open,high,low,close}], analog_corr, analog_index, scale,
             ensemble_k, projected_range, direction_predictive}.
    No `time` — the caller stamps future timestamps at its own TF spacing.
    """
    import numpy as np
    null = {"candles": [], "reason": "insufficient_history", "analog_corr": 0.0,
            "direction_predictive": False}
    if df is None or len(df) < max(min_history, window + horizon + 50):
        return null
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    close = d["close"].to_numpy(dtype=float)
    high  = d["high"].to_numpy(dtype=float)
    low   = d["low"].to_numpy(dtype=float)
    op    = d["open"].to_numpy(dtype=float)
    n = len(close)

    q  = close[n - window:n]
    qn = (q - q.mean()) / (q.std() + 1e-9)
    qatr = float(np.mean(high[n - window:n] - low[n - window:n])) + 1e-9

    # candidate windows end at i (use close[i-window:i]); continuation close[i:i+horizon]
    # must end strictly before the current bar -> i+horizon <= n  (no lookahead/overlap).
    last_allowed = n - horizon
    if last_allowed <= window + 1:
        return null
    idxs = np.arange(window, last_allowed)
    scores = np.empty(len(idxs), dtype=float)
    for p, i in enumerate(idxs):
        seg = close[i - window:i]
        sn = (seg - seg.mean()) / (seg.std() + 1e-9)
        scores[p] = float(np.dot(qn, sn) / window)        # Pearson (both z-normalised)

    order = np.argsort(scores)[::-1]
    chosen: list[int] = []
    for p in order:
        i = int(idxs[p])
        if any(abs(i - c) < window for c in chosen):
            continue
        chosen.append(i)
        if len(chosen) >= max(1, top_k):
            break
    if not chosen:
        return null
    best_i = chosen[0]
    best_score = float(scores[order[0]])
    if best_score < min_corr:
        return {"candles": [], "reason": f"no_analog(best={round(best_score,2)})",
                "analog_corr": round(best_score, 3), "direction_predictive": False}

    cur = float(close[-1])
    # ensemble the continuations: average each match's cumulative O/H/L/C move (vol-scaled)
    horizon_eff = min(horizon, n - best_i)
    acc_o = np.zeros(horizon); acc_c = np.zeros(horizon)
    acc_hi = np.zeros(horizon); acc_lo = np.zeros(horizon)
    used = 0
    for i in chosen:
        if i + horizon > n:
            continue
        aatr = float(np.mean(high[i - window:i] - low[i - window:i])) + 1e-9
        sc = qatr / aatr
        base = close[i - 1]
        acc_o  += (op[i:i + horizon]    - base) * sc
        acc_c  += (close[i:i + horizon] - base) * sc
        acc_hi += (high[i:i + horizon]  - base) * sc
        acc_lo += (low[i:i + horizon]   - base) * sc
        used += 1
    if used == 0:
        return null
    acc_o /= used; acc_c /= used; acc_hi /= used; acc_lo /= used

    out: list[dict] = []
    for k in range(horizon):
        o  = cur + float(acc_o[k]);  c = cur + float(acc_c[k])
        hi = cur + float(acc_hi[k]); lo = cur + float(acc_lo[k])
        hi = max(hi, o, c); lo = min(lo, o, c)
        out.append({"open": round(o, 5), "high": round(hi, 5),
                    "low": round(lo, 5), "close": round(c, 5)})

    proj_range = round(float(np.max([cc["high"] for cc in out]) -
                             np.min([cc["low"] for cc in out])), 5) if out else 0.0
    aatr0 = float(np.mean(high[best_i - window:best_i] - low[best_i - window:best_i])) + 1e-9
    return {"candles": out, "analog_corr": round(best_score, 3),
            "analog_index": int(best_i), "scale": round(float(qatr / aatr0), 3),
            "ensemble_k": used, "projected_range": proj_range,
            "direction_predictive": False,
            "window": window, "horizon": len(out)}

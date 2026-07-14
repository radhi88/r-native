"""
fractal_structure_engine.py
---------------------------
Fractal Intelligence Engine — detects market structure, BOS/CHoCH,
liquidity sweeps, protected levels, and structural bias.

Fully vectorized, no NaN output, works with lowercase column names.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

LEFT_BARS    = 2
RIGHT_BARS   = 2
MAX_FRACTALS = 20


# ─────────────────────────────────────────────────────────────────────────────
#  Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FractalPoint:
    time:      int
    price:     float
    kind:      str       # "high" | "low"
    protected: bool = False


@dataclass
class StructureEvent:
    time:       int
    price:      float
    kind:       str      # "BOS_bull" | "BOS_bear" | "CHoCH_bull" | "CHoCH_bear"
    from_price: float = 0.0


@dataclass
class LiquiditySweep:
    time:      int
    price:     float
    kind:      str      # "bull_sweep" | "bear_sweep"
    strength:  float
    recovered: bool


@dataclass
class FractalStructure:
    # Fractal arrays (serialisable via to_dict())
    fractal_highs:  list[FractalPoint] = field(default_factory=list)
    fractal_lows:   list[FractalPoint] = field(default_factory=list)

    protected_high:      float = 0.0
    protected_low:       float = 0.0
    protected_high_time: int   = 0
    protected_low_time:  int   = 0

    structure_events: list[StructureEvent]  = field(default_factory=list)
    last_bos:         StructureEvent | None = None
    last_choch:       StructureEvent | None = None

    sweeps:     list[LiquiditySweep] = field(default_factory=list)
    last_sweep: LiquiditySweep | None = None

    structure_bias:     str   = "neutral"   # bullish | bearish | neutral
    structure_strength: float = 0.0
    trend_quality:      str   = "choppy"    # impulsive | corrective | choppy
    swing_direction:    str   = "neutral"   # up | down | neutral

    liquidity_density:     float = 0.0
    fractal_density:       float = 0.0
    stop_hunt_probability: float = 0.0
    fake_break_probability:float = 0.0

    dist_protected_high: float = 0.0
    dist_protected_low:  float = 0.0

    bos_recent:    bool  = False
    choch_recent:  bool  = False
    sweep_recent:  bool  = False
    sweep_strength:float = 0.0

    def to_dict(self) -> dict:
        def _ev(e):
            return {"time": e.time, "price": e.price,
                    "kind": e.kind, "from_price": e.from_price}
        def _fp(f):
            return {"time": f.time, "price": f.price,
                    "kind": f.kind, "protected": f.protected}
        def _sw(s):
            return {"time": s.time, "price": s.price,
                    "kind": s.kind, "strength": s.strength,
                    "recovered": s.recovered}
        return {
            "fractal_highs":  [_fp(f) for f in self.fractal_highs],
            "fractal_lows":   [_fp(f) for f in self.fractal_lows],
            "protected_high":       self.protected_high,
            "protected_low":        self.protected_low,
            "protected_high_time":  self.protected_high_time,
            "protected_low_time":   self.protected_low_time,
            "structure_events":     [_ev(e) for e in self.structure_events],
            "last_bos":    _ev(self.last_bos)   if self.last_bos   else None,
            "last_choch":  _ev(self.last_choch) if self.last_choch else None,
            "sweeps":      [_sw(s) for s in self.sweeps],
            "last_sweep":  _sw(self.last_sweep) if self.last_sweep else None,
            "structure_bias":      self.structure_bias,
            "structure_strength":  self.structure_strength,
            "trend_quality":       self.trend_quality,
            "swing_direction":     self.swing_direction,
            "liquidity_density":   self.liquidity_density,
            "fractal_density":     self.fractal_density,
            "stop_hunt_probability":    self.stop_hunt_probability,
            "fake_break_probability":   self.fake_break_probability,
            "dist_protected_high": self.dist_protected_high,
            "dist_protected_low":  self.dist_protected_low,
            "bos_recent":   self.bos_recent,
            "choch_recent": self.choch_recent,
            "sweep_recent": self.sweep_recent,
            "sweep_strength":      self.sweep_strength,
        }


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe(v: Any) -> float:
    try:
        f = float(v)
        return 0.0 if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return 0.0


def _norm_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    if "tick_volume" in df.columns and "volume" not in df.columns:
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
    return df


def _atr_val(df: pd.DataFrame, period: int = 14) -> float:
    try:
        h, l, c = df["high"], df["low"], df["close"]
        tr = (h-l).combine((h-c.shift()).abs(), max).combine((l-c.shift()).abs(), max)
        return max(_safe(tr.ewm(span=period, adjust=False).mean().iloc[-1]), 1e-7)
    except Exception:
        return 1e-7


# ─────────────────────────────────────────────────────────────────────────────
#  Fractal detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_fractals(
    df: pd.DataFrame,
    left:  int = LEFT_BARS,
    right: int = RIGHT_BARS,
) -> tuple[list[FractalPoint], list[FractalPoint]]:
    h = df["high"].values
    l = df["low"].values
    t = [int(x.timestamp()) for x in df.index]
    n = len(df)
    highs: list[FractalPoint] = []
    lows:  list[FractalPoint] = []

    for i in range(left, n - right):
        hi = float(h[i])
        lo = float(l[i])
        if all(hi >= float(h[i-j]) for j in range(1, left+1)) and \
           all(hi >= float(h[i+j]) for j in range(1, right+1)):
            highs.append(FractalPoint(time=t[i], price=round(hi, 5), kind="high"))
        if all(lo <= float(l[i-j]) for j in range(1, left+1)) and \
           all(lo <= float(l[i+j]) for j in range(1, right+1)):
            lows.append(FractalPoint(time=t[i], price=round(lo, 5), kind="low"))

    return highs[-MAX_FRACTALS:], lows[-MAX_FRACTALS:]


# ─────────────────────────────────────────────────────────────────────────────
#  Market structure detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_structure(
    df: pd.DataFrame,
    frac_h: list[FractalPoint],
    frac_l: list[FractalPoint],
    atr: float,
) -> tuple[list[StructureEvent], str, float, str]:
    """Returns (events, bias, strength, trend_quality)."""
    if not frac_h or not frac_l:
        return [], "neutral", 0.0, "choppy"

    closes = df["close"].values
    times  = [int(x.timestamp()) for x in df.index]
    n = len(closes)

    ph_sorted = sorted(frac_h, key=lambda x: x.time)
    pl_sorted = sorted(frac_l, key=lambda x: x.time)

    events:     list[StructureEvent] = []
    bias        = "neutral"
    last_dir    = None
    consec_same = 0
    alternating = 0

    for i in range(1, n):
        c  = float(closes[i])
        ts = times[i]

        prev_h = [p for p in ph_sorted if p.time < ts]
        prev_l = [p for p in pl_sorted if p.time < ts]
        if not prev_h or not prev_l:
            continue

        last_ph = prev_h[-1].price
        last_pl = prev_l[-1].price

        if c > last_ph + atr * 0.05:
            kind = "BOS_bull" if bias in ("neutral", "bullish") else "CHoCH_bull"
            events.append(StructureEvent(time=ts, price=round(last_ph, 5),
                                         kind=kind, from_price=round(c, 5)))
            if last_dir == "bull": consec_same += 1
            elif last_dir == "bear": alternating += 1; consec_same = 0
            last_dir = "bull"
            bias = "bullish"

        elif c < last_pl - atr * 0.05:
            kind = "BOS_bear" if bias in ("neutral", "bearish") else "CHoCH_bear"
            events.append(StructureEvent(time=ts, price=round(last_pl, 5),
                                         kind=kind, from_price=round(c, 5)))
            if last_dir == "bear": consec_same += 1
            elif last_dir == "bull": alternating += 1; consec_same = 0
            last_dir = "bear"
            bias = "bearish"

    events = events[-12:]

    # Structure strength
    if events:
        e5   = events[-5:]
        dom  = max(sum(1 for e in e5 if "bull" in e.kind),
                   sum(1 for e in e5 if "bear" in e.kind))
        strength = min(1.0, dom / max(len(e5), 1))
    else:
        strength = 0.0

    # Trend quality
    if consec_same >= 2:
        quality = "impulsive"
    elif alternating >= 2:
        quality = "corrective"
    else:
        quality = "choppy"

    return events, bias, round(strength, 3), quality


# ─────────────────────────────────────────────────────────────────────────────
#  Liquidity sweep detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_sweeps(
    df: pd.DataFrame,
    frac_h: list[FractalPoint],
    frac_l: list[FractalPoint],
    atr: float,
) -> list[LiquiditySweep]:
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    t = [int(x.timestamp()) for x in df.index]
    n = len(df)
    sweeps: list[LiquiditySweep] = []

    for i in range(2, n):
        hi = float(h[i]); lo = float(l[i]); cl = float(c[i])
        ts = t[i]

        for fp in frac_h:
            if fp.time >= ts:
                continue
            if hi > fp.price + atr * 0.05 and cl < fp.price:
                excess = (hi - fp.price) / (atr + 1e-10)
                sweeps.append(LiquiditySweep(
                    time=ts, price=round(fp.price, 5), kind="bear_sweep",
                    strength=round(min(1.0, excess * 2), 3), recovered=True))

        for fp in frac_l:
            if fp.time >= ts:
                continue
            if lo < fp.price - atr * 0.05 and cl > fp.price:
                excess = (fp.price - lo) / (atr + 1e-10)
                sweeps.append(LiquiditySweep(
                    time=ts, price=round(fp.price, 5), kind="bull_sweep",
                    strength=round(min(1.0, excess * 2), 3), recovered=True))

    # Deduplicate (same timestamp, keep strongest)
    seen: dict[int, LiquiditySweep] = {}
    for s in sweeps:
        if s.time not in seen or s.strength > seen[s.time].strength:
            seen[s.time] = s
    return sorted(seen.values(), key=lambda x: x.time)[-12:]


# ─────────────────────────────────────────────────────────────────────────────
#  Protected levels
# ─────────────────────────────────────────────────────────────────────────────

def _find_protected(
    frac_h: list[FractalPoint],
    frac_l: list[FractalPoint],
    events: list[StructureEvent],
    current_price: float,
) -> tuple[float, int, float, int]:
    broken_h = {round(e.price, 5) for e in events if "bull" in e.kind}
    broken_l = {round(e.price, 5) for e in events if "bear" in e.kind}

    p_high, p_high_t = 0.0, 0
    for fh in reversed(frac_h):
        if round(fh.price, 5) not in broken_h and fh.price > current_price:
            p_high = fh.price; p_high_t = fh.time
            break

    p_low, p_low_t = 0.0, 0
    for fl in reversed(frac_l):
        if round(fl.price, 5) not in broken_l and fl.price < current_price:
            p_low = fl.price; p_low_t = fl.time
            break

    return p_high, p_high_t, p_low, p_low_t


# ─────────────────────────────────────────────────────────────────────────────
#  Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def analyse_structure(
    df: pd.DataFrame,
    left: int = LEFT_BARS,
    right: int = RIGHT_BARS,
    recent_bars: int = 25,
) -> FractalStructure:
    """Full structural analysis. Returns FractalStructure with all fields."""
    fs = FractalStructure()
    if df is None or len(df) < (left + right + 15):
        return fs

    df = _norm_df(df)
    atr = _atr_val(df)
    cur = float(df["close"].iloc[-1])

    # 1. Fractals
    fh, fl = detect_fractals(df, left, right)
    fs.fractal_highs = fh
    fs.fractal_lows  = fl

    # 2. Structure
    events, bias, strength, quality = detect_structure(df, fh, fl, atr)
    fs.structure_events  = events
    fs.structure_bias    = bias
    fs.structure_strength= strength
    fs.trend_quality     = quality

    # 3. Protected levels
    ph, ph_t, pl, pl_t = _find_protected(fh, fl, events, cur)
    fs.protected_high      = ph
    fs.protected_low       = pl
    fs.protected_high_time = ph_t
    fs.protected_low_time  = pl_t

    # 4. Sweeps
    sweeps = detect_sweeps(df, fh, fl, atr)
    fs.sweeps = sweeps

    # 5. Recent flags
    cutoff_ts = int(df.index[max(0, len(df) - recent_bars)].timestamp())
    re = [e for e in events if e.time >= cutoff_ts]
    rs = [s for s in sweeps if s.time >= cutoff_ts]

    fs.bos_recent   = any("BOS"   in e.kind for e in re)
    fs.choch_recent = any("CHoCH" in e.kind for e in re)
    fs.sweep_recent = len(rs) > 0
    fs.sweep_strength = max((s.strength for s in rs), default=0.0)

    fs.last_bos   = next((e for e in reversed(events) if "BOS"   in e.kind), None)
    fs.last_choch = next((e for e in reversed(events) if "CHoCH" in e.kind), None)
    fs.last_sweep = sweeps[-1] if sweeps else None

    # 6. Swing direction
    if len(events) >= 2:
        d = ["up" if "bull" in e.kind else "down" for e in events[-2:]]
        fs.swing_direction = d[0] if d[0] == d[1] else "neutral"

    # 7. Densities
    all_lvl = [f.price for f in fh + fl]
    nearby = sum(1 for p in all_lvl if abs(p - cur) < atr * 2)
    fs.liquidity_density = min(1.0, nearby / 6)
    fs.fractal_density   = min(1.0, (len(fh)+len(fl)) / max(len(df)//4, 1))

    # 8. Distances
    fs.dist_protected_high = round(ph - cur, 5) if ph > 0 else 0.0
    fs.dist_protected_low  = round(cur - pl, 5) if pl > 0 else 0.0

    # 9. Stop hunt probability
    ph_r = abs(cur - ph) / (atr * 3 + 1e-10) if ph > 0 else 1.0
    pl_r = abs(cur - pl) / (atr * 3 + 1e-10) if pl > 0 else 1.0
    near = max(0.0, 1.0 - min(ph_r, pl_r))
    fs.stop_hunt_probability = min(1.0,
        near * 0.4 + fs.sweep_strength * 0.3 +
        (0.3 if quality == "choppy" else 0.0))
    fs.fake_break_probability = round(fs.stop_hunt_probability * 0.8, 3)
    fs.stop_hunt_probability  = round(fs.stop_hunt_probability, 3)

    return fs


def to_features(fs: FractalStructure, atr: float = 1e-4) -> dict[str, float]:
    """Flat normalised feature dict — all floats, no NaN."""
    bm = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}
    dm = {"up": 1.0, "down": -1.0, "neutral": 0.0}
    qm = {"impulsive": 1.0, "corrective": 0.5, "choppy": 0.0}
    atr = max(float(atr), 1e-7)
    return {
        "structure_bias":         bm.get(fs.structure_bias, 0.0),
        "structure_strength":     _safe(fs.structure_strength),
        "trend_quality":          qm.get(fs.trend_quality, 0.0),
        "swing_direction":        dm.get(fs.swing_direction, 0.0),
        "dist_protected_high":    min(1.0, _safe(fs.dist_protected_high) / (atr * 50)),
        "dist_protected_low":     min(1.0, _safe(fs.dist_protected_low)  / (atr * 50)),
        "bos_recent":             1.0 if fs.bos_recent   else 0.0,
        "choch_recent":           1.0 if fs.choch_recent else 0.0,
        "sweep_recent":           1.0 if fs.sweep_recent else 0.0,
        "sweep_strength":         _safe(fs.sweep_strength),
        "liquidity_density":      _safe(fs.liquidity_density),
        "fractal_density":        _safe(fs.fractal_density),
        "stop_hunt_probability":  _safe(fs.stop_hunt_probability),
        "fake_break_probability": _safe(fs.fake_break_probability),
        "n_fractal_highs":        min(1.0, len(fs.fractal_highs) / 10),
        "n_fractal_lows":         min(1.0, len(fs.fractal_lows)  / 10),
        "n_structure_events":     min(1.0, len(fs.structure_events) / 6),
        "n_sweeps":               min(1.0, len(fs.sweeps) / 5),
    }

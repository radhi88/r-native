"""smc_engine.py — Smart Money Concepts pattern detector.

Pure-Python detectors for the SMC primitives used across the system:

    Pivots (fractals)   → atomic swing detection with confirmation discipline
    BOS                 → close past last confirmed swing in trend direction
    CHoCH               → first BOS opposite to prevailing trend
    Liquidity Sweep     → wick past a swing extreme + close back inside
    IDM (Inducement)    → minor counter-trend pivot swept before impulse
    Order Block         → last opposite-color candle before impulsive BOS
    FVG                 → 3-candle imbalance gap
    OF (Order Flow)     → retracement leg between two structural points

Two entry points:

    compute_smc_snapshot(symbol, tf_name, bars_back=200) → live (reads MT5)
    compute_offline(bars)                                → backtest/sim path

Both return the same dict shape consumed by genome_signal SMC evaluators
(see docs/smc/03_GENOME_INTEGRATION.md §2a).

Lookahead discipline: detectors only emit events whose source pivots have
been right-confirmed by `fractal_right` bars. Backtests are deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


DEFAULT_CFG: dict = {
    "fractal_left":          2,
    "fractal_right":         2,      # fractal-5 default
    "atr_period":           14,
    "min_penetration_atr":  0.05,
    "max_penetration_atr":  1.5,
    "max_close_back":        1,
    "eqh_tolerance_atr":    0.10,
    "sweep_to_choch_window": 10,
    "impulse_atr_mult":     1.5,
    "impulse_window":        5,
    "ob_body_ratio":        0.0,
    "ob_mitigation":        "close_through",
    "fvg_wicks":            True,
    "fvg_fill":             "50pct",
    # Snapshot shaping
    "snapshot_recent_bars":  80,    # only emit events whose ts_end is within this window
    "max_fvg_per_side":      5,     # cap list lengths
    "max_liq_pools_per_side": 6,
    "ob_freshness_bars":    80,
    "bos_age_max_bars":     60,
    "choch_age_max_bars":   30,
}


# ─── Event container ─────────────────────────────────────────────
@dataclass
class Event:
    kind:        str                 # "BOS" | "CHoCH" | "SWEEP" | "IDM" | "OB" | "FVG" | "OF"
    side:        str                 # "bull" | "bear"
    ts_start:    int
    ts_end:      int
    level_high:  float
    level_low:   float
    idx_start:   int = 0
    idx_end:     int = 0
    status:      str = "fresh"       # "fresh" | "mitigated"
    strength:    float = 0.0         # 0..1, detector-defined
    extras:      dict = field(default_factory=dict)


# ─── Bars wrapper (uniform access to dict / numpy structured) ────
class Bars:
    """Uniform view over either a list of dicts or a numpy structured array
    of OHLC bars. Supports `bars[i].open`, `bars[i].time`, etc."""

    def __init__(self, raw):
        self.raw = raw
        # Detect whether raw is numpy structured array (has dtype.names) or list
        self._is_struct = hasattr(raw, "dtype") and raw.dtype.names is not None
        self.n = len(raw)

    def __len__(self): return self.n

    def __getitem__(self, i: int):
        return _BarView(self.raw, i, self._is_struct)


class _BarView:
    __slots__ = ("_raw", "_i", "_s")
    def __init__(self, raw, i, is_struct):
        self._raw = raw; self._i = i; self._s = is_struct
    def _g(self, name):
        if self._s:
            return float(self._raw[name][self._i])
        item = self._raw[self._i]
        return float(item.get(name, item.get(name.lower(), 0)))
    @property
    def time(self):   return int(self._raw["time"][self._i]) if self._s else int(self._raw[self._i].get("time", 0))
    @property
    def open(self):   return self._g("open")
    @property
    def high(self):   return self._g("high")
    @property
    def low(self):    return self._g("low")
    @property
    def close(self):  return self._g("close")


# ─── Foundation: ATR & pivots ────────────────────────────────────
def _atr(bars: Bars, period: int) -> list[float]:
    """Rolling ATR — uses Wilder's smoothing for >= period bars, simple TR before."""
    n = len(bars)
    trs = [0.0] * n
    for i in range(n):
        h, l = bars[i].high, bars[i].low
        if i == 0:
            trs[i] = h - l
        else:
            pc = bars[i-1].close
            trs[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = [0.0] * n
    if n == 0: return atr
    # Simple average for first `period` bars, then Wilder smoothing
    if n <= period:
        s = sum(trs) / n if n else 0.0
        for i in range(n): atr[i] = s
        return atr
    s = sum(trs[:period]) / period
    for i in range(period):    atr[i] = s
    for i in range(period, n):
        s = (s * (period - 1) + trs[i]) / period
        atr[i] = s
    return atr


def detect_pivots(bars: Bars, cfg: dict) -> list[dict]:
    L = cfg.get("fractal_left",  DEFAULT_CFG["fractal_left"])
    R = cfg.get("fractal_right", DEFAULT_CFG["fractal_right"])
    n = len(bars)
    pivots = []
    if n < L + R + 1: return pivots
    for i in range(L, n - R):
        h_i, l_i = bars[i].high, bars[i].low
        is_high = True; is_low = True
        for j in range(i - L, i + R + 1):
            if j == i: continue
            if bars[j].high >= h_i: is_high = False
            if bars[j].low  <= l_i: is_low  = False
            if not is_high and not is_low: break
        if is_high:
            pivots.append({"idx": i, "ts": bars[i].time, "price": h_i,
                           "kind": "H", "state": "confirmed",
                           "confirmed_at_idx": i + R})
        if is_low:
            pivots.append({"idx": i, "ts": bars[i].time, "price": l_i,
                           "kind": "L", "state": "confirmed",
                           "confirmed_at_idx": i + R})
    return pivots


# ─── Detectors ───────────────────────────────────────────────────
def detect_bos(bars: Bars, cfg: dict, pivots: Optional[list] = None) -> list[Event]:
    pivots = pivots if pivots is not None else detect_pivots(bars, cfg)
    events: list[Event] = []
    last_H = last_L = None
    # Index pivots by confirmation idx for O(n) sweep
    confirm_at: dict[int, list] = {}
    for p in pivots:
        confirm_at.setdefault(p["confirmed_at_idx"], []).append(p)
    n = len(bars)
    for i in range(n):
        for p in confirm_at.get(i, ()):
            if p["kind"] == "H": last_H = p
            else:                last_L = p
        bar = bars[i]
        if last_H is not None and bar.close > last_H["price"]:
            events.append(Event(kind="BOS", side="bull",
                ts_start=last_H["ts"], ts_end=bar.time,
                level_high=last_H["price"], level_low=last_H["price"],
                idx_start=last_H["idx"], idx_end=i, status="fresh"))
            last_H = None
        if last_L is not None and bar.close < last_L["price"]:
            events.append(Event(kind="BOS", side="bear",
                ts_start=last_L["ts"], ts_end=bar.time,
                level_high=last_L["price"], level_low=last_L["price"],
                idx_start=last_L["idx"], idx_end=i, status="fresh"))
            last_L = None
    return events


def detect_choch(bars: Bars, cfg: dict, bos_events: Optional[list] = None) -> list[Event]:
    bos = bos_events if bos_events is not None else detect_bos(bars, cfg)
    events = []
    trend = None
    for b in bos:
        if trend is None:
            trend = "UP" if b.side == "bull" else "DOWN"
            continue
        if (trend == "UP" and b.side == "bear") or (trend == "DOWN" and b.side == "bull"):
            events.append(Event(kind="CHoCH", side=b.side,
                ts_start=b.ts_start, ts_end=b.ts_end,
                level_high=b.level_high, level_low=b.level_low,
                idx_start=b.idx_start, idx_end=b.idx_end,
                status="fresh"))
            trend = "DOWN" if b.side == "bear" else "UP"
    return events


def detect_sweep(bars: Bars, cfg: dict,
                 pivots: Optional[list] = None,
                 atr: Optional[list] = None) -> list[Event]:
    pivots = pivots if pivots is not None else detect_pivots(bars, cfg)
    atr    = atr    if atr    is not None else _atr(bars, cfg.get("atr_period", 14))
    min_p  = cfg.get("min_penetration_atr", DEFAULT_CFG["min_penetration_atr"])
    max_p  = cfg.get("max_penetration_atr", DEFAULT_CFG["max_penetration_atr"])
    cb_max = cfg.get("max_close_back",      DEFAULT_CFG["max_close_back"])
    n = len(bars)
    events = []
    for p in pivots:
        if p["state"] != "confirmed": continue
        for j in range(p["confirmed_at_idx"] + 1, n):
            a = atr[j] or 0.0
            if a == 0: continue
            if p["kind"] == "H":
                pen = bars[j].high - p["price"]
                if pen < min_p * a or pen > max_p * a: continue
                # close back inside within cb_max bars
                back_ok = False
                for k in range(j, min(j + cb_max + 1, n)):
                    if bars[k].close < p["price"]:
                        back_ok = True; break
                if back_ok:
                    events.append(Event(kind="SWEEP", side="bear",
                        ts_start=p["ts"], ts_end=bars[j].time,
                        level_high=bars[j].high, level_low=p["price"],
                        idx_start=p["idx"], idx_end=j, status="fresh",
                        strength=min(1.0, pen / (a or 1e-9))))
                    break
            else:
                pen = p["price"] - bars[j].low
                if pen < min_p * a or pen > max_p * a: continue
                back_ok = False
                for k in range(j, min(j + cb_max + 1, n)):
                    if bars[k].close > p["price"]:
                        back_ok = True; break
                if back_ok:
                    events.append(Event(kind="SWEEP", side="bull",
                        ts_start=p["ts"], ts_end=bars[j].time,
                        level_high=p["price"], level_low=bars[j].low,
                        idx_start=p["idx"], idx_end=j, status="fresh",
                        strength=min(1.0, pen / (a or 1e-9))))
                    break
    return events


def detect_idm(bars: Bars, cfg: dict,
               pivots: Optional[list] = None,
               bos_events: Optional[list] = None) -> list[Event]:
    pivots = [p for p in (pivots if pivots is not None else detect_pivots(bars, cfg))
              if p["state"] == "confirmed"]
    bos = bos_events if bos_events is not None else detect_bos(bars, cfg)
    events = []
    for b in bos:
        if b.side == "bull":
            i_break = b.idx_end
            highs_before = [p for p in pivots if p["kind"] == "H" and p["idx"] < i_break]
            if len(highs_before) < 2: continue
            broken_H = highs_before[-1]
            prior_H  = highs_before[-2]
            candidates = [p for p in pivots if p["kind"] == "L"
                          and prior_H["idx"] < p["idx"] < broken_H["idx"]]
            if not candidates: continue
            idm = min(candidates, key=lambda p: p["price"])
            swept = any(bars[k].low < idm["price"]
                        for k in range(broken_H["idx"], i_break + 1))
            if swept:
                events.append(Event(kind="IDM", side="bull",
                    ts_start=idm["ts"], ts_end=b.ts_end,
                    level_high=idm["price"], level_low=idm["price"],
                    idx_start=idm["idx"], idx_end=b.idx_end, status="fresh"))
        else:  # bear: mirror
            i_break = b.idx_end
            lows_before = [p for p in pivots if p["kind"] == "L" and p["idx"] < i_break]
            if len(lows_before) < 2: continue
            broken_L = lows_before[-1]
            prior_L  = lows_before[-2]
            candidates = [p for p in pivots if p["kind"] == "H"
                          and prior_L["idx"] < p["idx"] < broken_L["idx"]]
            if not candidates: continue
            idm = max(candidates, key=lambda p: p["price"])
            swept = any(bars[k].high > idm["price"]
                        for k in range(broken_L["idx"], i_break + 1))
            if swept:
                events.append(Event(kind="IDM", side="bear",
                    ts_start=idm["ts"], ts_end=b.ts_end,
                    level_high=idm["price"], level_low=idm["price"],
                    idx_start=idm["idx"], idx_end=b.idx_end, status="fresh"))
    return events


def detect_ob(bars: Bars, cfg: dict,
              bos_events: Optional[list] = None,
              atr: Optional[list] = None) -> list[Event]:
    bos = bos_events if bos_events is not None else detect_bos(bars, cfg)
    atr = atr if atr is not None else _atr(bars, cfg.get("atr_period", 14))
    impulse_atr   = cfg.get("impulse_atr_mult", DEFAULT_CFG["impulse_atr_mult"])
    impulse_win   = cfg.get("impulse_window",   DEFAULT_CFG["impulse_window"])
    body_min      = cfg.get("ob_body_ratio",    DEFAULT_CFG["ob_body_ratio"])
    events = []
    for b in bos:
        i_bos = b.idx_end
        a = atr[i_bos] if atr[i_bos] > 0 else (atr[i_bos - 1] if i_bos > 0 else 0)
        if a == 0: continue
        # Walk back to find where the impulse started
        impulse_start = i_bos
        cum = 0.0
        for k in range(i_bos, max(i_bos - impulse_win, 0) - 1, -1):
            step = (bars[k].close - bars[k].open) * (1 if b.side == "bull" else -1)
            cum += step
            if cum >= impulse_atr * a:
                impulse_start = k; break
        else:
            continue
        # Last opposite-color candle strictly before impulse_start
        want_bear = (b.side == "bull")
        for k in range(impulse_start - 1, -1, -1):
            is_bear = bars[k].close < bars[k].open
            body = abs(bars[k].close - bars[k].open)
            rng  = bars[k].high - bars[k].low
            if is_bear == want_bear and rng > 0 and (body / rng) >= body_min:
                events.append(Event(kind="OB", side=b.side,
                    ts_start=bars[k].time, ts_end=b.ts_end,
                    level_high=bars[k].high, level_low=bars[k].low,
                    idx_start=k, idx_end=b.idx_end, status="fresh",
                    strength=min(1.0, cum / (a * 3.0))))
                break
    return events


def detect_fvg(bars: Bars, cfg: dict) -> list[Event]:
    use_wicks = cfg.get("fvg_wicks", DEFAULT_CFG["fvg_wicks"])
    events = []
    n = len(bars)
    for i in range(2, n):
        c1, c3 = bars[i - 2], bars[i]
        if use_wicks:
            hi1, lo1 = c1.high, c1.low
            hi3, lo3 = c3.high, c3.low
        else:
            hi1, lo1 = max(c1.open, c1.close), min(c1.open, c1.close)
            hi3, lo3 = max(c3.open, c3.close), min(c3.open, c3.close)
        if hi1 < lo3:
            events.append(Event(kind="FVG", side="bull",
                ts_start=c1.time, ts_end=c3.time,
                level_high=lo3, level_low=hi1,
                idx_start=i - 2, idx_end=i, status="fresh"))
        elif lo1 > hi3:
            events.append(Event(kind="FVG", side="bear",
                ts_start=c1.time, ts_end=c3.time,
                level_high=lo1, level_low=hi3,
                idx_start=i - 2, idx_end=i, status="fresh"))
    return events


# ─── Mitigation status ───────────────────────────────────────────
def mark_ob_mitigation(bars: Bars, obs: list[Event], cfg: dict) -> None:
    """Update each OB event's status in-place based on later bar action."""
    mode = cfg.get("ob_mitigation", DEFAULT_CFG["ob_mitigation"])
    n = len(bars)
    for ob in obs:
        for k in range(ob.idx_end + 1, n):
            bar = bars[k]
            if ob.side == "bull":
                if mode == "close_through" and bar.close < ob.level_low:
                    ob.status = "mitigated"; ob.extras["mitigated_at"] = bar.time; break
                if mode == "wick_50":
                    mid = (ob.level_low + ob.level_high) / 2
                    if bar.low <= mid:
                        ob.status = "mitigated"; ob.extras["mitigated_at"] = bar.time; break
                if mode == "wick_full" and bar.low < ob.level_low:
                    ob.status = "mitigated"; ob.extras["mitigated_at"] = bar.time; break
            else:
                if mode == "close_through" and bar.close > ob.level_high:
                    ob.status = "mitigated"; ob.extras["mitigated_at"] = bar.time; break
                if mode == "wick_50":
                    mid = (ob.level_low + ob.level_high) / 2
                    if bar.high >= mid:
                        ob.status = "mitigated"; ob.extras["mitigated_at"] = bar.time; break
                if mode == "wick_full" and bar.high > ob.level_high:
                    ob.status = "mitigated"; ob.extras["mitigated_at"] = bar.time; break


def mark_fvg_fill(bars: Bars, fvgs: list[Event], cfg: dict) -> None:
    mode = cfg.get("fvg_fill", DEFAULT_CFG["fvg_fill"])
    n = len(bars)
    for f in fvgs:
        gap_lo, gap_hi = f.level_low, f.level_high
        mid = (gap_lo + gap_hi) / 2
        fill_pct = 0.0
        for k in range(f.idx_end + 1, n):
            bar = bars[k]
            if f.side == "bull":
                if bar.low <= gap_hi:
                    pen = min(gap_hi, bar.low + (gap_hi - bar.low))  # how far into gap
                    pen_pct = (gap_hi - max(bar.low, gap_lo)) / (gap_hi - gap_lo) if gap_hi > gap_lo else 0
                    fill_pct = max(fill_pct, pen_pct)
                    if mode == "touch":
                        f.status = "mitigated"; break
                    elif mode == "50pct" and fill_pct >= 0.5:
                        f.status = "mitigated"; break
                    elif mode == "full" and bar.low <= gap_lo:
                        f.status = "mitigated"; break
            else:
                if bar.high >= gap_lo:
                    pen_pct = (min(bar.high, gap_hi) - gap_lo) / (gap_hi - gap_lo) if gap_hi > gap_lo else 0
                    fill_pct = max(fill_pct, pen_pct)
                    if mode == "touch":
                        f.status = "mitigated"; break
                    elif mode == "50pct" and fill_pct >= 0.5:
                        f.status = "mitigated"; break
                    elif mode == "full" and bar.high >= gap_hi:
                        f.status = "mitigated"; break
        f.extras["fill_pct"] = round(fill_pct, 3)


# ─── Liquidity pools (equal highs/lows) ──────────────────────────
def detect_liquidity_pools(pivots: list[dict], atr_last: float, cfg: dict) -> dict:
    tol = cfg.get("eqh_tolerance_atr", DEFAULT_CFG["eqh_tolerance_atr"]) * max(atr_last, 1e-9)
    highs = sorted([p for p in pivots if p["kind"] == "H" and p["state"] == "confirmed"],
                   key=lambda p: p["price"])
    lows  = sorted([p for p in pivots if p["kind"] == "L" and p["state"] == "confirmed"],
                   key=lambda p: p["price"])
    def cluster(items):
        out = []
        cur: list = []
        for p in items:
            if not cur or abs(p["price"] - cur[-1]["price"]) <= tol:
                cur.append(p)
            else:
                out.append(cur); cur = [p]
        if cur: out.append(cur)
        return out
    return {
        "high_pools": [{"price": max(c, key=lambda p: p["price"])["price"],
                         "strength": len(c)} for c in cluster(highs)],
        "low_pools":  [{"price": min(c, key=lambda p: p["price"])["price"],
                         "strength": len(c)} for c in cluster(lows)],
    }


# ─── Snapshot composer ──────────────────────────────────────────
def _build_smc_snapshot(bars: Bars, cfg: dict) -> dict:
    """Compute the snapshot dict from a Bars view. Pure function."""
    if len(bars) < 30:
        return _empty_snapshot()
    atr = _atr(bars, cfg.get("atr_period", 14))
    pivots = detect_pivots(bars, cfg)
    bos    = detect_bos(bars, cfg, pivots)
    choch  = detect_choch(bars, cfg, bos)
    sweep  = detect_sweep(bars, cfg, pivots, atr)
    idm    = detect_idm(bars, cfg, pivots, bos)
    obs    = detect_ob(bars, cfg, bos, atr)
    fvgs   = detect_fvg(bars, cfg)
    mark_ob_mitigation(bars, obs, cfg)
    mark_fvg_fill(bars, fvgs, cfg)

    n = len(bars)
    last_idx = n - 1
    last_close = bars[last_idx].close
    atr_last = atr[last_idx] if atr else 0.0
    ob_fresh_window = cfg.get("ob_freshness_bars", DEFAULT_CFG["ob_freshness_bars"])

    # Nearest fresh OB above/below price
    fresh_obs_above = [o for o in obs if o.status == "fresh" and o.side == "bear"
                       and o.level_low > last_close
                       and (last_idx - o.idx_end) <= ob_fresh_window]
    fresh_obs_below = [o for o in obs if o.status == "fresh" and o.side == "bull"
                       and o.level_high < last_close
                       and (last_idx - o.idx_end) <= ob_fresh_window]
    fresh_obs_above.sort(key=lambda o: o.level_low)        # closest above first
    fresh_obs_below.sort(key=lambda o: -o.level_high)      # closest below first

    def ob_view(o: Optional[Event]) -> Optional[dict]:
        if o is None: return None
        return {
            "top":          o.level_high,
            "bottom":       o.level_low,
            "created_at":   o.ts_start,
            "age_bars":     last_idx - o.idx_end,
            "strength":     round(o.strength, 3),
            "tested_count": int(o.extras.get("tested_count", 0)),
        }

    # FVGs (caps)
    max_fvg = cfg.get("max_fvg_per_side", DEFAULT_CFG["max_fvg_per_side"])
    fresh_fvg_bull = [f for f in fvgs if f.side == "bull" and f.status == "fresh"]
    fresh_fvg_bear = [f for f in fvgs if f.side == "bear" and f.status == "fresh"]
    fresh_fvg_bull.sort(key=lambda f: -f.idx_end)          # most recent first
    fresh_fvg_bear.sort(key=lambda f: -f.idx_end)

    def fvg_view(f: Event) -> dict:
        return {
            "top":         f.level_high,
            "bottom":      f.level_low,
            "age_bars":    last_idx - f.idx_end,
            "filled_pct":  float(f.extras.get("fill_pct", 0.0)),
        }

    # Last BOS / CHoCH
    bos_age_max   = cfg.get("bos_age_max_bars",   DEFAULT_CFG["bos_age_max_bars"])
    choch_age_max = cfg.get("choch_age_max_bars", DEFAULT_CFG["choch_age_max_bars"])
    last_bos = bos[-1] if bos else None
    last_bos_view = None
    if last_bos and (last_idx - last_bos.idx_end) <= bos_age_max:
        last_bos_view = {
            "direction": "UP" if last_bos.side == "bull" else "DOWN",
            "level":     last_bos.level_high,
            "age_bars":  last_idx - last_bos.idx_end,
            "confirmed": True,
        }
    last_choch = choch[-1] if choch else None
    last_choch_view = None
    if last_choch and (last_idx - last_choch.idx_end) <= choch_age_max:
        last_choch_view = {
            "direction": "UP" if last_choch.side == "bull" else "DOWN",
            "level":     last_choch.level_high,
            "age_bars":  last_idx - last_choch.idx_end,
        }

    # Recent sweep (within 5 bars by default, but emit info up to bos_age_max)
    last_sweep = sweep[-1] if sweep else None
    recent_sweep_view = None
    if last_sweep and (last_idx - last_sweep.idx_end) <= 8:
        # side: which side's stops were hunted. Bear sweep takes BUY stops above.
        side = "BUY" if last_sweep.side == "bear" else "SELL"
        # Reclaim check: after the sweep bar, did price close back past?
        reclaim = False
        for k in range(last_sweep.idx_end + 1, min(last_sweep.idx_end + 4, n)):
            if last_sweep.side == "bear" and bars[k].close < last_sweep.level_low:
                reclaim = True; break
            if last_sweep.side == "bull" and bars[k].close > last_sweep.level_high:
                reclaim = True; break
        # Even the sweep bar itself counts if it closed back
        if last_sweep.side == "bear" and bars[last_sweep.idx_end].close < last_sweep.level_low:
            reclaim = True
        if last_sweep.side == "bull" and bars[last_sweep.idx_end].close > last_sweep.level_high:
            reclaim = True
        recent_sweep_view = {
            "side":     side,
            "level":    last_sweep.level_low if last_sweep.side == "bear" else last_sweep.level_high,
            "age_bars": last_idx - last_sweep.idx_end,
            "reclaim":  reclaim,
        }

    # Liquidity pools
    pools = detect_liquidity_pools(pivots, atr_last, cfg)
    pool_cap = cfg.get("max_liq_pools_per_side", DEFAULT_CFG["max_liq_pools_per_side"])
    liq_above = sorted([p["price"] for p in pools["high_pools"] if p["price"] > last_close])[:pool_cap]
    liq_below = sorted([p["price"] for p in pools["low_pools"]  if p["price"] < last_close],
                       reverse=True)[:pool_cap]

    # IDM status
    last_idm = idm[-1] if idm else None
    idm_view = None
    if last_idm and (last_idx - last_idm.idx_end) <= 30:
        idm_view = {
            "swept":    True,
            "side":     "UP" if last_idm.side == "bull" else "DOWN",
            "level":    last_idm.level_high,
            "age_bars": last_idx - last_idm.idx_end,
        }

    return {
        "fresh_ob_above":    ob_view(fresh_obs_above[0]) if fresh_obs_above else None,
        "fresh_ob_below":    ob_view(fresh_obs_below[0]) if fresh_obs_below else None,
        "fresh_fvg_bull":    [fvg_view(f) for f in fresh_fvg_bull[:max_fvg]],
        "fresh_fvg_bear":    [fvg_view(f) for f in fresh_fvg_bear[:max_fvg]],
        "last_bos":          last_bos_view,
        "last_choch":        last_choch_view,
        "recent_liq_sweep":  recent_sweep_view,
        "liq_above":         liq_above,
        "liq_below":         liq_below,
        "idm_status":        idm_view,
        "atr14":             atr_last,
        "current":           last_close,
    }


def _empty_snapshot() -> dict:
    return {
        "fresh_ob_above": None, "fresh_ob_below": None,
        "fresh_fvg_bull": [], "fresh_fvg_bear": [],
        "last_bos": None, "last_choch": None,
        "recent_liq_sweep": None,
        "liq_above": [], "liq_below": [],
        "idm_status": None,
        "atr14": 0.0, "current": 0.0,
    }


# ─── Detailed events list (for the chart drawer) ────────────────
def compute_events(bars, cfg: Optional[dict] = None) -> list[Event]:
    """Return ALL detected events (not just the snapshot-truncated view).
    Used by chart_drawings to render the full SMC picture on MT5."""
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    bv = bars if isinstance(bars, Bars) else Bars(bars)
    if len(bv) < 30: return []
    atr = _atr(bv, cfg.get("atr_period", 14))
    pivots = detect_pivots(bv, cfg)
    bos    = detect_bos(bv, cfg, pivots)
    choch  = detect_choch(bv, cfg, bos)
    sweep  = detect_sweep(bv, cfg, pivots, atr)
    idm    = detect_idm(bv, cfg, pivots, bos)
    obs    = detect_ob(bv, cfg, bos, atr)
    fvgs   = detect_fvg(bv, cfg)
    mark_ob_mitigation(bv, obs, cfg)
    mark_fvg_fill(bv, fvgs, cfg)
    return bos + choch + sweep + idm + obs + fvgs


# ─── Public entry points ────────────────────────────────────────
_TF_NAME_TO_MT5 = {
    "M1":  1,  "M5":  5,   "M15": 15,
    "M30": 30, "H1":  60,  "H4":  240,
    "D1":  1440,
}

# Per-(symbol, tf) cache: {key: (last_bar_epoch, snapshot_dict)}
_snapshot_cache: dict = {}


def compute_offline(bars, cfg: Optional[dict] = None) -> dict:
    """Compute SMC snapshot from a pre-fetched bars array. Pure — no I/O.

    `bars` may be a numpy structured array (with `time/open/high/low/close`)
    OR a list of dicts with those keys.
    """
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    bv = bars if isinstance(bars, Bars) else Bars(bars)
    return _build_smc_snapshot(bv, cfg)


def compute_smc_snapshot(symbol: str, tf_name: str, bars_back: int = 200,
                         cfg: Optional[dict] = None) -> dict:
    """Live path — fetches bars from MT5 then computes the snapshot.

    Returns an empty (but well-formed) snapshot on any failure so callers
    never need to defensively check before drilling into the dict.
    """
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    try:
        import MetaTrader5 as mt5  # noqa: F401 — only imported when live
    except Exception:
        return _empty_snapshot()
    try:
        if not mt5.initialize():
            mt5.initialize()
        tf_const = _resolve_tf_const(mt5, tf_name)
        if tf_const is None: return _empty_snapshot()
        # Cache key by (symbol, tf, last bar epoch)
        rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, bars_back)
        if rates is None or len(rates) < 30:
            return _empty_snapshot()
        last_epoch = int(rates["time"][-1])
        key = (symbol, tf_name)
        cached = _snapshot_cache.get(key)
        if cached and cached[0] == last_epoch:
            return cached[1]
        snap = _build_smc_snapshot(Bars(rates), cfg)
        _snapshot_cache[key] = (last_epoch, snap)
        return snap
    except Exception:
        return _empty_snapshot()


def _resolve_tf_const(mt5, tf_name: str):
    tf_name = (tf_name or "").upper()
    mapping = {
        "M1":  getattr(mt5, "TIMEFRAME_M1",  None),
        "M5":  getattr(mt5, "TIMEFRAME_M5",  None),
        "M15": getattr(mt5, "TIMEFRAME_M15", None),
        "M30": getattr(mt5, "TIMEFRAME_M30", None),
        "H1":  getattr(mt5, "TIMEFRAME_H1",  None),
        "H4":  getattr(mt5, "TIMEFRAME_H4",  None),
        "D1":  getattr(mt5, "TIMEFRAME_D1",  None),
    }
    return mapping.get(tf_name)

"""
r_levels.py — Reads the chart like a professional trader.

Detects key price levels R should respect for entries, SLs, and TPs:

  HORIZONTAL LEVELS
    • Previous Day High/Low (PDH / PDL)
    • Previous Week High/Low (PWH / PWL)
    • Daily Open / H4 Open
    • Current session's High/Low
    • Round numbers (×5, ×10, ×50)

  DYNAMIC LEVELS
    • VWAP and ±1σ / ±2σ bands (volume-weighted typical price)
    • Swing highs / swing lows (last 5 of each, ≥ 3-bar pivots)

  SMC-STYLE
    • Bullish FVG (Fair Value Gap) — gap below price waiting to fill
    • Bearish FVG — gap above price
    • Bullish OB (last bullish candle before sharp drop)
    • Bearish OB (last bearish candle before sharp rally)

Then for any (side, entry) R wants to take, find:
    nearest_resistance_above(entry) → TP for BUY / SL for SELL
    nearest_support_below(entry)   → SL for BUY / TP for SELL
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import MetaTrader5 as mt5
import numpy as np


@dataclass
class Level:
    name:   str         # e.g. "PDH", "VWAP+1σ", "FVG_BULL_4500.2"
    price:  float
    kind:   str         # "support" / "resistance" / "neutral"
    weight: float = 1.0 # 0..1, stronger = more likely to hold
    note:   str = ""


def _last_n_bars(symbol: str, tf, n: int) -> Optional[np.ndarray]:
    try: return mt5.copy_rates_from_pos(symbol, tf, 0, n)
    except Exception: return None


# ── Horizontal levels ─────────────────────────────────────────────
def get_session_levels(symbol: str) -> list[Level]:
    levels: list[Level] = []
    d = _last_n_bars(symbol, mt5.TIMEFRAME_D1, 5)
    if d is not None and len(d) >= 2:
        # Previous day = index -2 (last completed)
        prev = d[-2]
        levels.append(Level("PDH",  float(prev["high"]),  "resistance", 0.85, "Prev day high"))
        levels.append(Level("PDL",  float(prev["low"]),   "support",    0.85, "Prev day low"))
        levels.append(Level("PDO",  float(prev["open"]),  "neutral",    0.5, "Prev day open"))
        levels.append(Level("PDC",  float(prev["close"]), "neutral",    0.6, "Prev day close"))
        # Today's open + current H/L so far
        today = d[-1]
        levels.append(Level("DO",   float(today["open"]), "neutral",    0.7, "Today open"))
        levels.append(Level("DH",   float(today["high"]), "resistance", 0.6, "Today's high so far"))
        levels.append(Level("DL",   float(today["low"]),  "support",    0.6, "Today's low so far"))

    # Previous week
    w = _last_n_bars(symbol, mt5.TIMEFRAME_W1, 3)
    if w is not None and len(w) >= 2:
        prevw = w[-2]
        levels.append(Level("PWH", float(prevw["high"]),  "resistance", 0.9,  "Prev week high"))
        levels.append(Level("PWL", float(prevw["low"]),   "support",    0.9,  "Prev week low"))

    # H4 last bar open/H/L
    h4 = _last_n_bars(symbol, mt5.TIMEFRAME_H4, 5)
    if h4 is not None and len(h4) >= 2:
        last = h4[-2]
        levels.append(Level("H4_O", float(last["open"]),  "neutral",    0.55, "Prev H4 open"))
        levels.append(Level("H4_H", float(last["high"]),  "resistance", 0.65, "Prev H4 high"))
        levels.append(Level("H4_L", float(last["low"]),   "support",    0.65, "Prev H4 low"))

    return levels


# ── VWAP + bands ─────────────────────────────────────────────────
def get_vwap_levels(symbol: str) -> list[Level]:
    """Daily VWAP from M5 bars since session start (UTC midnight)."""
    bars = _last_n_bars(symbol, mt5.TIMEFRAME_M5, 288 * 2)   # 2 days of M5
    if bars is None or len(bars) < 30: return []
    # Filter bars from today UTC midnight
    today_midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = int(today_midnight.timestamp())
    today_bars = bars[bars["time"] >= cutoff]
    if len(today_bars) < 10: today_bars = bars[-60:]   # fallback: last 5h
    typical = (today_bars["high"] + today_bars["low"] + today_bars["close"]) / 3
    vol = today_bars["tick_volume"].astype(float)
    if vol.sum() == 0: return []
    vwap = float((typical * vol).sum() / vol.sum())
    # Std dev around VWAP weighted by volume
    var = ((typical - vwap) ** 2 * vol).sum() / vol.sum()
    sigma = math.sqrt(max(0.0, var))
    out = [Level("VWAP",     vwap,             "neutral",    0.8, "Volume-weighted average")]
    if sigma > 0:
        out.append(Level("VWAP+1σ", vwap + sigma,     "resistance", 0.7, "VWAP + 1 std-dev"))
        out.append(Level("VWAP-1σ", vwap - sigma,     "support",    0.7, "VWAP - 1 std-dev"))
        out.append(Level("VWAP+2σ", vwap + 2*sigma,   "resistance", 0.85,"VWAP + 2 std-dev (extreme)"))
        out.append(Level("VWAP-2σ", vwap - 2*sigma,   "support",    0.85,"VWAP - 2 std-dev (extreme)"))
    return out


# ── Swing highs/lows ─────────────────────────────────────────────
def get_swing_levels(symbol: str, lookback: int = 100, pivot: int = 3,
                     max_each: int = 5) -> list[Level]:
    """Detect swing highs (high with `pivot` lower highs on each side) and lows."""
    bars = _last_n_bars(symbol, mt5.TIMEFRAME_H1, lookback)
    if bars is None or len(bars) < 2 * pivot + 1: return []
    highs = bars["high"]; lows = bars["low"]
    swings: list[Level] = []
    for i in range(pivot, len(bars) - pivot):
        is_high = all(highs[i] >= highs[i-k] for k in range(1, pivot+1)) and \
                  all(highs[i] >= highs[i+k] for k in range(1, pivot+1))
        is_low  = all(lows[i]  <= lows[i-k]  for k in range(1, pivot+1)) and \
                  all(lows[i]  <= lows[i+k]  for k in range(1, pivot+1))
        if is_high:
            swings.append(Level(f"SwH{len(bars)-i}", float(highs[i]), "resistance", 0.7,
                                f"Swing H ({len(bars)-i} bars ago)"))
        elif is_low:
            swings.append(Level(f"SwL{len(bars)-i}", float(lows[i]), "support", 0.7,
                                f"Swing L ({len(bars)-i} bars ago)"))
    # Keep most recent N per side
    h_list = [s for s in swings if s.kind == "resistance"][-max_each:]
    l_list = [s for s in swings if s.kind == "support"][-max_each:]
    return h_list + l_list


# ── Fair Value Gaps (3-candle pattern) ──────────────────────────
def get_fvg_levels(symbol: str, lookback: int = 60) -> list[Level]:
    """Bullish FVG: high[i-2] < low[i]  (gap up, support zone)
       Bearish FVG: low[i-2]  > high[i] (gap down, resistance zone)
       Unfilled gaps remain valid."""
    bars = _last_n_bars(symbol, mt5.TIMEFRAME_M15, lookback)
    if bars is None or len(bars) < 5: return []
    levels: list[Level] = []
    cur = float(bars["close"][-1])
    for i in range(2, len(bars) - 1):
        h_im2 = float(bars["high"][i-2]); l_im2 = float(bars["low"][i-2])
        h_i   = float(bars["high"][i]);   l_i   = float(bars["low"][i])
        # Bullish gap: high of i-2 < low of i — gap area between them
        if h_im2 < l_i:
            top = l_i; bottom = h_im2; mid = (top + bottom) / 2
            # Only if not yet filled by subsequent candles
            filled = any(float(bars["low"][j]) <= bottom for j in range(i+1, len(bars)))
            if not filled and cur > top:
                levels.append(Level(f"FVG_BULL_{mid:.2f}", mid, "support", 0.75,
                                    f"Unfilled bullish FVG [{bottom:.2f}-{top:.2f}]"))
        # Bearish gap: low of i-2 > high of i
        if l_im2 > h_i:
            top = l_im2; bottom = h_i; mid = (top + bottom) / 2
            filled = any(float(bars["high"][j]) >= top for j in range(i+1, len(bars)))
            if not filled and cur < bottom:
                levels.append(Level(f"FVG_BEAR_{mid:.2f}", mid, "resistance", 0.75,
                                    f"Unfilled bearish FVG [{bottom:.2f}-{top:.2f}]"))
    # Keep latest 4 of each side
    bulls = [l for l in levels if "BULL" in l.name][-4:]
    bears = [l for l in levels if "BEAR" in l.name][-4:]
    return bulls + bears


# ── Liquidity sweeps (stop-hunt reversals) ──────────────────────
def _scan_sweeps(bars, pivot: int = 3, wick_frac: float = 0.30,
                 recent_bars: int = 3) -> dict:
    """Pure sweep scanner over a structured OHLC array (MT5 rates shape).

    A liquidity sweep = a confirmed swing high/low is pierced intra-bar in the
    last `recent_bars` candles, but price closes back inside the level, leaving
    a rejection wick ≥ `wick_frac` of the bar range → classic stop-hunt reversal.

      sweep_above: a swing HIGH was taken (buy-side liquidity grabbed) then
                   rejected → BEARISH bias (fade the fake break up).
      sweep_below: a swing LOW was taken (sell-side liquidity grabbed) then
                   rejected → BULLISH bias (fade the fake break down).
    """
    out = {"ok": False, "sweep_above": False, "sweep_below": False,
           "above_level": None, "below_level": None,
           "above_bars_ago": None, "below_bars_ago": None, "note": ""}
    if bars is None or len(bars) < 2 * pivot + recent_bars + 2:
        out["note"] = "insufficient bars"
        return out
    n = len(bars)
    highs = bars["high"]; lows = bars["low"]
    opens = bars["open"]; closes = bars["close"]

    # Confirmed pivots in the OLDER portion only (need `pivot` bars each side and
    # they must sit before the recent window so they can be swept by it).
    swing_highs: list[tuple[int, float]] = []
    swing_lows:  list[tuple[int, float]] = []
    for i in range(pivot, n - pivot):
        if i >= n - recent_bars - pivot:
            continue
        if all(highs[i] >= highs[i-k] for k in range(1, pivot+1)) and \
           all(highs[i] >= highs[i+k] for k in range(1, pivot+1)):
            swing_highs.append((i, float(highs[i])))
        if all(lows[i] <= lows[i-k] for k in range(1, pivot+1)) and \
           all(lows[i] <= lows[i+k] for k in range(1, pivot+1)):
            swing_lows.append((i, float(lows[i])))

    # Examine the last `recent_bars` candles for a pierce-then-reject.
    for j in range(n - recent_bars, n):
        hi = float(highs[j]); lo = float(lows[j])
        op = float(opens[j]); cl = float(closes[j])
        rng = hi - lo
        if rng <= 0:
            continue
        if not out["sweep_above"]:
            for si, sp in swing_highs:
                if si >= j:
                    continue
                if hi > sp and cl < sp and (hi - max(op, cl)) >= wick_frac * rng:
                    out["sweep_above"] = True
                    out["above_level"] = round(sp, 3)
                    out["above_bars_ago"] = n - 1 - j
                    break
        if not out["sweep_below"]:
            for si, sp in swing_lows:
                if si >= j:
                    continue
                if lo < sp and cl > sp and (min(op, cl) - lo) >= wick_frac * rng:
                    out["sweep_below"] = True
                    out["below_level"] = round(sp, 3)
                    out["below_bars_ago"] = n - 1 - j
                    break

    out["ok"] = True
    notes = []
    if out["sweep_above"]:
        notes.append(f"BEARISH sweep: swing high {out['above_level']} taken then "
                     f"rejected ({out['above_bars_ago']}b ago)")
    if out["sweep_below"]:
        notes.append(f"BULLISH sweep: swing low {out['below_level']} taken then "
                     f"rejected ({out['below_bars_ago']}b ago)")
    out["note"] = " | ".join(notes) if notes else "no recent sweep"
    return out


def detect_liquidity_sweeps(symbol: str, tf=None, lookback: int = 60,
                            pivot: int = 3, wick_frac: float = 0.30,
                            recent_bars: int = 3) -> dict:
    """Detect liquidity sweeps on `symbol` (M15 by default). Returns the
    sweep_above / sweep_below booleans + the swept level + bars-ago metadata."""
    if tf is None:
        tf = mt5.TIMEFRAME_M15
    bars = _last_n_bars(symbol, tf, lookback)
    r = _scan_sweeps(bars, pivot=pivot, wick_frac=wick_frac, recent_bars=recent_bars)
    r["symbol"] = symbol
    return r


# ── Order blocks (institutional supply/demand zones) ────────────
def _scan_order_blocks(bars, impulse_bars: int = 3, disp_mult: float = 1.5,
                       max_bars_ago: int = 40) -> dict:
    """Pure order-block scanner over a structured OHLC array (MT5 rates shape).

    An order block = the last opposite-colour candle immediately before a strong
    displacement (impulse) move — the footprint of institutional accumulation.

      OB_bull (demand): the last BEARISH candle before a sharp RALLY. Its
                        [low, high] is a support zone price often revisits.
      OB_bear (supply): the last BULLISH candle before a sharp DROP. Its
                        [low, high] is a resistance zone.

    The impulse must displace ≥ `disp_mult` × avg-bar-range over the next
    `impulse_bars` candles AND break past the OB candle's extreme (engulf), so
    plain noise is rejected. Only the MOST RECENT block each side is returned.
    `mitigated` = price has since traded back into the zone (tested → weaker).
    """
    out = {"ok": False, "OB_bull": None, "OB_bear": None, "note": ""}
    n = 0 if bars is None else len(bars)
    if n < impulse_bars + 5:
        out["note"] = "insufficient bars"
        return out

    highs = bars["high"]; lows = bars["low"]
    opens = bars["open"]; closes = bars["close"]
    avg_range = float(np.mean(highs - lows))
    if avg_range <= 0:
        out["note"] = "flat market"
        return out
    disp = disp_mult * avg_range

    bull = None  # (i, low, high)  — demand
    bear = None  # (i, low, high)  — supply
    lo_bound = max(0, n - impulse_bars - 1 - max_bars_ago)
    # Ascend so the newest qualifying block overwrites older ones.
    for i in range(lo_bound, n - impulse_bars):
        o = float(opens[i]); c = float(closes[i])
        j = i + impulse_bars
        # Bullish OB: bearish candle → up impulse that engulfs its high.
        if c < o:
            if (float(closes[j]) - c) >= disp and float(highs[j]) > float(highs[i]):
                bull = (i, float(lows[i]), float(highs[i]))
        # Bearish OB: bullish candle → down impulse that engulfs its low.
        if c > o:
            if (c - float(closes[j])) >= disp and float(lows[j]) < float(lows[i]):
                bear = (i, float(lows[i]), float(highs[i]))

    def _finish(ob):
        if ob is None:
            return None
        i, lo, hi = ob
        # Mitigated = any later bar (after the impulse) overlapped the zone.
        mitigated = False
        for k in range(i + impulse_bars + 1, n):
            if float(lows[k]) <= hi and float(highs[k]) >= lo:
                mitigated = True
                break
        return {"low": round(lo, 3), "high": round(hi, 3),
                "mid": round((lo + hi) / 2, 3),
                "bars_ago": n - 1 - i, "mitigated": mitigated}

    out["OB_bull"] = _finish(bull)
    out["OB_bear"] = _finish(bear)
    out["ok"] = True
    notes = []
    if out["OB_bull"]:
        b = out["OB_bull"]
        notes.append(f"BULLISH OB (demand) {b['low']}-{b['high']} "
                     f"{'mitigated' if b['mitigated'] else 'fresh'} ({b['bars_ago']}b ago)")
    if out["OB_bear"]:
        b = out["OB_bear"]
        notes.append(f"BEARISH OB (supply) {b['low']}-{b['high']} "
                     f"{'mitigated' if b['mitigated'] else 'fresh'} ({b['bars_ago']}b ago)")
    out["note"] = " | ".join(notes) if notes else "no recent order block"
    return out


def detect_order_blocks(symbol: str, tf=None, lookback: int = 60,
                        impulse_bars: int = 3, disp_mult: float = 1.5) -> dict:
    """Detect order blocks on `symbol` (M15 by default). Returns OB_bull /
    OB_bear zones (low/high/mid) each with a `mitigated` flag + bars-ago."""
    if tf is None:
        tf = mt5.TIMEFRAME_M15
    bars = _last_n_bars(symbol, tf, lookback)
    r = _scan_order_blocks(bars, impulse_bars=impulse_bars, disp_mult=disp_mult)
    r["symbol"] = symbol
    return r


# ── Round numbers ───────────────────────────────────────────────
def get_round_numbers(current_price: float, step: float = 5.0,
                       count_each_side: int = 3) -> list[Level]:
    base = math.floor(current_price / step) * step
    out = []
    for k in range(-count_each_side, count_each_side + 1):
        p = base + k * step
        # Stronger weight for ×10 and ×50 levels
        w = 0.4
        if abs(p - round(p/50)*50) < 0.01: w = 0.75
        elif abs(p - round(p/10)*10) < 0.01: w = 0.6
        kind = "support" if p < current_price else "resistance" if p > current_price else "neutral"
        out.append(Level(f"R{int(p)}", p, kind, w, f"Round number {p}"))
    return out


# ── Composite ───────────────────────────────────────────────────
def compute_all_levels(symbol: str = "XAUUSDm") -> dict:
    """Returns all detected levels + nearest support/resistance."""
    if not mt5.initialize():
        return {"ok": False, "error": "mt5 init"}
    try:
        tick = mt5.symbol_info_tick(symbol)
        if not tick: return {"ok": False, "error": "no tick"}
        current = (tick.bid + tick.ask) / 2

        all_levels: list[Level] = []
        all_levels += get_session_levels(symbol)
        all_levels += get_vwap_levels(symbol)
        all_levels += get_swing_levels(symbol)
        all_levels += get_fvg_levels(symbol)
        all_levels += get_round_numbers(current)

        # Deduplicate near-identical levels (within 0.05 = 5 cents)
        all_levels.sort(key=lambda l: l.price)
        dedup: list[Level] = []
        for lvl in all_levels:
            if dedup and abs(lvl.price - dedup[-1].price) < 0.05:
                # Merge: keep the higher-weight one with combined note
                if lvl.weight > dedup[-1].weight:
                    lvl.note = f"{dedup[-1].note} + {lvl.note}"
                    dedup[-1] = lvl
                else:
                    dedup[-1].note += f" + {lvl.name}"
            else:
                dedup.append(lvl)

        # Above / below current
        above = sorted([l for l in dedup if l.price > current], key=lambda l: l.price)
        below = sorted([l for l in dedup if l.price < current], key=lambda l: -l.price)

        # Liquidity sweeps (stop-hunt reversals) on M15
        sweeps = detect_liquidity_sweeps(symbol)

        # Order blocks (institutional supply/demand zones) on M15
        obs = detect_order_blocks(symbol)

        # Best (nearest with weight ≥ 0.6)
        nearest_R = next((l for l in above if l.weight >= 0.6), None)
        nearest_S = next((l for l in below if l.weight >= 0.6), None)

        # Major (next strong level beyond nearest, weight ≥ 0.8)
        major_R = next((l for l in above if l.weight >= 0.8 and (not nearest_R or l.price > nearest_R.price + 0.50)), None)
        major_S = next((l for l in below if l.weight >= 0.8 and (not nearest_S or l.price < nearest_S.price - 0.50)), None)

        def to_d(lvl: Optional[Level]):
            return None if not lvl else {
                "name": lvl.name, "price": round(lvl.price, 3),
                "kind": lvl.kind, "weight": lvl.weight, "note": lvl.note,
                "distance": round(lvl.price - current, 3),
            }

        return {
            "ok":            True,
            "symbol":        symbol,
            "current":       round(current, 3),
            "ts":            datetime.now(timezone.utc).isoformat(),
            "nearest_resistance": to_d(nearest_R),
            "nearest_support":    to_d(nearest_S),
            "major_resistance":   to_d(major_R),
            "major_support":      to_d(major_S),
            "above":         [to_d(l) for l in above[:8]],
            "below":         [to_d(l) for l in below[:8]],
            "total_levels":  len(dedup),
            "sweep_above":   sweeps.get("sweep_above", False),
            "sweep_below":   sweeps.get("sweep_below", False),
            "sweeps":        sweeps,
            "OB_bull":       obs.get("OB_bull"),
            "OB_bear":       obs.get("OB_bear"),
            "order_blocks":  obs,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def propose_trade_levels(side: str, current: float,
                          levels_data: dict, min_rr: float = 2.0,
                          max_sl_dist: float = 3.0) -> dict:
    """Given current price + side, propose SL/TP based on real levels.
       Returns entry/sl/near_tp/far_tp and the levels chosen + reasoning."""
    if not levels_data.get("ok"):
        return {"ok": False, "error": "no levels"}

    above = levels_data.get("above") or []
    below = levels_data.get("below") or []
    nearest_R = levels_data.get("nearest_resistance")
    nearest_S = levels_data.get("nearest_support")
    major_R   = levels_data.get("major_resistance")
    major_S   = levels_data.get("major_support")

    out = {"ok": True, "side": side, "entry": current,
           "sl": None, "near_tp": None, "far_tp": None,
           "sl_level": None, "near_tp_level": None, "far_tp_level": None,
           "rr": 0, "reasoning": ""}

    if side == "BUY":
        # SL = just below nearest support (so a break invalidates the long)
        if nearest_S:
            sl = nearest_S["price"] - 0.10   # 10 cents below the level
        else:
            sl = current - max_sl_dist
        # Near TP = nearest resistance above
        near_tp_level = nearest_R
        # Far TP = next major resistance
        far_tp_level  = major_R or (above[1] if len(above) >= 2 else None)
        if near_tp_level:
            near_tp = near_tp_level["price"] - 0.05
        else:
            near_tp = current + abs(current - sl) * 2
        if far_tp_level:
            far_tp = far_tp_level["price"] - 0.05
        else:
            far_tp = current + abs(current - sl) * 3
        out["sl_level"]      = nearest_S
        out["near_tp_level"] = near_tp_level
        out["far_tp_level"]  = far_tp_level

    else:   # SELL
        if nearest_R:
            sl = nearest_R["price"] + 0.10
        else:
            sl = current + max_sl_dist
        near_tp_level = nearest_S
        far_tp_level  = major_S or (below[1] if len(below) >= 2 else None)
        if near_tp_level:
            near_tp = near_tp_level["price"] + 0.05
        else:
            near_tp = current - abs(sl - current) * 2
        if far_tp_level:
            far_tp = far_tp_level["price"] + 0.05
        else:
            far_tp = current - abs(sl - current) * 3
        out["sl_level"]      = nearest_R
        out["near_tp_level"] = near_tp_level
        out["far_tp_level"]  = far_tp_level

    # Clamp SL to max distance (risk protection)
    if abs(current - sl) > max_sl_dist:
        if side == "BUY": sl = current - max_sl_dist
        else:             sl = current + max_sl_dist
        out["reasoning"] += f" SL clamped to max_dist={max_sl_dist}; "

    out["sl"]      = round(sl, 3)
    out["near_tp"] = round(near_tp, 3)
    out["far_tp"]  = round(far_tp, 3)
    sl_dist = abs(current - sl)
    tp_dist = abs(far_tp - current)
    out["rr"] = round(tp_dist / sl_dist, 2) if sl_dist > 0 else 0
    out["ok_rr"] = out["rr"] >= min_rr

    parts = []
    if out["sl_level"]: parts.append(f"SL just past {out['sl_level']['name']} ({out['sl_level']['price']})")
    if out["near_tp_level"]: parts.append(f"near TP at {out['near_tp_level']['name']} ({out['near_tp_level']['price']})")
    if out["far_tp_level"]: parts.append(f"far TP at {out['far_tp_level']['name']} ({out['far_tp_level']['price']})")
    out["reasoning"] = " · ".join(parts) + f" · R:R 1:{out['rr']}"

    return out


if __name__ == "__main__":
    import json
    r = compute_all_levels()
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    if r.get("ok"):
        for side in ("BUY", "SELL"):
            print(f"\n=== Proposed {side} ===")
            print(json.dumps(propose_trade_levels(side, r["current"], r), ensure_ascii=False, indent=2, default=str))

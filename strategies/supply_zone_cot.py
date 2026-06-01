"""strategies/supply_zone_cot.py — Supply/Demand zones gated by COT regime.

Reverse-engineered from the NOLAN.VADER methodology:

  • Identify supply zones (bearish OBs) and demand zones (bullish OBs) using
    smc_engine — exactly the same FVG/OB detector the rest of R-Native uses.
  • Cross-reference with the weekly CFTC Commitment of Traders report.
  • Only SHORT a supply zone when COT confirms: Commercials are net SHORT
    extreme AND Non-Commercials (retail proxy) are net LONG extreme.
  • Only BUY a demand zone when COT confirms: Commercials net LONG extreme
    AND Non-Commercials net SHORT extreme.

The COT regime is normalized via the standard 52-week COT Index:
  cot_idx = (current - min_52w) / (max_52w - min_52w) * 100

Commercials extreme bullish  →  cot_idx ≥ 80
Commercials extreme bearish  →  cot_idx ≤ 20
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import csv
import numpy as np


# ─── COT regime computation ─────────────────────────────────────
def cot_index(values: list[float], lookback: int = 52) -> list[float]:
    """Standard COT Index: 0..100 normalized over the past `lookback` weeks.

    values: time-ordered list of weekly net-position numbers.
    """
    out: list[float] = []
    for i, v in enumerate(values):
        if i < lookback - 1:
            out.append(float("nan")); continue
        window = values[i - lookback + 1: i + 1]
        lo, hi = min(window), max(window)
        if hi == lo:
            out.append(50.0)
        else:
            out.append((v - lo) / (hi - lo) * 100.0)
    return out


def load_cot_weekly(path: str | Path, market_name: str = "GOLD") -> list[dict]:
    """Parse a CFTC COT export (legacy futures-only format) and return weekly
    {date, comm_net, noncomm_net, comm_idx, noncomm_idx} for the named market.

    Works with the public CFTC bulk text files (the same format used by
    `cot_reports` PyPI package and by the historical archives on cftc.gov).
    """
    rows = []
    with open(path, encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            mkt = (r.get("Market and Exchange Names") or "").strip().strip('"')
            if market_name.upper() not in mkt.upper():
                continue
            try:
                date = r["As of Date in Form YYYY-MM-DD"].strip()
                # Use legacy report fields (Commercial vs Noncommercial)
                comm_long  = int(r["Commercial Positions-Long (All)"].strip())
                comm_short = int(r["Commercial Positions-Short (All)"].strip())
                ncom_long  = int(r["Noncommercial Positions-Long (All)"].strip())
                ncom_short = int(r["Noncommercial Positions-Short (All)"].strip())
            except (KeyError, ValueError):
                continue
            rows.append({
                "date":         date,
                "comm_net":     comm_long  - comm_short,
                "noncomm_net":  ncom_long  - ncom_short,
            })
    rows.sort(key=lambda r: r["date"])
    if not rows:
        return rows
    comm_idx = cot_index([r["comm_net"]    for r in rows])
    ncom_idx = cot_index([r["noncomm_net"] for r in rows])
    for r, ci, ni in zip(rows, comm_idx, ncom_idx):
        r["comm_idx"]    = ci
        r["noncomm_idx"] = ni
    return rows


def cot_regime(comm_idx: float, noncomm_idx: float,
               extreme_high: float = 80.0,
               extreme_low: float = 20.0) -> str:
    """Classify the weekly regime per the Nolan Vader rules.

    BULLISH_SETUP    : Commercials extreme LONG  + Retail extreme SHORT
                       -> trade demand zones LONG, avoid supply shorts
    BEARISH_SETUP    : Commercials extreme SHORT + Retail extreme LONG
                       -> trade supply zones SHORT, avoid demand longs
    NEUTRAL          : neither divergence present
    """
    if np.isnan(comm_idx) or np.isnan(noncomm_idx):
        return "NEUTRAL"
    if comm_idx >= extreme_high and noncomm_idx <= extreme_low:
        return "BULLISH_SETUP"
    if comm_idx <= extreme_low and noncomm_idx >= extreme_high:
        return "BEARISH_SETUP"
    return "NEUTRAL"


def regime_for_date(cot_weekly: list[dict], date_unix: int) -> str:
    """Look up the active COT regime for a Unix timestamp.

    COT reports are released Friday-close-of-business each week; we use the
    most recent report whose `date` is <= the bar's date.
    """
    if not cot_weekly:
        return "NEUTRAL"
    bar_date = datetime.fromtimestamp(date_unix, timezone.utc).date().isoformat()
    last = None
    for r in cot_weekly:
        if r["date"] <= bar_date:
            last = r
        else:
            break
    if last is None:
        return "NEUTRAL"
    return cot_regime(last["comm_idx"], last["noncomm_idx"])


# ─── Supply/Demand zone backtest using smc_engine OBs ───────────
def backtest(bars: list, cot_weekly: list[dict] | None,
             *, atr_sl_mult: float = 1.5,
             zone_buffer_atr: float = 0.5,
             max_zone_age_bars: int = 200,
             require_cot: bool = True,
             lot_value_per_unit: float = 1.0,
             smc_cfg: dict | None = None) -> dict:
    """Walk bars left-to-right, identify supply (bearish OB) and demand
    (bullish OB) zones from smc_engine, enter when price touches a fresh zone,
    gated by the COT regime if `require_cot` is True.

    SHORT supply zone -> only if regime == BEARISH_SETUP (or NEUTRAL when
                          require_cot=False).
    BUY  demand zone -> only if regime == BULLISH_SETUP.

    Exit: 2:1 R:R based on ATR(14) — TP at entry + 2*sl_dist (opposite side).
    """
    try:
        from r_native import smc_engine as se
    except Exception:
        import smc_engine as se

    smc_cfg = {**se.DEFAULT_CFG, **(smc_cfg or {})}
    bv = se.Bars(bars)
    n = len(bv)
    if n < 50:
        return {"trades": [], "summary": {"trades": 0, "wins": 0, "losses": 0,
                "win_rate": 0, "profit_factor": 0, "net_pnl": 0,
                "skipped_by_cot": 0, "exit_breakdown": {}}}

    # Detect ALL OBs (both sides) once over the whole window
    det = se._run_all_detectors(bv, smc_cfg)
    obs = det["obs"]
    atr = det["atr"]

    # ATR fallback if smc_engine atr returned 0 anywhere
    atr_arr = np.array(atr, dtype=float)
    atr_arr[atr_arr == 0] = np.nanmean(atr_arr[atr_arr > 0]) if (atr_arr > 0).any() else 1.0

    # Build a per-bar list of "active zones" — fresh OBs whose idx_end <= i
    obs_sorted = sorted(obs, key=lambda o: o.idx_end)

    open_positions = []   # [{side, entry, sl, tp, idx_open, regime}]
    trades = []
    equity = 0.0
    equity_curve = []
    skipped_cot = 0
    skipped_no_zone = 0

    # Cache the last-seen OBs by side so we don't iterate the whole list every bar
    next_ob = 0
    active_supply: list = []
    active_demand: list = []

    for i in range(1, n):
        # Bring new OBs online whose idx_end == i-1 (just confirmed)
        while next_ob < len(obs_sorted) and obs_sorted[next_ob].idx_end <= i - 1:
            ob = obs_sorted[next_ob]
            if ob.status == "fresh":
                if ob.side == "bear":  active_supply.append(ob)
                else:                  active_demand.append(ob)
            next_ob += 1
        # Drop stale zones
        active_supply = [o for o in active_supply
                          if (i - o.idx_end) <= max_zone_age_bars and o.status == "fresh"]
        active_demand = [o for o in active_demand
                          if (i - o.idx_end) <= max_zone_age_bars and o.status == "fresh"]

        # Check SL/TP on open positions
        still_open = []
        for pos in open_positions:
            bar_h = bv[i].high; bar_l = bv[i].low
            exit_px = None; reason = ""
            if pos["side"] == "SELL":
                if bar_h >= pos["sl"]: exit_px = pos["sl"]; reason = "SL"
                elif bar_l <= pos["tp"]: exit_px = pos["tp"]; reason = "TP"
            else:
                if bar_l <= pos["sl"]: exit_px = pos["sl"]; reason = "SL"
                elif bar_h >= pos["tp"]: exit_px = pos["tp"]; reason = "TP"
            if exit_px is not None:
                pnl = ((exit_px - pos["entry"]) if pos["side"] == "BUY"
                       else (pos["entry"] - exit_px)) * lot_value_per_unit
                equity += pnl
                trades.append({**pos, "exit": exit_px, "profit": pnl,
                               "idx_close": i, "exit_reason": reason})
            else:
                still_open.append(pos)
        open_positions = still_open

        # Try new entry: must touch a fresh zone + COT regime confirms (optional)
        if len(open_positions) >= 2:
            equity_curve.append({"i": i, "eq": equity}); continue

        bar = bv[i]
        regime = regime_for_date(cot_weekly or [], bar.time) if cot_weekly else "NEUTRAL"

        # SHORT a supply zone if price wicked into it
        for ob in active_supply:
            if bar.high >= ob.level_low and bar.low <= ob.level_high:
                if require_cot and regime != "BEARISH_SETUP":
                    skipped_cot += 1; break
                entry = min(bar.close, ob.level_high)
                sl_dist = atr_sl_mult * atr_arr[i]
                sl = ob.level_high + zone_buffer_atr * atr_arr[i]
                tp = entry - 2.0 * (sl - entry)
                open_positions.append({"side": "SELL", "entry": entry,
                    "sl": sl, "tp": tp, "idx_open": i, "regime": regime})
                ob.status = "mitigated"   # consume the zone
                break
        else:
            for ob in active_demand:
                if bar.high >= ob.level_low and bar.low <= ob.level_high:
                    if require_cot and regime != "BULLISH_SETUP":
                        skipped_cot += 1; break
                    entry = max(bar.close, ob.level_low)
                    sl_dist = atr_sl_mult * atr_arr[i]
                    sl = ob.level_low - zone_buffer_atr * atr_arr[i]
                    tp = entry + 2.0 * (entry - sl)
                    open_positions.append({"side": "BUY", "entry": entry,
                        "sl": sl, "tp": tp, "idx_open": i, "regime": regime})
                    ob.status = "mitigated"
                    break

        equity_curve.append({"i": i, "eq": equity})

    # Force-close at end
    for pos in open_positions:
        exit_px = bv[n - 1].close
        pnl = ((exit_px - pos["entry"]) if pos["side"] == "BUY"
               else (pos["entry"] - exit_px)) * lot_value_per_unit
        equity += pnl
        trades.append({**pos, "exit": exit_px, "profit": pnl,
                       "idx_close": n - 1, "exit_reason": "EOD"})

    wins   = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] < 0]
    gw = sum(t["profit"] for t in wins)
    gl = abs(sum(t["profit"] for t in losses))
    pf = gw / gl if gl > 0 else (999.99 if gw > 0 else 0.0)
    summary = {
        "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate":      round(len(wins) / max(len(trades), 1) * 100, 1),
        "profit_factor": round(pf, 2),
        "net_pnl":       round(equity, 2),
        "avg_win":       round(np.mean([t["profit"] for t in wins]), 2)   if wins   else 0,
        "avg_loss":      round(np.mean([t["profit"] for t in losses]), 2) if losses else 0,
        "best":          round(max([t["profit"] for t in trades]), 2) if trades else 0,
        "worst":         round(min([t["profit"] for t in trades]), 2) if trades else 0,
        "skipped_by_cot": skipped_cot,
        "exit_breakdown": {
            "TP":  sum(1 for t in trades if t["exit_reason"] == "TP"),
            "SL":  sum(1 for t in trades if t["exit_reason"] == "SL"),
            "EOD": sum(1 for t in trades if t["exit_reason"] == "EOD"),
        },
    }
    return {"trades": trades, "summary": summary, "equity_curve": equity_curve,
            "active_zones_at_end": {"supply": len(active_supply),
                                     "demand": len(active_demand)}}

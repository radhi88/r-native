"""strategies/supply_zone_cot.py — Supply Zone + CFTC COT strategy.

Combines smc_engine Order Block zones with CFTC Commitments of Traders (COT)
weekly data to filter entries. Only trades OB zones when the COT sentiment
aligns with the trade direction.

COT file: Legacy futures-only format (fut86_25.txt).
  Download: https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed
  File: fut86_25.zip → fut86_25.txt

Regime logic:
  - comm_idx = (commercials_net - min) / (max - min) * 100   (rolling 52-week)
  - noncomm_idx = 100 - comm_idx   (Non-Commercials mirror)
  - BULL regime: comm_idx > 60 (commercials are net long = bullish for price)
  - BEAR regime: comm_idx < 40
  - NEUTRAL: otherwise

Entry logic (on bars):
  BUY  → bullish OB within 2×ATR below price + BULL regime
  SELL → bearish OB within 2×ATR above price + BEAR regime

Backtest entry point: backtest(bars, cot_rows, ...) → dict
"""
from __future__ import annotations

import csv
import math
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# ─── COT parsing ─────────────────────────────────────────────────

def load_cot_weekly(
    cot_path: str,
    market_name: str = "GOLD - COMMODITY EXCHANGE INC.",
) -> List[Dict[str, Any]]:
    """Parse CFTC Legacy futures-only CSV/TXT file.

    Returns list of dicts sorted ascending by date:
      {date, comm_long, comm_short, noncomm_long, noncomm_short,
       comm_net, noncomm_net, comm_idx, noncomm_idx}

    comm_idx is a 52-week percentile (0–100). Requires ≥ 2 rows to compute.
    """
    rows: List[Dict] = []
    market_name_upper = market_name.upper()

    with open(cot_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("Market_and_Exchange_Names", "").strip().upper()
            if market_name_upper not in name:
                continue
            try:
                as_of = datetime.strptime(
                    row["As_of_Date_In_Form_YYMMDD"].strip(), "%y%m%d"
                ).date()
            except (KeyError, ValueError):
                try:
                    as_of = datetime.strptime(
                        row.get("Report_Date_as_MM_DD_YYYY", "").strip(), "%m/%d/%Y"
                    ).date()
                except ValueError:
                    continue

            try:
                cl  = int(row["Comm_Positions_Long_All"].replace(",", ""))
                cs  = int(row["Comm_Positions_Short_All"].replace(",", ""))
                nl  = int(row["NonComm_Positions_Long_All"].replace(",", ""))
                ns  = int(row["NonComm_Positions_Short_All"].replace(",", ""))
            except (KeyError, ValueError):
                continue

            rows.append({
                "date": as_of,
                "comm_long": cl, "comm_short": cs,
                "noncomm_long": nl, "noncomm_short": ns,
                "comm_net": cl - cs,
                "noncomm_net": nl - ns,
                "comm_idx": 50.0,       # placeholder; filled below
                "noncomm_idx": 50.0,
            })

    rows.sort(key=lambda r: r["date"])
    _compute_indices(rows, window=52)
    return rows


def _compute_indices(rows: List[Dict], window: int = 52) -> None:
    """Fill comm_idx / noncomm_idx as a rolling percentile rank."""
    nets = [r["comm_net"] for r in rows]
    for i, r in enumerate(rows):
        start = max(0, i - window + 1)
        segment = nets[start: i + 1]
        lo, hi = min(segment), max(segment)
        rng = hi - lo
        r["comm_idx"] = round(100.0 * (r["comm_net"] - lo) / rng, 1) if rng else 50.0
        r["noncomm_idx"] = round(100.0 - r["comm_idx"], 1)


def cot_regime(
    comm_idx: float,
    noncomm_idx: float,
    bull_thresh: float = 60.0,
    bear_thresh: float = 40.0,
) -> str:
    """Return 'BULL', 'BEAR', or 'NEUTRAL' based on COT indices."""
    if comm_idx > bull_thresh:
        return "BULL"
    if comm_idx < bear_thresh:
        return "BEAR"
    return "NEUTRAL"


def _cot_at_date(rows: List[Dict], bar_date: date) -> Optional[Dict]:
    """Return most-recent COT row whose date ≤ bar_date, or None."""
    result = None
    for r in rows:
        if r["date"] <= bar_date:
            result = r
        else:
            break
    return result


# ─── SMC Order Block helpers ─────────────────────────────────────

def _find_obs_offline(bars: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Lightweight OB detector: last opposite-color candle before a strong move.

    Returns (bull_obs, bear_obs) — each element has {idx, high, low, fresh}.
    """
    n = len(bars)
    if n < 5:
        return [], []

    closes = np.array([b["close"] for b in bars])
    opens  = np.array([b["open"]  for b in bars])
    highs  = np.array([b["high"]  for b in bars])
    lows   = np.array([b["low"]   for b in bars])

    # ATR(14) for impulse threshold
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]))
    atr = np.convolve(tr, np.ones(14) / 14, mode="full")[:n]

    bull_obs, bear_obs = [], []

    for i in range(2, n - 1):
        impulse = abs(closes[i] - opens[i])
        if impulse < atr[i] * 1.5:
            continue
        # Bullish impulse → bearish OB is the last red candle before it
        if closes[i] > opens[i]:
            j = i - 1
            while j >= 0 and closes[j] >= opens[j]:
                j -= 1
            if j >= 0:
                bull_obs.append({
                    "idx": j, "high": highs[j], "low": lows[j],
                    "fresh": True, "side": "bull",
                })
        # Bearish impulse → bullish OB is the last green candle before it
        else:
            j = i - 1
            while j >= 0 and closes[j] <= opens[j]:
                j -= 1
            if j >= 0:
                bear_obs.append({
                    "idx": j, "high": highs[j], "low": lows[j],
                    "fresh": True, "side": "bear",
                })

    # Deduplicate (keep latest per unique idx)
    def dedup(obs):
        seen = {}
        for ob in obs:
            seen[ob["idx"]] = ob
        return sorted(seen.values(), key=lambda x: x["idx"])

    return dedup(bull_obs), dedup(bear_obs)


def _mark_mitigated(obs: List[Dict], bars: List[Dict]) -> None:
    """Mark OBs as not fresh if price has traded through them."""
    for ob in obs:
        start = ob["idx"] + 1
        for i in range(start, len(bars)):
            c = bars[i]["close"]
            if ob["side"] == "bull" and c < ob["low"]:
                ob["fresh"] = False
                break
            if ob["side"] == "bear" and c > ob["high"]:
                ob["fresh"] = False
                break


# ─── ATR helper ──────────────────────────────────────────────────

def _atr_at(highs, lows, closes, i, period=14) -> float:
    start = max(0, i - period + 1)
    trs = []
    for j in range(max(1, start), i + 1):
        trs.append(max(
            highs[j] - lows[j],
            abs(highs[j] - closes[j - 1]),
            abs(lows[j] - closes[j - 1]),
        ))
    return float(np.mean(trs)) if trs else 1.0


# ─── Backtest ─────────────────────────────────────────────────────

def backtest(
    bars: List[Dict[str, Any]],
    cot_rows: Optional[List[Dict]] = None,
    require_cot: bool = True,
    ob_entry_atr_dist: float = 2.0,
    atr_sl_mult: float = 2.0,
    atr_tp_mult: float = 3.0,
    lot: float = 0.01,
    bull_thresh: float = 60.0,
    bear_thresh: float = 40.0,
) -> Dict[str, Any]:
    """Backtest Supply Zone + COT strategy.

    Args:
        bars:             list of OHLC dicts.
        cot_rows:         output of load_cot_weekly(); None = skip COT filter.
        require_cot:      if True, only trade when COT regime aligns.
        ob_entry_atr_dist: max ATR distance from price to OB to trigger entry.
        atr_sl_mult:      SL = OB edge ± ATR * mult.
        atr_tp_mult:      TP = entry ± ATR * mult.
        lot, bull_thresh, bear_thresh: as expected.

    Returns dict with trades list and summary.
    """
    n = len(bars)
    if n < 20:
        return {"trades": [], "summary": _empty_summary()}

    highs  = np.array([b["high"]  for b in bars], dtype=float)
    lows   = np.array([b["low"]   for b in bars], dtype=float)
    closes = np.array([b["close"] for b in bars], dtype=float)

    bull_obs, bear_obs = _find_obs_offline(bars)
    _mark_mitigated(bull_obs, bars)
    _mark_mitigated(bear_obs, bars)

    # Index fresh OBs by their index
    fresh_bull = {ob["idx"]: ob for ob in bull_obs if ob["fresh"]}
    fresh_bear = {ob["idx"]: ob for ob in bear_obs if ob["fresh"]}

    closed_trades: List[Dict] = []
    open_trades:   List[Dict] = []

    for i in range(10, n):
        price  = closes[i]
        atr_i  = _atr_at(highs, lows, closes, i)
        b_date = _bar_to_date(bars[i])

        # COT regime at this bar's date
        regime = "NEUTRAL"
        if cot_rows:
            row = _cot_at_date(cot_rows, b_date)
            if row:
                regime = cot_regime(row["comm_idx"], row["noncomm_idx"],
                                    bull_thresh, bear_thresh)

        # ── Manage open trades ──
        still_open = []
        for t in open_trades:
            exited = False
            if t["side"] == "BUY":
                if price >= t["tp"]:
                    t.update(exit_idx=i, exit_price=t["tp"], exit_reason="TP",
                             pnl=round((t["tp"] - t["entry"]) * lot * 100, 2))
                    exited = True
                elif price <= t["sl"]:
                    t.update(exit_idx=i, exit_price=t["sl"], exit_reason="SL",
                             pnl=round((t["sl"] - t["entry"]) * lot * 100, 2))
                    exited = True
            else:  # SELL
                if price <= t["tp"]:
                    t.update(exit_idx=i, exit_price=t["tp"], exit_reason="TP",
                             pnl=round((t["entry"] - t["tp"]) * lot * 100, 2))
                    exited = True
                elif price >= t["sl"]:
                    t.update(exit_idx=i, exit_price=t["sl"], exit_reason="SL",
                             pnl=round((t["entry"] - t["sl"]) * lot * 100, 2))
                    exited = True
            if exited:
                closed_trades.append(t)
            else:
                still_open.append(t)
        open_trades = still_open

        if len(open_trades) >= 2:
            continue

        # ── BUY: bullish OB below price within ob_entry_atr_dist ──
        if not require_cot or regime == "BULL":
            for _, ob in sorted(fresh_bull.items(), key=lambda x: -x[0]):
                if ob["idx"] >= i:
                    continue
                dist = price - ob["high"]
                if 0 < dist < atr_i * ob_entry_atr_dist:
                    if not any(t["side"] == "BUY" for t in open_trades):
                        sl = ob["low"] - atr_i * atr_sl_mult
                        tp = price + atr_i * atr_tp_mult
                        open_trades.append(dict(
                            side="BUY", entry_idx=i, entry=price,
                            sl=sl, tp=tp, ob_idx=ob["idx"],
                            exit_idx=None, exit_price=None, exit_reason=None, pnl=0.0,
                        ))
                    break

        # ── SELL: bearish OB above price within ob_entry_atr_dist ──
        if not require_cot or regime == "BEAR":
            for _, ob in sorted(fresh_bear.items(), key=lambda x: -x[0]):
                if ob["idx"] >= i:
                    continue
                dist = ob["low"] - price
                if 0 < dist < atr_i * ob_entry_atr_dist:
                    if not any(t["side"] == "SELL" for t in open_trades):
                        sl = ob["high"] + atr_i * atr_sl_mult
                        tp = price - atr_i * atr_tp_mult
                        open_trades.append(dict(
                            side="SELL", entry_idx=i, entry=price,
                            sl=sl, tp=tp, ob_idx=ob["idx"],
                            exit_idx=None, exit_price=None, exit_reason=None, pnl=0.0,
                        ))
                    break

    # EOD close
    for t in open_trades:
        p = closes[-1]
        t.update(exit_idx=n - 1, exit_price=p, exit_reason="EOD")
        if t["side"] == "BUY":
            t["pnl"] = round((p - t["entry"]) * lot * 100, 2)
        else:
            t["pnl"] = round((t["entry"] - p) * lot * 100, 2)
        closed_trades.append(t)

    return {"trades": closed_trades, "summary": _summarise(closed_trades)}


def _bar_to_date(bar: Dict) -> date:
    t = bar.get("time", 0)
    if isinstance(t, (int, float)):
        return datetime.utcfromtimestamp(t).date()
    if isinstance(t, str):
        return datetime.fromisoformat(t).date()
    return date.today()


def _empty_summary() -> dict:
    return {"trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "profit_factor": 0.0, "net_pnl": 0.0}


def _summarise(trades: List[Dict]) -> dict:
    if not trades:
        return _empty_summary()
    wins   = [t for t in trades if t.get("pnl", 0) > 0]
    losses = [t for t in trades if t.get("pnl", 0) <= 0]
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss   = abs(sum(t["pnl"] for t in losses)) or 1e-9
    pf  = round(gross_profit / gross_loss, 3)
    wr  = round(100.0 * len(wins) / len(trades), 1)
    net = round(sum(t["pnl"] for t in trades), 2)
    return {
        "trades":        len(trades),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      wr,
        "profit_factor": pf,
        "net_pnl":       net,
    }

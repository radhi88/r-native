"""
lob_backtest.py — London Open Breakout backtest on 30 days XAUUSDm M5.

Strategy:
  • 08:00-08:30 UTC → mark the high and low of this 30-min range
  • 08:30 → place:
      BUY_STOP  @ range_high + buffer  (SL = range_low,  TP = +1.5× range)
      SELL_STOP @ range_low  - buffer  (SL = range_high, TP = -1.5× range)
  • Whichever triggers → other is cancelled
  • If neither triggers by 12:00 UTC → cancel both, no trade today
  • Max 1 trade/day

Tested params (default):
  • buffer = 50 pt (broker spread compensation)
  • TP multiplier = 1.5× range
  • Max hold = 6 hours after entry
  • Skip Mondays (lower volatility) and Fridays after 16:00 UTC
"""
from __future__ import annotations
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

import numpy as np
import MetaTrader5 as mt5

SYMBOL          = "XAUUSDm"
ROOT            = Path(r"C:\Users\Radhi\MT5\friday_v3")
REPORT          = ROOT / "data" / "lob_report.json"
TRADES_CSV      = ROOT / "data" / "lob_trades.csv"

DAYS_BACK       = 30
INITIAL_BALANCE = 50.0

# Strategy params (tunable)
RANGE_START_HOUR_UTC = 8         # London open
RANGE_END_HOUR_UTC   = 9         # break candle = 08:00 → 09:00 UTC range
ENTRY_END_HOUR_UTC   = 12        # cancel pendings if not filled by noon
EXIT_BY_HOUR_UTC     = 18        # force-close by 18:00 UTC

BUFFER_PT            = 50
TP_RANGE_MULTIPLIER  = 1.5
MAX_RANGE_PT         = 1000      # skip if range > 1000pt (event noise)
MIN_RANGE_PT         = 100       # skip if range < 100pt (too quiet)

LOT                  = 0.01
POINT                = 0.01
SPREAD_PT            = 300       # current XAUUSDm spread
PT_VALUE_PER_LOT     = 100       # $1/pip per 1 lot on gold


@dataclass
class LobTrade:
    date:       str
    side:       str
    range_pt:   float
    entry:      float
    exit:       float
    sl:         float
    tp:         float
    pl_usd:     float
    win:        bool
    exit_reason: str
    hours_held: float


def run_lob_backtest():
    print(f"=== LOB Backtest — {DAYS_BACK} days on {SYMBOL} M5 ===\n")
    if not mt5.initialize():
        print("MT5 init failed"); return

    from_ts = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    bars = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M5, from_ts, datetime.now(timezone.utc))
    if bars is None or len(bars) < 100:
        print("Not enough data"); mt5.shutdown(); return
    print(f"  ✓ {len(bars):,} M5 bars loaded\n")

    # Group bars by trade day (UTC)
    by_day = defaultdict(list)
    for b in bars:
        dt = datetime.fromtimestamp(int(b["time"]), tz=timezone.utc)
        by_day[dt.date().isoformat()].append((dt, b))

    trades: list[LobTrade] = []

    for day, day_bars in sorted(by_day.items()):
        # Find 08:00-09:00 UTC bars
        range_bars = [(dt, b) for dt, b in day_bars
                      if RANGE_START_HOUR_UTC <= dt.hour < RANGE_END_HOUR_UTC]
        if len(range_bars) < 6:        # need at least 6 of 12 M5 bars
            continue

        range_high = max(float(b["high"]) for _, b in range_bars)
        range_low  = min(float(b["low"])  for _, b in range_bars)
        range_pt   = (range_high - range_low) / POINT

        if range_pt > MAX_RANGE_PT or range_pt < MIN_RANGE_PT:
            continue

        # Day of week filter — skip Friday after 16:00 (US close), all Sundays
        dow = datetime.fromisoformat(day).weekday()  # Mon=0, Sun=6
        if dow == 6: continue   # Sunday

        # Bars after 09:00 = trading window
        post = [(dt, b) for dt, b in day_bars if dt.hour >= RANGE_END_HOUR_UTC]
        if not post: continue

        # Define entry levels
        buy_entry  = range_high + BUFFER_PT * POINT
        sell_entry = range_low  - BUFFER_PT * POINT
        buy_sl   = range_low - BUFFER_PT * POINT
        sell_sl  = range_high + BUFFER_PT * POINT
        buy_tp   = buy_entry  + range_pt * TP_RANGE_MULTIPLIER * POINT
        sell_tp  = sell_entry - range_pt * TP_RANGE_MULTIPLIER * POINT

        # Simulate
        triggered: dict | None = None
        for dt, b in post:
            # Check pending triggers
            if dt.hour >= ENTRY_END_HOUR_UTC:
                break
            low_now  = float(b["low"])
            high_now = float(b["high"])

            if triggered is None:
                # Check entries
                if high_now + SPREAD_PT*POINT >= buy_entry:
                    triggered = {"side": "BUY", "entry_dt": dt, "entry": buy_entry,
                                 "sl": buy_sl, "tp": buy_tp}
                elif low_now - SPREAD_PT*POINT <= sell_entry:
                    triggered = {"side": "SELL", "entry_dt": dt, "entry": sell_entry,
                                 "sl": sell_sl, "tp": sell_tp}

        if not triggered:
            continue

        # Manage position until SL/TP/EXIT
        for dt, b in post:
            if dt < triggered["entry_dt"]:
                continue
            low_now  = float(b["low"])
            high_now = float(b["high"])
            hours_held = (dt - triggered["entry_dt"]).total_seconds() / 3600

            if triggered["side"] == "BUY":
                if low_now <= triggered["sl"]:
                    pl = (triggered["sl"] - triggered["entry"]) / POINT
                    pl_usd = pl * LOT * PT_VALUE_PER_LOT / 100 - 0.30  # spread cost
                    trades.append(LobTrade(day, "BUY", range_pt, triggered["entry"],
                                            triggered["sl"], triggered["sl"], triggered["tp"],
                                            round(pl_usd, 2), False, "SL", round(hours_held, 1)))
                    break
                if high_now >= triggered["tp"]:
                    pl = (triggered["tp"] - triggered["entry"]) / POINT
                    pl_usd = pl * LOT * PT_VALUE_PER_LOT / 100 - 0.30
                    trades.append(LobTrade(day, "BUY", range_pt, triggered["entry"],
                                            triggered["tp"], triggered["sl"], triggered["tp"],
                                            round(pl_usd, 2), True, "TP", round(hours_held, 1)))
                    break
            else:
                if high_now >= triggered["sl"]:
                    pl = (triggered["entry"] - triggered["sl"]) / POINT
                    pl_usd = pl * LOT * PT_VALUE_PER_LOT / 100 - 0.30
                    trades.append(LobTrade(day, "SELL", range_pt, triggered["entry"],
                                            triggered["sl"], triggered["sl"], triggered["tp"],
                                            round(pl_usd, 2), False, "SL", round(hours_held, 1)))
                    break
                if low_now <= triggered["tp"]:
                    pl = (triggered["entry"] - triggered["tp"]) / POINT
                    pl_usd = pl * LOT * PT_VALUE_PER_LOT / 100 - 0.30
                    trades.append(LobTrade(day, "SELL", range_pt, triggered["entry"],
                                            triggered["tp"], triggered["sl"], triggered["tp"],
                                            round(pl_usd, 2), True, "TP", round(hours_held, 1)))
                    break
            if dt.hour >= EXIT_BY_HOUR_UTC:
                # Force close at current
                close_price = float(b["close"])
                if triggered["side"] == "BUY":
                    pl = (close_price - triggered["entry"]) / POINT
                else:
                    pl = (triggered["entry"] - close_price) / POINT
                pl_usd = pl * LOT * PT_VALUE_PER_LOT / 100 - 0.30
                trades.append(LobTrade(day, triggered["side"], range_pt, triggered["entry"],
                                        close_price, triggered["sl"], triggered["tp"],
                                        round(pl_usd, 2), pl_usd > 0, "EOD", round(hours_held, 1)))
                break

    mt5.shutdown()

    # ── Metrics ──
    if not trades:
        report = {"verdict": "NO_TRADES", "total_trades": 0}
    else:
        wins = [t for t in trades if t.win]
        losses = [t for t in trades if not t.win]
        net_pl = sum(t.pl_usd for t in trades)
        win_rate = len(wins) / len(trades) * 100
        gross_win = sum(t.pl_usd for t in wins)
        gross_loss = abs(sum(t.pl_usd for t in losses))
        pf = gross_win / gross_loss if gross_loss > 0 else 0
        # Drawdown
        bal = INITIAL_BALANCE
        peak = bal
        max_dd = 0
        for t in trades:
            bal += t.pl_usd
            peak = max(peak, bal)
            max_dd = max(max_dd, peak - bal)
        verdict = "PASS" if (win_rate >= 50 and pf >= 1.5 and max_dd <= INITIAL_BALANCE * 0.30) else "FAIL"
        report = {
            "ts":             datetime.utcnow().isoformat(),
            "days":           DAYS_BACK,
            "symbol":         SYMBOL,
            "strategy":       "London Open Breakout",
            "total_trades":   len(trades),
            "wins":           len(wins),
            "losses":         len(losses),
            "win_rate":       round(win_rate, 2),
            "profit_factor":  round(pf, 2),
            "net_pl":         round(net_pl, 2),
            "max_drawdown":   round(max_dd, 2),
            "avg_win":        round(gross_win / max(1, len(wins)), 4),
            "avg_loss":       round(-gross_loss / max(1, len(losses)), 4),
            "avg_hold_hours": round(np.mean([t.hours_held for t in trades]), 2),
            "exits_by_reason": {r: sum(1 for t in trades if t.exit_reason==r) for r in {"TP","SL","EOD"}},
            "verdict":        verdict,
            "criteria":       "WR>=50%, PF>=1.5, DD<=30%",
        }

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(TRADES_CSV, "w", encoding="utf-8") as f:
        f.write("date,side,range_pt,entry,exit,sl,tp,pl_usd,win,exit_reason,hours_held\n")
        for t in trades:
            f.write(f"{t.date},{t.side},{t.range_pt:.0f},{t.entry:.2f},{t.exit:.2f},"
                    f"{t.sl:.2f},{t.tp:.2f},{t.pl_usd},{int(t.win)},{t.exit_reason},{t.hours_held}\n")

    print(f"\n{'='*60}")
    print(f"  LOB RESULTS")
    print(f"{'='*60}")
    for k, v in report.items():
        print(f"  {k:18}: {v}")


if __name__ == "__main__":
    run_lob_backtest()

"""
friday_self_test.py
===================
Connects to live MT5, fetches historical M1 bars for a symbol,
replays them bar-by-bar through TradingBrain, simulates trades
with ATR-based TP/SL, and prints a detailed report.

Usage:
    python scripts/friday_self_test.py --symbol XAUUSDm --bars 300 --profile gold_precision
    python scripts/friday_self_test.py --symbol XAUUSDm --bars 500 --profile gold
"""

import argparse
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# ── bootstrap ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import bootstrap
bootstrap()

import numpy as np
import pandas as pd

from mt5_ai.market_structure import add_market_structure
from mt5_ai.ai_brain import TradingBrain
from mt5_ai.strategy_profiles import get_profile

# ── params ────────────────────────────────────────────────────────────────────
TP_ATR_MULT  = 2.5   # TP = entry ± ATR * mult  (ICT: target next liquidity)
SL_ATR_MULT  = 1.2   # SL = entry ∓ ATR * mult  (below/above swept level)
MIN_BARS_CTX = 80    # bars needed for SMC context before we start checking

# ─────────────────────────────────────────────────────────────────────────────

def fetch_bars(mt5, symbol: str, n: int) -> pd.DataFrame:
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, n)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No bars returned for {symbol}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.rename(columns={"open": "Open", "high": "High",
                        "low": "Low", "close": "Close",
                        "tick_volume": "Volume"}, inplace=True)
    return df


def run_self_test(symbol: str, bars: int, profile_name: str):
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("MetaTrader5 package not installed.")
        return

    print(f"\n=== FRIDAY SELF-TEST ===")
    print(f"Symbol  : {symbol}")
    print(f"Bars    : {bars}")
    print(f"Profile : {profile_name}")
    print(f"Time    : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC\n")

    if not mt5.initialize():
        print(f"MT5 connect failed: {mt5.last_error()}")
        return

    try:
        df_full = fetch_bars(mt5, symbol, bars)
    except RuntimeError as e:
        print(e)
        mt5.shutdown()
        return

    mt5.shutdown()

    profile = get_profile(profile_name)
    brain   = TradingBrain(model=None, profile_name=profile_name)

    # ── point size ────────────────────────────────────────────────────────────
    price_ref = float(df_full["Close"].iloc[-1])
    if price_ref > 100:
        point = 0.01   # Gold / indices
    elif price_ref > 10:
        point = 0.001
    else:
        point = 0.00001

    trades  = []
    skipped = 0
    in_trade = None   # dict: side, entry, sl, tp, bar_open, atr, reason

    for i in range(MIN_BARS_CTX, len(df_full)):
        window = df_full.iloc[: i + 1].copy()

        try:
            enriched = add_market_structure(window)
        except Exception:
            skipped += 1
            continue

        atr = float(enriched["atr"].iloc[-1]) if "atr" in enriched.columns else price_ref * 0.0003
        if atr <= 0:
            atr = price_ref * 0.0003

        # ── check if open trade hits TP or SL ──────────────────────────────
        if in_trade is not None:
            bar_high = float(df_full["High"].iloc[i])
            bar_low  = float(df_full["Low"].iloc[i])
            close    = float(df_full["Close"].iloc[i])
            t = in_trade

            hit_tp = hit_sl = False
            if t["side"] == "BUY":
                if bar_high >= t["tp"]:
                    hit_tp = True
                elif bar_low <= t["sl"]:
                    hit_sl = True
            else:
                if bar_low <= t["tp"]:
                    hit_tp = True
                elif bar_high >= t["sl"]:
                    hit_sl = True

            if hit_tp or hit_sl:
                exit_price = t["tp"] if hit_tp else t["sl"]
                if t["side"] == "BUY":
                    pts = (exit_price - t["entry"]) / point
                else:
                    pts = (t["entry"] - exit_price) / point
                trades.append({
                    "bar_in":    t["bar_open"],
                    "bar_out":   i,
                    "side":      t["side"],
                    "entry":     t["entry"],
                    "exit":      exit_price,
                    "sl":        t["sl"],
                    "tp":        t["tp"],
                    "result":    "TP" if hit_tp else "SL",
                    "points":    round(pts, 1),
                    "reason":    t["reason"],
                    "time_in":   str(df_full["time"].iloc[t["bar_open"]]),
                    "time_out":  str(df_full["time"].iloc[i]),
                })
                in_trade = None

        # ── skip if already in a trade ─────────────────────────────────────
        if in_trade is not None:
            continue

        # ── ask brain for decision ─────────────────────────────────────────
        try:
            decision = brain.decide(df=enriched, probability=None)
        except Exception:
            skipped += 1
            continue

        if decision.action not in ("BUY", "SELL"):
            continue

        price = float(enriched["Close"].iloc[-1])
        if decision.action == "BUY":
            sl = price - atr * SL_ATR_MULT
            tp = price + atr * TP_ATR_MULT
        else:
            sl = price + atr * SL_ATR_MULT
            tp = price - atr * TP_ATR_MULT

        in_trade = {
            "side":     decision.action,
            "entry":    price,
            "sl":       sl,
            "tp":       tp,
            "bar_open": i,
            "atr":      atr,
            "reason":   decision.reason,
        }

    # ── close any still-open trade at last bar ────────────────────────────
    if in_trade is not None:
        last_close = float(df_full["Close"].iloc[-1])
        t = in_trade
        if t["side"] == "BUY":
            pts = (last_close - t["entry"]) / point
        else:
            pts = (t["entry"] - last_close) / point
        trades.append({
            "bar_in":   t["bar_open"],
            "bar_out":  len(df_full) - 1,
            "side":     t["side"],
            "entry":    t["entry"],
            "exit":     last_close,
            "sl":       t["sl"],
            "tp":       t["tp"],
            "result":   "OPEN",
            "points":   round(pts, 1),
            "reason":   t["reason"],
            "time_in":  str(df_full["time"].iloc[t["bar_open"]]),
            "time_out": "still open",
        })

    # ── report ────────────────────────────────────────────────────────────
    if not trades:
        print("No trades triggered in this window.")
        print(f"Bars skipped (error): {skipped}")
        return

    wins  = [t for t in trades if t["result"] == "TP"]
    loss  = [t for t in trades if t["result"] == "SL"]
    total_pts = sum(t["points"] for t in trades)
    wr    = len(wins) / len(trades) * 100 if trades else 0

    print(f"{'Bar':>4}  {'Time':19}  {'Side':4}  {'Entry':9}  {'Exit':9}  {'Pts':>7}  Res    Reason")
    print("-" * 90)
    for t in trades:
        bar_str  = f"{t['bar_in']:>4}"
        time_str = str(t["time_in"])[:19]
        pts_str  = f"{t['points']:+7.1f}"
        res_col  = "  WIN" if t["result"] == "TP" else ("  SL " if t["result"] == "SL" else " OPEN")
        print(f"{bar_str}  {time_str}  {t['side']:4}  {t['entry']:9.3f}  {t['exit']:9.3f}  {pts_str}  {res_col}  {t['reason']}")

    print("-" * 90)
    print(f"\nTotal trades : {len(trades)}  ({len(wins)} wins / {len(loss)} losses)")
    print(f"Win rate     : {wr:.1f}%")
    print(f"Total pts    : {total_pts:+.1f}")
    print(f"Avg pts/trade: {total_pts/len(trades):+.1f}")
    print(f"Bars skipped : {skipped}")
    print(f"\nProfile      : {profile_name}")
    print(f"  buy_threshold     = {profile.buy_threshold}")
    print(f"  sell_threshold    = {profile.sell_threshold}")
    print(f"  min_context_score = {profile.min_context_score}")
    print(f"  min_smc_score     = {profile.min_smc_score}")


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Friday self-test — bar-by-bar replay")
    ap.add_argument("--symbol",  default="XAUUSDm",       help="MT5 symbol")
    ap.add_argument("--bars",    type=int, default=300,   help="Historical bars to replay")
    ap.add_argument("--profile", default="gold_precision", help="Strategy profile name")
    args = ap.parse_args()
    run_self_test(args.symbol, args.bars, args.profile)

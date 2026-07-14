"""
Live paper trader — executes model decisions as tracked paper positions.

Connects to MT5 for live bars, runs the model every poll, opens/closes
paper positions with ATR-based TP/SL, and records results to LearningJournal.
No real orders are ever sent.

Usage:
    python live_paper_trader.py --profile sk --poll-seconds 15
    python live_paper_trader.py --profile sb --once
"""
import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import tensorflow as tf

from _bootstrap import bootstrap

bootstrap()

from mt5_ai.ai_brain import TradingBrain
from mt5_ai.config import (
    FEATURE_COLUMNS,
    LOG_DIR,
    MODEL_PATH,
    MT5_SYMBOL,
    SCALER_PATH,
    SEQ_LEN,
)
from mt5_ai.learning_journal import LearningJournal
from mt5_ai.market_structure import add_market_structure


TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
}

# R:R = 2:1  (TP = 2× ATR in price, SL = 1× ATR in price)
TP_ATR_MULT = 2.0
SL_ATR_MULT = 1.0
MAX_HOLD_BARS = 30  # close by time after this many polls regardless


# ─── Paper position ────────────────────────────────────────────────────────────

@dataclass
class PaperPosition:
    symbol: str
    side: str          # "BUY" or "SELL"
    entry: float
    tp: float
    sl: float
    strategy: str
    probability: float
    smc_buy_score: float
    smc_sell_score: float
    atr_price: float   # ATR in price units at entry
    opened_at: str
    bars_held: int = 0

    def check(self, current_price):
        """Returns 'tp', 'sl', 'time', or None."""
        if self.side == "BUY":
            if current_price >= self.tp:
                return "tp"
            if current_price <= self.sl:
                return "sl"
        else:
            if current_price <= self.tp:
                return "tp"
            if current_price >= self.sl:
                return "sl"
        if self.bars_held >= MAX_HOLD_BARS:
            return "time"
        return None

    def points(self, exit_price):
        if self.side == "BUY":
            return exit_price - self.entry
        return self.entry - exit_price


# ─── MT5 helpers ───────────────────────────────────────────────────────────────

def init_mt5(symbol):
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise SystemExit(f"MT5 init failed: {mt5.last_error()}")
    if not mt5.symbol_select(symbol, True):
        mt5.shutdown()
        raise SystemExit(f"Failed to select {symbol}: {mt5.last_error()}")
    return mt5


def fetch_rates(mt5, symbol, timeframe_name, bars):
    timeframe = getattr(mt5, TIMEFRAME_MAP[timeframe_name])
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No MT5 rates returned: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df.sort_values("time").reset_index(drop=True)


def make_sequence(df, scaler):
    enriched = add_market_structure(df)
    seq = enriched[FEATURE_COLUMNS].tail(SEQ_LEN).to_numpy(dtype=np.float32)
    if len(seq) < SEQ_LEN:
        raise RuntimeError(f"Need {SEQ_LEN} bars, got {len(seq)}")
    seq = scaler.transform(seq)
    return seq.reshape(1, SEQ_LEN, len(FEATURE_COLUMNS)), enriched


# ─── Position manager ──────────────────────────────────────────────────────────

class PaperTracker:
    def __init__(self, journal: LearningJournal, log_path):
        self.journal = journal
        self.log_path = log_path
        self.positions: list[PaperPosition] = []
        self.closed: list[dict] = []

    def has_position(self, symbol):
        return any(p.symbol == symbol for p in self.positions)

    def open(self, symbol, side, entry, atr_ratio, strategy, probability,
             smc_buy, smc_sell):
        atr_price = atr_ratio * entry
        if side == "BUY":
            tp = entry + TP_ATR_MULT * atr_price
            sl = entry - SL_ATR_MULT * atr_price
        else:
            tp = entry - TP_ATR_MULT * atr_price
            sl = entry + SL_ATR_MULT * atr_price

        pos = PaperPosition(
            symbol=symbol,
            side=side,
            entry=entry,
            tp=tp,
            sl=sl,
            strategy=strategy,
            probability=probability,
            smc_buy_score=smc_buy,
            smc_sell_score=smc_sell,
            atr_price=atr_price,
            opened_at=datetime.now(timezone.utc).isoformat(),
        )
        self.positions.append(pos)
        self._log("OPEN", {**asdict(pos), "tp_pts": round(tp - entry if side == "BUY" else entry - tp, 4)})
        print(f"  → OPEN  {side:4s} {symbol}  entry={entry:.4f}  "
              f"TP={tp:.4f}  SL={sl:.4f}  ATR={atr_price:.4f}")

    def update(self, symbol, current_price):
        for pos in list(self.positions):
            if pos.symbol != symbol:
                continue
            pos.bars_held += 1
            reason = pos.check(current_price)
            if reason:
                self._close(pos, current_price, reason)

    def _close(self, pos, exit_price, reason):
        pts = pos.points(exit_price)
        won = pts > 0
        record = {
            **asdict(pos),
            "exit": exit_price,
            "points": round(pts, 4),
            "won": won,
            "close_reason": reason,
            "closed_at": datetime.now(timezone.utc).isoformat(),
        }
        self.positions = [p for p in self.positions if p is not pos]
        self.closed.append(record)

        self.journal.remember_trade(
            strategy=pos.strategy,
            side=pos.side,
            probability=pos.probability,
            smc_buy_score=pos.smc_buy_score,
            smc_sell_score=pos.smc_sell_score,
            entry_price=pos.entry,
            exit_price=exit_price,
            points=pts,
            signal_type="strict_signal",
        )
        self._log("CLOSE", record)

        icon = "✓" if won else "✗"
        print(f"  → CLOSE {icon}  {pos.side:4s} {pos.symbol}  "
              f"entry={pos.entry:.4f}  exit={exit_price:.4f}  "
              f"pts={pts:+.4f}  [{reason}]")

    def _log(self, event, payload):
        line = json.dumps({"event": event, **payload}, default=str)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def print_summary(self):
        total = len(self.closed)
        if total == 0:
            print("  No closed trades yet.")
            return
        wins = sum(1 for r in self.closed if r["won"])
        pts = sum(r["points"] for r in self.closed)
        print(f"  Summary: {total} trades | {wins/total*100:.1f}% win | {pts:+.2f} pts total")


# ─── Main loop ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol",      default=MT5_SYMBOL)
    parser.add_argument("--timeframe",   choices=sorted(TIMEFRAME_MAP), default="M1")
    parser.add_argument("--profile",     default="sk")
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--bars",        type=int, default=400)
    parser.add_argument("--once",        action="store_true",
                        help="Run one analysis cycle and exit (no position tracking)")
    args = parser.parse_args()

    mt5 = init_mt5(args.symbol)
    model = tf.keras.models.load_model(MODEL_PATH, compile=False)
    scaler = joblib.load(SCALER_PATH)
    brain = TradingBrain(model=model, profile_name=args.profile)
    journal = LearningJournal()
    tracker = PaperTracker(journal=journal,
                           log_path=LOG_DIR / "live_paper_trades.jsonl")
    decision_log = LOG_DIR / "live_paper_decisions.jsonl"

    print("=" * 60)
    print(f"  FRIDAY Live Paper Trader")
    print(f"  Symbol:   {args.symbol}  |  TF: {args.timeframe}")
    print(f"  Profile:  {args.profile}")
    print(f"  TP mult:  {TP_ATR_MULT}× ATR  |  SL mult: {SL_ATR_MULT}× ATR")
    print(f"  Max hold: {MAX_HOLD_BARS} bars")
    print(f"  Trades log: {tracker.log_path}")
    print("  No real orders. Paper only.")
    print("=" * 60)

    try:
        poll = 0
        while True:
            poll += 1
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")

            try:
                df = fetch_rates(mt5, args.symbol, args.timeframe, args.bars)
                sequence, enriched = make_sequence(df, scaler)
            except RuntimeError as e:
                print(f"[{now}] Data error: {e}")
                time.sleep(args.poll_seconds)
                continue

            current_price = float(df["close"].iloc[-1])
            spread = float(df["spread"].iloc[-1]) if "spread" in df.columns else None
            atr_ratio = float(enriched["atr"].iloc[-1])

            # Update open positions first
            tracker.update(args.symbol, current_price)

            # Analyze
            decision = brain.decide(
                df=enriched,
                sequence=sequence,
                spread=spread,
            )
            d = decision.to_dict()
            d.update({
                "timestamp": now,
                "symbol": args.symbol,
                "timeframe": args.timeframe,
                "close": current_price,
                "poll": poll,
            })

            # Log decision
            with open(decision_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(d, default=str) + "\n")

            action = d["action"]
            ctx = d.get("context_score", 0)
            print(f"[{now}] poll={poll:4d}  price={current_price:.4f}  "
                  f"prob={d['probability']:.3f}  smc_bias={d['smc_bias']:+.0f}  "
                  f"ctx={ctx}  → {action}  ({d['reason']})")

            # Open position if signal and no existing position for this symbol
            if action in ("BUY", "SELL") and not tracker.has_position(args.symbol):
                tracker.open(
                    symbol=args.symbol,
                    side=action,
                    entry=current_price,
                    atr_ratio=atr_ratio,
                    strategy=d["strategy"],
                    probability=d["probability"],
                    smc_buy=d["smc_buy_score"],
                    smc_sell=d["smc_sell_score"],
                )

            # Print summary every 20 polls
            if poll % 20 == 0:
                tracker.print_summary()

            if args.once:
                break

            time.sleep(args.poll_seconds)

    except KeyboardInterrupt:
        print("\n" + "=" * 60)
        print("  Stopped by user.")
        tracker.print_summary()
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()

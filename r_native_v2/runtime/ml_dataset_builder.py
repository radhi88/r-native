"""runtime/ml_dataset_builder.py — Build the ML training dataset.

Born 2026-05-28 as foundation for Phase 5.C (ONNX classifier).

WHAT IT DOES:
  1. Read every trade from trading.db
  2. For each trade, find the closest brain_snapshot (by timestamp)
  3. Extract a feature vector from that snapshot
  4. Label by trade outcome (1=WIN, 0=LOSS)
  5. Save as CSV + parquet for sklearn/PyTorch training

TWO DATASETS PRODUCED:
  • user_trades.csv  — only manual trades (the high-WR human signal)
  • all_trades.csv   — every trade by every engine

FEATURES (snapshot at entry time):
  bias_m1, bias_m5, bias_m15, bias_h1     (categorical: BULL/BEAR/FLAT)
  rsi_m1, rsi_m5                          (numeric)
  atr_m1, atr_h1                          (numeric)
  mtf_align                               (categorical: 3/3, 2/3, MIXED)
  pressure_10m1                           (numeric, -∞..+∞)
  session                                 (categorical)
  regime                                  (categorical)
  side_BUY                                (0/1 — the action taken)

LABEL:
  win = 1 if pnl > 0 else 0

USAGE:
    python -m runtime.ml_dataset_builder
"""
from __future__ import annotations
import csv
from pathlib import Path
from typing import Optional

from runtime.shared.db import db
from runtime.shared.tokens import PATHS

OUT_DIR = PATHS["brain_decisions"].parent / "ml"

FEATURES = [
    "bias_m1", "bias_m5", "bias_m15", "bias_h1",
    "rsi_m1", "rsi_m5", "atr_m1", "atr_h1",
    "mtf_align", "pressure_10m1", "session", "regime",
    "side_BUY",
]


def build_dataset(only_manual: bool = False) -> tuple[list[dict], dict]:
    """Returns (rows, stats)."""
    # Pull every trade with a non-null PnL
    where = "pnl IS NOT NULL"
    if only_manual:
        where += " AND magic = 0"
    trades = db.query(f"""
        SELECT ts, magic, source, symbol, side, pnl, entry, ticket
        FROM trades
        WHERE {where}
        ORDER BY ts
    """)

    # Bulk-load all snapshots into memory (small dataset)
    snaps = db.query("SELECT * FROM brain_snapshots ORDER BY ts")
    if not snaps:
        return [], {"error": "no brain_snapshots", "trades_seen": len(trades)}

    snap_ts = [s["ts"] for s in snaps]

    out = []
    no_match = 0
    for t in trades:
        # Find snapshot with closest ts (binary search would be faster; this is fine for <2k rows)
        ts = t["ts"]
        # Pick latest snap_ts <= t.ts (lookback only — no peeking at future)
        candidate = None
        for s in snaps:
            if s["ts"] <= ts:
                candidate = s
            else:
                break
        if candidate is None:
            no_match += 1; continue

        row = {f: candidate[f] for f in FEATURES if f in candidate.keys()}
        row["side_BUY"] = 1 if t["side"] == "BUY" else 0
        row["pressure_10m1"] = candidate["pressure_10m1"] or 0
        row["mtf_align"] = candidate["mtf_align"] or "?"
        row["session"]   = candidate["session"]   or "?"
        row["regime"]    = candidate["regime"]    or "?"
        for k in ["bias_m1", "bias_m5", "bias_m15", "bias_h1"]:
            row[k] = candidate[k] or "FLAT"
        for k in ["rsi_m1", "rsi_m5", "atr_m1", "atr_h1"]:
            row[k] = candidate[k] or 0
        row["__pnl"]   = t["pnl"]
        row["__win"]   = 1 if t["pnl"] > 0 else 0
        row["__magic"] = t["magic"]
        row["__source"] = t["source"]
        row["__ticket"] = t["ticket"]
        row["__ts"]    = t["ts"]
        out.append(row)

    wins = sum(1 for r in out if r["__win"] == 1)
    stats = {
        "trades_seen": len(trades),
        "samples_built": len(out),
        "wins": wins,
        "losses": len(out) - wins,
        "win_rate": round(wins / len(out) * 100, 1) if out else 0,
        "unmatched_snapshots": no_match,
    }
    return out, stats


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows: return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["__ts", "__source", "__magic", "__ticket", "__win", "__pnl"] + FEATURES
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    print("═══ ML DATASET BUILDER ═══")
    print()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1] Building dataset: USER MANUAL TRADES ONLY")
    user_rows, user_stats = build_dataset(only_manual=True)
    write_csv(user_rows, OUT_DIR / "user_trades.csv")
    for k, v in user_stats.items():
        print(f"     {k:22s}: {v}")
    print(f"     → {OUT_DIR / 'user_trades.csv'}")
    print()

    print("[2] Building dataset: ALL ENGINES (bots + user)")
    all_rows, all_stats = build_dataset(only_manual=False)
    write_csv(all_rows, OUT_DIR / "all_trades.csv")
    for k, v in all_stats.items():
        print(f"     {k:22s}: {v}")
    print(f"     → {OUT_DIR / 'all_trades.csv'}")
    print()

    if user_rows:
        print("═══ FEATURE DISTRIBUTION (USER TRADES) ═══")
        # Win rate by session
        from collections import defaultdict, Counter
        by_session = defaultdict(lambda: {"w": 0, "l": 0})
        for r in user_rows:
            by_session[r["session"]]["w" if r["__win"] else "l"] += 1
        print("\n  By session:")
        for sess, d in sorted(by_session.items()):
            total = d["w"] + d["l"]
            wr = d["w"] / total * 100 if total else 0
            print(f"     {sess:14s}  {total:>3d}T  WR {wr:>4.1f}%")

        by_regime = defaultdict(lambda: {"w": 0, "l": 0})
        for r in user_rows:
            by_regime[r["regime"]]["w" if r["__win"] else "l"] += 1
        print("\n  By regime:")
        for reg, d in sorted(by_regime.items()):
            total = d["w"] + d["l"]
            wr = d["w"] / total * 100 if total else 0
            print(f"     {reg:14s}  {total:>3d}T  WR {wr:>4.1f}%")

        by_side = defaultdict(lambda: {"w": 0, "l": 0})
        for r in user_rows:
            side = "BUY" if r["side_BUY"] else "SELL"
            by_side[side]["w" if r["__win"] else "l"] += 1
        print("\n  By side:")
        for s, d in sorted(by_side.items()):
            total = d["w"] + d["l"]
            wr = d["w"] / total * 100 if total else 0
            print(f"     {s:14s}  {total:>3d}T  WR {wr:>4.1f}%")

    print()
    print("Next: `python -m runtime.ml_trainer` to train sklearn → ONNX")


if __name__ == "__main__":
    main()

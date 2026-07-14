"""
EA Monitor field-completeness assertion harness.

Plain assert/__main__ script (no pytest dependency required). Exits 0 on success,
non-zero on any failed assertion. Runs with MetaTrader5/anthropic ABSENT
(ea_monitor.py guards those imports), proving /data always emits every UI-SPEC
CurrentState and Candle field on every emission path.

Run:  python tests/test_ea_monitor_fields.py
"""

import os
import sys

# ea_monitor.py lives at the repo root (one level up from tests/).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import ea_monitor  # noqa: E402

# ── UI-SPEC field contracts ───────────────────────────────────────────
SPEC_CURRENT_KEYS = [
    "bar", "time", "balance", "equity", "peak_balance", "open_pnl", "positions",
    "lot_factor", "grid_factor", "win_streak", "loss_streak",
    "dna_gap", "dna_tp", "dna_sl", "dna_gen", "cooldown",
    "open", "high", "low", "close",
]

SPEC_CANDLE_KEYS = [
    "open", "high", "low", "close",
    "atr_points", "sig", "trend", "rsi", "adx", "macd_hist", "mfi",
    "vol_pct", "spread_points", "dch_pos", "demand", "supply",
    "entry_score", "avoid_score",
]

SPEC_TOPLEVEL_KEYS = ["connected", "current", "candles", "metrics", "suggestions", "dna_memory"]
SPEC_DNA_KEYS = ["count", "best", "records"]


def check(condition, message):
    if not condition:
        print(f"FAIL: {message}")
        sys.exit(1)


def main():
    # 1. normalize_current({}) must contain EVERY spec CurrentState key.
    cur = ea_monitor.normalize_current({})
    for key in SPEC_CURRENT_KEYS:
        check(key in cur, f"normalize_current() missing CurrentState key '{key}'")

    # 2. Drive the disconnected/empty candle path via normalize_history_rows.
    synthetic_rows = [{"o": 1, "h": 2, "l": 0.5, "c": 1.5} for _ in range(3)]
    candles = ea_monitor.normalize_history_rows(synthetic_rows, {})
    check(len(candles) == 3, f"expected 3 synthetic candles, got {len(candles)}")
    ea_monitor.state["candles"] = candles

    payload = ea_monitor.public_payload()

    # 3. Every emitted candle must carry the spec Candle keys.
    for idx, candle in enumerate(payload["candles"]):
        for key in SPEC_CANDLE_KEYS:
            check(key in candle, f"candle[{idx}] missing Candle key '{key}'")

    # 4. Top-level EAData shape + dna_memory shape.
    for key in SPEC_TOPLEVEL_KEYS:
        check(key in payload, f"public_payload() missing top-level key '{key}'")
    dna = payload["dna_memory"]
    for key in SPEC_DNA_KEYS:
        check(key in dna, f"dna_memory missing key '{key}'")

    # 5. inject_best_dna() returns a dict (ok False acceptable when memory empty).
    result = ea_monitor.inject_best_dna()
    check(isinstance(result, dict), "inject_best_dna() did not return a dict")
    check("ok" in result, "inject_best_dna() result missing 'ok' key")

    print("ALL EA MONITOR FIELD CHECKS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()

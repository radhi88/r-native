# -*- coding: utf-8 -*-
r"""
Build_MT5_Tester_Profile_CSV.py

يحوّل agent_profiles.json الناتج من تدريب Python إلى ملف CSV يقرأه EA داخل MT5 Strategy Tester.

المخرجات:
    agent_profiles_mql5.csv

المكان:
    MetaTrader 5 Common Files folder:
    C:\Users\<USER>\AppData\Roaming\MetaQuotes\Terminal\Common\Files

التشغيل:
    cd C:\Users\Radhi\MT5
    .\.venv\Scripts\python.exe Build_MT5_Tester_Profile_CSV.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

try:
    import MetaTrader5 as mt5
except Exception as exc:
    raise SystemExit("Install MetaTrader5 first: pip install MetaTrader5") from exc


PROFILE_JSON = "agent_profiles.json"
OUT_CSV_NAME = "agent_profiles_mql5.csv"

# If True: exports only enabled=true symbols.
# If False: exports all profiles but keeps enabled flag in CSV.
ONLY_ENABLED = True


def connect_mt5() -> None:
    if not mt5.initialize():
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")

    info = mt5.terminal_info()
    if info is None:
        raise SystemExit("MT5 terminal_info unavailable.")

    print(f"[MT5] data_path={info.data_path}")
    print(f"[MT5] commondata_path={info.commondata_path}")


def common_files_dir() -> Path:
    info = mt5.terminal_info()
    if info is None:
        raise SystemExit("MT5 terminal_info unavailable.")

    p = Path(info.commondata_path) / "Files"
    p.mkdir(parents=True, exist_ok=True)
    return p


def main() -> int:
    connect_mt5()

    src = Path(PROFILE_JSON)
    if not src.exists():
        raise SystemExit(f"Missing {PROFILE_JSON}. Run Train_Agentic_Grid_Backtest_v2.py first.")

    data = json.loads(src.read_text(encoding="utf-8"))
    profiles = data.get("profiles", {})
    if not profiles:
        raise SystemExit("No profiles found in agent_profiles.json")

    out_path = common_files_dir() / OUT_CSV_NAME

    rows = []
    for symbol, prof in profiles.items():
        enabled = bool(prof.get("enabled", False))
        if ONLY_ENABLED and not enabled:
            continue

        params = prof.get("params", {}) or {}

        rows.append({
            "symbol": symbol,
            "enabled": 1 if enabled else 0,
            "magic": int(prof.get("magic", 0) or 0),
            "asset_class": str(prof.get("asset_class", "")),
            "base_lot": float(prof.get("base_lot", 0.01) or 0.01),
            "atr_grid_multiplier": float(params.get("atr_grid_multiplier", 0.22)),
            "atr_trailing_multiplier": float(params.get("atr_trailing_multiplier", 0.12)),
            "spread_grid_multiplier": float(params.get("spread_grid_multiplier", 3.0)),
            "stop_loss_atr_multiplier": float(params.get("stop_loss_atr_multiplier", 6.0)),
            "take_profit_atr_multiplier": float(params.get("take_profit_atr_multiplier", 6.0)),
            "max_spread_to_atr_ratio": float(params.get("max_spread_to_atr_ratio", 0.35)),
        })

    if not rows:
        raise SystemExit("No enabled profiles to export.")

    fieldnames = [
        "symbol",
        "enabled",
        "magic",
        "asset_class",
        "base_lot",
        "atr_grid_multiplier",
        "atr_trailing_multiplier",
        "spread_grid_multiplier",
        "stop_loss_atr_multiplier",
        "take_profit_atr_multiplier",
        "max_spread_to_atr_ratio",
    ]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print("[OK] Exported MT5 tester profiles:")
    print(out_path)
    print("[SYMBOLS]", ", ".join([r["symbol"] for r in rows]))

    mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

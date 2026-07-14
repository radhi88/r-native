"""tools/export_mt5_bars.py — Export MT5 bars to JSON for offline backtesting.

Usage:
    python tools/export_mt5_bars.py --symbol XAUUSDm --bars 8000
    python tools/export_mt5_bars.py --symbol XAUUSDm --bars 8000 --tf M3 --out data/gold_m3_live.json

Output JSON schema:
    {
      "symbol": "XAUUSDm",
      "timeframe": "M3",
      "bars": 8000,
      "span": {"from": "...", "to": "..."},
      "broker": "...",
      "contract": 100.0,
      "bars": [{"time": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}, ...]
    }
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))


TF_MAP = {
    "M1":  1,  "M3":  3,  "M5":  5,  "M15": 15,
    "M30": 30, "H1":  60, "H4":  240, "D1":  1440,
}


def _tf_const(tf_str: str):
    """Convert TF string to MT5 TIMEFRAME_* constant."""
    import MetaTrader5 as mt5
    mapping = {
        "M1":  mt5.TIMEFRAME_M1,  "M3":  mt5.TIMEFRAME_M3,  "M5":  mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30, "H1":  mt5.TIMEFRAME_H1,
        "H4":  mt5.TIMEFRAME_H4,  "D1":  mt5.TIMEFRAME_D1,
    }
    key = tf_str.upper()
    if key not in mapping:
        raise ValueError(f"Unknown timeframe '{tf_str}'. Valid: {list(mapping)}")
    return mapping[key]


def export_bars(symbol: str, tf_str: str = "M3", bars_back: int = 8000, out_path: str = "") -> dict:
    import MetaTrader5 as mt5

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")

    tf = _tf_const(tf_str)
    raw = mt5.copy_rates_from_pos(symbol, tf, 0, bars_back)
    if raw is None or len(raw) == 0:
        mt5.shutdown()
        raise RuntimeError(f"copy_rates_from_pos({symbol}, {tf_str}, {bars_back}) returned nothing. "
                           f"Error: {mt5.last_error()}")

    bars = [
        {
            "time":   int(r["time"]),
            "open":   float(r["open"]),
            "high":   float(r["high"]),
            "low":    float(r["low"]),
            "close":  float(r["close"]),
            "volume": int(r["tick_volume"]),
        }
        for r in raw
    ]

    info = mt5.symbol_info(symbol)
    broker   = mt5.account_info().company if mt5.account_info() else "unknown"
    contract = float(info.trade_contract_size) if info else 100.0

    mt5.shutdown()

    span_from = datetime.utcfromtimestamp(bars[0]["time"]).strftime("%Y-%m-%d %H:%M")
    span_to   = datetime.utcfromtimestamp(bars[-1]["time"]).strftime("%Y-%m-%d %H:%M")

    payload = {
        "symbol":    symbol,
        "timeframe": tf_str.upper(),
        "bars":      len(bars),
        "span":      {"from": span_from, "to": span_to},
        "broker":    broker,
        "contract":  contract,
        "bars_data": bars,
    }

    if not out_path:
        data_dir = HERE / "data"
        data_dir.mkdir(exist_ok=True)
        out_path = str(data_dir / f"gold_{tf_str.lower()}_live.json")

    Path(out_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"✓ wrote {out_path}")
    print(f"  bars: {len(bars)}  span: {span_from} -> {span_to}")
    print(f"  broker: {broker}  contract: {contract}")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Export MT5 bars to JSON")
    parser.add_argument("--symbol", default="XAUUSDm")
    parser.add_argument("--tf",     default="M3")
    parser.add_argument("--bars",   type=int, default=8000)
    parser.add_argument("--out",    default="")
    args = parser.parse_args()
    export_bars(args.symbol, args.tf, args.bars, args.out)


if __name__ == "__main__":
    main()

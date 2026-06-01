"""Export real M3 gold bars from YOUR MT5 to a JSON file for backtesting.

Run this ONCE on your Windows machine where MT5 is installed. The output
JSON is small (a few hundred KB), commit it to the repo so the sandbox
can run the actual backtest on real data.

    pip install MetaTrader5
    python tools/export_mt5_bars.py
    git add data/gold_m3_live.json && git commit -m "data: gold M3 export" && git push

Then ping me — I'll run the backtest on these real bars and send the PNG.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def fetch_and_export(symbol: str, n_bars: int, out_path: Path) -> dict:
    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise SystemExit("MetaTrader5 not installed. Run:  pip install MetaTrader5")

    if not mt5.initialize():
        raise SystemExit(f"MT5 init failed: {mt5.last_error()}\n"
                         "Make sure MT5 terminal is running and you're logged in.")

    # Resolve symbol — try common broker suffix variants
    info = mt5.symbol_info(symbol)
    if info is None:
        for variant in (symbol + "m", symbol + ".raw", symbol[:-1] if symbol.endswith("m") else symbol):
            if mt5.symbol_info(variant) is not None:
                symbol = variant; info = mt5.symbol_info(symbol); break
    if info is None:
        raise SystemExit(f"Symbol {symbol} not found in MT5 Market Watch.\n"
                         "Right-click Market Watch -> Show All, then re-run.")
    if not info.visible:
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)

    # Pull M1 then resample to M3 (MT5 has no native M3 timeframe)
    n_m1 = n_bars * 3 + 30
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, n_m1)
    if rates is None or len(rates) < 100:
        raise SystemExit(f"insufficient M1 bars  rates={None if rates is None else len(rates)}")

    m3 = []
    block = []
    for r in rates:
        block.append(r)
        # 3-minute boundaries — close when this is the 3rd minute (epoch//60 % 3 == 2)
        if (int(r["time"]) // 60) % 3 == 2 and block:
            m3.append({
                "time":  int(block[0]["time"]),
                "open":  float(block[0]["open"]),
                "high":  float(max(b["high"] for b in block)),
                "low":   float(min(b["low"]  for b in block)),
                "close": float(block[-1]["close"]),
                "volume": int(sum(int(b["tick_volume"]) for b in block)),
            })
            block = []
    if not m3:
        # Boundary alignment failed — just chunk in groups of 3
        for i in range(0, len(rates) - 2, 3):
            ch = rates[i:i+3]
            m3.append({
                "time":  int(ch[0]["time"]),
                "open":  float(ch[0]["open"]),
                "high":  float(max(b["high"] for b in ch)),
                "low":   float(min(b["low"]  for b in ch)),
                "close": float(ch[-1]["close"]),
                "volume": int(sum(int(b["tick_volume"]) for b in ch)),
            })
    m3 = m3[-n_bars:]

    # Account context (useful for the backtest's lot economics)
    acct = mt5.account_info()
    payload = {
        "symbol":       symbol,
        "tf":           "M3",
        "fetched_at":   datetime.now(timezone.utc).isoformat(),
        "broker":       acct.company if acct else None,
        "account_ccy":  acct.currency if acct else None,
        "contract_sz":  float(info.trade_contract_size),
        "tick_size":    float(info.trade_tick_size),
        "tick_value":   float(info.trade_tick_value),
        "point":        float(info.point),
        "digits":       int(info.digits),
        "first_bar_iso": datetime.fromtimestamp(m3[0]["time"], timezone.utc).isoformat(),
        "last_bar_iso":  datetime.fromtimestamp(m3[-1]["time"], timezone.utc).isoformat(),
        "n_bars":       len(m3),
        "price_min":    min(b["low"]  for b in m3),
        "price_max":    max(b["high"] for b in m3),
        "bars":         m3,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ wrote {out_path}")
    print(f"  symbol:     {payload['symbol']}")
    print(f"  bars:       {payload['n_bars']}  (M3, resampled from M1)")
    print(f"  span:       {payload['first_bar_iso']}  ->  {payload['last_bar_iso']}")
    print(f"  price:      {payload['price_min']:.2f}  ->  {payload['price_max']:.2f}")
    print(f"  broker:     {payload['broker']}  ({payload['account_ccy']})")
    print(f"  contract:   {payload['contract_sz']}  (so 0.01 lot ≈ "
          f"${0.01 * payload['contract_sz']}/price unit)")
    print(f"  file size:  {out_path.stat().st_size / 1024:.1f} KB")
    return payload


def main():
    ap = argparse.ArgumentParser(description="Export gold M3 bars from MT5 to JSON")
    ap.add_argument("--symbol", default="XAUUSDm", help="Symbol on your broker (try XAUUSD if XAUUSDm fails)")
    ap.add_argument("--bars",   type=int, default=4000, help="How many M3 bars to export")
    ap.add_argument("--out",    default="data/gold_m3_live.json", help="Output JSON path (relative to repo)")
    args = ap.parse_args()

    out = Path(args.out)
    if not out.is_absolute():
        # Relative to repo root (so it works whether run from repo or from tools/)
        out = Path(__file__).resolve().parent.parent / out
    print(f"Pulling {args.bars} M3 bars of {args.symbol} from MT5 -> {out}")
    fetch_and_export(args.symbol, args.bars, out)


if __name__ == "__main__":
    main()

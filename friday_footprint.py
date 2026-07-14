"""
friday_footprint.py — Footprint / Volume Profile engine for XAUUSDm

Uses MT5 tick data to reconstruct:
  • Per-bar price-level tick counts (footprint cells)
  • Buy vs Sell ticks (classified by ask/bid movement)
  • Delta (buy - sell) per bar
  • POC (Point of Control) — price level with most ticks
  • Imbalances (any cell where buy:sell ≥ 3:1)
  • Cumulative Delta line

Output: friday_footprint.json (read by dashboard)
Run every ~5 seconds.
"""
from __future__ import annotations
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import MetaTrader5 as mt5

ROOT       = Path(r"C:\Users\Radhi\MT5")
OUTPUT     = ROOT / "friday_footprint.json"
SYMBOL     = "XAUUSDm"
TICK_SIZE  = 0.10        # group ticks into 0.10$ bins (10 pips for gold)
BARS_BACK  = 30          # how many M1 bars to analyze
UPDATE_S   = 2           # write JSON every N seconds (real-time)


def classify_tick(curr_bid: float, curr_ask: float,
                  prev_bid: float, prev_ask: float, flags: int) -> str:
    """Return 'BUY' if aggressive buy, 'SELL' if aggressive sell, else 'NEUTRAL'.

    Logic:
      - If MT5 marked the tick with TICK_FLAG_BUY  (0x20) → BUY
      - If marked TICK_FLAG_SELL (0x40) → SELL
      - Otherwise infer from ask/bid movement:
        - ask went up → BUY pressure
        - bid went down → SELL pressure
        - both moved → use last vs midpoint
    """
    if flags & 0x20: return "BUY"
    if flags & 0x40: return "SELL"

    if curr_ask > prev_ask and curr_bid >= prev_bid: return "BUY"
    if curr_bid < prev_bid and curr_ask <= prev_ask: return "SELL"

    # Both sides moved: use direction of midpoint
    prev_mid = (prev_bid + prev_ask) / 2
    curr_mid = (curr_bid + curr_ask) / 2
    if curr_mid > prev_mid: return "BUY"
    if curr_mid < prev_mid: return "SELL"
    return "NEUTRAL"


def bin_price(price: float) -> float:
    """Round price to TICK_SIZE bin."""
    return round(round(price / TICK_SIZE) * TICK_SIZE, 2)


def _cell_factory():
    return {"buy": 0, "sell": 0, "total": 0,
            "vol_lots": 0.0, "buy_lots": 0.0, "sell_lots": 0.0,
            "vol_usd": 0.0,  "buy_usd": 0.0,  "sell_usd": 0.0}


def build_footprint() -> dict:
    if not mt5.initialize():
        return {"error": "mt5 init failed"}

    # Contract size for USD value calculation
    si = mt5.symbol_info(SYMBOL)
    contract_size = float(si.trade_contract_size) if si else 100.0
    # volume data is real only if broker provides it (Exness OTC may not)
    vol_is_real = False

    # Get bars
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, BARS_BACK + 1)
    if rates is None or len(rates) < 2:
        mt5.shutdown()
        return {"error": "no bars"}

    # Get ticks covering all bars
    from_ts = datetime.fromtimestamp(int(rates[0]["time"]))
    ticks = mt5.copy_ticks_from(SYMBOL, from_ts, 200_000, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) < 5:
        mt5.shutdown()
        return {"error": "no ticks", "from": from_ts.isoformat()}

    # Check if broker provides real tick volume
    sample_vol = float(ticks["volume_real"][min(10, len(ticks)-1)])
    if sample_vol > 0:
        vol_is_real = True

    # Pre-compute previous bid/ask for direction classification
    bars_out = []

    # Tick classification (need previous tick context)
    prev_bid = ticks[0]["bid"]
    prev_ask = ticks[0]["ask"]
    classifications = ["NEUTRAL"]
    for i in range(1, len(ticks)):
        t = ticks[i]
        cls = classify_tick(t["bid"], t["ask"], prev_bid, prev_ask, int(t["flags"]))
        classifications.append(cls)
        prev_bid = t["bid"]
        prev_ask = t["ask"]

    cum_delta = 0
    cum_delta_series = []
    cum_vol_usd = 0.0

    # Process each bar
    for bi in range(len(rates)):
        bar = rates[bi]
        bar_start = int(bar["time"])
        bar_end   = int(rates[bi+1]["time"]) if bi + 1 < len(rates) else (bar_start + 60)

        # Tick mask for this bar
        mask = (ticks["time"] >= bar_start) & (ticks["time"] < bar_end)
        bar_ticks = ticks[mask]
        bar_class = [classifications[i] for i in np.where(mask)[0]]

        if len(bar_ticks) == 0:
            bars_out.append({
                "time":     datetime.fromtimestamp(bar_start).strftime("%H:%M"),
                "ts":       bar_start,
                "o": float(bar["open"]),  "h": float(bar["high"]),
                "l": float(bar["low"]),   "c": float(bar["close"]),
                "tick_count": 0, "buy_count": 0, "sell_count": 0,
                "delta": 0, "cum_delta": cum_delta, "poc": None,
                "vol_usd": 0.0, "buy_usd": 0.0, "sell_usd": 0.0,
                "imbalances": [], "cells": [],
            })
            cum_delta_series.append(cum_delta)
            continue

        # Build price-level bins with dollar volume
        cells: dict = defaultdict(_cell_factory)
        for j in range(len(bar_ticks)):
            t = bar_ticks[j]
            mid_price = (float(t["bid"]) + float(t["ask"])) / 2.0
            price_level = bin_price(mid_price)
            cls = bar_class[j]

            # Lot volume: prefer volume_real, fall back to volume
            lot_vol = float(t["volume_real"])
            if lot_vol == 0.0:
                lot_vol = float(t["volume"])
            usd_val = lot_vol * mid_price * contract_size

            cells[price_level]["total"] += 1
            cells[price_level]["vol_lots"] += lot_vol
            cells[price_level]["vol_usd"]  += usd_val

            if cls == "BUY":
                cells[price_level]["buy"]      += 1
                cells[price_level]["buy_lots"] += lot_vol
                cells[price_level]["buy_usd"]  += usd_val
            elif cls == "SELL":
                cells[price_level]["sell"]      += 1
                cells[price_level]["sell_lots"] += lot_vol
                cells[price_level]["sell_usd"]  += usd_val

        buy_total  = sum(c["buy"]  for c in cells.values())
        sell_total = sum(c["sell"] for c in cells.values())
        bar_vol_usd = sum(c["vol_usd"] for c in cells.values())
        bar_buy_usd = sum(c["buy_usd"] for c in cells.values())
        bar_sell_usd = sum(c["sell_usd"] for c in cells.values())
        delta = buy_total - sell_total
        cum_delta += delta
        cum_vol_usd += bar_vol_usd

        # POC — price with most ticks
        poc_price = max(cells.keys(), key=lambda p: cells[p]["total"]) if cells else None

        # Imbalances: cells where ratio ≥ 3:1 either way
        imbalances = []
        for price, c in cells.items():
            if c["buy"] >= 3 and c["sell"] >= 1 and c["buy"] / c["sell"] >= 3:
                imbalances.append({"price": price, "side": "BUY", "ratio": round(c["buy"]/c["sell"], 1)})
            elif c["sell"] >= 3 and c["buy"] >= 1 and c["sell"] / c["buy"] >= 3:
                imbalances.append({"price": price, "side": "SELL", "ratio": round(c["sell"]/c["buy"], 1)})
            elif c["buy"] >= 3 and c["sell"] == 0:
                imbalances.append({"price": price, "side": "BUY", "ratio": 99})
            elif c["sell"] >= 3 and c["buy"] == 0:
                imbalances.append({"price": price, "side": "SELL", "ratio": 99})

        # Sorted cells (top → bottom by price)
        sorted_cells = sorted(cells.items(), key=lambda kv: -kv[0])
        cells_out = [{
            "price":     p,
            "buy":       int(c["buy"]),
            "sell":      int(c["sell"]),
            "total":     int(c["total"]),
            "delta":     int(c["buy"] - c["sell"]),
            "vol_lots":  round(c["vol_lots"], 4),
            "buy_lots":  round(c["buy_lots"], 4),
            "sell_lots": round(c["sell_lots"], 4),
            "vol_usd":   round(c["vol_usd"], 2),
            "buy_usd":   round(c["buy_usd"], 2),
            "sell_usd":  round(c["sell_usd"], 2),
        } for p, c in sorted_cells]

        bars_out.append({
            "time":     datetime.fromtimestamp(bar_start).strftime("%H:%M"),
            "ts":       bar_start,
            "o": float(bar["open"]),  "h": float(bar["high"]),
            "l": float(bar["low"]),   "c": float(bar["close"]),
            "tick_count":  int(len(bar_ticks)),
            "buy_count":   int(buy_total),
            "sell_count":  int(sell_total),
            "delta":       int(delta),
            "cum_delta":   int(cum_delta),
            "vol_usd":     round(bar_vol_usd, 2),
            "buy_usd":     round(bar_buy_usd, 2),
            "sell_usd":    round(bar_sell_usd, 2),
            "poc":         poc_price,
            "imbalances":  imbalances,
            "cells":       cells_out,
        })
        cum_delta_series.append(cum_delta)

    # Aggregate volume profile across all bars (Volume Profile / TPO)
    profile: dict = defaultdict(lambda: {"buy": 0, "sell": 0,
                                          "vol_usd": 0.0, "buy_usd": 0.0, "sell_usd": 0.0})
    for bar in bars_out:
        for cell in bar["cells"]:
            profile[cell["price"]]["buy"]      += cell["buy"]
            profile[cell["price"]]["sell"]     += cell["sell"]
            profile[cell["price"]]["vol_usd"]  += cell["vol_usd"]
            profile[cell["price"]]["buy_usd"]  += cell["buy_usd"]
            profile[cell["price"]]["sell_usd"] += cell["sell_usd"]

    profile_sorted = sorted(profile.items(), key=lambda kv: -kv[0])
    volume_profile = [{
        "price":    p,
        "buy":      v["buy"],
        "sell":     v["sell"],
        "total":    v["buy"] + v["sell"],
        "delta":    v["buy"] - v["sell"],
        "vol_usd":  round(v["vol_usd"], 2),
        "buy_usd":  round(v["buy_usd"], 2),
        "sell_usd": round(v["sell_usd"], 2),
    } for p, v in profile_sorted]

    # Session POC (price with most total activity)
    if volume_profile:
        session_poc = max(volume_profile, key=lambda x: x["total"])["price"]
        # Value Area: 70% of volume around POC
        total_activity = sum(x["total"] for x in volume_profile)
        target = total_activity * 0.7
        # Sort by total desc, accumulate until 70%
        by_activity = sorted(volume_profile, key=lambda x: -x["total"])
        accumulated = 0
        va_prices = []
        for x in by_activity:
            accumulated += x["total"]
            va_prices.append(x["price"])
            if accumulated >= target: break
        vah = max(va_prices)  # Value Area High
        val = min(va_prices)  # Value Area Low
    else:
        session_poc = vah = val = None

    mt5.shutdown()

    return {
        "ts":            datetime.now().isoformat(),
        "symbol":        SYMBOL,
        "tick_size":     TICK_SIZE,
        "bars_back":     BARS_BACK,
        "contract_size": contract_size,
        "vol_is_real":   vol_is_real,
        "cum_vol_usd":   round(cum_vol_usd, 2),
        "bars":          bars_out,
        "volume_profile":   volume_profile,
        "session_poc":      session_poc,
        "vah":              vah,
        "val":              val,
        "cum_delta_series": cum_delta_series,
        "total_ticks":      int(len(ticks)),
    }


def main():
    print("═══ FRIDAY Footprint Engine ═══")
    print(f"  Symbol: {SYMBOL}")
    print(f"  Tick bin: ${TICK_SIZE}")
    print(f"  Bars: {BARS_BACK}")
    print(f"  Output: {OUTPUT.name} (every {UPDATE_S}s)\n")

    while True:
        try:
            data = build_footprint()
            OUTPUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            if "error" not in data:
                last_bar = data["bars"][-1] if data["bars"] else None
                if last_bar:
                    delta = last_bar["delta"]
                    sign = "+" if delta > 0 else ""
                    vol_tag = f"${last_bar['vol_usd']:,.0f}" if last_bar["vol_usd"] > 0 else f"{last_bar['tick_count']}t"
                    real_tag = "real" if data.get("vol_is_real") else "est"
                    print(f"[{datetime.now():%H:%M:%S}] bars={len(data['bars'])} "
                          f"ticks={data['total_ticks']} "
                          f"vol={vol_tag}({real_tag}) Δ{sign}{delta} "
                          f"POC={last_bar['poc']}  sess_POC={data['session_poc']}")
            else:
                print(f"[{datetime.now():%H:%M:%S}] {data.get('error')}")
        except Exception as e:
            print(f"[{datetime.now():%H:%M:%S}] ERROR: {e}")
            import traceback; traceback.print_exc()
        time.sleep(UPDATE_S)


if __name__ == "__main__":
    main()

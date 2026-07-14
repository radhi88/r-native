"""
cache_lab_data.py — Reusable bar-data cache for lab/backtest agents.

MT5 is single-terminal: concurrent mt5.initialize() calls from multiple
backtest agents contend on the one terminal. To avoid that, this script
fetches all bar data ONCE (sequentially, single MT5 session) and writes it
to data/lab_cache/ as .npz arrays + per-symbol meta JSON. Downstream agents
then read the cache (np.load / json) and never touch MetaTrader5.

Run:  ./.venv/Scripts/python.exe cache_lab_data.py
"""
import os
import json
import time

import numpy as np
import MetaTrader5 as mt5

# --- config -----------------------------------------------------------------
SYMBOLS = [
    "XAUUSDm", "XAGUSDm", "BTCUSDm", "ETHUSDm", "SOLUSDm",
    "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm", "USDCADm",
    "NZDUSDm", "USDCHFm", "EURJPYm", "GBPJPYm", "EURGBPm",
    "US30m", "USTECm", "US500m", "DE30m", "JP225m",
    "USOILm", "EURAUDm", "GBPAUDm", "AUDJPYm", "CADJPYm",
    "XAUEURm", "BTCJPYm", "NZDJPYm",
]

# (timeframe constant, label, bar count)
TIMEFRAMES = [
    (mt5.TIMEFRAME_M5, "M5", 40000),
    (mt5.TIMEFRAME_M15, "M15", 30000),
    (mt5.TIMEFRAME_H1, "H1", 20000),
]

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "data", "lab_cache")


def init_mt5():
    """initialize() with one retry."""
    if mt5.initialize():
        return True
    print(f"  mt5.initialize() failed (attempt 1): {mt5.last_error()} — retrying...")
    time.sleep(2.0)
    if mt5.initialize():
        return True
    print(f"  mt5.initialize() failed (attempt 2): {mt5.last_error()}")
    return False


def main():
    os.makedirs(CACHE_DIR, exist_ok=True)
    print(f"Cache dir: {CACHE_DIR}")

    if not init_mt5():
        print("FATAL: could not initialize MetaTrader5. Nothing cached.")
        return

    written = []   # list of (filename, bars)
    skipped = []   # list of (label, reason)
    cached = []    # list of (filename, reason) — already on disk, left untouched

    for symbol in SYMBOLS:
        # ensure symbol is selected/visible so copy_rates works
        if not mt5.symbol_select(symbol, True):
            print(f"[{symbol}] symbol_select failed: {mt5.last_error()} — continuing anyway")

        # ---- meta json (cost-correct backtests later) ----
        meta_path = os.path.join(CACHE_DIR, f"{symbol}_meta.json")
        if os.path.exists(meta_path):
            print(f"[{symbol}] meta already cached -> {os.path.basename(meta_path)} (skip)")
            cached.append((f"{symbol}_meta.json", "exists"))
        else:
            info = mt5.symbol_info(symbol)
            if info is None:
                print(f"[{symbol}] symbol_info is None: {mt5.last_error()} — skipping meta")
                skipped.append((f"{symbol}_meta", "symbol_info None"))
            else:
                meta = {
                    "symbol": symbol,
                    "trade_tick_value": float(info.trade_tick_value),
                    "trade_tick_size": float(info.trade_tick_size),
                    "tick_size": float(info.trade_tick_size),
                    "point": float(info.point),
                    "volume_min": float(info.volume_min),
                    "volume_step": float(info.volume_step),
                }
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
                print(f"[{symbol}] meta -> {os.path.basename(meta_path)} "
                      f"(tick_value={meta['trade_tick_value']}, "
                      f"tick_size={meta['tick_size']}, point={meta['point']}, "
                      f"vol_min={meta['volume_min']}, vol_step={meta['volume_step']})")

        # ---- bars per timeframe ----
        for tf_const, tf_label, n in TIMEFRAMES:
            out_path = os.path.join(CACHE_DIR, f"{symbol}_{tf_label}.npz")
            if os.path.exists(out_path):
                print(f"[{symbol} {tf_label}] already cached -> {os.path.basename(out_path)} (skip)")
                cached.append((f"{symbol}_{tf_label}.npz", "exists"))
                continue

            rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, n)
            if rates is None or len(rates) == 0:
                reason = "None" if rates is None else "empty"
                print(f"[{symbol} {tf_label}] copy_rates_from_pos returned {reason}: "
                      f"{mt5.last_error()} — noted, continuing")
                skipped.append((f"{symbol}_{tf_label}", reason))
                continue

            t = rates["time"].astype(np.int64)
            o = rates["open"].astype(np.float64)
            h = rates["high"].astype(np.float64)
            l = rates["low"].astype(np.float64)
            c = rates["close"].astype(np.float64)
            v = rates["tick_volume"].astype(np.float64)

            np.savez(out_path, t=t, o=o, h=h, l=l, c=c, v=v)
            bars = len(t)
            written.append((f"{symbol}_{tf_label}.npz", bars))
            print(f"[{symbol} {tf_label}] saved {bars} bars -> {os.path.basename(out_path)}")

    mt5.shutdown()

    print("\n===== SUMMARY =====")
    print(f"npz files written: {len(written)}")
    for fn, bars in written:
        print(f"  {fn}: {bars} bars")
    if cached:
        print(f"already cached (left untouched): {len(cached)}")
        for fn, reason in cached:
            print(f"  {fn}: {reason}")
    if skipped:
        print(f"skipped/empty: {len(skipped)}")
        for label, reason in skipped:
            print(f"  {label}: {reason}")

    return written, skipped, cached


if __name__ == "__main__":
    main()

"""Stub MetaTrader5 for Linux smoke-testing: serves synthetic OHLC bars."""
import numpy as np

TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_M30 = 1, 5, 15, 30
TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1 = 60, 240, 1440

class _SymInfo:
    point = 0.01
    digits = 2
    trade_tick_value = 1.0
    trade_tick_size = 0.01
    volume_min = 0.01
    volume_step = 0.01
    trade_contract_size = 1.0
    spread = 20
    name = "BTCUSDm"

class _Tick:
    bid = 50000.0
    ask = 50002.0

def initialize(*a, **k): return True
def shutdown(): return True
def symbol_info(symbol): return _SymInfo()
def symbol_info_tick(symbol): return _Tick()
def last_error(): return (0, "ok")

def copy_rates_from_pos(symbol, tf, start, count):
    rng = np.random.default_rng(42)
    dt = np.dtype([("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
                   ("close", "f8"), ("tick_volume", "i8"), ("spread", "i4"),
                   ("real_volume", "i8")])
    bars = np.zeros(count, dtype=dt)
    # random walk with drift + regime shifts so genes have something to chew on
    steps = rng.normal(0, 50, count) + np.sin(np.arange(count) / 60) * 8
    close = 50000 + np.cumsum(steps)
    close = np.maximum(close, 1000)
    opn = np.roll(close, 1); opn[0] = close[0]
    spread_hl = np.abs(rng.normal(0, 30, count))
    bars["time"] = np.arange(count) * 300 + 1_760_000_000
    bars["open"] = opn
    bars["close"] = close
    bars["high"] = np.maximum(opn, close) + spread_hl
    bars["low"] = np.minimum(opn, close) - spread_hl
    bars["tick_volume"] = rng.integers(100, 5000, count)
    bars["spread"] = 20
    return bars

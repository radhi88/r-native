"""
algory_backtest.py
------------------
Vectorized backtester for Algory-style genomes on all MT5 timeframes.

Architecture mirrors Algory's 12 parallel Engine.exe workers:
  - multiprocessing.Pool with up to 12 workers
  - pandas/numpy vectorized signal computation (via algory_signal_engine)
  - Supports M1 M5 M15 M30 H1 H2 H4 D1 with bar counts tuned per TF
  - Returns BacktestResult that populates AlgoryGenome.record_trade()

Bar counts per TF (approximate 3 years of data):
  M1  → 500 000 bars   M5  → 130 000   M15 → 45 000
  M30 → 23 000         H1  → 12 000    H2  → 6 000
  H4  → 3 000          D1  → 800
"""

from __future__ import annotations

import multiprocessing as mp
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .algory_dna import AlgoryGenome, CAMPAIGN_SETTINGS
from .algory_signal_engine import compute_signals

# ─────────────────────────────────────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────────────────────────────────────

WORKERS: int = min(12, max(1, mp.cpu_count() - 1))

TF_BAR_COUNTS: dict[str, int] = {
    "M1":  500_000,
    "M5":  130_000,
    "M15":  45_000,
    "M30":  23_000,
    "H1":   12_000,
    "H2":    6_000,
    "H4":    3_000,
    "D1":      800,
}

SPREAD_PIPS: dict[str, float] = {
    "EURUSD": 0.6, "GBPUSD": 0.8, "USDJPY": 0.5, "USDCHF": 0.8,
    "AUDUSD": 0.7, "USDCAD": 0.9, "NZDUSD": 1.0, "XAUUSD": 3.0,
    "EURUSDm": 0.6, "GBPUSDm": 0.8, "USDJPYm": 0.5,
}
DEFAULT_SPREAD_PIPS = 1.0

PIP_VALUE: dict[str, float] = {
    "EURUSD": 10.0, "GBPUSD": 10.0, "USDJPY": 9.1, "USDCHF": 10.9,
    "AUDUSD": 10.0, "USDCAD": 7.5,  "NZDUSD": 10.0, "XAUUSD": 1.0,
    "EURUSDm": 1.0, "GBPUSDm": 1.0, "USDJPYm": 1.0,
}
DEFAULT_PIP_VALUE = 10.0

# ─────────────────────────────────────────────────────────────────────────────
#  Result container
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    genome_id:       str
    symbol:          str
    timeframe:       str
    trades:          int   = 0
    wins:            int   = 0
    total_pnl:       float = 0.0
    win_pnl:         float = 0.0
    loss_pnl:        float = 0.0
    max_dd_pct:      float = 0.0
    equity_curve:    list[float] = field(default_factory=list)
    trade_log:       list[dict]  = field(default_factory=list)
    elapsed_sec:     float = 0.0
    error:           str   = ""

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        if self.loss_pnl <= 0:
            return 1.0 if self.win_pnl > 0 else 0.0
        return self.win_pnl / abs(self.loss_pnl)

    @property
    def total_return_pct(self) -> float:
        return (self.total_pnl / CAMPAIGN_SETTINGS["balance"]) * 100.0

    def apply_to_genome(self, genome: AlgoryGenome) -> None:
        genome.trades      = self.trades
        genome.wins        = self.wins
        genome.total_pnl   = self.total_pnl
        genome.win_pnl     = self.win_pnl
        genome.loss_pnl    = self.loss_pnl
        genome.max_dd_pct  = self.max_dd_pct
        genome.equity_curve = self.equity_curve
        genome.trade_log   = self.trade_log


# ─────────────────────────────────────────────────────────────────────────────
#  Data provider (MT5 or cache)
# ─────────────────────────────────────────────────────────────────────────────

def _get_mt5_data(symbol: str, timeframe: str, n_bars: int) -> pd.DataFrame | None:
    """Fetch OHLCV from MT5. Returns None if MT5 not available."""
    try:
        import MetaTrader5 as mt5
        TF_MAP = {
            "M1": mt5.TIMEFRAME_M1,  "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,  "H2": mt5.TIMEFRAME_H2,
            "H4": mt5.TIMEFRAME_H4,  "D1": mt5.TIMEFRAME_D1,
        }
        tf = TF_MAP.get(timeframe)
        if tf is None:
            return None
        if not mt5.initialize():
            return None
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, n_bars)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "tick_volume": "Volume"}, inplace=True)
        return df.set_index("time")
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  Core simulation
# ─────────────────────────────────────────────────────────────────────────────

def _simulate(
    df: pd.DataFrame,
    signals_df: pd.DataFrame,
    genome: AlgoryGenome,
    symbol: str,
    timeframe: str,
) -> BacktestResult:
    """Event-driven trade simulation over pre-computed signals."""
    result = BacktestResult(genome_id=genome.id, symbol=symbol, timeframe=timeframe)

    balance  = CAMPAIGN_SETTINGS["balance"]
    risk_pct = genome.risk_pct / 100.0

    spread_pip  = SPREAD_PIPS.get(symbol, DEFAULT_SPREAD_PIPS)
    pip_val     = PIP_VALUE.get(symbol, DEFAULT_PIP_VALUE)
    spread_pts  = spread_pip * 0.0001 if "JPY" not in symbol else spread_pip * 0.01

    # R4/R2: cap equity at 1000× starting balance to prevent ERANGE overflow
    EQUITY_CAP = balance * 1_000.0

    equity       = balance
    peak_equity  = balance
    in_trade     = False
    entry_px     = 0.0
    sl_px        = 0.0
    tp_px        = 0.0
    direction    = 0  # 1=long -1=short
    entry_bar    = 0

    n = len(signals_df)
    for i in range(1, n):
        row = signals_df.iloc[i]
        bar = df.iloc[i]

        hi  = float(bar["High"])
        lo  = float(bar["Low"])
        cls = float(bar["Close"])

        if in_trade:
            exit_reason = ""
            pnl = 0.0

            if direction == 1:
                if lo <= sl_px:
                    pnl         = (sl_px - entry_px - spread_pts) * (equity * risk_pct / abs(entry_px - sl_px))
                    exit_reason = "SL"
                elif hi >= tp_px:
                    pnl         = (tp_px - entry_px - spread_pts) * (equity * risk_pct / abs(entry_px - sl_px))
                    exit_reason = "TP"
            else:
                if hi >= sl_px:
                    pnl         = (entry_px - sl_px - spread_pts) * (equity * risk_pct / abs(entry_px - sl_px))
                    exit_reason = "SL"
                elif lo <= tp_px:
                    pnl         = (entry_px - tp_px - spread_pts) * (equity * risk_pct / abs(entry_px - sl_px))
                    exit_reason = "TP"

            # Friday EOD close
            if not exit_reason and genome.use_eod_close:
                ts = signals_df.index[i]
                if hasattr(ts, "weekday") and ts.weekday() == 4 and ts.hour >= genome.friday_close:
                    pnl         = ((cls - entry_px) if direction == 1 else (entry_px - cls)) * (equity * risk_pct / abs(entry_px - sl_px + 1e-12))
                    pnl        -= spread_pts * equity * risk_pct / abs(entry_px - sl_px + 1e-12)
                    exit_reason = "FRIDAY"

            if exit_reason:
                equity += pnl
                equity = min(equity, EQUITY_CAP)   # R4: cap to prevent overflow
                peak_equity = max(peak_equity, equity)
                dd_pct = (peak_equity - equity) / peak_equity * 100.0 if peak_equity > 0 else 0.0
                result.max_dd_pct = max(result.max_dd_pct, dd_pct)

                won = pnl > 0
                result.trades += 1
                if won:
                    result.wins    += 1
                    result.win_pnl += abs(pnl)
                else:
                    result.loss_pnl += abs(pnl)
                result.total_pnl += pnl
                result.equity_curve.append(round(equity, 2))
                result.trade_log.append({
                    "t": result.trades, "bar": i, "dir": direction,
                    "entry": round(entry_px, 6), "exit": round(sl_px if exit_reason == "SL" else tp_px if exit_reason == "TP" else cls, 6),
                    "pnl": round(pnl, 4),
                    "pnl_pct": round(pnl / CAMPAIGN_SETTINGS["balance"] * 100.0, 6),
                    "reason": exit_reason,
                })
                in_trade = False

        if not in_trade and row.get("filter_ok", False):
            ed = int(row.get("entry_dir", 0))
            if ed != 0:
                sl  = float(row.get("sl",  0.0))
                tp  = float(row.get("tp",  0.0))
                epx = float(row.get("entry_px", cls))
                if sl > 0 and tp > 0 and abs(epx - sl) > 1e-8:
                    entry_px  = epx + (spread_pts if ed == 1 else -spread_pts)
                    sl_px     = sl
                    tp_px     = tp
                    direction = ed
                    entry_bar = i
                    in_trade  = True

    # trim for storage
    result.equity_curve = result.equity_curve[-16_000:]
    result.trade_log    = result.trade_log[-2_000:]
    return result


# ─────────────────────────────────────────────────────────────────────────────
#  Worker function (runs in subprocess)
# ─────────────────────────────────────────────────────────────────────────────

def _worker(args: tuple) -> BacktestResult:
    genome_dict, symbol, timeframe, n_bars, df_records = args
    t0 = time.perf_counter()
    try:
        genome = AlgoryGenome.from_dict(genome_dict)

        if df_records is not None:
            df = pd.DataFrame.from_records(df_records)
            if "time" in df.columns:
                df["time"] = pd.to_datetime(df["time"])
                df = df.set_index("time")
        else:
            df = _get_mt5_data(symbol, timeframe, n_bars)
            if df is None or len(df) < 100:
                r = BacktestResult(genome_id=genome.id, symbol=symbol, timeframe=timeframe)
                r.error = "no_data"
                return r

        signals = compute_signals(df, genome)
        result  = _simulate(df, signals, genome, symbol, timeframe)
        result.elapsed_sec = round(time.perf_counter() - t0, 3)
        return result
    except OverflowError as e:
        # R4: ERANGE — fitness overflow, genome is degenerate
        try:
            from .core.numeric_safety import reject_erange
            reject_erange(source=f"{symbol}|{timeframe}", details=str(e))
        except ImportError:
            pass
        r = BacktestResult(genome_id=genome_dict.get("id", "?"), symbol=symbol, timeframe=timeframe)
        r.error = f"ERANGE:{e}"
        r.elapsed_sec = round(time.perf_counter() - t0, 3)
        return r
    except Exception as e:
        r = BacktestResult(genome_id=genome_dict.get("id", "?"), symbol=symbol, timeframe=timeframe)
        r.error = str(e)
        r.elapsed_sec = round(time.perf_counter() - t0, 3)
        return r


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────

def backtest_genome(
    genome: AlgoryGenome,
    symbol: str,
    timeframe: str,
    df: pd.DataFrame | None = None,
) -> BacktestResult:
    """Backtest a single genome synchronously (no subprocess overhead)."""
    n_bars = TF_BAR_COUNTS.get(timeframe, 12_000)
    t0     = time.perf_counter()
    try:
        if df is None:
            df = _get_mt5_data(symbol, timeframe, n_bars)
        if df is None or len(df) < 100:
            r = BacktestResult(genome_id=genome.id, symbol=symbol, timeframe=timeframe)
            r.error = "no_data"
            return r
        signals = compute_signals(df, genome)
        result  = _simulate(df, signals, genome, symbol, timeframe)
        result.elapsed_sec = round(time.perf_counter() - t0, 3)
        return result
    except Exception as e:
        r = BacktestResult(genome_id=genome.id, symbol=symbol, timeframe=timeframe)
        r.error = str(e)
        r.elapsed_sec = round(time.perf_counter() - t0, 3)
        return r


def backtest_population(
    population: list[AlgoryGenome],
    symbol: str,
    timeframe: str,
    df: pd.DataFrame | None = None,
    workers: int = WORKERS,
) -> list[BacktestResult]:
    """
    Backtest an entire population in parallel (up to 12 workers).
    Mirrors Algory's 12 × Engine.exe multiprocessing architecture.
    """
    n_bars  = TF_BAR_COUNTS.get(timeframe, 12_000)
    records = None

    if df is None:
        df = _get_mt5_data(symbol, timeframe, n_bars)

    if df is not None:
        df_reset  = df.reset_index()
        if "time" in df_reset.columns:
            df_reset["time"] = df_reset["time"].astype(str)
        records = df_reset.to_dict("records")

    args = [
        (g.to_dict(), symbol, timeframe, n_bars, records)
        for g in population
    ]

    if workers <= 1 or len(population) <= 4:
        return [_worker(a) for a in args]

    with mp.Pool(processes=workers) as pool:
        return pool.map(_worker, args)


def backtest_multi_timeframe(
    genome: AlgoryGenome,
    symbol: str,
    timeframes: list[str] | None = None,
    workers: int = WORKERS,
) -> dict[str, BacktestResult]:
    """
    Run one genome across multiple timeframes in parallel.
    Returns {timeframe: BacktestResult}.
    """
    if timeframes is None:
        timeframes = list(TF_BAR_COUNTS.keys())

    args = [
        (genome.to_dict(), symbol, tf, TF_BAR_COUNTS.get(tf, 12_000), None)
        for tf in timeframes
    ]

    if workers <= 1:
        results = [_worker(a) for a in args]
    else:
        with mp.Pool(processes=min(workers, len(timeframes))) as pool:
            results = pool.map(_worker, args)

    return {tf: r for tf, r in zip(timeframes, results)}


def backtest_multi_symbol_tf(
    genome: AlgoryGenome,
    symbol_tf_pairs: list[tuple[str, str]],
    workers: int = WORKERS,
) -> dict[tuple[str, str], BacktestResult]:
    """
    Backtest one genome across many (symbol, timeframe) pairs simultaneously.
    Returns {(symbol, tf): BacktestResult}.
    """
    args = [
        (genome.to_dict(), sym, tf, TF_BAR_COUNTS.get(tf, 12_000), None)
        for sym, tf in symbol_tf_pairs
    ]

    if workers <= 1:
        results = [_worker(a) for a in args]
    else:
        with mp.Pool(processes=min(workers, len(args))) as pool:
            results = pool.map(_worker, args)

    return {pair: r for pair, r in zip(symbol_tf_pairs, results)}

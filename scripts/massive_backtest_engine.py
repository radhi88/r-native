"""
QADER — Massive Historical Backtest Engine
==========================================
Scans 1M+ candles across timeframes, detects SMC/Fractal/ICT patterns,
simulates trades, builds statistical DNA genes.

Usage:
    .venv\\Scripts\\python.exe scripts\\massive_backtest_engine.py
    .venv\\Scripts\\python.exe scripts\\massive_backtest_engine.py --symbols XAUUSDm EURUSDm --timeframes M1 M5 M15 --max-bars 500000
    .venv\\Scripts\\python.exe scripts\\massive_backtest_engine.py --build-dna --monte-carlo
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
SRC  = ROOT / "src"
for p in (str(SRC), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QADER_ROOT", str(ROOT))
os.environ.setdefault("FRIDAY_PROJECT_ROOT", str(ROOT))

try:
    import numpy as np
    import pandas as pd
except ImportError:
    print("Installing numpy + pandas...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "numpy", "pandas", "-q"])
    import numpy as np
    import pandas as pd

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DEFAULT_SYMBOLS    = ["XAUUSDm"]
DEFAULT_TIMEFRAMES = ["M1", "M5", "M15", "H1"]
DEFAULT_MAX_BARS   = 1_000_000
OUTPUT_DIR         = ROOT / "data" / "backtest"
DNA_OUTPUT         = ROOT / "data" / "qader" / "dna" / "gene_store_backtest.json"
REPORT_PATH        = ROOT / "reports" / "claude_review" / "backtest_summary.json"

TF_MAP = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440, "W1": 10080,
}

SESSION_HOURS = {
    "asian":      (0,  7),
    "london":     (7, 12),
    "ny":         (12, 17),
    "london_ny":  (12, 14),
    "dead":       (17, 23),
}

ATR_REGIMES = {"low": (0, 0.33), "medium": (0.33, 0.67), "high": (0.67, 1.0)}

# ─── MT5 DATA LOADER ─────────────────────────────────────────────────────────

def load_mt5_bars(symbol: str, timeframe_str: str, max_bars: int) -> pd.DataFrame | None:
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            print(f"  [ERROR] MT5 init failed: {mt5.last_error()}")
            return None
        tf_const = getattr(mt5, f"TIMEFRAME_{timeframe_str}", None)
        if tf_const is None:
            print(f"  [WARN] Unknown timeframe: {timeframe_str}")
            return None
        rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, max_bars)
        if rates is None or len(rates) == 0:
            print(f"  [WARN] No data for {symbol} {timeframe_str}")
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        df.set_index("time", inplace=True)
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        print(f"  [DATA] {symbol} {timeframe_str}: {len(df):,} bars "
              f"({df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')})")
        return df
    except Exception as exc:
        print(f"  [ERROR] MT5 load failed: {exc}")
        return None


def load_synthetic_bars(n: int = 200_000, seed: int = 42) -> pd.DataFrame:
    """Synthetic OHLCV for offline testing when MT5 is unavailable."""
    np.random.seed(seed)
    returns   = np.random.normal(0, 0.0003, n)
    price     = 2300.0 + np.cumsum(returns) * 10
    spread    = np.random.uniform(0.0002, 0.0006, n)
    high      = price + np.abs(np.random.normal(0, 0.15, n))
    low       = price - np.abs(np.random.normal(0, 0.15, n))
    close_var = np.random.normal(0, 0.05, n)
    close     = np.clip(price + close_var, low, high)
    volume    = np.random.randint(100, 5000, n)
    idx = pd.date_range("2021-01-01", periods=n, freq="1min", tz="UTC")
    df = pd.DataFrame({"open": price, "high": high, "low": low, "close": close, "volume": volume}, index=idx)
    print(f"  [SYNTHETIC] {len(df):,} bars generated (offline mode)")
    return df


# ─── VECTORIZED INDICATORS ───────────────────────────────────────────────────

def atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, pc = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def ema_series(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def session_label(hour: int) -> str:
    for name, (start, end) in SESSION_HOURS.items():
        if start <= hour < end:
            return name
    return "dead"


# ─── PATTERN DETECTORS (vectorized) ──────────────────────────────────────────

def detect_fractals(df: pd.DataFrame, left: int = 2, right: int = 2) -> pd.DataFrame:
    """Classic 5-bar fractal pattern (Bill Williams style)."""
    h, l = df["high"], df["low"]
    bull = pd.Series(False, index=df.index)
    bear = pd.Series(False, index=df.index)
    for i in range(left, len(df) - right):
        window_h = h.iloc[i - left: i + right + 1]
        window_l = l.iloc[i - left: i + right + 1]
        if h.iloc[i] == window_h.max():
            bear.iloc[i] = True
        if l.iloc[i] == window_l.min():
            bull.iloc[i] = True
    return pd.DataFrame({"fractal_bull": bull, "fractal_bear": bear}, index=df.index)


def detect_bos_choch(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """BOS = Break of Structure, ChoCH = Change of Character (vectorized approx)."""
    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    rolling_high = high.rolling(lookback).max().shift(1)
    rolling_low  = low.rolling(lookback).min().shift(1)
    bos_bull  = close > rolling_high
    bos_bear  = close < rolling_low
    prev_bos_bull = bos_bull.shift(1).fillna(False)
    prev_bos_bear = bos_bear.shift(1).fillna(False)
    choch_bull = bos_bull & prev_bos_bear
    choch_bear = bos_bear & prev_bos_bull
    return pd.DataFrame({
        "bos_bull": bos_bull,
        "bos_bear": bos_bear,
        "choch_bull": choch_bull,
        "choch_bear": choch_bear,
    }, index=df.index)


def detect_order_blocks(df: pd.DataFrame, lookback: int = 10) -> pd.DataFrame:
    """OB = last bearish candle before bullish BOS (and vice versa)."""
    close = df["close"]
    open_ = df["open"]
    rolling_high = df["high"].rolling(lookback).max().shift(1)
    rolling_low  = df["low"].rolling(lookback).min().shift(1)
    bos_bull = close > rolling_high
    bos_bear = close < rolling_low
    bull_candle = close > open_
    bear_candle = close < open_
    ob_bull = bos_bull & bear_candle.shift(1).fillna(False)
    ob_bear = bos_bear & bull_candle.shift(1).fillna(False)
    return pd.DataFrame({"ob_bull": ob_bull, "ob_bear": ob_bear}, index=df.index)


def detect_fvg(df: pd.DataFrame) -> pd.DataFrame:
    """Fair Value Gap = gap between candle[i-2].high and candle[i].low (bullish), or inverse."""
    h, l = df["high"], df["low"]
    fvg_bull = l > h.shift(2)
    fvg_bear = h < l.shift(2)
    return pd.DataFrame({"fvg_bull": fvg_bull, "fvg_bear": fvg_bear}, index=df.index)


def detect_engulfing(df: pd.DataFrame) -> pd.DataFrame:
    """Bullish/bearish engulfing candles."""
    o, c = df["open"], df["close"]
    prev_o, prev_c = o.shift(1), c.shift(1)
    bull_eng = (c > o) & (prev_c < prev_o) & (c > prev_o) & (o < prev_c)
    bear_eng = (c < o) & (prev_c > prev_o) & (c < prev_o) & (o > prev_c)
    return pd.DataFrame({"engulf_bull": bull_eng, "engulf_bear": bear_eng}, index=df.index)


def detect_pinbar(df: pd.DataFrame, ratio: float = 2.5) -> pd.DataFrame:
    """Pin bar: wick > ratio * body."""
    o, c, h, l = df["open"], df["close"], df["high"], df["low"]
    body    = (c - o).abs()
    upper   = h - pd.concat([o, c], axis=1).max(axis=1)
    lower   = pd.concat([o, c], axis=1).min(axis=1) - l
    bull_pb = (lower > ratio * body.clip(lower=1e-8)) & (lower > upper)
    bear_pb = (upper > ratio * body.clip(lower=1e-8)) & (upper > lower)
    return pd.DataFrame({"pinbar_bull": bull_pb, "pinbar_bear": bear_pb}, index=df.index)


# ─── FULL PATTERN UNIVERSE BUILDER ───────────────────────────────────────────

def build_pattern_universe(df: pd.DataFrame, symbol: str, timeframe: str) -> pd.DataFrame:
    print(f"    Detecting patterns on {symbol} {timeframe} ({len(df):,} bars)...")
    atr     = atr_series(df, 14)
    atr_pct = atr.rank(pct=True)

    signals = pd.DataFrame(index=df.index)
    signals["symbol"]    = symbol
    signals["timeframe"] = timeframe
    signals["close"]     = df["close"]
    signals["atr"]       = atr
    signals["atr_pct"]   = atr_pct
    signals["hour"]      = df.index.hour
    signals["weekday"]   = df.index.weekday
    signals["session"]   = signals["hour"].apply(session_label)
    signals["atr_regime"] = pd.cut(atr_pct, bins=[0, 0.33, 0.67, 1.0],
                                   labels=["low", "medium", "high"], include_lowest=True)

    # All detectors
    frac  = detect_fractals(df)
    bos   = detect_bos_choch(df)
    obs   = detect_order_blocks(df)
    fvg   = detect_fvg(df)
    eng   = detect_engulfing(df)
    pin   = detect_pinbar(df)

    for name, col in [
        ("fractal_bull", frac["fractal_bull"]),
        ("fractal_bear", frac["fractal_bear"]),
        ("bos_bull",     bos["bos_bull"]),
        ("bos_bear",     bos["bos_bear"]),
        ("choch_bull",   bos["choch_bull"]),
        ("choch_bear",   bos["choch_bear"]),
        ("ob_bull",      obs["ob_bull"]),
        ("ob_bear",      obs["ob_bear"]),
        ("fvg_bull",     fvg["fvg_bull"]),
        ("fvg_bear",     fvg["fvg_bear"]),
        ("engulf_bull",  eng["engulf_bull"]),
        ("engulf_bear",  eng["engulf_bear"]),
        ("pinbar_bull",  pin["pinbar_bull"]),
        ("pinbar_bear",  pin["pinbar_bear"]),
    ]:
        signals[name] = col.fillna(False)

    # Confluence signals (2+ patterns agree)
    bull_cols = ["fractal_bull", "bos_bull", "ob_bull", "fvg_bull", "engulf_bull", "pinbar_bull"]
    bear_cols = ["fractal_bear", "bos_bear", "ob_bear", "fvg_bear", "engulf_bear", "pinbar_bear"]
    signals["confluence_bull"] = signals[bull_cols].sum(axis=1)
    signals["confluence_bear"] = signals[bear_cols].sum(axis=1)
    signals["any_bull"]  = signals["confluence_bull"] >= 1
    signals["any_bear"]  = signals["confluence_bear"] >= 1
    signals["strong_bull"] = signals["confluence_bull"] >= 2
    signals["strong_bear"] = signals["confluence_bear"] >= 2

    return signals


# ─── TRADE SIMULATOR ─────────────────────────────────────────────────────────

def simulate_trades(df: pd.DataFrame, signals: pd.DataFrame,
                    sl_atr_mult: float = 1.5, tp_atr_mult: float = 3.0,
                    min_atr: float = 0.01) -> pd.DataFrame:
    """
    For each signal, forward-simulate the trade outcome:
    - Entry at next bar open
    - SL = entry ± atr * sl_mult
    - TP = entry ± atr * tp_mult
    - Exit: first of SL, TP, or end of data
    """
    trades = []
    atr_vals  = df["atr"] if "atr" in df.columns else None
    close_arr = df["close"].values
    high_arr  = df["high"].values
    low_arr   = df["low"].values
    atr_arr   = signals["atr"].values
    idx_arr   = df.index

    sig_bull    = signals["strong_bull"].values
    sig_bear    = signals["strong_bear"].values
    session_arr = signals["session"].values
    active_sessions = {"london", "ny", "london_ny"}

    for i in range(len(df) - 50):
        if session_arr[i] not in active_sessions:
            continue  # skip asian and dead-hour signals
        if not (sig_bull[i] or sig_bear[i]):
            continue
        direction = "BUY" if sig_bull[i] else "SELL"
        if sig_bull[i] and sig_bear[i]:
            continue  # conflict, skip
        entry_i = i + 1
        if entry_i >= len(df):
            continue
        entry_price = close_arr[entry_i]
        atr_v = max(float(atr_arr[i]), min_atr)
        sl_dist = atr_v * sl_atr_mult
        tp_dist = atr_v * tp_atr_mult
        if direction == "BUY":
            sl = entry_price - sl_dist
            tp = entry_price + tp_dist
        else:
            sl = entry_price + sl_dist
            tp = entry_price - tp_dist

        outcome = "timeout"
        exit_price = close_arr[min(i + 50, len(df) - 1)]
        exit_i = i + 50

        for j in range(entry_i + 1, min(i + 200, len(df))):
            h, l = high_arr[j], low_arr[j]
            if direction == "BUY":
                if l <= sl:
                    outcome = "sl"; exit_price = sl; exit_i = j; break
                if h >= tp:
                    outcome = "tp"; exit_price = tp; exit_i = j; break
            else:
                if h >= sl:
                    outcome = "sl"; exit_price = sl; exit_i = j; break
                if l <= tp:
                    outcome = "tp"; exit_price = tp; exit_i = j; break

        if direction == "BUY":
            pnl_r = (exit_price - entry_price) / sl_dist
        else:
            pnl_r = (entry_price - exit_price) / sl_dist

        conf_bull = int(signals["confluence_bull"].iloc[i])
        conf_bear = int(signals["confluence_bear"].iloc[i])
        trades.append({
            "entry_time":  idx_arr[entry_i],
            "exit_time":   idx_arr[exit_i],
            "symbol":      signals["symbol"].iloc[i],
            "timeframe":   signals["timeframe"].iloc[i],
            "direction":   direction,
            "session":     signals["session"].iloc[i],
            "atr_regime":  str(signals["atr_regime"].iloc[i]),
            "weekday":     int(signals["weekday"].iloc[i]),
            "hour":        int(signals["hour"].iloc[i]),
            "entry_price": round(entry_price, 5),
            "exit_price":  round(exit_price, 5),
            "sl":          round(sl, 5),
            "tp":          round(tp, 5),
            "atr":         round(atr_v, 5),
            "outcome":     outcome,
            "pnl_r":       round(pnl_r, 4),
            "win":         outcome == "tp",
            "confluence":  max(conf_bull, conf_bear),
            "bars_held":   exit_i - entry_i,
        })

    return pd.DataFrame(trades)


# ─── STATISTICS CALCULATOR ───────────────────────────────────────────────────

def calc_stats(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty or len(trades) < 5:
        return {}
    pnl = trades["pnl_r"].values
    wins = trades["win"].values
    n = len(trades)
    win_rate  = float(wins.mean())
    avg_win   = float(pnl[pnl > 0].mean()) if (pnl > 0).any() else 0.0
    avg_loss  = float(pnl[pnl < 0].mean()) if (pnl < 0).any() else 0.0
    total_r   = float(pnl.sum())
    gross_win = float(pnl[pnl > 0].sum()) if (pnl > 0).any() else 0.0
    gross_loss= abs(float(pnl[pnl < 0].sum())) if (pnl < 0).any() else 1e-9
    pf        = gross_win / max(gross_loss, 1e-9)
    equity    = np.cumsum(pnl)
    dd        = equity - np.maximum.accumulate(equity)
    max_dd    = float(dd.min())
    sharpe    = float(pnl.mean() / (pnl.std() + 1e-9) * np.sqrt(252))
    # max consecutive losses
    max_consec_loss = 0
    cur_loss = 0
    for w in wins:
        if not w:
            cur_loss += 1
            max_consec_loss = max(max_consec_loss, cur_loss)
        else:
            cur_loss = 0
    return {
        "n":                  n,
        "win_rate":           round(win_rate, 4),
        "avg_win_r":          round(avg_win, 4),
        "avg_loss_r":         round(avg_loss, 4),
        "total_r":            round(total_r, 4),
        "profit_factor":      round(pf, 4),
        "max_drawdown_r":     round(max_dd, 4),
        "sharpe":             round(sharpe, 4),
        "max_consec_losses":  max_consec_loss,
        "expectancy_r":       round(float(pnl.mean()), 4),
    }


# ─── MONTE CARLO STRESS TEST ─────────────────────────────────────────────────

def monte_carlo_test(trades: pd.DataFrame, n_simulations: int = 1000,
                     max_dd_threshold: float = -15.0) -> dict[str, Any]:
    """Randomly shuffle trade sequence 1000x, check worst-case drawdown.

    Threshold scales with sqrt(n/50) so that large-sample groups aren't penalised
    for naturally wider drawdown ranges (a 2000-trade sequence can accumulate
    more losses than a 50-trade sequence even at the same per-trade edge).
    """
    if trades.empty or len(trades) < 10:
        return {"passed": False, "reason": "insufficient_trades"}
    pnl = trades["pnl_r"].values
    # Scale threshold: for 50 trades use base; for 500 trades allow ~3× more
    n = len(pnl)
    scaled_threshold = max_dd_threshold * max(1.0, (n / 50) ** 0.5)
    worst_dds = []
    for _ in range(n_simulations):
        shuffled = np.random.permutation(pnl)
        equity = np.cumsum(shuffled)
        dd = float((equity - np.maximum.accumulate(equity)).min())
        worst_dds.append(dd)
    worst_dds = np.array(worst_dds)
    p5_dd = float(np.percentile(worst_dds, 5))
    passed = p5_dd > scaled_threshold
    return {
        "passed":         passed,
        "p5_max_dd_r":    round(p5_dd, 3),
        "mean_max_dd_r":  round(float(worst_dds.mean()), 3),
        "n_simulations":  n_simulations,
        "threshold_r":    round(scaled_threshold, 2),
        "base_threshold": max_dd_threshold,
    }


# ─── WALK-FORWARD VALIDATION ─────────────────────────────────────────────────

def walk_forward_test(trades: pd.DataFrame, train_pct: float = 0.8) -> dict[str, Any]:
    """Compare in-sample vs out-of-sample win rate. Fail if OOS degrades > 15%."""
    if trades.empty or len(trades) < 20:
        return {"passed": False, "reason": "insufficient_trades"}
    n     = len(trades)
    split = int(n * train_pct)
    is_trades  = trades.iloc[:split]
    oos_trades = trades.iloc[split:]
    is_wr  = float(is_trades["win"].mean()) if not is_trades.empty else 0.0
    oos_wr = float(oos_trades["win"].mean()) if not oos_trades.empty else 0.0
    degradation = oos_wr - is_wr
    passed = degradation > -0.15  # OOS win rate not more than 15pp worse
    return {
        "passed":       passed,
        "is_win_rate":  round(is_wr, 4),
        "oos_win_rate": round(oos_wr, 4),
        "degradation":  round(degradation, 4),
        "is_trades":    len(is_trades),
        "oos_trades":   len(oos_trades),
    }


# ─── DNA GENE BUILDER ────────────────────────────────────────────────────────

def build_genes_from_trades(all_trades: pd.DataFrame,
                             min_trades: int = 15,
                             min_win_rate: float = 0.36,
                             min_pf: float = 1.15,
                             min_sharpe: float = 0.3,
                             run_monte_carlo: bool = True,
                             run_walk_forward: bool = True) -> list[dict]:
    genes = []
    group_keys = ["symbol", "timeframe", "direction", "session", "atr_regime"]
    available_keys = [k for k in group_keys if k in all_trades.columns]

    for group_vals, group_df in all_trades.groupby(available_keys):
        if len(group_df) < min_trades:
            continue
        stats = calc_stats(group_df)
        if not stats:
            continue
        if stats["win_rate"] < min_win_rate:
            continue
        if stats["profit_factor"] < min_pf:
            continue
        if stats["sharpe"] < min_sharpe:
            continue

        # Build group dict
        group_dict = dict(zip(available_keys, group_vals if isinstance(group_vals, tuple) else [group_vals]))
        gene_id = "_".join(str(v) for v in group_vals if v)

        mc  = monte_carlo_test(group_df) if run_monte_carlo else {"passed": True}
        wft = walk_forward_test(group_df) if run_walk_forward else {"passed": True}

        if not mc.get("passed") or not wft.get("passed"):
            continue

        # Compute optimal thresholds
        confidence_floor = min(0.85, max(0.55, 1.0 - stats["win_rate"]))
        sl_mult          = 1.5
        tp_mult          = max(2.0, stats["avg_win_r"] / max(abs(stats["avg_loss_r"]), 0.01))
        lot_scale        = min(2.0, max(0.5, stats["profit_factor"] / 2.0))

        genes.append({
            "gene_id":    gene_id,
            "version":    "backtest_v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "group":      group_dict,
            "stats":      stats,
            "thresholds": {
                "min_confidence":   round(confidence_floor, 3),
                "sl_atr_mult":      round(sl_mult, 2),
                "tp_atr_mult":      round(tp_mult, 2),
                "lot_scale":        round(lot_scale, 2),
                "min_confluence":   1,
            },
            "validation": {
                "monte_carlo":    mc,
                "walk_forward":   wft,
            },
            "live_performance": {
                "trades": 0, "wins": 0, "win_rate": None,
                "bayesian_prior": stats["win_rate"],
                "bayesian_posterior": stats["win_rate"],
            },
            "active": True,
        })

    genes.sort(key=lambda g: g["stats"]["sharpe"], reverse=True)
    return genes


# ─── GENE STORE WRITER ───────────────────────────────────────────────────────

def save_genes(genes: list[dict]) -> None:
    DNA_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version":    "backtest_v1",
        "generated":  datetime.now(timezone.utc).isoformat(),
        "gene_count": len(genes),
        "genes":      genes,
    }
    DNA_OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[DNA] {len(genes)} genes saved → {DNA_OUTPUT}")


# ─── SIGNAL ARBITER GENE INJECTOR ────────────────────────────────────────────

def inject_genes_to_arbiter(genes: list[dict]) -> None:
    """Write a weights file that SignalArbiter can load at startup."""
    weights_path = ROOT / "data" / "qader" / "dna" / "arbiter_gene_weights.json"
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    weights: dict[str, Any] = {}
    for gene in genes:
        grp = gene["gene_id"]
        weights[grp] = {
            "min_confidence": gene["thresholds"]["min_confidence"],
            "lot_scale":      gene["thresholds"]["lot_scale"],
            "sl_atr_mult":    gene["thresholds"]["sl_atr_mult"],
            "tp_atr_mult":    gene["thresholds"]["tp_atr_mult"],
            "sharpe":         gene["stats"]["sharpe"],
            "win_rate":       gene["stats"]["win_rate"],
            "active":         gene["active"],
        }
    weights_path.write_text(json.dumps(weights, indent=2), encoding="utf-8")
    print(f"[ARBITER] Gene weights injected → {weights_path}")


# ─── PROGRESS PRINTER ────────────────────────────────────────────────────────

def print_gene_table(genes: list[dict], top_n: int = 20) -> None:
    print(f"\n{'─' * 100}")
    print(f"{'GENE ID':<45} {'N':>6} {'WR%':>6} {'PF':>6} {'Sharpe':>7} {'MaxDD':>7} {'MC':>4} {'WFT':>4}")
    print(f"{'─' * 100}")
    for g in genes[:top_n]:
        mc  = "✓" if g["validation"]["monte_carlo"].get("passed") else "✗"
        wft = "✓" if g["validation"]["walk_forward"].get("passed") else "✗"
        s   = g["stats"]
        print(f"{g['gene_id']:<45} {s['n']:>6} {s['win_rate']*100:>5.1f}% {s['profit_factor']:>6.2f} "
              f"{s['sharpe']:>7.2f} {s['max_drawdown_r']:>7.2f} {mc:>4} {wft:>4}")
    print(f"{'─' * 100}")


# ─── REPORT ──────────────────────────────────────────────────────────────────

def save_report(genes: list[dict], total_bars: int, total_trades: int,
                symbols: list[str], timeframes: list[str]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "generated":    datetime.now(timezone.utc).isoformat(),
        "symbols":      symbols,
        "timeframes":   timeframes,
        "total_bars_scanned":   total_bars,
        "total_signals_found":  total_trades,
        "genes_built":  len(genes),
        "top_gene":     genes[0] if genes else None,
        "gene_summary": [{
            "gene_id":       g["gene_id"],
            "win_rate":      g["stats"]["win_rate"],
            "profit_factor": g["stats"]["profit_factor"],
            "sharpe":        g["stats"]["sharpe"],
            "n_trades":      g["stats"]["n"],
        } for g in genes[:30]],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[REPORT] Saved → {REPORT_PATH}")


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Qader Massive Backtest Engine")
    parser.add_argument("--symbols",     nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--timeframes",  nargs="+", default=DEFAULT_TIMEFRAMES)
    parser.add_argument("--max-bars",    type=int,  default=DEFAULT_MAX_BARS)
    parser.add_argument("--sl-mult",     type=float, default=1.5)
    parser.add_argument("--tp-mult",     type=float, default=3.0)
    parser.add_argument("--min-trades",  type=int,  default=15)
    parser.add_argument("--min-wr",      type=float, default=0.36)
    parser.add_argument("--min-pf",      type=float, default=1.15)
    parser.add_argument("--monte-carlo", action="store_true", default=True)
    parser.add_argument("--walk-forward",action="store_true", default=True)
    parser.add_argument("--offline",     action="store_true", help="Use synthetic data (no MT5)")
    args = parser.parse_args()

    print(f"\n{'═' * 70}")
    print(f"  QADER — MASSIVE HISTORICAL BACKTEST ENGINE")
    print(f"  Symbols: {args.symbols}  |  Timeframes: {args.timeframes}")
    print(f"  Max bars per symbol/TF: {args.max_bars:,}")
    print(f"{'═' * 70}\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_trades_list = []
    total_bars = 0
    t0 = time.monotonic()

    for symbol in args.symbols:
        for tf_str in args.timeframes:
            print(f"[SCAN] {symbol} {tf_str}")
            if args.offline:
                n = min(args.max_bars, 200_000)
                df = load_synthetic_bars(n)
            else:
                df = load_mt5_bars(symbol, tf_str, args.max_bars)
                if df is None:
                    continue

            total_bars += len(df)
            signals = build_pattern_universe(df, symbol, tf_str)
            sig_count = signals[["strong_bull", "strong_bear"]].any(axis=1).sum()
            print(f"    Signals found: {sig_count:,}")

            trades_df = simulate_trades(df, signals, args.sl_mult, args.tp_mult)
            print(f"    Trades simulated: {len(trades_df):,}")
            if not trades_df.empty:
                all_trades_list.append(trades_df)

    elapsed = time.monotonic() - t0
    print(f"\n[DONE] Scanned {total_bars:,} bars in {elapsed:.1f}s")

    if not all_trades_list:
        print("[ERROR] No trade data generated.")
        return

    all_trades = pd.concat(all_trades_list, ignore_index=True)
    print(f"[TOTAL] {len(all_trades):,} simulated trades across all symbols/timeframes")

    win_r = all_trades["win"].mean()
    print(f"[STATS] Overall win rate: {win_r*100:.1f}% | "
          f"Avg R: {all_trades['pnl_r'].mean():.3f} | "
          f"Total R: {all_trades['pnl_r'].sum():.1f}")

    # Save raw trades
    trades_path = OUTPUT_DIR / "all_trades.parquet"
    try:
        all_trades.to_parquet(trades_path, index=False)
        print(f"[SAVED] Raw trades → {trades_path}")
    except Exception:
        trades_path = OUTPUT_DIR / "all_trades.csv"
        all_trades.to_csv(trades_path, index=False)
        print(f"[SAVED] Raw trades → {trades_path} (CSV fallback)")

    # Build DNA genes
    print(f"\n[DNA] Building genes (min_trades={args.min_trades}, min_wr={args.min_wr}, min_pf={args.min_pf})...")
    genes = build_genes_from_trades(
        all_trades,
        min_trades   = args.min_trades,
        min_win_rate = args.min_wr,
        min_pf       = args.min_pf,
        min_sharpe   = 0.5,
        run_monte_carlo  = args.monte_carlo,
        run_walk_forward = args.walk_forward,
    )
    print(f"[DNA] {len(genes)} genes passed all filters")

    if genes:
        print_gene_table(genes)
        save_genes(genes)
        inject_genes_to_arbiter(genes)

    save_report(genes, total_bars, len(all_trades), args.symbols, args.timeframes)

    print(f"\n{'═' * 70}")
    print(f"  BACKTEST COMPLETE")
    print(f"  Bars scanned   : {total_bars:,}")
    print(f"  Trades simulated: {len(all_trades):,}")
    print(f"  Genes built    : {len(genes)}")
    print(f"  Time elapsed   : {elapsed:.1f}s")
    print(f"{'═' * 70}\n")


if __name__ == "__main__":
    main()

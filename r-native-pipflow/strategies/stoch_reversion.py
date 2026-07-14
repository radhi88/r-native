"""strategies/stoch_reversion.py — Stochastic Reversion strategy for Gold M3.

Entry logic (works on any OHLC bar list):
  SELL  → Stoch %D ≥ OB_Heavy (default 90) OR %D ≥ OB_Light (85) on two bars
  BUY   → Stoch %D ≤ OS_Heavy (default 10) OR %D ≤ OS_Light (15) on two bars
  TP    → when %D crosses back to Midline (50)
  SL    → ATR * AtrSlMult (default 2.5)  if UseSL=True

Backtest entry point: backtest(bars, ...)  → dict with summary + trades list.
Each bar is a dict: {time, open, high, low, close, volume}.

Magic number for live EA: 20260605
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional

import numpy as np


# ─── Stochastic K/D computation ─────────────────────────────────

def _stoch_kd(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    k_period: int = 5,
    d_period: int = 3,
    smooth_k: int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (%K, %D) arrays — NaN for insufficient history."""
    n = len(closes)
    raw_k = np.full(n, np.nan)
    for i in range(k_period - 1, n):
        lo = lows[i - k_period + 1 : i + 1].min()
        hi = highs[i - k_period + 1 : i + 1].max()
        rng = hi - lo
        raw_k[i] = 100.0 * (closes[i] - lo) / rng if rng > 0 else 50.0

    # Smooth %K → final %K
    k = np.full(n, np.nan)
    for i in range(smooth_k - 1, n):
        window = raw_k[i - smooth_k + 1 : i + 1]
        if not np.any(np.isnan(window)):
            k[i] = window.mean()

    # %D = SMA of smoothed %K
    d = np.full(n, np.nan)
    for i in range(d_period - 1, n):
        window = k[i - d_period + 1 : i + 1]
        if not np.any(np.isnan(window)):
            d[i] = window.mean()

    return k, d


def _atr(highs, lows, closes, period: int = 14) -> np.ndarray:
    n = len(closes)
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = np.full(n, np.nan)
    if n >= period:
        atr[period - 1] = tr[1:period].mean()
        alpha = 1.0 / period
        for i in range(period, n):
            atr[i] = atr[i - 1] * (1 - alpha) + tr[i] * alpha
    return atr


# ─── Config ──────────────────────────────────────────────────────

class StochReversionConfig:
    def __init__(
        self,
        ob_heavy: float = 90.0,
        ob_light: float = 85.0,
        os_heavy: float = 10.0,
        os_light: float = 15.0,
        midline: float = 50.0,
        k_period: int = 5,
        d_period: int = 3,
        smooth_k: int = 3,
        lot: float = 0.01,
        max_trades: int = 2,
        use_sl: bool = True,
        atr_sl_mult: float = 2.5,
        magic: int = 20260605,
        pip_value: float = 0.1,   # XAUUSDm: 0.01 lot × $1/pip = $0.10/pip
    ):
        self.ob_heavy = ob_heavy
        self.ob_light = ob_light
        self.os_heavy = os_heavy
        self.os_light = os_light
        self.midline = midline
        self.k_period = k_period
        self.d_period = d_period
        self.smooth_k = smooth_k
        self.lot = lot
        self.max_trades = max_trades
        self.use_sl = use_sl
        self.atr_sl_mult = atr_sl_mult
        self.magic = magic
        self.pip_value = pip_value

    @classmethod
    def default(cls) -> "StochReversionConfig":
        return cls()


# ─── Trade record ────────────────────────────────────────────────

class Trade:
    __slots__ = ("side", "entry_idx", "entry_price", "sl", "tp", "exit_idx",
                 "exit_price", "exit_reason", "pnl")

    def __init__(self, side, entry_idx, entry_price, sl, tp):
        self.side = side            # "BUY" | "SELL"
        self.entry_idx = entry_idx
        self.entry_price = entry_price
        self.sl = sl                # None if use_sl=False
        self.tp = tp                # midline %D trigger price (approximate)
        self.exit_idx = None
        self.exit_price = None
        self.exit_reason = None     # "TP" | "SL" | "EOD"
        self.pnl = 0.0

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


# ─── Backtest ─────────────────────────────────────────────────────

def backtest(
    bars: List[Dict[str, Any]],
    cfg: Optional[StochReversionConfig] = None,
) -> Dict[str, Any]:
    """Run Stoch Reversion backtest on `bars`.

    Args:
        bars: list of OHLC dicts with keys time/open/high/low/close/volume.
        cfg:  strategy config; defaults to StochReversionConfig.default().

    Returns:
        {
          "trades":  list of trade dicts,
          "summary": {trades, wins, losses, win_rate, profit_factor, net_pnl},
          "indicators": {"stoch_k": [...], "stoch_d": [...]},
        }
    """
    if cfg is None:
        cfg = StochReversionConfig.default()

    n = len(bars)
    if n < 30:
        return {"trades": [], "summary": _empty_summary(), "indicators": {}}

    highs  = np.array([b["high"]  for b in bars], dtype=float)
    lows   = np.array([b["low"]   for b in bars], dtype=float)
    closes = np.array([b["close"] for b in bars], dtype=float)

    k_arr, d_arr = _stoch_kd(highs, lows, closes, cfg.k_period, cfg.d_period, cfg.smooth_k)
    atr_arr = _atr(highs, lows, closes)

    open_trades: List[Trade] = []
    closed_trades: List[Trade] = []

    for i in range(1, n):
        d_prev = d_arr[i - 1]
        d_cur  = d_arr[i]
        if np.isnan(d_cur) or np.isnan(d_prev) or np.isnan(atr_arr[i]):
            continue

        price = closes[i]
        atr_i = atr_arr[i]

        # ── Manage open trades ──
        still_open = []
        for t in open_trades:
            exited = False
            if t.side == "SELL":
                # TP: %D crosses back below midline from overbought
                if d_prev >= cfg.midline > d_cur:
                    t.exit_idx = i; t.exit_price = price; t.exit_reason = "TP"
                    t.pnl = (t.entry_price - price) * cfg.lot * 100.0
                    exited = True
                elif cfg.use_sl and t.sl is not None and price >= t.sl:
                    t.exit_idx = i; t.exit_price = t.sl; t.exit_reason = "SL"
                    t.pnl = (t.entry_price - t.sl) * cfg.lot * 100.0
                    exited = True
            else:  # BUY
                if d_prev <= cfg.midline < d_cur:
                    t.exit_idx = i; t.exit_price = price; t.exit_reason = "TP"
                    t.pnl = (price - t.entry_price) * cfg.lot * 100.0
                    exited = True
                elif cfg.use_sl and t.sl is not None and price <= t.sl:
                    t.exit_idx = i; t.exit_price = t.sl; t.exit_reason = "SL"
                    t.pnl = (t.sl - t.entry_price) * cfg.lot * 100.0
                    exited = True

            if exited:
                closed_trades.append(t)
            else:
                still_open.append(t)
        open_trades = still_open

        # ── Open new trades (max_trades cap) ──
        if len(open_trades) < cfg.max_trades:
            sl_dist = atr_i * cfg.atr_sl_mult if cfg.use_sl else None

            # SELL signal: %D ≥ OB_Heavy, or second bar ≥ OB_Light
            if d_cur >= cfg.ob_heavy or (d_prev >= cfg.ob_light and d_cur >= cfg.ob_light):
                if not any(t.side == "SELL" for t in open_trades):
                    sl = (price + sl_dist) if sl_dist else None
                    open_trades.append(Trade("SELL", i, price, sl, None))

            # BUY signal: %D ≤ OS_Heavy, or second bar ≤ OS_Light
            elif d_cur <= cfg.os_heavy or (d_prev <= cfg.os_light and d_cur <= cfg.os_light):
                if not any(t.side == "BUY" for t in open_trades):
                    sl = (price - sl_dist) if sl_dist else None
                    open_trades.append(Trade("BUY", i, price, sl, None))

    # Close any remaining open positions at last bar
    for t in open_trades:
        t.exit_idx = n - 1
        t.exit_price = closes[-1]
        t.exit_reason = "EOD"
        if t.side == "SELL":
            t.pnl = (t.entry_price - closes[-1]) * cfg.lot * 100.0
        else:
            t.pnl = (closes[-1] - t.entry_price) * cfg.lot * 100.0
        closed_trades.append(t)

    summary = _summarise(closed_trades)
    return {
        "trades": [t.to_dict() for t in closed_trades],
        "summary": summary,
        "indicators": {
            "stoch_k": k_arr.tolist(),
            "stoch_d": d_arr.tolist(),
        },
    }


def _empty_summary() -> dict:
    return {"trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "profit_factor": 0.0, "net_pnl": 0.0}


def _summarise(trades: List[Trade]) -> dict:
    if not trades:
        return _empty_summary()
    wins   = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_profit = sum(t.pnl for t in wins)
    gross_loss   = abs(sum(t.pnl for t in losses)) or 1e-9
    pf = round(gross_profit / gross_loss, 3)
    wr = round(100.0 * len(wins) / len(trades), 1)
    net = round(sum(t.pnl for t in trades), 2)
    return {
        "trades":        len(trades),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      wr,
        "profit_factor": pf,
        "net_pnl":       net,
    }

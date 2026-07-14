"""
dip_detector.py — Real-time aggressive dip detector for FRIDAY v3.

Mirrors Radhi's proven manual approach:
  "عندما أرى انخفاض بالسوق أشتري بشكل هجومي"

Detects:
  • Sharp drops (price down N points in M bars)
  • Oversold momentum (RSI <30 + Stoch <20)
  • Volume spike on the down move (capitulation)
  • Multi-TF confluence (M1 + M5 both confirming)
  • Distance from key levels (PDH/PDL/Swing)
  • Pin-bar / hammer rejection at the dip

Returns:
  DipSignal {
    quality:   "STRONG" | "MEDIUM" | "WEAK" | "NONE"
    score:     0-100
    drop_pt:   how many points dropped
    drop_atr:  drop in ATR multiples
    reasons:   list of confirming signals
    suggested_lot_factor: 0.5-2.0 (genes use this)
  }
"""
from __future__ import annotations
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import MetaTrader5 as mt5

SYMBOL = "XAUUSDm"


@dataclass
class DipSignal:
    quality:              str = "NONE"     # STRONG | MEDIUM | WEAK | NONE
    score:                int = 0          # 0-100
    drop_pt:              float = 0
    drop_atr:             float = 0
    rsi_m1:               float = 50
    rsi_m5:               float = 50
    stoch_k:              float = 50
    volume_surge:         float = 1.0      # current bar volume / 20-bar avg
    has_hammer:           bool = False
    multi_tf_aligned:     bool = False
    distance_to_swing_low_pt: float = 0
    suggested_lot_factor: float = 1.0
    reasons:              list = field(default_factory=list)
    ts:                   str = ""

    def is_actionable(self) -> bool:
        return self.quality in ("STRONG", "MEDIUM") and self.score >= 50


# ─────────────────────────────────────────────────────────────────────────
# Indicator computations (lightweight, fast — no third-party deps beyond numpy)
# ─────────────────────────────────────────────────────────────────────────

def _rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1: return 50.0
    diff = np.diff(closes)
    gains = np.where(diff > 0, diff, 0)
    losses = np.where(diff < 0, -diff, 0)
    avg_gain = gains[-period:].mean()
    avg_loss = losses[-period:].mean()
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _stochastic_k(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period: return 50.0
    h = highs[-period:].max()
    l = lows[-period:].min()
    if h == l: return 50.0
    return round((closes[-1] - l) / (h - l) * 100, 2)


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1: return 0.0
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i]  - closes[i-1])
        )
        tr_list.append(tr)
    return float(np.mean(tr_list[-period:]))


def _is_hammer(o: float, h: float, l: float, c: float) -> bool:
    """Hammer = small body at top, long lower wick (≥2× body) — bullish reversal."""
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    if body == 0: return False
    return (lower_wick >= 2.0 * body and upper_wick <= body * 0.5)


def _swing_low(lows: np.ndarray, window: int = 5) -> float:
    """Return most recent swing low (lowest of last `window` bars)."""
    if len(lows) < window: return float(lows.min()) if len(lows) else 0
    return float(lows[-window:].min())


# ─────────────────────────────────────────────────────────────────────────
# Main detector
# ─────────────────────────────────────────────────────────────────────────

def detect_dip(symbol: str = SYMBOL, point: float | None = None,
               shutdown_after: bool = False) -> DipSignal:
    """Run a full dip-detection scan using live MT5 data.

    point: if None, auto-detected from mt5.symbol_info(symbol).point.
           DO NOT hardcode — XAUUSDm uses 0.001 (3 digits), not 0.01.
    shutdown_after: if True, calls mt5.shutdown() at end (for standalone CLI use).
    When called from a long-running daemon, leave False to preserve the connection.
    """
    if not mt5.initialize():
        return DipSignal(reasons=["mt5 init failed"])

    # Auto-detect point from broker (critical: XAUUSDm = 0.001, not 0.01)
    if point is None:
        sym_info = mt5.symbol_info(symbol)
        point = sym_info.point if sym_info else 0.001

    # Pull data: M1 (40 bars) + M5 (40 bars) for multi-TF
    m1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 40)
    m5 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 40)
    tick = mt5.symbol_info_tick(symbol)
    if m1 is None or m5 is None or tick is None or len(m1) < 20:
        return DipSignal(reasons=["insufficient data"])

    sig = DipSignal(ts=datetime.utcnow().isoformat())

    # Extract M1 arrays
    o1, h1, l1, c1 = m1["open"], m1["high"], m1["low"], m1["close"]
    v1 = m1["tick_volume"]

    # Extract M5 arrays
    o5, h5, l5, c5 = m5["open"], m5["high"], m5["low"], m5["close"]

    # ── Core: was there a drop? ──
    # Look at last 5 M1 bars: how far did price fall from the recent peak?
    recent_peak = float(h1[-5:].max())
    current      = float(c1[-1])
    drop_pt      = (recent_peak - current) / point
    sig.drop_pt  = round(drop_pt, 1)

    atr_pt = _atr(h1, l1, c1, 14) / point
    sig.drop_atr = round(drop_pt / atr_pt, 2) if atr_pt > 0 else 0

    # If no real drop, return early
    if drop_pt < 30:                       # less than 30pt drop = no dip
        sig.quality = "NONE"
        sig.reasons.append(f"drop {drop_pt:.0f}pt < 30pt threshold")
        mt5.shutdown()
        return sig

    # ── Indicators ──
    sig.rsi_m1  = _rsi(c1, 14)
    sig.rsi_m5  = _rsi(c5, 14)
    sig.stoch_k = _stochastic_k(h1, l1, c1, 14)

    # Volume surge
    avg_vol = v1[-20:-1].mean() if len(v1) >= 20 else v1.mean()
    sig.volume_surge = round(float(v1[-1] / avg_vol), 2) if avg_vol > 0 else 1.0

    # Hammer at the dip?
    sig.has_hammer = _is_hammer(float(o1[-1]), float(h1[-1]), float(l1[-1]), float(c1[-1]))

    # Multi-TF alignment: is M5 also showing the dip?
    m5_drop_pt = (float(h5[-3:].max()) - float(c5[-1])) / point
    sig.multi_tf_aligned = m5_drop_pt > 50

    # Distance to swing low (supports)
    swing = _swing_low(l1, 20)
    sig.distance_to_swing_low_pt = round((current - swing) / point, 1)

    # ── Scoring ──
    score  = 0
    reasons = []

    # Drop magnitude
    if sig.drop_atr >= 1.5:   score += 25; reasons.append(f"drop {sig.drop_atr}x ATR (strong)")
    elif sig.drop_atr >= 1.0: score += 15; reasons.append(f"drop {sig.drop_atr}x ATR")
    elif sig.drop_atr >= 0.7: score += 8

    # RSI oversold
    if sig.rsi_m1 < 25:       score += 25; reasons.append(f"RSI M1 oversold {sig.rsi_m1}")
    elif sig.rsi_m1 < 35:     score += 15; reasons.append(f"RSI M1 low {sig.rsi_m1}")

    # Stoch oversold
    if sig.stoch_k < 20:      score += 15; reasons.append(f"Stoch oversold {sig.stoch_k}")
    elif sig.stoch_k < 35:    score += 8

    # Volume capitulation
    if sig.volume_surge >= 2.0: score += 15; reasons.append(f"vol surge {sig.volume_surge}x")
    elif sig.volume_surge >= 1.5: score += 8

    # Multi-TF
    if sig.multi_tf_aligned:  score += 10; reasons.append("M5 also confirming drop")

    # Hammer
    if sig.has_hammer:        score += 10; reasons.append("hammer/rejection candle")

    # Near swing low = strong support
    if 0 < sig.distance_to_swing_low_pt < 30:
        score += 10; reasons.append(f"at swing low ({sig.distance_to_swing_low_pt}pt away)")

    score = min(100, score)
    sig.score = score
    sig.reasons = reasons

    if   score >= 75: sig.quality = "STRONG";  sig.suggested_lot_factor = 1.5
    elif score >= 50: sig.quality = "MEDIUM";  sig.suggested_lot_factor = 1.0
    elif score >= 30: sig.quality = "WEAK";    sig.suggested_lot_factor = 0.5
    else:             sig.quality = "NONE";    sig.suggested_lot_factor = 0.0

    if shutdown_after: mt5.shutdown()
    return sig


if __name__ == "__main__":
    s = detect_dip(shutdown_after=True)
    print(f"Dip: {s.quality}  score {s.score}/100")
    print(f"  drop: {s.drop_pt}pt ({s.drop_atr}x ATR)")
    print(f"  RSI M1: {s.rsi_m1}  M5: {s.rsi_m5}")
    print(f"  Stoch K: {s.stoch_k}")
    print(f"  vol surge: {s.volume_surge}x")
    print(f"  hammer: {s.has_hammer}  multi_tf: {s.multi_tf_aligned}")
    print(f"  swing_low distance: {s.distance_to_swing_low_pt}pt")
    print(f"  suggested lot_factor: {s.suggested_lot_factor}")
    print(f"  reasons:")
    for r in s.reasons: print(f"    - {r}")

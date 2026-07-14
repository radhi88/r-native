"""shared/trend_filter.py — Dominant higher-timeframe trend + counter-trend veto.

Born 2026-05-29 from the gold-loss post-mortem:

  The son was BUYING gold while it was in a confirmed TREND_DOWN. Root cause:
  `evaluate_genome` chose its side purely from a count of per-timeframe MTF
  biases (up_count / dn_count). A short-term bounce (m1=UP, m5=UP) could reach
  the min_mtf threshold and fire a BUY even while H1 + regime were screaming
  DOWN — a textbook counter-trend entry that gets stopped on the next leg down.

  The fix is the oldest professional rule there is: **don't fight a confirmed
  higher-timeframe trend.** Buying the dip *with* the trend is fine (that's the
  genome's pullback mode); taking a *momentum* trade *against* the dominant HTF
  trend is the loss generator we kill here.

This module is PURE: snapshot in → verdict out. It sends no orders.

WHAT MAKES A TREND "DOMINANT"
─────────────────────────────
A weighted vote over the snapshot's HTF signals, each in [-1, +1] (+ = up):

  regime  (TREND_UP / TREND_DOWN)   weight 0.40   ← authoritative, ADX-backed
  bias.h1 (highest TF in the snap)  weight 0.30
  bias.m15                          weight 0.20
  mtf_align (≥3 of 4 TFs agree)     weight 0.10
                                    ────────────
                                    total |score| ≤ 1.0  → "strength"

`direction` is the sign of the score; `strength` is |score|. A trend is
"confirmed" when strength ≥ min_strength (default 0.45) — i.e. at least the
regime plus one more HTF signal point the same way.
"""
from __future__ import annotations
from dataclasses import dataclass

# Weights — regime is authoritative (it already folds in ADX for gold via the
# dedicated classifier, and ADX-derived for FX in brain_v1).
_W_REGIME = 0.40
_W_H1     = 0.30
_W_M15    = 0.20
_W_MTF    = 0.10

DEFAULT_MIN_STRENGTH = 0.45   # regime + one more HTF agree → "confirmed"


@dataclass
class TrendVerdict:
    direction: str        # "UP" | "DOWN" | "NEUTRAL"
    strength: float       # 0..1  (|weighted score|)
    confirmed: bool       # strength >= min_strength
    score: float          # signed -1..+1 (+ up)
    reason: str           # human-readable breakdown

    def opposes(self, side: str) -> bool:
        """True if a BUY/SELL fights this (confirmed) dominant trend."""
        if not self.confirmed:
            return False
        if side == "BUY":
            return self.direction == "DOWN"
        if side == "SELL":
            return self.direction == "UP"
        return False

    def agrees(self, side: str) -> bool:
        """True if side runs WITH a confirmed dominant trend."""
        if not self.confirmed:
            return False
        return ((side == "BUY"  and self.direction == "UP") or
                (side == "SELL" and self.direction == "DOWN"))


def dominant_trend(snap: dict,
                   min_strength: float = DEFAULT_MIN_STRENGTH) -> TrendVerdict:
    """Weighted HTF trend vote → TrendVerdict. Never raises."""
    if not snap:
        return TrendVerdict("NEUTRAL", 0.0, False, 0.0, "no snap")

    bias   = snap.get("bias") or {}
    regime = str(snap.get("regime") or "").upper()
    mtf    = str(snap.get("mtf_align") or "").upper()

    score = 0.0
    bits: list[str] = []

    if regime == "TREND_UP":
        score += _W_REGIME; bits.append("regime↑")
    elif regime == "TREND_DOWN":
        score -= _W_REGIME; bits.append("regime↓")

    h1 = str(bias.get("h1") or "").upper()
    if h1 == "UP":
        score += _W_H1; bits.append("H1↑")
    elif h1 == "DOWN":
        score -= _W_H1; bits.append("H1↓")

    m15 = str(bias.get("m15") or "").upper()
    if m15 == "UP":
        score += _W_M15; bits.append("M15↑")
    elif m15 == "DOWN":
        score -= _W_M15; bits.append("M15↓")

    if mtf == "UP":
        score += _W_MTF; bits.append("MTF↑")
    elif mtf == "DOWN":
        score -= _W_MTF; bits.append("MTF↓")

    strength  = round(min(abs(score), 1.0), 3)
    direction = "UP" if score > 1e-9 else ("DOWN" if score < -1e-9 else "NEUTRAL")
    confirmed = strength >= min_strength
    reason = (f"{direction} {strength:.2f}"
              + (" ✓confirmed" if confirmed else " ·weak")
              + (f" [{' '.join(bits)}]" if bits else ""))
    return TrendVerdict(direction, strength, confirmed, round(score, 3), reason)


def counter_trend_veto(snap: dict, side: str,
                       min_strength: float = DEFAULT_MIN_STRENGTH
                       ) -> tuple[bool, str]:
    """(veto?, reason). Veto a momentum entry that fights a confirmed HTF trend.

    Returns (True, reason) when `side` opposes a confirmed dominant trend — the
    caller should then NOT enter. Pullbacks WITH the trend never trip this.
    """
    v = dominant_trend(snap, min_strength)
    if v.opposes(side):
        return (True, f"عكس الاتجاه العام: {side} ضد ترند {v.reason}")
    return (False, v.reason)


__all__ = ["TrendVerdict", "dominant_trend", "counter_trend_veto",
           "DEFAULT_MIN_STRENGTH"]

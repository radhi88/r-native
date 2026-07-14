"""adaptive_trailing.py — Smart SL trailing that adapts to live conviction.

The fixed-distance trailing R uses by default ($0.50 BE, $1.00 trail at $1.50
behind price) doesn't react to:
  • how confident the genome is RIGHT NOW (vs at entry)
  • how close we are to TP (closer = more vulnerable to reversal)
  • whether the genome's signal has FLIPPED to the opposite side

This module computes a new SL each cycle from those three inputs.

API:
  compute_adaptive_sl(position, side, current_price, entry, tp,
                       current_sl, live_confidence, live_side_agrees,
                       atr_h1=None) -> (new_sl_or_None, reason_str)

Logic (BUY case; SELL is mirrored):
  gain      = current_price - entry         (must be > 0)
  progress  = gain / (tp - entry)            (0.0 .. 1.0+)

  base_lock_ratio:  fraction of current gain to lock as SL above entry
    confidence ≥ 80 → 0.50  (let it run — strong conviction)
    60-79          → 0.65
    40-59          → 0.80
    < 40 or NO     → 0.90  (low conviction — lock most)

  signal-flip override:
    if genome currently fires OPPOSITE side → snap to lock 95% of gain

  near-TP tightening:
    progress ≥ 0.80 → ratio *= 1.25 (capped at 0.95)
    progress ≥ 0.95 → ratio = 0.97  (lock almost everything)

  micro-gain guard:
    if gain < 2 × spread → don't move SL yet (would get stopped on noise)

Returns the proposed SL only if it IMPROVES vs current_sl (never widens).
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

GATE_CACHE_TTL_S = 6     # avoid hammering brain_server per position per cycle
_GATE_CACHE: dict = {}    # {symbol: (ts, verdict_dict)}

# Per-trade snapshot for "did confidence drop since entry?" comparison
TRAIL_STATE_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\adaptive_trail_state.json")


def _fetch_live_gate(symbol: str) -> Optional[dict]:
    """Pull /api/r/trade_gate?symbol=X with short cache. None on failure."""
    now = time.time()
    cached = _GATE_CACHE.get(symbol)
    if cached and (now - cached[0]) < GATE_CACHE_TTL_S:
        return cached[1]
    try:
        url = f"http://localhost:5055/api/r/trade_gate?symbol={symbol}"
        with urllib.request.urlopen(url, timeout=3) as r:
            d = json.loads(r.read().decode())
        _GATE_CACHE[symbol] = (now, d)
        return d
    except Exception:
        return None


def _load_state() -> dict:
    if not TRAIL_STATE_PATH.exists(): return {}
    try: return json.loads(TRAIL_STATE_PATH.read_text(encoding="utf-8"))
    except Exception: return {}


def _save_state(state: dict) -> None:
    try:
        TRAIL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TRAIL_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    except Exception: pass


def record_entry_confidence(ticket: int, confidence: int, symbol: str,
                             side: str, entry: float, tp: float) -> None:
    """Called once per OPEN — stores baseline for the trailing module."""
    state = _load_state()
    state[str(ticket)] = {
        "entry_confidence": int(confidence or 0),
        "entry_price":      float(entry),
        "tp":               float(tp),
        "symbol":           symbol,
        "side":             side,
        "opened_at":        datetime.now(timezone.utc).isoformat(),
    }
    _save_state(state)


def forget_ticket(ticket: int) -> None:
    state = _load_state()
    state.pop(str(ticket), None)
    _save_state(state)


def compute_adaptive_sl(*, ticket: int, symbol: str, side: str,
                         current_price: float, entry: float, tp: float,
                         current_sl: float, spread_price: float = 0.0
                         ) -> tuple[Optional[float], str]:
    """Return (new_sl, reason) or (None, reason) if no move warranted.

    Reads live gate verdict for `symbol`, compares confidence/side against
    the entry snapshot from record_entry_confidence(), and trails the SL
    based on gain progress + current conviction.
    """
    # 1) Compute gain + progress
    if side == "BUY":
        gain    = current_price - entry
        tp_dist = tp - entry
    elif side == "SELL":
        gain    = entry - current_price
        tp_dist = entry - tp
    else:
        return None, "unknown side"

    if gain <= 0:
        return None, "no gain yet"
    if tp_dist <= 0:
        return None, "tp invalid"

    progress = max(0.0, min(1.5, gain / tp_dist))

    # 2) Micro-gain guard: don't move SL if gain barely exceeds spread
    min_meaningful = spread_price * 2.0 if spread_price > 0 else 0
    if gain < min_meaningful:
        return None, f"gain ${gain:.3f} < 2×spread"

    # 3) Pull live gate verdict for this symbol
    live_gate = _fetch_live_gate(symbol)
    live_confidence = 0
    live_side = None
    if live_gate:
        live_confidence = int(live_gate.get("confidence") or 0)
        live_side       = live_gate.get("side")

    # 4) Get entry-time confidence (defaults to 50 if missing)
    entry_state = _load_state().get(str(ticket), {})
    entry_conf = int(entry_state.get("entry_confidence") or 50)

    # 5) Base lock ratio — AGGRESSIVE (tightened 2026-05-26 per user
    # "move SL to bigger profit, was slow and took smaller profit"):
    # was 50/65/80/90 — too loose, gave back too much on reversals
    if live_confidence >= 80:
        base_ratio = 0.72         # was 0.50 — even on strong conviction, lock 72%
    elif live_confidence >= 60:
        base_ratio = 0.82         # was 0.65
    elif live_confidence >= 40:
        base_ratio = 0.90         # was 0.80
    else:
        base_ratio = 0.95         # was 0.90 — almost full lock on low conviction

    # 6) Confidence-decay penalty: if live_conf dropped ≥ 25 vs entry, tighten more
    decay = entry_conf - live_confidence
    if decay >= 40:
        base_ratio = max(base_ratio, 0.96)   # was 0.92
        decay_note = f"conf-decay {decay}"
    elif decay >= 25:
        base_ratio = max(base_ratio, 0.92)   # was 0.85
        decay_note = f"conf-decay {decay}"
    else:
        decay_note = ""

    # 7) Signal-flip override: live verdict now says opposite side → lock fast
    flip_note = ""
    if live_side and live_side != side and live_gate and live_gate.get("verdict") == "GO":
        base_ratio = 0.98          # was 0.95 — flipped signal, lock almost all
        flip_note = f"FLIP→{live_side}"

    # 8) Progress-based ratchet — much earlier tightening so larger gains
    # get locked aggressively. Was: trigger only at 80% / 95% of TP.
    # Now ratchets up from 40% progress.
    near_tp_note = ""
    if progress >= 0.95:
        base_ratio = 0.99          # was 0.97 — at TP, lock everything
        near_tp_note = f"~TP({progress*100:.0f}%)"
    elif progress >= 0.80:
        base_ratio = max(base_ratio, 0.96)   # was *1.25 capped 0.95
        near_tp_note = f"near-TP({progress*100:.0f}%)"
    elif progress >= 0.60:
        base_ratio = max(base_ratio, 0.92)   # NEW tier
        near_tp_note = f"prog-60({progress*100:.0f}%)"
    elif progress >= 0.40:
        base_ratio = max(base_ratio, 0.88)   # NEW tier — start locking at 40% of way to TP
        near_tp_note = f"prog-40({progress*100:.0f}%)"

    # 9) Compute proposed new SL
    locked = base_ratio * gain
    if side == "BUY":
        new_sl = entry + locked
        improves = (new_sl > current_sl)
    else:
        new_sl = entry - locked
        improves = (new_sl < current_sl)

    if not improves:
        return None, "no improvement vs current_sl"

    bits = [f"lock {int(base_ratio*100)}% of ${gain:.2f}",
            f"prog {progress*100:.0f}%",
            f"conf {live_confidence}"]
    for n in (decay_note, flip_note, near_tp_note):
        if n: bits.append(n)
    return round(new_sl, 5), " · ".join(bits)

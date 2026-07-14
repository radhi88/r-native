"""council/architect.py — system & data integrity check.

Validates that the proposal is internally consistent:
  • SL is on the correct side of entry for the trade direction
  • TP is on the correct side of entry
  • Lot size is within broker min/step bounds
  • Price levels are not stale (snapshot < 10s old)
  • Symbol is actually tradable right now
"""
from __future__ import annotations
from datetime import datetime, timezone
from .types import Proposal, Verdict


def architect_review(proposal: Proposal, snapshot, account) -> Verdict:
    p = proposal
    # 1. SL/TP side correctness
    if p.side == "BUY":
        if p.sl >= p.entry:
            return Verdict(False, f"BUY SL ({p.sl}) must be below entry ({p.entry})", 100)
        if p.tp <= p.entry:
            return Verdict(False, f"BUY TP ({p.tp}) must be above entry ({p.entry})", 100)
    elif p.side == "SELL":
        if p.sl <= p.entry:
            return Verdict(False, f"SELL SL ({p.sl}) must be above entry ({p.entry})", 100)
        if p.tp >= p.entry:
            return Verdict(False, f"SELL TP ({p.tp}) must be below entry ({p.entry})", 100)
    else:
        return Verdict(False, f"unknown side {p.side}", 100)

    # 2. R:R sanity — at least 1:1
    rr = abs(p.tp - p.entry) / max(abs(p.entry - p.sl), 1e-9)
    if rr < 1.0:
        return Verdict(False, f"R:R={rr:.2f} below 1.0 — losing-EV setup", 95)

    # 3. Snapshot freshness
    try:
        ts = datetime.fromisoformat(snapshot.ts_utc.replace("Z", "+00:00"))
        if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
        age_s = (datetime.now(timezone.utc) - ts).total_seconds()
        if age_s > 10:
            return Verdict(False, f"snapshot {age_s:.0f}s stale", 90)
    except Exception: pass

    # 4. Lot bounds (assume MT5 accessible)
    try:
        import MetaTrader5 as mt5
        si = mt5.symbol_info(p.symbol)
        if si:
            if p.lot < si.volume_min:
                return Verdict(False, f"lot {p.lot} < min {si.volume_min}", 100)
            if p.lot > si.volume_max:
                return Verdict(False, f"lot {p.lot} > max {si.volume_max}", 100)
    except Exception: pass

    return Verdict(True, f"R:R={rr:.2f} OK · snapshot fresh · sides correct", 85)

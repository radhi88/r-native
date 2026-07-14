"""scale_out.py — 3-target scale-out plan (FPU-MAX Engine D, adapted to R-Native).

MANAGEMENT edge (the project's REAL edge, not prediction): bank profit in thirds
as price advances, and ratchet the stop to break-even after the first bank — the
"bank the wave" pattern from the user's own winning manual style.

HONEST CONSTRAINT: a position must be splittable into thirds. At the fixed 0.01
safety lot you CANNOT partial-close (min lot 0.01), so this is a NO-OP until
sizing grows to >= 3x min-lot (e.g. via proven Kelly sizing). This module is the
tested, ready logic; the executor gates it behind R_SCALE_OUT + a volume check.

Pure + side-effect-free: given the position geometry it returns a PLAN
(what to close, whether to move SL to break-even). The executor does the mt5 I/O.
"""
from __future__ import annotations


def _r_multiple(side: str, entry: float, sl: float, price: float) -> float:
    """Current profit in R (risk units = |entry - sl|). >0 = in profit."""
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0
    if side.upper() == "BUY":
        return (price - entry) / risk
    return (entry - price) / risk


def plan_scale_out(*, side: str, entry: float, sl: float, price: float,
                   volume: float, orig_volume: float, banked: set,
                   tp1_r: float = 1.0, tp2_r: float = 2.0,
                   min_lot: float = 0.01, lot_step: float = 0.01) -> dict:
    """Decide the next scale-out action for one open position.

    banked  : set of levels already banked (subset of {1, 2}).
    orig_volume : the position's ORIGINAL volume (thirds are computed off this).
    Returns {"close_lots": float, "move_sl_to_be": bool, "level": int|None, "reason": str}.
    close_lots==0 → no action this tick. Fail-safe: never closes below min_lot,
    never leaves a sub-min-lot remainder, no-op if the position can't be split.
    """
    noop = {"close_lots": 0.0, "move_sl_to_be": False, "level": None, "reason": ""}
    # Must be splittable into thirds — the 0.01-lot reality guard.
    if orig_volume < 3 * min_lot - 1e-9:
        return noop
    rr = _r_multiple(side, entry, sl, price)

    def _third() -> float:
        # one third of the ORIGINAL size, snapped to the lot step, >= min_lot
        raw = orig_volume / 3.0
        snapped = round(raw / lot_step) * lot_step
        return round(max(min_lot, snapped), 2)

    # TP2 first (higher milestone wins if both crossed on the same tick)
    if 2 not in banked and rr >= tp2_r:
        chunk = _third()
        # never close more than what leaves a min-lot runner
        if volume - chunk < min_lot - 1e-9:
            chunk = round(volume - min_lot, 2)
        if chunk >= min_lot - 1e-9:
            return {"close_lots": chunk, "move_sl_to_be": False, "level": 2,
                    "reason": f"scale-out TP2 ({tp2_r:.0f}R): bank {chunk}"}
        return noop
    if 1 not in banked and rr >= tp1_r:
        chunk = _third()
        if volume - chunk < min_lot - 1e-9:
            chunk = round(volume - min_lot, 2)
        if chunk >= min_lot - 1e-9:
            return {"close_lots": chunk, "move_sl_to_be": True, "level": 1,
                    "reason": f"scale-out TP1 ({tp1_r:.0f}R): bank {chunk} + SL→BE"}
        return noop
    return noop


if __name__ == "__main__":
    # ── self-test ──────────────────────────────────────────────────────────
    # geometry: BUY entry 100, SL 98 → risk 2.0 ; TP1 @102 (1R), TP2 @104 (2R)
    E, S = 100.0, 98.0

    # 0.01 lot → NEVER scales (the honest constraint)
    p = plan_scale_out(side="BUY", entry=E, sl=S, price=104, volume=0.01,
                       orig_volume=0.01, banked=set())
    assert p["close_lots"] == 0.0, f"0.01 lot must be no-op: {p}"

    # 0.03 lot, price at 1R → bank a third (0.01) + move SL to BE
    p = plan_scale_out(side="BUY", entry=E, sl=S, price=102, volume=0.03,
                       orig_volume=0.03, banked=set())
    assert p["level"] == 1 and abs(p["close_lots"] - 0.01) < 1e-9 and p["move_sl_to_be"], p

    # already banked TP1, price at 2R → bank second third, no BE move
    p = plan_scale_out(side="BUY", entry=E, sl=S, price=104, volume=0.02,
                       orig_volume=0.03, banked={1})
    assert p["level"] == 2 and abs(p["close_lots"] - 0.01) < 1e-9 and not p["move_sl_to_be"], p

    # below TP1 → no action
    p = plan_scale_out(side="BUY", entry=E, sl=S, price=100.5, volume=0.03,
                       orig_volume=0.03, banked=set())
    assert p["close_lots"] == 0.0, p

    # SELL mirror: entry 100 SL 102 (risk 2), price 98 = 1R
    p = plan_scale_out(side="SELL", entry=100.0, sl=102.0, price=98.0, volume=0.03,
                       orig_volume=0.03, banked=set())
    assert p["level"] == 1 and p["move_sl_to_be"], p

    # runner protection: don't leave a sub-min-lot remainder
    p = plan_scale_out(side="BUY", entry=E, sl=S, price=104, volume=0.02,
                       orig_volume=0.03, banked={1}, min_lot=0.01)
    assert p["close_lots"] <= 0.01 + 1e-9 and (0.02 - p["close_lots"]) >= 0.01 - 1e-9, p

    print("scale_out self-test PASSED")
    print("  0.01-lot →", plan_scale_out(side="BUY", entry=E, sl=S, price=104,
          volume=0.01, orig_volume=0.01, banked=set())["reason"] or "NO-OP (as expected)")
    print("  0.03-lot @1R →", plan_scale_out(side="BUY", entry=E, sl=S, price=102,
          volume=0.03, orig_volume=0.03, banked=set())["reason"])

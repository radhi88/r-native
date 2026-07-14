"""runtime/shared/fvg_pending.py — FVG-anchored PENDING-order planner.

Born 2026-05-29 from the user's request:

  "درب ولدنا على وضع اوامر محدد معلقة بالاضافة الى الاوامر المباشرة ... لان في
   فجوات سعرية راح يلمسها اما يرد من عندها او يكمل نزول او صعود"

i.e. for every price gap (FVG) the price will revisit, place a SPECIFIC pending
order ahead of time — either expecting a REVERSAL from the gap, or a
CONTINUATION through it — in addition to the market orders he already fires.

This module is PURE planning: snapshot in → list[PendingPlan] out. It sends no
orders and touches no MT5 state. unified_trader places + manages them.

THE FOUR SETUPS
───────────────
Current price sits ABOVE a bull (demand) FVG, or BELOW a bear (supply) FVG.

  • Bull FVG (demand gap below price)
      REVERSAL  (يرد من عندها)  → BUY_LIMIT at the gap's top edge,
                                   SL below gap bottom, TP = RR · risk up.
                                   Fires when HTF leans UP (price dips to demand
                                   and bounces).
      CONTINUE  (يكمل نزول)    → SELL_STOP below the gap bottom,
                                   SL above gap top, TP = RR · risk down.
                                   Fires when HTF is strongly DOWN (price slices
                                   through demand → keeps falling).

  • Bear FVG (supply gap above price)
      REVERSAL  (يرد من عندها)  → SELL_LIMIT at the gap's bottom edge,
                                   SL above gap top, TP = RR · risk down.
                                   Fires when HTF leans DOWN.
      CONTINUE  (يكمل صعود)    → BUY_STOP above the gap top,
                                   SL below gap bottom, TP = RR · risk up.
                                   Fires when HTF is strongly UP.

All distances are expressed in gold-points then scaled by `pt` so the same
genome thresholds work on every symbol.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PendingPlan:
    side: str                 # "BUY" | "SELL"
    order_type: str           # "LIMIT" | "STOP"
    kind: str                 # "reversal" | "continuation"
    entry: float
    sl: float
    tp: float
    reason: str
    gap_lo: float             # the source FVG bounds (for dedupe/invalidation)
    gap_hi: float


def _digits_for(pt: float) -> int:
    return 5 if pt <= 0.0001 else (3 if pt <= 0.01 else 2)


def plan_fvg_pendings(snap: dict, genome_params: dict, pt: float = 1.0,
                      sym: str = "") -> list[PendingPlan]:
    """Return the pending-order plans the son should have resting on the book.

    Genome-tunable (all optional, gold-point units where noted):
      fvg_pending        bool   master switch                       (default True)
      fvg_max_age        int    skip gaps older than N bars          (default 30)
      fvg_min_size_pt    float  gap must be at least this wide       (default 2.5)
      fvg_sl_buffer_pt   float  SL padding beyond the far edge       (default 2.0)
      fvg_tp_rr          float  reward:risk multiple                 (default 2.0)
      fvg_min_dist_pt    float  entry must be ≥ this from price       (default 1.0)
      fvg_max_dist_atr   float  ignore gaps further than N·ATR away  (default 3.0)
      fvg_cont_strong    int    HTF count needed for a continuation  (default 3)
      fvg_max_plans      int    cap plans returned per scan          (default 4)
    """
    if not snap:
        return []
    if not bool(genome_params.get("fvg_pending", True)):
        return []

    fvg = snap.get("fvg_m5") or {}
    bull = fvg.get("bull") or []
    bear = fvg.get("bear") or []
    if not bull and not bear:
        return []

    bid = snap.get("bid"); ask = snap.get("ask")
    mid = (bid + ask) / 2.0 if (bid and ask) else (bid or ask or 0.0)
    if mid <= 0:
        return []
    atr = (snap.get("atr") or {}).get("m5") or (snap.get("atr") or {}).get("m1") or (5.0 * pt)

    spread = float(snap.get("spread") or 0.0)

    max_age   = int(genome_params.get("fvg_max_age", 30))
    # Volatility- & spread-aware size floor. A fixed point-count alone is
    # gold-calibrated and wrong across asset classes / sessions: in a quiet
    # FX session ATR≈spread≈2pt, so a real 1.5pt gap would be discarded by the
    # 2.5pt gold floor — yet a gap narrower than the spread can never be traded
    # profitably. So a gap qualifies when it clears the SPREAD floor AND is
    # meaningful by the EASIER of the absolute (pt) or volatility (ATR) standard.
    size_pt     = float(genome_params.get("fvg_min_size_pt", 2.5)) * pt
    size_atr    = float(genome_params.get("fvg_min_size_atr", 0.5)) * atr
    size_spread = float(genome_params.get("fvg_min_size_spread", 1.5)) * spread
    min_size  = max(size_spread, min(size_pt, size_atr))
    sl_buf    = float(genome_params.get("fvg_sl_buffer_pt", 2.0)) * pt
    rr        = float(genome_params.get("fvg_tp_rr", 2.0))
    min_dist  = float(genome_params.get("fvg_min_dist_pt", 1.0)) * pt
    max_dist  = float(genome_params.get("fvg_max_dist_atr", 3.0)) * atr
    cont_n    = int(genome_params.get("fvg_cont_strong", 3))
    max_plans = int(genome_params.get("fvg_max_plans", 4))
    digits    = _digits_for(pt)

    bias = snap.get("bias") or {}
    up = sum(1 for v in bias.values() if v == "UP")
    dn = sum(1 for v in bias.values() if v == "DOWN")

    # Trend-alignment: never rest a REVERSAL pending that fights a CONFIRMED
    # higher-timeframe trend (the same root-cause fix as the market path — buying
    # a demand gap while H1+regime are firmly DOWN is how the son bled on gold).
    # Continuations run WITH the move, so they are always allowed.
    tv = None
    if bool(genome_params.get("fvg_trend_align", True)):
        try:
            from runtime.shared.trend_filter import dominant_trend
            tv = dominant_trend(
                snap, float(genome_params.get("fvg_trend_align_min", 0.55)))
        except Exception:
            tv = None

    def _reversal_blocked(side: str) -> bool:
        return bool(tv and tv.opposes(side))

    plans: list[PendingPlan] = []

    def _ok_gap(g: dict) -> tuple[float, float] | None:
        lo = g.get("bot"); hi = g.get("top")
        if lo is None or hi is None:
            return None
        if g.get("age", 0) > max_age:
            return None
        if (hi - lo) < min_size:
            return None
        return float(lo), float(hi)

    # ── Bull (demand) FVGs that sit BELOW current price ──────────────────────
    for g in bull:
        gb = _ok_gap(g)
        if not gb:
            continue
        lo, hi = gb
        if hi >= mid:                      # gap not cleanly below price → skip
            continue
        if (mid - hi) > max_dist:          # too far away to matter
            continue
        # REVERSAL: BUY_LIMIT at the proximal (top) edge — price dips in & bounces
        if up >= 2 and not _reversal_blocked("BUY"):
            entry = round(hi, digits)
            if (mid - entry) >= min_dist:
                sl = round(lo - sl_buf, digits)
                risk = entry - sl
                tp = round(entry + rr * risk, digits)
                plans.append(PendingPlan(
                    "BUY", "LIMIT", "reversal", entry, sl, tp,
                    f"FVG ارتداد شراء @ سقف فجوة الطلب {lo:.{digits}f}-{hi:.{digits}f} "
                    f"(HTF↑{up}/4) — يرد من عندها", lo, hi))
        # CONTINUATION: SELL_STOP below the gap — strong down breaks demand
        elif dn >= cont_n and up <= 1:
            entry = round(lo - sl_buf * 0.5, digits)
            if (mid - entry) >= min_dist:
                sl = round(hi + sl_buf, digits)
                risk = sl - entry
                tp = round(entry - rr * risk, digits)
                plans.append(PendingPlan(
                    "SELL", "STOP", "continuation", entry, sl, tp,
                    f"FVG استمرار نزول @ كسر فجوة الطلب {lo:.{digits}f} "
                    f"(HTF↓{dn}/4) — يكمل نزول", lo, hi))

    # ── Bear (supply) FVGs that sit ABOVE current price ──────────────────────
    for g in bear:
        gb = _ok_gap(g)
        if not gb:
            continue
        lo, hi = gb
        if lo <= mid:                      # gap not cleanly above price → skip
            continue
        if (lo - mid) > max_dist:
            continue
        # REVERSAL: SELL_LIMIT at the proximal (bottom) edge
        if dn >= 2 and not _reversal_blocked("SELL"):
            entry = round(lo, digits)
            if (entry - mid) >= min_dist:
                sl = round(hi + sl_buf, digits)
                risk = sl - entry
                tp = round(entry - rr * risk, digits)
                plans.append(PendingPlan(
                    "SELL", "LIMIT", "reversal", entry, sl, tp,
                    f"FVG ارتداد بيع @ قاع فجوة العرض {lo:.{digits}f}-{hi:.{digits}f} "
                    f"(HTF↓{dn}/4) — يرد من عندها", lo, hi))
        # CONTINUATION: BUY_STOP above the gap — strong up breaks supply
        elif up >= cont_n and dn <= 1:
            entry = round(hi + sl_buf * 0.5, digits)
            if (entry - mid) >= min_dist:
                sl = round(lo - sl_buf, digits)
                risk = entry - sl
                tp = round(entry + rr * risk, digits)
                plans.append(PendingPlan(
                    "BUY", "STOP", "continuation", entry, sl, tp,
                    f"FVG استمرار صعود @ كسر فجوة العرض {hi:.{digits}f} "
                    f"(HTF↑{up}/4) — يكمل صعود", lo, hi))

    # Closest-to-price first (most likely to fill), then cap.
    plans.sort(key=lambda p: abs(p.entry - mid))
    return plans[:max_plans]


__all__ = ["PendingPlan", "plan_fvg_pendings"]

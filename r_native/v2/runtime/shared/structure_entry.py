"""runtime/shared/structure_entry.py — the SMART entry brain.

Born 2026-05-29 because the user (rightly) said our son entered "بالشكل الغبي
والمكان الغبي" — he traded on RSI + MTF bias + raw pressure and IGNORED all the
market structure the brain already captures.

This module turns that captured structure into a REAL trader's decision:

  • FVG / IFVG     — buy unfilled demand gaps (price returns to fill, then goes);
                     avoid buying into bearish gaps / supply. Inverse-FVG flips
                     (a gap that got reclaimed) become support/resistance.
  • Order Blocks   — institutional demand/supply zones; enter AT them, never
                     chase INTO a fresh opposing OB.
  • VWAP           — fair value. Longs want discount (≤ VWAP), shorts premium.
                     Reject chasing > 2σ from VWAP.
  • Volume Profile — POC / value-area as magnets and shelves.
  • Footprint+CVD  — who's actually in control (buyer vs seller volume, delta
                     divergence) — confirmation, not guessing.
  • Candle wicks   — rejection tails = the other side got trapped.

Output: structure_decision(snap, pt) → dict with side, confidence, reasons,
vetoes and a human zone description. The trader uses this as the PRIMARY entry
trigger; RSI/MTF/genome act as filters and the ML clone is the final gate.
"""
from __future__ import annotations


# ── small helpers ──────────────────────────────────────────────────────────
def _mid(snap):
    b = snap.get("bid"); a = snap.get("ask")
    if b and a:
        return (b + a) / 2.0
    return b or a or 0.0


def _atr5(snap):
    return (snap.get("atr") or {}).get("m5") or (snap.get("atr") or {}).get("m1") or 1.0


def _last_candle(snap, tf="m1"):
    arr = snap.get(f"{tf}_last5") or snap.get(f"{tf}_last3") or []
    return arr[-1] if arr else {}


def _wick_reject(cdl, bullish: bool) -> float:
    """0..1 strength of a rejection wick in the desired direction.
    Bullish reject = long lower wick (sellers pushed down, buyers slammed back)."""
    if not cdl:
        return 0.0
    body = max(abs(cdl.get("c", 0) - cdl.get("o", 0)), 1e-9)
    lw = cdl.get("lower_wick", 0); uw = cdl.get("upper_wick", 0)
    wick = lw if bullish else uw
    other = uw if bullish else lw
    ratio = wick / body                      # tail vs body
    score = min(ratio / 2.0, 1.0)            # 2× body wick = full score
    if wick < other:                          # opposite tail dominates → weak
        score *= 0.4
    kind = cdl.get("kind", "")
    if bullish and kind in ("hammer", "inverted_hammer"):
        score = max(score, 0.7)
    if (not bullish) and kind in ("shooting_star", "hanging_man"):
        score = max(score, 0.7)
    return round(min(score, 1.0), 3)


def _in_zone(price, bot, top, atr, tol=0.15):
    """Return (where, dist_atr): where ∈ inside/above/below. tol = ATR fraction."""
    pad = atr * tol
    if bot - pad <= price <= top + pad:
        return "inside", 0.0
    if price < bot:
        return "below", (bot - price) / max(atr, 1e-9)
    return "above", (price - top) / max(atr, 1e-9)


# ── the decision ────────────────────────────────────────────────────────────
def structure_decision(snap: dict, pt: float = 1.0) -> dict:
    """Score a LONG and a SHORT from market structure; return the better one."""
    if not snap:
        return {"side": None, "confidence": 0.0, "reasons": [], "vetoes": ["no snap"]}

    mid = _mid(snap)
    atr = _atr5(snap)
    fvg = snap.get("fvg_m5") or {}
    ob  = snap.get("ob_m5") or {}
    vwap = snap.get("vwap_m5") or {}
    vp   = snap.get("vol_profile_m15") or {}
    fp   = snap.get("footprint") or {}
    cvd  = float(snap.get("cvd_30m1") or 0)
    bias = snap.get("bias") or {}
    rsi  = (snap.get("rsi") or {}).get("m1", 50)
    up = sum(1 for v in bias.values() if v == "UP")
    dn = sum(1 for v in bias.values() if v == "DOWN")

    cdl1 = _last_candle(snap, "m1")
    cdl5 = _last_candle(snap, "m5")

    long_reasons, long_veto, long = [], [], 0.0
    short_reasons, short_veto, short = [], [], 0.0

    # ===== 1. DEMAND / SUPPLY ZONE (max 0.35) — where, not just whether =====
    bull_fvgs = fvg.get("bull") or []
    bear_fvgs = fvg.get("bear") or []
    ob_bull = ob.get("bull") or {}
    ob_bear = ob.get("bear") or {}

    # LONG: price filling a bull FVG (demand gap) or sitting on a bull OB
    best_bull = None
    for g in bull_fvgs:
        where, d = _in_zone(mid, g["bot"], g["top"], atr)
        fresh = max(0.3, 1.0 - g.get("age", 0) / 40.0)
        if where == "inside":
            sc = 0.35 * fresh; tag = f"داخل فجوة شراء FVG {g['bot']:.2f}-{g['top']:.2f} (تعبئة)"
        elif where == "above" and d <= 0.6:        # price just above an unfilled gap → coming to fill
            sc = 0.22 * fresh; tag = f"يقترب لتعبئة فجوة شراء تحت ({g['mid']:.2f})"
        else:
            continue
        if best_bull is None or sc > best_bull[0]:
            best_bull = (sc, tag)
    if ob_bull:
        where, d = _in_zone(mid, ob_bull["bot"], ob_bull["top"], atr)
        if where == "inside":
            fresh = max(0.3, 1.0 - ob_bull.get("age", 0) / 30.0)
            sc = 0.30 * fresh
            if best_bull is None or sc > best_bull[0]:
                best_bull = (sc, f"على Order Block شراء {ob_bull['bot']:.2f}-{ob_bull['top']:.2f}")
    if best_bull:
        long += best_bull[0]; long_reasons.append(best_bull[1])

    # SHORT: mirror
    best_bear = None
    for g in bear_fvgs:
        where, d = _in_zone(mid, g["bot"], g["top"], atr)
        fresh = max(0.3, 1.0 - g.get("age", 0) / 40.0)
        if where == "inside":
            sc = 0.35 * fresh; tag = f"داخل فجوة بيع FVG {g['bot']:.2f}-{g['top']:.2f}"
        elif where == "below" and d <= 0.6:
            sc = 0.22 * fresh; tag = f"يقترب لتعبئة فجوة بيع فوق ({g['mid']:.2f})"
        else:
            continue
        if best_bear is None or sc > best_bear[0]:
            best_bear = (sc, tag)
    if ob_bear:
        where, d = _in_zone(mid, ob_bear["bot"], ob_bear["top"], atr)
        if where == "inside":
            fresh = max(0.3, 1.0 - ob_bear.get("age", 0) / 30.0)
            sc = 0.30 * fresh
            if best_bear is None or sc > best_bear[0]:
                best_bear = (sc, f"على Order Block بيع {ob_bear['bot']:.2f}-{ob_bear['top']:.2f}")
    if best_bear:
        short += best_bear[0]; short_reasons.append(best_bear[1])

    # ===== 2. REJECTION WICK (max 0.20) — the other side got trapped =====
    lw = max(_wick_reject(cdl1, True), _wick_reject(cdl5, True))
    uw = max(_wick_reject(cdl1, False), _wick_reject(cdl5, False))
    if lw > 0.2:
        long += 0.20 * lw; long_reasons.append(f"ذيل سفلي رفض البائعين ({lw:.2f})")
    if uw > 0.2:
        short += 0.20 * uw; short_reasons.append(f"ذيل علوي رفض المشترين ({uw:.2f})")

    # ===== 3. ORDER FLOW (max 0.20) — who is actually in control =====
    delta = float(fp.get("fp_cum_delta", 0) or 0)
    div   = float(fp.get("fp_delta_div", 0) or 0)
    of_long  = (0.12 if cvd > 0 else 0.0) + (0.08 if delta > 0 else 0.0)
    of_short = (0.12 if cvd < 0 else 0.0) + (0.08 if delta < 0 else 0.0)
    if of_long:
        long += of_long; long_reasons.append(f"تدفّق شراء (CVD {cvd:+.0f}, Δ {delta:+.3g})")
    if of_short:
        short += of_short; short_reasons.append(f"تدفّق بيع (CVD {cvd:+.0f}, Δ {delta:+.3g})")
    if div > 0:
        long += 0.05; long_reasons.append("دايفرجنس دلتا صاعد")
    elif div < 0:
        short += 0.05; short_reasons.append("دايفرجنس دلتا هابط")

    # ===== 4. VALUE / VWAP (max 0.15) — discount for longs, premium for shorts =====
    vw = vwap.get("vwap"); sd = vwap.get("sd") or atr
    if vw:
        dev = (mid - vw) / max(sd, 1e-9)        # +above / -below VWAP, in σ
        if dev <= 0:
            long += min(0.15, 0.10 + abs(dev) * 0.03); long_reasons.append(f"خصم تحت VWAP ({dev:.1f}σ)")
        else:
            short += min(0.15, 0.10 + dev * 0.03); short_reasons.append(f"بريميوم فوق VWAP ({dev:.1f}σ)")
        # chasing veto — extended > 2σ from fair value
        if dev > 2.0:
            long_veto.append(f"ممتد {dev:.1f}σ فوق VWAP — لا تطارد شراء")
        if dev < -2.0:
            short_veto.append(f"ممتد {dev:.1f}σ تحت VWAP — لا تطارد بيع")
    # POC / value-area shelf
    poc = vp.get("poc")
    if poc:
        if mid <= poc:
            long_reasons.append(f"تحت/عند POC {poc:.2f}")
        else:
            short_reasons.append(f"فوق/عند POC {poc:.2f}")

    # ===== 5. HTF TREND ALIGN (max 0.10) =====
    long  += min(up, 4) / 4 * 0.10
    short += min(dn, 4) / 4 * 0.10
    if up >= 3: long_reasons.append(f"اتجاه أعلى صاعد {up}/4")
    if dn >= 3: short_reasons.append(f"اتجاه أعلى هابط {dn}/4")

    # ===== 6. IFVG flip (bonus 0.06) — reclaimed gap becomes support/resistance
    last_close = (cdl5 or {}).get("c", mid)
    for g in bear_fvgs:                          # bear gap reclaimed upward → support
        if last_close > g["top"]:
            long += 0.06; long_reasons.append(f"IFVG: استرجع فجوة بيع → دعم {g['top']:.2f}"); break
    for g in bull_fvgs:                          # bull gap lost downward → resistance
        if last_close < g["bot"]:
            short += 0.06; short_reasons.append(f"IFVG: كسر فجوة شراء → مقاومة {g['bot']:.2f}"); break

    # ===== VETOES — don't enter into the opposing zone (no chasing into supply/demand)
    if ob_bear:
        where, d = _in_zone(mid, ob_bear["bot"], ob_bear["top"], atr, tol=0.0)
        if (where == "below" and d <= 0.5 and ob_bear.get("age", 99) < 10) or where == "inside":
            long_veto.append(f"شراء تحت Order Block بيع طازج {ob_bear['bot']:.2f} — دخول غبي")
    if ob_bull:
        where, d = _in_zone(mid, ob_bull["bot"], ob_bull["top"], atr, tol=0.0)
        if (where == "above" and d <= 0.5 and ob_bull.get("age", 99) < 10) or where == "inside":
            short_veto.append(f"بيع فوق Order Block شراء طازج {ob_bull['top']:.2f} — دخول غبي")
    for g in bear_fvgs:                          # buying straight into a supply gap
        where, _ = _in_zone(mid, g["bot"], g["top"], atr, tol=0.0)
        if where == "inside":
            long_veto.append(f"شراء داخل فجوة بيع {g['bot']:.2f}-{g['top']:.2f}"); break
    for g in bull_fvgs:
        where, _ = _in_zone(mid, g["bot"], g["top"], atr, tol=0.0)
        if where == "inside":
            short_veto.append(f"بيع داخل فجوة شراء {g['bot']:.2f}-{g['top']:.2f}"); break

    long = round(min(long, 1.0), 3)
    short = round(min(short, 1.0), 3)
    if long_veto:  long = 0.0
    if short_veto: short = 0.0

    # pick the better side
    if long >= short and long > 0:
        side, conf, reasons, zone = "BUY", long, long_reasons, (best_bull[1] if best_bull else "")
    elif short > long and short > 0:
        side, conf, reasons, zone = "SELL", short, short_reasons, (best_bear[1] if best_bear else "")
    else:
        side, conf, reasons, zone = None, 0.0, [], ""

    return {
        "side": side, "confidence": conf, "score_long": long, "score_short": short,
        "reasons": reasons, "zone": zone,
        "long_reasons": long_reasons, "short_reasons": short_reasons,
        "long_vetoes": long_veto, "short_vetoes": short_veto,
        "vetoes": (long_veto if side == "BUY" else short_veto if side == "SELL" else long_veto + short_veto),
        "mid": round(mid, 5), "vwap": (round(vw, 5) if vw else None), "rsi": rsi,
    }

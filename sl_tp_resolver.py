"""sl_tp_resolver.py — SMC-aware SL/TP placement.

Given a genome, side, entry, snapshot, and ATR, decide where to put SL/TP:
- If the genome has an SMC anchor flag on (`sl_anchor_smc_ob`,
  `sl_anchor_smc_swing`, `tp_target_smc_liq`, `tp_target_smc_ob`), use the
  corresponding SMC structure in the snapshot.
- Otherwise fall back to the caller-supplied function (legacy ATR math).

Returns a dict with the resolved levels plus `anchor_levels` for the chart
drawer to render the actual SL/TP basis on the user's MT5 chart.

This module is pure — no I/O. Called from `trade_gate.evaluate_gate` (live)
and from `ga_simulator.simulate_genome` (backtest).
"""
from __future__ import annotations

from typing import Callable, Optional


def resolve_sl_tp(
    genome: dict,
    side: str,                       # "BUY" | "SELL"
    entry: float,
    snap: dict,                      # snapshot in genome_signal format (with .smc)
    h1_atr: float,
    fallback: Optional[Callable] = None,
    max_sl_dist: Optional[float] = None,
) -> dict:
    """Decide SL and TP for a trade. Returns:

        {
          ok: True/False,
          sl: float, near_tp: float, far_tp: float,
          sl_anchor: "smc_ob" | "smc_swing" | "atr",
          tp_anchor: "smc_liq" | "smc_ob"   | "atr",
          anchor_levels: {ob_used, swing_used, liq_used},
          reasoning: [str, ...],
        }

    `ok=False` means the caller should use its legacy ATR fallback (the
    SMC anchor was attempted but produced an invalid or too-far level).
    """
    flags  = (genome or {}).get("flags",  {}) or {}
    params = (genome or {}).get("params", {}) or {}
    smc_h1 = ((snap or {}).get("h1") or {}).get("smc") or {}

    side = (side or "").upper()
    if side not in ("BUY", "SELL"):
        return _fallback_result(fallback, genome, side, entry, h1_atr,
                                reason=f"bad side {side}")

    reasoning: list[str] = []
    anchor_levels: dict = {"ob_used": None, "swing_used": None, "liq_used": None}

    # ── SL resolution ────────────────────────────────────────────
    sl, sl_anchor = None, "atr"
    if flags.get("sl_anchor_smc_ob"):
        sl, sl_anchor, anchor_levels["ob_used"] = _resolve_sl_from_ob(
            side, entry, smc_h1, params, h1_atr, reasoning)
    if sl is None and flags.get("sl_anchor_smc_swing"):
        sl, sl_anchor, anchor_levels["swing_used"] = _resolve_sl_from_swing(
            side, entry, snap, params, h1_atr, reasoning)

    # ── TP resolution ────────────────────────────────────────────
    near_tp, far_tp, tp_anchor = None, None, "atr"
    if flags.get("tp_target_smc_liq"):
        near_tp, far_tp, tp_anchor, anchor_levels["liq_used"] = _resolve_tp_from_liq(
            side, entry, sl if sl is not None else entry, smc_h1, reasoning)
    if (near_tp is None or far_tp is None) and flags.get("tp_target_smc_ob"):
        n2, f2, t2, ob_used = _resolve_tp_from_opposite_ob(
            side, entry, sl if sl is not None else entry, smc_h1, reasoning)
        near_tp = near_tp if near_tp is not None else n2
        far_tp  = far_tp  if far_tp  is not None else f2
        tp_anchor = tp_anchor if tp_anchor != "atr" else t2
        if ob_used: anchor_levels["ob_used"] = ob_used

    # ── Apply fallback for whatever wasn't resolved by SMC ──────
    if sl is None or near_tp is None or far_tp is None:
        fb = _fallback_result(fallback, genome, side, entry, h1_atr,
                              reason="partial smc -> atr fallback")
        if not fb["ok"]:
            return fb
        sl       = sl       if sl       is not None else fb["sl"]
        near_tp  = near_tp  if near_tp  is not None else fb["near_tp"]
        far_tp   = far_tp   if far_tp   is not None else fb["far_tp"]

    # ── Risk cap ─────────────────────────────────────────────────
    sl_dist = abs(entry - sl)
    if max_sl_dist is not None and sl_dist > max_sl_dist:
        reasoning.append(f"sl_dist {sl_dist:.5f} > cap {max_sl_dist:.5f} — refuse")
        return {
            "ok": False, "sl": sl, "near_tp": near_tp, "far_tp": far_tp,
            "sl_anchor": sl_anchor, "tp_anchor": tp_anchor,
            "anchor_levels": anchor_levels, "reasoning": reasoning,
        }

    # Ensure TPs are on the correct side of entry
    if side == "BUY":
        if near_tp <= entry: near_tp = entry + sl_dist * 1.0
        if far_tp  <= entry: far_tp  = entry + sl_dist * 2.0
        if near_tp > far_tp: near_tp, far_tp = far_tp, near_tp
    else:
        if near_tp >= entry: near_tp = entry - sl_dist * 1.0
        if far_tp  >= entry: far_tp  = entry - sl_dist * 2.0
        if near_tp < far_tp: near_tp, far_tp = far_tp, near_tp

    return {
        "ok": True, "sl": sl, "near_tp": near_tp, "far_tp": far_tp,
        "sl_anchor": sl_anchor, "tp_anchor": tp_anchor,
        "anchor_levels": anchor_levels, "reasoning": reasoning,
    }


# ─── SL anchors ─────────────────────────────────────────────────
def _resolve_sl_from_ob(side: str, entry: float, smc_h1: dict, params: dict,
                        h1_atr: float, reasoning: list) -> tuple:
    """SL just past the OB the genome is reacting to."""
    buf = float(params.get("smc_ob_buffer_atr", 0.5)) * max(h1_atr, 1e-9)
    if side == "BUY":
        ob = smc_h1.get("fresh_ob_below")
        if not ob:
            reasoning.append("OB-SL requested but no fresh_ob_below")
            return None, "atr", None
        sl = float(ob["bottom"]) - buf
        if sl >= entry:
            reasoning.append(f"OB-SL {sl} >= entry {entry}, abandon")
            return None, "atr", None
        reasoning.append(f"SL anchored under bull OB at {ob['bottom']:.5f} - buf {buf:.5f}")
        return sl, "smc_ob", ob
    else:
        ob = smc_h1.get("fresh_ob_above")
        if not ob:
            reasoning.append("OB-SL requested but no fresh_ob_above")
            return None, "atr", None
        sl = float(ob["top"]) + buf
        if sl <= entry:
            reasoning.append(f"OB-SL {sl} <= entry {entry}, abandon")
            return None, "atr", None
        reasoning.append(f"SL anchored over bear OB at {ob['top']:.5f} + buf {buf:.5f}")
        return sl, "smc_ob", ob


def _resolve_sl_from_swing(side: str, entry: float, snap: dict, params: dict,
                           h1_atr: float, reasoning: list) -> tuple:
    """SL just past the last H1 swing low (BUY) or swing high (SELL)."""
    buf = float(params.get("smc_ob_buffer_atr", 0.5)) * max(h1_atr, 1e-9)
    h1 = (snap or {}).get("h1") or {}
    if side == "BUY":
        swing = h1.get("swing_low")
        if not swing:
            reasoning.append("swing-SL requested but no swing_low")
            return None, "atr", None
        sl = float(swing) - buf
        if sl >= entry:
            reasoning.append(f"swing-SL {sl} >= entry {entry}, abandon")
            return None, "atr", None
        reasoning.append(f"SL anchored under swing_low {swing:.5f}")
        return sl, "smc_swing", {"price": float(swing), "side": "low"}
    else:
        swing = h1.get("swing_high")
        if not swing:
            reasoning.append("swing-SL requested but no swing_high")
            return None, "atr", None
        sl = float(swing) + buf
        if sl <= entry:
            reasoning.append(f"swing-SL {sl} <= entry {entry}, abandon")
            return None, "atr", None
        reasoning.append(f"SL anchored over swing_high {swing:.5f}")
        return sl, "smc_swing", {"price": float(swing), "side": "high"}


# ─── TP anchors ─────────────────────────────────────────────────
def _resolve_tp_from_liq(side: str, entry: float, sl: float, smc_h1: dict,
                         reasoning: list) -> tuple:
    """TP targets the nearest/2nd-nearest liquidity pool on opposite side."""
    if side == "BUY":
        pools = sorted(p for p in smc_h1.get("liq_above", []) if p > entry)
    else:
        pools = sorted((p for p in smc_h1.get("liq_below", []) if p < entry),
                       reverse=True)
    if not pools:
        reasoning.append("liq-TP requested but no opposite-side pools")
        return None, None, "atr", None
    near = pools[0]
    far  = pools[1] if len(pools) > 1 else (entry + 2 * abs(entry - sl)
                                            if side == "BUY"
                                            else entry - 2 * abs(entry - sl))
    reasoning.append(f"TP near={near:.5f} far={far:.5f} (liquidity pools)")
    return float(near), float(far), "smc_liq", [near, far]


def _resolve_tp_from_opposite_ob(side: str, entry: float, sl: float,
                                 smc_h1: dict, reasoning: list) -> tuple:
    """far_tp = centre of opposite OB; near_tp = half-way."""
    sl_dist = abs(entry - sl)
    if side == "BUY":
        ob = smc_h1.get("fresh_ob_above")
        if not ob:
            reasoning.append("OB-TP requested but no opposite OB")
            return None, None, "atr", None
        far = (float(ob["top"]) + float(ob["bottom"])) / 2
        if far <= entry:
            reasoning.append(f"OB-TP {far} <= entry {entry}, abandon")
            return None, None, "atr", None
        near = entry + sl_dist * 1.5
    else:
        ob = smc_h1.get("fresh_ob_below")
        if not ob:
            reasoning.append("OB-TP requested but no opposite OB")
            return None, None, "atr", None
        far = (float(ob["top"]) + float(ob["bottom"])) / 2
        if far >= entry:
            reasoning.append(f"OB-TP {far} >= entry {entry}, abandon")
            return None, None, "atr", None
        near = entry - sl_dist * 1.5
    reasoning.append(f"TP anchored at opposite OB centre {far:.5f}")
    return float(near), float(far), "smc_ob", ob


# ─── Legacy ATR fallback adapter ────────────────────────────────
def _fallback_result(fallback: Optional[Callable], genome: dict, side: str,
                     entry: float, h1_atr: float, reason: str) -> dict:
    if fallback is not None:
        try:
            fb = fallback(genome, side, entry, h1_atr)
        except Exception as e:
            fb = {"ok": False, "error": str(e)}
        if fb.get("ok"):
            fb.setdefault("sl_anchor", "atr")
            fb.setdefault("tp_anchor", "atr")
            fb.setdefault("anchor_levels", {})
            fb.setdefault("reasoning", [reason])
        return fb
    return _default_atr_resolver(genome, side, entry, h1_atr, reason)


def _default_atr_resolver(genome: dict, side: str, entry: float,
                          h1_atr: float, reason: str) -> dict:
    """Plain ATR math used when no caller-provided fallback is available."""
    params = (genome or {}).get("params", {}) or {}
    sl_mult = float(params.get("sl_atr_mult", 1.5))
    tp_mult = float(params.get("tp_atr_mult", 3.0))
    if h1_atr <= 0:
        return {"ok": False, "reasoning": [f"atr=0 unable to size, {reason}"]}
    sl_dist = sl_mult * h1_atr
    tp_dist = tp_mult * h1_atr
    if side == "BUY":
        sl = entry - sl_dist
        far_tp  = entry + tp_dist
        near_tp = entry + tp_dist * 0.5
    else:
        sl = entry + sl_dist
        far_tp  = entry - tp_dist
        near_tp = entry - tp_dist * 0.5
    return {
        "ok": True, "sl": sl, "near_tp": near_tp, "far_tp": far_tp,
        "sl_anchor": "atr", "tp_anchor": "atr",
        "anchor_levels": {"ob_used": None, "swing_used": None, "liq_used": None},
        "reasoning": [f"default ATR math (sl={sl_mult}×ATR tp={tp_mult}×ATR)", reason],
    }

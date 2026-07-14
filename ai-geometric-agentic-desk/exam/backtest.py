"""Walk-forward exam — net of spread, no look-ahead.

Replays the full confluence pipeline bar by bar: the ML model is retrained on
only the bars preceding each decision, geometry is computed from closed bars,
and each accepted trade's outcome is resolved by walking *forward* to the first
stop or target. Profit factor, win rate, and expectancy are computed net of an
estimated round-trip spread, then folded across walk-forward blocks to punish
window-fragile results. The final 0–100 score gates execution.

This is intentionally adversarial: given the project's NO_EDGE history on SMC,
fractals, and ML direction, a passing score is hard to earn — which is the
point. Nothing risks the $10 until the geometry actually pays net of cost.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import config
from core.confluence import evaluate
from core.fractals import fractal_state, williams_fractals
from core.ml_signal import LogisticSignal
from core.smc import compute_smc


def _atr(h, l, c, i: int, period: int = 14) -> float:
    """Wilder-ish ATR over the window ending at ``i``."""
    a = max(1, i - period)
    tr = np.maximum(h[a:i + 1] - l[a:i + 1],
                    np.abs(h[a:i + 1] - c[a - 1:i])) if a >= 1 else (h[:i + 1] - l[:i + 1])
    return float(np.mean(tr)) if len(tr) else float(h[i] - l[i])


def _resolve(h, l, c, i: int, d: int, entry: float, sl: float, tp: float,
             horizon: int, spread_r: float) -> float | None:
    """Walk forward from bar ``i`` to the first SL/TP hit; return net R."""
    sl_dist = abs(entry - sl)
    if sl_dist <= 0:
        return None
    for j in range(i + 1, min(len(c), i + horizon)):
        if d > 0:
            if l[j] <= sl:
                return -1.0 - spread_r
            if h[j] >= tp:
                return (tp - entry) / sl_dist - spread_r
        else:
            if h[j] >= sl:
                return -1.0 - spread_r
            if l[j] <= tp:
                return (entry - tp) / sl_dist - spread_r
    last = c[min(len(c) - 1, i + horizon - 1)]
    return d * (last - entry) / sl_dist - spread_r


@dataclass
class ExamResult:
    """Aggregated exam metrics and final score."""

    score: float
    profit_factor: float
    trades: int
    win_rate: float
    expectancy_r: float
    folds_positive: int
    notes: str


def simulate(o, h, l, c, profile_k: float, sq9_deg: tuple[float, ...],
             spread_price: float, r_multiple: float = 1.5,
             warmup: int = 120, horizon: int = 48) -> list[float]:
    """Replay the pipeline and return the net-R outcome of each trade.

    Args:
        o, h, l, c: OHLC arrays, oldest first.
        profile_k: ATR stop multiplier for the market.
        sq9_deg: Square-of-9 rotations to project.
        spread_price: Estimated round-trip spread in price units.
        r_multiple: Reward-to-risk target.
        warmup: Bars reserved before the first decision.
        horizon: Max bars to hold a trade.

    Returns:
        List of net-R results (one per executed trade).
    """
    out: list[float] = []
    model = LogisticSignal()
    last_fit = 0
    for i in range(warmup, len(c) - 2):
        if i - last_fit >= 50:  # periodic causal retrain
            model.fit(o, h, l, c, i)
            last_fit = i
        w = slice(max(0, i - 200), i + 1)
        atr = _atr(h, l, c, i)
        if atr <= 0:
            continue
        smc = compute_smc(o[w], h[w], l[w], c[w])
        fr = williams_fractals(h[w], l[w])
        state = fractal_state(fr)
        md, mc = model.predict(o, h, l, c, i)
        piv = float(c[max(0, i - 20)])
        dec = evaluate(float(c[i]), atr, smc, state, md, mc, piv,
                       max(0, i - 20), i, sq9_deg)
        if not dec.trade:
            continue
        entry = float(c[i])
        sl_dist = atr * max(1.4, min(2.0, profile_k))
        sl = entry - dec.direction * sl_dist
        tp = entry + dec.direction * sl_dist * r_multiple
        r = _resolve(h, l, c, i, dec.direction, entry, sl, tp, horizon,
                     spread_price / sl_dist)
        if r is not None:
            out.append(r)
    return out


def _metrics(rs: list[float]) -> tuple[float, float, float]:
    """Return ``(profit_factor, win_rate, expectancy_r)`` for net-R results."""
    if not rs:
        return 0.0, 0.0, 0.0
    wins = [x for x in rs if x > 0]
    losses = [-x for x in rs if x < 0]
    gp, gl = sum(wins), sum(losses)
    pf = gp / gl if gl > 0 else (gp if gp > 0 else 0.0)
    return pf, len(wins) / len(rs), float(np.mean(rs))


def score_exam(o, h, l, c, profile_k: float, sq9_deg: tuple[float, ...],
               spread_price: float, folds: int = 4) -> ExamResult:
    """Run the walk-forward exam and produce a 0–100 score.

    The score rewards profit factor toward :data:`config.PF_TARGET`, positive
    expectancy, adequate sample size, and consistency across walk-forward
    folds. A strategy that only works in one block is capped low.

    Args:
        o, h, l, c: OHLC arrays.
        profile_k: ATR stop multiplier.
        sq9_deg: Square-of-9 rotations.
        spread_price: Round-trip spread in price units.
        folds: Number of contiguous walk-forward blocks.

    Returns:
        An :class:`ExamResult`.
    """
    rs = simulate(o, h, l, c, profile_k, sq9_deg, spread_price)
    pf, wr, exp = _metrics(rs)
    n = len(rs)
    if n < 20:
        return ExamResult(min(40.0, n), pf, n, wr, exp, 0,
                          "insufficient trades — not deployable")

    seg = max(1, len(rs) // folds)
    fold_pf = [_metrics(rs[k * seg:(k + 1) * seg])[0] for k in range(folds)]
    pos = sum(1 for p in fold_pf if p > 1.0)

    pf_score = min(1.0, pf / config.PF_TARGET) * 45.0
    exp_score = max(0.0, min(1.0, exp / 0.20)) * 20.0
    cons_score = (pos / folds) * 25.0
    size_score = min(1.0, n / 100.0) * 10.0
    score = round(pf_score + exp_score + cons_score + size_score, 1)
    note = (f"pf={pf:.2f} wr={wr:.0%} exp={exp:+.3f}R n={n} "
            f"folds+={pos}/{folds}")
    return ExamResult(score, pf, n, wr, exp, pos, note)

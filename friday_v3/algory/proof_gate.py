"""
proof_gate.py — HONEST PROOF-GATE for the R executor (magic 20260605).

The operationalization of the project's core doctrine: "measure before trust".
This is a PURE, side-effect-free module. It NEVER reads MT5, files, or the DB
and it NEVER mutates any live trading state. You hand it a list of closed-trade
net P/Ls for one magic; it hands back an honest verdict.

Doctrine (single, non-negotiable rule — thresholds mirror real_account_gate.py
and stage_promoter.py; do NOT invent new ones here):

    GREEN         : n >= 30  AND  t_stat >= 2.0  AND  net > 0
    RED           : n >= 30  AND  (net <= 0  OR  t_stat < 0)
    ACCUMULATING  : n < 30   (not enough evidence yet — keep measuring)

`net` is expected to already be net-of-cost (pnl + commission + swap), which is
exactly what the canonical friday.db `trades.net` column and desk_scoreboard's
`_deal_pl` (profit + commission + swap) both provide. This module does not add
or remove cost — it trusts the caller to pass net-of-cost values.

t_stat is the standard one-sample t-statistic of per-trade P/L against a mean of
zero, using the *sample* standard deviation (n-1 divisor):

    t = mean(net) / (sample_std / sqrt(n))
      = mean(net) * sqrt(n) / sample_std

This matches stage_promoter._tstat (the maturity system's promotion primitive).
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

# ── Gate thresholds (doctrine constants — keep identical to the assessments) ──
JUDGE_MIN_N = 30      # below this we cannot judge — verdict is ACCUMULATING
PROMOTE_MIN_T = 2.0   # one-sample t must clear 2-sigma to certify a positive edge


def _tstat(nets: Sequence[float]) -> float:
    """One-sample t of per-trade P/L vs 0, sample std (n-1). n<2 or std==0 -> 0.0."""
    n = len(nets)
    if n < 2:
        return 0.0
    mu = sum(nets) / n
    var = sum((x - mu) ** 2 for x in nets) / (n - 1)  # sample variance (unbiased)
    sd = math.sqrt(var)
    if sd <= 0.0:
        return 0.0
    return mu * math.sqrt(n) / sd


def compute(pls: Sequence[float],
            r_multiples: Optional[Sequence[float]] = None,
            magic: Optional[int] = None) -> dict:
    """Honest proof-gate stats for a single magic's closed trades.

    Args:
        pls: list of closed-trade net P/Ls (already net-of-cost). Order-independent
             for the verdict; a copy is taken so the caller's list is never mutated.
        r_multiples: optional per-trade R multiples (same length as pls). Purely
             descriptive — surfaced as avg_r if provided; never affects the verdict.
        magic: optional identifier echoed back into the result for the UI.

    Returns a dict with:
        magic, n, wins, losses, win_rate, net, avg, std, t_stat, avg_r, verdict, reason
    """
    # Defensive copy + coerce to float; drop anything non-numeric (fail-open).
    nets: List[float] = []
    for x in (pls or []):
        try:
            nets.append(float(x))
        except (TypeError, ValueError):
            continue

    n = len(nets)
    wins = sum(1 for x in nets if x > 0)
    losses = sum(1 for x in nets if x <= 0)  # net<=0 counts as a loss (breakeven is not a win)
    net = round(sum(nets), 6)
    avg = round(net / n, 6) if n > 0 else 0.0
    win_rate = round(wins / n, 4) if n > 0 else 0.0

    # std (sample, n-1) for reporting; t via the shared primitive
    if n > 1:
        mu = sum(nets) / n
        std = round(math.sqrt(sum((x - mu) ** 2 for x in nets) / (n - 1)), 6)
    else:
        std = 0.0
    t_stat = round(_tstat(nets), 4)

    avg_r = None
    if r_multiples:
        rs: List[float] = []
        for r in r_multiples:
            try:
                rs.append(float(r))
            except (TypeError, ValueError):
                continue
        if rs:
            avg_r = round(sum(rs) / len(rs), 4)

    # ── Verdict (the whole point of the module) ──
    if n < JUDGE_MIN_N:
        verdict = "ACCUMULATING"
        reason = f"n={n} < {JUDGE_MIN_N}: not enough closed trades to judge — keep measuring"
    elif net > 0 and t_stat >= PROMOTE_MIN_T:
        verdict = "GREEN"
        reason = f"n={n} >= {JUDGE_MIN_N}, net=+{net} > 0, t={t_stat} >= {PROMOTE_MIN_T}: edge certified"
    elif net <= 0 or t_stat < 0:
        verdict = "RED"
        reason = f"n={n} >= {JUDGE_MIN_N} but net={net} / t={t_stat}: no positive edge"
    else:
        # n>=30, net>0, but 0 <= t < 2 : positive-leaning yet not significant
        verdict = "ACCUMULATING"
        reason = f"n={n} >= {JUDGE_MIN_N}, net=+{net} > 0 but t={t_stat} < {PROMOTE_MIN_T}: not yet significant"

    return {
        "magic": magic,
        "n": n,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "net": net,
        "avg": avg,
        "std": std,
        "t_stat": t_stat,
        "avg_r": avg_r,
        "verdict": verdict,
        "reason": reason,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Self-test — run:  python friday_v3/algory/proof_gate.py
# ─────────────────────────────────────────────────────────────────────────────
def _selftest() -> None:
    # 1) Strong, consistent winner: 40 trades, clearly positive, tight spread → GREEN
    winners = [1.0, 1.2, 0.8, 1.1, 0.9] * 8  # n=40, mean=1.0, small variance
    r = compute(winners, magic=20260605)
    assert r["n"] == 40, r
    assert r["net"] > 0, r
    assert r["t_stat"] >= 2.0, r
    assert r["verdict"] == "GREEN", r

    # 2) Clear loser: 40 trades, negative net → RED
    losers = [-1.0, -1.2, -0.8, 0.5, -0.9] * 8  # n=40, net negative
    r = compute(losers)
    assert r["n"] == 40, r
    assert r["net"] <= 0, r
    assert r["verdict"] == "RED", r

    # 3) Small sample (n<30) → ACCUMULATING regardless of sign
    small_win = [2.0, 1.5, 3.0, 2.5, 1.0]  # n=5, positive
    r = compute(small_win)
    assert r["n"] == 5, r
    assert r["verdict"] == "ACCUMULATING", r
    small_loss = [-2.0, -1.5, -3.0]  # n=3, negative
    r = compute(small_loss)
    assert r["verdict"] == "ACCUMULATING", r

    # 4) n>=30, positive net but NOT significant (fat noise) → ACCUMULATING
    noisy = ([10.0, -9.0] * 15) + [1.0] * 2  # n=32, tiny positive mean, huge std
    r = compute(noisy)
    assert r["n"] == 32, r
    assert r["net"] > 0, r
    assert r["t_stat"] < 2.0, r
    assert r["verdict"] == "ACCUMULATING", r

    # 5) n>=30, exactly breakeven (net==0) → RED (breakeven is not an edge)
    even = [1.0, -1.0] * 15  # n=30, net exactly 0
    r = compute(even)
    assert r["n"] == 30, r
    assert r["net"] == 0, r
    assert r["verdict"] == "RED", r

    # 6) Empty input is safe → ACCUMULATING, no crash
    r = compute([])
    assert r["n"] == 0, r
    assert r["verdict"] == "ACCUMULATING", r

    # 7) r_multiples surface as avg_r without affecting the verdict
    r = compute(winners, r_multiples=[2.0] * len(winners), magic=20260605)
    assert r["avg_r"] == 2.0, r
    assert r["verdict"] == "GREEN", r

    # 8) Non-numeric junk is dropped (fail-open), doesn't crash
    r = compute([1.0, None, "x", 2.0, float("nan")])  # nan survives coercion but n small
    assert r["verdict"] == "ACCUMULATING", r

    print("proof_gate self-test PASSED")


if __name__ == "__main__":
    _selftest()

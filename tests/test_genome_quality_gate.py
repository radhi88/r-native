"""
test_genome_quality_gate.py
---------------------------
Controlled genome safety test using synthetic test cases.
Verifies all 8+ rejection rules and status progression.

Run: python -m tests.test_genome_quality_gate
  OR: python tests/test_genome_quality_gate.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\Radhi\MT5")
SRC  = ROOT / "src"
for p in (str(SRC), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mt5_ai.core.genome_quality_gate import (
    GenomeQualityGate, GenomeStatus, compute_bounded_score,
)

gate = GenomeQualityGate()

# ── Test case helpers ─────────────────────────────────────────────────────────

def _case(
    name: str,
    score_raw:    float,
    return_pct:   float,
    winrate:      float,
    drawdown_pct: float,
    trades:       int,
    pf:           float = 1.5,
    oos_ratio:    float = 1.0,
) -> dict:
    return dict(
        name=name, score_raw=score_raw, return_pct=return_pct,
        winrate=winrate, drawdown_pct=drawdown_pct, trades=trades,
        pf=pf, oos_ratio=oos_ratio,
    )


PASS_STATUSES = {
    GenomeStatus.CANDIDATE,
    GenomeStatus.WATCHLIST,
    GenomeStatus.APPROVED_FOR_BREEDING,
    GenomeStatus.APPROVED_FOR_DEMO,
}

REJECT_STATUSES = {
    GenomeStatus.REJECTED,
    GenomeStatus.QUARANTINED,
}

# ── Test cases ────────────────────────────────────────────────────────────────

TEST_CASES = [
    # (case_dict, expected_pass: bool, description)

    # --- SHOULD PASS ---
    (_case("healthy_genome",
           score_raw=18.5, return_pct=42.0, winrate=0.52,
           drawdown_pct=5.2, trades=280, pf=1.65, oos_ratio=0.85),
     True, "Normal healthy genome — should become CANDIDATE or APPROVED_FOR_BREEDING"),

    (_case("decent_small",
           score_raw=9.0, return_pct=22.0, winrate=0.48,
           drawdown_pct=8.0, trades=160, pf=1.25, oos_ratio=0.9),
     True, "Decent smaller genome — should become CANDIDATE"),

    # --- SHOULD REJECT ---
    (_case("degenerate_score",
           score_raw=26_806_002.0, return_pct=4_337_520_470.0, winrate=0.179,
           drawdown_pct=30.2, trades=95, pf=3.2, oos_ratio=1.0),
     False, "Actual degenerate EURUSDm H1 genome — MUST be REJECTED (R1+R2)"),

    (_case("nan_score",
           score_raw=math.nan, return_pct=50.0, winrate=0.50,
           drawdown_pct=5.0, trades=200, pf=1.5),
     False, "NaN score — MUST be REJECTED (R3)"),

    (_case("inf_return",
           score_raw=100.0, return_pct=math.inf, winrate=0.55,
           drawdown_pct=3.0, trades=200, pf=2.0),
     False, "Inf return_pct — MUST be REJECTED (R3)"),

    (_case("inf_score",
           score_raw=math.inf, return_pct=80.0, winrate=0.55,
           drawdown_pct=5.0, trades=200, pf=2.0),
     False, "Inf score — MUST be REJECTED (R3)"),

    (_case("high_return_low_trades",
           score_raw=500.0, return_pct=75_000.0, winrate=0.60,
           drawdown_pct=2.0, trades=100, pf=3.0),
     False, "High return + low trades — MUST be REJECTED (R5)"),

    (_case("high_wr_low_trades",
           score_raw=50.0, return_pct=30.0, winrate=0.97,
           drawdown_pct=3.0, trades=150, pf=2.0),
     False, "Win rate 97% with only 150 trades — MUST be REJECTED (R6)"),

    (_case("zero_dd_high_return",
           score_raw=200.0, return_pct=5_000.0, winrate=0.60,
           drawdown_pct=0.02, trades=200, pf=2.5),
     False, "Near-zero drawdown + very high return — MUST be REJECTED (R7)"),

    (_case("too_few_trades",
           score_raw=10.0, return_pct=20.0, winrate=0.55,
           drawdown_pct=4.0, trades=50, pf=1.4),
     False, "Only 50 trades — MUST be REJECTED (RMIN)"),
]

# ── Bounded score test ────────────────────────────────────────────────────────

def test_bounded_score_never_exceeds_1000() -> bool:
    """Score must never exceed 1000 regardless of inputs."""
    extreme_cases = [
        (1_000_000.0, 0.0001, 0.99, 10_000.0, 50_000, 1.0),
        (0.0, 0.0, 0.0, 0.0, 0, 1.0),
        (200.0, 0.1, 0.50, 1.5, 500, 1.0),
        (50.0, 8.0, 0.45, 1.3, 1000, 0.8),
    ]
    for args in extreme_cases:
        s = compute_bounded_score(*args)
        if s > 1000.0 or s < 0.0 or math.isnan(s) or math.isinf(s):
            return False
    return True


# ── Run tests ─────────────────────────────────────────────────────────────────

def run() -> dict:
    results = []
    passed  = 0
    failed  = 0

    print("\n" + "=" * 72)
    print("  GENOME QUALITY GATE — SYNTHETIC SAFETY TEST")
    print("=" * 72)

    for case, expect_pass, description in TEST_CASES:
        gr = gate.check_stats(
            score_raw=case["score_raw"],
            return_pct=case["return_pct"],
            winrate=case["winrate"],
            drawdown_pct=case["drawdown_pct"],
            trades=case["trades"],
            pf=case["pf"],
            oos_ratio=case["oos_ratio"],
            source=f"test:{case['name']}",
        )
        actual_pass = gr.ok
        ok = (actual_pass == expect_pass)
        status_str = gr.status.value
        icon = "✅" if ok else "❌"

        print(f"\n{icon} {case['name']}")
        print(f"   Expect: {'PASS' if expect_pass else 'REJECT'}  "
              f"Got: {status_str}  Rule: {gr.rule}")
        print(f"   Score: {gr.score:.1f}  Reason: {gr.reason[:80]}")
        print(f"   {description}")

        results.append({
            "name":        case["name"],
            "expect_pass": expect_pass,
            "actual_pass": actual_pass,
            "status":      status_str,
            "rule":        gr.rule,
            "score":       gr.score,
            "ok":          ok,
        })
        if ok:
            passed += 1
        else:
            failed += 1

    # Bounded score test
    bst_ok = test_bounded_score_never_exceeds_1000()
    icon = "✅" if bst_ok else "❌"
    print(f"\n{icon} bounded_score_never_exceeds_1000")
    print(f"   All extreme inputs produce score in [0, 1000]: {'PASS' if bst_ok else 'FAIL'}")
    results.append({
        "name": "bounded_score_ceiling",
        "ok": bst_ok,
        "status": "PASS" if bst_ok else "FAIL",
    })
    if bst_ok:
        passed += 1
    else:
        failed += 1

    print("\n" + "=" * 72)
    total = passed + failed
    print(f"  RESULTS: {passed}/{total} passed  |  {failed} failed")
    print("=" * 72)

    gate_status = "PASS" if failed == 0 else f"FAIL ({failed} failures)"
    print(f"\nGENOME_GATE_STATUS = {'PASS' if failed == 0 else 'FAIL_REQUIRES_FIXES'}")

    return {
        "total":   total,
        "passed":  passed,
        "failed":  failed,
        "results": results,
        "gate_status": "PASS" if failed == 0 else "FAIL_REQUIRES_FIXES",
    }


if __name__ == "__main__":
    outcome = run()
    sys.exit(0 if outcome["failed"] == 0 else 1)

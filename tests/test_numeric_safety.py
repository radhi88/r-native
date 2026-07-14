"""
test_numeric_safety.py
----------------------
Unit tests for numeric_safety.validate_genome_stats() covering all 8 rejection
rules (R1–R8) and the guard_denominator / reject_erange helpers.

No MT5, TensorFlow, or config dependencies.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mt5_ai.core.numeric_safety import (
    validate_genome_stats,
    validate_genome,
    reject_erange,
    guard_denominator,
    SafetyResult,
    SCORE_MAX,
    RETURN_MAX,
    HIGH_RETURN_THRESHOLD,
    HIGH_RETURN_MIN_TRADES,
    HIGH_WR_THRESHOLD,
    HIGH_WR_MIN_TRADES,
    ZERO_DD_RETURN_LIMIT,
    NEAR_ZERO_DENOM,
)


# ── Suppress log file writes ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_disk_writes():
    with patch("mt5_ai.core.numeric_safety._write_log"):
        yield


# ── Helpers ───────────────────────────────────────────────────────────────────

def _valid(
    score: float = 20.0,
    return_pct: float = 40.0,
    winrate: float = 0.55,
    drawdown_pct: float = 5.0,
    trades: int = 300,
) -> SafetyResult:
    return validate_genome_stats(score, return_pct, winrate, drawdown_pct, trades)


# ── Passing baseline ──────────────────────────────────────────────────────────

def test_valid_genome_passes():
    r = _valid()
    assert r.ok is True
    assert r.rule == "PASS"


def test_valid_boundary_score_exactly_at_max():
    r = validate_genome_stats(SCORE_MAX, 100.0, 0.55, 5.0, 300)
    assert r.ok is True


# ── R1 — score ceiling ────────────────────────────────────────────────────────

def test_r1_score_exceeds_max():
    r = validate_genome_stats(SCORE_MAX + 0.01, 100.0, 0.55, 5.0, 300)
    assert r.ok is False
    assert r.rule == "R1"


def test_r1_extreme_score_rejected():
    r = validate_genome_stats(1e9, 100.0, 0.55, 5.0, 300)
    assert r.ok is False
    assert r.rule in ("R1", "R3")


# ── R2 — return_pct ceiling ───────────────────────────────────────────────────

def test_r2_positive_overflow_rejected():
    r = validate_genome_stats(50.0, RETURN_MAX + 1, 0.55, 5.0, 300)
    assert r.ok is False
    assert r.rule == "R2"


def test_r2_negative_overflow_rejected():
    r = validate_genome_stats(50.0, -(RETURN_MAX + 1), 0.55, 5.0, 300)
    assert r.ok is False
    assert r.rule == "R2"


def test_r2_boundary_exactly_at_limit_passes():
    r = validate_genome_stats(50.0, RETURN_MAX, 0.55, 5.0, 600)
    # RETURN_MAX also satisfies R5 check (HIGH_RETURN_THRESHOLD < RETURN_MAX)
    # with 600 trades ≥ HIGH_RETURN_MIN_TRADES → should pass R2 but hit R5
    assert r.ok is True or r.rule in ("R5",)


# ── R3 — NaN / Inf in any metric ─────────────────────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("score",        math.nan),
    ("score",        math.inf),
    ("score",       -math.inf),
    ("return_pct",   math.nan),
    ("return_pct",   math.inf),
    ("winrate",      math.nan),
    ("drawdown_pct", math.nan),
    ("drawdown_pct", math.inf),
])
def test_r3_nan_inf_in_metric(field, value):
    kwargs = dict(score=20.0, return_pct=40.0, winrate=0.55,
                  drawdown_pct=5.0, trades=300)
    kwargs[field] = value
    r = validate_genome_stats(**kwargs)
    assert r.ok is False
    assert r.rule == "R3"


def test_r3_non_numeric_value():
    # Non-numeric that math.isnan will raise TypeError on
    r = validate_genome_stats("bad", 40.0, 0.55, 5.0, 300)  # type: ignore
    assert r.ok is False
    assert r.rule == "R3"


# ── R4 — ERANGE overflow helper ───────────────────────────────────────────────

def test_r4_reject_erange_returns_false():
    r = reject_erange("genome_evolver", "score overflow")
    assert r.ok is False
    assert r.rule == "R4"


def test_r4_details_appear_in_reason():
    r = reject_erange("test", "fitness * 1e400 overflowed")
    assert "fitness" in r.reason or "overflow" in r.reason.lower()


# ── R5 — high return with too few trades ──────────────────────────────────────

def test_r5_high_return_low_trades_rejected():
    r = validate_genome_stats(
        score=500.0,
        return_pct=HIGH_RETURN_THRESHOLD + 1,
        winrate=0.60,
        drawdown_pct=2.0,
        trades=HIGH_RETURN_MIN_TRADES - 1,
    )
    assert r.ok is False
    assert r.rule == "R5"


def test_r5_high_return_sufficient_trades_passes():
    r = validate_genome_stats(
        score=500.0,
        return_pct=HIGH_RETURN_THRESHOLD + 1,
        winrate=0.60,
        drawdown_pct=2.0,
        trades=HIGH_RETURN_MIN_TRADES,
    )
    # May still be blocked by R7 (zero-dd check) but not R5
    assert r.rule != "R5"


# ── R6 — near-perfect win rate with too few trades ────────────────────────────

def test_r6_high_wr_low_trades_rejected():
    r = validate_genome_stats(
        score=50.0,
        return_pct=30.0,
        winrate=HIGH_WR_THRESHOLD + 0.01,
        drawdown_pct=3.0,
        trades=HIGH_WR_MIN_TRADES - 1,
    )
    assert r.ok is False
    assert r.rule == "R6"


def test_r6_high_wr_sufficient_trades_passes():
    r = validate_genome_stats(
        score=50.0,
        return_pct=30.0,
        winrate=HIGH_WR_THRESHOLD + 0.01,
        drawdown_pct=3.0,
        trades=HIGH_WR_MIN_TRADES,
    )
    assert r.rule != "R6"


def test_r6_boundary_wr_exact_threshold_passes():
    # exactly at HIGH_WR_THRESHOLD (0.95) should NOT trigger R6
    r = validate_genome_stats(50.0, 30.0, HIGH_WR_THRESHOLD, 3.0, 50)
    assert r.rule != "R6"


# ── R7 — near-zero drawdown with high return ─────────────────────────────────

def test_r7_zero_dd_high_return_rejected():
    r = validate_genome_stats(
        score=200.0,
        return_pct=ZERO_DD_RETURN_LIMIT + 1,
        winrate=0.60,
        drawdown_pct=0.04,   # ≤ 0.05
        trades=300,
    )
    assert r.ok is False
    assert r.rule == "R7"


def test_r7_realistic_drawdown_not_rejected():
    r = validate_genome_stats(200.0, 2000.0, 0.60, 10.0, 600)
    assert r.rule != "R7"


def test_r7_exact_dd_boundary_triggers():
    # drawdown exactly 0.05 → ≤ 0.05 → should still trigger R7
    r = validate_genome_stats(200.0, ZERO_DD_RETURN_LIMIT + 1, 0.60, 0.05, 300)
    assert r.ok is False
    assert r.rule == "R7"


def test_r7_dd_just_above_boundary_does_not_trigger():
    r = validate_genome_stats(200.0, ZERO_DD_RETURN_LIMIT + 1, 0.60, 0.06, 600)
    assert r.rule != "R7"


# ── R8 — guard_denominator ────────────────────────────────────────────────────

@pytest.mark.parametrize("value,fallback,expected", [
    (1.0,          0.0, 1.0),
    (NEAR_ZERO_DENOM, 0.0, 0.0),   # exactly at boundary → fallback
    (NEAR_ZERO_DENOM * 0.5, 99.0, 99.0),  # below → fallback
    (NEAR_ZERO_DENOM * 2,   0.0, NEAR_ZERO_DENOM * 2),  # above → keep
    (-1.5,         0.0, -1.5),   # large negative → keep
    (0.0,          7.0, 7.0),    # exact zero → fallback
])
def test_guard_denominator(value, fallback, expected):
    result = guard_denominator(value, fallback)
    assert result == pytest.approx(expected)


def test_guard_denominator_non_numeric_returns_fallback():
    result = guard_denominator("bad", 42.0)  # type: ignore
    assert result == pytest.approx(42.0)


# ── validate_genome with mock object ─────────────────────────────────────────

def test_validate_genome_object_passes():
    genome = MagicMock()
    genome.modern_score.return_value = 20.0
    genome.total_return_pct = 40.0
    genome.win_rate = 0.55
    genome.max_dd_pct = 5.0
    genome.trades = 300
    r = validate_genome(genome)
    assert r.ok is True


def test_validate_genome_attribute_error_rejected():
    class BrokenGenome:
        @property
        def total_return_pct(self):
            raise RuntimeError("missing attribute")

    r = validate_genome(BrokenGenome(), "test")
    assert r.ok is False
    assert r.rule == "R3"


def test_validate_genome_nan_score_rejected():
    genome = MagicMock()
    genome.modern_score.return_value = math.nan
    genome.total_return_pct = 40.0
    genome.win_rate = 0.55
    genome.max_dd_pct = 5.0
    genome.trades = 300
    r = validate_genome(genome)
    assert r.ok is False
    assert r.rule == "R3"


# ── Rule ordering: R3 fires before R1/R2 ─────────────────────────────────────

def test_r3_takes_precedence_over_r1():
    """NaN score → R3 fires, not R1, because R3 runs first."""
    r = validate_genome_stats(math.nan, 40.0, 0.55, 5.0, 300)
    assert r.rule == "R3"


# ── SafetyResult fields ───────────────────────────────────────────────────────

def test_safety_result_fields_on_pass():
    r = _valid()
    assert r.ok is True
    assert isinstance(r.rule, str)
    assert isinstance(r.reason, str)


def test_safety_result_fields_on_reject():
    r = validate_genome_stats(math.nan, 40.0, 0.55, 5.0, 300)
    assert r.ok is False
    assert r.rule == "R3"
    assert len(r.reason) > 0

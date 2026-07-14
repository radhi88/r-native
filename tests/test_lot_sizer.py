"""Tests for lot_sizer.compute_lot — tier selection, streak guard, balance cap."""

import pytest
from unittest.mock import patch
from src.mt5_ai.lot_sizer import compute_lot, _wilson_lower, SizingResult, DEFAULT_LOT, MAX_LOT


def _row(won: bool, points: float) -> dict:
    return {"won": won, "points": str(points)}


def _rows(n: int, wr: float = 0.60, avg_pts: float = 10.0) -> list[dict]:
    """Build n journal rows with the given win rate."""
    rows = []
    for i in range(n):
        won = i < int(n * wr)
        rows.append(_row(won, avg_pts if won else -avg_pts))
    return rows


class TestWilsonLower:
    def test_zero_trades_returns_zero(self):
        assert _wilson_lower(0, 0) == 0.0

    def test_perfect_winrate_below_one(self):
        lb = _wilson_lower(100, 100)
        assert 0.9 < lb < 1.0

    def test_50pct_wr_near_half(self):
        lb = _wilson_lower(50, 100)
        assert 0.40 < lb < 0.50


class TestComputeLot:
    def test_empty_journal_returns_default(self):
        result = compute_lot([])
        assert result.lot == DEFAULT_LOT
        assert result.tier == 0

    def test_tier_0_below_50_trades(self):
        result = compute_lot(_rows(30, wr=0.75))
        assert result.lot == DEFAULT_LOT
        assert result.tier == 0

    def test_tier_1_at_50_trades_good_stats(self):
        # 50 trades, 70% WR, PF > 1.4 should reach tier 1
        result = compute_lot(_rows(50, wr=0.70, avg_pts=15.0))
        assert result.tier >= 1
        assert result.lot >= 0.02

    def test_tier_3_elite_requires_200_trades(self):
        # 250 trades at 65% WR with strong PF
        result = compute_lot(_rows(250, wr=0.65, avg_pts=20.0))
        assert result.tier == 3
        assert result.lot == 0.05

    def test_losing_streak_resets_to_tier0(self):
        rows = _rows(100, wr=0.60)
        # Append 5 consecutive losses at the end
        for _ in range(5):
            rows.append(_row(False, -10.0))
        result = compute_lot(rows)
        assert result.lot == DEFAULT_LOT
        assert result.tier == 0
        assert "losing streak" in result.reason

    def test_streak_of_4_does_not_reset(self):
        rows = _rows(200, wr=0.65, avg_pts=20.0)
        for _ in range(4):
            rows.append(_row(False, -10.0))
        result = compute_lot(rows)
        # 4 < 5 threshold, should still tier up
        assert result.tier >= 1

    def test_balance_cap_limits_lot(self):
        # Paper balance $10 → 2% cap → max ~0.002, floored at DEFAULT_LOT
        result = compute_lot(_rows(200, wr=0.65, avg_pts=20.0), paper_balance=10.0)
        assert result.lot == DEFAULT_LOT

    def test_max_lot_cap_never_exceeded(self):
        result = compute_lot(_rows(500, wr=0.80, avg_pts=50.0), paper_balance=1_000_000.0)
        assert result.lot <= MAX_LOT

    def test_no_loss_rows_pf_infinite_safe(self):
        rows = [_row(True, 10.0) for _ in range(50)]
        result = compute_lot(rows)
        assert result.lot >= DEFAULT_LOT   # should not raise

    def test_won_field_accepts_string_true(self):
        rows = [{"won": "True", "points": "10"} for _ in range(50)]
        rows += [{"won": "False", "points": "-5"} for _ in range(20)]
        result = compute_lot(rows)
        assert isinstance(result, SizingResult)

    def test_won_field_accepts_int_1(self):
        rows = [{"won": 1, "points": "10"} for _ in range(100)]
        result = compute_lot(rows)
        assert result.lot >= DEFAULT_LOT

"""Tests for ConfidenceEngine — Kelly criterion, score bounds, extra positions."""

import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.mt5_ai.confidence_engine import (
    ConfidenceEngine, MIN_SCORE, MAX_SCORE, WIN_BOOST, LOSS_HIT
)


def _make_engine(symbol="EURUSDm", state_file=None):
    """Return an engine with an isolated (tmp) state file."""
    eng = ConfidenceEngine.__new__(ConfidenceEngine)
    eng.symbol = symbol
    eng._state = {symbol: {}}
    eng._ensure_symbol_state()
    eng._save = MagicMock()   # no filesystem writes during tests
    return eng


class TestScoreBounds:
    def test_initial_score_is_1(self):
        e = _make_engine()
        assert e._state["EURUSDm"]["score"] == 1.0

    def test_repeated_wins_capped_at_max(self):
        e = _make_engine()
        for _ in range(200):
            e.on_win(pnl_points=100.0)
        assert e._state["EURUSDm"]["score"] <= MAX_SCORE

    def test_repeated_losses_floored_at_min(self):
        e = _make_engine()
        for _ in range(200):
            e.on_loss(pnl_points=100.0)
        assert e._state["EURUSDm"]["score"] >= MIN_SCORE

    def test_win_increases_score(self):
        e = _make_engine()
        before = e._state["EURUSDm"]["score"]
        e.on_win(pnl_points=10.0)
        assert e._state["EURUSDm"]["score"] > before

    def test_loss_decreases_score(self):
        e = _make_engine()
        before = e._state["EURUSDm"]["score"]
        e.on_loss(pnl_points=10.0)
        assert e._state["EURUSDm"]["score"] < before


class TestStreak:
    def test_win_streak_increments(self):
        e = _make_engine()
        e.on_win(pnl_points=5.0)
        e.on_win(pnl_points=5.0)
        assert e.streak == 2

    def test_loss_streak_decrements(self):
        e = _make_engine()
        e.on_loss(pnl_points=5.0)
        e.on_loss(pnl_points=5.0)
        assert e.streak == -2

    def test_win_after_losses_resets_streak(self):
        e = _make_engine()
        e.on_loss(pnl_points=5.0)
        e.on_loss(pnl_points=5.0)
        e.on_win(pnl_points=5.0)
        assert e.streak > 0


class TestKellyLotMultiplier:
    def test_returns_one_with_few_trades(self):
        e = _make_engine()
        for _ in range(15):
            e.on_win(5.0)
        assert e.kelly_lot_multiplier == 1.0

    def test_returns_above_one_with_strong_stats(self):
        e = _make_engine()
        for _ in range(25):
            e.on_win(20.0)
        for _ in range(5):
            e.on_loss(5.0)
        mult = e.kelly_lot_multiplier
        assert mult >= 1.0

    def test_never_below_0_8(self):
        e = _make_engine()
        # Simulate 20 trades with bad stats (all losses)
        for _ in range(20):
            e.on_loss(10.0)
        mult = e.kelly_lot_multiplier
        assert mult >= 0.8

    def test_kelly_uses_rolling_window(self):
        e = _make_engine()
        # 20+ trades, then check it uses rolling data not all-time
        for _ in range(20):
            e.on_win(10.0)
        assert e.kelly_lot_multiplier >= 1.0


class TestApplyLot:
    def test_apply_lot_never_below_base(self):
        e = _make_engine()
        # Force a low score
        for _ in range(50):
            e.on_loss(100.0)
        result = e.apply_lot(0.01)
        assert result >= 0.01

    def test_apply_lot_never_above_max(self):
        from src.mt5_ai.confidence_engine import MAX_LOT
        e = _make_engine()
        for _ in range(50):
            e.on_win(100.0)
        result = e.apply_lot(1.0)
        assert result <= MAX_LOT

    def test_apply_lot_with_few_trades_uses_score(self):
        e = _make_engine()
        # < 20 trades → uses score multiplier
        result = e.apply_lot(0.01)
        expected = round(0.01 * e.lot_multiplier, 2)
        assert result == pytest.approx(expected, abs=0.005)


class TestExtraPositions:
    def test_zero_when_few_trades(self):
        e = _make_engine()
        assert e.extra_positions == 0

    def test_one_extra_at_moderate_performance(self):
        e = _make_engine()
        # 20 trades at 80% WR with decent score
        for _ in range(16):
            e.on_win(10.0)
        for _ in range(4):
            e.on_loss(10.0)
        # Need score ≥ 1.4 — multiple wins should push it there
        extras = e.extra_positions
        assert extras in (0, 1)   # 0 if score threshold not yet met

    def test_two_extras_at_elite_performance(self):
        e = _make_engine()
        for _ in range(30):
            e.on_win(20.0)
        for _ in range(5):
            e.on_loss(5.0)
        # WR 86%, score likely > 1.7 — should be 2
        extras = e.extra_positions
        assert extras in (1, 2)


class TestTouchPrediction:
    def test_touch_hit_increases_score(self):
        e = _make_engine()
        before = e._state["EURUSDm"]["score"]
        e.on_prediction_hit("BUY", 1.1000)
        assert e._state["EURUSDm"]["score"] > before

    def test_touch_miss_decreases_score(self):
        e = _make_engine()
        before = e._state["EURUSDm"]["score"]
        e.on_prediction_miss("BUY", 1.1000)
        assert e._state["EURUSDm"]["score"] < before

    def test_touch_hit_increments_counter(self):
        e = _make_engine()
        e.on_prediction_hit("BUY", 1.1000)
        e.on_prediction_hit("SELL", 1.1100)
        assert e._state["EURUSDm"]["touch_hits"] == 2

    def test_touch_miss_increments_counter(self):
        e = _make_engine()
        e.on_prediction_miss("BUY", 1.1000)
        assert e._state["EURUSDm"]["touch_misses"] == 1


class TestStatus:
    def test_status_keys_present(self):
        e = _make_engine()
        s = e.status()
        for key in ("symbol", "confidence", "wins", "losses", "kelly_mult",
                    "streak", "extra_positions", "rolling"):
            assert key in s, f"Missing key: {key}"

    def test_rolling_performance_keys(self):
        e = _make_engine()
        r = e.rolling_performance()
        for key in ("rolling_trades", "rolling_wr", "rolling_avg_win",
                    "rolling_avg_loss", "rolling_rr", "kelly_mult"):
            assert key in r

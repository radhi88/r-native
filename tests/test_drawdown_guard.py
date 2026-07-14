"""Tests for DrawdownGuard — cooldown rules, lot forcing, threshold boosting."""

import pytest
from src.mt5_ai.agents.drawdown_guard import DrawdownGuard


class TestDrawdownGuard:
    def setup_method(self):
        self.guard = DrawdownGuard(symbol="XAUUSDm", min_lot=0.01)

    # ── Initial state ─────────────────────────────────────────────────────────

    def test_initial_state_allows_entry(self):
        assert self.guard.tick() is True

    def test_initial_status(self):
        s = self.guard.status()
        assert s["consec_losses"] == 0
        assert s["pause_bars_left"] == 0
        assert s["force_min_lot"] is False
        assert s["boost_thresh"] is False

    # ── Win resets everything ─────────────────────────────────────────────────

    def test_win_resets_after_losses(self):
        self.guard.on_trade_closed(-10.0)
        self.guard.on_trade_closed(-10.0)
        self.guard.on_trade_closed(5.0)   # profit
        s = self.guard.status()
        assert s["consec_losses"] == 0
        assert s["pause_bars_left"] == 0
        assert s["force_min_lot"] is False
        assert s["boost_thresh"] is False

    # ── 1 consecutive loss ────────────────────────────────────────────────────

    def test_one_loss_pauses_10_bars(self):
        self.guard.on_trade_closed(-5.0)
        assert self.guard.status()["pause_bars_left"] == 10

    def test_one_loss_no_lot_force(self):
        self.guard.on_trade_closed(-5.0)
        assert self.guard.status()["force_min_lot"] is False

    def test_one_loss_no_thresh_boost(self):
        self.guard.on_trade_closed(-5.0)
        assert self.guard.status()["boost_thresh"] is False

    def test_tick_counts_down_pause(self):
        self.guard.on_trade_closed(-5.0)
        self.guard.tick()   # 9 remaining
        assert self.guard.status()["pause_bars_left"] == 9

    def test_tick_returns_false_during_pause(self):
        self.guard.on_trade_closed(-5.0)
        result = self.guard.tick()
        assert result is False

    def test_tick_returns_true_after_pause_expires(self):
        self.guard.on_trade_closed(-5.0)
        for _ in range(10):
            self.guard.tick()
        assert self.guard.tick() is True

    # ── 2 consecutive losses ──────────────────────────────────────────────────

    def test_two_losses_pauses_30_bars(self):
        self.guard.on_trade_closed(-5.0)
        self.guard.on_trade_closed(-5.0)
        assert self.guard.status()["pause_bars_left"] == 30

    def test_two_losses_boosts_thresholds(self):
        self.guard.on_trade_closed(-5.0)
        self.guard.on_trade_closed(-5.0)
        assert self.guard.status()["boost_thresh"] is True

    def test_two_losses_no_lot_force(self):
        self.guard.on_trade_closed(-5.0)
        self.guard.on_trade_closed(-5.0)
        assert self.guard.status()["force_min_lot"] is False

    def test_two_losses_threshold_adjustment(self):
        self.guard.on_trade_closed(-5.0)
        self.guard.on_trade_closed(-5.0)
        new_buy, new_sell = self.guard.adjust_thresholds(0.60, 0.40)
        assert new_buy > 0.60
        assert new_sell < 0.40

    # ── 3+ consecutive losses ─────────────────────────────────────────────────

    def test_three_losses_pauses_60_bars(self):
        for _ in range(3):
            self.guard.on_trade_closed(-5.0)
        assert self.guard.status()["pause_bars_left"] == 60

    def test_three_losses_forces_min_lot(self):
        for _ in range(3):
            self.guard.on_trade_closed(-5.0)
        assert self.guard.status()["force_min_lot"] is True

    def test_three_losses_boost_thresh(self):
        for _ in range(3):
            self.guard.on_trade_closed(-5.0)
        assert self.guard.status()["boost_thresh"] is True

    def test_force_min_lot_overrides_requested(self):
        for _ in range(3):
            self.guard.on_trade_closed(-5.0)
        assert self.guard.adjust_lot(0.10) == 0.01

    # ── Threshold adjustment caps ─────────────────────────────────────────────

    def test_threshold_adjustment_caps_at_0_9(self):
        for _ in range(2):
            self.guard.on_trade_closed(-5.0)
        buy, _ = self.guard.adjust_thresholds(0.88, 0.40)
        assert buy <= 0.90

    def test_threshold_adjustment_floors_sell_at_0_1(self):
        for _ in range(2):
            self.guard.on_trade_closed(-5.0)
        _, sell = self.guard.adjust_thresholds(0.60, 0.12)
        assert sell >= 0.10

    # ── Lot adjustment without force ─────────────────────────────────────────

    def test_adjust_lot_passthrough_when_no_force(self):
        self.guard.on_trade_closed(-5.0)  # 1 loss — no lot force
        assert self.guard.adjust_lot(0.05) == 0.05

    # ── Multiple loss accumulation ────────────────────────────────────────────

    def test_five_losses_still_60_bars(self):
        for _ in range(5):
            self.guard.on_trade_closed(-5.0)
        s = self.guard.status()
        assert s["consec_losses"] == 5
        assert s["pause_bars_left"] == 60  # same cap

    # ── Zero pnl treated as loss ──────────────────────────────────────────────

    def test_zero_pnl_treated_as_loss(self):
        self.guard.on_trade_closed(0.0)
        assert self.guard.status()["consec_losses"] == 1

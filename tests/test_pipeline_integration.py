"""
Integration test skeletons — signal pipeline, risk gate, lot sizing chain.

These tests exercise the full logical path from raw journal data through
risk checks to execution without touching MT5 or filesystem.
Each test is marked with the modules it covers so gaps are trackable.
"""

import pytest
from unittest.mock import MagicMock, patch

# Tested modules (import errors here indicate missing implementations)
from src.mt5_ai.lot_sizer import compute_lot
from src.mt5_ai.agents.drawdown_guard import DrawdownGuard
from src.mt5_ai.execution import PaperExecutor
from src.mt5_ai.trailing_sl import TrailingSLEngine


# ── helpers ───────────────────────────────────────────────────────────────────

def _win_row(pts=10.0):
    return {"won": True, "points": str(pts)}

def _loss_row(pts=10.0):
    return {"won": False, "points": str(-abs(pts))}


# ── Test: lot_sizer → drawdown_guard → executor pipeline ─────────────────────

class TestLotSizerToExecutorPipeline:
    """
    Scenario: compute lot from journal, apply drawdown guard, execute paper trade.
    Covers lot_sizer + drawdown_guard + PaperExecutor integration.
    """

    def test_healthy_equity_executes_at_computed_lot(self):
        journal = [_win_row() for _ in range(50)] + [_loss_row() for _ in range(20)]
        guard = DrawdownGuard("EURUSDm")
        executor = PaperExecutor()

        sizing = compute_lot(journal)
        allowed_lot = guard.adjust_lot(sizing.lot)
        result = executor.execute("EURUSDm", "BUY", 1.1000, lot=allowed_lot)

        assert result["sent"] is True
        assert result["lot"] == allowed_lot

    def test_three_losses_forces_min_lot_into_executor(self):
        journal = [_win_row() for _ in range(100)]   # strong history
        guard = DrawdownGuard("EURUSDm", min_lot=0.01)
        for _ in range(3):
            guard.on_trade_closed(-10.0)   # 3 consecutive losses

        executor = PaperExecutor()
        sizing = compute_lot(journal)
        # Guard should force min_lot regardless of journal tier
        allowed_lot = guard.adjust_lot(sizing.lot)
        result = executor.execute("EURUSDm", "BUY", 1.1000, lot=allowed_lot)

        assert result["lot"] == 0.01

    def test_losing_streak_in_journal_and_guard_both_agree(self):
        # 5 journal losses → lot_sizer drops to Tier 0
        # 3 guard losses → guard forces min_lot anyway
        journal = [_loss_row() for _ in range(5)]
        guard = DrawdownGuard("EURUSDm", min_lot=0.01)
        for _ in range(3):
            guard.on_trade_closed(-5.0)

        sizing = compute_lot(journal)
        from src.mt5_ai.config import DEFAULT_LOT
        assert sizing.lot == DEFAULT_LOT          # lot_sizer Tier 0
        allowed_lot = guard.adjust_lot(sizing.lot)
        assert allowed_lot == 0.01                # guard min


# ── Test: trailing SL → position update pipeline ─────────────────────────────

class TestTrailingSLPipeline:
    """
    Scenario: a position rises through multiple ATR milestones;
    the trailing engine should tighten the SL at each stage.
    """

    def test_buy_position_sl_tightens_through_stages(self):
        engine = TrailingSLEngine()
        entry = 1.1000
        atr = 0.01
        pos = {"side": "BUY", "entry": entry, "sl": 1.0900}
        positions = {"agent1": pos}

        # Stage 1: breakeven (0.5× ATR above entry)
        ups = engine.update(positions, current_price=1.1060, atr_points=atr)
        if ups:
            sl = dict(ups)["agent1"]
            pos["sl"] = sl

        # Stage 2: normal trail (1.5× ATR)
        ups = engine.update(positions, current_price=1.1200, atr_points=atr)
        if ups:
            sl = dict(ups)["agent1"]
            pos["sl"] = sl

        # Stage 3: tight trail (3× ATR)
        ups = engine.update(positions, current_price=1.1330, atr_points=atr)
        if ups:
            sl = dict(ups)["agent1"]
            pos["sl"] = sl

        # At the end, SL must be strictly better than the original
        assert pos["sl"] > 1.0900

    def test_sl_never_widens_on_drawback(self):
        engine = TrailingSLEngine()
        positions = {"agent1": {"side": "BUY", "entry": 1.1000, "sl": 1.0900}}

        # Push price up to set a high peak
        engine.update(positions, current_price=1.1300, atr_points=0.01)

        # Now price dips — SL must NOT decrease
        sl_before = positions["agent1"]["sl"]
        engine.update(positions, current_price=1.1100, atr_points=0.01)
        assert positions["agent1"]["sl"] >= sl_before


# ── Test: guard cooldown blocks execution ─────────────────────────────────────

class TestGuardBlocksExecution:
    """
    Scenario: after 2 consecutive losses the guard should block entry for 30 bars.
    The executor should only be called when guard.tick() is True.
    """

    def test_guard_blocks_after_two_losses(self):
        guard = DrawdownGuard("XAUUSDm")
        guard.on_trade_closed(-5.0)
        guard.on_trade_closed(-5.0)

        executor = PaperExecutor()
        executor.execute = MagicMock()

        # Simulate 10 bars — all should be blocked
        executed = 0
        for _ in range(10):
            if guard.tick():
                executor.execute("XAUUSDm", "BUY", 2300.0)
                executed += 1

        assert executed == 0
        executor.execute.assert_not_called()

    def test_guard_allows_after_cooldown_expires(self):
        guard = DrawdownGuard("XAUUSDm")
        guard.on_trade_closed(-5.0)  # 1 loss → 10 bar cooldown

        executor = PaperExecutor()

        # Drain the 10-bar cooldown
        for _ in range(10):
            guard.tick()

        # Bar 11 should be allowed
        assert guard.tick() is True
        r = executor.execute("XAUUSDm", "BUY", 2300.0)
        assert r["sent"] is True


# ── Test: end-to-end paper round-trip ─────────────────────────────────────────

class TestPaperRoundTrip:
    """
    Scenario: open a paper position → apply trailing SL → record outcome.
    No real MT5 connection needed.
    """

    def test_open_trail_close_cycle(self):
        executor = PaperExecutor()
        trail_engine = TrailingSLEngine()
        guard = DrawdownGuard("EURUSDm")

        # Open
        r = executor.execute("EURUSDm", "BUY", 1.1000, sl=1.0950, tp=1.1100)
        assert r["sent"]

        # Build a live position dict (as coordinator would maintain)
        positions = {"paper": {"side": "BUY", "entry": 1.1000, "sl": 1.0950}}

        # Price advances → trail
        ups = trail_engine.update(positions, current_price=1.1200, atr_points=0.01)
        for name, new_sl in ups:
            positions[name]["sl"] = new_sl

        assert positions["paper"]["sl"] > 1.0950

        # Simulate TP hit (price > TP)
        pnl = 1.1100 - 1.1000   # positive
        guard.on_trade_closed(pnl * 10000)   # in points

        assert guard.status()["consec_losses"] == 0
        assert guard.tick() is True

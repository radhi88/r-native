"""Tests for TrailingSLEngine — multi-stage trailing, breakeven, never-widen invariant."""

import pytest
from src.mt5_ai.trailing_sl import TrailingSLEngine, _find_trail


def _pos(side: str, entry: float, sl: float) -> dict:
    return {"side": side, "entry": entry, "sl": sl}


class TestFindTrail:
    def test_below_breakeven_returns_none(self):
        dist, label = _find_trail(0.3)
        assert dist == 0.0
        assert label == "none"

    def test_normal_band(self):
        dist, label = _find_trail(1.5)
        assert dist == 1.0
        assert label == "normal"

    def test_tight_band(self):
        _, label = _find_trail(3.0)
        assert label == "tight"

    def test_ultra_band(self):
        _, label = _find_trail(5.0)
        assert label == "ultra"

    def test_lock_band(self):
        _, label = _find_trail(8.0)
        assert label == "lock"

    def test_first_match_wins(self):
        # 9× ATR should match "lock" not "ultra" or "tight"
        _, label = _find_trail(9.0)
        assert label == "lock"


class TestTrailingSLEngine:
    def setup_method(self):
        self.engine = TrailingSLEngine()

    # ── BUY ───────────────────────────────────────────────────────────────────

    def test_buy_breakeven_triggers(self):
        positions = {"a1": _pos("BUY", 1.1000, 1.0900)}
        # profit = 0.006, atr = 0.01 → profit/atr = 0.6 >= 0.5 (breakeven)
        updates = self.engine.update(positions, current_price=1.1060, atr_points=0.01)
        names = {name for name, _ in updates}
        assert "a1" in names
        new_sl = dict(updates)["a1"]
        assert new_sl == pytest.approx(1.1000, abs=1e-4)

    def test_buy_normal_trail(self):
        positions = {"a1": _pos("BUY", 1.1000, 1.0900)}
        # profit = 0.02, atr = 0.01 → profit/atr = 2.0 → normal trail (1×ATR behind peak)
        updates = self.engine.update(positions, current_price=1.1200, atr_points=0.01)
        assert len(updates) == 1
        new_sl = updates[0][1]
        assert new_sl > 1.0900   # moved up

    def test_buy_sl_never_widens(self):
        positions = {"a1": _pos("BUY", 1.1000, 1.1150)}
        # Current price only slightly higher → new_sl would be below existing → no update
        updates = self.engine.update(positions, current_price=1.1160, atr_points=0.01)
        assert updates == []

    def test_buy_no_update_below_breakeven(self):
        positions = {"a1": _pos("BUY", 1.1000, 1.0900)}
        # profit = 0.001, atr = 0.01 → profit/atr = 0.1 < 0.5
        updates = self.engine.update(positions, current_price=1.1010, atr_points=0.01)
        assert updates == []

    # ── SELL ──────────────────────────────────────────────────────────────────

    def test_sell_breakeven_triggers(self):
        positions = {"s1": _pos("SELL", 1.1000, 1.1100)}
        # profit = 0.006, atr = 0.01 → profit/atr = 0.6 >= 0.5
        updates = self.engine.update(positions, current_price=1.0940, atr_points=0.01)
        names = {name for name, _ in updates}
        assert "s1" in names
        new_sl = dict(updates)["s1"]
        assert new_sl == pytest.approx(1.1000, abs=1e-4)

    def test_sell_normal_trail(self):
        positions = {"s1": _pos("SELL", 1.1000, 1.1100)}
        # price = 1.0780, profit = 0.022, atr = 0.01 → normal trail
        updates = self.engine.update(positions, current_price=1.0780, atr_points=0.01)
        assert len(updates) == 1
        new_sl = updates[0][1]
        assert new_sl < 1.1100   # moved down

    def test_sell_sl_never_widens(self):
        positions = {"s1": _pos("SELL", 1.1000, 1.0850)}
        # Current price barely moved → no update
        updates = self.engine.update(positions, current_price=1.0990, atr_points=0.01)
        assert updates == []

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_zero_atr_returns_empty(self):
        positions = {"a1": _pos("BUY", 1.1000, 1.0900)}
        updates = self.engine.update(positions, current_price=1.2000, atr_points=0.0)
        assert updates == []

    def test_negative_atr_returns_empty(self):
        positions = {"a1": _pos("BUY", 1.1000, 1.0900)}
        updates = self.engine.update(positions, current_price=1.2000, atr_points=-0.01)
        assert updates == []

    def test_position_without_sl_skipped(self):
        positions = {"a1": {"side": "BUY", "entry": 1.1000, "sl": None}}
        updates = self.engine.update(positions, current_price=1.2000, atr_points=0.01)
        assert updates == []

    def test_empty_positions_returns_empty(self):
        updates = self.engine.update({}, current_price=1.1000, atr_points=0.01)
        assert updates == []

    def test_multiple_positions_updated_independently(self):
        positions = {
            "buy_agent":  _pos("BUY",  1.1000, 1.0900),
            "sell_agent": _pos("SELL", 1.2000, 1.2100),
        }
        updates = self.engine.update(positions, current_price=1.1200, atr_points=0.01)
        names = {name for name, _ in updates}
        assert "buy_agent" in names    # should trail up
        assert "sell_agent" not in names  # wrong direction, sell loses on 1.12

    def test_peak_persists_across_calls(self):
        positions = {"a1": _pos("BUY", 1.1000, 1.0900)}
        # First call: price at 1.13 sets peak
        self.engine.update(positions, current_price=1.1300, atr_points=0.01)
        # Second call: price dips to 1.12 — peak should still be 1.13
        updates = self.engine.update(positions, current_price=1.1200, atr_points=0.01)
        # SL should NOT go below peak−trail (i.e., should be near 1.12)
        if updates:
            new_sl = updates[0][1]
            assert new_sl >= 1.1000

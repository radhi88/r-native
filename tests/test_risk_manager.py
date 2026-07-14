"""
test_risk_manager.py
--------------------
Unit tests for RiskManager.validate() covering all 6 guard paths and their
edge cases. MT5 / config deps are patched so no live connection is needed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mt5_ai.core.signal_schema import DecisionResult, Direction
from mt5_ai.core.risk_manager import RiskManager


# ── Helpers ───────────────────────────────────────────────────────────────────

def _decision(action: Direction = Direction.BUY, confidence: float = 0.75) -> DecisionResult:
    return DecisionResult(
        action=action, symbol="XAUUSDm", timeframe="M5", confidence=confidence
    )


def _rm_with_config(
    kill_switch: bool = False,
    max_spread: dict | float = {"XAUUSDm": 350, "default": 350},
    max_positions: int = 3,
    max_dd: float = 2.0,
    min_conf: float = 0.45,
    max_lot: float = 0.10,
):
    """Return a RiskManager whose config values are fully controlled."""
    def _get(key: str):
        mapping = {
            "risk.max_spread_points": max_spread,
            "risk.max_open_positions": max_positions,
            "risk.max_daily_loss_percent": max_dd,
            "confidence.min_decision_confidence": min_conf,
            "risk.max_lot": max_lot,
        }
        return mapping.get(key)

    with (
        patch("mt5_ai.core.risk_manager.get", side_effect=_get),
        patch("mt5_ai.core.risk_manager.is_kill_switch", return_value=kill_switch),
        patch("mt5_ai.core.risk_manager.log_risk"),
        patch("mt5_ai.core.risk_manager.spread_quality", return_value={"spread_quality": "normal"}),
    ):
        rm = RiskManager()
    return rm, _get, kill_switch


# ── HOLD / non-trade actions pass through ─────────────────────────────────────

@pytest.mark.parametrize("action", [Direction.HOLD, Direction.CLOSE, Direction.TRAIL_ONLY])
def test_non_trade_actions_are_auto_approved(action):
    """HOLD / CLOSE / TRAIL_ONLY should bypass all guards and return approved."""
    rm = RiskManager()
    decision = _decision(action=action)
    with (
        patch("mt5_ai.core.risk_manager.is_kill_switch", return_value=False),
        patch("mt5_ai.core.risk_manager.log_risk"),
    ):
        result = rm.validate(decision, "XAUUSDm")
    assert result.approved is True
    assert result.reason == "no_trade_action"


# ── Kill switch ───────────────────────────────────────────────────────────────

def test_kill_switch_blocks_trade():
    decision = _decision(Direction.BUY)
    rm = RiskManager()
    with (
        patch("mt5_ai.core.risk_manager.is_kill_switch", return_value=True),
        patch("mt5_ai.core.risk_manager.get", return_value=None),
        patch("mt5_ai.core.risk_manager.log_risk"),
        patch("mt5_ai.core.risk_manager.spread_quality", return_value={"spread_quality": "normal"}),
    ):
        result = rm.validate(decision, "XAUUSDm")
    assert result.approved is False
    assert "kill_switch" in result.blocks


def test_kill_switch_inactive_does_not_block():
    decision = _decision(Direction.BUY)
    rm = RiskManager()
    with (
        patch("mt5_ai.core.risk_manager.is_kill_switch", return_value=False),
        patch("mt5_ai.core.risk_manager.get", side_effect=lambda k: {
            "risk.max_spread_points": {"default": 350},
            "risk.max_open_positions": 3,
            "risk.max_daily_loss_percent": 2.0,
            "confidence.min_decision_confidence": 0.45,
            "risk.max_lot": 0.10,
        }.get(k)),
        patch("mt5_ai.core.risk_manager.log_risk"),
        patch("mt5_ai.core.risk_manager.spread_quality", return_value={"spread_quality": "normal"}),
    ):
        result = rm.validate(decision, "XAUUSDm", spread_points=100)
    assert "kill_switch" not in result.blocks


# ── Spread guard ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("spread,expected_ok", [
    (100, True),
    (350, True),   # equal to limit — still OK
    (351, False),  # just over limit — blocked
    (9999, False),
])
def test_spread_guard(spread, expected_ok):
    decision = _decision(Direction.BUY)
    rm = RiskManager()
    with (
        patch("mt5_ai.core.risk_manager.is_kill_switch", return_value=False),
        patch("mt5_ai.core.risk_manager.get", side_effect=lambda k: {
            "risk.max_spread_points": {"XAUUSDm": 350, "default": 350},
            "risk.max_open_positions": 10,
            "risk.max_daily_loss_percent": 99.0,
            "confidence.min_decision_confidence": 0.0,
            "risk.max_lot": 0.10,
        }.get(k)),
        patch("mt5_ai.core.risk_manager.log_risk"),
        patch("mt5_ai.core.risk_manager.spread_quality", return_value={
            "spread_quality": "blocked" if spread > 350 else "normal"
        }),
    ):
        result = rm.validate(decision, "XAUUSDm", spread_points=spread)
    assert result.spread_ok is expected_ok


def test_spread_config_fallback_to_default():
    """Symbol not in spread dict → falls back to 'default' key."""
    decision = _decision(Direction.SELL)
    rm = RiskManager()
    with (
        patch("mt5_ai.core.risk_manager.is_kill_switch", return_value=False),
        patch("mt5_ai.core.risk_manager.get", side_effect=lambda k: {
            "risk.max_spread_points": {"default": 200},  # no symbol-specific key
            "risk.max_open_positions": 10,
            "risk.max_daily_loss_percent": 99.0,
            "confidence.min_decision_confidence": 0.0,
            "risk.max_lot": 0.10,
        }.get(k)),
        patch("mt5_ai.core.risk_manager.log_risk"),
        patch("mt5_ai.core.risk_manager.spread_quality", return_value={"spread_quality": "blocked"}),
    ):
        result = rm.validate(decision, "EURUSDm", spread_points=201)  # above default 200
    assert result.spread_ok is False


def test_spread_config_scalar_value():
    """Scalar spread config (not dict) is treated as the limit directly."""
    decision = _decision(Direction.BUY)
    rm = RiskManager()
    with (
        patch("mt5_ai.core.risk_manager.is_kill_switch", return_value=False),
        patch("mt5_ai.core.risk_manager.get", side_effect=lambda k: {
            "risk.max_spread_points": 100,  # scalar
            "risk.max_open_positions": 10,
            "risk.max_daily_loss_percent": 99.0,
            "confidence.min_decision_confidence": 0.0,
            "risk.max_lot": 0.10,
        }.get(k)),
        patch("mt5_ai.core.risk_manager.log_risk"),
        patch("mt5_ai.core.risk_manager.spread_quality", return_value={"spread_quality": "normal"}),
    ):
        result = rm.validate(decision, "XAUUSDm", spread_points=50)
    assert result.spread_ok is True


# ── Position limit ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("open_pos,limit,expected_ok", [
    (0, 3, True),
    (2, 3, True),
    (3, 3, False),  # equal to limit — blocked (strictly less than)
    (10, 3, False),
])
def test_position_limit_guard(open_pos, limit, expected_ok):
    decision = _decision(Direction.BUY)
    rm = RiskManager()
    with (
        patch("mt5_ai.core.risk_manager.is_kill_switch", return_value=False),
        patch("mt5_ai.core.risk_manager.get", side_effect=lambda k: {
            "risk.max_spread_points": {"default": 999},
            "risk.max_open_positions": limit,
            "risk.max_daily_loss_percent": 99.0,
            "confidence.min_decision_confidence": 0.0,
            "risk.max_lot": 0.10,
        }.get(k)),
        patch("mt5_ai.core.risk_manager.log_risk"),
        patch("mt5_ai.core.risk_manager.spread_quality", return_value={"spread_quality": "normal"}),
    ):
        result = rm.validate(decision, "XAUUSDm", open_positions=open_pos)
    assert result.position_limit_ok is expected_ok


# ── Daily loss guard ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("daily_loss,max_dd,expected_ok", [
    (0.0, 2.0, True),
    (1.99, 2.0, True),
    (2.0, 2.0, False),   # equal — blocked
    (5.0, 2.0, False),
])
def test_daily_loss_guard(daily_loss, max_dd, expected_ok):
    decision = _decision(Direction.SELL)
    rm = RiskManager()
    with (
        patch("mt5_ai.core.risk_manager.is_kill_switch", return_value=False),
        patch("mt5_ai.core.risk_manager.get", side_effect=lambda k: {
            "risk.max_spread_points": {"default": 999},
            "risk.max_open_positions": 10,
            "risk.max_daily_loss_percent": max_dd,
            "confidence.min_decision_confidence": 0.0,
            "risk.max_lot": 0.10,
        }.get(k)),
        patch("mt5_ai.core.risk_manager.log_risk"),
        patch("mt5_ai.core.risk_manager.spread_quality", return_value={"spread_quality": "normal"}),
    ):
        result = rm.validate(decision, "XAUUSDm", daily_loss_pct=daily_loss)
    assert result.daily_loss_ok is expected_ok


# ── Confidence floor ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("conf,floor,expect_block", [
    (0.80, 0.45, False),
    (0.45, 0.45, False),   # equal — just passes
    (0.44, 0.45, True),
    (0.0, 0.45, True),
])
def test_confidence_floor(conf, floor, expect_block):
    decision = _decision(Direction.BUY, confidence=conf)
    rm = RiskManager()
    with (
        patch("mt5_ai.core.risk_manager.is_kill_switch", return_value=False),
        patch("mt5_ai.core.risk_manager.get", side_effect=lambda k: {
            "risk.max_spread_points": {"default": 999},
            "risk.max_open_positions": 10,
            "risk.max_daily_loss_percent": 99.0,
            "confidence.min_decision_confidence": floor,
            "risk.max_lot": 0.10,
        }.get(k)),
        patch("mt5_ai.core.risk_manager.log_risk"),
        patch("mt5_ai.core.risk_manager.spread_quality", return_value={"spread_quality": "normal"}),
    ):
        result = rm.validate(decision, "XAUUSDm")
    conf_blocks = [b for b in result.blocks if b.startswith("confidence_")]
    assert bool(conf_blocks) is expect_block


# ── Multiple blocks accumulate ────────────────────────────────────────────────

def test_multiple_blocks_all_reported():
    """Spread + position + daily_loss all breached → all appear in blocks list."""
    decision = _decision(Direction.BUY, confidence=0.9)
    rm = RiskManager()
    with (
        patch("mt5_ai.core.risk_manager.is_kill_switch", return_value=False),
        patch("mt5_ai.core.risk_manager.get", side_effect=lambda k: {
            "risk.max_spread_points": {"default": 100},
            "risk.max_open_positions": 1,
            "risk.max_daily_loss_percent": 1.0,
            "confidence.min_decision_confidence": 0.45,
            "risk.max_lot": 0.10,
        }.get(k)),
        patch("mt5_ai.core.risk_manager.log_risk"),
        patch("mt5_ai.core.risk_manager.spread_quality", return_value={"spread_quality": "blocked"}),
    ):
        result = rm.validate(
            decision, "XAUUSDm",
            spread_points=500,    # >100 → blocked
            open_positions=5,     # >=1 → blocked
            daily_loss_pct=2.0,   # >=1.0 → blocked
        )
    assert result.approved is False
    assert len(result.blocks) >= 3


# ── Approved path sets correct lot ───────────────────────────────────────────

def test_approved_path_returns_max_lot():
    decision = _decision(Direction.BUY, confidence=0.85)
    rm = RiskManager()
    with (
        patch("mt5_ai.core.risk_manager.is_kill_switch", return_value=False),
        patch("mt5_ai.core.risk_manager.get", side_effect=lambda k: {
            "risk.max_spread_points": {"default": 999},
            "risk.max_open_positions": 10,
            "risk.max_daily_loss_percent": 99.0,
            "confidence.min_decision_confidence": 0.0,
            "risk.max_lot": 0.05,
        }.get(k)),
        patch("mt5_ai.core.risk_manager.log_risk"),
        patch("mt5_ai.core.risk_manager.spread_quality", return_value={"spread_quality": "normal"}),
    ):
        result = rm.validate(decision, "XAUUSDm")
    assert result.approved is True
    assert result.max_lot == pytest.approx(0.05)
    assert result.adjusted_lot == pytest.approx(0.05)

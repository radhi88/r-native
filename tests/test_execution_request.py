"""
test_execution_request.py
-------------------------
Unit tests for ExecutionRequest.is_valid() covering every decision branch,
and for the SignalProposal guard (can_execute must be False).

Pure schema tests — no MT5, no config, no disk I/O.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mt5_ai.core.signal_schema import (
    Direction,
    ExecutionRequest,
    SignalProposal,
    RiskDecision,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _buy(magic: int = 12345, lot: float = 0.01, sl: float = 1900.0) -> ExecutionRequest:
    return ExecutionRequest(
        action=Direction.BUY,
        symbol="XAUUSDm",
        lot=lot,
        magic=magic,
        sl=sl,
    )


def _sell(magic: int = 12345, lot: float = 0.01, sl: float = 2100.0) -> ExecutionRequest:
    return ExecutionRequest(
        action=Direction.SELL,
        symbol="XAUUSDm",
        lot=lot,
        magic=magic,
        sl=sl,
    )


def _close(ticket: int = 999, lot: float = 0.01, magic: int = 12345) -> ExecutionRequest:
    return ExecutionRequest(
        action=Direction.CLOSE,
        symbol="XAUUSDm",
        lot=lot,
        position_ticket=ticket,
        magic=magic,
    )


def _trail(ticket: int = 999, magic: int = 12345) -> ExecutionRequest:
    return ExecutionRequest(
        action=Direction.TRAIL_ONLY,
        symbol="XAUUSDm",
        lot=0.0,
        position_ticket=ticket,
        magic=magic,
    )


def _reduce(ticket: int = 999, lot: float = 0.005, magic: int = 12345) -> ExecutionRequest:
    return ExecutionRequest(
        action=Direction.REDUCE,
        symbol="XAUUSDm",
        lot=lot,
        position_ticket=ticket,
        magic=magic,
    )


# ── Magic number required ─────────────────────────────────────────────────────

def test_magic_zero_invalid():
    ok, reason = _buy(magic=0).is_valid()
    assert ok is False
    assert "magic" in reason.lower()


def test_magic_nonzero_does_not_block_on_its_own():
    ok, _ = _buy(magic=1).is_valid()
    assert ok is True


# ── BUY — lot and SL requirements ────────────────────────────────────────────

@pytest.mark.parametrize("lot,sl,expect_ok", [
    (0.01,  1900.0, True),    # valid
    (0.0,   1900.0, False),   # lot zero
    (-0.01, 1900.0, False),   # lot negative
    (0.01,  0.0,   False),    # SL zero
    (0.01, -1.0,   False),    # SL negative
])
def test_buy_lot_and_sl_validation(lot, sl, expect_ok):
    ok, reason = _buy(lot=lot, sl=sl).is_valid()
    assert ok is expect_ok


def test_buy_tp_not_required():
    req = ExecutionRequest(
        action=Direction.BUY, symbol="XAUUSDm",
        lot=0.01, magic=99, sl=1900.0, tp=0.0
    )
    ok, _ = req.is_valid()
    assert ok is True


# ── SELL — same guards as BUY ─────────────────────────────────────────────────

@pytest.mark.parametrize("lot,sl,expect_ok", [
    (0.01,  2100.0, True),
    (0.0,   2100.0, False),
    (0.01,  0.0,   False),
])
def test_sell_lot_and_sl_validation(lot, sl, expect_ok):
    ok, _ = _sell(lot=lot, sl=sl).is_valid()
    assert ok is expect_ok


# ── CLOSE ─────────────────────────────────────────────────────────────────────

def test_close_valid():
    ok, _ = _close().is_valid()
    assert ok is True


def test_close_zero_lot_valid():
    ok, _ = _close(lot=0.0).is_valid()
    assert ok is True


def test_close_negative_lot_invalid():
    ok, reason = _close(lot=-0.01).is_valid()
    assert ok is False
    assert "lot" in reason.lower()


def test_close_missing_ticket_invalid():
    ok, reason = _close(ticket=0).is_valid()
    assert ok is False
    assert "ticket" in reason.lower()


# ── TRAIL_ONLY ────────────────────────────────────────────────────────────────

def test_trail_only_valid():
    ok, _ = _trail().is_valid()
    assert ok is True


def test_trail_only_missing_ticket_invalid():
    ok, reason = _trail(ticket=0).is_valid()
    assert ok is False
    assert "ticket" in reason.lower()


def test_trail_only_negative_lot_invalid():
    req = ExecutionRequest(
        action=Direction.TRAIL_ONLY, symbol="XAUUSDm",
        lot=-0.01, position_ticket=999, magic=12345
    )
    ok, reason = req.is_valid()
    assert ok is False
    assert "lot" in reason.lower()


# ── REDUCE ────────────────────────────────────────────────────────────────────

def test_reduce_valid():
    ok, _ = _reduce().is_valid()
    assert ok is True


def test_reduce_zero_lot_invalid():
    ok, reason = _reduce(lot=0.0).is_valid()
    assert ok is False
    assert "lot" in reason.lower()


def test_reduce_missing_ticket_invalid():
    ok, reason = _reduce(ticket=0).is_valid()
    assert ok is False
    assert "ticket" in reason.lower()


# ── No action — HOLD ─────────────────────────────────────────────────────────

def test_hold_action_needs_magic_only():
    """HOLD falls through to the base magic check; lot/sl not required."""
    req = ExecutionRequest(
        action=Direction.HOLD, symbol="XAUUSDm",
        lot=0.0, magic=12345
    )
    ok, _ = req.is_valid()
    assert ok is True


def test_hold_magic_zero_invalid():
    req = ExecutionRequest(
        action=Direction.HOLD, symbol="XAUUSDm",
        lot=0.0, magic=0
    )
    ok, _ = req.is_valid()
    assert ok is False


# ── SignalProposal — can_execute guard ────────────────────────────────────────

def test_signal_proposal_can_execute_true_raises():
    with pytest.raises(ValueError, match="can_execute=False"):
        SignalProposal(
            source="test_agent",
            strategy_id="X",
            symbol="XAUUSDm",
            timeframe="M5",
            direction=Direction.BUY,
            confidence=0.8,
            can_execute=True,   # must be rejected
        )


def test_signal_proposal_can_execute_false_succeeds():
    prop = SignalProposal(
        source="test_agent",
        strategy_id="X",
        symbol="XAUUSDm",
        timeframe="M5",
        direction=Direction.BUY,
        confidence=0.8,
        can_execute=False,
    )
    assert prop.can_execute is False


# ── Confidence clamping ───────────────────────────────────────────────────────

@pytest.mark.parametrize("raw_conf,expected_conf", [
    (1.5,  1.0),   # above 1.0 → clamped to 1.0
    (-0.3, 0.0),   # below 0.0 → clamped to 0.0
    (0.75, 0.75),  # in range → unchanged
    (0.0,  0.0),
    (1.0,  1.0),
])
def test_signal_proposal_confidence_clamped(raw_conf, expected_conf):
    prop = SignalProposal(
        source="agent",
        strategy_id="X",
        symbol="XAUUSDm",
        timeframe="M5",
        direction=Direction.BUY,
        confidence=raw_conf,
        can_execute=False,
    )
    assert prop.confidence == pytest.approx(expected_conf)


# ── RiskDecision defaults ─────────────────────────────────────────────────────

def test_risk_decision_defaults_all_ok():
    rd = RiskDecision(approved=True, reason="all_ok")
    assert rd.spread_ok is True
    assert rd.margin_ok is True
    assert rd.daily_loss_ok is True
    assert rd.position_limit_ok is True
    assert rd.blocks == []
    assert rd.warnings == []


def test_risk_decision_rejected_fields():
    rd = RiskDecision(
        approved=False, reason="spread_blocked",
        blocks=["spread_500>350"],
        spread_ok=False,
    )
    assert rd.approved is False
    assert rd.spread_ok is False
    assert "spread_500>350" in rd.blocks

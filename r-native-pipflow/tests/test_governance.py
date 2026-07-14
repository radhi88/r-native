"""Tests for agent_governance — rate limits, cooldowns, hard pause.

Uses a fresh Governance() instance per test (the module singleton would
persist counters across tests). The instance writes to a temp path-ish
file but Linux can still write to a fake Windows path inside /tmp safely
because we monkey-patch GOV_STATE.
"""
from __future__ import annotations

import os
import sys
import importlib.util
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

_modname = "agent_governance_under_test"
spec = importlib.util.spec_from_file_location(
    _modname, os.path.join(REPO, "agent_governance.py"))
gov = importlib.util.module_from_spec(spec)
sys.modules[_modname] = gov
spec.loader.exec_module(gov)


def _fresh(policy=None) -> "gov.Governance":
    # Redirect state file to /tmp so we don't fight Windows paths
    tmp = Path(tempfile.mkdtemp()) / "gov.json"
    gov.GOV_STATE = tmp
    gov.GOV_LOG   = tmp.parent / "gov.jsonl"
    return gov.Governance(policy=policy)


def test_default_allow():
    g = _fresh()
    ok, reason = g.can_trade("ag1", "X")
    assert ok, reason
    print("OK test_default_allow")


def test_hourly_rate_limit():
    g = _fresh(gov.GovernancePolicy(max_trades_per_hour_per_agent=3))
    for _ in range(3):
        g.record_trade("ag", "X", "open")
    ok, reason = g.can_trade("ag", "X")
    assert ok is False
    assert "hourly cap" in reason
    print("OK test_hourly_rate_limit")


def test_daily_symbol_cap():
    g = _fresh(gov.GovernancePolicy(max_trades_per_day_per_symbol=2))
    g.record_trade("ag", "X", "open")
    g.record_trade("ag", "X", "open")
    ok, reason = g.can_trade("ag", "X")
    assert ok is False
    assert "daily cap" in reason
    print("OK test_daily_symbol_cap")


def test_consecutive_losses_cooldown():
    g = _fresh(gov.GovernancePolicy(consecutive_losses_pause_threshold=2,
                                     cooldown_after_losses_minutes=60))
    g.record_trade("ag", "X", "loss")
    ok, _ = g.can_trade("ag", "X")
    assert ok is True
    g.record_trade("ag", "X", "loss")
    ok, reason = g.can_trade("ag", "X")
    assert ok is False
    assert "cooldown" in reason
    print("OK test_consecutive_losses_cooldown")


def test_win_resets_streak():
    g = _fresh(gov.GovernancePolicy(consecutive_losses_pause_threshold=2,
                                     cooldown_after_losses_minutes=60))
    g.record_trade("ag", "X", "loss")
    g.record_trade("ag", "X", "win")
    g.record_trade("ag", "X", "loss")
    ok, _ = g.can_trade("ag", "X")
    assert ok is True   # only 1 consecutive loss after the win reset
    print("OK test_win_resets_streak")


def test_hard_pause_blocks_everything():
    g = _fresh()
    g.hard_pause("manual")
    ok, reason = g.can_trade("ag", "X")
    assert ok is False
    assert "account paused" in reason
    g.resume()
    ok, _ = g.can_trade("ag", "X")
    assert ok is True
    print("OK test_hard_pause_blocks_everything")


def test_drawdown_triggers_pause():
    g = _fresh(gov.GovernancePolicy(account_drawdown_hard_pause_pct=5.0))
    triggered, _ = g.check_drawdown(6.0)
    assert triggered
    ok, _ = g.can_trade("ag", "X")
    assert ok is False
    print("OK test_drawdown_triggers_pause")


def test_status_contains_keys():
    g = _fresh()
    g.record_trade("ag1", "X", "open")
    g.record_deploy("X", "ABC123")
    s = g.status()
    assert "policy"  in s and "agents" in s and "deploys_today" in s
    assert s["agents"]["ag1"]["trades_last_hour"] == 1
    assert s["deploys_today"] == 1
    print("OK test_status_contains_keys")


if __name__ == "__main__":
    test_default_allow()
    test_hourly_rate_limit()
    test_daily_symbol_cap()
    test_consecutive_losses_cooldown()
    test_win_resets_streak()
    test_hard_pause_blocks_everything()
    test_drawdown_triggers_pause()
    test_status_contains_keys()
    print("\n✓ all governance tests passed")

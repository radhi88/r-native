"""tests/test_agent_governance.py — unit tests for the agents' constitution.

Verifies the hard safety boundaries of runtime.shared.agent_governance:
  • LOW proposal reaches CONSENSUS_OK at exactly 2 peer approvals
  • money-touching params (lot / risk_pct / ...) auto-escalate to HIGH
  • HIGH can NEVER pass on votes alone (quorum 99 → stays PENDING / NEEDS_CLAUDE)
  • edit_code and crown_genome are ALWAYS HIGH regardless of claimed risk

CRITICAL ISOLATION: the module persists to live JSON under
r_native_v2/data/governance/. Every storage path constant is monkeypatched to a
tmpdir BEFORE any propose/vote call, and a final test asserts the real
proposals.json was untouched (mtime + size unchanged).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

V2_ROOT = Path(r"C:\Users\Radhi\MT5\r_native_v2")
if str(V2_ROOT) not in sys.path:
    sys.path.insert(0, str(V2_ROOT))

from runtime.shared import agent_governance as gov  # noqa: E402

REAL_PROPOSALS = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\governance\proposals.json")
_REAL_STAT_BEFORE = (
    (REAL_PROPOSALS.stat().st_mtime_ns, REAL_PROPOSALS.stat().st_size)
    if REAL_PROPOSALS.exists() else None
)


@pytest.fixture()
def sandbox(monkeypatch, tmp_path):
    """Redirect EVERY storage path the module writes to into a tmpdir."""
    gov_dir = tmp_path / "governance"
    monkeypatch.setattr(gov, "GOV_DIR", gov_dir)
    monkeypatch.setattr(gov, "PROPOSALS_FILE", gov_dir / "proposals.json")
    monkeypatch.setattr(gov, "AUDIT_LOG", gov_dir / "audit.jsonl")
    monkeypatch.setattr(gov, "RESTART_QUEUE", gov_dir / "restart_requests.jsonl")
    monkeypatch.setattr(gov, "OVERRIDES_FILE", tmp_path / "agent_overrides.json")
    return tmp_path


# ──────────────────────────────────────────────────────────────────────────────
# LOW risk: consensus at quorum 2
# ──────────────────────────────────────────────────────────────────────────────
def test_low_reaches_consensus_at_two_approvals(sandbox):
    pid = gov.propose("agent_a", "set_override", "override:ui_theme",
                      {"value": "dark"}, "cosmetic tweak", risk=gov.RISK_LOW)
    st = gov.vote(pid, "agent_b", approve=True)
    assert st == gov.ST_PENDING, "1 approval must NOT reach LOW quorum (2)"
    st = gov.vote(pid, "agent_c", approve=True)
    assert st == gov.ST_CONSENSUS, "2 distinct approvals must reach LOW quorum"
    # and it is now ready for the governor
    assert pid in [p.id for p in gov.approved_ready()]


def test_self_vote_ignored(sandbox):
    pid = gov.propose("agent_a", "set_override", "override:ui_theme",
                      {"value": "dark"}, "cosmetic", risk=gov.RISK_LOW)
    gov.vote(pid, "agent_a", approve=True)          # self-vote → ignored
    st = gov.vote(pid, "agent_b", approve=True)
    assert st == gov.ST_PENDING, "self-vote must not count toward quorum"


# ──────────────────────────────────────────────────────────────────────────────
# Risk-bearing target auto-escalation
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("target", [
    "genome:lot", "genome:XAUUSDm:lot", "genome:risk_pct",
    "config:GLOBAL_MAX_OPEN", "override:trading_enabled", "genome:sl_pts",
])
def test_money_targets_auto_escalate_to_high(sandbox, target):
    pid = gov.propose("agent_a", "tune_param", target,
                      {"value": 0.01}, "sneaky under-claim", risk=gov.RISK_LOW)
    raw = gov._load_all()[pid]
    assert raw["risk"] == gov.RISK_HIGH, (
        f"{target} touches money — claimed LOW must escalate to HIGH")


# ──────────────────────────────────────────────────────────────────────────────
# HIGH can never pass on votes alone
# ──────────────────────────────────────────────────────────────────────────────
def test_high_never_passes_on_votes(sandbox):
    pid = gov.propose("agent_a", "tune_param", "genome:lot",
                      {"value": 9.99}, "moon it", risk=gov.RISK_LOW)  # → HIGH
    for i in range(10):
        st = gov.vote(pid, f"agent_{i}", approve=True)
    assert st not in (gov.ST_CONSENSUS, gov.ST_APPROVED, gov.ST_APPLIED), (
        "HIGH proposal must never become live via peer votes alone")
    # it must sit in Claude's consult queue, not the governor's apply queue
    assert pid in [p.id for p in gov.pending_for_claude()]
    assert pid not in [p.id for p in gov.approved_ready()]


def test_high_requires_claude_to_approve(sandbox):
    pid = gov.propose("agent_a", "set_override", "override:max_open",
                      {"value": 5}, "more slots", risk=gov.RISK_LOW)  # → HIGH
    gov.vote(pid, "agent_b", approve=True)
    st = gov.claude_decide(pid, approve=True, note="reviewed, bounded")
    assert st == gov.ST_APPROVED
    assert pid in [p.id for p in gov.approved_ready()]


# ──────────────────────────────────────────────────────────────────────────────
# edit_code / crown_genome are ALWAYS HIGH
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("action", ["edit_code", "crown_genome"])
@pytest.mark.parametrize("claimed", [gov.RISK_LOW, gov.RISK_MED, gov.RISK_HIGH, "", None])
def test_code_and_crown_always_high(sandbox, action, claimed):
    assert gov.resolve_risk(action, "whatever:target", claimed) == gov.RISK_HIGH
    pid = gov.propose("agent_a", action, "svc:cosmetic_rename",
                      {"diff": "x"}, "claims it is trivial", risk=claimed or "LOW")
    assert gov._load_all()[pid]["risk"] == gov.RISK_HIGH


def test_unknown_action_rejected_on_sight(sandbox):
    with pytest.raises(ValueError):
        gov.propose("agent_a", "rm_rf_everything", "t", {}, "nope")


# ──────────────────────────────────────────────────────────────────────────────
# Peer rejection path
# ──────────────────────────────────────────────────────────────────────────────
def test_two_rejections_kill_a_proposal(sandbox):
    pid = gov.propose("agent_a", "set_override", "override:ui_theme",
                      {"value": "pink"}, "bad idea", risk=gov.RISK_LOW)
    gov.vote(pid, "agent_b", approve=False)
    st = gov.vote(pid, "agent_c", approve=False)
    assert st == gov.ST_REJECTED


# ──────────────────────────────────────────────────────────────────────────────
# SAFETY NET: the real live governance file was never touched
# ──────────────────────────────────────────────────────────────────────────────
def test_zzz_real_proposals_file_untouched():
    """Runs last (zzz): live proposals.json mtime+size must be exactly as they
    were when this module was imported. If this fails, a test leaked writes
    into the LIVE governance store — treat as a P0 test-harness bug."""
    if _REAL_STAT_BEFORE is None:
        pytest.skip("real proposals.json did not exist at import time")
    now = (REAL_PROPOSALS.stat().st_mtime_ns, REAL_PROPOSALS.stat().st_size)
    assert now == _REAL_STAT_BEFORE, (
        "LIVE governance proposals.json changed during tests — isolation broken")

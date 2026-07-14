"""
PlutoBrain Swarm — Agent Roster
================================
The full 45-worker roster from the MEGA AGENT SWARM spec, mapped to reality.

Each agent is either:
  - backed by a deterministic worker function (most of them), OR
  - ESCALATE: a judgment role that pings the human / friday_decision.py on demand.

This is the honest version of "50 agents": the static-analysis roles run for real,
continuously, with no LLM cost. The reasoning roles are marked ESCALATE so they
don't silently pretend to think.
"""
from __future__ import annotations
from dataclasses import dataclass, field

ESCALATE = "ESCALATE"  # role needs human/LLM judgment, not a deterministic worker


@dataclass
class Agent:
    id: str
    role: str
    cluster: str          # ALPHA | BETA | GAMMA | ORCH
    worker: str           # worker function name in workers.py, or ESCALATE
    interval_sec: int     # how often the orchestrator dispatches it
    skills: str = ""
    # runtime state (filled by orchestrator)
    last_run: float = 0.0
    last_status: str = "idle"   # idle | running | ok | error | escalated
    last_summary: str = ""
    pool: str = "cluster"       # cluster | active_pool  (set when mission "done")


# ---------------------------------------------------------------------------
# TIER 1 — Orchestrator
# ---------------------------------------------------------------------------
ORCHESTRATOR = Agent(
    id="ORCH-00", role="Orchestrator_Prime", cluster="ORCH",
    worker="orchestrate", interval_sec=30,
    skills="System design, conflict resolution, resource allocation",
)

# ---------------------------------------------------------------------------
# CLUSTER ALPHA — Architecture & Foundation
# ---------------------------------------------------------------------------
ALPHA = [
    Agent("A-01", "File Mapper",          "ALPHA", "file_mapper",        60,  "Path analysis, dependency graphs"),
    Agent("A-02", "Code Archaeologist",   "ALPHA", "code_archaeologist", 120, "Legacy code analysis, pattern detection"),
    Agent("A-03", "Dependency Tracker",   "ALPHA", "dependency_tracker", 120, "Include resolution, linkage analysis"),
    Agent("A-04", "Conflict Detector",    "ALPHA", "conflict_detector",  180, "Logic analysis, contradiction finder"),
    Agent("A-05", "Duplicate Hunter",     "ALPHA", "duplicate_hunter",   180, "Fuzzy matching, similarity detection"),
    Agent("A-06", "Standardizer",         "ALPHA", "standardizer",       240, "Naming conventions, code style"),
    Agent("A-07", "Header Writer",        "ALPHA", "header_auditor",     240, "Documentation, metadata"),
    Agent("A-08", "Structure Designer",   "ALPHA", ESCALATE,             0,   "OOP design, inheritance"),
    Agent("A-09", "Interface Builder",    "ALPHA", ESCALATE,             0,   "API design, abstraction"),
    Agent("A-10", "Config Manager",       "ALPHA", "config_extractor",   240, "Parameter centralization"),
    Agent("A-11", "Migration Planner",    "ALPHA", ESCALATE,             0,   "Change management, rollback"),
    Agent("A-12", "Backup Guardian",      "ALPHA", "backup_guardian",    300, "Version control, snapshots"),
    Agent("A-13", "Path Optimizer",       "ALPHA", "path_optimizer",     300, "File organization, hierarchy"),
    Agent("A-14", "Legacy Bridge",        "ALPHA", "version_clusterer",  300, "Compatibility, deprecation"),
    Agent("A-15", "Integration Tester",   "ALPHA", ESCALATE,             0,   "System testing, validation"),
]

# ---------------------------------------------------------------------------
# CLUSTER BETA — Intelligence & Enhancement
# ---------------------------------------------------------------------------
BETA = [
    Agent("B-01", "Risk Engineer",     "BETA", ESCALATE,         0,   "Kelly, Optimal F, Monte Carlo"),
    Agent("B-02", "Multi-TF Analyst",  "BETA", ESCALATE,         0,   "Timeframe correlation"),
    Agent("B-03", "Regime Detector",   "BETA", ESCALATE,         0,   "Market state, volatility clustering"),
    Agent("B-04", "Correlation Guard", "BETA", ESCALATE,         0,   "Signal overlap, redundancy"),
    Agent("B-05", "Equity Guardian",   "BETA", ESCALATE,         0,   "Drawdown control, circuit breakers"),
    Agent("B-06", "Session Master",    "BETA", "session_auditor",  240, "Market hours, timezone logic"),
    Agent("B-07", "News Filter",       "BETA", ESCALATE,         0,   "Economic calendar, impact scoring"),
    Agent("B-08", "ATR Engineer",      "BETA", ESCALATE,         0,   "Volatility adaptation, dynamic stops"),
    Agent("B-09", "Partial Close",     "BETA", ESCALATE,         0,   "TP1/TP2/TP3 + breakeven"),
    Agent("B-10", "Recovery Designer", "BETA", ESCALATE,         0,   "Grid, hedge, martingale control"),
    Agent("B-11", "Slippage Guard",    "BETA", ESCALATE,         0,   "Execution quality"),
    Agent("B-12", "Spread Monitor",    "BETA", "spread_auditor",   240, "Spread-based trade filtering"),
    Agent("B-13", "Magic Manager",     "BETA", "magic_manager",    120, "Unique magic numbers, collision check"),
    Agent("B-14", "Memory Watcher",    "BETA", "process_watcher",  120, "Resource tracking, leak detection"),
    Agent("B-15", "Performance Tuner", "BETA", "loc_profiler",     300, "Latency, execution speed"),
]

# ---------------------------------------------------------------------------
# CLUSTER GAMMA — Validation & Operations
# ---------------------------------------------------------------------------
GAMMA = [
    Agent("G-01", "Stress Tester",     "GAMMA", ESCALATE,           0,   "Edge case simulation"),
    Agent("G-02", "Gap Simulator",     "GAMMA", ESCALATE,           0,   "Weekend/news gaps, flash crashes"),
    Agent("G-03", "Spread Spiker",     "GAMMA", ESCALATE,           0,   "Spread spike torture tests"),
    Agent("G-04", "Disconnect Sim",    "GAMMA", ESCALATE,           0,   "Network/broker downtime"),
    Agent("G-05", "Conflict Tester",   "GAMMA", ESCALATE,           0,   "Multi-strategy conflict"),
    Agent("G-06", "Memory Auditor",    "GAMMA", "process_watcher",    120, "Heap tracking, loop detection"),
    Agent("G-07", "Hardcode Hunter",   "GAMMA", "hardcode_hunter",    180, "Static analysis, value extraction"),
    Agent("G-08", "Broker Validator",  "GAMMA", "broker_assumptions", 240, "Assumption checking, portability"),
    Agent("G-09", "Backtest Engine",   "GAMMA", ESCALATE,           0,   "Historical simulation"),
    Agent("G-10", "Forward Tester",    "GAMMA", ESCALATE,           0,   "Paper trading, demo validation"),
    Agent("G-11", "Compiler Guard",    "GAMMA", "compiler_guard",     180, "Syntax check, warning elimination"),
    Agent("G-12", "Documentation Bot", "GAMMA", "doc_auditor",        300, "Auto-doc, README sync"),
    Agent("G-13", "Changelog Keeper",  "GAMMA", "changelog_keeper",   300, "Change tracking, version history"),
    Agent("G-14", "Setup Guide",       "GAMMA", "setup_auditor",      300, "Deployment, configuration"),
    Agent("G-15", "Health Monitor",    "GAMMA", "health_monitor",     60,  "24/7 system health checks"),
]

ALL_AGENTS = [ORCHESTRATOR] + ALPHA + BETA + GAMMA


def roster() -> list[Agent]:
    """Fresh copy of the full roster (orchestrator owns runtime state)."""
    import copy
    return copy.deepcopy(ALL_AGENTS)


def deterministic_count() -> int:
    return sum(1 for a in ALL_AGENTS if a.worker != ESCALATE)


def escalate_count() -> int:
    return sum(1 for a in ALL_AGENTS if a.worker == ESCALATE)

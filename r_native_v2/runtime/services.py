"""runtime/services.py — Service registry / manifest.

Born 2026-05-28 via /design-system Phase 4.

Single source of truth for every long-running process in the system.
Lets the health monitor know what SHOULD be running, what files each
service writes, and what staleness threshold means "this is broken".

CATEGORIES:
  CAPTURE       — feeds data into the system from the broker / world
  ANALYSIS      — classifies / scores incoming data
  DECISION      — picks engines, votes, evaluates genomes
  EXECUTION     — places real trades on MT5
  EVOLUTION     — breeds + promotes genomes
  INFRASTRUCTURE — UI, monitoring, telemetry

Each service entry:
  • module        — python module path (run with `python -m <module>`)
  • category      — one of the 6 above
  • writes        — list of file keys (from tokens.PATHS) that prove it's alive
  • interval_s    — expected write cadence; staleness = 3× this
  • critical      — True if system can't trade without it
  • description   — what it does
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

Category = Literal["CAPTURE", "ANALYSIS", "DECISION", "EXECUTION", "EVOLUTION", "INFRASTRUCTURE"]


@dataclass
class Service:
    name: str
    module: str
    category: Category
    writes: list[str] = field(default_factory=list)
    interval_s: float = 5.0
    critical: bool = False
    description: str = ""

    @property
    def stale_after_s(self) -> float:
        """File output is considered stale after this many seconds."""
        return self.interval_s * 3


# ─────────────────────────────────────────────────────────────────
# THE REGISTRY
# ─────────────────────────────────────────────────────────────────
SERVICES: list[Service] = [
    # ── CAPTURE ──────────────────────────────────────────────────
    Service(
        name="brain_v1",
        module="runtime.brain_v1",
        category="CAPTURE",
        writes=["brain_live", "brain_memory", "brain_decisions"],
        interval_s=2.0,
        critical=True,
        description="Snapshots MT5 + decides every 2s — writes brain_live.json",
    ),

    # ── ANALYSIS ─────────────────────────────────────────────────
    Service(
        name="regime_classifier",
        module="runtime.regime_classifier",
        category="ANALYSIS",
        writes=["market_regime"],
        interval_s=5.0,
        critical=True,
        description="Detects TREND/CHOP/SPIKE every 5s",
    ),
    Service(
        name="performance_coordinator",
        module="runtime.performance_coordinator",
        category="ANALYSIS",
        writes=["engine_performance"],
        interval_s=30.0,
        critical=False,
        description="Computes per-engine PnL/WR every 30s",
    ),

    # ── DECISION ─────────────────────────────────────────────────
    Service(
        name="trader_orchestrator",
        module="runtime.trader_orchestrator",
        category="DECISION",
        writes=["active_engines"],
        interval_s=15.0,
        critical=True,
        description="Picks which engines may trade based on regime",
    ),
    Service(
        name="palace_council",
        module="runtime.palace_council",
        category="DECISION",
        writes=["council_votes"],
        interval_s=2.0,
        critical=False,
        description="5-expert vote on every new signal",
    ),

    # ── EXECUTION ────────────────────────────────────────────────
    Service(
        name="claude_genome_trader",
        module="runtime.claude_genome_trader",
        category="EXECUTION",
        writes=[],   # log path; no state file
        interval_s=5.0,
        critical=False,
        description="Trades the LIVE evolved genome (magic 99782)",
    ),
    Service(
        name="claude_smart_trader",
        module="runtime.claude_smart_trader",
        category="EXECUTION",
        writes=[],
        interval_s=5.0,
        critical=False,
        description="Defensive scalper with regime filters (magic 99781)",
    ),
    Service(
        name="claude_simple_trader",
        module="runtime.claude_simple_trader",
        category="EXECUTION",
        writes=[],
        interval_s=5.0,
        critical=False,
        description="Aggressive MTF scalper (magic 99780)",
    ),

    # ── EVOLUTION ────────────────────────────────────────────────
    Service(
        name="genome_evolver",
        module="runtime.genome_evolver",
        category="EVOLUTION",
        writes=["genomes_population", "genome_fitness"],
        interval_s=600.0,
        critical=False,
        description="GA evolves genome population every 10 min",
    ),
    Service(
        name="genome_promoter",
        module="runtime.genome_promoter",
        category="EVOLUTION",
        writes=["live_genome"],
        interval_s=300.0,
        critical=False,
        description="Auto-promotes best genome every 5 min",
    ),

    # ── INFRASTRUCTURE ───────────────────────────────────────────
    Service(
        name="live_dashboard",
        module="runtime.live_dashboard",
        category="INFRASTRUCTURE",
        writes=[],
        interval_s=3.0,
        critical=False,
        description="Unified terminal dashboard, refresh every 3s",
    ),
    Service(
        name="health_monitor",
        module="runtime.health_monitor",
        category="INFRASTRUCTURE",
        writes=[],
        interval_s=10.0,
        critical=False,
        description="Watches IPC files for staleness — alerts on dead services",
    ),
]


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────
def by_category() -> dict[str, list[Service]]:
    """Group services by category for display."""
    out: dict[str, list[Service]] = {}
    for s in SERVICES:
        out.setdefault(s.category, []).append(s)
    return out


def critical_services() -> list[Service]:
    """Services that MUST run for the system to trade."""
    return [s for s in SERVICES if s.critical]


def find(name: str) -> Service | None:
    """Look up a service by name."""
    for s in SERVICES:
        if s.name == name:
            return s
    return None


__all__ = ["Service", "SERVICES", "by_category", "critical_services", "find"]

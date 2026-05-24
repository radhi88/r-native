"""agents/orchestrator.py — owns all agent lifecycles.

Started by brain_server at boot. Spawns each agent on its own thread.
Exposed via /api/r/agents/* endpoints.
"""
from __future__ import annotations

from typing import Optional

from r_native.agents.base import Agent, get_recent_insights, emit_insight

# Will be populated as agents are imported below
_agents: dict[str, Agent] = {}


def register(agent: Agent):
    _agents[agent.name] = agent


def _load_default_agents():
    """Import each agent module — they self-register on import."""
    try:
        from r_native.agents.risk_sentinel import RiskSentinel
        register(RiskSentinel())
    except Exception as e:
        print(f"[orchestrator] RiskSentinel failed to load: {e}")
    try:
        from r_native.agents.genome_curator import GenomeCurator
        register(GenomeCurator())
    except Exception as e:
        print(f"[orchestrator] GenomeCurator failed to load: {e}")
    try:
        from r_native.agents.market_reader import MarketReader
        register(MarketReader())
    except Exception as e:
        print(f"[orchestrator] MarketReader failed to load: {e}")
    try:
        from r_native.agents.performance_auditor import PerformanceAuditor
        register(PerformanceAuditor())
    except Exception as e:
        print(f"[orchestrator] PerformanceAuditor failed to load: {e}")


_started = False


def start_all():
    """Idempotent — safe to call repeatedly."""
    global _started
    if _started: return
    if not _agents:
        _load_default_agents()
    for a in _agents.values():
        a.start()
    _started = True
    emit_insight("orchestrator", "INFO",
                 f"started {len(_agents)} agents: {list(_agents.keys())}")


def stop_all():
    for a in _agents.values():
        a.stop()


def list_agents() -> list[dict]:
    return [a.status() for a in _agents.values()]


def toggle(name: str, enabled: Optional[bool] = None) -> Optional[dict]:
    a = _agents.get(name)
    if not a: return None
    a.toggle(enabled)
    return a.status()


def run_now(name: str) -> Optional[dict]:
    """Manually trigger one tick of an agent (off-thread)."""
    a = _agents.get(name)
    if not a: return None
    import threading
    threading.Thread(target=a.tick, daemon=True,
                     name=f"agent-manual-{name}").start()
    return {"name": name, "kicked_off": True}


def insights(n: int = 100, agent: str = None, level: str = None) -> list[dict]:
    return get_recent_insights(n=n, agent=agent, level=level)

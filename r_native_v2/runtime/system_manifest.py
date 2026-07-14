"""runtime/system_manifest.py — THE single source of truth for the whole system.

Born 2026-05-28: "اربط الدنيا ببعض وكل شيء مهمته وتسلسلها ووقتها وتبعياتها".

Every component — its TASK, LAYER, CADENCE, DEPENDENCIES, MAGIC, ACTION class,
CRITICALITY, and STATUS — declared in one place. The supervisor reads this to
launch everything in correct dependency order, monitor health, and restart
failures. The UI reads it to show the full org-chart of the trading brain.

LAYERS (data flows top → bottom):
  1. CAPTURE      — pull raw market state from MT5 / broker
  2. ANALYSIS     — classify, score, detect (regime, footprint, scan)
  3. DECISION     — gate + choose: orchestrator, council, genome eval, ML
  4. EXECUTION    — place orders on MT5
  5. MANAGEMENT   — manage open trades (trail, breakeven, close, hedge)
  6. EVOLUTION    — breed / promote / academy
  7. LEARNING     — log, sync, train, backfill
  8. INFRASTRUCTURE — dashboards, health, supervisor, IO

ACTION classes:  CAPTURE · ANALYSE · GATE · OPEN · MODIFY · CLOSE · ADVISORY · META
CRITICALITY:     CRITICAL (system can't trade without it) · IMPORTANT · OPTIONAL
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

Layer = Literal["CAPTURE", "ANALYSIS", "DECISION", "EXECUTION",
                "MANAGEMENT", "EVOLUTION", "LEARNING", "INFRASTRUCTURE"]
Action = Literal["CAPTURE", "ANALYSE", "GATE", "OPEN", "MODIFY",
                 "CLOSE", "ADVISORY", "META"]
Crit = Literal["CRITICAL", "IMPORTANT", "OPTIONAL"]
Kind = Literal["v2_service", "rnative_agent", "shared_lib", "ui"]


@dataclass
class Component:
    id: str
    layer: Layer
    task: str
    action: Action = "ADVISORY"
    cadence_s: float = 0.0          # 0 = library / event-driven
    depends_on: list[str] = field(default_factory=list)
    magic: int = 0                  # 0 = none / manual
    crit: Crit = "OPTIONAL"
    kind: Kind = "v2_service"
    module: str = ""                # python -m <module>, or "" for libs/agents
    writes: list[str] = field(default_factory=list)   # PATHS keys it produces

    def to_dict(self) -> dict:
        return {
            "id": self.id, "layer": self.layer, "task": self.task,
            "action": self.action, "cadence_s": self.cadence_s,
            "depends_on": self.depends_on, "magic": self.magic,
            "crit": self.crit, "kind": self.kind, "module": self.module,
            "writes": self.writes,
        }


# ═══════════════════════════════════════════════════════════════════
# THE MANIFEST — every component, fully wired
# ═══════════════════════════════════════════════════════════════════
COMPONENTS: list[Component] = [
    # ── LAYER 1: CAPTURE ──────────────────────────────────────────
    Component("brain_v1", "CAPTURE",
              "Snapshot full market state (bias/RSI/ATR/pressure/MTF/SMC) every 2s",
              "CAPTURE", 2.0, [], 0, "CRITICAL", "v2_service",
              "runtime.brain_v1", ["brain_live", "brain_memory", "brain_decisions"]),
    Component("footprint_publisher", "CAPTURE",
              "Export order-flow footprint cells (bid×ask, CVD, imbalance) from MT5",
              "CAPTURE", 5.0, [], 0, "OPTIONAL", "v2_service",
              "runtime.footprint_publisher", ["footprint_cells"]),
    Component("footprint_brain_bridge", "CAPTURE",
              "Merge MQL5 footprint JSON into the brain snapshot",
              "CAPTURE", 2.0, ["brain_v1", "footprint_publisher"], 0, "OPTIONAL",
              "v2_service", "runtime.footprint_brain_bridge", []),
    Component("user_trade_observer", "CAPTURE",
              "Watch + log every manual trade with full market context (learning source)",
              "CAPTURE", 1.5, ["brain_v1"], 0, "IMPORTANT", "v2_service",
              "runtime.user_trade_observer", ["user_trades"]),

    # ── LAYER 2: ANALYSIS ─────────────────────────────────────────
    Component("regime_classifier", "ANALYSIS",
              "Classify TREND_UP/DOWN/CHOP/SPIKE/TRANSITION via ADX+EMA+vol",
              "ANALYSE", 5.0, ["brain_v1"], 0, "CRITICAL", "v2_service",
              "runtime.regime_classifier", ["market_regime", "regime_history"]),
    Component("chart_publisher", "ANALYSIS",
              "Draw live analysis (S/R, ZigZag, BOS/CHoCH) on the MT5 chart",
              "ANALYSE", 4.0, ["brain_v1"], 0, "OPTIONAL", "v2_service",
              "runtime.chart_publisher", []),
    Component("performance_coordinator", "ANALYSIS",
              "Compute per-engine PnL / win-rate / expectancy ranking",
              "ANALYSE", 30.0, [], 0, "IMPORTANT", "v2_service",
              "runtime.performance_coordinator", ["engine_performance"]),

    # ── LAYER 3: DECISION ─────────────────────────────────────────
    Component("trader_orchestrator", "DECISION",
              "Regime-aware gate: decide which engines may trade this minute",
              "GATE", 15.0, ["regime_classifier", "performance_coordinator"], 0,
              "CRITICAL", "v2_service", "runtime.trader_orchestrator", ["active_engines"]),
    Component("palace_council", "DECISION",
              "5-expert APPROVE/VETO vote on every genome signal",
              "GATE", 2.0, ["brain_v1", "genome_signals"], 99779, "OPTIONAL",
              "v2_service", "runtime.palace_council", ["council_votes"]),
    Component("ml_clone_gate", "DECISION",
              "P(win) gate: only fire in contexts cloned from the user's wins (AUC 0.72)",
              "GATE", 0.0, ["brain_v1", "trade_sync"], 0, "IMPORTANT", "shared_lib",
              "", []),
    Component("orchestrator_gate", "DECISION",
              "Library: is_engine_active() — every trader checks before firing",
              "GATE", 0.0, ["trader_orchestrator"], 0, "CRITICAL", "shared_lib", "", []),
    Component("circuit_breaker", "DECISION",
              "3 breakers: rate-limit + loss-cascade + drawdown-velocity",
              "GATE", 0.0, [], 0, "CRITICAL", "shared_lib", "", []),
    Component("risk_sentinel_gate", "DECISION",
              "Library: central pre-trade risk gate (equity floor, daily loss, spread)",
              "GATE", 0.0, [], 0, "CRITICAL", "shared_lib", "", []),

    # ── LAYER 4: EXECUTION ────────────────────────────────────────
    Component("unified_trader", "EXECUTION",
              "THE sole executor: genome → orchestrator gate → CB → ML gate → order",
              "OPEN", 3.0,
              ["brain_v1", "regime_classifier", "trader_orchestrator",
               "ml_clone_gate", "circuit_breaker", "live_genome"],
              99782, "CRITICAL", "v2_service", "runtime.unified_trader",
              ["decisions", "buy_alerts"]),

    # ── LAYER 5: MANAGEMENT ───────────────────────────────────────
    Component("trailing_stop_manager", "MANAGEMENT",
              "Universal SL trail on every open position (BE@3pt → ladder)",
              "MODIFY", 2.0, [], 0, "CRITICAL", "v2_service",
              "runtime.trailing_stop_manager", ["trailing_state"]),

    # ── LAYER 6: EVOLUTION ────────────────────────────────────────
    Component("genome_evolver", "EVOLUTION",
              "GA: mutate + breed the genome population every 10 min",
              "META", 600.0, ["brain_v1"], 0, "IMPORTANT", "v2_service",
              "runtime.genome_evolver", ["genomes_population", "genome_fitness"]),
    Component("genome_promoter", "EVOLUTION",
              "Promote the best genome to LIVE every 5 min",
              "META", 300.0, ["genome_evolver"], 0, "IMPORTANT", "v2_service",
              "runtime.genome_promoter", ["live_genome"]),
    Component("champion_seeder", "EVOLUTION",
              "Boot guard: restore the immortal CHILD genome if ever lost",
              "META", 0.0, [], 0, "CRITICAL", "v2_service",
              "runtime.champion_seeder", ["live_genome"]),
    Component("champion_evolution", "EVOLUTION",
              "Every 4h: breed challenger, crown if it beats champion fitness",
              "META", 14400.0, ["trade_sync", "genome_birth"], 0, "OPTIONAL",
              "v2_service", "runtime.champion_evolution", []),
    Component("genome_academy", "EVOLUTION",
              "Living lab: breed+gauntlet(7 symbols)+agent-panel, crown generalists",
              "META", 60.0, ["backtest_engine", "trade_sync"], 0, "OPTIONAL",
              "v2_service", "runtime.genome_academy", ["academy_state"]),

    # ── LAYER 7: LEARNING ─────────────────────────────────────────
    Component("trade_sync", "LEARNING",
              "Sync MT5 closed deals (incl manual) → trading.db.trades every 60s",
              "META", 60.0, [], 0, "IMPORTANT", "v2_service",
              "runtime.trade_sync", []),
    Component("decision_outcome_filler", "LEARNING",
              "Backfill realized PnL onto logged decisions every 30s",
              "META", 30.0, ["unified_trader"], 0, "IMPORTANT", "v2_service",
              "runtime.decision_outcome_filler", []),
    Component("decision_log", "LEARNING",
              "Library: record every entry decision + context to db + jsonl",
              "META", 0.0, [], 0, "IMPORTANT", "shared_lib", "", ["decisions"]),
    Component("ml_clone_trainer", "LEARNING",
              "Retrain the P(win) model on latest wins → ONNX (on demand / scheduled)",
              "META", 0.0, ["trade_sync", "decision_log"], 0, "IMPORTANT",
              "shared_lib", "runtime.ml_clone", []),

    # ── LAYER 8: INFRASTRUCTURE ───────────────────────────────────
    Component("supervisor", "INFRASTRUCTURE",
              "Launch all components in dependency order, monitor + auto-restart",
              "META", 20.0, [], 0, "CRITICAL", "v2_service",
              "runtime.supervisor", []),
    Component("health_monitor", "INFRASTRUCTURE",
              "Watch every IPC file for staleness, alert on dead services",
              "META", 10.0, [], 0, "OPTIONAL", "v2_service",
              "runtime.health_monitor", ["alerts"]),
    Component("competition_tracker", "INFRASTRUCTURE",
              "Per-engine live leaderboard (PnL, WR, streak)",
              "META", 5.0, [], 0, "OPTIONAL", "v2_service",
              "runtime.competition_tracker", ["competition_scoreboard"]),
    Component("sql_dashboard", "INFRASTRUCTURE",
              "Single-pane terminal view of the whole system from trading.db",
              "META", 5.0, [], 0, "OPTIONAL", "v2_service",
              "runtime.sql_dashboard", []),
    Component("buy_pulse", "INFRASTRUCTURE",
              "Live BUY/SELL condition checklist screen (✅/❌)",
              "META", 2.0, ["brain_v1", "live_genome"], 0, "OPTIONAL",
              "v2_service", "runtime.buy_pulse", []),
    Component("r_native_brain_link", "INFRASTRUCTURE",
              "Feed brain snapshots to the genome population",
              "META", 5.0, ["brain_v1"], 0, "OPTIONAL", "v2_service",
              "runtime.r_native_brain_link", ["genome_signals"]),
]


# ═══════════════════════════════════════════════════════════════════
# R Native legacy agents (magic 20260605) — catalogued, NOT auto-run
# These are the 31 agents in r_native/agents/. The supervisor does NOT
# launch them (they run inside the R Native app). Listed for the full map.
# ═══════════════════════════════════════════════════════════════════
RNATIVE_AGENTS: list[Component] = [
    Component("risk_sentinel", "DECISION", "Kill runaway losers, trip kill-switch", "ADVISORY", 20, [], 20260605, "IMPORTANT", "rnative_agent"),
    Component("genome_curator", "EVOLUTION", "HoF caretaker: pin/prune/breed-suggest", "ADVISORY", 1800, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("market_reader", "ANALYSIS", "Regime-aware genome router + auto-deploy", "ADVISORY", 300, [], 20260605, "IMPORTANT", "rnative_agent"),
    Component("performance_auditor", "LEARNING", "Hourly/daily audit reports", "ADVISORY", 3600, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("llm_strategist", "DECISION", "LLM strategic recommendations", "ADVISORY", 900, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("gap_hunter", "EXECUTION", "Place pending limits at price gaps", "OPEN", 300, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("news_blocker", "DECISION", "Block symbols ±15min around news", "ADVISORY", 60, [], 20260605, "IMPORTANT", "rnative_agent"),
    Component("correlation_guard", "DECISION", "Block over-correlated exposure", "ADVISORY", 30, [], 20260605, "IMPORTANT", "rnative_agent"),
    Component("drawdown_recovery", "MANAGEMENT", "Cut lot/positions in DD, kill@18%", "ADVISORY", 30, [], 20260605, "IMPORTANT", "rnative_agent"),
    Component("session_specialist", "ANALYSIS", "Per-symbol session preference scores", "ADVISORY", 600, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("volatility_hunter", "EXECUTION", "Straddle pending orders on ATR spikes", "OPEN", 180, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("performance_coach", "EVOLUTION", "Hard-retire losing genomes on live evidence", "ADVISORY", 3600, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("night_shift", "MANAGEMENT", "Overnight risk cuts, close bleeders >2h", "CLOSE", 600, [], 20260605, "IMPORTANT", "rnative_agent"),
    Component("winner_booster", "MANAGEMENT", "Scale lot up on proven winners", "ADVISORY", 120, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("market_scanner", "ANALYSIS", "MTF + levels + gap snapshot", "ADVISORY", 90, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("regime_scaler", "MANAGEMENT", "Per-symbol lot multipliers from regime", "ADVISORY", 120, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("auto_rotator", "EVOLUTION", "Promote/demote competitor genomes by P/L", "ADVISORY", 1800, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("side_balance_monitor", "ANALYSIS", "Surface BUY/SELL imbalance", "ADVISORY", 3600, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("streak_detector", "ANALYSIS", "Hot/cold streak detection per genome", "ADVISORY", 900, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("position_aging", "MANAGEMENT", "Close stagnant/zombie positions 24/7", "CLOSE", 60, [], 20260605, "IMPORTANT", "rnative_agent"),
    Component("session_pl_tracker", "LEARNING", "Per-session P/L breakdown", "ADVISORY", 1800, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("deploy_assistant", "EVOLUTION", "Auto-deploy qualified genomes as competitors", "ADVISORY", 1800, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("dynamic_tp", "MANAGEMENT", "Compress TP when volatility dies", "MODIFY", 180, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("deployment_status", "INFRASTRUCTURE", "Primary/competitor slot snapshot", "ADVISORY", 900, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("breakeven_lock", "MANAGEMENT", "Move SL to breakeven on +$0.30", "MODIFY", 30, [], 20260605, "IMPORTANT", "rnative_agent"),
    Component("margin_safety", "DECISION", "Margin-usage early warning", "ADVISORY", 60, [], 20260605, "IMPORTANT", "rnative_agent"),
    Component("trade_journal", "LEARNING", "Per-trade JSONL journal", "ADVISORY", 120, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("volatility_reversion", "EXECUTION", "Reversion straddle (DISABLED — superseded)", "OPEN", 180, [], 20260605, "OPTIONAL", "rnative_agent"),
    Component("hedge_resolver", "MANAGEMENT", "Close redundant hedge pairs", "CLOSE", 60, [], 20260605, "IMPORTANT", "rnative_agent"),
    Component("sl_safety_tightener", "MANAGEMENT", "Cap loss at 3% equity via SL", "MODIFY", 60, [], 20260605, "IMPORTANT", "rnative_agent"),
    Component("recovery_mode", "DECISION", "Micro-lot winners-only gate until $105", "GATE", 60, [], 20260605, "IMPORTANT", "rnative_agent"),
]


# ═══════════════════════════════════════════════════════════════════
# Query helpers
# ═══════════════════════════════════════════════════════════════════
def all_components() -> list[Component]:
    return COMPONENTS + RNATIVE_AGENTS


def by_layer() -> dict[str, list[Component]]:
    out: dict[str, list[Component]] = {}
    for c in all_components():
        out.setdefault(c.layer, []).append(c)
    return out


def launch_order() -> list[Component]:
    """Topological sort of v2_service components by depends_on (Kahn's algo)."""
    services = [c for c in COMPONENTS if c.kind == "v2_service" and c.module]
    ids = {c.id for c in services}
    indeg = {c.id: 0 for c in services}
    for c in services:
        for d in c.depends_on:
            if d in ids:
                indeg[c.id] += 1
    ready = [c for c in services if indeg[c.id] == 0]
    order, seen = [], set()
    # stable: process by layer priority then name
    layer_rank = {l: i for i, l in enumerate(
        ["CAPTURE", "ANALYSIS", "DECISION", "EXECUTION", "MANAGEMENT",
         "EVOLUTION", "LEARNING", "INFRASTRUCTURE"])}
    while ready:
        ready.sort(key=lambda c: (layer_rank.get(c.layer, 9), c.id))
        c = ready.pop(0)
        if c.id in seen: continue
        seen.add(c.id); order.append(c)
        for nxt in services:
            if c.id in nxt.depends_on and nxt.id not in seen:
                indeg[nxt.id] -= 1
                if indeg[nxt.id] <= 0 and nxt not in ready:
                    ready.append(nxt)
    # append any leftover (cycle-safe)
    for c in services:
        if c.id not in seen: order.append(c)
    return order


def critical_ids() -> list[str]:
    return [c.id for c in COMPONENTS if c.crit == "CRITICAL"]


def stats() -> dict:
    comps = all_components()
    return {
        "total": len(comps),
        "v2_services": sum(1 for c in comps if c.kind == "v2_service"),
        "rnative_agents": sum(1 for c in comps if c.kind == "rnative_agent"),
        "shared_libs": sum(1 for c in comps if c.kind == "shared_lib"),
        "critical": sum(1 for c in comps if c.crit == "CRITICAL"),
        "by_layer": {k: len(v) for k, v in by_layer().items()},
        "by_action": {a: sum(1 for c in comps if c.action == a)
                      for a in ["CAPTURE", "ANALYSE", "GATE", "OPEN", "MODIFY",
                                "CLOSE", "ADVISORY", "META"]},
    }


__all__ = ["Component", "COMPONENTS", "RNATIVE_AGENTS", "all_components",
           "by_layer", "launch_order", "critical_ids", "stats"]


if __name__ == "__main__":
    import json
    s = stats()
    print("═══ SYSTEM MANIFEST ═══")
    print(f"  total components: {s['total']}  "
          f"(v2 services {s['v2_services']} · R Native agents {s['rnative_agents']} · libs {s['shared_libs']})")
    print(f"  critical: {s['critical']}")
    print(f"\n  by layer: {json.dumps(s['by_layer'], ensure_ascii=False)}")
    print(f"  by action: {json.dumps(s['by_action'], ensure_ascii=False)}")
    print(f"\n═══ LAUNCH ORDER (dependency-sorted v2 services) ═══")
    for i, c in enumerate(launch_order(), 1):
        deps = f" ← {','.join(c.depends_on)}" if c.depends_on else ""
        print(f"  {i:2d}. [{c.layer[:4]}] {c.id:24s} {c.cadence_s:>6.0f}s  {c.crit[:4]}{deps}")

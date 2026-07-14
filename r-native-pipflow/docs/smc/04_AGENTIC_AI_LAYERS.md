# Agentic AI Layers — Mapping the Framework to R-Native

> The user's vision: build a self-improving, autonomous trading system aligned
> with the Agentic AI framework (Foundation → Deep Learning → Gen AI →
> AI Agents → Agentic AI). This doc maps each framework layer to concrete
> R-Native modules and deliverables.

---

## Layer 1 — Foundation (AI & ML, Deep Learning)

### Status: 80% existing, 20% new

| Capability | Module | Status |
|---|---|---|
| Supervised learning (genome scoring) | `genetic_engine.py`, `combo_fitness.py` | ✅ Exists |
| Reinforcement learning (continuous evolution) | `continuous_evolution.py`, `hall_of_fame.py` | ✅ Exists |
| Unsupervised learning (regime clustering) | `agents/market_reader.py` | ✅ Exists |
| Transfer learning (HoF seed pool across symbols) | `hall_of_fame.py` | ✅ Exists |
| CNN/LSTM SMC pattern scorer | `smc_neural.py` | 🔲 NEW (Phase 5) |
| Attention mechanism for multi-TF fusion | `multi_tf_attention.py` | 🔲 NEW (Phase 5+) |

### New deliverables

**`smc_neural.py`** — A small CNN+LSTM stack that scores SMC pattern quality:

```python
class SMCPatternScorer:
    """Score 0..100 confidence that a detected OB / FVG will hold.
    Trained on labeled outcomes: (pattern, future_N_bars) → did_react."""
    def __init__(self, weights_path: str): ...
    def score_ob(self, bars_window: np.ndarray, ob: dict) -> float
    def score_fvg(self, bars_window: np.ndarray, fvg: dict) -> float
```

- Architecture: 1D CNN (3 layers, kernel 5/3/3) on (open, high, low, close,
  volume, time_of_day) features → LSTM (32 hidden) → Dense → sigmoid.
- Training data: re-play historic bars through `smc_engine`, label OBs/FVGs
  by whether price respected them within N=20 bars.
- Output feeds into `snap["h1"]["smc"]["fresh_ob_below"]["nn_strength"]`,
  consumed by `_sig_smc_ob` as a multiplier on vote weight.

---

## Layer 2 — Gen AI (Content Creation, Multimodal)

### Status: 30% existing (LLMStrategist), 70% new

| Capability | Module | Status |
|---|---|---|
| LLM client | `agents/llm.py` | ✅ Exists |
| LLM strategist agent | `agents/llm_strategist.py` | ✅ Exists |
| RAG (state & history) | `trade_commentary.py` | 🟡 Partial |
| Tool use / function calling | LLM agents | 🔲 NEW (Phase 6) |
| Prompt engineering registry | `prompts/` | 🔲 NEW |
| Multimodal generation (chart screenshots) | `trade_screenshots.py` | ✅ Exists |
| Hallucination mitigation | Schema validation | 🔲 NEW |

### New deliverables

**`agents/smc_narrator.py`** — Generates Arabic trade narratives from raw SMC data:

```python
class SMCNarrator(Agent):
    """Translates SMC structural state into human-readable Arabic explanations.
    Posts to brain.drawings[].label so the user sees 'دخول طويل عند OB صاعد
    بعد كسر سيولة' on the chart."""

    def explain_entry(self, snap, verdict) -> str:
        """Build Arabic narrative from snap.smc + verdict.smc_anchors."""

    def explain_exit(self, trade, exit_reason) -> str:
        """Post-mortem in Arabic: why we won/lost, what to learn."""
```

Uses Claude API via existing `llm.py` wrapper. Output schema:
```json
{
  "headline_ar": "دخول طويل بعد كسر سيولة + ارتداد OB",
  "rationale_ar": "السعر حاب الـIDM ورجع لمنطقة OB الصاعدة...",
  "risk_ar": "SL تحت OB، TP عند الـliquidity فوق",
  "confidence_smc": 0..100,
}
```

**Prompt registry (`prompts/smc/`)** — Versioned prompt templates:
- `prompts/smc/entry_explain_ar.txt`
- `prompts/smc/post_mortem_ar.txt`
- `prompts/smc/structure_overview_ar.txt`

**Hallucination guard** — Every LLM output runs through a schema validator;
levels/prices in the narrative must match `snap.smc` actual values
(±0.5% tolerance, else regenerated with stricter prompt).

---

## Layer 3 — AI Agents (Autonomous Tasks)

### Status: 90% existing (19 agents already), 10% new

The system already has a robust agent layer:

```
orchestrator → 19 agents:
  base, correlation_guard, drawdown_recovery, gap_hunter, genome_curator,
  llm, llm_strategist, market_reader, market_scanner, news_blocker,
  night_shift, performance_auditor, performance_coach, risk_sentinel,
  session_specialist, volatility_hunter, winner_booster
```

### New agents to add

**`agents/smc_monitor.py`** — Watches SMC structure changes:

```python
class SMCMonitor(Agent):
    """Emits insights when:
      - new CHoCH fires on H1 or H4 (regime change)
      - high-strength OB forms
      - inducement is swept
      - liquidity pool gets raided
    Triggers SMCNarrator to post Arabic commentary."""
```

**`agents/smc_calibrator.py`** — Runs a fast micro-GA on just SMC params:

```python
class SMCCalibrator(Agent):
    """Every 6h, runs a 100-genome × 1-generation GA varying only the SMC
    continuous params (smc_ob_buffer_atr, smc_ob_freshness_bars,
    smc_htf_lookback_bars) on the last 7 days of bars per symbol.
    Auto-tunes per-symbol SMC sensitivity."""
```

**`agents/smc_self_critic.py`** — Closes the feedback loop:

```python
class SMCSelfCritic(Agent):
    """After each closed trade tagged with SMC entry, query combo_fitness:
      - Was this SMC combo a known winner here? If no, emit WARN.
      - Was the trade aligned with last BOS direction? If no, emit INFO.
      - Did the exit reason match the prediction (e.g. tp_target_smc_liq
        but exited via atr_tp)? If mismatch, emit INSIGHT.
    Feeds the next campaign as 'lessons learned'."""
```

---

## Layer 4 — Agentic AI (Full Automation)

### Status: 40% existing, 60% new

| Capability | Where it lives | Status |
|---|---|---|
| Agent protocol (registration, lifecycle) | `agents/orchestrator.py` | ✅ Exists |
| Multi-agent coordination | `orchestrator.py` (insight bus) | ✅ Exists |
| State persistence | `state.json` per agent | ✅ Exists |
| Planning (ReAct, CoT, ToT) | LLMStrategist | 🟡 Partial |
| Task scheduling | `auto_scheduler.py`, `auto_ga_daemon.py` | ✅ Exists |
| Self-improvement | `continuous_evolution.py` | ✅ Exists |
| Rollback mechanisms | None | 🔲 NEW |
| Feedback loops & evaluators | `combo_fitness.py`, `performance_coach.py` | 🟡 Partial |
| Cost & resource management | `auto_ga_daemon.py` (daily cap) | 🟡 Partial |
| Long-term autonomy | Symbol configs + HoF | 🟡 Partial |
| Governance, safety, guardrails | `risk_sentinel.py`, `news_blocker.py` | ✅ Exists |
| Human-in-the-loop oversight | Insights feed + manual override | 🟡 Partial |
| Memory governance & retention | `combo_fitness.py` (cap 5000) | 🟡 Partial |
| Observability & tracing | Insights JSONL + state.json | 🟡 Partial |
| Risk management & constraints | `prop_firm.py`, `exposure_guard.py` | ✅ Exists |

### New deliverables

**`genome_rollback.py`** — Automatic rollback on regression:

```python
class GenomeRollback:
    """If a newly-deployed genome's first-10-trades win-rate drops >15%
    below the previous one's, auto-revert and demote the new genome."""

    def evaluate_post_deploy(self, symbol: str) -> dict
    def execute_rollback(self, symbol: str, previous_genome_id: str)
```

**`agent_governance.py`** — Hard guardrails on agent actions:

```python
class AgentGovernance:
    """Cross-cut policy enforcement:
      - Max trades per agent per hour
      - Max deploys per day per symbol
      - Mandatory cooling-off after N consecutive losses
      - Force pause on >X% account drawdown
    Wraps emit_insight + actions; can VETO any agent's tick output."""
```

**`agentic_memory.py`** — Long-term memory governance:

```python
class AgenticMemory:
    """Two tiers:
      - Short-term: last 500 insights (ring buffer, already exists)
      - Long-term: per-symbol 'lessons.json' with promoted patterns:
            - 'XAUUSD prefers IDM-swept OB on London open'
            - 'EURUSD CHoCH on H4 worth +12% expected return'
      Surfaced to LLMStrategist as RAG context."""
```

**`observability/trace.py`** — Per-decision trace logging:

```python
def trace_decision(decision_id: str, stages: list[dict]):
    """Persist the full chain: snapshot → SMC engine → genome → resolver →
    verdict → order. Replayable; lets us answer 'why did genome X enter here?'
    days later."""
```

---

## Cross-Cutting: Self-Reflection & Failure Recovery

### Self-reflection loop

```
Every closed trade →
   SMCSelfCritic asks: did the predicted SMC story play out?
   →  If yes: bump combo_fitness for this SMC combo + context
   →  If no:  log mismatch, prompt LLMStrategist to propose a hypothesis
   →  Hypothesis → SMCCalibrator schedules a focused micro-GA
   →  Micro-GA winner → if score > threshold → propose deploy
   →  GenomeRollback monitors first 10 trades; revert if regress
```

### Failure recovery

| Failure | Detection | Recovery |
|---|---|---|
| Pending order placed in wrong direction | `risk_sentinel` notices no fill + adverse move | Cancel order, emit WARN |
| Genome consistently losing | `performance_coach` tracks rolling win-rate | Auto-pause + propose retraining |
| MT5 disconnect | `heartbeat_server.py` ping | Reconnect + replay queued orders |
| Brain JSON corruption | EA tolerates parse failure | Atomic `.tmp` swap; skip tick |
| LLM hallucinated price level | Schema validator | Regenerate with stricter prompt |
| Drawing object overflow on chart | `DR_MAX_OBJECTS=250` | Prune oldest first |

---

## End-State Architecture (Phase 7 complete)

```
                  ┌───────────────────┐
                  │  Human (Telegram) │
                  └─────────┬─────────┘
                            │
                            ▼
        ┌───────────────────────────────────────┐
        │     LLMStrategist + SMCNarrator       │   ← Gen AI
        │  (Arabic explanation, hypothesis)     │
        └─────────┬─────────────────────────────┘
                  │
                  ▼
        ┌───────────────────────────────────────┐
        │            Orchestrator               │   ← AI Agents
        │  (19+ agents, governed, observable)   │
        └────────┬───────────────────────┬──────┘
                 │                       │
                 ▼                       ▼
        ┌─────────────────┐   ┌───────────────────┐
        │  SMC Engine +   │   │ Genome population │
        │  Neural scorer  │──▶│ (per-symbol lanes)│   ← Deep Learning + ML
        │  (Phase 1+5)    │   │ (PR-2..5)         │
        └────────┬────────┘   └─────────┬─────────┘
                 │                       │
                 ▼                       ▼
        ┌───────────────────────────────────────┐
        │     trade_gate.evaluate_gate           │   ← Foundation
        │     sl_tp_resolver (SMC-anchored)      │
        └─────────┬─────────────────────────────┘
                  │
                  ▼
        ┌───────────────────────────────────────┐
        │  brain.json (decision + drawings)     │
        └─────────┬─────────────────────────────┘
                  │
                  ▼
        ┌───────────────────────────────────────┐
        │  FRIDAY_Brain_Executor.mq5 + EA       │
        │  (places orders + renders SMC zones)  │
        └───────────────────────────────────────┘
```

Feedback loops (not shown for clarity):

- Closed trades → `combo_fitness.record_smc_trade` → next campaign uses data
- Insights → SMCSelfCritic → hypothesis → SMCCalibrator → new genome
- GenomeRollback monitors deploys → reverts regressions
- AgenticMemory promotes proven patterns → LLM RAG context

---

## Maturity Milestones

| Milestone | Indicators |
|---|---|
| **M1 — SMC visible** | Charts show OB/FVG/BOS/CHoCH rendered live (Phase 1+2) |
| **M2 — SMC trades** | Genome with `use_sig_smc_*` deployed and profitable (PR-2..4) |
| **M3 — SMC specializes** | Per-symbol HoF shows dominant SMC lane (PR-5) |
| **M4 — SMC narrates** | Arabic explanation on every entry (SMCNarrator) |
| **M5 — SMC self-tunes** | SMCCalibrator's micro-GA produces deployed genome |
| **M6 — SMC self-critiques** | SMCSelfCritic generates lessons → memory → next campaign |
| **M7 — SMC governed** | Rollback fires once on regression and recovers |

# 06 — Refactor Objectives
Generated: 2026-05-13

## Target Architecture

```
Agents / Strategies (SignalProposal only, can_execute=False)
    ↓
DecisionRouter  →  ConflictGuard
    ↓
RiskManager
    ↓
PositionManager (management requests only)
    ↓
ExecutionManager (ONLY execution authority)
    ↓
MT5Gateway (ONLY MT5 adapter)
    ↓
MT5
```

## Phase Plan

### Phase 1 — Safety snapshot
- Archive all files to be modified into `src/mt5_ai/archive/original_snapshot_YYYYMMDD/`
- Create `reports/07_MODIFICATION_BACKUP_MANIFEST.md`

### Phase 2 — Core schemas
Build `src/mt5_ai/core/`:
- `signal_schema.py` — SignalProposal, DecisionResult, RiskDecision, PositionManagementRequest, ExecutionRequest, ExecutionResult
- `structured_logger.py` — JSONL loggers for all layers

### Phase 3 — Central config
- `config/trading_runtime.yaml` — unified runtime config
- `src/mt5_ai/core/config_loader.py` — loads and validates config

### Phase 4 — Magic registry
- `src/mt5_ai/core/magic_registry.py` — clean registry (see report 05)
- Add `20260600` to algory_runner immediately
- Update FRIDAY_MAGICS in all learner files

### Phase 5 — MT5Gateway cleanup
- `src/mt5_ai/mt5_gateway.py` — remove any decision logic, keep only low-level adapter
- Ensure all callers route through it

### Phase 6 — ExecutionManager
- `src/mt5_ai/core/execution_manager.py`
- Receives only approved ExecutionRequest
- DRY_RUN mode simulates without sending
- algory_runner refactored to call ExecutionManager instead of mt5.order_send directly

### Phase 7 — RiskManager
- `src/mt5_ai/core/risk_manager.py`
- Validates spread, volume, margin, limits, cooldown, news block

### Phase 8 — ConflictGuard
- `src/mt5_ai/core/conflict_guard.py`
- Detects BUY+SELL conflicts, duplicate entries, loop detection

### Phase 9 — DecisionRouter
- `src/mt5_ai/core/decision_router.py`
- Collects SignalProposals, weights sources, produces one DecisionResult

### Phase 10 — PositionManager
- `src/mt5_ai/core/position_manager.py`
- Trail, breakeven, partial close — all routed through ExecutionManager

### Phase 11 — Convert dangerous executors
- Extract strategy logic from executors into agent SignalProducers
- Archive original executors
- Files: governors, scalper_executor, touch_executor, risk_close, ollama_trader, ict_sweep

### Phase 12 — Agents
- `src/mt5_ai/agents/`: fractal_agent, smc_agent, ict_sweep_agent, ai_agent, scalper_agent, touch_agent
- All return SignalProposal only, can_execute=False

### Phase 13 — Main runtime loop
- `src/mt5_ai/runtime/main_loop.py`
- `src/mt5_ai/runtime/dry_run_runner.py`
- `src/mt5_ai/runtime/demo_runner.py`

### Phase 14 — Dashboards / Jarvis
- Verify no execution authority in mark_xxxix, voice, dashboards

### Phase 15 — MQ5 boundary
- Document FRIDAY_Gold_EA.mq5 conflict risk

### Phases 16-18 — Verification + Reports + Live micro config

## Immediate Quick Wins (safe while system runs)
1. Add magic `20260600` to algory_runner → positions become identifiable
2. Add `20260600` to FRIDAY_MAGICS in learner files → trades get learned
3. Build `src/mt5_ai/core/` new files (additive, doesn't break anything)
4. Build `src/mt5_ai/agents/` (additive)

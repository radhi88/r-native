# Report: 01 — Independent Architecture Review

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Phase start:** 02:10 UTC  
**Phase end:** 02:22 UTC  
**Elapsed:** ~12 minutes  
**Scope:** `src/mt5_ai/` — all active (non-archive) Python files

---

## 1. Main Runner

**File:** `src/mt5_ai/runtime/main_loop.py`

This is confirmed as the production runner. Entry point is `main()` at line 167. It:
- Accepts `--symbol`, `--timeframe`, `--interval`, `--cycles`, `--config` CLI args
- Calls `_cl.use_config(...)` before pipeline initialization when `--config` is provided
- Initializes MT5 via `mt5.initialize()`
- Runs `run_cycle()` in a `while True` loop with `time.sleep(interval)` between cycles
- Calls `mt5.shutdown()` on exit

**Secondary runners (not production):**
| File | Role |
|---|---|
| `runtime/dry_run_simulation.py` | Synthetic signal test — no MT5 bar data |
| `runtime/demo_runner.py` | Single-cycle manual test — delegates to `dry_run_runner.py` |
| `runtime/dry_run_runner.py` | Confirmed exists, wraps a single pipeline cycle |
| `algory_runner.py` | Algory genome strategy runner — separate execution context |

---

## 2. Active Agents

### Signal Producers (entry agents)

| Agent | File | Source ID | Emit Type |
|---|---|---|---|
| `FractalAgent` | `agents/fractal_agent.py` | `fractal_agent` | `SignalProposal` |
| `SmcAgent` | `agents/smc_agent.py` | `smc_agent` | `SignalProposal` (or `NO_CONFIRMATION`) |
| `IctSweepAgent` | `agents/ict_sweep_agent.py` | `ict_sweep_agent` | `SignalProposal` |
| `AiAgent` | `agents/ai_agent.py` | `ai_agent` | (imported but not used in `run_cycle`) |
| `ScalperAgent` | `agents/scalper_agent.py` | `scalper_agent` | (imported but not used in `run_cycle`) |

**Active in `run_cycle()`:** Only `FractalAgent`, `SmcAgent`, `IctSweepAgent` (line 95 in `main_loop.py`). `AiAgent` and `ScalperAgent` are imported but never called from the production loop.

### Position Management Agents

| Agent | File | Emit Type |
|---|---|---|
| `GovernorAgent` | `agents/governor_agent.py` | `PositionManagementRequest` |
| `RiskCloseAgent` | `agents/risk_close_agent.py` | `PositionManagementRequest` |

**Critical finding:** Both feed into `PositionManager → ExecutionManager`. See Safety note in §7.

---

## 3. SignalArbiter Placement

**File:** `src/mt5_ai/core/signal_arbiter.py`

**Position in pipeline:**
```
FractalAgent ─┐
SmcAgent      ├─ raw_signals → [SignalArbiter.decide()] → single ArbiterDecision
IctSweepAgent ─┘
                                     │
                          arb.final_direction == HOLD → return early
                                     │ (if not HOLD)
                          arb.to_signal_proposal() → arb_signal
                                     │
                           [DecisionRouter.route([arb_signal])]
```

SignalArbiter is instantiated on **every cycle** (line 101 in `main_loop.py`):
```python
arbiter = SignalArbiter()   # ← NEW INSTANCE per cycle — minor inefficiency
arb     = arbiter.decide(raw_signals, symbol, timeframe)
```

**Weights confirmed:**
- `WEIGHT_FRACTAL = 0.45`
- `WEIGHT_SMC = 0.45`
- `WEIGHT_SESSION = 0.10`
- `CONFIDENCE_THRESHOLD = 0.70`
- `MATERIAL_DELTA = 0.12`

**IctSweepAgent signal integration:** IctSweepAgent is collected in `raw_signals` but the arbiter only uses `fractal_agent` and `smc_agent` sources explicitly. ICT signals land in `confirmers` list (non-primary) and are logged but have **zero weight** in the arbiter's scoring formula. ICT signals are also not forwarded to DecisionRouter (the arbiter replaces the entire raw list with one arbiter signal).

---

## 4. ConflictGuard Placement

**File:** `src/mt5_ai/core/conflict_guard.py`

**Position:** After DecisionRouter, before RiskManager.

```python
allow, cfls = guard.check(decision, [arb_signal], {})
```

Note: `open_positions={}` is always passed as an empty dict (hardcoded `{}`). The opposite-position conflict check (rule 3) will **never fire** because no existing positions are passed. This is a gap.

**Active rules:**
| Rule | Description |
|---|---|
| 1 | Block any signal with `can_execute=True` |
| 2 | Block if both BUY and SELL present in signal list |
| 3 | Block if opposite open position exists (BROKEN — empty dict always passed) |
| 4 | Block if `decision.confidence < min_decision_confidence` (default 0.45) |
| 5 | Block single weak signal if confidence < 0.50 |

Rule 2 is effectively inert now (arbiter emits only one direction), so ConflictGuard acts as confidence floor and can_execute guard only.

---

## 5. RiskManager Placement

**File:** `src/mt5_ai/core/risk_manager.py`

**Position:** After ConflictGuard, before ExecutionManager.

**Checks performed:**
- Kill switch re-check
- Max spread (from config, default 30; XAUUSDm=80)
- Max open positions (from config, default 3)
- Max daily loss (from config, default 2.0%)
- Confidence floor (from config, default 0.45)
- Lot calculation (uses `max_lot` from config)

**Gap:** `spread_points`, `open_positions`, and `daily_loss_pct` are ALL passed as 0 by `run_cycle()`. Real market spread and position count are never fetched. Spread and position-count gates **never fire**.

---

## 6. ExecutionManager Placement

**File:** `src/mt5_ai/core/execution_manager.py`

**Position:** Final gate — only component that can call `mt5.order_send`.

**Guard layers (in order):**
1. Kill switch check
2. `req.is_valid()` — lot > 0, magic != 0, sl > 0 for BUY/SELL
3. `validate_request(magic, comment)` — magic must be in `ALL_FRIDAY_MAGICS`
4. `is_dry_run()` — if True, returns simulated result immediately, never reaches MT5Gateway
5. `is_live_allowed()` — requires mode=LIVE AND allow_live_trading=True AND NOT kill_switch

**Three execution methods:**
- `execute(req)` — primary path used by `main_loop.py`
- `cancel_pending_order(ticket, magic, comment)` — used by `algory_runner.py`
- `send_raw_order(req_dict, magic)` — used by `algory_runner.py` for live/pending orders

---

## 7. order_send Path Audit

### Active (non-archive) files with `order_send` calls

| File | Line(s) | Guard Status |
|---|---|---|
| `core/execution_manager.py` | 111, 150 | ✅ guarded: kill_switch → DRY_RUN → is_live_allowed() before reaching these lines |
| `mt5_gateway.py` | 361, 364, 438, 441, 533, 536 | ⚠️ **PARTIAL**: only guarded by `DEMO_TRADING_ENABLED` and `is_demo_account()` — no kill_switch or DRY_RUN check from config_loader |

### mt5_gateway.py gap (detailed)

`MT5Gateway.send_demo_market_order()` and `send_demo_pending_order()` and `modify_demo_position_sl_tp()` bypass the `execution_manager.py` safety pipeline entirely. They check only:
1. `DEMO_TRADING_ENABLED` (a module-level constant from `config.py`, not the YAML config)
2. `is_demo_account()` (server name keyword check)

They do NOT check:
- `is_kill_switch()` from `config_loader.py`
- `is_dry_run()` from `config_loader.py`
- Magic number registry

**Risk level:** MEDIUM — These methods are not called by `main_loop.py` or the new pipeline. But they exist as callable functions and could be triggered by voice assistant, algory_runner, or manual scripts.

### Archive files
All `order_send` calls in `src/mt5_ai/archive/` are in dead code that is not imported by any active module. Risk: LOW (files could be manually executed or accidentally imported).

---

## 8. Full Pipeline Diagram (Confirmed)

```
MT5 bars (read-only via copy_rates_from_pos)
  │
  ├─ FractalAgent.analyse()   → SignalProposal (can_execute=False)
  ├─ SmcAgent.analyse()       → SignalProposal or NO_CONFIRMATION
  └─ IctSweepAgent.analyse()  → SignalProposal or None
         │
         ▼
  SignalArbiter.decide()
  ├─ Fractal + SMC → weighted score (0.45 + 0.45 + 0.10 session)
  ├─ Threshold 0.70 gate
  ├─ Logs to logs/arbitration_decisions.jsonl
  └─ Emits ONE ArbiterDecision
         │
  (if HOLD → return early, no downstream reached)
         │
  arb.to_signal_proposal() → single arb_signal
         │
         ▼
  DecisionRouter.route([arb_signal])
  ├─ Source weight lookup (signal_arbiter gets default 1.0)
  └─ buy/sell scoring → DecisionResult
         │
  (if HOLD → return early)
         │
         ▼
  ConflictGuard.check()
  ├─ can_execute guard
  ├─ buy+sell conflict (inert — single signal from arbiter)
  ├─ opposite position check (INERT — empty dict hardcoded)
  ├─ confidence floor
  └─ single weak signal check
         │
         ▼
  RiskManager.validate()
  ├─ kill_switch
  ├─ spread check (INERT — spread_points always 0)
  ├─ position count check (INERT — open_positions always 0)
  ├─ daily loss check (INERT — daily_loss_pct always 0)
  └─ confidence floor
         │
         ▼
  ATR-based SL/TP computation (main_loop.py lines 132–147)
         │
         ▼
  ExecutionManager.execute(req)
  ├─ kill_switch → block
  ├─ req.is_valid() → block if lot=0 / magic=0 / sl=0
  ├─ validate_request(magic) → block if unknown magic
  ├─ is_dry_run() → return simulated result (CURRENT STATE)
  ├─ is_live_allowed() → block if not authorized
  └─ MT5Gateway.send_order() ← UNREACHABLE in DRY_RUN
                                (also: send_order() METHOD DOES NOT EXIST — see finding #9)

Position Management (parallel path):
  RiskCloseAgent.evaluate_positions() → PositionManagementRequest
  GovernorAgent.evaluate_positions()  → PositionManagementRequest
         │
  PositionManager.handle()
         │ generates ExecutionRequest with magic=0
         │
  ExecutionManager.execute() ← BLOCKED: validate_request(0) raises ValueError
                                (position management BROKEN — see CODEX ACTION LIST)
```

---

## 9. Architecture Gaps Summary

| # | Gap | Severity |
|---|---|---|
| 1 | `position_manager.py` uses `magic=0` → all position management fails at magic validation | CRITICAL |
| 2 | `execution_manager.py` calls `gw.send_order()`, `gw.close_position()`, `gw.modify_position()` which don't exist in `MT5Gateway` | CRITICAL (masked by DRY_RUN) |
| 3 | `AiAgent`, `ScalperAgent` imported but never called in `run_cycle()` | LOW |
| 4 | `IctSweepAgent` signals collected but not weighted by arbiter (confirmer only, weight=0) | MEDIUM |
| 5 | `ConflictGuard` receives empty `open_positions={}` — opposite position rule never fires | MEDIUM |
| 6 | `RiskManager` receives spread=0, positions=0, daily_loss=0 — three checks never fire | MEDIUM |
| 7 | `SignalArbiter` instantiated per cycle instead of once in `main()` | LOW |
| 8 | `MT5Gateway` demo methods bypass ExecutionManager safety pipeline | MEDIUM |
| 9 | `decision_router.py` has no weight entry for `"signal_arbiter"` source | LOW |

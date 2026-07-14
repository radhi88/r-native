# Report 20 — Qader Live Autopilot Architecture Review

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Scope:** Overall architecture for QADER_LIVE_AUTOPILOT mode — what exists, what is missing, integration gaps

---

## 1. Current State — Two Parallel Application Stacks

The project currently contains **two separate Qader application stacks** that are not integrated:

| Stack | Entry Point | Technology | Purpose |
|---|---|---|---|
| **qader_app** | `src/qader_app/main.py` | PyQt6 desktop app | Canonical Qader GUI — tabs, scanner, permissions, genome |
| **JarvisLive (mark_xxxix)** | `mark_xxxix/main.py` | PyQt6 + Gemini Live | Voice-first assistant — live audio, AI conversation |

**The canonical Qader desktop application for live trading is `src/qader_app/`.** This stack has the proper permissions system, audit log, scanner pipeline, and execution gate already partially wired. It uses `src/qader_app/main.py` as its entry point and `packaging/qader.spec` as its PyInstaller spec.

The `mark_xxxix/` stack is the voice-first JarvisLive assistant. It is a separate product that happens to share the same project root. For `QADER_LIVE_AUTOPILOT`, the `qader_app` stack is the correct target.

---

## 2. What Exists — Significant Prior Work

The following infrastructure already exists and is functional:

### 2.1 Execution Gate (REAL_CONTROLLED_MODE)
`src/mt5_ai/core/execution_manager.py` — `_execute_real_controlled_market()` implements:
- 30+ validation gates before any `mt5.order_send` call
- Config-level checks: `mode == REAL_CONTROLLED_MODE`, `allow_live_trading=True`, `simulate_only=False`, `dry_run=False`
- Kill_switch gate
- Permissions gate: `can_place_live_orders`, `_real_controlled_mode_unlocked`, `_real_unlock_phrase_confirmed`
- Lockdown timestamp freshness check (max_age_minutes from config)
- Account state gate: reads live `mt5.account_info()` at order time
- Spread filter
- Magic number enforcement: `QADER_REAL_CONTROLLED_MAGIC = 20260514`
- Full pre-order and post-order audit log via `qader_app.storage.audit_log`
- Pending orders disabled, no martingale, no grid, no pyramiding, no averaging, no re-entry loop
- One market order per run limit

### 2.2 Permissions System
`src/qader_app/storage/settings_store.py` — `PermissionsStore` implements:
- `unlock_real_controlled_mode(phrase, lockdown_summary)` — requires exact phrase `"I ACCEPT REAL TRADING RISK"` AND clean lockdown (exit_code=0, zero open positions, zero pending orders, no external magic=0 exposure)
- `lock_real_controlled_mode(reason)` — immediate lock
- `load()` — forces `can_place_live_orders=False` unless all unlock conditions are satisfied
- All permissions stored in `data/qader/permissions.json`

### 2.3 Lockdown Verification
`verify_mt5_lockdown.py` — standalone script that:
- Connects to MT5, reads account info, open positions, pending orders
- Returns exit code 0 only if account is clean (zero positions, zero pending orders)
- Called by the ExecutionManager lockdown freshness check

### 2.4 PermissionsGuard (per-action enforcement)
`src/qader_app/assistant/permissions_guard.py` — every service action checks a specific permission before executing. `can_place_live_orders` requires all three unlock conditions to be simultaneously true.

### 2.5 Audit Log
`src/qader_app/storage/audit_log.py` — JSONL audit trail at `logs/qader_audit.jsonl`. Pre-order and post-order events are logged. `ExecutionManager._audit()` calls this.

### 2.6 Market Scanner
`src/qader_app/services/scanner_service.py` — runs FractalAgent + SmcAgent + IctSweepAgent → SignalArbiter → ConflictGuard → RiskManager. Read-only; never executes.

### 2.7 Genome / DNA System
- `src/qader_app/genome/gene_store.py` — default_genome.json, active_genome.json, genome_history.jsonl, performance_journal.jsonl
- `src/qader_app/genome/mutation_engine.py` — propose_threshold_adjustment, apply (requires `can_modify_strategy_dna`), rollback_to_default, auto_rollback_if_bad
- `src/qader_app/genome/evaluation_engine.py` — scores dry-run decisions by confidence

### 2.8 Emergency Stop
`RunnerService.emergency_stop()` activates kill_switch and stops the voice listener. Connected to `MainWindow.emergency_stop()` via `dashboard.emergency_button`.

### 2.9 Project Root Portability
`src/mt5_ai/core/project_root.py` — all 17 previously hardcoded paths fixed. `FRIDAY_PROJECT_ROOT` env var supported.

---

## 3. Architecture Gap Analysis

### 3.1 CRITICAL: execute() Main Path Does Not Route REAL_CONTROLLED_MODE

**File:** `src/mt5_ai/core/execution_manager.py` — `execute()` method

The `execute()` method (the main entry point for the trading pipeline) handles:
1. Kill switch → block
2. DRY_RUN → simulate
3. `is_live_allowed()` → requires `mode == "LIVE"` AND `allow_live_trading=True`
4. Otherwise → MT5Gateway.send_order() (which is **permanently blocked**)

`REAL_CONTROLLED_MODE` is not `"LIVE"` mode. `is_live_allowed()` returns `False` for it. So:
- `execute()` called in REAL_CONTROLLED_MODE → returns `"live_trading_not_allowed_in_config"` and **never reaches `_execute_real_controlled_market()`**
- The real execution path `_execute_real_controlled_market()` is only reachable by calling it directly, not through `execute()`

**Required fix:** Add a REAL_CONTROLLED_MODE branch to `execute()`:
```python
# After is_dry_run() check, before is_live_allowed():
if is_real_controlled_mode() and is_real_controlled_allowed():
    return self._execute_real_controlled_market(req)
```

### 3.2 CRITICAL: No Autonomous Live Trading Loop

`RunnerService` only implements `run_fixed_dry_run()`. There is no `run_live_autopilot()` or autonomous loop for REAL_CONTROLLED_MODE. The live autopilot loop must:
- Continuously scan user-selected symbols/timeframes
- Call the full pipeline: Agents → SignalArbiter → ConflictGuard → RiskManager → ExecutionManager
- Enforce daily/session loss limits
- Enforce max open positions from risk profile
- Check kill_switch each cycle
- Log every scan result regardless of outcome
- Stop cleanly on emergency stop

### 3.3 CRITICAL: No Live Unlock GUI Screen

The current `PermissionsView` in the GUI is not a multi-step unlock wizard. The required unlock sequence (account info → lockdown verify → phrase → risk profile → symbols → daily loss limit) does not exist as a UI flow. Only the storage layer (`PermissionsStore.unlock_real_controlled_mode`) exists.

### 3.4 HIGH: config/trading_runtime.yaml Missing REAL_CONTROLLED_MODE Keys

`ExecutionManager.validate_real_controlled_request()` reads these keys from config:
- `execution.pending_orders_enabled` — expected `false`
- `execution.averaging_enabled` — expected `false`
- `execution.martingale_enabled` — expected `false`
- `execution.grid_enabled` — expected `false`
- `execution.pyramiding_enabled` — expected `false`
- `execution.reentry_loop_enabled` — expected `false`
- `runtime.max_runtime_minutes` — freshness window for lockdown timestamp
- `execution.comment` — comment prefix check in REAL_CONTROLLED_MODE

None of these are currently in `config/trading_runtime.yaml`. Without them, `validate_real_controlled_request()` would fail all these gates (defaults to `None != False` → fails).

### 3.5 HIGH: Dynamic Risk Governor Missing

`RiskManager.validate()` uses `get("risk.max_lot")` as both the approved lot and the adjusted lot. No equity-based calculation exists. The lot returned is always `0.10` (or whatever `max_lot` is in config) — regardless of account balance, equity, SL distance, or risk profile.

Required: A `RiskGovernor` that computes:
```
risk_amount = equity × risk_percent_per_trade
estimated_loss_per_lot = sl_distance / tick_size × tick_value
lot = risk_amount / estimated_loss_per_lot
lot = clamp(lot, broker_min_lot, broker_max_lot, profile_max_lot)
```

### 3.6 HIGH: Risk Profiles Not Implemented

No Conservative/Balanced/Aggressive/Extreme profiles exist anywhere in the codebase. The genome has a fixed `max_lot: 0.01`. The `trading_runtime.yaml` has a fixed `max_lot: 0.10`. Neither is parameterized per profile.

### 3.7 MEDIUM: Two Entry Points for One Product

`packaging/qader.spec` correctly points to `src/qader_app/main.py`. The `qader.spec` created at the project root today points to `mark_xxxix/main.py`. These are different products. Codex should update `qader.spec` at the root to match `packaging/qader.spec` (qader_app entry point), or delete the root-level spec and use `packaging/qader.spec` exclusively.

### 3.8 MEDIUM: Packaging Spec Missing Assets

`packaging/qader.spec` includes `live_micro_disabled.yaml` which does not exist in `config/`. The spec also lacks Vosk model, faster-whisper hidden imports, and google.genai.

---

## 4. Architecture Map — After Live Autopilot

```
User → Qader GUI (qader_app/main.py)
         │
         ├── Unlock Live Autopilot (new: LiveUnlockWizard)
         │    ├── 1. Show account info (MT5Service.account_snapshot)
         │    ├── 2. Run verify_mt5_lockdown.py (exit_code must be 0)
         │    ├── 3. Require phrase: "I ACCEPT REAL TRADING RISK"
         │    ├── 4. Select risk profile (Conservative/Balanced/Aggressive/Extreme)
         │    ├── 5. Select allowed symbols/timeframes
         │    ├── 6. Set max daily loss / max session loss
         │    └── 7. PermissionsStore.unlock_real_controlled_mode()
         │
         ├── Autonomous Live Loop (new: LiveAutopilotService)
         │    ├── Loop: scan selected symbols/timeframes
         │    ├── Pipeline: Agents → Arbiter → Router → ConflictGuard
         │    ├── RiskGovernor: equity-based lot sizing (new)
         │    ├── ExecutionManager.execute() → REAL_CONTROLLED_MODE branch (fix required)
         │    │    └── _execute_real_controlled_market() [30+ gates] → mt5.order_send
         │    └── Post-trade: record result, update performance journal
         │
         ├── Position Management (existing: GovernorAgent + RiskCloseAgent → PositionManager)
         │    └── Breakeven, partial TP, trailing SL, EOD close
         │
         └── Emergency Stop → kill_switch.activate() → immediate halt
```

---

## 5. Safe Implementation Order

1. Fix `execute()` to route REAL_CONTROLLED_MODE (no new risk introduced — just wires existing gate)
2. Add missing YAML keys to `trading_runtime.yaml`
3. Implement `RiskGovernor` with equity-based lot sizing + risk profiles
4. Implement `LiveUnlockWizard` GUI (multi-step)
5. Implement `LiveAutopilotService` autonomous loop
6. Update DNA genome to include risk profile and module toggle fields
7. Add signal/bias/filter module toggle infrastructure to scanner and genome
8. Expand DashboardView: live status badge, account panel, risk meter, scanner table
9. Add live trade result recording to EvaluationEngine
10. Update `packaging/qader.spec` with correct assets and hidden imports

---

## 6. Summary Table

| Gap | Severity | Blocking Live | Fix Location |
|---|---|---|---|
| execute() doesn't route REAL_CONTROLLED_MODE | CRITICAL | YES | `execution_manager.py` |
| No autonomous live trading loop | CRITICAL | YES | new `LiveAutopilotService` |
| No live unlock GUI wizard | CRITICAL | YES | new `LiveUnlockWizard` |
| Missing YAML keys for REAL_CONTROLLED_MODE | CRITICAL | YES | `trading_runtime.yaml` |
| No dynamic risk governor | HIGH | YES | new `RiskGovernor` |
| No risk profiles | HIGH | YES | genome + config + UI |
| Two spec files (different entry points) | MEDIUM | NO | delete root qader.spec or sync |
| Packaging spec missing assets | MEDIUM | YES (EXE build) | `packaging/qader.spec` |
| No signal/bias/filter toggles | MEDIUM | NO | genome + scanner |
| DNA learning from real trades | MEDIUM | NO | `EvaluationEngine` |

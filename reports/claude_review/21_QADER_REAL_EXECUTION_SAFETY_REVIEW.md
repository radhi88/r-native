# Report 21 — Qader Real Execution Safety Review

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Scope:** Order execution gate, kill_switch, live unlock conditions, audit trail, order send path

---

## 1. Execution Gate — What Already Exists

`ExecutionManager._execute_real_controlled_market()` implements an extensive pre-flight check before calling `mt5.order_send`. The gate checks are recorded and returned as a structured report.

### Gates Verified (30+ conditions):

**Config gates:**
- `runtime_mode == REAL_CONTROLLED_MODE`
- `allow_live_trading == True`
- `simulate_only == False`
- `dry_run == False`
- `kill_switch == False`
- `is_real_controlled_allowed()` (composite config check)
- `pending_orders_enabled == False`
- `averaging_enabled == False`
- `martingale_enabled == False`
- `grid_enabled == False`
- `pyramiding_enabled == False`
- `reentry_loop_enabled == False`
- `one_market_order_per_run == True` (only 1 order per executor lifecycle)

**Permissions gates:**
- `can_place_live_orders == True`
- `_real_controlled_mode_unlocked == True`
- `_real_unlock_phrase_confirmed == True`
- `_real_lockdown_exit_code == 0`
- `lockdown timestamp fresh` (within `max_runtime_minutes` from config)

**Request gates:**
- `execution_request_valid` (SL required, lot > 0, etc.)
- `action_buy_or_sell`
- `signal_arbiter_decision_buy_sell` (comment must contain "ARB" — arbiter result required)
- `final_confidence >= min_decision_confidence`
- `risk_manager_approved`
- `sl_required` (SL > 0)
- `tp_or_trailing_required` (TP > 0)
- `lot == fixed_lot` (exact match to config fixed_lot)
- `lot <= max_lot`
- `magic_number == QADER_REAL_CONTROLLED_MAGIC == 20260514`
- `comment contains execution.comment prefix`

**Account gates (live MT5 query at order time):**
- `account_info_readable`
- `open_positions_clean` (0 positions, < max_open_positions)
- `pending_orders_clean` (0 pending orders)
- `magic0_external_exposure_none` (no external/Exness positions)
- `spread_within_limit`

**Audit:**
- Pre-order audit event: full gate report logged before any order send
- Post-order audit event: retcode, order ticket, deal ticket logged after order send
- Both events written to `logs/qader_audit.jsonl` via `audit_log.log_action()`

**Conclusion: The execution gate itself is thorough.** If all conditions are met and `_execute_real_controlled_market()` is called, the order will only send after 30+ verified conditions.

---

## 2. CRITICAL FINDING — execute() Does Not Route to REAL_CONTROLLED_MODE

**File:** `src/mt5_ai/core/execution_manager.py` — `execute()` method

This is the most important safety-critical gap in the current implementation.

The main `execute()` method that is called by the trading pipeline has this logic:
```python
def execute(self, req):
    if is_kill_switch():        → block
    validate request            → block if invalid
    validate magic              → block if unregistered
    if is_dry_run():            → simulate (return success=True, simulated=True)
    if not is_live_allowed():   → block ("live_trading_not_allowed_in_config")
    # Falls through to MT5Gateway.send_order() — PERMANENTLY BLOCKED
```

`is_live_allowed()` checks: `mode == "LIVE" AND allow_live_trading=True AND not kill_switch`

In `REAL_CONTROLLED_MODE`: `mode == "REAL_CONTROLLED_MODE"` ≠ `"LIVE"`, so `is_live_allowed()` returns `False`.

**Result:** In REAL_CONTROLLED_MODE, `execute()` returns `"live_trading_not_allowed_in_config"` and **never calls `_execute_real_controlled_market()`**. The 30-gate pre-flight check is bypassed — not because it's insecure, but because the routing never reaches it.

**Also:** Even if `is_live_allowed()` returned True (e.g., in "LIVE" mode), `MT5Gateway.send_order()` permanently returns `blocked:"live_order_adapter_blocked"`. There is currently NO path from `execute()` to a real `mt5.order_send`.

**Required fix:**
```python
def execute(self, req: ExecutionRequest) -> ExecutionResult:
    if is_kill_switch():
        ...
    ok, msg = req.is_valid()
    if not ok:
        ...
    try:
        validate_request(req.magic, req.comment)
    except ValueError as e:
        ...
    if is_dry_run():
        ...  # simulate
    # ADD THIS BLOCK:
    if is_real_controlled_mode():
        return self._execute_real_controlled_market(req)
    if not is_live_allowed():
        ...
    ...  # MT5Gateway path (blocked — future LIVE mode)
```

This change routes REAL_CONTROLLED_MODE through the 30-gate check while keeping all other paths unchanged.

---

## 3. config/trading_runtime.yaml Missing REAL_CONTROLLED_MODE Keys

`validate_real_controlled_request()` checks these config keys — all missing from current `trading_runtime.yaml`:

| Key | Required Value | Current | Gate Result |
|---|---|---|---|
| `execution.pending_orders_enabled` | `false` | missing | FAIL (`None != False`) |
| `execution.averaging_enabled` | `false` | missing | FAIL |
| `execution.martingale_enabled` | `false` | missing | FAIL |
| `execution.grid_enabled` | `false` | missing | FAIL |
| `execution.pyramiding_enabled` | `false` | missing | FAIL |
| `execution.reentry_loop_enabled` | `false` | missing | FAIL |
| `runtime.max_runtime_minutes` | e.g. `480` | missing | freshness check broken |
| `execution.comment` | e.g. `"QADER_RC"` | missing | comment gate FAIL |

**Impact:** Even if the execution routing is fixed, every REAL_CONTROLLED_MODE order would fail the gate with 8 simultaneous gate failures.

**Required additions to `trading_runtime.yaml`:**
```yaml
execution:
  ...existing keys...
  pending_orders_enabled: false
  averaging_enabled: false
  martingale_enabled: false
  grid_enabled: false
  pyramiding_enabled: false
  reentry_loop_enabled: false
  comment: "QADER_RC"     # must appear in every real order comment

runtime:
  ...existing keys...
  max_runtime_minutes: 480   # lockdown timestamp valid for 8 hours
```

---

## 4. Unlock Phrase and Lockdown Verification

### What exists:
- `PermissionsStore.unlock_real_controlled_mode(phrase, lockdown_summary)`:
  - Phrase must equal `"I ACCEPT REAL TRADING RISK"` exactly (case-sensitive)
  - `lockdown_summary.exit_code` must be `0`
  - `lockdown_summary.open_positions` must be `0`
  - `lockdown_summary.pending_orders` must be `0`
  - `lockdown_summary.external_magic0_exposure` must be `False`
- `verify_mt5_lockdown.py` produces exit codes 0/1/2 based on account state
- `PermissionsStore.load()` forces `can_place_live_orders=False` unless ALL three conditions are simultaneously satisfied: `_real_controlled_mode_unlocked AND _real_unlock_phrase_confirmed AND _real_lockdown_exit_code == 0`

### What is missing:
- **GUI wizard** to collect these conditions step by step (see Report 24)
- **Lockdown re-verification** before each session start (ExecutionManager checks timestamp freshness, but `max_runtime_minutes` is not yet in config)
- **Auto-relock** on session end, emergency stop, or app close

### Recommended: Add auto-relock on session end
```python
# In LiveAutopilotService.stop():
PermissionsStore().lock_real_controlled_mode("session_ended")
```

---

## 5. Kill Switch Behavior

`kill_switch.py` — `activate()` writes `kill_switch: true` to the active config file via `active_config_path()` (fixed in prior session).

Kill switch is checked:
- First line of `ExecutionManager.execute()` ✅
- First line of `ExecutionManager.cancel_pending_order()` ✅
- First line of `ExecutionManager.send_raw_order()` ✅
- First check in `validate_real_controlled_request()` ✅ (gate `kill_switch_false`)
- First check in `RunnerService.emergency_stop()` ✅

**Finding:** Kill switch is adequately enforced across all execution paths.

**Gap:** `kill_switch.deactivate()` would re-enable trading. This must require the same unlock phrase + lockdown verification. Currently `deactivate()` writes `kill_switch: false` without any confirmation gate.

**Required fix:** `kill_switch.deactivate()` should be blocked unless called explicitly by the unlock wizard after re-verification.

---

## 6. Order Parameters Required

Every real order must include:
- `magic`: `20260514` (`QADER_REAL_CONTROLLED_MAGIC`) ✅ enforced by gate
- `comment`: must contain `execution.comment` prefix ✅ enforced by gate
- `sl`: must be > 0 ✅ enforced by gate
- `tp`: must be > 0 ✅ enforced by gate (TP required — trailing stop not yet implemented as alternative)
- `deviation`: `20` (from config) ✅ in ExecutionRequest
- `type_filling`: `IOC` ✅ in `_execute_real_controlled_market()`
- `type_time`: `GTC` ✅ in `_execute_real_controlled_market()`

**Gap:** The `lot` gate checks `lot == fixed_lot` (exact match to config `risk.fixed_lot`). This conflicts with a dynamic equity-based lot size. When the risk governor is implemented, this gate must change to `min_lot <= lot <= max_lot` rather than exact fixed_lot match.

---

## 7. voice → execute() Safety

Per the review: Voice triggers `_friday_stack_control()` — now blocked (fixed in prior session). Voice cannot call `execute()` directly. Voice commands route through `QaderBrain` and `RunnerService`, neither of which has a `run_live_real_order()` method.

**Confirmed:** Live orders cannot be triggered by voice alone. Live unlock requires GUI wizard with typed phrase. ✅

---

## 8. Audit Trail Adequacy

Current audit events logged for REAL_CONTROLLED_MODE:
- `real_controlled_pre_order_gate_check` — full gate report before order send
- `real_controlled_before_order_send` — exact MT5 request dict logged
- `real_controlled_after_order_send` — retcode, order ticket, deal ticket logged
- `real_controlled_order_send_exception` — exception logged if MT5 call throws

**Gap:** Post-trade P/L recording is missing. After a position is opened, there is no automated mechanism to detect when it closes and record the outcome (profit/loss, duration, exit reason). This is needed for DNA learning.

---

## 9. Safety Summary

| Item | Status |
|---|---|
| Kill switch enforced on all execution paths | ✅ CONFIRMED |
| DRY_RUN simulated — never reaches MT5 | ✅ CONFIRMED |
| Real order requires 30+ gates | ✅ CONFIRMED |
| Voice cannot trigger live orders | ✅ CONFIRMED (stack control now blocked) |
| Unlock requires typed phrase + clean lockdown | ✅ CONFIRMED |
| Permissions forced to False unless all conditions met | ✅ CONFIRMED |
| execute() routes REAL_CONTROLLED_MODE to gate | ❌ MISSING — must be added |
| YAML config has REAL_CONTROLLED_MODE keys | ❌ MISSING — 8 keys needed |
| Lot gate compatible with dynamic sizing | ❌ INCOMPATIBLE — exact fixed_lot match |
| kill_switch.deactivate() requires confirmation | ❌ MISSING — any caller can deactivate |
| Post-trade P/L recorded | ❌ MISSING — needed for DNA learning |
| Audit log pre+post order | ✅ CONFIRMED |

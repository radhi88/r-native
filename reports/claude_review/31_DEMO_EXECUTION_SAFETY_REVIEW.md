# Review 31 — Demo Execution Safety Review
**Reviewer:** Claude (Supervisor)  
**Date:** 2026-05-14  
**Scope:** Requirements 6, 8, 9, 10, 13: order_send gateway, safety guards, SL enforcement, emergency stop.

---

## Summary Verdict: PASS WITH ONE CRITICAL BUG — All safety gates present; gate logic has a defect in multi-position scenario.

---

## REQUIREMENT 6: order_send only through execution_manager.py

**Status:** ✅ PASS — Verified by code audit

**Evidence:**
- `src/mt5_ai/core/execution_manager.py:244` — only one call to `mt5.order_send()`, inside `_execute_real_controlled_market()`.
- All execution paths converge at `ExecutionManager.execute()`:
  - `real_time_loop_service.py:514` → `exec_mgr.execute(req)`
  - `real_mode_service.py:276` → same via `main_loop.run_cycle()`
  - `runner_service.py:82` → dry run path
- `runner_service.py:53-55` — monkeypatches `mt5.order_send` to a hard blocker in dry run mode (defense-in-depth).
- No other file in `src/` calls `mt5.order_send` directly.

---

## REQUIREMENT 8: SignalArbiter, ConflictGuard, RiskManager remain active

**Status:** ✅ PASS — All three are wired in both execution paths

**Pipeline confirmed:**
```
Agents → SignalArbiter → DecisionRouter → ConflictGuard → RiskManager → ExecutionManager
```

In `real_time_loop_service.py:172-173`:
```python
guard = ConflictGuard()
risk_mgr = RiskManager()
arbiter = SignalArbiter()
```

In `_scan_symbol_cycle()`:
- Line 442: `arb = arbiter.decide(raw_signals, symbol, timeframe)`
- Line 459: `allow, conflicts = guard.check(decision, [arb_signal], open_positions_map)`
- Line 467: `risk_decision = risk_mgr.validate(decision, symbol, ...)`

**Arbitration evidence:** `logs/arbitration_decisions.jsonl` — 100+ entries confirmed.

**Conflict guard evidence:** `logs/conflict_log.jsonl` — file exists.

**Risk log evidence:** `logs/risk_log.jsonl` — file exists.

---

## REQUIREMENT 9: No grid, no martingale, no averaging

**Status:** ✅ PASS — Enforced at config + gate level

**Config enforcement** (`config/real_controlled_mode.yaml`):
```yaml
execution:
  averaging_enabled: false
  martingale_enabled: false
  grid_enabled: false
  pyramiding_enabled: false
  reentry_loop_enabled: false
```

**Gate enforcement** (`execution_manager.py:94-98`):
```python
self._gate(gates, "no_averaging",     execution.get("averaging_enabled")  is False, ...)
self._gate(gates, "no_martingale",    execution.get("martingale_enabled") is False, ...)
self._gate(gates, "no_grid",          execution.get("grid_enabled")        is False, ...)
self._gate(gates, "no_pyramiding",    execution.get("pyramiding_enabled")  is False, ...)
self._gate(gates, "no_reentry_loop",  execution.get("reentry_loop_enabled") is False, ...)
```

If any of these keys are `True`, the gate fails and the order is blocked.

---

## REQUIREMENT 10: SL is always required

**Status:** ✅ PASS — Enforced at gate + ATR calculation level

**Gate enforcement** (`execution_manager.py:141`):
```python
self._gate(gates, "sl_required", float(req.sl or 0.0) > 0, f"sl={req.sl}")
```

**ATR-based SL calculation** (`real_time_loop_service.py:481-489`):
```python
atr = calc_atr(bars, period=14)
sl_dist = max(atr * 1.5, 0.0001)  # minimum 0.0001 — never zero
if arb.final_direction == Direction.BUY:
    sl = round(last_close - sl_dist, 5)
else:
    sl = round(last_close + sl_dist, 5)
```
SL is always non-zero before the request is built. `max(atr * 1.5, 0.0001)` guarantees a positive distance.

**Config enforcement:**
```yaml
risk:
  require_sl: true
```

---

## REQUIREMENT 13: Emergency stop works

**Status:** ✅ PASS — Three independent stop paths confirmed

**Path 1 — GUI Dashboard (`main_window.py:67-71`):**
```python
def emergency_stop(self) -> None:
    self.runner.emergency_stop()           # kills RunnerService loop
    self.real_mode.lock("dashboard_emergency_stop")  # locks permissions
    self.voice.listening = False
```

**Path 2 — Real Controlled Mode panel (`real_controlled.py:160-164`):**
```python
def emergency_stop(self) -> None:
    self.service.lock("emergency_stop")    # locks real mode service
```

**Path 3 — RealTimeLoopService (`real_time_loop_service.py:132-142`):**
```python
def emergency_stop(self) -> dict[str, Any]:
    self._stop_event.set()                 # terminates loop thread
    self._pause_event.set()
    self._set_state(self.EMERGENCY_STOP, "emergency_stop")
    from mt5_ai.core.kill_switch import activate
    activate("qader_emergency_stop")       # writes kill_switch=true to YAML
```

**Kill switch propagation** (`kill_switch.py:9-15`):
- Writes `runtime.kill_switch = true` to the active YAML config.
- Calls `config_loader.load(force=True)` to propagate immediately.
- Every cycle in every loop checks `is_kill_switch()` before any execution.

---

## BUGS FOUND

### BUG-31-A: `open_positions_clean` gate logic is unnecessarily restrictive

**Priority:** HIGH  
**File:** `src/mt5_ai/core/execution_manager.py:179`  
**Current code:**
```python
self._gate(gates, "open_positions_clean",
           len(positions) == 0 and len(positions) < max_open,
           f"open_positions={len(positions)},max={max_open}")
```
**Issue:** The condition `len(positions) == 0 and len(positions) < max_open` always requires zero open positions. With `max_open_positions=1` this is correct by coincidence, but if `max_open_positions` is ever raised to 3, the gate would still block any entry when even 1 position exists. The `== 0` check is incorrect.

**Risk:** Prevents multi-trade even when configured for 3 max positions.

**Recommendation for Codex:** Change to:
```python
self._gate(gates, "open_positions_clean",
           len(positions) < max_open,
           f"open_positions={len(positions)},max={max_open}")
```
**Safe to apply now:** YES

### BUG-31-B: `one_market_order_per_run` counter not reset between loop cycles

**Priority:** CRITICAL  
**File:** `src/mt5_ai/core/execution_manager.py` + `src/qader_app/services/real_time_loop_service.py`  
**Issue:** `_real_orders_sent_this_run` is reset only once at loop startup via `exec_mgr.reset_real_controlled_run()`. After 1 successful order, all subsequent orders in the same run (infinite loop) are blocked by the `one_market_order_per_run` gate. The execution log confirms this:
```
7 attempts with magic=20260514 — ALL failed: "real_controlled_gate_blocked:one_market_order_per_run"
```

**Risk:** CRITICAL — System can never place more than 1 real order per application session. Multi-trade is structurally impossible.

**Recommendation for Codex:** See Action List item A-32-01 for full fix.  
**Safe to apply now:** YES (controlled change)

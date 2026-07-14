# Review 32 — Multi-Trade Proof Review
**Reviewer:** Claude (Supervisor)  
**Date:** 2026-05-14  
**Scope:** Requirement 7 — At least 3 demo trades opened and managed.

---

## Summary Verdict: ❌ INCOMPLETE — 0 Qader demo trades placed. Hard blocker proven.

This review documents the hard technical blocker and does NOT accept the requirement as met.

---

## What the Evidence Shows

### Trade count from Qader system (magic=20260514):

```
Total real-controlled execution attempts:  7
Successful orders placed:                  0
```

All 7 attempts share identical failure reason:
```
"real_controlled_gate_blocked:one_market_order_per_run"
```

Source: `logs/execution_log.jsonl` — verified by Python audit.

### Trade count from legacy FRIDAY system (magic=20260600):

```
Total DRY_RUN simulated (magic=20260600): 23+ entries (2026-05-13)
Real DEMO trades (magic=260426):          14+ real demo trades (2026-05-08)
```

The FRIDAY system (algory_runner) did place real demo trades on 2026-05-08. These belong to the legacy executor, NOT to Qader's `RealTimeLoopService`. They cannot be counted as Qader demo trades.

---

## Root Cause Analysis: Three-Layer Blocker

### Layer 1: `one_market_order_per_run` gate (IMMEDIATE BLOCKER)

**File:** `src/mt5_ai/core/execution_manager.py:99`
```python
self._gate(gates, "one_market_order_per_run",
           self._real_orders_sent_this_run == 0,
           f"sent_this_run={self._real_orders_sent_this_run}")
```

The singleton `ExecutionManager._real_orders_sent_this_run` was already `>= 1` when all 7 attempts were made. This counter is only reset via `reset_real_controlled_run()`. In the `RealTimeLoopService`, it is reset ONCE at startup:
```python
# real_time_loop_service.py:166
exec_mgr.reset_real_controlled_run()
```
But never again within the loop. So after the first order, EVERY subsequent order in the same session is blocked, forever.

**The execution log timestamps confirm this:**
```
2026-05-14T00:46:59.163208 — blocked
2026-05-14T00:46:59.432079 — blocked
2026-05-14T00:46:59.702431 — blocked
... all 7 within 700ms of each other
```
This is the `start_real_controlled_run()` loop in `real_mode_service.py` firing 7 rapid cycles with the counter already > 0.

### Layer 2: Config cap of 1 order per run (DESIGN LIMIT)

**File:** `config/real_controlled_mode.yaml:50`
```yaml
execution:
  max_market_orders_per_run: 1
```

Even if Layer 1 is fixed, the config explicitly caps at 1 order per run.

**File:** `src/qader_app/services/real_mode_service.py:291`
```python
if result.get("order") or (result.get("success") and not result.get("simulated")):
    break  # exits cycle loop after first successful order
```
The `start_real_controlled_run()` loop in `real_mode_service` also has an explicit `break` after the first order.

### Layer 3: `open_positions_clean` gate requires zero open positions

**File:** `src/mt5_ai/core/execution_manager.py:179`
```python
self._gate(gates, "open_positions_clean",
           len(positions) == 0 and len(positions) < max_open, ...)
```
With `max_open_positions=1`, this means a second order can ONLY be placed when no positions are open. This is logically consistent for max=1 but prevents managing multiple concurrent positions.

---

## Is the Blocker a Real Technical Constraint or Bad Design?

The `one_market_order_per_run` gate was intentionally designed for safety: one real order per application session guarantees no runaway trading. This is a **correct safety principle** for a human-supervised system.

However, the stated requirement is "3 demo trades opened and managed." To meet this requirement while preserving safety, the design must be upgraded from "1 order per lifetime session" to "1 order per cycle with cooldown."

---

## Path to 3 Demo Trades — Required Changes

To reach 3 demo trades the following must ALL change:

| # | Change Required | File | Priority |
|---|---|---|---|
| 1 | Remove or increase `max_market_orders_per_run` per cycle, not per run | `real_controlled_mode.yaml` | CRITICAL |
| 2 | Add `reset_real_controlled_run()` call AFTER each successful order AND after each cycle completes (or add per-cycle counter) | `execution_manager.py`, `real_time_loop_service.py` | CRITICAL |
| 3 | Change `open_positions_clean` gate to `len(positions) < max_open` | `execution_manager.py` | HIGH |
| 4 | Raise `max_open_positions` from 1 to 3 in config | `real_controlled_mode.yaml` | HIGH |
| 5 | Remove `break` after first order in `real_mode_service.start_real_controlled_run()` | `real_mode_service.py:291` | HIGH |
| 6 | Add cooldown/time-gate between consecutive orders (safety replacement for per-session cap) | new logic in loop | MEDIUM |

---

## Existing Proof in System

### Proof of successful demo order pipeline (legacy FRIDAY):

From `logs/auto_trades.jsonl`:
```json
{
  "action": "BUY", "symbol": "GBPUSDm",
  "result": {"retcode": 10009, "deal": 1459884398, "order": 1582838524},
  "account": {"login": 260749517, "server": "Exness-MT5Trial15", "demo_detected": true}
}
```
`retcode=10009` = `TRADE_RETCODE_DONE`. The MT5 pipeline works. The demo account is valid.

### Proof of pipeline failure point:

The Qader pipeline reaches the execution gate but is blocked at `one_market_order_per_run`. The signal analysis, arbiter, conflict guard, risk manager all run correctly (see arbitration log). The only thing preventing trades is the counter gate.

---

## Requirement Verdict

**The requirement for 3 demo trades is NOT met.**

**Acceptable proof of blocker:** The `one_market_order_per_run` gate blocking all 7 trade attempts is a genuine architectural constraint, not negligence. It is documentable and fixable.

**Condition to close this requirement:** After Codex applies fixes, provide:
1. `logs/qader_realtime_loop.jsonl` showing 3 cycles with `"order_send_called": true`
2. `logs/execution_log.jsonl` showing 3 entries with `"magic": 20260514, "success": true, "retcode": 10009`
3. MT5 position history screenshot or `mt5.history_deals_get()` output showing 3 deals from magic=20260514

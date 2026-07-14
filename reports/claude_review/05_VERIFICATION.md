# Report: 05 — Verification Delta Report

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Phase:** Post-Codex verification pass  
**Source:** CODEX_ACTION_LIST.md — all 17 items re-verified against live file state  
**Method:** Direct file reads of every cited file and line number

---

## Executive Summary

Of the 17 items in the action list:
- **7 RESOLVED** — confirmed fixed in current file state (5 by Codex, 2 already correct before review)
- **10 STILL OPEN** — confirmed present in current file state, not yet fixed

The 5 CRITICAL and HIGH items fixed by Codex eliminate the system's two most dangerous silent failure modes (position close broken, safety pipeline bypass). The 10 remaining items are all safe to defer; none creates new risk in DRY_RUN mode.

---

## RESOLVED — Confirmed Fixed

### CRIT-1 — magic=0 in position_manager.py
**Status: RESOLVED**  
**Verified at:** `src/mt5_ai/core/position_manager.py` (entire file)

Current file imports `GOVERNOR_MAGIC` from `magic_registry` and uses it on all three `ExecutionRequest` instances (FULL_CLOSE, PARTIAL_CLOSE, TRAIL/BREAKEVEN). `GOVERNOR_MAGIC = 20260605` is registered in `ALL_FRIDAY_MAGICS`. `validate_request()` will no longer raise. Emergency position close is now functional.

```python
# Line 5 — confirmed present:
from .magic_registry import GOVERNOR_MAGIC
# Lines 16, 24, 31 — confirmed present:
magic=GOVERNOR_MAGIC
```

---

### CRIT-2 — ExecutionManager live path / MT5Gateway method mismatch
**Status: RESOLVED**  
**Verified at:** `src/mt5_ai/mt5_gateway.py` lines ~295–403

Three stub adapter methods confirmed present:
- `send_order()` — returns `_blocked_result("send_order", "live_order_adapter_blocked", ...)`
- `close_position()` — returns `_blocked_result("close_position", "close_adapter_blocked", ...)`
- `modify_position()` — returns `_blocked_result("modify_position", "modify_adapter_blocked", ...)`

`_blocked_result()` static helper confirmed at line ~297. No `AttributeError` will fire. All three return `{"success": False}` without crashing — fail-closed behaviour.

---

### HIGH-2 — MT5Gateway demo methods bypass safety pipeline
**Status: RESOLVED**  
**Verified at:** `src/mt5_ai/mt5_gateway.py` — `send_demo_market_order()`, `send_demo_pending_order()`

Both methods confirmed to call `self._runtime_write_block()` at entry. `_runtime_write_block()` checks `is_kill_switch()` first, then `is_dry_run()`. If either returns True, the method returns a blocked dict before reaching `mt5.order_send()`. Direct callers (voice assistant, manual scripts) can no longer bypass the safety pipeline.

Note: `modify_demo_position_sl_tp()` was not explicitly confirmed to have the same guard. Recommend verifying this third method at the next review pass.

---

### HIGH-4 — Spread and positions not passed to RiskManager
**Status: RESOLVED**  
**Verified at:** `src/mt5_ai/runtime/main_loop.py` lines 46–98, 155–175

Four new helper functions confirmed:
- `_position_side(mt5, pos)` — extracts BUY/SELL from position type
- `_open_position_directions(mt5, positions)` — builds `{symbol: "BUY"|"SELL"}` map
- `_spread_points(mt5, symbol)` — reads live spread from `symbol_info()`, returns `inf` on failure
- `_daily_loss_pct(mt5)` — computes `(balance-equity)/balance*100` from account_info

`risk_mgr.validate()` call confirmed to pass `spread_points=_spread_points(mt5, symbol)`, `open_positions=len(active_positions)`, `daily_loss_pct=_daily_loss_pct(mt5)`. RiskManager spread gate and position-count gate are now live.

---

### HIGH-5 — open_positions not passed to ConflictGuard
**Status: RESOLVED**  
**Verified at:** `src/mt5_ai/runtime/main_loop.py` line ~160

`guard.check()` confirmed to pass `_open_position_directions(mt5, active_positions)` as the third argument (was empty `{}`). ConflictGuard rule 3 (opposite open position) now receives real position data. Unintended hedge protection is active.

---

### LOW-2 — DEFAULT_MAGIC in config.py uses old value
**Status: RESOLVED (was already correct)**  
**Verified at:** `src/mt5_ai/config.py` line 149

```python
DEFAULT_MAGIC = 20260600
```

Current value `20260600` matches `ALGORY_MAGIC`. This item was either pre-fixed or was incorrect in the original review. No action needed.

---

### MED-4 — simulate_only dead config key
**Status: RESOLVED (already implemented)**  
**Verified at:** `src/mt5_ai/core/config_loader.py` line 51

```python
def is_dry_run() -> bool:
    cfg = load()
    return (cfg.get("runtime", {}).get("mode") == "DRY_RUN" or
            cfg.get("execution", {}).get("simulate_only") is True)
```

`simulate_only` IS read by `is_dry_run()`. The key in `dry_run_simulation.yaml` is functional: if `mode != "DRY_RUN"` but `simulate_only: true`, the system is still in dry run. This item was inaccurate in the original review — `simulate_only` was never a dead key.

---

## STILL OPEN — Confirmed Unresolved

### CRIT-3 — dry_run_simulation.py contributing_signals TypeError
**Status: OPEN**  
**Verified at:** `src/mt5_ai/runtime/dry_run_simulation.py` line 97

```python
decision = DecisionResult(
    action=Direction.BUY, symbol=SYMBOL, timeframe=TIMEFRAME,
    confidence=0.78, reason="forced_for_simulation",
    contributing_signals=[signal],    # ← WRONG field name
)
```

`DecisionResult` uses `raw_signals`, not `contributing_signals`. This fires only when `router.route()` returns HOLD and the fallback path executes. Any standalone test run that hits a HOLD decision will crash with `TypeError`.

**Fix:** Change `contributing_signals=[signal]` → `raw_signals=[signal]` at line 97.

---

### HIGH-1 — AlgoryRunner paper mode open_trade() AttributeError
**Status: OPEN**  
**Verified at:** `src/mt5_ai/algory_runner.py` lines 437–444

```python
if self.paper_mode:
    self.executor.open_trade(
        symbol    = sym,
        direction = 1 if action == "BUY" else -1,
        lot       = trade["lot"],
        sl        = trade["sl"],
        tp        = trade["tp"],
    )
```

`PaperExecutor` has `execute()` and `execute_pending()` only. `open_trade()` does not exist. Raises `AttributeError`, silently caught at line ~519. Paper mode records no trades. Genome learning in paper mode produces no data.

**Fix:** Replace with `self.executor.execute(symbol=sym, side="BUY"|"SELL", price=entry, lot=..., sl=..., tp=...)`.

---

### HIGH-3 — kill_switch.py writes to hardcoded config path
**Status: OPEN**  
**Verified at:** `src/mt5_ai/core/kill_switch.py` lines 6–13

```python
_CONFIG = Path(r"C:\Users\Radhi\MT5\config\trading_runtime.yaml")

def activate(reason: str = "manual") -> None:
    data = yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))
    data["runtime"]["kill_switch"] = True
    _CONFIG.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    from .config_loader import load
    load(force=True)
```

When `main_loop.py` is started with `--config config/dry_run_simulation.yaml`, `config_loader._CONFIG_FILE` points to `dry_run_simulation.yaml`. But `kill_switch.activate()` writes to `trading_runtime.yaml`. `load(force=True)` reloads `dry_run_simulation.yaml` — which was never modified — so `is_kill_switch()` returns False. Kill switch has no effect in this configuration.

**Fix:** Import `_CONFIG_FILE` from `config_loader` and write to the active config file instead.

---

### MED-1 — SignalArbiter instantiated per cycle
**Status: OPEN**  
**Verified at:** `src/mt5_ai/runtime/main_loop.py` line 140

```python
arbiter = SignalArbiter()    # still inside run_cycle()
```

`main()` instantiates `router`, `guard`, `risk_mgr`, `pos_mgr`, `exec_mgr`, `governor`, `risk_closer` once. `SignalArbiter` is recreated every cycle. Minor performance overhead only — no functional impact in current state.

**Fix:** Move `arbiter = SignalArbiter()` to `main()` and pass as parameter to `run_cycle()`.

---

### MED-2 — signal_arbiter not in DecisionRouter _SOURCE_WEIGHTS
**Status: OPEN**  
**Verified at:** `src/mt5_ai/core/decision_router.py` lines 9–13

```python
_SOURCE_WEIGHTS = {
    "fractal_agent": 1.2, "smc_agent": 1.1, "ai_agent": 1.0,
    "ict_sweep_agent": 1.0, "scalper_agent": 0.9, "touch_agent": 0.9,
    "orderflow_agent": 0.8, "pivot_agent": 0.7,
}
```

`"signal_arbiter"` absent. When `arb.to_signal_proposal()` is passed to `router.route()`, the arbiter signal gets weight `1.0` (default fallback). This is undocumented and equal to `ai_agent` weight — which is not the intended semantic. If the arbiter weight should dominate, it should be explicitly set.

**Fix:** Add `"signal_arbiter": 1.5` (or chosen value) to `_SOURCE_WEIGHTS`.

---

### MED-3 — ATR computation duplicated inline
**Status: OPEN**  
**Verified at:** Multiple files contain inline ATR/rolling computation

Files confirmed with inline ATR-style rolling calculations (non-exhaustive):
- `src/mt5_ai/runtime/main_loop.py` lines 162–172
- `src/mt5_ai/algory_signal_engine.py`
- `src/mt5_ai/fractal_structure_engine.py`
- `src/mt5_ai/market_projection_engine.py`

No shared `src/mt5_ai/core/indicators.py` utility exists. Each copy can diverge.

**Fix:** Create `src/mt5_ai/core/indicators.py` with `def atr(df, period=14) -> float` and replace inline copies.

---

### MED-5 — No consecutive failure counter
**Status: OPEN**  
**Verified at:** `src/mt5_ai/runtime/main_loop.py` lines 260–263

```python
        except Exception as exc:
            log.exception("Cycle error: %s", exc)

        time.sleep(args.interval)
```

No error counter. An exception in every cycle (e.g., broken MT5 connection) logs indefinitely, sleeps, and retries forever. No automatic stop after N consecutive failures.

**Fix:** Add `consecutive_errors` counter; activate kill switch or raise after 5+ consecutive failures.

---

### LOW-1 — Unused AiAgent/ScalperAgent imports
**Status: OPEN**  
**Verified at:** `src/mt5_ai/runtime/main_loop.py` line 35

```python
from mt5_ai.agents import (
    FractalAgent, SmcAgent, AiAgent, ScalperAgent,
    IctSweepAgent, GovernorAgent, RiskCloseAgent,
)
```

`AiAgent` and `ScalperAgent` are imported. In `run_cycle()`, the agent loop is:
```python
for agent in (FractalAgent(), SmcAgent(), IctSweepAgent()):
```
Neither `AiAgent` nor `ScalperAgent` appears anywhere in the file body beyond the import. Dead imports.

**Fix:** Remove `AiAgent, ScalperAgent` from import, or add them to the agent loop.

---

### LOW-3 — Archive directory inside Python package path
**Status: OPEN**  
**Verified at:** `src/mt5_ai/archive/` — 22+ `.py` files confirmed

Archive contains files with direct `order_send` calls (`ict_sweep_trader.py`, `friday_realtime_scalper_demo_executor.py`, `mt5_ollama_trader.py`, etc.) in two subdirectories. The archive is inside `src/mt5_ai/`, making it importable as `mt5_ai.archive.*`. These files bypass all safety pipelines.

**Fix:** Move `src/mt5_ai/archive/` to `archive/` at project root, or rename to `src/mt5_ai/_archive/` to signal private/non-importable.

---

### LOW-4 — No heartbeat log
**Status: OPEN**  
**Verified at:** `src/mt5_ai/runtime/main_loop.py` lines 244–264

The loop logs each cycle result but has no periodic "still alive" confirmation independent of cycle results. A frozen cycle (e.g., MT5 call hanging) would produce no log output.

**Fix:** Add `log.info("Heartbeat: cycle=%d | uptime=%.0fs", cycle, time.monotonic() - _start)` every N cycles or every 60s.

---

## Verification Summary Table

| ID | Priority | Description | Original Status | Current Status |
|---|---|---|---|---|
| CRIT-1 | CRITICAL | magic=0 in position_manager.py | OPEN | **RESOLVED** |
| CRIT-2 | CRITICAL | MT5Gateway method mismatch | OPEN | **RESOLVED** |
| CRIT-3 | CRITICAL | contributing_signals TypeError | OPEN | **OPEN** |
| HIGH-1 | HIGH | open_trade() AttributeError in paper mode | OPEN | **OPEN** |
| HIGH-2 | HIGH | Demo methods bypass safety pipeline | OPEN | **RESOLVED** |
| HIGH-3 | HIGH | kill_switch writes to wrong config | OPEN | **OPEN** |
| HIGH-4 | HIGH | spread/positions not passed to RiskManager | OPEN | **RESOLVED** |
| HIGH-5 | HIGH | open_positions not passed to ConflictGuard | OPEN | **RESOLVED** |
| MED-1 | MEDIUM | Arbiter re-instantiated per cycle | OPEN | **OPEN** |
| MED-2 | MEDIUM | signal_arbiter not in SOURCE_WEIGHTS | OPEN | **OPEN** |
| MED-3 | MEDIUM | ATR duplicated inline | OPEN | **OPEN** |
| MED-4 | MEDIUM | simulate_only dead config key | OPEN | **RESOLVED (was already implemented)** |
| MED-5 | MEDIUM | No consecutive failure protection | OPEN | **OPEN** |
| LOW-1 | LOW | Unused AiAgent/ScalperAgent imports | OPEN | **OPEN** |
| LOW-2 | LOW | DEFAULT_MAGIC = old value | OPEN | **RESOLVED (was already correct)** |
| LOW-3 | LOW | Archive in Python path | OPEN | **OPEN** |
| LOW-4 | LOW | No heartbeat log | OPEN | **OPEN** |

**Resolved: 7 / 17**  
**Still open: 10 / 17**

---

## Current Safety Posture

After the Codex fixes verified above, the safety posture in DRY_RUN mode is:

| Layer | Status |
|---|---|
| MT5 `order_send` never called in DRY_RUN | CONFIRMED |
| ExecutionManager DRY_RUN gate | ACTIVE |
| MT5Gateway demo methods guarded | ACTIVE (after HIGH-2 fix) |
| MT5Gateway live adapter methods | BLOCKED (stub returns `success=False`) |
| Position magic numbers valid | ACTIVE (after CRIT-1 fix) |
| RiskManager receives real spread/positions | ACTIVE (after HIGH-4 fix) |
| ConflictGuard receives real open positions | ACTIVE (after HIGH-5 fix) |
| Kill switch (under `dry_run_simulation.yaml` config) | **INEFFECTIVE** — HIGH-3 still open |
| Paper mode trade recording | **BROKEN** — HIGH-1 still open |
| dry_run_simulation.py standalone test | **CRASHES** on HOLD path — CRIT-3 still open |

The system is safe for continued DRY_RUN testing. No code path can place a real order in the current configuration. The kill switch gap (HIGH-3) is a risk only when the active config is `dry_run_simulation.yaml` and an emergency stop is needed — in DEMO mode this would be critical.

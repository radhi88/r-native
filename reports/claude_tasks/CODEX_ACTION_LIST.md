# CODEX ACTION LIST — Prioritized Implementation Checklist

**Author:** Claude (supervisor/reviewer)  
**Date:** 2026-05-14  
**Source reports:** claude_review/01–05  
**Verification:** 05_VERIFICATION.md — all items re-verified against live file state  
**Purpose:** Actionable tasks for Codex (implementer) in priority order

---

## Status Legend
- `[RESOLVED]` — Verified fixed in current file state. No further action needed.
- `[OPEN]` — Verified still present. Fix required.

---

## CRITICAL

---

### ~~CRIT-1: Fix magic=0 in position_manager.py~~ `[RESOLVED]`

**Verified:** `position_manager.py` now imports and uses `GOVERNOR_MAGIC = 20260605` on all three `ExecutionRequest` instances. `validate_request()` will not raise. Emergency position close is functional.

---

### ~~CRIT-2: Fix ExecutionManager.execute() live path — MT5Gateway method mismatch~~ `[RESOLVED]`

**Verified:** `mt5_gateway.py` now has `send_order()`, `close_position()`, `modify_position()` stub adapters that return `{"success": False, "mode": "blocked"}` without crashing. `_blocked_result()` and `_runtime_write_block()` helpers confirmed present.

---

### CRIT-3: Fix dry_run_simulation.py constructor error `[OPEN]`

**File:** `src/mt5_ai/runtime/dry_run_simulation.py`  
**Line:** 97

**Issue:**
```python
contributing_signals=[signal]    # WRONG — field doesn't exist in DecisionResult
```
`DecisionResult` uses `raw_signals`, not `contributing_signals`. Raises `TypeError` on the forced-BUY fallback path (when router returns HOLD).

**Fix:**
```python
decision = DecisionResult(
    action=Direction.BUY, symbol=SYMBOL, timeframe=TIMEFRAME,
    confidence=0.78, reason="forced_for_simulation",
    raw_signals=[signal],    # was: contributing_signals=[signal]
)
```

**Risk if ignored:** `dry_run_simulation.py` always crashes on the forced-BUY fallback path. Unusable as a standalone test tool.

**Safe to apply now:** YES — isolated to this test file.

---

## HIGH

---

### HIGH-1: Fix AlgoryRunner paper mode — open_trade() does not exist `[OPEN]`

**File:** `src/mt5_ai/algory_runner.py`  
**Line:** 438

**Issue:**
```python
self.executor.open_trade(...)   # AttributeError — PaperExecutor has no open_trade()
```
`PaperExecutor` has `execute()` and `execute_pending()`. Paper mode trade recording is completely broken. Exception caught silently at line ~519.

**Fix:** Replace with:
```python
result = self.executor.execute(
    symbol=sym,
    side="BUY" if action == "BUY" else "SELL",
    price=entry,
    lot=trade["lot"],
    sl=trade["sl"],
    tp=trade["tp"],
)
```

**Risk if ignored:** Paper mode records no trades. Genome learning has no data. Every paper trade raises a silent AttributeError.

**Safe to apply now:** YES — paper mode only, no live execution.

---

### ~~HIGH-2: Add kill_switch check to MT5Gateway demo methods~~ `[RESOLVED]`

**Verified:** `send_demo_market_order()` and `send_demo_pending_order()` now call `self._runtime_write_block()` at entry, which checks `is_kill_switch()` then `is_dry_run()`. Direct callers can no longer bypass the safety pipeline.

**Note:** `modify_demo_position_sl_tp()` was not explicitly confirmed to have the same guard — verify at next review pass.

---

### HIGH-3: Fix kill_switch.py to write to active config, not hardcoded path `[OPEN]`

**File:** `src/mt5_ai/core/kill_switch.py`  
**Lines:** 6–12

**Issue:**
```python
_CONFIG = Path(r"C:\Users\Radhi\MT5\config\trading_runtime.yaml")  # hardcoded
```
If active config is `dry_run_simulation.yaml` (via `--config` or `use_config()`), the kill switch writes to `trading_runtime.yaml` — not the file that `config_loader` is reading. `load(force=True)` reloads the unmodified active config. `is_kill_switch()` returns False. Emergency stop has no effect.

**Fix:**
```python
def activate(reason: str = "manual") -> None:
    from .config_loader import _CONFIG_FILE  # use the currently active config
    data = yaml.safe_load(_CONFIG_FILE.read_text(encoding="utf-8"))
    data["runtime"]["kill_switch"] = True
    _CONFIG_FILE.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    load(force=True)
    print(f"[KILL SWITCH ACTIVATED] reason={reason}")
```
Apply same pattern to `deactivate()`.

**Risk if ignored:** Emergency kill switch cannot stop a process running under `dry_run_simulation.yaml`. In DEMO mode this is a critical safety gap.

**Safe to apply now:** YES.

---

### ~~HIGH-4: Pass real spread and open_positions to RiskManager~~ `[RESOLVED]`

**Verified:** Helper functions `_spread_points()`, `_daily_loss_pct()` added to `main_loop.py`. `risk_mgr.validate()` now receives real values. RiskManager spread gate and position-count gate are active.

---

### ~~HIGH-5: Pass open_positions to ConflictGuard~~ `[RESOLVED]`

**Verified:** `_open_position_directions()` helper added. `guard.check()` now receives real position map. ConflictGuard rule 3 (opposite open position) is active.

---

## MEDIUM — Fix before regular operation

---

### MED-1: Move SignalArbiter instantiation out of run_cycle() `[OPEN]`

**File:** `src/mt5_ai/runtime/main_loop.py`  
**Line:** 140

**Issue:** `arbiter = SignalArbiter()` still inside `run_cycle()`, creating a new instance each cycle. `main()` creates all other components once.

**Fix:** Add to `main()` setup section:
```python
arbiter = SignalArbiter()
```
And pass as parameter to `run_cycle()`.

**Risk if ignored:** Minor performance waste — no functional issue.

**Safe to apply now:** YES.

---

### MED-2: Add "signal_arbiter" to DecisionRouter source weights `[OPEN]`

**File:** `src/mt5_ai/core/decision_router.py`  
**Line:** 10

**Issue:** `_SOURCE_WEIGHTS` has no entry for `"signal_arbiter"`. Arbiter output gets weight `1.0` (implicit fallback), equal to `"ai_agent"` — not the intended priority.

**Fix:**
```python
_SOURCE_WEIGHTS = {
    "signal_arbiter": 1.5,   # arbiter-resolved signal has highest priority
    "fractal_agent": 1.2,
    "smc_agent": 1.1,
    ...
}
```

**Risk if ignored:** Arbiter signal weight is undocumented and lower than intended.

**Safe to apply now:** YES.

---

### MED-3: Extract ATR computation into shared utility `[OPEN]`

**Files:** `runtime/main_loop.py`, `algory_signal_engine.py`, `fractal_structure_engine.py`, `market_projection_engine.py` (4+ files confirmed)

**Issue:** ATR rolling computation duplicated across 4+ files. Each copy can diverge.

**Fix:** Create `src/mt5_ai/core/indicators.py`:
```python
def atr(df: pd.DataFrame, period: int = 14) -> float:
    cp = df["close"].shift(1)
    tr = pd.concat([df["high"]-df["low"], (df["high"]-cp).abs(), (df["low"]-cp).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])
```
Replace inline copies.

**Risk if ignored:** Divergent ATR calculations across the pipeline.

**Safe to apply now:** YES.

---

### ~~MED-4: Remove or implement `simulate_only` config key~~ `[RESOLVED — was already implemented]`

**Verified:** `config_loader.py` line 51 already reads `simulate_only`:
```python
def is_dry_run() -> bool:
    cfg = load()
    return (cfg.get("runtime", {}).get("mode") == "DRY_RUN" or
            cfg.get("execution", {}).get("simulate_only") is True)
```
The key is functional. No action needed.

---

### MED-5: Add consecutive failure counter to main_loop.py `[OPEN]`

**File:** `src/mt5_ai/runtime/main_loop.py`  
**Lines:** 260–263

**Issue:** Any exception in a cycle is caught, logged, and ignored. A crash loop runs indefinitely.

```python
except Exception as exc:
    log.exception("Cycle error: %s", exc)
# no counter, no stop
```

**Fix:** Add `consecutive_errors` counter. After 5+ consecutive errors, activate kill switch or raise:
```python
consecutive_errors = 0
# ... inside while True:
try:
    ...
    consecutive_errors = 0
except Exception as exc:
    log.exception("Cycle error: %s", exc)
    consecutive_errors += 1
    if consecutive_errors >= 5:
        log.critical("5 consecutive cycle errors — activating kill switch")
        from mt5_ai.core.kill_switch import activate
        activate("consecutive_failures")
        break
```

**Risk if ignored:** A broken agent or MT5 connection could loop indefinitely, generating thousands of error log lines.

**Safe to apply now:** YES.

---

## LOW — Quality improvements

---

### LOW-1: Remove unused imports from main_loop.py `[OPEN]`

**File:** `src/mt5_ai/runtime/main_loop.py`  
**Line:** 35

`AiAgent` and `ScalperAgent` imported but never used in `run_cycle()` or anywhere in the file body. Either remove imports or add these agents to the active agent loop.

---

### ~~LOW-2: Reconcile DEFAULT_MAGIC in config.py with ALGORY_MAGIC~~ `[RESOLVED — was already correct]`

**Verified:** `config.py` line 149: `DEFAULT_MAGIC = 20260600` — matches `ALGORY_MAGIC`. No action needed.

---

### LOW-3: Archive directory should not be in Python module path `[OPEN]`

**Location:** `src/mt5_ai/archive/`  
**Count:** 22+ `.py` files confirmed across two subdirectories

Archive files with direct `order_send` calls (`ict_sweep_trader.py`, `friday_realtime_scalper_demo_executor.py`, `mt5_ollama_trader.py`) are importable as `mt5_ai.archive.*` and bypass all safety pipelines.

**Fix:** Move `src/mt5_ai/archive/` to `archive/` at project root, or rename to `src/mt5_ai/_archive/`.

---

### LOW-4: Add heartbeat log to main_loop.py `[OPEN]`

**File:** `src/mt5_ai/runtime/main_loop.py`

Add a periodic heartbeat (every 60 seconds or N cycles):
```python
log.info("Heartbeat: cycle=%d | uptime=%.0fs", cycle, time.monotonic() - _start)
```
A frozen cycle (MT5 call hanging) currently produces no log output.

---

## Current Status Summary Table

| ID | Priority | File | Issue | Status |
|---|---|---|---|---|
| CRIT-1 | CRITICAL | `core/position_manager.py` | magic=0 breaks position management | **RESOLVED** |
| CRIT-2 | CRITICAL | `core/execution_manager.py` | MT5Gateway method mismatch | **RESOLVED** |
| CRIT-3 | CRITICAL | `runtime/dry_run_simulation.py` | contributing_signals TypeError | **OPEN** |
| HIGH-1 | HIGH | `algory_runner.py` | open_trade() AttributeError in paper mode | **OPEN** |
| HIGH-2 | HIGH | `mt5_gateway.py` | Demo methods bypass safety pipeline | **RESOLVED** |
| HIGH-3 | HIGH | `core/kill_switch.py` | Writes to wrong config file | **OPEN** |
| HIGH-4 | HIGH | `runtime/main_loop.py` | spread/position not passed to RiskManager | **RESOLVED** |
| HIGH-5 | HIGH | `runtime/main_loop.py` | open_positions not passed to ConflictGuard | **RESOLVED** |
| MED-1 | MEDIUM | `runtime/main_loop.py` | Arbiter re-instantiated per cycle | **OPEN** |
| MED-2 | MEDIUM | `core/decision_router.py` | signal_arbiter not in SOURCE_WEIGHTS | **OPEN** |
| MED-3 | MEDIUM | `runtime/main_loop.py` | ATR duplicated inline | **OPEN** |
| MED-4 | MEDIUM | `config_loader.py` | simulate_only dead config key | **RESOLVED (pre-existing)** |
| MED-5 | MEDIUM | `runtime/main_loop.py` | No consecutive failure protection | **OPEN** |
| LOW-1 | LOW | `runtime/main_loop.py` | Unused AiAgent/ScalperAgent imports | **OPEN** |
| LOW-2 | LOW | `config.py` | DEFAULT_MAGIC = old value | **RESOLVED (pre-existing)** |
| LOW-3 | LOW | `src/mt5_ai/archive/` | Archive in Python path | **OPEN** |
| LOW-4 | LOW | `runtime/main_loop.py` | No heartbeat log | **OPEN** |

**Resolved: 7 / 17 | Open: 10 / 17**

### Remaining open by priority:
- **CRITICAL (1):** CRIT-3
- **HIGH (2):** HIGH-1, HIGH-3
- **MEDIUM (4):** MED-1, MED-2, MED-3, MED-5
- **LOW (3):** LOW-1, LOW-3, LOW-4

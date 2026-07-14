# Report: 02 — Safety Review

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Phase start:** 02:22 UTC  
**Phase end:** 02:35 UTC  
**Elapsed:** ~13 minutes  
**Scope:** All `order_send`, `allow_live_trading`, `simulate_only`, `DRY_RUN`, `kill_switch`, `magic=0`, direct MT5 write operations

---

## OVERALL SAFETY VERDICT

```
CURRENT STATUS: SAFE FOR DRY_RUN USE
UNSAFE FOR LIVE USE: 3 critical structural gaps exist that would cause failures or bypasses
                     if mode were changed to DEMO or LIVE
```

---

## 1. order_send Audit

### Grep results — all files in `src/` (excluding archive)

| File | Lines | Status |
|---|---|---|
| `core/execution_manager.py` | 111, 150 | ✅ SAFE — guarded by DRY_RUN (line 53) before reaching these |
| `mt5_gateway.py` | 361, 364, 438, 441, 533, 536 | ⚠️ UNSAFE PATH — not gated by config_loader |
| Archive files (all) | multiple | ✅ ISOLATED — not imported by active modules |

### `execution_manager.py` guard chain (lines 33–63)

```python
def execute(req):
    if is_kill_switch(): return BLOCKED           # guard 1
    ok, msg = req.is_valid()                      # guard 2
    validate_request(req.magic, ...)              # guard 3
    if is_dry_run(): return SIMULATED             # guard 4 ← current state
    if not is_live_allowed(): return BLOCKED      # guard 5
    gw.send_order(...)                            # order_send (never reached in DRY_RUN)
```

**Verdict:** In current DRY_RUN configuration, `mt5.order_send` is structurally unreachable through the production pipeline.

### `mt5_gateway.py` unguarded paths

`send_demo_market_order()` and `send_demo_pending_order()` call `mt5.order_send()` with only:
- Check 1: `DEMO_TRADING_ENABLED` (constant in `config.py`, always True — **not** the YAML config)
- Check 2: `is_demo_account()` — checks server name contains "demo/trial/practice/contest"

**Missing:**
- No `is_kill_switch()` check from `config_loader.py`
- No `is_dry_run()` check from `config_loader.py`
- No magic number validation against `magic_registry.py`
- Magic used is `DEFAULT_MAGIC = 260426` — NOT in `ALL_FRIDAY_MAGICS`

**Risk:** If any code calls `MT5Gateway().send_demo_market_order(plan)` directly (voice assistant, algory_runner demo path, manual script), it would bypass all safety layers. The connected account is a DEMO account so `is_demo_account()` would return True, enabling execution.

---

## 2. allow_live_trading Audit

### Config files

| File | `allow_live_trading` | `mode` | `kill_switch` |
|---|---|---|---|
| `config/trading_runtime.yaml` | `false` ✅ | `DRY_RUN` ✅ | `true` ✅ |
| `config/dry_run_simulation.yaml` | `false` ✅ | `DRY_RUN` ✅ | `false` |
| `config/live_micro_disabled.yaml` | `false` ✅ | `DRY_RUN` ✅ | `true` ✅ |

**All three configs have `allow_live_trading=false`.** No live path is enabled at config level.

### `is_live_allowed()` implementation (config_loader.py:39)

```python
def is_live_allowed() -> bool:
    return (cfg.get("runtime", {}).get("mode") == "LIVE" and
            cfg.get("runtime", {}).get("allow_live_trading") is True and
            not cfg.get("runtime", {}).get("kill_switch", False))
```

**Verdict:** Three conditions must ALL be True simultaneously. Current state: all False. ✅

---

## 3. simulate_only Audit

**Finding:** `execution.simulate_only: true` appears in `dry_run_simulation.yaml` but is **never read by any code**.

```python
# config_loader.py — no reference to "simulate_only"
def is_dry_run() -> bool:
    return load().get("runtime", {}).get("mode") == "DRY_RUN"
```

The actual simulation gate is `is_dry_run()` which reads `runtime.mode`, not `execution.simulate_only`.

**Impact:** The `simulate_only: true` key is cosmetic. It provides documentation value but zero functional safety value. DRY_RUN mode is enforced by `runtime.mode`, not `simulate_only`.

**Recommendation:** Remove `simulate_only` from configs OR add a reader so it provides an additional gate.

---

## 4. DRY_RUN Mode Audit

### How DRY_RUN works

- `config_loader.is_dry_run()` returns `True` when `runtime.mode == "DRY_RUN"`
- `execution_manager.py:53`: `if is_dry_run(): return ExecutionResult(success=True, simulated=True, ...)`
- This gate fires **before** MT5Gateway is instantiated (lazy init at line 30)

### DRY_RUN enforcement confirmed in

| Method | DRY_RUN check |
|---|---|
| `execute()` | Line 53 — ✅ |
| `cancel_pending_order()` | Line 100 — ✅ |
| `send_raw_order()` | Line 137 — ✅ |

**Verdict:** All three ExecutionManager methods check DRY_RUN before any MT5 call. ✅

---

## 5. kill_switch Audit

### What kill_switch does

- `config_loader.is_kill_switch()` → reads `runtime.kill_switch` from active YAML config
- Checked at start of every `run_cycle()` (main_loop.py:68)
- Checked inside `ExecutionManager.execute()`, `cancel_pending_order()`, `send_raw_order()`
- Checked inside `RiskManager.validate()`

### Kill switch activation mechanism

`kill_switch.py:activate()` writes `kill_switch: True` to **hardcoded path** `config/trading_runtime.yaml`:

```python
_CONFIG = Path(r"C:\Users\Radhi\MT5\config\trading_runtime.yaml")
def activate(reason: str = "manual") -> None:
    data = yaml.safe_load(_CONFIG.read_text(...))
    data["runtime"]["kill_switch"] = True
    _CONFIG.write_text(...)
    load(force=True)   # reloads config_loader's cache
```

**Gap:** If the active config is `dry_run_simulation.yaml` (set via `use_config()`), the kill switch writes to `trading_runtime.yaml` but the running process reads from `dry_run_simulation.yaml`. The kill switch would NOT stop the running process.

**Risk:** In current DRY_RUN state this is safe (no real orders). But if this system transitions to DEMO/LIVE, the kill switch activation mechanism must be fixed to write to the active config file.

---

## 6. magic=0 Audit

### In active (non-archive) code

**`core/position_manager.py`** — CRITICAL:

```python
# FULL_CLOSE
return ExecutionRequest(magic=0, ...)   # line 17

# PARTIAL_CLOSE
return ExecutionRequest(magic=0, ...)   # line 24

# TRAIL / BREAKEVEN
return ExecutionRequest(magic=0, ...)   # line 32
```

**All three position management actions use `magic=0`.** When these reach `ExecutionManager.execute()`:

```python
validate_request(0, req.comment)
# raises ValueError: "ExecutionRequest from '...' uses unregistered magic 0"
# → ExecutionResult(success=False, message="ExecutionRequest ... unregistered magic 0")
```

**Result:** The ENTIRE position management path is silently broken. GovernorAgent and RiskCloseAgent can produce close requests, but they ALL fail at magic validation. No position is ever closed by the governor, including emergency risk-close scenarios.

**This is the single most dangerous structural bug in the project.**

### External magic=0 (Exness Social Trading)

Exness Social Trading server-side subscription (account 260749517) produces magic=0 trades. These are server-generated and outside Python control. Manual cancellation required via Exness PA. Status: still unresolved as of Report 34.

---

## 7. Direct MT5 Write Operations Audit

### Non-order_send MT5 write calls in active code

| Function | File | Type | Guarded? |
|---|---|---|---|
| `mt5.symbol_select(symbol, True)` | `mt5_gateway.py:123` | Metadata only | ✅ harmless |
| `mt5.order_send(request)` | `mt5_gateway.py:361,364` | TRADE | ⚠️ partial guard only |
| `mt5.order_send(request)` | `mt5_gateway.py:438,441` | TRADE | ⚠️ partial guard only |
| `mt5.order_send(request)` | `mt5_gateway.py:533,536` | TRADE | ⚠️ partial guard only |

### `send_market_order()` in MT5Gateway

**BLOCKED by design** — always returns `sent=False, reason="live_trading_permanently_disabled"`. This is safe.

### friday_voice/mt5_tools.py

Read-only. Uses `mt5.positions_get()`, `mt5.orders_get()`, `mt5.copy_rates_from_pos()`, `mt5.symbol_info()`, `mt5.account_info()`. No write operations. ✅ SAFE.

---

## 8. Safety Summary Table

| Check | Status | Notes |
|---|---|---|
| `order_send` in production pipeline | ✅ SAFE | Blocked by DRY_RUN at execution_manager:53 |
| `allow_live_trading=false` | ✅ SAFE | All 3 configs |
| `simulate_only` flag | ⚠️ COSMETIC | Not read by any code — dead config key |
| `DRY_RUN` enforcement | ✅ SAFE | All 3 ExecutionManager methods check |
| `kill_switch` in pipeline | ✅ SAFE | But activate() has wrong target file path |
| `magic=0` in position_manager | ❌ BROKEN | All position management silently fails |
| `MT5Gateway` demo methods bypass | ⚠️ RISK | Not gated by config_loader safety chain |
| Archive files | ✅ ISOLATED | Not imported by active modules |
| `send_market_order()` | ✅ SAFE | Permanently blocked by design |
| Voice assistant MT5Tools | ✅ SAFE | Read-only, no order_send |

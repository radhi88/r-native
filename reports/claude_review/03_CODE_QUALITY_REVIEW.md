# Report: 03 — Code Quality Review

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Phase start:** 02:35 UTC  
**Phase end:** 02:50 UTC  
**Elapsed:** ~15 minutes  
**Scope:** Active pipeline files — `core/`, `agents/`, `runtime/`, `config.py`, `mt5_gateway.py`

---

## 1. Duplicate Logic

### ATR computation — duplicated in `main_loop.py`

`main_loop.py` lines 132–147 compute a 14-bar ATR inline using raw pandas:

```python
close_prev = df["close"].shift(1)
tr  = pd.concat([df["high"] - df["low"],
                 (df["high"] - close_prev).abs(),
                 (df["low"]  - close_prev).abs()], axis=1).max(axis=1)
atr = float(tr.rolling(14).mean().iloc[-1])
```

The same rolling ATR computation appears in:
- `market_structure.py` (SMC engine)
- `config.py` `RISK_SL_ATR_MULT` references
- `trailing_sl.py`
- Multiple agent files

This is a clear utility candidate. An `atr(df, period=14)` function should live in one place and be imported everywhere.

### Signal schema duplication — two `ExecutionResult` classes

- `core/signal_schema.py` defines `ExecutionResult` (dataclass, fields: success, retcode, order, deal, message, raw, simulated)
- `execution.py` defines its own `ExecutionResult` (dataclass, fields: mode, action, symbol, side, lot, price, sent, reason, timestamp)

These are completely different types with the same name. `algory_runner.py` uses `execution.PaperExecutor` which returns `execution.ExecutionResult`. The pipeline uses `signal_schema.ExecutionResult`. Any code that mixes the two would silently produce wrong results.

### Confidence computation duplication

`ConflictGuard` and `RiskManager` both check `confidence.min_decision_confidence` independently:
- `conflict_guard.py:34`: `get("confidence.min_decision_confidence") or 0.45`
- `risk_manager.py:44`: `get("confidence.min_decision_confidence") or 0.45`

Same config key, same default, same logic. This check fires twice on every passing signal.

---

## 2. Broken Imports

### `dry_run_simulation.py:97`

```python
decision = DecisionResult(
    action=Direction.BUY, symbol=SYMBOL, timeframe=TIMEFRAME,
    confidence=0.78, reason="forced_for_simulation",
    contributing_signals=[signal],   # ← WRONG FIELD NAME
)
```

`DecisionResult` has `raw_signals: list[SignalProposal]`, not `contributing_signals`. This would raise `TypeError: __init__() got an unexpected keyword argument 'contributing_signals'` if the forced-BUY fallback path fires.

This path fires when `router.route()` returns HOLD (line 93). That is the expected outcome for synthetic signals below threshold. The line `log.warning("Router returned HOLD — forcing BUY for simulation completeness")` is triggered, then the broken constructor is called.

**Status:** This is a latent crash that fires every time `dry_run_simulation.py` is run as a standalone test.

### `algory_runner.py:438`

In paper mode, `AlgoryRunner._execute()` calls:
```python
self.executor.open_trade(
    symbol=sym, direction=1 if action == "BUY" else -1,
    lot=trade["lot"], sl=trade["sl"], tp=trade["tp"],
)
```

But `PaperExecutor` (from `execution.py`) has no `open_trade()` method. Methods are `execute()` and `execute_pending()`. This raises `AttributeError: 'PaperExecutor' object has no attribute 'open_trade'`, caught silently by `except Exception` at line 519.

**Impact:** Paper mode in `AlgoryRunner` logs "Execution error" and continues. Paper trades are never recorded. The paper mode of AlgoryRunner is functionally broken.

### Missing `AiAgent` and `ScalperAgent` in `run_cycle()`

`main_loop.py:34–36` imports `AiAgent` and `ScalperAgent` from `agents/__init__.py`. These are never used in `run_cycle()`. If either import fails (e.g., missing dependency), the entire module fails to load.

---

## 3. Unused Files

### Active agents never called in production

| File | Agent Class | Status |
|---|---|---|
| `agents/ai_agent.py` | `AiAgent` | Imported in `__init__.py`, imported in `main_loop.py`, but NEVER CALLED in `run_cycle()` |
| `agents/scalper_agent.py` | `ScalperAgent` | Same — imported, never called |
| `agents/touch_agent.py` | `TouchAgent` | Exported from `__init__.py`, not used |
| `agents/swing_agent.py` | (various) | Old agent — not in `__init__.py` |
| `agents/pending_agent.py` | (various) | Old agent — not in `__init__.py` |

### Old execution architecture files (active location, not archive)

These are in `src/mt5_ai/` (active, importable):
- `execution.py` — `PaperExecutor`, `SafeMT5Executor`, `DemoMT5Executor`, `ExecutionResult` (old schema)
- `signals.py`, `pipeline.py`, `ensemble.py`, `auto_paper_trader.py` — unclear if still used by any active module
- `risk.py` (in `src/mt5_ai/`) — different from `core/risk_manager.py`; unclear purpose

These create import confusion. Code in `algory_runner.py` uses old `execution.py` paths.

### Archive files accessible from `src/`

The `archive/` directory is inside `src/mt5_ai/archive/`. It is not excluded from Python's module search path. Any file in it can be imported accidentally. This is a significant risk for files that contain unguarded `order_send`.

---

## 4. Weak Exception Handling

### `run_cycle()` in `main_loop.py`

The outer try/except at line 215:
```python
except Exception as exc:
    log.exception("Cycle error: %s", exc)
```

This catches AND CONTINUES on ANY exception including:
- MT5 connection failures
- Agent crashes
- Arbiter exceptions
- Execution failures

No back-off strategy, no consecutive failure counting, no automatic kill switch. A repeated crash loop runs at `interval` seconds indefinitely.

### `governor_agent.py`

```python
except Exception as exc:
    log_error(self.source, str(exc), ...)
```

Swallows all errors per position silently. If `_decide()` crashes, the position gets no action.

### `smc_agent.py`, `fractal_agent.py`, `ict_sweep_agent.py`

All have bare `except Exception` → `log_error()` → `return None`. This is correct for agents (no signal is better than a wrong signal) but means a broken dependency (e.g., `market_structure.py` crash) is invisible unless logs are checked.

### `algory_runner.py:519`

```python
except Exception as e:
    log.exception("Execution error: %s", e)
```

This silently catches the `AttributeError` from the broken `open_trade()` call. The paper mode failure is never surfaced.

---

## 5. Missing Logs

### Position management path has no end-to-end log

When `PositionManager.handle()` creates an `ExecutionRequest(magic=0, ...)` and `ExecutionManager` rejects it with `ValueError`, the rejection is logged via `log_error("execution_manager", ...)`. But the caller (`run_cycle()`) does not check the `ExecutionResult.success` from `exec_mgr.execute(exec_req)` — the result is discarded:

```python
exec_req = pos_mgr.handle(req)
if exec_req:
    exec_mgr.execute(exec_req)   # result is DISCARDED — never checked
```

There is no log of whether position management succeeded or failed.

### `signal_arbiter.py` — no error log on log write failure

```python
def _log_decision(decision):
    try:
        with _LOG_PATH.open("a") as f: ...
    except Exception as exc:
        log.warning("arbitration log write failed: %s", exc)
```

Failure to write the decision log is only a warning. This could silently lose audit trail records.

### Missing heartbeat log in `main_loop.py`

There's no periodic heartbeat log to confirm the loop is alive between cycles. For production monitoring, this is a gap.

---

## 6. Unsafe Defaults

### `config.py:135` — DEMO_TRADING_ENABLED = True

```python
DEMO_TRADING_ENABLED = True
```

This is a module-level constant that enables `MT5Gateway`'s demo methods. It is `True` by default with no YAML override mechanism. The mt5_gateway.py demo methods check this flag, not the YAML config.

### `config.py:150` — DEFAULT_MAGIC = 260426

The old gateway uses `DEFAULT_MAGIC = 260426` for all demo/pending orders. This magic number is NOT in `ALL_FRIDAY_MAGICS` (which contains 20260600–20260606 and legacy 20260504–20260507). If these orders were ever placed via `send_demo_market_order()`, the resulting positions would have `magic=260426`, which FRIDAY's own filter logic would not recognize as belonging to the system.

### `conflict_guard.py:34` — default confidence 0.45

```python
min_conf = get("confidence.min_decision_confidence") or 0.45
```

The `or 0.45` means that if the config key is missing (key not found returns `None`), the default 0.45 is used silently. This is correct behavior but should be documented.

### RiskManager passes `open_positions=0` always

`run_cycle()` in `main_loop.py` calls `risk_mgr.validate(decision, symbol)` with no `spread_points`, `open_positions`, or `daily_loss_pct` arguments, so they default to 0. The position-count gate (`max_open_positions`) and spread gate would never fire in production. This means the system could theoretically open unlimited positions.

---

## 7. Unclear Config Usage

### Two config systems in parallel

The project has two separate config systems:
1. **YAML pipeline config** (`config/trading_runtime.yaml` / `dry_run_simulation.yaml`) — read by `config_loader.py`. Controls kill_switch, DRY_RUN, allow_live_trading, lot sizes, spreads.
2. **Module constants** (`config.py`) — Python constants. Controls DEMO_TRADING_ENABLED, DEFAULT_MAGIC, DEFAULT_LOT, MAX_LOT, MT5_TERMINAL_PATH, etc.

These two systems are NOT connected. The YAML config cannot override `DEMO_TRADING_ENABLED` or `DEFAULT_MAGIC`. Code that reads from `config.py` constants is unaffected by YAML config changes.

### `execution.simulate_only` key

`dry_run_simulation.yaml` has `execution.simulate_only: true`. No code reads this key. Its presence is misleading — it implies a meaningful safety gate exists when it doesn't.

### `logging.log_dir` key

`trading_runtime.yaml:57` specifies `log_dir: "C:/Users/Radhi/AppData/Local/FRIDAY/logs"`. But `structured_logger.py` uses `_PROJECT_LOG_DIR = Path(r"C:\Users\Radhi\MT5\logs")` as primary and writes to AppData as secondary. The config `log_dir` key is not read.

### `execution.one_execution_path_only: true`

Present in both configs but never enforced programmatically.

### `execution.require_risk_approval: true`

Present in both configs. `main_loop.py` does call `risk_mgr.validate()` unconditionally, so this is satisfied, but it's not gate-checked — the value isn't read.

---

## 8. Test Coverage Gaps

### Position management path is untested

No report tests GovernorAgent → PositionManager → ExecutionManager. The path is broken (magic=0) and has never been tested end-to-end.

### Live execution path is untested AND broken

`ExecutionManager.execute()` line 68 calls `gw.send_order(...)` but `MT5Gateway` has no `send_order()` method. `close_position()` and `modify_position()` also don't exist. If DRY_RUN is ever disabled, the first trade attempt would raise `AttributeError`.

### `agents_conflicted` scenario with material lead never tested

Reports 36–38 only verify:
- `structure_without_entry_confirmation` (fractal directional + SMC NO_CONFIRMATION) → HOLD
- `agents_aligned` → BUY or SELL

The `agents_conflicted` scenario (both directional but opposing, delta ≥ 0.12 AND score ≥ 0.70) has never been demonstrated to produce a passing BUY/SELL. It only exists in code.

### Synthetic tests vs real data

Report 34 used `test_100_cycles.py` with synthetic signals. No integration test uses real MT5 bars and exercises the full agent stack end-to-end in a repeatable way.

### No test for kill_switch interrupting a cycle

No test demonstrates that kill_switch=True stops mid-cycle execution.

### No test for ATR edge cases

`main_loop.py:139` computes `atr = float(tr.rolling(14).mean().iloc[-1])`. If `df` has fewer than 14 bars, `atr` is `NaN`. `max(NaN * 1.5, 0.0001) = NaN`. `sl = last_close - NaN = NaN`. `ExecutionRequest(sl=NaN)` would pass `is_valid()` (since NaN > 0 is False — wait actually NaN > 0 is False in Python, so it would be BLOCKED by `is_valid()`). This needs verification.

---

## Summary

| Category | Finding Count | Critical |
|---|---|---|
| Duplicate logic | 3 | 0 |
| Broken imports | 3 | 2 |
| Unused files | 5+ | 0 |
| Weak exception handling | 4 | 1 |
| Missing logs | 3 | 1 |
| Unsafe defaults | 4 | 1 |
| Unclear config usage | 5 | 0 |
| Test coverage gaps | 6 | 2 |

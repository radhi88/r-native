# Qader REAL_CONTROLLED_MODE Test Results

Date: 2026-05-14

## Summary

Controlled real mode was implemented and validated without placing any real order. No test clicked the GUI final real-run confirmation. No runtime test called `mt5.order_send`.

Final status: `REAL_CONTROLLED_MODE_IMPLEMENTED_LOCKED_BY_DEFAULT`.

## Commands Run

| Command | Result |
|---|---|
| `.\.venv\Scripts\python.exe -m compileall src\qader_app src\mt5_ai\core src\mt5_ai\runtime verify_mt5_lockdown.py` | pass |
| `rg -n "self\.mt5\.order_send|mt5\.order_send\(" src/mt5_ai src/qader_app -g "*.py" -g "!**/archive/**"` | one active call site in `ExecutionManager` |
| `.\.venv\Scripts\python.exe verify_mt5_lockdown.py` | pass, exit code 0 |
| `.\.venv\Scripts\python.exe -c "... RealModeService().run_lockdown_check() ..."` | pass, clean account |
| `.\.venv\Scripts\python.exe -c "... RealModeService().validation_mode_without_order() ..."` | pass, no order, blocked until GUI unlock |
| `.\.venv\Scripts\python.exe -m unittest tests.test_qader_app` | 13 tests OK |
| `.\.venv\Scripts\python.exe -m unittest tests.test_qader_app tests.test_pivot_engine tests.test_smart_algo` | 27 tests OK |
| `.\.venv\Scripts\python.exe tests/test_genome_quality_gate.py` | 11/11 checks passed |
| `.\.venv\Scripts\python.exe -c "import ..."` | import OK |

Skipped:

| Test | Reason |
|---|---|
| `tests/test_client.py` | ZMQ client test, requires external running server |
| `tests/test_send_real.py` | ZMQ client test name suggests real-send context; not needed for safe real-mode validation |

## Lockdown Output

`verify_mt5_lockdown.py` returned:

| Check | Result |
|---|---|
| Account readable | yes |
| Open positions | 0 |
| Pending orders | 0 |
| magic=0 external exposure | none |
| Exit code | 0 |

Observed account:

| Field | Value |
|---|---|
| Login | 260749517 |
| Server | Exness-MT5Trial15 |
| Currency | USD |
| Balance | 160.81 |
| Equity | 160.81 |
| Margin | 0.00 |
| Verify note | DEMO/TRIAL |

## Static Safety Scan

Active `order_send` result:

```text
src/mt5_ai/core/execution_manager.py:244: result = mt5.order_send(request)
```

Archived legacy `order_send` references remain under `src/mt5_ai/archive/` and were not used.

## Validation-Only Gate Result

Validation mode used `RealModeService.validation_mode_without_order()`.

| Field | Value |
|---|---|
| Allowed | false |
| Reason | expected lock: GUI unlock not performed |
| Orders sent this run | 0 |
| Real `order_send` calls | 0 |

Expected failed gates:

- `permission_can_place_live_orders=False`
- `real_mode_unlocked=False`
- `unlock_phrase_confirmed=False`
- no stored GUI unlock lockdown result
- no stored GUI unlock timestamp

Passing gates included runtime config, live flags, non-dry-run flags, no averaging/martingale/grid/pyramiding/re-entry, one-order-per-run, ExecutionRequest validity, SignalArbiter proof, ConflictGuard proof, RiskManager proof, confidence threshold, SL/TP, lot fixed/max, Qader magic, Qader comment, account clean, pending orders clean, no magic=0 exposure, and spread within limit.

## Real Order Count

| Metric | Count |
|---|---:|
| Real order_send calls during implementation/testing | 0 |
| Real order_send call sites in active code | 1 |
| Real orders placed | 0 |

## Warnings

| Warning | Impact |
|---|---|
| PyQt6 font warning during offscreen GUI smoke test | Non-blocking test environment warning |
| Connected server is `Exness-MT5Trial15` | Verify script labels it DEMO/TRIAL; do not assume this is the real account without checking the MT5 terminal |
| Archived legacy files contain old `order_send` references | Not active; left untouched |

## Final Status

Live trading is still locked unless the user manually unlocks `REAL_CONTROLLED_MODE` in the Qader permissions screen and then confirms the final real-run dialog. `order_send` can now execute only through `ExecutionManager` after all gates pass.

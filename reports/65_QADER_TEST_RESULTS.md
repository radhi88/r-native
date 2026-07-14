# Report 65 - Qader Test Results

Generated: 2026-05-14

## Commands Run

| Command | Result |
|---|---|
| `python -m py_compile src/qader_app/**/*.py tests/test_qader_app.py` | PASS |
| `python -c "import qader_app..."` | PASS |
| `python -m qader_app.main --no-gui` | PASS |
| `python tests/test_qader_app.py` | PASS, 10 tests |
| `python verify_mt5_lockdown.py` | PASS, exit code 0 |
| static `order_send` scan | PASS for Qader; no Qader live order path |
| static live config scan | PASS, no `allow_live_trading: true`, no active `mode: LIVE` |
| `python -c runpy.run_module('mt5_ai.runtime.dry_run_simulation')` | PASS |
| `python test_100_cycles.py` | PASS |
| `packaging/qader.spec` syntax compile | PASS |
| Qader read-only scanner smoke (`XAUUSDm`, `M1`, temp QADER_ROOT under `_archive`) | PASS |

## Lockdown Result

- Account info readable: yes
- Open positions: 0
- Pending orders: 0
- Exit code: 0

## Qader Unit Tests

`tests/test_qader_app.py`

Coverage:
- app bootstrap
- onboarding/profile/settings/permissions storage
- live permission lock
- permissions guard audit logging
- local memory sensitive-key stripping
- genome mutation approval and permission checks
- scanner denial when permissions are missing
- assistant intent routing
- packaging file presence
- PyQt6 GUI import/smoke test

Result: `Ran 10 tests ... OK`

Qt warning observed:

```text
QFontDatabase: Cannot find font directory ... PyQt6/Qt6/lib/fonts.
```

This did not fail the GUI smoke test. For a polished EXE, bundle a font or configure font fallback.

## Dry-Run Results

`dry_run_simulation.py`:
- status: `SIMULATION_COMPLETE`
- arbiter: BUY
- decision: BUY
- execution: simulated
- real order sent: false
- MT5Gateway called: false

`test_100_cycles.py`:
- total cycles: 100
- errors: 0
- simulated executions: 45
- real orders sent: 0

## Market Scanner Smoke

Read-only Qader scanner test:

```json
{
  "symbol": "XAUUSDm",
  "timeframe": "M1",
  "fractal_result": "SELL",
  "smc_result": "NO_CONFIRMATION",
  "arbiter_result": "HOLD",
  "risk_status": "not_reached",
  "final_action": "HOLD",
  "real_order_send_calls": 0
}
```

## Real order_send Calls

Observed real `order_send` calls from Qader validation: `0`.

Static scan showed only the existing guarded core/gateway sites plus Qader's explicit dry-run monkey-patch blocker in `RunnerService`.

## Final Safety Status

`SAFE_FOR_DRY_RUN_ONLY`

Live trading remains disabled and locked.

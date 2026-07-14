# Report 28 — Legacy Executor Isolation Gate

Generated: 2026-05-13T03:28:12.973840

## Action

Legacy executors were archived and replaced with safe disabled stubs.

## Archive Folder

`C:\Users\Radhi\MT5\src\mt5_ai\archive\legacy_executors_disabled_20260513_032812`

## Files

- DISABLED: `scripts\ict_sweep_trader.py` -> archived to `C:\Users\Radhi\MT5\src\mt5_ai\archive\legacy_executors_disabled_20260513_032812\scripts\ict_sweep_trader.py`
- DISABLED: `scripts\mt5_ollama_trader.py` -> archived to `C:\Users\Radhi\MT5\src\mt5_ai\archive\legacy_executors_disabled_20260513_032812\scripts\mt5_ollama_trader.py`
- DISABLED: `friday_demo_position_governor.py` -> archived to `C:\Users\Radhi\MT5\src\mt5_ai\archive\legacy_executors_disabled_20260513_032812\friday_demo_position_governor.py`
- DISABLED: `friday_demo_position_governor_v2.py` -> archived to `C:\Users\Radhi\MT5\src\mt5_ai\archive\legacy_executors_disabled_20260513_032812\friday_demo_position_governor_v2.py`
- DISABLED: `friday_realtime_scalper_demo_executor.py` -> archived to `C:\Users\Radhi\MT5\src\mt5_ai\archive\legacy_executors_disabled_20260513_032812\friday_realtime_scalper_demo_executor.py`
- DISABLED: `friday_touch_demo_executor.py` -> archived to `C:\Users\Radhi\MT5\src\mt5_ai\archive\legacy_executors_disabled_20260513_032812\friday_touch_demo_executor.py`
- DISABLED: `friday_risk_close.py` -> archived to `C:\Users\Radhi\MT5\src\mt5_ai\archive\legacy_executors_disabled_20260513_032812\friday_risk_close.py`
- DISABLED: `ict_sweep_trader.py` -> archived to `C:\Users\Radhi\MT5\src\mt5_ai\archive\legacy_executors_disabled_20260513_032812\ict_sweep_trader.py`

## Safety Result

Original legacy execution code is preserved in archive only.

Active legacy script files now contain only:
- `LEGACY_EXECUTOR_DISABLED = True`
- disabled `main()`
- direct-execution guard
- no MT5 order execution logic

## Required Verification

Run:
- compileall
- execution scan excluding archive folders
- direct guard scan

Final status will be confirmed after verification.

LEGACY_EXECUTOR_STATUS = PATCH_APPLIED_PENDING_VERIFY

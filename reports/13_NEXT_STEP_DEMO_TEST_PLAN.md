# Report 13 — Next Step: Demo Test Plan

**Date:** 2026-05-13  
**Prerequisites:** Report 12 `FINAL_STATUS = PASS_SAFE_DRY_RUN_READY`  
**Account type required:** MT5 DEMO account only  
**Live mode:** NEVER during this plan  

---

## Overview

This plan describes how to run FRIDAY in demo mode safely. The goal is to validate that the full pipeline (agents → decision → risk → execution) functions correctly on a demo account before any consideration of live trading.

**This plan does NOT enable live trading. At no point should you:**
- Set `allow_live_trading: true`
- Attach the MQ5 EA to a symbol being tested
- Connect a real/live MT5 account
- Increase lot size beyond 0.01
- Disable the kill_switch without a specific reason and re-enable it immediately after

---

## Step 1: Pre-Flight Config

Edit `config/trading_runtime.yaml`:

```yaml
runtime:
  mode: DRY_RUN        # ← keep DRY_RUN for first 100 cycles
  allow_live_trading: false
  kill_switch: true    # ← keep true until step 3
  log_level: INFO
```

**Do not change to DEMO or LIVE yet.**  
Run Step 2 (100-cycle DRY_RUN test) first.

---

## Step 2: 100-Cycle Dry-Run Validation

### Required config

```yaml
runtime:
  mode: DRY_RUN
  allow_live_trading: false
  kill_switch: false    # ← set false for this step only
```

### How to run

```powershell
cd C:\Users\Radhi\MT5
python -m mt5_ai.runtime.dry_run_runner
```

Or loop 100 times (watch for errors):

```powershell
for ($i = 1; $i -le 100; $i++) {
    python -m mt5_ai.runtime.dry_run_runner
    Start-Sleep -Seconds 5
}
```

### Pass criteria

- Zero Python exceptions or tracebacks
- All results are one of: `HOLD`, `no_signals`, `BLOCKED`, `RISK_BLOCKED`, `BUY` (simulated=True), `SELL` (simulated=True)
- `simulated=True` on all non-HOLD results (confirms DRY_RUN is active)
- No `allow_live_trading` warnings in logs

### After step 2

Reset config:
```yaml
kill_switch: true    # ← reset to safe default after 100 cycles
```

---

## Step 3: Demo Account Validation

### Required config

```yaml
runtime:
  mode: DRY_RUN         # ← KEEP DRY_RUN (demo data source, no real orders)
  allow_live_trading: false
  kill_switch: false
```

**Note:** `mode: DRY_RUN` still fetches real MT5 bar data and runs the full pipeline. It does not place orders. This is the correct mode for validating the pipeline.

To eventually place demo orders, you would change to `mode: DEMO` — but only after this full plan is complete and signed off.

### MT5 account requirements

- Account type: **DEMO only**  
- Broker: same demo broker currently connected (equity 160.81)  
- No real account numbers  
- No EA attached to test symbols (EURUSDm, XAUUSDm)

### EA isolation check

Before running: in MetaTrader5, verify `FRIDAY_Gold_EA.mq5` is **detached** from EURUSDm and XAUUSDm charts. The EA uses magic 20250501. If it is attached, positions with that magic will appear in MT5 but will NOT be managed by Python. This creates confusing state in the position governor.

```
MT5 Navigator → Expert Advisors → confirm no EA running on test symbols
```

---

## Step 4: Logs to Monitor

### JSONL log files

Location: `C:/Users/Radhi/AppData/Local/FRIDAY/logs/`

| File | What to watch |
|------|--------------|
| `signals.jsonl` | Agent signal counts, confidence values |
| `decisions.jsonl` | DecisionRouter output, reason strings |
| `execution.jsonl` | All ExecutionManager calls — confirm `simulated=true` always |
| `positions.jsonl` | PositionManager requests (should be empty in DRY_RUN) |
| `errors.jsonl` | Any pipeline errors — must be empty |
| `kills.jsonl` | Kill switch activations |

### Key checks in execution.jsonl

Every entry must have:
```json
{"simulated": true, "success": true}
```

If you ever see `"simulated": false` — STOP. Set `kill_switch: true` immediately. Investigate before continuing.

### algory_runner log

Location: `C:/Users/Radhi/AppData/Local/FRIDAY/algory_runner.log`

Watch for:
- `[DRY_RUN] RAW_ORDER` messages — confirm orders are simulated
- `[LIVE]` prefix — should NEVER appear in DRY_RUN mode

---

## Step 5: Stop Conditions

Stop the test immediately and set `kill_switch: true` if:

| Condition | Action |
|-----------|--------|
| Any `"simulated": false` in execution.jsonl | Kill switch → investigate |
| Any `[LIVE]` prefix in algory_runner.log | Kill switch → investigate |
| Any `allow_live_trading` warning | Kill switch → check config |
| Any unhandled exception in the pipeline | Kill switch → fix before continuing |
| MT5 equity drops by more than $5 | Kill switch → check for unexpected positions |
| Any position opened with magic 20260600 | Unexpected in DRY_RUN — kill switch → investigate |
| Spread > 80 points on gold, > 30 on forex | Not a stop condition, but log and skip |

### Emergency kill

To stop all execution immediately:

```yaml
# config/trading_runtime.yaml
runtime:
  kill_switch: true
```

Or via Python:
```python
from mt5_ai.core.kill_switch import activate
activate(reason="manual_stop")
```

---

## Step 6: Risk Parameters (Hard Limits)

These limits must NOT be changed during the demo test:

| Parameter | Value | Location |
|-----------|-------|----------|
| max_lot | 0.01 | trading_runtime.yaml |
| max_open_positions | 1 | trading_runtime.yaml |
| allow_live_trading | false | trading_runtime.yaml |
| kill_switch | true (default) | trading_runtime.yaml |
| EA on test symbols | detached | MT5 Navigator |
| Real account | never | MT5 login |

---

## Step 7: Demo Trade Execution Test (Future)

This step is NOT part of the current plan. It is listed as a future gate only.

When Step 2 and Step 3 have passed:
1. Change `mode: DRY_RUN` → `mode: DEMO`
2. Run a single cycle
3. Verify in MT5: one position opened with magic 20260600, lot 0.01
4. Verify in execution.jsonl: `"simulated": false, "success": true`
5. Verify no second position opens (max_open_positions: 1)
6. Verify kill_switch works: activate, confirm no new orders
7. Close position manually in MT5
8. Deactivate kill_switch, reset to `mode: DRY_RUN`

---

## Checklist Before Any Demo Execution

- [ ] 100-cycle DRY_RUN completed with zero errors
- [ ] execution.jsonl shows only `simulated: true` entries
- [ ] errors.jsonl is empty
- [ ] FRIDAY_Gold_EA.mq5 detached from test symbols
- [ ] MT5 account confirmed as DEMO
- [ ] kill_switch confirmed functional (tested in Step 2)
- [ ] max_lot = 0.01 in config
- [ ] max_open_positions = 1 in config
- [ ] allow_live_trading: false in config
- [ ] No live account connected to MT5
- [ ] Second person reviewed config (recommended)

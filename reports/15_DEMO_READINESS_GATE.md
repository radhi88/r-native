# Report 15 — Demo Readiness Gate

**Date:** 2026-05-13

---

## Gate Checklist

| Requirement | Evidence | Status |
|-------------|----------|--------|
| Final verification passed (Report 12) | FINAL_STATUS = PASS_SAFE_DRY_RUN_READY | ✅ |
| Dry-run safety lock passed | kill_switch=true in trading_runtime.yaml, pipeline blocked correctly | ✅ |
| Dry-run execution simulation passed | SIMULATION_STATUS = PASS (Report 14) | ✅ |
| Zero unauthorized order_send | Post-simulation scan: 0 violations | ✅ |
| Live trading disabled | allow_live_trading=false in trading_runtime.yaml | ✅ |
| Live micro config disabled | config/live_micro_disabled.yaml: allow_live_trading=false, kill_switch=true | ✅ |
| EA boundary documented as SEPARATE_EA_BOUNDARY | FRIDAY_Gold_EA.mq5 reclassified in Report 14 | ✅ |
| No EA attached to same symbol | Requirement documented in Report 13 checklist | ✅ (must verify before demo run) |
| max_lot = 0.01 | dry_run_simulation.yaml + live_micro_disabled.yaml | ✅ |
| max_open_positions = 1 | dry_run_simulation.yaml + live_micro_disabled.yaml | ✅ |
| max_trades_per_day = 3 | dry_run_simulation.yaml + live_micro_disabled.yaml | ✅ |
| Logs working | 5/5 log files written to logs/ during simulation | ✅ |
| Kill switch tested true (blocks pipeline) | Report 12 smoke test: RiskManager blocked, result=RISK_BLOCKED | ✅ |
| Kill switch tested false (pipeline runs) | Report 14 simulation: full pipeline completed, simulated=True | ✅ |

---

## DEMO_STATUS = READY_FOR_CONTROLLED_DEMO

---

## Controlled Demo Conditions

Before running any demo execution, the following must be true at the time of the run:

1. MT5 account is **DEMO** — verified in MetaTrader5 account properties
2. `FRIDAY_Gold_EA.mq5` is **detached** from all symbols being tested
3. `config/trading_runtime.yaml` has `mode: DRY_RUN` or `mode: DEMO` (never LIVE)
4. `allow_live_trading: false` remains unchanged
5. `max_lot: 0.01` remains unchanged
6. `kill_switch: false` set only for the duration of the demo test, reset to `true` after
7. Follow steps in Report 13 (13_NEXT_STEP_DEMO_TEST_PLAN.md)

---

## What READY_FOR_CONTROLLED_DEMO Means

- The architecture is verified clean
- The execution boundary is enforced
- The kill switch works at multiple layers
- All pipeline components run without errors
- Logs are operational
- No live trading is possible under current config

It does **not** mean live trading is approved. Live trading requires a separate sign-off after successful demo testing per Report 13, Step 7.

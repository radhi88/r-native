# Qader REAL_CONTROLLED_MODE Design

Date: 2026-05-14

## Executive Summary

Qader now has a controlled real execution mode named `REAL_CONTROLLED_MODE`. It is not the default mode and it is not enabled automatically. The default runtime config remains `DRY_RUN` with `allow_live_trading: false` and `kill_switch: true`.

The new mode can reach `mt5.order_send` only through `src/mt5_ai/core/execution_manager.py`, after Qader permissions, typed GUI confirmation, `verify_mt5_lockdown.py`, SignalArbiter, ConflictGuard, RiskManager, lot, SL/TP, spread, account-cleanliness, and one-order-per-run gates pass.

Connected account observed during verification:

| Field | Value |
|---|---|
| Login | 260749517 |
| Server | Exness-MT5Trial15 |
| Balance | 160.81 USD |
| Equity | 160.81 USD |
| Open positions | 0 |
| Pending orders | 0 |
| Trade mode note | verify script labels this server as DEMO/TRIAL |

## Files Added

| File | Purpose |
|---|---|
| `config/real_controlled_mode.yaml` | Non-default live-controlled config with hard limits |
| `src/qader_app/services/real_mode_service.py` | Lockdown, typed unlock, validation-only, and bounded real-run orchestration |
| `src/qader_app/gui/real_controlled.py` | REAL CONTROLLED MODE GUI screen |
| `reports/70_REAL_CONTROLLED_MODE_DESIGN.md` | Design report |
| `reports/71_REAL_CONTROLLED_MODE_SAFETY_GATES.md` | Safety gate report |
| `reports/72_REAL_CONTROLLED_MODE_TEST_RESULTS.md` | Test result report |

## Files Modified

| File | Change |
|---|---|
| `src/mt5_ai/core/execution_manager.py` | Added the only active real `mt5.order_send` path and full gate report |
| `src/mt5_ai/core/config_loader.py` | Added `REAL_CONTROLLED_MODE` helpers |
| `src/mt5_ai/core/magic_registry.py` | Registered `QADER_REAL_CONTROLLED` magic `20260514` |
| `src/mt5_ai/core/signal_schema.py` | Added real-mode pipeline proof fields |
| `src/mt5_ai/runtime/main_loop.py` | Passes config magic/comment plus SignalArbiter and ConflictGuard proof into `ExecutionRequest` |
| `src/mt5_ai/mt5_gateway.py` | Removed active gateway direct write calls; gateway write helpers now return blocked |
| `src/qader_app/storage/settings_store.py` | Added typed phrase unlock state and hard default live lock |
| `src/qader_app/assistant/permissions_guard.py` | Allows live permission only after real-mode unlock metadata is valid |
| `src/qader_app/assistant/qader_brain.py` | Voice/text live requests now require manual permissions-screen confirmation |
| `src/qader_app/gui/permissions.py` | Added typed real-mode unlock and lock controls |
| `src/qader_app/gui/main_window.py` | Added REAL CONTROLLED MODE tab |
| `src/qader_app/gui/dashboard.py` | Added red live safety indicator behavior |
| `packaging/qader.spec` | Bundles real-mode config and lockdown script |
| `packaging/README_BUILD.md` | Documents locked real-mode packaging behavior |
| `verify_mt5_lockdown.py` | Labels Qader real-mode magic `20260514` |
| `tests/test_qader_app.py` | Added safe tests for real-mode config, unlock phrase, and voice denial |

## Config

Created `config/real_controlled_mode.yaml`.

Key limits:

| Setting | Value |
|---|---|
| mode | `REAL_CONTROLLED_MODE` |
| allow_live_trading | `true` |
| simulate_only | `false` |
| dry_run | `false` |
| symbol | `XAUUSDm` |
| timeframe | `M1` |
| max_cycles | `20` |
| max_runtime_minutes | `10` |
| max_open_positions | `1` |
| max_pending_orders | `0` |
| fixed_lot | `0.01` |
| max_lot | `0.01` |
| max_daily_loss_usd | `5` |
| max_trade_loss_usd | `2` |
| max_spread_points | `350` for XAUUSDm |
| require_sl | `true` |
| require_tp_or_trailing | `true` |
| close_on_emergency_stop | `false` |
| magic_number | `20260514` |
| comment | `QADER_REAL_CONTROLLED` |

The 350-point XAUUSDm spread cap was selected as a broker-aware ceiling because validation observed spread around 308 points. Trades still block above that cap.

## Execution Architecture

```text
Qader GUI typed unlock
  -> RealModeService.run_lockdown_check()
  -> PermissionsStore.unlock_real_controlled_mode()
  -> RealModeService.start_real_controlled_run(final_confirmation=True)
  -> main_loop.run_cycle()
  -> Agents
  -> SignalArbiter
  -> DecisionRouter
  -> ConflictGuard
  -> RiskManager
  -> ExecutionManager._execute_real_controlled_market()
  -> mt5.order_send()
  -> stop after first send attempt/order
```

## GUI Behavior

Qader now has:

- Permissions screen typed unlock for `REAL_CONTROLLED_MODE`.
- Dedicated `REAL CONTROLLED MODE` tab.
- Red live trading status indicator.
- Account details panel: login, server, balance, equity, margin, open positions, pending orders.
- Lockdown check button.
- Validation-only button that never calls `order_send`.
- Final confirmation dialog before a bounded real run.
- Emergency stop button that locks real mode.
- Live execution log panel.

## Voice Behavior

Voice can request real trading but cannot activate it.

Any live/real trading command returns:

```text
Real trading requires manual confirmation from the permissions screen.
```

## Launch Command

Development launch:

```powershell
$env:PYTHONPATH="C:\Users\Radhi\MT5\src"; .\.venv\Scripts\python.exe -m qader_app.main
```

Packaged launch after build:

```powershell
.\dist\Qader\Qader.exe
```

## Unlock Flow

1. Launch Qader.
2. Open `Permissions`.
3. Type exactly: `I ACCEPT REAL TRADING RISK`.
4. Click `Unlock REAL CONTROLLED MODE`.
5. Qader runs `verify_mt5_lockdown.py`.
6. Unlock succeeds only if account info is readable, open positions are 0, pending orders are 0, and no magic=0 external exposure exists.
7. Open `REAL CONTROLLED MODE`.
8. Click `Validation only` to inspect gates.
9. Click `Start one real controlled run`.
10. Accept the final GUI confirmation dialog.

## Final Design Status

Implemented. Live trading remains locked unless the user manually unlocks `REAL_CONTROLLED_MODE` from the GUI and passes all safety gates.

# Qader REAL_CONTROLLED_MODE Safety Gates

Date: 2026-05-14

## Boundary

Active code scan:

```powershell
rg -n "self\.mt5\.order_send|mt5\.order_send\(" src/mt5_ai src/qader_app -g "*.py" -g "!**/archive/**"
```

Result:

```text
src/mt5_ai/core/execution_manager.py:244: result = mt5.order_send(request)
```

The active codebase has one real `mt5.order_send` call site. It is inside `ExecutionManager`.

Archived legacy files still contain old `order_send` code under `src/mt5_ai/archive/`; those files were not used or reactivated.

## Required Gates

`ExecutionManager.validate_real_controlled_request()` blocks `order_send` unless all gates below pass.

| Gate | Enforcement |
|---|---|
| `runtime.mode == REAL_CONTROLLED_MODE` | `config_loader.is_real_controlled_allowed()` and explicit gate |
| `allow_live_trading == true` | Real config only, not default runtime |
| `simulate_only == false` | Explicit gate |
| `dry_run == false` | Explicit gate |
| kill switch false | Explicit gate |
| Qader permission `can_place_live_orders` | `PermissionsGuard` and ExecutionManager gate |
| Real mode unlocked | `PermissionsStore` metadata gate |
| Typed phrase confirmed | Requires `I ACCEPT REAL TRADING RISK` |
| Lockdown exit code 0 | Stored after `verify_mt5_lockdown.py` |
| Lockdown recent | Must be within configured runtime window |
| SignalArbiter final BUY/SELL | `ExecutionRequest.signal_arbiter_passed` plus BUY/SELL action |
| ConflictGuard passed | `ExecutionRequest.conflict_guard_passed` |
| RiskManager approved | `ExecutionRequest.risk_decision.approved` |
| Final confidence threshold | `confidence.min_decision_confidence`, currently `0.55` |
| SL required | `req.sl > 0` |
| TP or trailing required | First version requires `req.tp > 0` |
| Lot fixed | `req.lot == 0.01` |
| Lot max | `req.lot <= 0.01` |
| Magic number | Must be `20260514` |
| Comment | Must include `QADER_REAL_CONTROLLED` |
| Account info readable | MT5 `account_info()` must return data |
| Open positions clean | Must be `0` before run; no averaging/pyramiding |
| Pending orders clean | Must be `0` |
| magic=0 external exposure absent | No position/order with `magic == 0` |
| Spread within limit | XAUUSDm max 350 points |
| Pending orders disabled | Config gate |
| No averaging | Config gate |
| No martingale | Config gate |
| No grid | Config gate |
| No pyramiding | Config gate |
| No re-entry loop | Config gate |
| One market order per run | ExecutionManager counter |

## Disabled Paths

| Path | Status |
|---|---|
| `MT5Gateway.send_demo_pending_order()` | Returns blocked |
| `MT5Gateway.send_demo_market_order()` | Returns blocked |
| `MT5Gateway.modify_demo_position_sl_tp()` | Returns blocked |
| `ExecutionManager.send_raw_order()` live path | Returns blocked |
| `ExecutionManager.cancel_pending_order()` live path | Returns blocked in v1 |
| Voice live trading activation | Denied; requires manual permissions screen |

## Account Lockdown Result

Command:

```powershell
.\.venv\Scripts\python.exe verify_mt5_lockdown.py
```

Result:

| Check | Result |
|---|---|
| Account info readable | yes |
| Login | 260749517 |
| Server | Exness-MT5Trial15 |
| Balance | 160.81 USD |
| Equity | 160.81 USD |
| Open positions | 0 |
| Pending orders | 0 |
| magic=0 external exposure | none |
| Exit code | 0 |

Note: the verify script identifies `Exness-MT5Trial15` as DEMO/TRIAL.

## Validation Mode Result

Command:

```powershell
.\.venv\Scripts\python.exe -c "import sys,json; sys.path.insert(0,'src'); from qader_app.services.real_mode_service import RealModeService; r=RealModeService().validation_mode_without_order(); print(json.dumps({'allowed': r.get('allowed'), 'failed_gates': [g for g in r.get('gates', []) if not g.get('passed')], 'orders_sent_this_run': r.get('orders_sent_this_run')}, indent=2, default=str))"
```

Result:

| Field | Value |
|---|---|
| Allowed | `false` |
| Orders sent this run | `0` |
| Real `order_send` called | `0` |

Failed gates were expected because the user has not manually unlocked real mode in the GUI:

| Gate | Reason |
|---|---|
| `permission_can_place_live_orders` | `can_place_live_orders=False` |
| `real_mode_unlocked` | `unlocked=False` |
| `unlock_phrase_confirmed` | `phrase_confirmed=False` |
| `lockdown_exit_code_zero` | no stored GUI unlock lockdown result |
| `lockdown_recent` | no stored GUI unlock timestamp |

All structural/config/account gates passed in validation-only mode, including SignalArbiter proof, ConflictGuard proof, RiskManager proof, SL/TP, lot, magic, account clean, pending orders clean, no external magic=0 exposure, and spread within limit.

## Final Safety Status

`order_send` can execute only after manual GUI unlock and final GUI confirmation. In the current state, live trading remains locked.

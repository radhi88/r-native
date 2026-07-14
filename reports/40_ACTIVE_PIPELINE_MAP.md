# Report 40 - Active Pipeline Map

Generated: 2026-05-14T02:22:35+03:00

## Main Runner

`src/mt5_ai/runtime/main_loop.py` is the confirmed controlled runner.

## Current Pipeline

```text
MT5 copy_rates_from_pos/read-only bars
  -> FractalAgent + SmcAgent + IctSweepAgent
  -> SignalArbiter
  -> DecisionRouter
  -> ConflictGuard
  -> RiskManager
  -> ExecutionManager
  -> DRY_RUN simulated result in current config
```

## Connected Agents

| Role | Connected |
|---|---|
| Entry signals | FractalAgent, SmcAgent, IctSweepAgent |
| Position management | GovernorAgent, RiskCloseAgent |

## Not Connected To `run_cycle()`

AiAgent, ScalperAgent, TouchAgent, ScalpingAgent, SwingAgent, WickAgent, RiskAgent, PendingAgent, MarketAnalystAgent, LiquidityHunterAgent, MonitorAgent.

## Risk

Active risk module: `src/mt5_ai/core/risk_manager.py`.

Codex applied the Claude-approved fix so `main_loop.py` now passes actual spread, open-position count, and daily-loss percent into `RiskManager.validate()`.

## Execution

Active execution boundary: `src/mt5_ai/core/execution_manager.py`.

`ExecutionManager` checks kill switch, request validity, magic registry, DRY_RUN/simulate_only, and `allow_live_trading` before any MT5 send path.

`src/mt5_ai/mt5_gateway.py` remains a boundary wrapper. Direct demo write methods are now blocked by runtime DRY_RUN/kill_switch checks and `DEMO_TRADING_ENABLED=False`.

## Config Control

| Config | Role |
|---|---|
| `config/trading_runtime.yaml` | default runtime config; DRY_RUN, allow_live_trading=false, kill_switch=true |
| `config/dry_run_simulation.yaml` | test config; DRY_RUN and simulate_only=true |
| `config/live_micro_disabled.yaml` | disabled template only; DRY_RUN and allow_live_trading=false |

## order_send Boundary

Guarded active `order_send` call sites: `8`.

Unguarded active `order_send` call sites: `0`.

Real `order_send` calls during controlled runtime test: `0`.

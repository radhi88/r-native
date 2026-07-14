# 79 - Qader Demo System Status

Generated: 2026-05-14

## Final Status

RUNNING in DEMO/TRIAL mode.

## Account and Data

- Account: `260749517`
- Server: `Exness-MT5Trial15`
- Trade mode: `0` (`DEMO/TRIAL`)
- Balance/equity latest proof: `100.34` / `100.34`
- Symbol: `XAUUSDm`
- Timeframe: `M1`
- MT5 tick check: PASS
- M1 bars received: `120` in standalone check, `150` in loop records

## Runtime

- Realtime loop: running
- Loop interval: 1 second
- Log path: `logs/qader_realtime_loop.jsonl`
- Dashboard state: `dashboard/qader_live_state.json`
- Current proof runner: manage-only restart after 3-trade target
- Latest proof restart state:
  - `loop_state`: `RUNNING`
  - latest cycle observed: `340`
  - `allow_new_entries`: `false`
  - `thread_alive`: `true`
  - `execution_status`: `new_entries_disabled`
  - `bars_received`: `150`

## Trades

- Demo trades opened: `6` actual MT5 entry deals with Qader magic `20260514`
- Demo trades managed: `6` entries with management/SLTP modify proof
- Current open positions: `0`
- Closed positions/deals: `6`
- Entry order IDs: `1616673302`, `1616673339`, `1616673386`, `1621153896`, `1621153980`, `1621154029`
- Entry deal tickets: `1492048690`, `1492048725`, `1492048765`, `1496393091`, `1496393171`, `1496393223`
- Exit deal tickets: `1492049369`, `1492049370`, `1492049603`, `1496396496`, `1496396502`, `1496396622`
- Entry order_send successes: `6`
- SL/TP modify order_send successes: `9`
- Total successful ExecutionManager order_send calls: `15`

## Safety

- DEMO_ONLY mode active.
- Real accounts are blocked by account gate.
- `order_send` remains in `src/mt5_ai/core/execution_manager.py`.
- Max market orders per run: `3`.
- Max open Qader positions: `3`.
- Lot size: `0.01`.
- SL required.
- TP or trailing/management required.
- Spread check required.
- SignalArbiter, ConflictGuard, and RiskManager are required before entry.
- Emergency stop disables new entries and activates kill switch.

## Validation Run

- `verify_mt5_lockdown.py`: PASS, account clean, no positions/orders.
- MT5 XAUUSDm M1 bars/tick check: PASS.
- Import checks: PASS.
- PyQt GUI smoke: PASS.
- Active static order_send scan: only `src/mt5_ai/core/execution_manager.py` has active MT5 `order_send` calls; `runner_service.py` only defines a blocked monkeypatch for safety.

## Remaining Blockers

None for the demo target. PyQt WebEngine is optional; when unavailable, Qader still writes and opens the local HTML dashboard.

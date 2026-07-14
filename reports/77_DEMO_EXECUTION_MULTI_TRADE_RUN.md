# 77 - Demo Execution Multi-Trade Run

Generated: 2026-05-14

## Status

PASS. Qader opened at least 3 actual MT5 demo trades through `ExecutionManager` on Exness-MT5Trial15. Latest MT5 history proof shows 6 Qader demo entry deals.

## Account

- Login: `260749517`
- Server: `Exness-MT5Trial15`
- Trade mode: `0` (`DEMO/TRIAL`)
- Balance after run: `100.34`
- Equity after run: `100.34`

## Actual Demo Trades

Entry deals counted from MT5 history with Qader magic `20260514`:

| Order | Entry Deal | Symbol | Lot | Comment |
|---:|---:|---|---:|---|
| 1616673302 | 1492048690 | XAUUSDm | 0.01 | QADER_DEMO\|ARB\|d |
| 1616673339 | 1492048725 | XAUUSDm | 0.01 | QADER_DEMO\|ARB\|d |
| 1616673386 | 1492048765 | XAUUSDm | 0.01 | QADER_DEMO\|ARB\|d |
| 1621153896 | 1496393091 | XAUUSDm | 0.01 | QADER_DEMO\|ARB\|d |
| 1621153980 | 1496393171 | XAUUSDm | 0.01 | QADER_DEMO\|ARB\|d |
| 1621154029 | 1496393223 | XAUUSDm | 0.01 | QADER_DEMO\|ARB\|d |

Exit deals counted from MT5 history:

- `1492049369`
- `1492049370`
- `1492049603`
- `1496396496`
- `1496396502`
- `1496396622`

## Management Proof

`logs/live_performance_journal.jsonl` records:

- repeated `position_management_evaluated` entries for tickets `1616673302`, `1616673339`, `1616673386`
- `position_management_order_result` with `retcode=10009` for SL lock/trailing/breakeven updates

## Order Send Counts

- Entry `order_send` successes: `6`
- SL/TP modify `order_send` successes: `9`
- Close/reduce management `order_send` successes: `0`
- Total successful `ExecutionManager` order_send calls: `15`

## Current Positions

- Current MT5 positions: `0`
- Current Qader positions: `0`
- All 6 demo entries are now closed by broker-side SL/TP handling after active Qader management.

## Notes

After the target was proven, the patched runner was restarted in manage-only mode (`QADER_START_MANAGE_ONLY=1`) to keep realtime analysis/logging running without adding extra demo exposure.

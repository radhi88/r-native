# 81 - Live Chart UI Upgrade

Generated: 2026-05-14

## Status

PASS. Qader now has a live-updating chart in both the PyQt dashboard and the JavaScript/HTML dashboard.

## Implemented

- `RealTimeLoopService` now writes `chart_history` into `dashboard/qader_live_state.json`.
- Chart history includes:
  - timestamp
  - cycle number
  - bid
  - ask
  - mid price
  - spread
  - confidence
  - final action
  - arbiter result
  - risk/execution status
  - open position count
- PyQt dashboard now includes a custom painted realtime chart:
  - XAUUSDm M1 mid-price line
  - confidence overlay
  - BUY/SELL signal markers
  - live price and confidence labels
- HTML dashboard now includes a Canvas realtime chart:
  - auto-refresh every second
  - responsive canvas rendering
  - price line
  - confidence line
  - BUY/SELL markers
  - latency, mid price, and confidence stats
- GUI auto-start now checks `dashboard/qader_live_state.json` first and avoids launching a duplicate realtime loop if an external runner is already alive.

## Runtime Verification

- Current chart-enabled runner is active.
- Only one runner remains after stopping the duplicate GUI-started loop.
- `dashboard/qader_live_state.json` contains `chart_history`.
- Latest observed loop:
  - state: `RUNNING`
  - cycle: `111`
  - symbol: `XAUUSDm`
  - timeframe: `M1`
  - bars received: `150`
  - allow new entries: `false`
  - thread alive: `true`

## Files Changed

- `src/qader_app/services/real_time_loop_service.py`
- `src/qader_app/gui/dashboard.py`
- `src/qader_app/gui/main_window.py`
- `src/qader_app/gui/real_controlled.py`
- `dashboard/qader_live_dashboard.html`
- `dashboard/qader_dashboard.css`
- `dashboard/qader_dashboard.js`

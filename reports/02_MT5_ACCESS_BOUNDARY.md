# 02 — MT5 Access Boundary
Generated: 2026-05-13

## Classification

| File | MT5 Access Type | Status |
|------|----------------|--------|
| `src/mt5_ai/mt5_gateway.py` | **Allowed low-level adapter** | KEEP — refactor callers to use it |
| `src/mt5_ai/algory_runner.py` | **Unsafe executor** — bypasses gateway | FIX — route through mt5_gateway |
| `friday_demo_position_governor.py` | Unsafe executor | ARCHIVE after extracting logic |
| `friday_demo_position_governor_v2.py` | Unsafe executor | ARCHIVE after extracting logic |
| `friday_realtime_scalper_demo_executor.py` | Unsafe executor | ARCHIVE |
| `friday_touch_demo_executor.py` | Unsafe executor | ARCHIVE |
| `friday_risk_close.py` | Unsafe executor | ARCHIVE → route via PositionManager |
| `scripts/mt5_ollama_trader.py` | Unsafe executor | Convert to OllamaAgent (SignalProducer) |
| `scripts/ict_sweep_trader.py` | Unsafe executor | Convert to IctSweepAgent |
| `ict_sweep_trader.py` (root) | Unsafe executor | ARCHIVE (duplicate) |
| `src/mt5_ai/friday_voice/mt5_tools.py` | Read-only data provider | KEEP — no order_send |
| `friday_scalper_live_dashboard.py` | Dashboard only | KEEP |
| `algory_chart_dashboard.py` | Dashboard only | KEEP |
| `friday_capital_brain.py` | Read-only (position query) | KEEP |
| `friday_feature_outcome_learner.py` | Read-only (deal history) | KEEP |
| `friday_trade_outcome_learner.py` | Read-only (deal history) | KEEP |
| `FRIDAY_Gold_EA.mq5` | Separate EA execution path | Document boundary, disable if Python running |

## Required boundary enforcement
After refactor, only `src/mt5_ai/mt5_gateway.py` may import MetaTrader5 for write operations.
All other files may import MetaTrader5 only for read operations (copy_rates, symbol_info, tick).

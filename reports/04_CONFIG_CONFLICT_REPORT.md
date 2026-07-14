# 04 — Config Conflict Report
Generated: 2026-05-13

## Duplicated / Conflicting Settings Found

### Magic Numbers (CRITICAL)
| Value | Used By | Conflict |
|-------|---------|---------|
| `260426` | `src/mt5_ai/config.py` DEFAULT_MAGIC, `selected_code/config.py`, mt5_gateway | Safe — legacy default |
| `20260504` | `friday_realtime_scalper_demo_executor.py`, FRIDAY_MAGICS set | Inactive but registered |
| `20260505` | `friday_touch_demo_executor.py`, FRIDAY_MAGICS set | Inactive but registered |
| `20260506` | `scripts/ict_sweep_trader.py`, `friday_demo_position_governor.py` --magic default, FRIDAY_MAGICS set | **CONFLICT — 2 files use same magic** |
| `20260507` | `friday_demo_position_governor_v2.py` --magic default, FRIDAY_MAGICS set | Inactive |
| `88888` | `scripts/mt5_ollama_trader.py` | **NOT in FRIDAY_MAGICS** — learners skip these trades |
| `202605` | `ict_sweep_trader.py` (root) | Different from `scripts/` version (20260506) — same file concept, 2 magic numbers |
| None | `algory_runner.py` | **No magic number** — uses comment "FRIDAY\|{gid}" for identification |

### Symbol Definitions
- `friday_symbol_universe.py` — master list
- `src/mt5_ai/algory_runner.py` — hardcoded in orchestrator args: `EURUSDm GBPUSDm USDJPYm AUDUSDm USDCADm NZDUSDm USDCHFm XAUUSDm`
- Various executors have their own symbol lists
- **Conflict:** orchestrator symbols ≠ potentially what governors manage

### Lot / Risk Settings
- `src/mt5_ai/algory_dna.py` — genome.risk_pct per genome
- `friday_realtime_scalper_demo_executor.py` — hardcoded lot logic
- `friday_touch_demo_executor.py` — own lot calculation
- `scripts/mt5_ollama_trader.py` — own lot calculation
- No single unified risk config

### Max Positions / Max Trades
- `friday_demo_position_governor_v2.py` — `--max-trades`, `--max-open-positions` CLI args
- `src/mt5_ai/prop_firm_guard.py` — own limits
- `friday_capital_brain.py` — own position counting
- No unified max_positions config

### Cooldown Settings
- Multiple files implement independent cooldown logic
- `src/mt5_ai/algory_runner.py` — cooldown per symbol/TF in `_bar_lock`
- `friday_entry_gate.py` — own cooldown
- `friday_demo_position_governor.py` — `--cooldown-minutes`
- No shared cooldown state

### Session Filters
- Each executor defines its own session hours
- Not centralized

### Demo/Live Flags
- `algory_runner.py` — `--live` CLI arg
- Orchestrator passes `--live` to algory_runner
- Other executors have own demo/live flags
- No unified kill switch

## Required Consolidation
1. Create `config/trading_runtime.yaml` as single source of truth
2. All magic numbers into `src/mt5_ai/core/magic_registry.py`
3. All symbol lists through `friday_symbol_universe.py`
4. All risk limits through `RiskManager`
5. Kill switch must be global and checked by ExecutionManager

# 05 — Magic Number Registry Report
Generated: 2026-05-13

## Current Magic Numbers Found

| Magic | File | Strategy | Status |
|-------|------|----------|--------|
| `260426` | `src/mt5_ai/config.py` DEFAULT_MAGIC | Legacy/mt5_gateway default | CONFLICT — not in FRIDAY_MAGICS, reassign |
| `20260504` | `friday_realtime_scalper_demo_executor.py` | Scalper | INACTIVE — keep in registry |
| `20260505` | `friday_touch_demo_executor.py` | Touch executor | INACTIVE — keep in registry |
| `20260506` | `scripts/ict_sweep_trader.py` + `friday_demo_position_governor.py` | ICT Sweep + Governor | **DUPLICATE — 2 owners** |
| `20260507` | `friday_demo_position_governor_v2.py` | Governor v2 | INACTIVE — keep in registry |
| `88888` | `scripts/mt5_ollama_trader.py` | Ollama AI | **NOT in FRIDAY_MAGICS — learners skip** |
| `202605` | `ict_sweep_trader.py` (root) | ICT Sweep root | DUPLICATE concept (different number) |
| None | `src/mt5_ai/algory_runner.py` | Algory | **NO MAGIC — uses comment only** |

## Problems
1. `20260506` assigned to two different strategies
2. `algory_runner` has no magic — positions unidentifiable by magic
3. `88888` unknown to learner systems
4. `260426` is default in mt5_gateway but not tracked by FRIDAY_MAGICS

## Recommended Clean Registry

| ID | Magic | Strategy | Owner |
|----|-------|----------|-------|
| FRIDAY_ALGORY | `20260600` | Algory Runner | `algory_runner.py` |
| FRIDAY_SMC | `20260601` | SMC / Fractal Agent | future smc_agent |
| FRIDAY_ICT | `20260602` | ICT Sweep Agent | future ict_sweep_agent |
| FRIDAY_SCALPER | `20260603` | Scalper Agent | future scalper_agent |
| FRIDAY_TOUCH | `20260604` | Touch Agent | future touch_agent |
| FRIDAY_GOVERNOR | `20260605` | Position Governor | future position_manager |
| FRIDAY_OLLAMA | `20260606` | Ollama / AI Agent | future ai_agent |
| MANUAL_TEST | `20260699` | Manual / test trades | reserved |

## Action Required
- Add magic `20260600` to `algory_runner.py` immediately
- Add all new magics to FRIDAY_MAGICS set in learner files
- Create `src/mt5_ai/core/magic_registry.py` as single source

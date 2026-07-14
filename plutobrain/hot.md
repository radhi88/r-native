# Hot Cache

> Session cache. Read this FIRST before any substantive response. Updated by `/weekly-update` and after significant sessions.

## Last updated
2026-05-21

## What I'm currently focused on

1. **FRIDAY Phase 2** — Core schemas and architecture stabilization after Phase 0+1 completion
2. **PlutoBrain setup** — Installing this vault as the knowledge OS for the FRIDAY project
3. **Local AI assistant** — Running quantized models via Ollama/llama.cpp for trading queries

## Active open loops

- Phase 2 core schemas: not started yet
- Stop-loss on entry: KNOWN BUG — open, not fixed
- Kill-switch enforcement: config exists but not fully wired
- LIVE_TRADING_ENABLED: still True in selected code — needs audit before live use
- Paper trading validation: no documented win-rate on XAUUSDm M1 yet
- Gene learning loop: running but not backtested end-to-end
- HuggingFace AGENTS customization: initiated this session

## Recently shipped

- 2026-05-21: Algory factory fully integrated (9 files, bootstrap from vault, runner in start_friday_trading_full.ps1)
- 2026-05-21: Fractal engine all phases complete (live monitor 40 pairs, backtester, dashboard extensions)
- 2026-05-21: Architecture refactor Phase 0+1 done (7 reports + archive)
- 2026-05-21: ALGORY_MAGIC = 20260600 added
- 2026-05-21: PlutoBrain cloned + configured for FRIDAY project

## What's been on my mind

- How to make the local AI assistant (Ollama) respond fast enough for M1 scalping decisions
- When to flip LIVE_TRADING_ENABLED after paper trading validation
- Whether to stabilize current architecture before adding new integrations (→ see Pattern: Scope Creep)

## Recent decisions

- 2026-05-21: PlutoBrain installed at `C:\Users\Radhi\MT5\plutobrain` as knowledge OS for FRIDAY
- 2026-05-21: Architecture refactor: next focus is Phase 2 (core schemas) not new feature additions
- 2026-05-21: HuggingFace skills scoped to: local-models, hf-cli, tool-builder, trackio, sentence-transformers only

---
*Auto-updated by `/weekly-update`. Edit manually anytime.*

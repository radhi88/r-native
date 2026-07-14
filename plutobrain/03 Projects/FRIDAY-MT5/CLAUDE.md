# FRIDAY-MT5 — Project Layer

> Project-specific config for the FRIDAY AI scalping system. Inherits vault root `CLAUDE.md`. This folder holds REFERENCE DOCS ONLY — code lives at `C:\Users\Radhi\MT5`.

## Project at a glance

**One-line description:** Local-first AI scalping engine for XAUUSDm M1 using Keras NN + SMC + fractal analysis on MetaTrader 5.

**Stage:** Building → iterating (Phase 2 of 18-phase refactor)

**Owner:** Radhi Amash

**Started:** ~2025 (active development ongoing as of 2026-05-21)

**Target outcome:** Profitable automated scalping on XAUUSDm M1 with positive expectancy over 3 months live paper trading, then live deployment.

**Why this matters:** Primary income vehicle. The system must be robust, self-improving, and safe before going live.

## Active vs reference

**Reference project.** Code lives at `C:\Users\Radhi\MT5`. This folder holds structured docs, decisions, research, and architecture notes only. Claude does NOT edit source code from within this vault — it edits from the `C:\Users\Radhi\MT5` working directory directly.

## Folder structure

```
03 Projects/FRIDAY-MT5/
├── CLAUDE.md (this file — reference config)
├── inputs/  (architecture diagrams, trade data samples, research inputs)
├── process/ (phase plans, decisions, working notes)
├── outputs/ (backtesting results, performance reports, phase completion docs)
└── notes/   (ad-hoc notes on the system)
```

## Architecture — quick reference

```
C:\Users\Radhi\MT5\
├── start_friday_trading_full.ps1    ← main launcher
├── friday_web_dashboard.py          ← dashboard (has gaps — see below)
├── algory_factory/                  ← Algory signal factory (9 files)
├── fractal_structure_engine.py      ← fractal analysis
├── market_projection_engine.py      ← projection layer
├── live_monitor_*.py                ← 40-pair live monitor
└── .planning/codebase/              ← 7 architecture docs
```

**Core stack:**
- MT5 terminal ↔ Python via `MetaTrader5` library
- ZeroMQ for inter-process messaging
- Keras/TensorFlow NN for signal scoring
- Ollama / llama.cpp for local AI queries (OpenAI-compatible API)
- Gene learning loop (weights updated from trade outcomes)

**Key constants:**
- `ALGORY_MAGIC = 20260600`
- Primary symbol: `XAUUSDm`
- Primary timeframe: `M1`

## Known open bugs (MUST FIX before live)

1. **No stop-loss on entry** — trades open without SL attached. High risk.
2. **Kill-switch not fully enforced** — exists in config, not wired through all entry paths.
3. **LIVE_TRADING_ENABLED = True** in some code paths — needs audit. Paper trading is default intent.

## 18-phase refactor status

| Phase | Description | Status |
|---|---|---|
| 0 | Audit + baseline reports | ✅ Done |
| 1 | Archive + quick wins (ALGORY_MAGIC) | ✅ Done |
| 2 | Core schemas | 🔄 Next |
| 3-17 | TBD per plan | ⏳ Pending |

## Project-specific instructions for Claude

- Always treat this as a REFERENCE project — never commit code changes from vault context
- When referencing source files, always include full path from `C:\Users\Radhi\MT5\`
- Flag any suggestion that touches LIVE_TRADING_ENABLED or removes safety checks
- Paper trading is the default. Live trading requires explicit user confirmation.
- Code responses: Python preferred, no unnecessary abstractions, no mock data for critical paths
- Architecture decisions: document in `process/decisions-log.md`

## Active sub-tasks / milestones

### Now (this week)
- [ ] Begin Phase 2: core schemas (data models, signal contracts)
- [ ] Audit LIVE_TRADING_ENABLED across all files
- [ ] Document current paper trading win-rate baseline (even if zero)

### Next (this month)
- [ ] Fix stop-loss on entry
- [ ] Enforce kill-switch through all entry paths
- [ ] Phase 2 complete and verified

### Later (this quarter)
- [ ] Phases 3-6 per refactor plan
- [ ] Sentence-transformers on trade log for semantic search
- [ ] Gene learning loop backtested end-to-end

### Done
- [x] 2026-05-21 — Algory factory integrated (9 files, bootstrap from vault)
- [x] 2026-05-21 — Fractal engine all phases complete (40-pair live monitor)
- [x] 2026-05-21 — Architecture refactor Phase 0+1 done (7 reports + archive)
- [x] 2026-05-21 — ALGORY_MAGIC = 20260600 added
- [x] 2026-05-21 — PlutoBrain vault configured as knowledge OS

## Decisions log

- (2026-05-21) — Chose local-first AI (Ollama/llama.cpp) over cloud API. Reason: latency for M1 scalping, no API cost per trade, offline capability. Trade-off: limited model size on local hardware.
- (2026-05-21) — Paper trading is default until 3 criteria met: SL fixed, kill-switch enforced, 500+ paper trades with positive expectancy.
- (2026-05-21) — HuggingFace skills scoped to: local-models, hf-cli, tool-builder, trackio, sentence-transformers. No vision/Gradio/paper publishing.
- (2026-05-21) — PlutoBrain installed as vault for FRIDAY knowledge base, NOT as a replacement for .planning/ docs.

## Open questions

- What's the actual win-rate on XAUUSDm M1 in paper trading right now?
- Which quantized model (GGUF) gives best SMC reasoning at <500ms on local hardware?
- After Phase 2 schemas: what's the right test suite to validate signal contract integrity?

## Related vault entries

- [[Smart Money Concepts]] — core trading theory
- [[Fractal Structure]] — fractal engine basis
- [[XAUUSDm]] — primary instrument
- [[Algory Integration]] — completed sub-project

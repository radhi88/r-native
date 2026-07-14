# 🏛 R Native V2 — The Palace

**Codename**: PALACE
**Started**: 2026-05-27 (Cycle 39 night, silent build)
**Status**: 🔒 SILENT BUILD — v1 keeps running, v2 baked here in parallel

## Why a New House?

V1 grew from 0 → 31 agents → 149 HoF genomes via emergency fixes layered on
emergencies. The result:
- 5 systems on one account (R Native, FRIDAY Brain, QADER, etc.)
- 52 stale pending orders sitting in JSON
- Agents that recommend kills but can't act (autonomy gaps)
- Genome routing that put losing genomes on exotic pairs
- A RSI-FLIP bug that flipped winning trades into losing ones
- Combined -$449 in 7 days = -82% account drawdown

V1 was reactive — every fix was a patch. V2 is **designed**.

## What We Take From V1 (Keep)

- `extra_indicators.py` — CCI/Stoch/Fib/Candle math is sound
- `hall_of_fame.py` — atomic write + lineage tracking is mature (post-cycle 36 fix)
- `recovery_mode.py` (cycle 39) — winners-only whitelist concept
- Genome 4F5F59 (proven winner across XAU/EUR/GBPJPY)
- `genome_signal.py` SIGNAL_EVALUATORS dict pattern (extensible)

## What We Leave Behind

- 28 agents that never produced ACT-level insights in 7 days
- Magic 20260514 / 20260600 / 77701 / 0 systems (separate decoupled brains)
- The `_ALG_ARCHETYPE` legacy archetype layer (BREAKOUT_HUNTER etc.)
- LLM kill safety ceiling logic (now superseded by performance_coach act path)
- Hardcoded WHITELIST in recovery_mode — V2 derives it dynamically from live PnL

## V2 Core Principles

1. **Council, not orchestra** — 5 named experts vote on every trade.
   No 31-agent committee. No agent without a vote.
2. **MTF confluence required** — M15 trend + M5 setup + M1 trigger
   must align. No solo-TF entries.
3. **Session-aware** — Asian session = M15 only. London+NY overlap = M1 OK.
   Outside windows = no trading.
4. **Genome = persona** — Each genome has an *identity* (Claude-Apex,
   Claude-Hunter, etc.) and a thesis ("buys breakouts on aligned MTF
   trend during NY overlap"). Backtests + live results judged against
   the thesis, not just PnL.
5. **Two-version progression** — V2 paper-trades for 50+ trades on demo
   before going LIVE on the real account. No "let's just try it" launches.

## The Council

```
                        ┌─────────────┐
                        │  ARCHITECT  │  system design, data flow, integrity
                        └──────┬──────┘
                               │
       ┌───────────┬───────────┼───────────┬───────────┐
       │           │           │           │           │
   ┌───▼──┐   ┌────▼───┐   ┌───▼────┐  ┌───▼───┐  ┌────▼────┐
   │ QUANT│   │  RISK  │   │EXECUTOR│  │REVIEWR│  │ HISTORY │
   │math  │   │capital │   │ orders │  │ cross │  │ memory  │
   │indi  │   │SL/TP   │   │ fills  │  │ check │  │ journal │
   └──────┘   └────────┘   └────────┘  └───────┘  └─────────┘
       │           │           │           │           │
       └───────────┴───────────┼───────────┴───────────┘
                               │
                        ┌──────▼──────┐
                        │   TRADER    │ ← the genome (Claude-X)
                        └─────────────┘
```

**Decision flow**: Trader proposes → Council votes (each vetoes independently)
→ if 4/5 approve → trade. Single veto blocks. Everything logged.

## File Layout

```
r_native_v2/
├── docs/                     ← manifesto, design docs, ADRs
│   └── PALACE_MANIFESTO.md   ← this file
├── council/                  ← 5 expert agent classes
│   ├── architect.py
│   ├── quant.py
│   ├── risk.py
│   ├── executor.py
│   └── reviewer.py
├── indicators/               ← clean reimplementation of MTF stack
│   ├── mtf_engine.py         ← single source of truth for M1/M5/M15/H1/H4
│   ├── confluence.py         ← MTF alignment scoring
│   └── session.py            ← session window logic
├── genomes/                  ← named persona classes
│   ├── claude_apex.py        ← my first genome (XAU specialist)
│   ├── claude_hunter.py      ← breakout hunter (pending: after Apex proven)
│   └── base.py               ← Genome ABC + thesis contract
├── agents/                   ← v2 background agents (much fewer)
│   ├── live_journal.py       ← every trade gets a story
│   ├── council_logger.py     ← vote tallies, dissent tracking
│   └── thesis_validator.py   ← compares actual results vs genome thesis
├── runtime/
│   ├── paper_trader.py       ← simulates trades against live feed
│   └── live_bridge.py        ← (LATER) bridge to real mt5.order_send
└── tests/
    └── golden/               ← fixtures for backtesting

# v1 stays at C:/Users/Radhi/MT5/r_native (untouched)
# v2 lives at C:/Users/Radhi/MT5/r_native_v2 (this directory)
```

## Launch Criteria (when does V2 go live?)

V2 paper-trades for at least:
- [ ] 50 trades on XAUUSDm (or any single instrument)
- [ ] Profit factor ≥ 1.4 on paper
- [ ] Maximum drawdown ≤ 10%
- [ ] At least 3 consecutive winning days
- [ ] All 5 council members vote unanimously on > 60% of approved trades
- [ ] Zero "council disagreement caused loss" incidents in journal

Only then does the live bridge get plugged in.

## Migration Plan ("Moving to the Palace")

1. **Phase 0** (current): build skeleton + Claude-Apex genome + paper trader
2. **Phase 1**: paper-trade Claude-Apex on live XAU M1 feed for 100 trades
3. **Phase 2**: add Claude-Hunter (breakout persona), council compares
4. **Phase 3**: build 5 more personas (EURUSD, GBPJPY, BTC, ETH, US30 specialists)
5. **Phase 4**: launch on demo account (separate broker login if available)
6. **Phase 5**: graduate to live with $50 sub-account, 0.01 lot, 4-week test
7. **Phase 6**: full migration — v1 archived, v2 takes over

No timeline. Each phase needs criteria met. Patience > speed.

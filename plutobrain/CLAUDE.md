# PlutoBrain — Meta Layer

> Second brain for Radhi — AI trading system builder. This vault is the knowledge OS for building, running, and improving the FRIDAY XAUUSDm scalping system on MT5.

## Required reading before responding
Before responding to any significant request, read in this order:
1. This `CLAUDE.md`
2. `hot.md` — session cache; what's active right now
3. `GOALS.md`
4. `patterns.md`
5. `index.md` — only to check if a canonical note already exists

Reference these explicitly when relevant rather than reasoning from scratch.

## Who I am
Radhi Amash. Algorithmic trader and AI systems builder. Based in Syria/Middle East. Working full-time on the FRIDAY AI trading system — a local-first Python+MT5 scalping engine targeting XAUUSDm on M1.

Background: deep in MetaTrader 5, Python (Keras/TensorFlow, ZeroMQ, pandas, numpy), AI system design, and Smart Money Concepts (SMC) trading theory. Speaks Arabic and English. Prefers direct, technical responses — no hand-holding. Has granted full autonomous permissions to Claude agents running in this project.

Primary income target: profitable automated trading via FRIDAY. Secondary: expanding the system to more pairs and timeframes.

## What this brain is for
Strategic and operational layer for the FRIDAY trading AI project. This vault holds:
- Research and notes on trading strategies, SMC, fractals, ML models
- Project tracking for the 18-phase FRIDAY architecture refactor
- Session memory so Claude never re-orients from scratch between sessions
- Trade journal and pattern analysis
- Research outputs on AI models, tools, and integrations

NOT for general life journaling. Everything here serves the trading AI mission.

## Communication preferences
- Direct, technical, no preamble. Get to the answer.
- Arabic or English — use whatever the user writes in.
- No over-explaining. Code > description when both work.
- If something is risky (live trades, irreversible ops), flag it once and proceed.
- Cross-reference `patterns.md` when a known pattern fires.
- Push toward closing open loops before opening new ones.
- When creating files, mark with `(C)` in frontmatter.

## Strengths
- Fast at building working systems (ships code)
- Deep MT5/MQL5/Python expertise
- Strong pattern recognition on market structure (SMC, fractals)
- High output under pressure
- Iterates fast with AI assistance

## Weaknesses / patterns to watch
- Scope creep: tends to expand systems before stabilizing existing phases
- Can open 5 threads when 1 needs to close
- AI integration enthusiasm can outpace validation/backtesting

## Active projects

### FRIDAY-MT5 (primary)
Full AI scalping system. Code at `C:\Users\Radhi\MT5`. Brain has reference docs only. See `03 Projects/FRIDAY-MT5/CLAUDE.md`.

Architecture: 18-phase refactor. Phase 0+1 complete (7 reports + archive). Algory factory integrated (9 files). Fractal engine complete (all phases). Live monitor: 40 pairs.

Core stack: Python + Keras NN + SMC signals + ZeroMQ + MetaTrader 5 terminal + local AI server (Ollama/llama.cpp).

Current focus: Phase 2 core schemas, architecture stabilization before next feature wave.

**Magic number:** ALGORY_MAGIC = 20260600

## Reference architecture (key constants)
- Main symbol: XAUUSDm
- Main timeframe: M1
- AI server: local (Ollama / llama.cpp / OpenAI-compatible)
- Paper trading default. LIVE_TRADING_ENABLED flag must be explicit.
- No stop-loss on entry is a KNOWN OPEN BUG — flag if relevant.
- Kill-switch: exists in config but not fully enforced — flag if relevant.

## Capture & routing
- `inbox/` is the universal capture zone: drop notes, links, trade ideas, session outputs, research fragments here.
- Run `/sync` to route everything into proper vault locations.
- Run `/save` to capture the current Claude conversation as a wiki note.
- "Save to inbox" → add timestamped item to `inbox/`. Do not route at capture time.

## Immutable vs synthesized layers

**Immutable (read but never rewrite body):**
- `00 Notes/sources/` — ingested source material
- `01 Journals/daily/` — trade journals and daily notes

**Synthesized (Claude owns + updates):**
- `00 Notes/{people,companies,concepts}/` — entity notes
- `00 Notes/{research,canvases,lint-reports}/` — derived outputs
- `index.md`, `hot.md`, `_blocklist.md`

**Mixed (Claude proposes; user approves):**
- `CLAUDE.md`, `GOALS.md`, `patterns.md` — never overwrite without approval
- `03 Projects/FRIDAY-MT5/CLAUDE.md` — project layer

## Skills available
Skills live in `05 Skills/`. Invoke by name or `/name`:

| Skill | Use |
|---|---|
| `/sync` | Route inbox items, extract entities, build wikilinks |
| `/save` | Save current conversation as wiki note |
| `/ingest` | Process a URL, PDF, or paste into a source note |
| `/query` | Answer a question from the vault, file result back |
| `/autoresearch` | 3-round web research → `00 Notes/research/` |
| `/canvas` | Visual Obsidian canvas of vault content |
| `/lint` | Read-only vault health check |
| `/refine` | Interactive vault cleanup |
| `/new-project` | Spawn a project under `03 Projects/` |
| `/weekly-update` | Refresh hot.md, scan stale refs, surface open loops |
| `/pre-mortem` | Decision pre-mortem before significant commitments |
| `/typed-links` | Extract typed wikilink graph (run: `python "05 Skills/scripts/typed-links-extract.py" --vault "."`) |

## Token-budget tiers
- L0 (~200 tokens): CLAUDE.md snippet + hot.md focus
- L1 (~1-2K): full hot.md + index + recent log
- L2 (~2-5K): TLDRs of relevant pages
- L3 (~5-20K): full pages, only when L0-L2 confirm they're needed

## Two-Claude workflow
1. **Strategist Claude (terminal)** — full vault context, generates strategic responses, scrutinizes plans
2. **Executor Claude (editor/Obsidian)** — executes skills, writes files, populates the graph

Flow: skill in Editor → output → paste to Strategist → next reply → paste back to Editor.

## Customization status
- [x] Identity filled
- [x] Brain purpose filled
- [x] Communication preferences set
- [x] Active projects linked
- [x] FRIDAY-MT5 project created
- [ ] Run `/brain-setup` express to deepen if desired
- [ ] Run `/typed-links` after first real notes accumulate

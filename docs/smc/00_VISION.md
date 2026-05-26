# SMC + Agentic AI — Vision & Master Roadmap

> **Goal**: turn R-Native's genomes into per-symbol SMC specialists that read
> the chart in real time, draw their analysis directly on MT5, and improve
> themselves continuously — aligned with the Agentic AI framework
> (Foundation → Deep Learning → Gen AI → AI Agents → Agentic AI).

This is the top-level doc. Implementation specs live in:

- [`01_SMC_ALGORITHMS.md`](./01_SMC_ALGORITHMS.md) — deterministic pattern detectors
- [`02_DRAWING_BRIDGE.md`](./02_DRAWING_BRIDGE.md) — Python → MT5 chart drawing
- [`03_GENOME_INTEGRATION.md`](./03_GENOME_INTEGRATION.md) — SMC genes, signals, fitness
- [`04_AGENTIC_AI_LAYERS.md`](./04_AGENTIC_AI_LAYERS.md) — framework mapping

---

## What "done" looks like

A trader opens MT5 on their phone, sees:

1. **Live SMC zones on the chart** for every deployed symbol — bullish OBs in
   teal, bearish OBs in red, FVGs as transparent blue/orange blocks, BOS/CHoCH
   trendlines, liquidity pools as orange dashed lines, IDM as purple dots.
2. **Trade markers in context** — entry arrow + SL + TP zones rendered with
   the SMC structure that justified them.
3. **Arabic narrative label** at the entry: «دخول طويل بعد كسر سيولة + ارتداد
   OB صاعد على H1». Tap it → see the full hypothesis from `SMCNarrator`.
4. **Auto-improvement** in the background: every closed trade updates
   `combo_fitness`, every 6h a micro-GA recalibrates SMC params, every
   regression triggers `GenomeRollback`. The system gets better while sleeping.

---

## What exists today (60% of the platform)

| Capability | Status |
|---|---|
| Per-symbol GA campaigns + Hall of Fame | ✅ `genetic_engine.py`, `hall_of_fame.py` |
| 11 signal evaluators + 8 filters + 12 biases | ✅ `genome_signal.py` |
| Per-symbol gene-combo fitness tracking | ✅ `combo_fitness.py` |
| Continuous evolution daemon | ✅ `continuous_evolution.py` |
| 19 specialist agents (orchestrator-managed) | ✅ `agents/` |
| Live H1/M15/H4 snapshot pipeline | ✅ `brain_server.py` |
| MT5 EA reading brain JSON for decisions | ✅ `friday_v3/algory/r_executor.py` |
| FVG + OB raw detection | ✅ `friday_v3/algory/r_levels.py` (not wired into genome) |
| LLM strategist agent (Arabic context) | ✅ `agents/llm_strategist.py` |

## What's missing (40%, this initiative)

| Capability | Module | Phase |
|---|---|---|
| Full SMC engine (BOS, CHoCH, Sweep, IDM, OF as 1st-class) | `smc_engine.py` (NEW) | 1 |
| MT5 chart drawing bridge | `chart_drawings.py` (NEW) + `DrawingRenderer.mqh` | 1 |
| SMC genes (signals, filters, SL/TP modifiers) | `genes.py` | 2 |
| SMC signal evaluators in genome | `genome_signal.py` | 2 |
| SMC-anchored SL/TP resolver | `sl_tp_resolver.py` (NEW) | 3 |
| Per-trade SMC context in fitness | `combo_fitness.py` | 4 |
| Lane-aware lineage breeding | `hall_of_fame.py` + `continuous_evolution.py` | 5 |
| Neural SMC pattern scorer | `smc_neural.py` (NEW, CNN+LSTM) | 6 |
| Arabic SMC narrator | `agents/smc_narrator.py` (NEW) | 7 |
| Self-critic + rollback + memory | `genome_rollback.py`, `agentic_memory.py` (NEW) | 8 |

---

## Phased delivery plan

Each phase = one or more focused PRs, each fully shippable in isolation. The
existing platform keeps running through every phase — backwards-compatible
additions only.

### **Phase 0 — Bug fix + Design** (this PR — DONE)
- ✅ Fix `volatility_hunter` direction-blindness (already committed)
- ✅ Send broker-side `expiration` in `pending_orders.place_pending`
- ✅ Write four design docs in `docs/smc/`

### **Phase 1 — SMC Engine + Drawing Bridge** (PR-1)
Two modules, one MQ5 include, end-to-end smoke test:
- `smc_engine.py` implementing every detector from doc 01
- `chart_drawings.py` implementing every builder from doc 02
- `mql5_templates/DrawingRenderer.mqh` (uses `JAson.mqh`)
- Hook `_collect_drawings(symbol)` in `r_executor._write_brain_json`
- One symbol end-to-end: XAGUSDm should show OBs and FVGs on the live chart

**DoD**: open XAGUSDm chart on the user's MT5, see at least one OB rectangle
and one FVG appear within 5 seconds of EA load.

### **Phase 2 — Genome SMC DNA** (PR-2)
- `genes.py` — append 13 new flag genes + 3 cont params + repair rules
- `genome_signal.py` — register 6 SMC signal evaluators + 3 SMC filters
- `combo_fitness.py` — add `smc_combos` and `smc_contexts` buckets +
  `record_smc_trade` ingestion
- No behavior change for old genomes (flags default off)

**DoD**: random genome with `use_sig_smc_ob=True` returns BUY/SELL/NO without
crashing on a snapshot that has `smc` populated.

### **Phase 3 — SL/TP Resolver + Simulator** (PR-3)
- `sl_tp_resolver.py` — anchor SL/TP to OB/swing/liquidity
- Refactor `trade_gate.evaluate_gate` to delegate (legacy ATR = fallback)
- `ga_simulator` builds per-bar `smc` via `compute_offline` and calls resolver
- `TradeVerdict.smc_anchors` propagated for chart drawer

**DoD**: backtest a known winner genome with `sl_anchor_smc_ob=True` over
1 month of XAGUSDm and observe more trades with SL hugging OB boundaries.

### **Phase 4 — Live Snapshot Wiring** (PR-4)
- `brain_server._quick_tf_snapshot` attaches `smc` dict per TF
- Bar-aligned cache to avoid recomputation on every poll
- `/api/r/trade_gate` automatically sees SMC data

**DoD**: hit `/api/snapshot?symbol=XAGUSDm` and see `multi_tf.tfs.H1.smc`
populated with real OBs and FVGs.

### **Phase 5 — Lineage SMC Lane** (PR-5)
- `hall_of_fame.admit` classifies entries into `lane: "smc" | "classic"`
- `_load_elite_seeds` reserves half the slots for SMC lane
- `Genome.mutate` accepts `group_intensities` for boosted SMC bit-flip
- `continuous_evolution` boosts SMC mutation during cold-start (first 100 trades)

**DoD**: after 24h of `continuous_evolution`, HoF shows at least 5 genomes
in SMC lane for at least one symbol.

### **Phase 6 — Neural SMC Scorer** (PR-6)
- `smc_neural.py` — small CNN+LSTM scoring OB/FVG quality
- Training script over 1 year of historic bars
- Inference adds `nn_strength` to each `fresh_ob_*` / `fresh_fvg_*` dict
- Evaluators use `nn_strength` as vote multiplier

**DoD**: deployed `smc_neural.pt` scores >0.75 on the held-out test set;
inference latency <10ms per snapshot.

### **Phase 7 — Arabic Narrator + Self-Critic** (PR-7)
- `agents/smc_narrator.py` — LLM-powered Arabic explanation per trade
- `agents/smc_self_critic.py` — post-trade SMC context analysis
- `prompts/smc/` templates
- Hallucination guard (level cross-check)

**DoD**: every entry on XAGUSDm gets a narrator label visible on MT5 within 3s.

### **Phase 8 — Agentic Governance** (PR-8)
- `genome_rollback.py` — auto-revert on regression
- `agent_governance.py` — hard guardrails (max trades/hour, cooling-off)
- `agentic_memory.py` — long-term lessons.json per symbol
- `observability/trace.py` — per-decision replayable trace

**DoD**: deliberately deploy a known-bad genome; rollback fires within 10
trades and reverts to previous deployed.

---

## Maturity ladder

| Milestone | Phases needed | What the user observes |
|---|---|---|
| M1 — SMC visible | 1 | OBs, FVGs, BOS, CHoCH drawn live on MT5 charts |
| M2 — SMC trades | 1+2+3+4 | Genome enters using SMC + SL hugs OB on chart |
| M3 — SMC specializes | +5 | Per-symbol HoF shows dominant SMC lane |
| M4 — SMC narrates | +7 | Arabic explanation on every entry |
| M5 — SMC self-tunes | +6 | Neural scorer boosts only high-quality patterns |
| M6 — SMC self-critiques | +7 (full) | Lessons file grows per symbol |
| M7 — SMC governed | +8 | Rollback proven on stress test |

---

## Non-goals (explicitly out of scope)

- Tick-level order flow / footprint charts (no DOM tick stream available today)
- Option implied-vol integration (no data source wired)
- Multi-broker bridging (current design assumes single MT5 broker)
- Mobile push notifications (Telegram exists; phone app is separate project)
- Web-based chart rendering (drawings live on the MT5 client only)

---

## Risk register

| Risk | Mitigation |
|---|---|
| SMC detectors lookahead bias | `confirmed_at_idx` discipline in doc 01 |
| MT5 chart object flicker | Deterministic IDs in doc 02 |
| Old genomes crash on new snapshot | All evaluators tolerate missing `smc` key |
| SMC cold-start crowding | Lane separation + boosted exploration mutation |
| Broker rejects `ORDER_TIME_SPECIFIED` | Fallback to GTC + local cleanup retained |
| LLM hallucinated narrative | Schema validation + regenerate with strict prompt |
| Neural model overfits | Hold-out test set, online drift monitor |
| Drawing overflow on chart | `DR_MAX_OBJECTS=250` cap + LRU pruning |

---

## How this doc is used

- Each PR description references the relevant phase and the section in the
  corresponding sub-doc.
- Changes to schemas or contracts must update the relevant sub-doc in the
  same PR.
- Phases can ship out of order if their dependencies are met (e.g. Phase 2
  doesn't need Phase 1 to land — only `smc_engine.compute_offline` is needed
  for the simulator).

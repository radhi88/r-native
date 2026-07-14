# Phase A — R Native 2 Hub Integration: Analysis & Map

> **Status:** Analysis only — NO code modified. Awaiting user review before Phase B/C.
> **Date:** 2026-06-06 · DEMO only · Author: VS agent (GSD)
> Source brief: `R_NATIVE2_HUB_INTEGRATION_TASK.md` · Coordination: `agent_bus/AGENT_BUS_PROTOCOL.md`

---

## 1. Scope surveyed

~805 Python files / ~237k LOC across 8 folders:

| Folder | Py files | LOC | Own git repo? | Tracked in parent MT5? | Role |
|--------|---------:|----:|---------------|------------------------|------|
| **r_native_v2** (target hub) | 123 | 29.7k | no | YES (307 files) | The "Palace" v2 — designed-from-scratch |
| r_native (v1) | 220 | 57.0k | **YES (nested)** | no (embedded gitlink) | Original R Native — reactive, 31 agents |
| r-native-pipflow | 152 | 41.9k | **YES (nested)** | no (embedded gitlink) | Near-fork of r_native |
| mark_xxxix | 48 | 30.3k | **YES (nested)** | no (embedded gitlink) | Separate system |
| plutobrain | 3 | 0.7k | **YES (nested)** | no (embedded gitlink) | Knowledge OS (small) |
| friday_v3 | 26 | 7.3k | no | YES (1669 incl. assets) | Algory engine (r_executor) |
| src/mt5_ai | 153 | 50.6k | no | YES (165) | FRIDAY AI core + legacy archive snapshots |
| archive_root | 80 | 20.3k | no | YES (80) | Historical reference |

**Live engines (root MT5, all present, single-copy):** `gold_live.py` (538, scalper 99791), `coordinator.py` (116), `scalp_evolver.py` (149), `scalp_proof.py` (89), `chart_read.py` (135), `markov_regime.py` (134), `friday_decision.py` (257, 3-layer LLM), `brain_server.py` (3268), `algory_chart_dashboard.py` (2232, :8866), `friday_brain_view.py` (342, :5056), `friday_gui.py` (207), `sdk_scheduler.py` (53), `ea_monitor.py` (892). `friday_web_dashboard.py` lives under `scripts/` (54 py there).

---

## 2. R Native 2 internal map ("The Palace")

**Philosophy** (`docs/PALACE_MANIFESTO.md`): a *designed* replacement for v1. Core principles: **Council not orchestra** (5 named experts vote, single veto blocks), **MTF confluence required** (M15 trend + M5 setup + M1 trigger), **session-aware**, **genome = persona with a thesis**, **paper-trade 50+ before live**.

**Actual package layout (grown well beyond the manifesto's clean skeleton):**

```
r_native_v2/
├── council/        architect · quant · risk · executor · reviewer · types   (5-expert vote)
├── agents/         council_logger · live_journal · thesis_validator
├── genomes/        claude_apex (+ persona classes)
├── indicators/     mtf_engine (212) · session
├── runtime/        ← the bulk (29.7k LOC center of mass)
│   ├── unified_trader.py (1290)        ← main runtime loop
│   ├── chart_signal_writer.py (999)    ← signal output
│   ├── gold_htf_trend/overlay/backtest ← gold HTF engine family
│   ├── cot_*.py (walkforward/ob/3way)  ← COT (commitments of traders) engine
│   ├── genome_* (academy/evolver/birth/promoter/walkforward) ← evolution
│   ├── claude_*_trader.py (autonomous/genome/smart/simple) ← LLM trader variants
│   ├── footprint_* · ml_* · palace_council · regime_classifier · supervisor · services
│   ├── shared/     contracts · db · circuit_breaker · cost_model · decision_log ·
│   │               order_blocks · risk_sentinel · cot_* · structure_entry · fvg_pending
│   └── runtime/    ⚠ SELF-MIRROR of parent runtime/ (see Dup #1)
├── docs/           PALACE_MANIFESTO · USER_EDGE_BOOK
├── data/           heavy live state (genomes, brain_live__*.json per symbol, gold_live.*)
└── agent_bus/      ASK/REPLY channel (currently empty)
```

- **Entry points:** ~40 `__main__` modules (every trader/genome/backtest is independently runnable). No single front-door yet — this is the gap the "one request interface" (req #4) must fill.
- **No HTTP servers inside r_native_v2** — dashboards/servers live in parent MT5 (algory_chart_dashboard :8866, friday_brain_view :5056, ea_monitor :7799).
- **Weaknesses observed:** (a) internal self-duplication (runtime/runtime); (b) ~40 independent entrypoints, no unified hub/CLI; (c) heavy JSON state in `data/` mixed with per-symbol files (migrate_jsonl_to_sqlite.py exists → mid-migration to SQLite); (d) manifesto skeleton ≠ actual sprawl.

---

## 3. Duplication inventory (the core of Phase A)

### Dup #1 — The Palace exists 3–4 times (HIGH severity)
`live_pulse.py` is **byte-identical (md5 `1c9b2d37…`)** at:
- `r_native_v2/runtime/live_pulse.py`
- `r_native_v2/runtime/runtime/live_pulse.py`  ← internal self-mirror
- `r_native/v2/runtime/live_pulse.py`  ← a **stale, smaller (77 py vs 123) copy of the whole palace nested inside v1**
- `r_native/v2/runtime/runtime/live_pulse.py`

Same pattern for `paper_trader` (247), `footprint_publisher` (221), `chart_publisher` (471), `decision_log` (230), `health_monitor` (141), `risk_sentinel` (133).
➡ **Canonical = top-level `r_native_v2/`.** `r_native/v2/` and `r_native_v2/runtime/runtime/` are redundant snapshots to delete after diffing.

### Dup #2 — r_native ↔ r-native-pipflow are near-forks (HIGH)
Identical top-level dir structure (agents, assets, build_scripts, dashboard, docs, friday_v3, launcher_module, mql5_templates, scripts, tools). **118 shared unique basenames.** pipflow adds `data/ strategies/ tests/`. Both are separate nested git repos.
➡ pipflow = a working branch of v1. Treat r_native(v1) as the reference; harvest pipflow's *unique* additions (strategies/, tests/) only.

### Dup #3 — friday_v3 / algory engine triplicated (MEDIUM)
`friday_v3/` == `r_native/friday_v3/` (identical md5 on learning_memory, r_executor ~1464). `r-native-pipflow/friday_v3/` has **diverged** (different md5; r_executor 1429). Standalone friday_v3 r_executor = 1521 (newest/biggest).
➡ Canonical = the largest/newest standalone `friday_v3/` (already parent-tracked). The two nested copies are stale/diverged forks.

### Dup #4 — engine families duplicated across agents/ (MEDIUM)
`risk_sentinel` (4×: r_native_v2/shared 141, r_native/agents 241, r_native/v2 133, pipflow/agents 192 — **diverged, not identical**), `market_scanner` (195 identical r_native↔pipflow + 103 archive), `r_executor/r_learning/r_levels/r_training/r_multi_symbol` (3× each across r_native/pipflow/friday_v3).
➡ These diverged — needs content diff to pick the canonical, not blind dedup.

### Dup #5 — src/mt5_ai legacy archive snapshots (LOW)
`ict_sweep_trader` etc. duplicated under `src/mt5_ai/archive/legacy_executors_disabled_*` and `original_snapshot_*` — historical, already quarantined. Leave as-is (reference).

---

## 4. Commit / safety topology (critical for Phase C)

- **r_native_v2 IS tracked in the parent MT5 repo** (307 files) → hub integration commits land in the **parent** repo. Good — no nested-repo gymnastics for the target.
- **r_native, r-native-pipflow, mark_xxxix, plutobrain are nested git repos NOT tracked by parent** (embedded gitlinks, 1 entry each). To integrate their code: **copy OUT** of them into r_native_v2 (do not move; preserve originals as reference per AGENT_BUS rule "انسخ لا تنقل").
- This mirrors the OpenJarvis pattern seen earlier (nested gitignored repos).
- **Live-trading hazard:** `gold_live.py` (root, 99791) + `coordinator.py` + `scalp_proof.py` + `sdk_scheduler.py` are running. r_native_v2/data has `gold_live.lock/.out/state` → r_native_v2 runtime ALSO manages a gold engine. Any consolidation of the gold path must keep the live scalper working or replace-after-test. Never touch `magic 0`.

---

## 5. Proposed integration plan (for your approval — nothing executed yet)

**Guiding model:** r_native_v2 stays the hub. Integration = *converge duplicates into canonical modules inside r_native_v2*, then *bridge the live engines + brain + dashboards through one front door*, then *add self-update + "update pending" notification*. Every merge step is atomic, reversible, and gated through the agent_bus (ASK→REPLY) before execution.

| Step | What | Risk | Gate |
|------|------|------|------|
| **B0** | De-dup the Palace: diff & delete `runtime/runtime/` self-mirror and stale `r_native/v2/` (after confirming r_native_v2 is the superset). Pure cleanup, no behavior change. | Low | ASK before delete |
| **B1** | Define the **Hub contract**: one entry module (`r_native_v2/hub.py`) + a unified request interface (CLI/queue) routing to council/genomes/traders/brain. Design doc only. | Low | ASK (design review) |
| **C1** | Converge friday_v3/algory → canonical under r_native_v2 (copy newest, wrap try/except, isolated, not wired to live yet). | Med | ASK + isolated test |
| **C2** | Converge diverged engine families (risk_sentinel/r_executor/etc.) — content-diff each, pick canonical, adapter-shim the rest. | Med | ASK per family |
| **C3** | Bridge live engines (gold_live/coordinator/chart_read/markov/friday_decision) into the hub as registered services — **keep them running**, hub observes/controls, no rewrite. | **High** | ASK + parallel-run proof before any cutover |
| **C4** | Bridge brain (brain_server/plutobrain Knowledge OS) + dashboards as hub-attached views. | Med | ASK |
| **D1** | Self-improvement loop (reuse existing reflection/genome evolution) wired to the hub. | Med | ASK + honest gate |
| **D2** | "Update pending" mechanism: `UPDATE_PENDING.md` writer + notify + approve-to-launch + `CHANGELOG.md`. | Low | ASK |

**Honesty rule:** every C/D step that claims an edge gets a real OOS/parallel-run gate; negatives recorded (per `memory/project_real_edge_discipline.md` — the only proven edge is discipline).

---

## 6. Open questions for you / the other Claude (before Phase B)

1. **Hub front-door form** — CLI? a small local HTTP service? reuse an existing dashboard (algory_chart_dashboard :8866 / brain_server)? or a queue/file interface like agent_bus?
2. **r_native(v1) fate** — archive entirely once v2 absorbs the useful parts, or keep v1 live until v2 paper-proves (manifesto says paper-trade 50+ first)?
3. **mark_xxxix** — what is it, and is it in scope to absorb or leave standalone? (48 files / 30k LOC, separate repo — needs a closer look in B.)
4. **Live gold path** — is the canonical live scalper `root/gold_live.py` or `r_native_v2/runtime` gold_htf_*? They appear to overlap.
5. **Delete vs keep** stale mirrors (`r_native/v2`, `runtime/runtime/`) — confirm OK to remove after diff.

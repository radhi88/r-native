# F1 — R Native Autonomy Map (read-only analysis)

> **Status:** ANALYSIS ONLY — no engine touched; r_native (v1, dirty, 3rd session) not modified.
> Goal: map how R Native v2 runs, creates genes, and what it tests — vs the user's vision
> ("enter ANY market it sees · create genes · test ALL markets multi-TF/multi-bar"). Date 2026-06-06.

## 1. Live engine — 12 v2 services (`runtime/services.py` registry; bootstrapped via app.py, PAPER)
| # | Service | Category | Role (writes) |
|---|---------|----------|---------------|
| 1 | brain_v1 | CAPTURE | snapshot MT5 + decide every 2s → brain_live.json |
| 2 | regime_classifier | ANALYSIS | TREND/CHOP/SPIKE every 5s → market_regime |
| 3 | performance_coordinator | ANALYSIS | per-genome/perf coordination |
| 4 | trader_orchestrator | DECISION | routes which trader/genome acts |
| 5 | palace_council | DECISION | 5-expert vote (architect/quant/risk/executor/reviewer) |
| 6 | claude_genome_trader | EXECUTION | trades the active genome (PAPER) |
| 7 | claude_smart_trader | EXECUTION | smart-trader variant |
| 8 | claude_simple_trader | EXECUTION | simple-trader variant |
| 9 | genome_evolver | EVOLUTION | mutate genome library on fitness |
| 10 | genome_promoter | EVOLUTION | promote winners → live_genome__<SYM>.json |
| 11 | live_dashboard | INFRASTRUCTURE | local view |
| 12 | health_monitor | INFRASTRUCTURE | service liveness |

`system_manifest.py` also lists optional/advisory components (e.g. `market_scanner` — ADVISORY, OPTIONAL).
Executor is **PAPER** (not live order_send). Live order_send is the separate gold_live(99791)/btc_live(99792).

## 2. Gene-creation pipeline
```
winning context (brain_decisions/genome_signals, MTF aligns)
   │  genome_birth.py  → derive a genome from what actually won (requires MTF agreement seen in wins)
   ▼
genomes_population.json (GA pool)
   │  genome_evolver.py → mutate params on genome_fitness.json (ranges, e.g. min_mtf_agreement 1..4)
   ▼
genome_academy.py  → GAUNTLET: backtest every genome on real MT5 bars across SYMBOLS
   │  (random_genome + crossover; genes: rsi_max, min_pressure_abs, min_mtf_agreement, sl_pts, tp_pts…)
   ▼
genome_promoter.py → promote champion → live_genome__<SYMBOL>.json  (per-symbol persona, live)
   +  multi_symbol_champions.py → per-symbol top-3 modules PER TIMEFRAME (meta_favored_modules)
```
So genes ARE created from real outcomes + evolved + gauntlet-tested + promoted per symbol. Solid core.

## 3. What it tests now — symbol/TF/bar coverage
- **Symbols (HARDCODED, and INCONSISTENT across files):**
  - `genome_academy.SYMBOLS` = XAUUSDm, EURUSDm, GBPUSDm, GBPJPYm, BTCUSDm, USDJPYm, XAGUSDm (7)
  - `brain_v1.SYMBOLS` = XAUUSDm, EURUSDm, GBPUSDm, USDJPYm, … (own list)
  - `chart_signal_writer.DEFAULT_SYMBOLS` = XAUUSDm, BTCUSDm, EURUSDm, GBPUSDm, XAGUSDm (5)
  - `footprint_feeder.SYMBOLS` = XAUUSDm, XAGUSDm, BTCUSDm, EURUSDm, GBPUSDm, USDJPYm (6)
  - live personas exist for 11 (adds AUD/NZD/CAD/CHF/EURJPY) — but academy only gauntlets 7.
- **Timeframes:** MTF is encoded as `min_mtf_agreement` (1–4 aligned TFs) + `multi_symbol_champions` favors modules per-TF. There is **no systematic per-TF gauntlet** (genomes aren't scored TF-by-TF in academy).
- **Bars:** fixed lookbacks per engine; **no multi-seq-length / multi-horizon sweep**.

## 4. Gaps vs the user's vision
| # | Gap | Evidence | Impact |
|---|-----|----------|--------|
| G1 | **No single symbol universe** — 4+ hardcoded, divergent lists | §3 | adding a market = editing many files; drift |
| G2 | **No dynamic market discovery** — does NOT "enter any market it sees" | no `symbols_get`→auto-add; market_scanner is ADVISORY/OPTIONAL, not wired to spawn personas | can't auto-onboard new broker symbols |
| G3 | **multi-TF/multi-bar not systematic** | academy gauntlets symbols, not TF×bar grid | "test all markets multi-TF/multi-bar" unmet |
| G4 | **MT5-only** | adapters absent (see E2) | no crypto-venue/Polymarket |
| G5 | **session flags per-genome, error-prone** | INT-01 (EUR session_filter=[] ⇒ wrong 24/7) | weekend-trade risk on FX if trusted |

## 5. Proposed path (F2/F3 — DESIGN, gated; no code now)
1. **F2-a (single source of truth):** one `symbol_universe.json` (or hub intent) feeding ALL engines;
   eliminate the 4 divergent lists. Read-only design first; migration parallel-run.
2. **F2-b (dynamic discovery):** promote `market_scanner` to discover broker symbols
   (`mt5.symbols_get`, filtered by spread/liquidity/tradability) → propose additions to the universe →
   **user/hub-gated** auto-spawn of a per-symbol persona (genome_birth seed). "Enter any market it sees"
   but **gated**, not blind.
3. **F3 (multi-TF/multi-bar gauntlet):** extend genome_academy to score each genome across a TF×seq_len
   grid (e.g. M1/M5/M15 × {64,128,200}); record per-TF fitness; promote per-(symbol,TF).
4. **Honesty gate:** every newly-onboarded symbol/TF must clear OOS before live use (Phase-9 ethos);
   non-clearing stays advisory. Crypto 24/7 first (E2). The hub surfaces the universe + per-symbol gauntlet
   status (read-only) so the user SEES it.

## 6. Coordination / safety
- r_native (v1) is dirty (3rd session) — **not touched**; this is read-only analysis of r_native_v2.
- Any F2/F3 implementation touches live evolution engines → agent_bus ASK + parallel-run before cutover.
- PAPER stays PAPER; live order_send remains gold_live(99791)/btc_live(99792) only; never `magic 0`.

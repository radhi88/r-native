# MQL5 Integration Report (E1) — read-only analysis

> **Status:** ANALYSIS ONLY — no `.mq5` touched (FRIDAY_Brain_Executor.mq5 is owned by a third
> session). Proposes a wiring contract for review; no code/contract committed beyond this doc.
> **Date:** 2026-06-06 · DEMO · author: VS agent (agent_bus E1).

---

## 1. Components found (read-only)

| File | LOC | Magic | Role |
|------|----:|-------|------|
| `r_native/v2/mql5_experts/FRIDAY_Brain_Executor.mq5` | 830 | **20260600** | EA — executes brain orders, draws levels/trade-box. ⚠ being edited by 3rd session. |
| `ea_backups/FRIDAY_Brain_Executor_*.mq5` | 750–785 | 20260600 | older snapshots (reference) |
| `active_ea/CLAUDE_BRAIN_EA_v1.mq5`, `CLAUDE_FOOTPRINT_v*.mq5` | 1.1–1.4k | — | other EAs (self-contained tester EAs) |
| `CLAUDE_SIGNAL.mq5` (indicator) | — | — | **NOT in repo** — likely in the MT5 terminal `MQL5/Indicators/` or being authored by the 3rd session. Reads `signal_<SYMBOL>.json` to draw the brain's read (see §3). Needs confirmation. |

> Note: `gold_live.py` scalper is **Magic 99791** — a *separate* path, not this EA. The EA here is the
> FRIDAY **Brain** executor (20260600).

## 2. Live integration topology (two distinct paths)

```
            ┌─────────────────────────── EXECUTION PATH (Magic 20260600) ───────────────────────────┐
 brain (friday_brain.py / friday_v3 r_executor.py / r_native/app.py)
        │ writes  <Common>/Files/friday_brain_orders.json   {epoch, decision:{side,sl,tp,lot}}
        ▼
 FRIDAY_Brain_Executor.mq5  ── reads every InpCheckEverySeconds(3s), ignores if epoch age > 60s
        │  GATE: son_status.json {p_win, side}  (written/mirrored by r_native_v2 unified_trader.py)
        │        → trade allowed only if p_win ≥ InpSonMinPwin(0.50); else veto (ML_BLOCK/WAITING/FROZEN), fail-open if absent/stale(>45s)
        │  GATE: kill_switch.txt  · night block (server 22→08) · risk caps (MaxLot .05, MaxOpen 4, spread, RequireSL)
        ▼  order_send (the ONLY MT5 order path for magic 20260600)

            ┌─────────────────────────── VISUAL / SIGNAL PATH ───────────────────────────┐
 r_native_v2/runtime/chart_signal_writer.py  (REVERSE bridge: brain read → on-chart)
        │ writes  <Common>/Files/signal_<SYMBOL>.json   (rich schema, see §3)
        ▼
 CLAUDE_SIGNAL indicator (on each symbol chart)  → draws BUY/SELL/WAIT, zones, regime, footprint
```

Other writers seen for these files: `unified_signal_bridge.py`, `brain_server.py`, `signal_executor.py`,
`shared/brain_signal.py`, `manual_copilot.py` — convergence candidate (one canonical writer) for a later phase.

## 3. The per-symbol signal contract ALREADY EXISTS (key for E2)
Live in `<Common>/Files/`: `signal_XAUUSDm.json`, `signal_BTCUSDm.json`, `signal_EURUSDm.json`,
`signal_GBPUSDm.json`, `signal_XAGUSDm.json` — i.e. the **multi-market substrate is already in place**.
Schema (from live `signal_XAUUSDm.json`, `chart_signal_writer.py`):
```
schema_version, source:"r_native_brain", symbol, ts, tf, action(BUY/SELL/WAIT),
confidence, label(ar), dominant(LONG/SHORT), bullish, bearish, price, zones[],
reason(ar), spread, spread_quality, regime{adx,er,no_trend,htf_dir},
footprint_signal, cvd_norm, tape_norm, wick, velocity, vwap, imb
```
Execution still uses the single `friday_brain_orders.json` (one active symbol); the rich per-symbol
files currently feed the **chart/indicator** view.

## 3b. CLAUDE_SIGNAL.mq5 (indicator) — analyzed (read-only)
Location: `…\Terminal\53785E099C927DB68A545C249CDBCE06\MQL5\Indicators\CLAUDE_SIGNAL.mq5`
(17976 B, modified 2026-06-04). **Read-only — not edited** (3rd session may own it).
- `#property indicator_chart_window`, `indicator_plots 0` — pure drawing overlay, **no orders, no buffers**.
- **Reads `signal_<SYMBOL>.json`** (the chart's own symbol; written by `chart_signal_writer.py`),
  `InpMaxAgeSec=120` (ignores stale), redraw `InpRefreshMs=400`.
- Draws: (1) a comprehensive panel — action/conf/score/pillars/STOCH/regime/HTF/FADE/all 11
  components/reason; (2) a BUY/SELL arrow on the candle; (3) SMC supply/demand zone rectangles.
- Object prefix `CLSIG_`. Confirms §2 "visual path": it is the on-chart renderer of the brain's
  per-symbol read. **No execution coupling** — display only.

➡ Resolves open question #1. The visual contract = `chart_signal_writer.py` → `signal_<SYMBOL>.json`
→ `CLAUDE_SIGNAL.mq5`. The executor (`FRIDAY_Brain_Executor`, 20260600) is a separate path (§2).

## 4. Hub wiring points (proposed — NOT implemented)
1. **Read-only first (safe, fits current hub):** extend hub `GET /state` to also surface
   `<Common>/Files/` signals: `friday_brain_orders.json`, `son_status.json`, `kill_switch.txt`, and the
   per-symbol `signal_*.json`. Gives one place to see every chart's brain read + the EA gate — zero risk,
   no `.mq5` change.
2. **Canonical signal writer (later, C-phase):** converge the ~6 writers of `signal_*.json` into one,
   behind the hub, so each symbol has exactly one authoritative producer.
3. **Per-chart EA contract (E2):** standardize each symbol chart's EA to read its own
   `signal_<SYMBOL>.json` (+ a per-symbol `brain_orders_<SYMBOL>.json` if we move execution multi-symbol),
   gated by a per-symbol son verdict. The naming convention already exists — E2 formalizes it.
4. **Kill switch via hub (state-changing → C3 + secret):** a `trade.halt` intent could write
   `kill_switch.txt`. NOT now (read-only phase); requires the shared-secret + parallel-run gate.

## 5. Proposed wiring contract (for Claude's review — no code yet)
- **Producer:** `chart_signal_writer.py` (canonical) → `signal_<SYMBOL>.json` per symbol (existing schema).
- **Indicator (`CLAUDE_SIGNAL`):** reads `signal_<SYMBOL>.json` for the chart's symbol → draws action/zones/regime. Pure display, no orders.
- **Executor (`FRIDAY_Brain_Executor`, 20260600):** reads `friday_brain_orders.json` (today) → later optional `brain_orders_<SYMBOL>.json`; gated by `son_status.json`(+ per-symbol later), `kill_switch.txt`, night block, risk caps. Unchanged for now.
- **Hub:** observes all of the above read-only (§4.1); becomes the control point in C3+ (kill/activate per symbol) behind the secret + parallel-run gate.

## 6. Open questions for Claude
1. **`CLAUDE_SIGNAL.mq5` location/owner** — is it in the terminal `MQL5/Indicators/` or being authored by the 3rd session? I could not find it in the repo. Confirm so I analyze the real indicator (read-only).
2. Approve **hub §4.1 read-only Common/Files surfacing** as the next concrete step (extends `/state`, zero `.mq5` touch)?
3. For **E2**, adopt the existing `signal_<SYMBOL>.json` convention as the canonical per-symbol contract (and add `brain_orders_<SYMBOL>.json` for multi-symbol execution later)?
4. Should the ~6 `signal_*.json` writers be converged to one canonical (`chart_signal_writer.py`) in a later C-phase?

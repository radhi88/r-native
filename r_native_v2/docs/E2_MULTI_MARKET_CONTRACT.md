# E2 — Multi-Market Contract (design only)

> **Status:** DESIGN ONLY — no code. Builds on the already-live `signal_<SYMBOL>.json` substrate (E1).
> **Rails:** DEMO · hub advisory/read-only until C3 · MT5 orders stay with gold_live(99791)/Brain-EA(20260600)
> · never `magic 0` · honesty gate per market (no fake edge). · Date 2026-06-06.

## 1. Principle
The hub controls **every market**, not gold/MT5 only. `market` + `symbol` are first-class params on
every intent. Each symbol carries its own persona (genome/strategy/behavior). Execution backends differ
per market behind a `MarketAdapter`; the **intent contract stays stable**.

## 2. Canonical per-symbol contract (ADOPTED — already live)
**`<Common>/Files/signal_<SYMBOL>.json`** is the canonical per-symbol signal (written by
`chart_signal_writer.py`, drawn by `CLAUDE_SIGNAL.mq5`). Schema (live today):
`schema_version, source, symbol, ts, tf, action(BUY/SELL/WAIT), confidence, label, dominant,
bullish, bearish, price, zones[], reason, spread, spread_quality, regime{adx,er,no_trend,htf_dir},
footprint_signal, cvd_norm, tape_norm, wick, velocity, vwap, imb`.
Already present for XAUUSDm, BTCUSDm, EURUSDm, GBPUSDm, XAGUSDm → **multi-market substrate exists.**

**Future (later, gated):**
- `brain_orders_<SYMBOL>.json` — per-symbol execution (today a single `friday_brain_orders.json`).
- `son_status_<SYMBOL>.json` — per-symbol P(win) gate (today a single `son_status.json`).
- `kill_switch_<SYMBOL>.txt` — per-symbol halt (today a single global `kill_switch.txt`, currently HALT).

## 3. Market classes & sessions
| Market | Symbols | Session rule | Execution backend |
|--------|---------|--------------|-------------------|
| MT5-FX/metals | EURUSDm, GBPUSDm, XAUUSDm, XAGUSDm | session windows (London/NY overlap; night-block per discipline) | Brain EA 20260600 / gold_live 99791 |
| MT5-crypto | **BTCUSDm (LIVE now via btc_live magic 99792)**, ETHUSDm | **24/7 incl. weekends** — session gate must NOT block crypto | btc_live.py direct order_send (99792) |
| Prediction mkts (future) | Polymarket events | event-driven, 24/7 | `PolymarketAdapter` (isolated) |

**24/7 handling:** the session-window logic (Asian=M15-only, outside=no-trade) is FX-centric. Crypto
symbols must be flagged `always_open=true` so the gate allows weekend trading. This is the first concrete
multi-market behavior change (design; implement under E2-exec later, gated).

## 4. Per-symbol persona (ties to genomes/)
Each symbol → its own genome/strategy/behavior record (the project already has per-symbol
`live_genome__<SYMBOL>.json` + `brain_live__<SYMBOL>.json` in `r_native_v2/data/`). E2 formalizes:
`persona(symbol) = {genome, strategy, risk_profile, session_rule, market}`. The hub's `decide`
intent resolves the persona by `{market,symbol}`.

## 5. Hub intent shape (extends HUB_CONTRACT §6b)
```
POST /request {intent:"decide",  market:"MT5", symbol:"BTCUSDm"}
POST /request {intent:"status",  market:"MT5", symbol:"XAUUSDm"}
POST /request {intent:"regime",  market:"MT5", symbol:"EURUSDm"}
POST /request {intent:"trade.halt", market:"MT5", symbol:"BTCUSDm"}   # C3 + secret + parallel-run
```
`GET /state` already returns all per-symbol `signal_*.json` (read-only, shipped in 33c8acc).

## 6. MarketAdapter interface (future — placeholder, no code)
```
class MarketAdapter:           # one per market backend
    def read_signal(symbol) -> dict        # -> canonical signal schema
    def decide(symbol, persona) -> dict     # advisory decision
    def positions(symbol) -> list           # read-only
    def halt(symbol) / resume(symbol)       # state-changing -> C3 gated
    # execute(...) -> ONLY MT5Adapter wires to the protected EA/gold_live; others isolated+gated
```
- `MT5Adapter`: maps to existing direct-path scalpers — gold_live(99791, XAU), btc_live(99792, BTC) —
  plus the Brain-EA(20260600) JSON-bridge path. NOTE: gold_live/btc_live are NOT gated by the Brain-EA
  kill_switch (direct order_send); only Brain-EA(20260600) is. Never `magic 0`.
- `CryptoAdapter`: MT5-crypto symbols with `always_open` (btc_live already implements this for 99792).
- `PolymarketAdapter` (future): isolated, separately gated; NOT MT5.

## 7. Rollout (each step its own agent_bus ASK + honest gate)
1. **E2-a (read-only, safe):** hub `/state` already multi-symbol ✅. Add a per-symbol `persona` view
   (read existing `live_genome__*.json`) — read-only.
2. **E2-b (design→impl, gated):** session gate honors `always_open` for crypto (BTCUSDm 24/7) — the first
   real multi-market behavior. parallel-run vs current before any live effect.
3. **E2-c (gated, C3):** per-symbol `brain_orders_<SYMBOL>.json` + `son_status_<SYMBOL>.json` + per-symbol
   kill switch. Then `MarketAdapter` abstraction. Each with parallel-run + ASK.
4. **E2-d (future):** PolymarketAdapter (own gate, non-MT5).

## 8. Honesty gate
Per market/symbol: prove edge OOS/parallel before trusting `decide`. Record negatives (the only proven
edge is discipline — `memory/project_real_edge_discipline.md`). A symbol that doesn't clear its gate stays
advisory-only (like the regime model in Phase 9).

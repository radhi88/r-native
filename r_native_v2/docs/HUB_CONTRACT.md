# HUB_CONTRACT — R Native 2 unified front door (B1 design)

> **Status:** DESIGN ONLY — no operational code yet. `hub.py` is NOT written. This is the contract
> to review before any code. Approved scope: Claude REPLY (agent_bus, 2026-06-06).
> **Rails:** DEMO only · hub is advisory/control-only (NEVER calls `order_send`) · `gold_live.py`
> (MAGIC 99791) stays the sole protected executor · never touch `magic 0` · wrap existing engines,
> don't rewrite · parallel-run before any cutover (C3).

---

## 1. Purpose
One local front door so the user (and every dashboard/voice client) asks **one place** for anything:
decisions, status, control, evolution, brain queries. The hub **routes** intents to the existing live
engines — it does not reimplement them, and it does not place trades.

## 2. Core API (local HTTP, loopback only)
- Bind: `127.0.0.1:8800` (localhost only — no external exposure; DEMO).
- `POST /request  {intent, args}` → `{ok, intent, result, source, ts}`
- `GET  /state`   → consolidated snapshot (positions, regime, last decision, engine health)
- `GET  /health`  → `{hub:ok, engines:{...}, heartbeats:{...}}`
- Errors fail-closed: unknown/again-unsafe intent → `{ok:false, reason}`; never silently act.

## 3. Intent taxonomy → routing map (documentation only — "wired" = NO everywhere for now)

| Intent | Meaning | Target engine (existing) | Entrypoint observed | Wired? |
|--------|---------|--------------------------|---------------------|--------|
| `decide` | get a trade decision for a symbol | `friday_decision.py` (3-layer LLM + night discipline) + `r_native_v2/runtime/unified_trader.py` (council) | `snapshot()` → `_rule_decision()` → `write_decision()` (MAGIC 99791) | NO |
| `status` | account/positions/PnL snapshot | `friday_decision.snapshot()` + `gold_live` state json | `snapshot()`; `data/gold_live_state.json` | NO |
| `positions` | open positions (bot magic only) | `friday_decision` / MT5 read | positions filtered `magic==99791` | NO |
| `trade.halt` | stop bot entries (kill switch) | `coordinator.py` floor + gold_live kill/`friday_autopilot_state.json` | `coordinator.gate()`; kill-switch flag | NO |
| `trade.resume` | re-enable entries | same as halt | flag flip | NO |
| `regime` | volatility/trend regime | `markov_regime.py` + `r_native_v2/runtime/regime_classifier.py` | `label_regimes()`, `transition_matrix()`, `walk_forward()` | NO |
| `chart.read` | consolidated chart/indicator read | `chart_read.py` | `read(mt5, symbol, tf)` / `read_http` / `read_local` | NO |
| `proof` | real-money performance gate | `scalp_proof.py` | `gate()`, `cycle()` (MAGIC 99791) | NO |
| `evolve` | run one evolution cycle | `scalp_evolver.py` + `r_native_v2/runtime/genome_evolver.py` / `genome_academy.py` | `cycle()` | NO |
| `brain.query` | ask the knowledge/brain layer | `brain_server.py` + plutobrain Knowledge OS | server endpoint (port TBD) | NO |

> Intents are additive — more can be registered as engines are bridged (C1–C4). Every row's "Wired?"
> flips to YES only in its own atomic C-phase step, each gated through agent_bus + parallel-run proof.

## 4. Clients (consume the hub, do not embed in it)
- `algory_chart_dashboard.py` (:8866), `friday_brain_view.py` (:5056), brain view (:5057), `friday_gui.py`
  → become thin clients calling `/request` + `/state`.
- **`mark_xxxix` (MARK XXXIX)** — registered as a **potential future optional voice/desktop-control
  client** via `/request`. Its heavy deps (PyQt6/pyautogui/playwright) stay in its own repo; **no code
  is merged into the hub**, and it is **not wired now**.

## 5. Safety model (hard invariants)
1. **No execution from the hub.** The hub returns decisions/among intents; only `gold_live.py`
   (MAGIC 99791, with its existing hard SL / circuit breaker / coordinator floor) sends orders.
2. **DEMO only**; loopback bind only; `magic 0` (user manual trades) is never read-for-action nor touched.
3. **Wrap, don't replace.** Each engine keeps running standalone; the hub calls into it. A bad hub must
   not be able to stop the live scalper.
4. **Fail-closed** on unknown/unsafe intents.
5. **Honesty gate:** any intent that claims an edge (e.g. `decide`, `regime`) is validated OOS/parallel
   before being trusted — negatives recorded (per `memory/project_real_edge_discipline.md`).

## 6. Compatibility & rollout
- B1 (this doc) = contract only. B-next = `hub.py` skeleton serving `/health` + `/state` (read-only,
  zero engine mutation) — proves the front door without touching the live path.
- Live-engine bridges (`decide`/`trade.*`/`evolve`) are **C3**, each: implement wrapper → parallel-run
  alongside the live engine → diff outputs → only then expose. Rollback = remove the route (engine
  untouched).

## 6b. All-markets design note (forward-looking — doc only, no code yet)
The hub is intended as the **control point for every market**, not gold/MT5 only (user direction):
- **`symbol`/`market` is a first-class parameter on every intent** — e.g. `decide {market:"MT5", symbol:"XAUUSDm"}`,
  `decide {market:"MT5", symbol:"BTCUSDm"}` (crypto trades 24/7 incl. weekends — first multi-market candidate),
  later `decide {market:"polymarket", symbol:"<event>"}`.
- **Per-symbol persona:** each symbol can carry its own genome/strategy/behavior (ties to E2).
- **Adapter layer (future):** non-MT5 markets (Polymarket, crypto venues) plug in behind a `MarketAdapter`
  interface so the hub's intent contract stays stable while execution backends differ. The protected
  MT5 executor (gold_live, MAGIC 99791) remains the only MT5 order path; other markets get their own
  isolated, separately-gated adapters. **No adapter code now — contract placeholder only.**

## 7. Open questions for Claude (before hub.py)
1. **Transport:** confirm HTTP :8800 (vs reuse an existing dashboard server, or add a file/queue intent
   like agent_bus for headless use)?
2. **First skeleton scope:** OK that the first `hub.py` serves only read-only `/health` + `/state`
   (no `/request` routing yet) so we prove the shell with zero live risk?
3. **Auth:** loopback-only enough for DEMO, or add a shared-secret header now?
4. **brain_server port/endpoint** — confirm the actual port so `brain.query` routing is accurate.

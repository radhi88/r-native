# C3 — `POST /request` activation contract (DESIGN ONLY)

> **Status:** DESIGN ONLY — no code. `POST /request` stays 405 until this is approved + parallel-run.
> **Rails:** DEMO · hub imports NO MetaTrader5 · NO order_send from hub · never `magic 0` ·
> read-only whitelist FIRST; state-changing intents are a later, separately-gated sub-step.
> Date 2026-06-06.

## 1. Scope of this contract
Turn the currently-disabled `POST /request` into a **read-only-whitelisted** router. It exposes the
same data the hub already reads (files), now addressable by intent — still zero execution, still MT5-free.
State-changing intents (`trade.halt/resume`) are specified here but **remain disabled** until C3-b.

## 2. Auth (new — required before any /request)
- A shared secret in `.env` (e.g. `HUB_SECRET=...`), read at hub start (utf-8-sig — repo .env has BOM).
- Every `POST /request` MUST send header `X-Hub-Secret: <value>`; mismatch → `401`, fail-closed.
- `.env` is gitignored (never committed). Loopback bind remains (defense in depth).
- `GET /health`, `/state` stay open on loopback (read-only, no secret) — unchanged.

## 3. Read-only intent whitelist (C3-a — the only intents enabled first)
| intent | args | returns | backing (existing, file/already-built) |
|--------|------|---------|----------------------------------------|
| `status` | `{market?,symbol?}` | account/engine snapshot | build_state() subset |
| `positions` | `{magic?}` | open positions view | from live_traders + (later) state files — NO MT5 call |
| `pnl` | `{magic?}` | per-magic PnL | build_pnl() (scalp_proof.json / btc_state.json) |
| `persona` | `{symbol}` | symbol genome | build_personas()[symbol] |
| `regime` | `{symbol}` | regime read | signal_<symbol>.json.regime (read) |
| `signal` | `{symbol}` | latest chart signal | signal_<symbol>.json (read) |
| `decide` (read) | `{market,symbol}` | latest decision (NOT a new order) | sdk_decision.json / signal file — **read of existing decision only** |

Unknown intent → `{ok:false, reason:"not in read-only whitelist"}` (fail-closed). No intent in C3-a
mutates anything or calls MT5.

## 4. State-changing intents (C3-b — SPECIFIED, DISABLED until separately gated)
| intent | effect | gate before enabling |
|--------|--------|----------------------|
| `trade.halt` | write `kill_switch.txt` / per-symbol kill | secret + explicit user OK + parallel-run; **Brain-EA kill is already HALT** |
| `trade.resume` | clear kill | explicit user instruction ONLY (matches the 2026-05-27 HALT note) |
| `evolve` | trigger one evolution cycle | secret + parallel-run |
Each C3-b intent ships in its own atomic step with its own ASK. None are part of C3-a.

## 5. Hard invariants (unchanged)
- Hub NEVER imports MetaTrader5, NEVER calls order_send. Execution stays with gold_live(99791)/
  btc_live(99792) direct paths and Brain-EA(20260600).
- `magic 0` (manual) is never acted on.
- Fail-closed everywhere; loopback; secret on every mutating-or-not /request.

## 6. Rollout
1. **C3-a:** implement `POST /request` with the read-only whitelist + secret. parallel-run: confirm each
   intent returns the same data as the equivalent `/state` slice. ASK before enabling.
2. **C3-b:** per-intent, much later, only with explicit user authorization (esp. anything touching the
   HALT kill switch). Likely never automated for `trade.resume`.

## 7. Open questions for Claude
1. Approve the C3-a read-only whitelist + `.env` `HUB_SECRET` scheme?
2. Should `decide(read)` return only the last persisted decision (safe), or is even that too much before C3-b?
3. Confirm `trade.resume` stays **manual-only forever** (never an automatable intent), given the HALT history.

# 01 — True Execution Ownership
Generated: 2026-05-13

Every direct MT5 execution call found in the codebase.

## Legend
- **OPEN** = opens a new trade
- **CLOSE** = closes an existing position
- **MODIFY_SLTP** = modifies SL/TP of open position
- **REMOVE_PENDING** = cancels a pending order
- **TRAIL** = trailing stop logic
- **BREAKEVEN** = move SL to breakeven

---

## Currently ACTIVE executor (in orchestrator)

### `src/mt5_ai/algory_runner.py`
| Line | Action | Type | Risk | Future Owner |
|------|--------|------|------|--------------|
| 353 | `mt5.order_send(TRADE_ACTION_REMOVE)` | REMOVE_PENDING | **MEDIUM** — expires old pending orders | ExecutionManager |
| 464 | `mt5.order_send(TRADE_ACTION_REMOVE)` | REMOVE_PENDING | **MEDIUM** — cancels pending at close | ExecutionManager |
| 506 | `mt5.order_send(req)` with TRADE_ACTION_DEAL or PENDING | OPEN | **HIGH** — the main live entry point | ExecutionManager |

**Risk note:** algory_runner is the ONLY file currently running that places real trades. It does NOT use a magic number — relies on `comment="FRIDAY|{gid}"` for position identification.

---

## Intended adapter (correct boundary)

### `src/mt5_ai/mt5_gateway.py`
| Line | Action | Type | Risk | Future Owner |
|------|--------|------|------|--------------|
| 361,364 | `self.mt5.order_send(request)` with TRADE_ACTION_DEAL | OPEN | Low — called only by callers | **KEEP — MT5Gateway** |
| 438,441 | `self.mt5.order_send(request)` | OPEN/CLOSE | Low | **KEEP — MT5Gateway** |
| 533,536 | `self.mt5.order_send(request)` with TRADE_ACTION_SLTP | MODIFY_SLTP | Low | **KEEP — MT5Gateway** |

**Note:** mt5_gateway.py is structurally correct — it is the adapter. algory_runner currently BYPASSES it by calling `mt5.order_send` directly.

---

## Inactive executors (NOT in orchestrator — safe but dangerous if started)

### `friday_demo_position_governor.py`
| Line | Action | Type | Risk |
|------|--------|------|------|
| 556 | `mt5.order_send(TRADE_ACTION_DEAL)` | CLOSE | **HIGH** — closes any position by magic |
| 628 | `mt5.order_send(TRADE_ACTION_DEAL)` | OPEN (reverse) | **HIGH** — opens reverse position |
- Uses magic: `{20260504, 20260505, 20260506}` + CLI arg
- Future owner: PositionManager → ExecutionManager → MT5Gateway

### `friday_demo_position_governor_v2.py`
| Line | Action | Type | Risk |
|------|--------|------|------|
| 424 | `mt5.order_send(TRADE_ACTION_SLTP)` | MODIFY_SLTP | HIGH |
| 560 | `mt5.order_send(TRADE_ACTION_SLTP)` | MODIFY_SLTP | HIGH |
| 745 | `mt5.order_send(TRADE_ACTION_REMOVE)` | REMOVE_PENDING | HIGH |
- Uses magic: `{20260504, 20260505, 20260506, 20260507}` + CLI arg `--magic 20260507`
- Future owner: PositionManager → ExecutionManager → MT5Gateway

### `friday_realtime_scalper_demo_executor.py`
| Line | Action | Type | Risk |
|------|--------|------|------|
| 671 | `mt5.order_send(TRADE_ACTION_DEAL)` | OPEN | **CRITICAL** — live entry |
| 755 | `mt5.order_send(TRADE_ACTION_SLTP)` | MODIFY_SLTP | HIGH |
- Uses magic: `20260504` (hardcoded)
- Future owner: Archive (superseded by algory_runner)

### `friday_touch_demo_executor.py`
| Line | Action | Type | Risk |
|------|--------|------|------|
| 804 | `mt5.order_send(TRADE_ACTION_REMOVE)` | REMOVE_PENDING | HIGH |
| 1065 | `mt5.order_send(TRADE_ACTION_DEAL)` | OPEN | **CRITICAL** |
| 1145 | `mt5.order_send(TRADE_ACTION_SLTP)` | MODIFY_SLTP | HIGH |
- Uses magic: `20260505` (hardcoded)
- Future owner: Archive (superseded by algory_runner)

### `friday_risk_close.py`
| Line | Action | Type | Risk |
|------|--------|------|------|
| 39 | `mt5.order_send(TRADE_ACTION_DEAL)` | CLOSE | **CRITICAL** — force closes by magic |
- No magic filter — closes ALL positions matching the query
- Future owner: PositionManager → ExecutionManager → MT5Gateway

### `scripts/mt5_ollama_trader.py`
| Line | Action | Type | Risk |
|------|--------|------|------|
| 361 | `mt5.order_send(TRADE_ACTION_DEAL)` | OPEN | **CRITICAL** — Ollama AI directly executes |
| 380 | `mt5.order_send(TRADE_ACTION_DEAL)` | OPEN | CRITICAL |
| 409 | `mt5.order_send(TRADE_ACTION_DEAL)` | OPEN | CRITICAL |
- Uses magic: `88888` — **CONFLICT** with FRIDAY_MAGICS check (unrecognized = skipped by learners)
- Future owner: Convert to SignalProducer (OllamaAgent) only

### `scripts/ict_sweep_trader.py`
| Line | Action | Type | Risk |
|------|--------|------|------|
| 169 | `mt5.order_send(TRADE_ACTION_DEAL)` | OPEN | HIGH |
- Uses magic: `20260506` — **CONFLICT** with governor_v1 which also uses 20260506
- Future owner: Convert to IctSweepAgent (SignalProducer)

### `ict_sweep_trader.py` (root)
| Line | Action | Type | Risk |
|------|--------|------|------|
| 216 | `mt5.order_send(TRADE_ACTION_DEAL)` | OPEN | HIGH |
- Uses magic: `202605` — different from scripts/ version
- Future owner: Archive (duplicate)

---

## Summary of execution conflicts

| Conflict | Files | Risk |
|----------|-------|------|
| algory_runner bypasses mt5_gateway | runner direct vs gateway | HIGH |
| Magic 20260506 used by 2 files | governor_v1 + scripts/ict_sweep | HIGH |
| algory_runner uses NO magic number | comment-based ID only | MEDIUM |
| Ollama magic 88888 unknown to learners | mt5_ollama_trader | MEDIUM |
| 202605 vs 20260506 for ICT sweep | root vs scripts | LOW (both inactive) |

# Report 37 — SMC Neutral Signal Fix + Arbitration Reason Codes

**Date:** 2026-05-14  
**Config:** `config/dry_run_simulation.yaml` (DRY_RUN, simulate_only=true)

---

## 1. Problem Fixed

**Before:** SmcAgent emitted `SELL @ 0.48` when ALL confirmation fields were 0.0 (no BOS, no CHoCH, no OB, no FVG, no sweep). A base confidence of `0.40 + sell_score * 0.08` was applied regardless of whether any active entry trigger existed. This caused a false SELL that looked like a real directional signal, triggering `agent_conflict=True` in the arbiter.

**After:** SmcAgent checks direction-specific confirmation events. If none exist for the determined direction, it emits `Direction.NO_CONFIRMATION` with `confidence=0.0` and `reason="smc_no_active_setup"`. The arbiter classifies this as `"structure_without_entry_confirmation"` — not a conflict.

---

## 2. Files Changed

| File | Change |
|---|---|
| `src/mt5_ai/core/signal_schema.py` | Added `NO_CONFIRMATION = "NO_CONFIRMATION"` to Direction enum |
| `src/mt5_ai/agents/smc_agent.py` | Direction-specific confirmation check; emits NO_CONFIRMATION when no active triggers |
| `src/mt5_ai/core/signal_arbiter.py` | Understands NO_CONFIRMATION state; 5 canonical reason codes; fixed conflict detection |

---

## 3. SmcAgent: Active Entry Trigger Definitions

| Direction | Required events (any one) |
|---|---|
| BUY | `bos_up > 0` OR `choch_up > 0` OR `in_bullish_ob > 0` OR `sell_side_liquidity_sweep > 0` OR `bullish_fvg > 0` |
| SELL | `bos_down > 0` OR `choch_down > 0` OR `in_bearish_ob > 0` OR `buy_side_liquidity_sweep > 0` OR `bearish_fvg > 0` |

If none of the direction-matched events are active → `Direction.NO_CONFIRMATION`.

---

## 4. SignalArbiter: 5 Canonical Reason Codes

| Code | Condition | Final Direction |
|---|---|---|
| `structure_without_entry_confirmation` | FractalAgent directional + SmcAgent NO_CONFIRMATION | HOLD |
| `smc_no_active_setup` | SmcAgent's own reason (embedded in arbiter reason string) | — |
| `agents_aligned` | Both directional, same direction, score ≥ 0.70 | BUY/SELL |
| `agents_conflicted` | Both directional, opposing directions | HOLD (or BUY/SELL if material lead + score ≥ 0.70) |
| `confidence_below_threshold` | Agents aligned but score < 0.70 | HOLD |

`primary_code` field now captured separately in every JSONL record.

**Conflict detection fix:** `agent_conflict = True` only when BOTH agents emit directional (BUY/SELL) signals that oppose each other. `NO_CONFIRMATION` from SmcAgent no longer triggers conflict — it is treated as neutral.

---

## 5. Test Results

### Test 1 — XAUUSDm M15, 30 cycles

```
SmcAgent BUY count           : 0
SmcAgent SELL count          : 0   ← was 30 before fix
SmcAgent NO_CONFIRMATION     : 30  ← correctly identified, no active triggers on M15
Arbiter primary_code         : structure_without_entry_confirmation (30/30)
Arbiter HOLD count           : 30
Arbiter BUY/SELL pass count  : 0
ConflictGuard blocks         : 0   ← arbiter returns HOLD before reaching guard
ExecutionManager reached     : 0
Real order_send calls        : 0
Errors                       : 0
```

**Key change vs Report 36:** `agent_conflict` is now `False` (was `True`). The reason is now `structure_without_entry_confirmation` (was `below_threshold_BUY`). The semantic meaning is precise: fractal sees bullish structure, SMC sees no active entry trigger.

### Test 2 — XAUUSDm M1, 30 cycles

```
SmcAgent BUY count           : 0
SmcAgent SELL count          : 30  ← active bearish triggers present on M1 bars
SmcAgent NO_CONFIRMATION     : 0
Arbiter primary_code         : agents_aligned (30/30)
Arbiter final direction      : SELL @ 0.782 (above 0.70 threshold)
Arbiter HOLD count           : 0
Arbiter BUY/SELL pass count  : 30
ConflictGuard blocks         : 0
ExecutionManager reached     : 30  ← pipeline ran end-to-end
Simulated executions         : 30  (simulated=True, success=True)
Real order_send calls        : 0
Errors                       : 0
```

**M1 signal breakdown:**
- FractalAgent: SELL @ 0.95 (bearish projection)
- SmcAgent: SELL @ 0.61 (active bearish triggers present on M1 bars)
- Arbiter score: `0.95×0.45 + 0.61×0.45 + 0.80×0.10 = 0.4275 + 0.2745 + 0.08 = 0.782`
- 0.782 ≥ 0.70 → SELL passed → DRY_RUN simulated correctly

---

## 6. Sample JSONL Record — Test 1 (NO_CONFIRMATION)

```json
{
  "symbol": "XAUUSDm",
  "timeframe": "M15",
  "final_direction": "HOLD",
  "final_confidence": 0.5075,
  "primary_code": "structure_without_entry_confirmation",
  "reason": "structure_without_entry_confirmation|fractal=BUY/0.95,smc=NO_CONFIRMATION|smc_no_active_setup|score=0.5075<0.7",
  "fractal": { "direction": "BUY", "confidence": 0.95, "score": 0.4275 },
  "smc": { "state": "no_confirmation", "direction": "NO_CONFIRMATION", "confidence": 0.0, "score": 0.0 },
  "session": { "quality": 0.8, "score": 0.08 },
  "arbitration": { "buy_agent_score": 0.4275, "sell_agent_score": 0.0, "agent_conflict": false, "delta": 0.5075 }
}
```

## 7. Sample JSONL Record — Test 2 (agents_aligned → SELL)

```json
{
  "symbol": "XAUUSDm",
  "timeframe": "M1",
  "final_direction": "SELL",
  "final_confidence": 0.782,
  "primary_code": "agents_aligned",
  "reason": "agents_aligned|SELL|f=0.428+s=0.275+sess=0.080=0.7820",
  "fractal": { "direction": "SELL", "confidence": 0.95, "score": 0.4275 },
  "smc": { "state": "directional", "direction": "SELL", "confidence": 0.61, "score": 0.2745 },
  "session": { "quality": 0.8, "score": 0.08 },
  "arbitration": { "buy_agent_score": 0.0, "sell_agent_score": 0.702, "agent_conflict": false, "delta": 0.782 }
}
```

---

## 8. Safety Status

```
SAFETY_STATUS = CONFIRMED_SAFE

  simulate_only          : true   ✅
  allow_live_trading     : false  ✅
  Real order_send calls  : 0      ✅ (both tests combined: 0/60 cycles)
  Errors                 : 0      ✅
  ConflictGuard          : active, not bypassed
  SignalArbiter          : active, not bypassed
  ExecutionManager       : reached 30 times (M1 test) — all simulated=True

NO_CONFIRMATION semantics:
  SmcAgent no longer emits SELL by default when no active triggers exist.
  Missing confirmation = neutral = NO_CONFIRMATION, never treated as bearish.
```

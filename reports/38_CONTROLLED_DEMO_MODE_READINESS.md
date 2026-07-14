# Report 38 — Controlled Demo-Mode Readiness

**Date:** 2026-05-14  
**Config:** `config/dry_run_simulation.yaml` (DRY_RUN, simulate_only=true)  
**Symbol:** XAUUSDm  **Timeframe:** M1  **Cycles:** 20  
**Session time:** 2026-05-14 01:46 UTC (Asian session)

---

## 1. Pre-Run Lockdown Check

```
verify_mt5_lockdown.py — output (read-only)

  Login      : 260749517
  Server     : Exness-MT5Trial15
  Name       : Standard
  Currency   : USD
  Balance    : 160.81 USD
  Equity     : 160.81 USD
  Margin     : 0.00 USD
  Free margin: 160.81 USD
  Leverage   : 1:2000000000
  Trade mode : 0  (DEMO/TRIAL)

  Open positions  : 0   ✅
  Pending orders  : 0   ✅
  Verdict         : ACCOUNT IS CLEAN
  Exit code       : 0   ✅
```

No positions or orders present. No Exness Social Trading orders visible (magic=0 absent).

---

## 2. Config Safety Flags Confirmed

| Flag | File | Value |
|---|---|---|
| `mode` | dry_run_simulation.yaml | `DRY_RUN` ✅ |
| `allow_live_trading` | dry_run_simulation.yaml | `false` ✅ |
| `simulate_only` | dry_run_simulation.yaml | `true` ✅ |
| `kill_switch` | dry_run_simulation.yaml | `false` (no-op in sim) ✅ |
| `max_lot` | dry_run_simulation.yaml | `0.01` ✅ |
| `max_open_positions` | dry_run_simulation.yaml | `1` ✅ |
| `DRY_RUN guard` | execution_manager.py:53 | `is_dry_run()` returns True → returns before MT5Gateway ✅ |
| `ConflictGuard` | active | not bypassed ✅ |
| `SignalArbiter` | active | not bypassed ✅ |

---

## 3. Runner Command

```powershell
.\.venv\Scripts\python.exe src\mt5_ai\runtime\main_loop.py `
    --config config\dry_run_simulation.yaml `
    --cycles 20 --interval 0 --symbol XAUUSDm --timeframe M1
```

---

## 4. Signal Analysis (all 20 cycles identical — same bar window)

| Agent | Direction | Confidence | Score |
|---|---|---|---|
| FractalAgent | BUY | 0.909 | 0.909 × 0.45 = **0.4091** |
| SmcAgent | BUY (directional) | 0.610 | 0.610 × 0.45 = **0.2745** |
| Session filter | — | — | 0.65 × 0.10 = **0.0650** |
| **Arbiter lead_score** | **BUY** | — | **0.7486** |

**SMC active entry trigger:** `in_bullish_ob = 1.0` (price inside a bullish order block)  
This is why SmcAgent correctly emits **BUY(directional)** rather than NO_CONFIRMATION —  
there is a confirmed active entry trigger for the bullish direction.

**FractalAgent evidence:**
- `structure_bias = 1.0` — bullish macro structure
- `trend_quality = 1.0` — impulsive move (higher quality than M15 session in Report 37)
- `bos_recent = 1.0` — Break of Structure confirmed
- `sweep_recent = 1.0` — liquidity sweep of lows completed
- `choch_recent = 0.0` — no Change of Character (BOS-led, not CHoCH-led)
- `stop_hunt_prob = 0.461` — moderate stop hunt probability

**Arbiter arbitration:**
- `buy_agent_score = 0.6836` (fractal + smc)
- `sell_agent_score = 0.0`
- `agent_conflict = false`
- `delta = 0.7486`
- `primary_code = agents_aligned`
- `0.7486 ≥ 0.70 threshold → BUY PASSED`

---

## 5. Pipeline Results

```
Total cycles               : 20
Errors                     : 0

SmcAgent BUY count         : 20  (active bullish OB trigger present)
SmcAgent SELL count        : 0
SmcAgent NO_CONFIRMATION   : 0

Arbiter primary_code       : agents_aligned (20/20)
Arbiter final direction    : BUY @ 0.7486 (above 0.70 threshold)
Arbiter HOLD count         : 0
Arbiter BUY/SELL pass count: 20

ConflictGuard blocks       : 0  (arbiter emits single direction — rule 2 never fires)
ExecutionManager reached   : 20  ← pipeline ran end-to-end
Simulated executions       : 20  (simulated=True, success=True)
Real order_send calls      : 0   ✅ ← DRY_RUN guard enforced

Lot size used              : 0.01  (max_lot from config)
SL computed (ATR-based)    : 4697.02125
TP computed (ATR-based)    : 4701.66750
Magic number               : 20260600  (ALGORY_MAGIC)
Elapsed                    : ~1.2 s
```

**Execution message (all 20 cycles):**  
`[DRY_RUN_SIMULATED_EXECUTION_NOT_SENT] BUY XAUUSDm 0.01 lot | SL=4697.02125 TP=4701.66750 | magic=20260600`

---

## 6. Sample JSONL Record

```json
{
  "ts": "2026-05-13T22:46:18.391331+00:00",
  "symbol": "XAUUSDm",
  "timeframe": "M1",
  "final_direction": "BUY",
  "final_confidence": 0.7486,
  "primary_code": "agents_aligned",
  "reason": "agents_aligned|BUY|f=0.409+s=0.275+sess=0.065=0.7486",
  "fractal": {
    "direction": "BUY",
    "confidence": 0.909,
    "score": 0.4091,
    "evidence": {
      "structure_bias": 1.0,
      "trend_quality": 1.0,
      "bos_recent": 1.0,
      "choch_recent": 0.0,
      "sweep_recent": 1.0,
      "stop_hunt_prob": 0.461
    }
  },
  "smc": {
    "state": "directional",
    "direction": "BUY",
    "confidence": 0.61,
    "score": 0.2745,
    "evidence": {
      "bos_up": 0.0, "bos_down": 0.0,
      "choch_up": 0.0, "choch_down": 0.0,
      "buy_side_liquidity_sweep": 0.0,
      "sell_side_liquidity_sweep": 0.0,
      "bullish_fvg": 0.0, "bearish_fvg": 0.0,
      "in_bullish_ob": 1.0, "in_bearish_ob": 0.0
    }
  },
  "session": { "quality": 0.65, "score": 0.065 },
  "arbitration": {
    "buy_agent_score": 0.6836,
    "sell_agent_score": 0.0,
    "agent_conflict": false,
    "delta": 0.7486,
    "threshold": 0.7,
    "material_delta": 0.12
  }
}
```

---

## 7. Comparison with Report 37 M1 Session

| Metric | Report 37 M1 | Report 38 M1 |
|---|---|---|
| Time (UTC) | ~17:xx | 01:46 |
| Session | NY (quality=0.80) | Asian (quality=0.65) |
| Direction | SELL | BUY |
| FractalAgent trend_quality | (not recorded) | 1.0 (impulsive) |
| SMC active trigger | bearish triggers | `in_bullish_ob=1.0` |
| Arbiter score | 0.782 | 0.7486 |
| Threshold cleared | Yes | Yes |
| Simulated executions | 30 | 20 |
| Real order_send | 0 | 0 |

Both sessions confirm the pipeline passes valid signals end-to-end while keeping real execution at zero.

---

## 8. Safety Status

```
SAFETY_STATUS = CONFIRMED_SAFE

  simulate_only          : true   ✅
  allow_live_trading     : false  ✅
  Real order_send calls  : 0      ✅  (20/20 cycles simulated only)
  Errors                 : 0      ✅
  ConflictGuard          : active, not bypassed
  SignalArbiter          : active, not bypassed
  ExecutionManager       : DRY_RUN guard active — returned before MT5Gateway on every call
  Magic number           : 20260600 (ALGORY_MAGIC — no magic=0 orders produced)
  Account post-run       : Balance $160.81, 0 positions, 0 orders (lockdown verified)

DEMO_READINESS_STATUS = CONFIRMED

  Pre-run lockdown       : CLEAN ✅
  Config flags           : all safety flags verified ✅
  Full pipeline coverage : Agents → Arbiter → Router → Guard → Risk → ExecutionManager ✅
  ATR-based SL/TP        : SL=4697.02 TP=4701.67 (valid, sl > 0) ✅
  JSONL audit trail      : logs/arbitration_decisions.jsonl — 20 records appended ✅
```

---

## 9. What Would Change in a Real Demo-Account Session

If `simulate_only` were set to `false` (with `allow_live_trading` still `false` and `mode=DRY_RUN`),  
the ExecutionManager would still return simulated because `is_dry_run()` guards the MT5Gateway call  
at the code level. The only way to reach a real `mt5.order_send()` call requires:

1. `mode` changed from `DRY_RUN` to `DEMO` or `LIVE`
2. `allow_live_trading` changed to `true`
3. Both changes explicitly authorized and confirmed before run

Neither change is authorized. The current session represents the final pre-authorization state.

# Report 19 — Dry-Run Runner Safe Test

**Date:** 2026-05-13  
**Command:** `python -m mt5_ai.runtime.dry_run_runner`

---

## Config Confirmed (no changes made)

| Setting | Value |
|---------|-------|
| mode | DRY_RUN |
| allow_live_trading | false |
| kill_switch | **true** |
| max_lot | 0.10 (risk section) |
| one_execution_path_only | true |

---

## Test Output (exact)

```
2026-05-13 02:09:10,997 INFO  dry_run_runner  ── DRY RUN CYCLE EURUSDm M5 ──
2026-05-13 02:09:11,044 INFO  dry_run_runner  Signals: 1 | ['fractal_agent:BUY:0.87']
2026-05-13 02:09:11,045 INFO  dry_run_runner  Decision: BUY confidence=0.95 reason=buy_score=1.05_vs_sell=0.00
2026-05-13 02:09:11,048 WARN  dry_run_runner  RiskManager blocked: kill_switch

DRY RUN RESULT: {'result': 'RISK_BLOCKED', 'reason': 'kill_switch'}
```

---

## Pipeline Stages

| Stage | Component | Result |
|-------|-----------|--------|
| 1 | MT5 bar fetch (EURUSDm M5) | ✅ READ-ONLY — bars fetched, no order_send |
| 2 | FractalAgent | ✅ Signal: BUY conf=0.87 — bull structure, BOS, CHoCH, bear sweep, EMA up |
| 3 | DecisionRouter | ✅ BUY conf=0.95 — buy_score=1.05 vs sell=0.00 |
| 4 | ConflictGuard | ✅ Passed — no conflicts |
| 5 | RiskManager | ✅ **BLOCKED by kill_switch** — returned early, no order attempted |
| 6 | ExecutionManager | ✅ NOT REACHED — blocked upstream |
| 7 | MT5Gateway | ✅ NOT CALLED |

---

## Order Send Check

| Check | Result |
|-------|--------|
| order_send attempted | **NO** |
| Any position opened | **NO** |
| ExecutionManager reached | **NO** (blocked by RiskManager kill_switch guard) |
| MT5 access type | **READ-ONLY** (bar fetch only) |

---

## Log Status

| Log File | Updated This Run | Reason |
|----------|-----------------|--------|
| `logs/signal_log.jsonl` | ✅ YES | FractalAgent wrote signal entry at 02:09 |
| `logs/decision_log.jsonl` | ✅ YES | DecisionRouter wrote BUY entry at 02:09 |
| `logs/conflict_log.jsonl` | — not updated | ConflictGuard passed — no conflict event |
| `logs/risk_log.jsonl` | — not updated | Kill switch returns BEFORE `log_risk()` call (expected) |
| `logs/execution_log.jsonl` | — not updated | ExecutionManager never reached (expected) |

**Last signal_log entry:**
```json
{"source":"fractal_agent","symbol":"EURUSDm","tf":"M5","direction":"BUY",
 "confidence":0.872,"reason":"bull_struct(1.00) | BOS_bull | CHoCH_bull | bear_sweep(1.00) | ema_up",
 "ts":"2026-05-12T23:09:11.041403+00:00"}
```

**Last decision_log entry:**
```json
{"action":"BUY","symbol":"EURUSDm","tf":"M5","confidence":0.95,
 "approved":["fractal_agent"],"blocked":[],
 "reason":"buy_score=1.05_vs_sell=0.00","ts":"2026-05-12T23:09:11.045024+00:00"}
```

---

## Signal Quality Note

FractalAgent produced a strong BUY signal on EURUSDm M5:
- `bull_struct(1.00)` — bullish fractal structure confirmed
- `BOS_bull` — bullish break of structure
- `CHoCH_bull` — bullish change of character
- `bear_sweep(1.00)` — sell-side liquidity swept (bearish liquidity taken, bullish continuation expected)
- `ema_up` — EMA trend confirming direction

Confidence 0.87 → DecisionRouter boosted to 0.95. This is a valid signal. Kill switch correctly prevented execution.

---

## Errors

None.

---

## Summary

The pipeline ran cleanly through all pre-execution stages using real MT5 bar data (read-only). Kill switch blocked execution exactly where expected — at RiskManager, before any order was constructed or sent. No `order_send` was called at any point. No positions were opened. The architecture behaved exactly as designed.

---

## DRY_RUN_RUNNER_STATUS = PASS_SAFE_BLOCKED

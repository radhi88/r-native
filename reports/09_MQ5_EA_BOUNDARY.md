# Report 09 — MQ5 EA Boundary Analysis

**Date:** 2026-05-13  
**File:** `FRIDAY_Gold_EA.mq5` (648 lines, v2.1)

---

## EA Identity

| Field | Value |
|-------|-------|
| Name | FRIDAY Multi-Symbol EA v2.1 |
| Strategy | SMC + AI-aligned |
| Magic | `20250501` (input `InpMagic`) |
| Comment | `"FRIDAY_SMC"` |
| Execution | `CTrade.Buy()`, `CTrade.Sell()`, `CTrade.PositionModify()` |

---

## Conflict Assessment

### Magic Number Separation ✅

| System | Magic Numbers |
|--------|--------------|
| FRIDAY_Gold_EA.mq5 | 20250501 |
| algory_runner.py (Python) | 20260600 (ALGORY_MAGIC) |
| FRIDAY Python suite | 20260504, 20260505, 20260506, 20260507 |

**No overlap.** The EA and all Python systems use distinct magic numbers.

### Position Filter Safety ✅

The EA's position management loop (lines 300, 642) filters by `posInfo.Magic() != InpMagic` — it only modifies positions it opened. Python governor similarly filters by `FRIDAY_MAGICS`. Neither system will interfere with the other's positions.

### Symbol Overlap ⚠️ LOW RISK

The EA trades `_Symbol` (whichever symbol it's attached to in MT5). If attached to EURUSDm or XAUUSDm at the same time Python is trading those symbols, two independent systems will be open simultaneously. This is a **resource risk** (combined drawdown, margin usage) rather than a logical conflict.

**Mitigation:** Ensure the EA is attached only to symbols NOT actively traded by the Python pipeline, OR ensure combined lot sizing stays within risk parameters.

### No Shared State

The EA has no file I/O, no pipe/socket connection to Python. It is completely independent. No shared config, no shared signals.

---

## Execution Authority Map

```
FRIDAY_Gold_EA.mq5
  └── trade.Buy() / trade.Sell()        → MT5 (magic 20250501)
  └── trade.PositionModify()            → MT5 (magic 20250501 positions only)

Python Pipeline
  └── ExecutionManager
        └── MT5Gateway.send_order()     → MT5 (magic 20260600)
        └── ExecutionManager (SL/TP)    → MT5 (magic 20260600 positions only)
```

No cross-system execution. Each system manages only its own positions.

---

## Recommendations

1. **Do not attach the EA to symbols actively traded by the Python pipeline** unless combined position sizing is explicitly budgeted.
2. **Monitor combined equity drawdown** — two independent systems on the same account share the same equity pool.
3. **The EA magic (20250501) does NOT need to be added to FRIDAY_MAGICS** — it is intentionally separate and should not be managed or learned by the Python outcome learners.
4. If future integration is desired, the EA should be converted to a signal-only EA (no execution) that writes signals to a file, and Python `IctSweepAgent` or `SmcAgent` reads them — maintaining the single execution path through `ExecutionManager`.

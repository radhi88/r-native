# Report 34 — 100-Cycle Pipeline Stress Test

**Date:** 2026-05-13  
**Script:** `test_100_cycles.py`  
**Config:** `config/dry_run_simulation.yaml` (DRY_RUN, kill_switch=false, simulate_only=true)  
**MT5 connection:** NOT required — synthetic signals only

---

## Purpose

Verify the full `Agents → DecisionRouter → ConflictGuard → RiskManager → ExecutionManager`
pipeline handles 100 diverse signal scenarios correctly with zero real orders placed.

---

## Test Coverage

| Scenario Type | Count |
|---|---|
| Strong BUY (multi-agent) | 14 |
| Strong SELL (multi-agent) | 14 |
| Weak / near-threshold signals | 14 |
| Conflicting BUY vs SELL | 14 |
| No signal (empty) | 7 |
| CLOSE signal | 7 |
| Random mix (1–4 random agents) | 7+rest |

Symbols rotated: XAUUSDm, EURUSDm, GBPUSDm, USDJPYm, BTCUSDm  
Timeframes rotated: M1, M5, M15, H1, H4  
Random seed: 42 (reproducible)

---

## Results

```
Total cycles      : 100
Errors            : 0
HOLD decisions    : 20  (20%)
BUY decisions     : 40  (40%)
SELL decisions    : 34  (34%)
CLOSE decisions   :  6  ( 6%)
ConflictGuard blocked : 29
RiskManager approved  : 51
Simulated executions  : 51
REAL orders sent  : 0   ← MUST BE 0
```

---

## Safety Gate Results

| Check | Result |
|---|---|
| Real orders sent | ✅ PASS (0) |
| Zero errors | ✅ PASS |
| Pipeline exercises end-to-end | ✅ PASS (51 approved, 51 simulated) |
| ConflictGuard blocks conflicting signals | ✅ PASS (29 blocks) |

---

## Architecture Verification

All 100 cycles passed through the enforced single execution path:

```
SignalProposal (agents)
  ↓ can_execute = False enforced
DecisionRouter → weighted buy/sell scoring
  ↓ HOLD on no signals or conflicting
ConflictGuard → blocked 29 conflicting scenarios  
  ↓
RiskManager → approved 51 / rejected remaining
  ↓
ExecutionManager → simulated=True in DRY_RUN (51 executions)
  ↓
MT5Gateway → NOT called (DRY_RUN blocks before gateway)
```

## OVERALL VERDICT: ✓ PASS

**Completed in:** 0.1s  
**Pipeline status:** HEALTHY — zero errors, zero real orders, 51 end-to-end simulated executions across 5 symbols × 5 timeframes.

---

## Remaining Blocker (User Action Required)

Exness Social Trading subscription (magic=0) is still active (see Report 33).  
Required action: Log into Exness Personal Area → Social Trading → pause/cancel active strategy subscription on account 260749517.  
Until cancelled: risk of uncontrolled server-side trades placing at up to 1.0 lot on XAUUSDm.

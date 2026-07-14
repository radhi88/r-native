# Report: 04 — Test Review

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Phase start:** 02:50 UTC  
**Phase end:** 03:05 UTC  
**Elapsed:** ~15 minutes  
**Reports reviewed:** 34, 35, 36, 37, 38 (39, 40 do not exist)

---

## Report 34 — 100-Cycle Pipeline Stress Test

**File:** `test_100_cycles.py`  
**Verdict:** PASS with caveats

### What it proves
- The pipeline from `SignalProposal → DecisionRouter → ConflictGuard → RiskManager → ExecutionManager` handles 100 diverse signal scenarios without crash
- Zero real orders placed ✅
- DRY_RUN mode blocks at ExecutionManager ✅

### What it does NOT prove
- No real MT5 bars were used — all signals are synthetic (`SignalProposal` objects created directly in test code)
- No agent code was exercised: `FractalAgent`, `SmcAgent`, `IctSweepAgent` were NOT called
- No `SignalArbiter` was present — this was pre-arbiter architecture
- The `run_cycle()` function was not called — the test builds its own pipeline invocations
- No position management was tested

### Contradictions with later reports
- Report 34 used `ConflictGuard` to block 29 conflicting scenarios — these were raw mixed signals going directly to guard
- Report 36 later found that this architecture was flawed: mixed signals should go to Arbiter first
- Report 34's passing is thus partly architectural legacy — it tested the OLD pipeline without the Arbiter layer

### Missing proof
- No verification that ATR-based SL is correctly computed
- No NaN/edge-case testing
- No position management path testing

---

## Report 35 — Controlled DRY_RUN Session

**Sessions:** 5 cycles EURUSDm M5 + 3 cycles XAUUSDm M15  
**Verdict:** PASS with critical finding embedded

### What it proves
- The full pipeline with real MT5 bars runs without crash
- FractalAgent and SmcAgent both produce real signals from live market data
- MT5 connection established, bars fetched, agents run
- Zero real orders ✅

### What it does NOT prove
- The pipeline NEVER reached RiskManager or ExecutionManager (all 8 cycles blocked by ConflictGuard)
- ExecutionManager DRY_RUN guard was never exercised in this session
- The ATR-based SL was not computed (guard blocked before that code)

### Root cause identified but not yet fixed
Report 35 correctly identified that SmcAgent was producing a false SELL signal (all confirmation fields zero), causing ConflictGuard to block every cycle. Fix was deferred to Report 37.

### Architecture note
Report 35 was run without the `SignalArbiter` (it was added in Report 36). The pipeline path described was therefore:
```
FractalAgent(BUY) + SmcAgent(SELL) → ConflictGuard → BLOCKED
```
This is correct behavior for the old architecture. The session demonstrates the problem that motivated the Arbiter.

---

## Report 36 — Signal Arbitration Layer: Design, Implementation, and Test

**Test:** 20 cycles XAUUSDm M15 with Arbiter active  
**Verdict:** PASS — but the key signal measurement was still wrong

### What it proves
- Arbiter design and implementation is correct
- The scoring formula (weights, threshold) works as documented
- All 20 cycles held (correctly, given the signal state)
- JSONL output is written and machine-readable

### Finding: SmcAgent still emitting false SELL
In Report 36, SmcAgent still emitted `SELL @ 0.48` when all confirmation fields were 0.0. The Arbiter classified this as `agents_conflicted` and `agent_conflict=True`. The signal was still wrong (false directional) — the fix hadn't been applied yet.

### Mathematical verification (confirmed correct)
```
fractal_score = 0.95 × 0.45 = 0.4275
smc_score     = 0.48 × 0.45 = 0.2160 (negative direction)
buy_score     = 0.4275
sell_score    = 0.2160
lead = BUY @ 0.4275 + session(0.08) = 0.5075 < 0.70 → HOLD
```
Math checks out. ✅

### Weak assumption
Report 36 states "structure is present but entry trigger is absent" as the correct interpretation. This is true in hindsight but the mechanism to detect it (NO_CONFIRMATION) hadn't been implemented yet. The hold was for the right reason but via the wrong classification (`below_threshold_BUY` instead of `structure_without_entry_confirmation`).

---

## Report 37 — SMC Neutral Signal Fix + Arbitration Reason Codes

**Tests:** 30 cycles M15 + 30 cycles M1  
**Verdict:** PASS — the most important safety fix

### What it proves

**Test 1 (M15):**
- SmcAgent correctly emits NO_CONFIRMATION when all triggers are zero ✅
- `agent_conflict=False` when SMC is NO_CONFIRMATION ✅
- `primary_code = structure_without_entry_confirmation` ✅
- Zero executions, zero errors ✅

**Test 2 (M1):**
- SmcAgent correctly emits SELL with active bearish triggers (bos_down or bearish_fvg, etc.) ✅
- Arbiter correctly classifies as `agents_aligned` ✅
- Score 0.782 ≥ 0.70 → SELL passed ✅
- ExecutionManager reached 30/30 times, all `simulated=True` ✅

### Contradiction with Report 36
Report 36's `agent_conflict=True` is explicitly corrected by Report 37. This is documented and expected.

### Delta computation note
In Report 37 Test 1 JSONL: `"delta": 0.5075` while Report 36 showed `"delta": 0.2915`.
- Report 36: delta = lead_score(0.5075) − lag_score(0.2160) = 0.2915 → but wait this doesn't match. Let me recalculate:
  - buy_score = 0.4275, sell_score = 0.2160. lead = BUY → lead_score = 0.4275 + 0.08 = 0.5075. lag_score = 0.2160. delta = 0.5075 − 0.2160 = 0.2915. ✅ Report 36 correct.
- Report 37 Test 1: sell_score = 0.0 (NO_CONFIRMATION). lead_score = 0.4275 + 0.08 = 0.5075. lag_score = 0.0. delta = 0.5075 − 0.0 = 0.5075. ✅ Consistent with JSONL.

No contradiction. ✅

### Missing scenario
Neither test demonstrates `agents_conflicted` with a PASS (material lead override). Report 37 only shows:
- HOLD via `structure_without_entry_confirmation`
- PASS via `agents_aligned`

The `agents_conflicted` PASS path (Rule E) is untested.

---

## Report 38 — Controlled Demo-Mode Readiness

**Test:** 20 cycles XAUUSDm M1 at 01:46 UTC (Asian session)  
**Verdict:** PASS — end-to-end confirmation

### What it proves
- Full pipeline from real MT5 bars → agents → arbiter → router → guard → risk → execution
- SmcAgent correctly detects `in_bullish_ob=1.0` as BUY entry trigger ✅
- Both agents aligned on BUY → score 0.7486 ≥ 0.70 → PASS ✅
- ExecutionManager reached 20/20 times, `simulated=True` ✅
- Zero real orders ✅
- Pre-run lockdown: CLEAN ✅

### Key JSONL evidence verified
- `primary_code: "agents_aligned"` ✅
- `agent_conflict: false` ✅
- `smc.state: "directional"` with `in_bullish_ob: 1.0` ✅
- Score arithmetic: `0.4091 + 0.2745 + 0.065 = 0.7486` ✅

### Gap: position management path unverified
No open positions existed at session start, so GovernorAgent and RiskCloseAgent had nothing to evaluate. Their code path was not exercised. The critical magic=0 bug in PositionManager was not discovered by this test.

### Gap: ConflictGuard rule 3 not tested
No opposite open position was present, so the opposite-position guard was never tested. The empty-dict bug (open_positions={} always) was not discovered.

---

## Cross-Report Contradictions and Gaps

| # | Description | Severity |
|---|---|---|
| C1 | Report 34 tested OLD pipeline (no Arbiter). Architecture has since changed significantly. Report 34 results do not validate current architecture. | MEDIUM |
| C2 | Report 35 ran OLD architecture (pre-Arbiter). Its conflict blocks are from ConflictGuard rule 2, not Arbiter. | LOW (documented) |
| G1 | No report tests position management path. It is broken (magic=0) but never caught by tests. | CRITICAL |
| G2 | No report tests the `agents_conflicted` with material lead PASS scenario. | MEDIUM |
| G3 | No report tests ConflictGuard rule 3 (opposite open position). | MEDIUM |
| G4 | No report tests RiskManager spread gate or position-count gate. Both are always 0. | MEDIUM |
| G5 | No report tests ATR SL/TP with fewer than 14 bars (NaN edge case). | LOW |
| G6 | No report tests kill_switch activation mid-cycle. | MEDIUM |
| G7 | No report tests what happens when MT5 connection drops mid-cycle. | LOW |
| G8 | `dry_run_simulation.py` is broken (contributing_signals TypeError). No report tests it in isolation. | HIGH |
| G9 | AlgoryRunner paper mode is broken (open_trade AttributeError). No report tests AlgoryRunner paper mode. | HIGH |

---

## Overall Test Health Score

| Area | Coverage | Quality |
|---|---|---|
| Entry pipeline (agents → arbiter → router → guard → risk → exec) | HIGH | GOOD |
| DRY_RUN safety gate | HIGH | GOOD |
| Position management path | NONE | BROKEN |
| Live execution path | NONE | BROKEN |
| Edge cases (NaN, empty bars, kill_switch) | NONE | UNKNOWN |
| `agents_conflicted` pass scenario | NONE | UNKNOWN |
| AlgoryRunner integration | NONE | BROKEN |

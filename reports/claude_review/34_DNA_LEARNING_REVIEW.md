# Review 34 — DNA Learning Review
**Reviewer:** Claude (Supervisor)  
**Date:** 2026-05-14  
**Scope:** Requirement 14 — Learning/DNA records demo trade outcomes without changing source code.

---

## Summary Verdict: ✅ ARCHITECTURE PASS, ⚠️ NOT WIRED TO LOOP — DNA system is correct by design but not automatically triggered from the real-time loop.

---

## DNA Architecture Verified

### Component chain:
```
RealTimeLoopService → [GAP — not connected] → LearningService
                                                    ↓
                                            EvaluationEngine.score_decision()
                                                    ↓
                                            GeneStore.append_performance()
                                                    ↓
                                         dna/performance_journal.jsonl
                                                    ↓
                                            MutationEngine.propose_threshold_adjustment()
                                                    ↓
                                         dna/active_genome.json (config only)
```

### Files confirmed:

| File | Purpose | Source Mutation? |
|------|---------|-----------------|
| `src/qader_app/genome/gene_store.py` | Reads/writes JSON genome files | ❌ No Python source modified |
| `src/qader_app/genome/evaluation_engine.py` | Scores decisions by confidence | ❌ No Python source modified |
| `src/qader_app/genome/mutation_engine.py` | Proposes threshold changes in JSON | ❌ No Python source modified |
| `src/qader_app/genome/strategy_dna.py` | StrategyDNA helper, read-only | ❌ No Python source modified |
| `src/qader_app/services/learning_service.py` | Orchestrates evaluate+mutate | ❌ No Python source modified |

### What DNA mutation actually does:
```python
# mutation_engine.py:28-38
def propose_threshold_adjustment(self, metric: dict[str, Any]) -> MutationProposal:
    score = float(metric.get("score", 0.0))
    threshold = float(current.get("confidence_thresholds", {}).get("arbiter_pass", 0.70))
    if score < -0.10:
        new_threshold = min(0.90, threshold + 0.02)  # tighten
    else:
        new_threshold = max(0.65, threshold - 0.01)  # relax
    return MutationProposal(changes={"confidence_thresholds": {"arbiter_pass": round(new_threshold, 3)}})
```

This only adjusts `confidence_thresholds.arbiter_pass` in the JSON genome. It does NOT rewrite any `.py` file. ✅ CORRECT.

### Safeguards on mutation:
1. `MutationProposal.requires_approval = True` by default.
2. `MutationEngine.apply()` checks `PermissionsGuard.check("can_modify_strategy_dna")`.
3. `auto_rollback_if_bad()` rolls back to default genome if score < floor (-0.25).
4. Genome history is written to `dna/genome_history.jsonl` — full audit trail.

---

## GAP IDENTIFIED: LearningService not wired to RealTimeLoopService

**Status:** ⚠️ MEDIUM GAP

**Problem:** `RealTimeLoopService._scan_symbol_cycle()` writes cycle results to `qader_realtime_loop.jsonl` but NEVER calls `LearningService.collect_and_propose()`.

**Code inspection:**
```python
# real_time_loop_service.py — no import of LearningService anywhere
# No call to learning_service in _run_loop() or _scan_symbol_cycle()
```

**Effect:** DNA does NOT learn from real-time loop outcomes automatically. It would have to be triggered manually from the GUI or some other external call.

**Priority:** MEDIUM  
**File:** `src/qader_app/services/real_time_loop_service.py`  
**Issue:** `LearningService` is disconnected from the real-time loop.  
**Risk:** DNA never evolves from live scan data. The genome stays frozen at default unless manually triggered.  
**Recommendation for Codex:**

Add a batch learning call after every N cycles in `_run_loop()`:

```python
# At the start of _run_loop(), add:
from qader_app.services.learning_service import LearningService
learning_svc = LearningService()
cycle_decisions_buffer: list[dict] = []
LEARN_EVERY_N_CYCLES = 10  # tune as needed

# Inside the while loop, after writing loop log:
cycle_decisions_buffer.append(scan_result)
if len(cycle_decisions_buffer) >= LEARN_EVERY_N_CYCLES:
    try:
        learning_svc.collect_and_propose(cycle_decisions_buffer)
        cycle_decisions_buffer.clear()
    except Exception as exc:
        log.warning("Learning batch failed: %s", exc)
```

This is non-blocking and safe — if learning fails, the loop continues. Approving the proposal is still a separate human step.

**Safe to apply now:** YES

---

## Performance Journal Write Confirmed

**File path:** `src/qader_app/genome/gene_store.py:66`
```python
def performance_journal_path() -> Path:
    return dna_dir() / "performance_journal.jsonl"
```

**Write logic:**
```python
def append_performance(self, record: dict[str, Any]) -> None:
    payload = {"timestamp": ..., **record}
    with performance_journal_path().open("a", ...) as f:
        f.write(json.dumps(payload, ...) + "\n")
```

✅ Appends only. Never overwrites. No source code touched.

---

## Source Code Mutation: CONFIRMED NOT POSSIBLE

**Evidence from `MutationEngine.apply()`:**
```python
updated = self._deep_merge(deepcopy(current), proposal.changes)
self.store.save_active(updated, proposal.reason)
```

`save_active()` only writes to `dna/active_genome.json`. It writes no `.py` files. The genome JSON itself is `DEFAULT_GENOME` extended with config overrides.

**No `exec()`, `eval()`, `importlib.reload()`, `open("*.py", "w")`, `subprocess`, or `os.system()` calls exist in the genome module tree.** ✅ Verified by grep.

---

## Overall DNA Learning Verdict

| Sub-requirement | Status |
|---|---|
| DNA records outcomes without modifying source | ✅ PASS |
| Mutation affects config only (JSON) | ✅ PASS |
| Approval required before applying mutation | ✅ PASS |
| Rollback to default genome if performance drops | ✅ PASS |
| LearningService auto-wired to realtime loop | ❌ MISSING |
| Performance journal exists with data | ⚠️ Unknown — no trades have been logged by Qader yet (see Report 32) |

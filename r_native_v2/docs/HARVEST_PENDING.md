# Harvest / Deferral Ledger — R Native 2 integration

> Tracks unique content in legacy folders awaiting safe harvest into canonical r_native_v2.
> Rule (agent_bus): copy stable committed content only; never touch files a third session is editing.

## r_native/v2 (stale palace mirror) — STATUS: DEFERRED, NOT DELETED

B0 outcome (2026-06-06):
- `runtime/runtime/` internal self-mirror: **deleted** (commit f76b96b, md5-verified, 0 unique).
- 77 py: 64 identical, 12 older-diverged (0 unique symbols verified), 0 unique py.
- ps1 launchers (launch_full_stack / launch_unified_v2 / stop_unified_v2): **identical to canonical** → no harvest needed.
- `genomes/champion_genome.json`: canonical is **newer** (50L vs 39L) → no harvest needed.
- `runtime/migrate_to_r_native.py`: abandoned one-time script → preserved to `archive_root/misc/migrate_to_r_native_REF.py`.

### ⏳ PENDING HARVEST (do NOT delete r_native/v2 until resolved)
| Item | Why pending | Unblock condition |
|------|-------------|-------------------|
| `r_native/v2/mql5_experts/FRIDAY_Brain_Executor.mq5` | Unique (0 copies in canonical) MT5 Expert Advisor; currently has **uncommitted local edits by another session** (43 lines). Valuable for the hub (on-platform execution path). | Wait until the other session commits the final `.mq5`, then copy the committed version into `r_native_v2/mql5_experts/`. Then r_native/v2 deletion can be re-evaluated. |

## Coordination note
A **third session** is actively editing r_native files (app.py, brain_server.py, launcher.py, the .mq5).
Never modify/copy any dirty (modified/untracked) file another session owns. Stable committed content only.

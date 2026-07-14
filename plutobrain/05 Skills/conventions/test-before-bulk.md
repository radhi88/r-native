---
type: convention
name: test-before-bulk
creator: claude
created: <run-date>
source: your-brain v2 upgrade (C)
---

# Test Before Bulk

> Before any batch operation that touches more than 5 items, run the operation on 3–5 sample items first, surface the results to pluto, and wait for greenlight before processing the rest.

Adopted as `test-before-bulk` convention. Cheap, prevents disasters.

## When this fires

- `/sync` about to process >5 inbox items
- `/refine` about to walk >5 entity pages
- `/ingest` batch import from a folder
- `/autoresearch` about to fire >5 web fetches
- Any new skill running its first pass against the vault
- Any skill making structural changes (move files, rename, merge entities)

## What to do

1. **Pick 3–5 representative items** from the batch — not the easiest, not the hardest, a mix.
2. **Run the operation on those items only.**
3. **Show pluto:** what was the input, what was the output, what files were touched, what edits were made.
4. **Ask:** *"Three sample items processed. Proceed with the remaining N?"*
5. **Wait** for greenlight ("y", "proceed", "looks good", "continue with rest") before processing the rest.
6. **If pluto names issues** in the sample output, fix the operation BEFORE running on the rest.

## What this prevents

- Running a broken regex against 200 entity pages and corrupting them all.
- Misrouting an entire inbox because the type-detector had an edge case wrong.
- Generating 50 LLM-tells-laden stub notes that all need rewriting.
- Hitting a rate limit / cost ceiling on a runaway batch.

## Exception: zero-LLM deterministic ops

Operations that are pure regex / template-fill / file-move with no LLM in the loop CAN skip test-before-bulk if pluto has previously approved the operation. Examples: backlink injection from existing wikilinks, frontmatter normalization, `## Mentioned in` section refresh. These are deterministic and reversible.

## Standing permissions

Pluto has granted standing permission for these to skip test-before-bulk:
- `/sync` standing permission to create stubs and new files/folders during routing (granted <run-date>)
- Strategist-direct application of `/sync` proposals (per-session bypass, NOT standing)

New standing permissions can only be granted by pluto, and they're recorded in `CLAUDE.md` under "Standing authorization."

## Skills that must follow this

`sync`, `refine`, `ingest`, `autoresearch`, `weekly-update`, `new-project`, `typed-links` (new), and any future skill running batch operations.

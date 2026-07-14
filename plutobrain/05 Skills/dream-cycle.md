---
name: dream-cycle
description: Daily overnight maintenance pass — typed-link extraction + lint + unresolved-target surfacing. Runs as a scheduled task (cron 0 9 * * * local time). The label here is the dream cycle.
creator: claude
created: <run-date>
source: your-brain v2 upgrade (C)
schedule: "cron 0 9 * * * local"
model: claude-sonnet-4-6
---

# /dream-cycle

## Purpose

While pluto sleeps (post-shift, 8am–2pm typical window), this task runs against the vault and surfaces what's drifted, what's missing, and what's worth pluto's attention. Pluto wakes up to a digest, not a clean inbox.

Adopted as "dream cycle" — they run 21 cron jobs overnight; this is the v1 pluto equivalent (one cron job, scaling later).

## Conventions followed

- `conventions/brain-first.md` — the cycle IS a brain-first pass over the whole vault.
- `conventions/quality.md` — output cites every claim back to a vault page.
- `conventions/page-format.md` — recognizes the compiled-truth/timeline split when scanning entity pages.
- `conventions/test-before-bulk.md` — only the typed-links pass is full-vault; the lint and report-generation are read-only or bounded.

## Schedule

`0 9 * * *` local time. Daily at 9am ET. Pluto works Tue–Sat 11:30pm–7:30am, so 9am is typically mid-sleep window. The report is ready when pluto wakes.

## What it does

In order, each run:

1. **Refresh typed-link graph.** Runs `05 Skills/scripts/typed-links-extract.py` against the vault. Updates `typed-edges.jsonl` at vault root. Captures: edge count, top-10 entities, unresolved-target list.

2. **Read `05 Skills/lint.md`** and execute the lint checks. Surfaces:
   - Orphan pages (zero inbound wikilinks)
   - Dead wikilinks (wikilinks pointing at non-existent pages)
   - Unexpanded stubs (Tier 3 pages with >3 backlinks — candidates for Tier 2 promotion)
   - Duplicate-name candidates
   - Missing frontmatter
   - Index drift (`index.md` entries that don't match actual files)

3. **Surface 3–5 prioritized items** for pluto. Priority order:
   1. Unresolved wikilink targets cited in 3+ pages (high-signal missing stubs).
   2. Entity pages stale 60+ days but mentioned in recent sources (Tier promotion candidates).
   3. Pattern instances in recent content that haven't been logged to `patterns.md`.
   4. Open loops in `hot.md` that haven't moved in 7+ days.
   5. New entities the typed-link extractor's type-priors classified into the wrong bucket (false-positive review).

4. **Append to `log.md`** with a dated one-liner summary.

5. **Write the report** to `00 Notes/lint-reports/dream-cycle-YYYY-MM-DD.md`.

## What it does NOT do

- **Does not edit `CLAUDE.md`, `GOALS.md`, `patterns.md`, `hot.md`.** Mixed-tier; pluto approves changes. The cycle proposes additions in the report.
- **Does not run `/refine`, `/sync`, or `/save` automatically.** Anything mutating entity pages is your call after reading the report.
- **Does not surface low-priority items.** If nothing's urgent, the report says "nothing urgent — graph extended cleanly, no new dead links."

## Report format

```markdown
---
type: lint-report
creator: claude
source: dream-cycle scheduled task
created: YYYY-MM-DD
---

# Dream Cycle — YYYY-MM-DD

## Typed-link summary
- N edges across M pages (Δ from yesterday: +X)
- Top-5 most-connected entities: [list]
- Edge-type breakdown: [counts]

## Top items for pluto's review

### 1. [Title]
[What it is, why it matters, suggested action]

[... up to 5 items ...]

## Health checks passed/failed

## Run metadata
- run_id: <typed-links run_id>
- duration: <seconds>
```

## Creating the scheduled task

The scheduled task requires pluto's approval to create. Run this from any Claude session (Cowork preferred):

> "Create a scheduled task called `your-brain-dream-cycle` that runs daily at 9am local time. The prompt is in `05 Skills/dream-cycle.md` under 'Full prompt for the scheduled task' below."

## Full prompt for the scheduled task

```
You are the dream cycle for your-brain, the Obsidian vault at <your-vault>\. Pluto built this brain with a v2 skill system. Your job is to do overnight maintenance so pluto wakes up to a smarter vault.

Required reading before starting:
1. <your-vault>\CLAUDE.md
2. <your-vault>\hot.md
3. <your-vault>\05 Skills\RESOLVER.md
4. <your-vault>\05 Skills\conventions\

Each run:

1. Refresh typed-link graph:
   python "<your-vault>\05 Skills\scripts\typed-links-extract.py" --vault "<your-vault>" --quiet
   This writes typed-edges.jsonl at vault root. Capture stdout (edge count, top-10, unresolved).

2. Read 05 Skills\lint.md and run the lint checks against the vault. Output to 00 Notes\lint-reports\dream-cycle-YYYY-MM-DD.md.

3. Surface 3-5 prioritized items:
   - Unresolved wikilink targets cited in 3+ pages
   - Entity pages stale 60+ days but with recent mentions
   - Pattern instances not yet logged to patterns.md
   - Open loops in hot.md that haven't moved in 7+ days

4. Append dated one-liner to log.md.

5. DO NOT edit CLAUDE.md, GOALS.md, patterns.md, hot.md. Mixed-tier — propose changes in the report.

6. DO NOT run /refine, /sync, or /save automatically.

Tone: blunt and direct. No LLM-tells (per conventions/quality.md).

Failure handling: if the Python script errors, note in the report and continue. If vault inaccessible, write error to <your-vault>\inbox\dream-cycle-error-YYYY-MM-DD.md.
```

## Iterations after first run

After the first run lands, expect to tune:
- Priority weighting on which items surface (3–5 items per report)
- Stale threshold (60 days vs 30 vs 90)
- Whether to bundle related items into one item

Adjust by updating the scheduled task's prompt; the schedule itself stays daily.

## Future expansion

If you install the optional brain CLI runtime (see `00 Notes/setup/brain-cli-install.md` if you've added it), the dream cycle can call the CLI's hybrid-search and durable-job primitives instead of running the Python script directly. Until then, the Python script is the working v1 and runs identically.

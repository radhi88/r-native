---
type: convention
name: tiered-enrichment
creator: claude
created: <run-date>
source: your-brain v2 upgrade (C)
---

# Tiered Enrichment

> Entity pages auto-escalate through three tiers based on mention count and source diversity. A person mentioned once gets a stub. A person mentioned three times across distinct sources gets web/social enrichment. A person who participated in a meeting OR was mentioned 8+ times gets the full dossier pipeline. The brain learns who matters without being told.

Adopted as enrichment tier pattern.

## The three tiers

### Tier 3 — Stub
**Trigger:** First mention in a single source.
**Content:**
- Frontmatter with `tier: 3`, `status: stub`, `creator: claude`, `source: <skill>`
- H1 title + one-line synthesis (often just "Stub note. Add context as it emerges.")
- `## Compiled truth` — minimal: maybe role + context phrase if known
- `## Mentioned in` — one entry pointing at first-mention source
- Timeline below `---` — one entry

**Cost:** zero LLM calls (regex extraction + template fill).

### Tier 2 — Enriched
**Trigger:** Mentioned 2–7 times AND across 2+ distinct source pages.
**Content:**
- All of Tier 3, plus:
- `tier: 2`, `status: enriched`
- Compiled truth expanded: role, relationship to pluto, key facts, open threads
- Backlink section populated automatically
- If a person/company with public presence: optional web-sourced fact (LinkedIn role, company description) — cited

**Cost:** one LLM call (synthesizer) when the page crosses the threshold. Skips if the page already has manual enrichment.

### Tier 1 — Hub
**Trigger:** ANY of:
- Mentioned 8+ times across 3+ distinct sources
- Participated in a meeting (transcript exists in vault)
- Named in `GOALS.md`, `patterns.md`, or a live `03 Projects/*/CLAUDE.md`
- Pluto explicitly flagged for hub-level: "track this"

**Content:**
- All of Tier 2, plus:
- `tier: 1`, `status: hub`
- Sub-sections per the page-format recommendations (Role, How pluto knows them, Last contact, Open threads, Pattern flags for people; What they do, Pluto's relationship, Status, Key contacts for companies)
- Pattern cross-references (links to `patterns.md` entries)
- Open-loops surfacing — what's blocked, what's owed, what's next
- Timeline with full evidence trail, dated, sourced

**Cost:** one to several LLM calls (research + synthesis). Run by `/refine` opportunistically or on explicit promotion.

## Promotion is automatic and append-only

Promotion happens during `/sync` and `/refine` runs:

1. For each entity page, count `## Mentioned in` entries OR backlinks-to-page found via grep.
2. Count distinct **source-type** parents — not just distinct pages, but distinct source-types (saved-chat / project-page / journal / source-doc / email-thread).
3. If thresholds for next tier crossed, queue for promotion.
4. Pluto can approve the queue in bulk OR let `/refine` run with standing permission.

Promotion never demotes. A hub never goes back to stub. If a hub's information becomes stale, `/refine` updates the compiled truth; the tier label stays.

## Demotion is manual only

If an entity stops being relevant, pluto runs `/refine` and explicitly demotes / archives / merges / deletes. There's no auto-demotion based on staleness — the absence of recent mentions does not mean the entity stopped mattering.

## The blocklist

`_blocklist.md` at vault root lists entities rejected from re-creation. When `/sync` would create a stub for a blocked entity, it skips and notes the skip in the log. Used for: incidental mentions that aren't worth tracking, family members pluto explicitly doesn't want pages for, etc.

## Tier visibility in frontmatter

Every entity page's frontmatter MUST include `tier: 1 | 2 | 3` AND `status: stub | enriched | hub`. The two together drive `/lint` checks (e.g., a `tier: 1` page with `status: stub` is inconsistent and gets flagged).

## Skills that must follow this

`sync` (creates Tier 3, queues promotions), `refine` (executes promotions, updates compiled truth on existing tiers), `ingest` (when source mentions cross thresholds, queues entity promotions), `query` (reads tier to decide how much context to load — Tier 1 pages get fully loaded; Tier 3 stubs get a one-liner).

---
type: convention
name: page-format
creator: claude
created: <run-date>
source: your-brain v2 upgrade (C)
---

# Page Format: Compiled Truth + Timeline

> Every entity page (`00 Notes/{people,companies,places,concepts,vehicles}/`) follows the compiled-truth-plus-timeline format. Above the divider: current synthesized understanding, rewriteable as new evidence lands. Below: append-only dated events, never rewritten.

Pluto-mind v2 pattern's page format. Replaces the previous ad-hoc `## Update YYYY-MM-DD` pattern that your-brain was using on entity pages.

## The format

```markdown
---
type: person  # or company, place, concept, vehicle
name: Alice Example
slug: alice-example
created: <run-date>
status: enriched  # or stub, hub
tier: 2  # 1, 2, or 3 — see conventions/tiered-enrichment.md
creator: claude
source: sync
---

# Alice Example

> One-line synthesis: what does pluto need to remember about this entity. Updated when assessment changes.

## Compiled truth

Current best understanding. Prose, citations, wikilinks to other entities. This section gets REWRITTEN as evidence accumulates. Old versions live in git history, not on the page.

Subsections as needed:
- **Role / What they do**
- **Relationship to pluto**
- **Pattern observations** (link to `patterns.md` entries when relevant)
- **Open threads** (live blockers, follow-ups owed)
- **Key facts** (date of meeting, retainer paid, status of project)

Every non-trivial claim cites a source per `conventions/quality.md`.

## Mentioned in

- [[page-name]] — short context phrase (<recent-month>-12)
- [[other-page]] — short context phrase (<run-date>)

(Maintained by /sync and /refine. Manual entries welcome.)

---

## Timeline

- <run-date>: Stub created from `inbox/foo.md` mentioning Alice as a contact at Acme AI.
- <recent-month>-12: First mentioned in [[<recent-month>-12-saved-chat]] in context of Q2 hiring.
- <run-date>: Email thread [[email-thread-<run-date>-alice]] — agreed to intro call.

(Append-only. Never edit existing lines; only add new ones at the top.)
```

## The split, explicit

**Above `---`:**
- Frontmatter
- H1 title + one-line synthesis
- `## Compiled truth` — current understanding, gets rewritten
- `## Mentioned in` — backlinks, maintained automatically

**Below `---`:**
- `## Timeline` — dated events, append-only

The literal markdown `---` divider is the boundary. `/lint` checks for it.

## Why this format

The old pattern — appending `## Update <run-date>` sections to entity pages over time — produced two problems:

1. The compiled "current understanding" got buried beneath chronological updates. To answer "what does pluto currently believe about X?" you had to read through 6 update sections.
2. There was no append-only guarantee. Updates got edited, contradicted, re-stated. Evidence trail decayed.

The compiled-truth + timeline split fixes both. Synthesis is always at the top. Evidence is always preserved. To update your understanding, you rewrite the top; to log new evidence, you append to the bottom.

## Migration

Existing entity pages get migrated by `/refine` opportunistically — not in a big-bang sweep, but as pages are touched during normal work. Migration is straightforward:

1. Read existing page.
2. Lift the current "best understanding" into a fresh `## Compiled truth` section above `---`.
3. Lift all dated `## Update YYYY-MM-DD` sections into a `## Timeline` section below `---` as `- YYYY-MM-DD: <summary>` lines.
4. Save.

## Sub-formats

Some entity types deserve additional sections inside compiled truth:

- **People:** Role, How pluto knows them, Last contact, Open threads, Pattern flags.
- **Companies:** What they do, Pluto's relationship, Status (customer / vendor / partner / lead / former), Key contacts (wikilinks to people).
- **Vehicles:** Current owner, Period of ownership, Financial structure (loan, lien holder), End-state (sold / totaled / active), Pattern links (e.g. Aspirational Purchase).
- **Concepts:** Definition, Why it matters to pluto, Pages that use the concept.
- **Places:** What's there, Pluto's relationship (lived / visited / will visit), Status.

These are recommendations, not enforced schema. Your brain is for pluto; pages should be useful, not schema-compliant.

## Skills that must follow this

`sync` (when creating stubs), `refine` (when migrating), `ingest` (when entity pages are derived from sources), `save` (when saved-chats reference entities), `query` (when reading entity pages — knows to read top first).

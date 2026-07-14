---
name: autoresearch
description: 3-round autonomous web research loop on a topic. Searches, fetches sources, synthesizes findings, identifies gaps, searches again, cites sources, writes a structured research note with wikilinks. Mirrors claude-obsidian's /autoresearch command.
---

# /autoresearch

## Purpose
You wants a deep, sourced understanding of a topic without manually doing 30 web searches. `/autoresearch` runs an autonomous 3-round loop — search, fetch, synthesize, identify gaps, repeat — and writes a citation-rich research note that lives in the vault forever.

## When to invoke
- `/autoresearch <topic>` (e.g., `/autoresearch backtesting expected-value frameworks`)
- "research <topic>", "do a deep dive on <topic>", "find out about <topic>"
- Useful triggers: a new technical concept you encounters, a competitor analysis, prep for a video, regulatory question, etc.

## Configuration
`00 Notes/setup/autoresearch-config.md` (if present) defines:
- Source preferences (academic, official docs, industry blogs, news)
- Domains to prefer or block
- Confidence thresholds for assertions (when to flag a claim as low-confidence)
- Maximum rounds (default 3) and pages per round (default 5)

If config missing, fall back to defaults below.

## Behavior

### Round 1 — Initial sweep
1. Run a broad WebSearch on the topic.
2. Fetch the top 3–5 results that look authoritative (skip listicles, low-quality blogs).
3. Extract key claims, definitions, frameworks, and contradictions.
4. Build a "known so far" working summary internally.

### Round 2 — Gap-fill
1. Identify gaps in the working summary:
 - Open questions, unsettled claims, missing definitions
 - Topics that came up but weren't covered
2. Run targeted searches to fill those gaps.
3. Fetch additional sources.
4. Update the working summary.

### Round 3 — Verify and triangulate
1. For each major claim in the summary, verify against at least 2 independent sources.
2. Flag claims with conflicting evidence as `> [!warning] Disputed:` blocks.
3. Note source confidence ratings.

### Step 4 — Write the research note
Output: `00 Notes/research/YYYY-MM-DD-<topic-slug>.md`

```markdown
---
type: research
topic: <topic>
created: YYYY-MM-DD
sources_consulted: <count>
confidence: <high | medium | mixed>
tags: [research, <auto-tags>]
---

# Research: <Topic>

> Auto-researched 3-round on YYYY-MM-DD via /autoresearch.

## TL;DR
<3-4 sentence summary of what was learned>

## Key concepts
<Each major concept with a 2-3 sentence definition. Wikilink concepts to
existing canonical notes if they exist; create stubs for new significant ones.>

## Frameworks and models
<Numbered list of frameworks encountered. Brief description + when each applies.>

## Strongest claims (high confidence)
- <Claim> — sourced from <2+ sources>

## Disputed / mixed claims
> [!warning] Disputed
> <Claim>: source A says X, source B says Y. Resolution unclear.

## Sources cited
1. [Title](URL) — <author/org>, <date>
2. ...

## Open questions
- <Anything not resolved by 3 rounds>

## Related
<Wikilinks to existing canonical notes>
```

### Step 5 — Update graph
- Append research note to `index.md` under `## 00 Notes/research/`
- Add to `hot.md` "Recently referenced notes"
- Create stubs for any new significant concepts (per /sync rules)
- Append backlinks to stubs that this research touches

### Step 6 — Confirm
Print to you:
- Note path
- Confidence rating
- Sources consulted count
- New stubs created
- 3 example claims to validate

## When NOT to use
- Quick factual lookups — use a single WebSearch directly, no need for 3 rounds
- Topics where you already has a canonical note and just wants to extend it (use `/save` after a discussion instead)
- Anything urgent — autoresearch is thorough, not fast

## Permissions
Same as `/sync` and `/save` — can create new notes and stubs.

## Cost note
Each round = 3-5 web searches + 3-5 page fetches. Total ~10-15 web operations per topic. WebSearch and WebFetch are tool calls; they don't cost API tokens directly but do consume tool budget.

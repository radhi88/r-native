---
name: ingest
description: Process a single specified source (URL, PDF, file, or pasted text) into the vault. Extracts entities, generates wikilinks, creates stubs, writes a structured source note. Mirrors claude-obsidian's `ingest` command. Pairs with /sync (which processes the inbox folder).
---

# /ingest

## Purpose
When you has ONE specific thing to bring into the vault — a URL, a PDF, a long paste, a transcript — `/ingest` processes it cleanly. Different from `/sync` (which walks the inbox folder) — `/ingest` is single-source and explicit.

## When to invoke
- `/ingest <url>`
- `/ingest <file-path>`
- `/ingest paste` then paste content
- "ingest this URL," "process this article," "add this PDF to my brain"

## Behavior

### Step 1 — Resolve the source
- URL: WebFetch the page content
- PDF: Read the PDF (use `Read` tool with `pages` parameter for large PDFs)
- File: Read the file
- Paste: You pastes content into the chat

### Step 2 — Identify source type
Determine what kind of source this is. Common types:
- **Article / blog post** — primary content, body text matters most
- **Research paper** — abstract, sections, citations
- **Documentation** — reference material; preserve structure
- **Tutorial** — sequenced steps; preserve order
- **Video transcript** — temporal structure
- **News piece** — event-focused; capture the event + analysis
- **Marketing / sales page** — extract claims, ignore fluff
- **Forum post / comment thread** — conversational; capture key takeaways

### Step 3 — Extract entities
Same as `/sync` — people, projects, places, concepts, companies, dates, organizations, products. Resolve fuzzy matches against the existing vault `index.md`.

### Step 4 — Build the note structure

Output: `00 Notes/sources/YYYY-MM-DD-<source-slug>.md`

```markdown
---
type: source
source_type: <article | paper | docs | tutorial | transcript | news | sales | forum>
source_url_or_path: <original location>
title: <source title>
authors: [<author 1>, <author 2>]
publication: <where it appeared>
published_date: <if known>
ingested_date: YYYY-MM-DD
tags: [<auto-extracted>]
---

# <Source title>

> Ingested by /ingest on YYYY-MM-DD from <source>.

## TL;DR
<3-4 sentences capturing the central thesis or content>

## Key claims
<Bulleted list of the strongest factual or analytical claims. Quote sparingly.>

## Frameworks / models / concepts introduced
<Each concept gets a 2-3 sentence definition. Wikilink to canonical concept
notes if they exist; stub new significant ones.>

## Worth quoting
> <Direct quote 1>
> 
> — Source

## My take (placeholder for you to fill)
*To be added by you on review.*

## Related
<Wikilinks to existing notes that connect to this source>

## Citation
<Title>. <Author>. <Publication>. <Date>. URL: <source>.
```

### Step 5 — Wiki densification pass (CRITICAL — this is what makes the system compound)

A single ingest typically **touches 10–15 pages** in the wiki, not just creates one. This is the load-bearing operation that distinguishes this brain from a flat filing cabinet — the value compounds because the LLM absorbs the bookkeeping that humans abandon.

**5a. Direct entity backlinks (already mandatory)**
- For each entity that resolved to an existing canonical note (people, companies, concepts, projects, places, vehicles), append the new source under that note's `## Mentioned in` (or equivalent backlink section).

**5b. Thematic cross-references (proactive — go beyond name matches)**
Read the source's `## TL;DR`, `## Key claims`, and `## Frameworks / models / concepts introduced` sections. Then scan the wiki for notes that connect *thematically* — not just by exact name match:

- **Concept notes** the source touches even if it doesn't use the canonical name (e.g., a piece on "automation frameworks" connects to `[[Building Over Finishing]]` if that pattern is what the framework is meant to defeat).
- **Active projects** whose status, decision log, or open-flags are affected by the source — append a one-line "External input" or update note in the project's relevant doc.
- **Patterns** in `[[patterns]]` that the source provides evidence for or against. Append a one-line citation under that pattern's instances list.
- **People hubs** whose ongoing background context the source updates (e.g., a legal source updates `[[{{YOUR_NAME}}]]` Background; a podcast on a mentor updates that mentor's stub).
- **Sister sources** in `00 Notes/sources/` covering adjacent material — surface a `## Related sources` cross-link.

For each candidate cross-reference, propose to you with a one-line rationale ("Source argues X; this connects to your `[[Y]]` note because Z"). You confirms or rejects each. On confirm, inject:
- A `[[<source-note>]]` reference in the appropriate section of the target note (Mentioned in / Related / Background / External input / Open flags).
- A reciprocal `[[<target>]]` reference in the source note's `## Related` section if not already present.

Default target: 5–15 page touches per substantive ingest. Trivial sources (a single-page reference, a news clip) may legitimately touch only 1–2. If the LLM proposes <3 touches for a substantive source, treat that as a signal to scan harder before stopping.

**5c. Registry updates**
- Append entry to `index.md` under `## 00 Notes/sources/<domain>/` (sources are domain-organized — see `index.md`).
- Add to `hot.md` "Recently referenced notes".
- Append a one-line entry to `log.md` if it exists (chronological ingest record).

### Step 6 — Batch mode
If you runs `/ingest all` while the inbox has multiple sources, process all of them in parallel. Each becomes its own source note. Cross-reference relationships across the batch (if source A and source B both mention concept X, they end up linked through the X stub note).

### Step 7 — Confirm
Print to you:
- Note path written (with the routed `sources/<domain>/` subfolder)
- Source type detected
- Entities extracted (counts by category)
- Stubs created (list)
- **Pages touched**: total count + breakdown (e.g., "12 pages touched: 4 entity backlinks, 3 thematic cross-refs, 2 pattern citations, 2 project doc updates, 1 source note created"). Aim 5–15 for substantive sources; flag if outside that range.
- Wikilinks injected (count + 3 examples)
- 3 key claims for spot-check

## Permissions
Same as `/sync` and `/save` — create notes and stubs, update index/hot.

## Difference from /sync
| | /sync | /ingest |
|---|---|---|
| Trigger | Walks inbox/ | Single explicit source |
| Source location | inbox/ | Anywhere (URL, file, paste) |
| Type detection | Mixed bag | Source-content-aware (article, paper, etc.) |
| Output structure | Routed to projects/notes/journals based on content | Always under 00 Notes/sources/<domain>/ |
| Asks user | Per-item routing | Only if title/source-type unclear |
| Wiki touches | Per-item entity backlinks | 5–15 page touches via Step 5b densification pass |

Use `/sync` to process accumulated capture. Use `/ingest` when you have a specific thing to lock in.

## Log entry
After the ingest completes, append a one-line entry to `[[log.md]]` at the vault root:
- Format: `## [YYYY-MM-DD HH:MM] ingest | <source title> | <pages touched>`
- Example: `## [2026-04-30 11:48] ingest | [example article] | 11 pages touched (4 entity backlinks, 3 thematic cross-refs, 2 pattern citations, 2 project doc updates)`
- Append-only — never edit existing log entries.

## Required output format (added 2026-05)

Every source note created by `/ingest` MUST follow this structure (per `00 Notes/_NOTE_FORMAT.md`):

```markdown
---
type: source
source-url: <URL>
source-author: <author if known>
ingested: YYYY-MM-DD
domain: <subfolder under sources/>
tags: [list]
---

# <Source Title>

## TLDR
<ONE SENTENCE summary. Required. Skills index-scan TLDRs before loading full content.>

## Key claims
<bulleted list, each claim ≤1 line. IMMUTABLE after ingest — never rewrite these.>

## Quoted highlights
<5-15 word quotes max, in quotation marks, with no editorializing. IMMUTABLE.>

## My take
<empty initially. The user owns this section. Append-only after first write.>

## Counter-Arguments & Data Gaps
<populated by divergence-check pass after ingest, OR inline if `/ingest` runs with `--challenge` flag.
Format:
- **Counter-argument:** <strongest objection to the source's thesis>
- **Data gap:** <what's missing that would change conclusions>
- **Tension with:** [[Other Note]] — <describe contradiction>>

## Connected concepts
<wikilinks to relevant entity / concept pages — populated by densification pass.>
```

**Behavior change:** if running `/ingest <source> --challenge`, automatically run a divergence pass on the new note before exiting (calls `/divergence-check` on just this page).

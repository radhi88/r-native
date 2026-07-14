---
name: typed-links
description: Zero-LLM-call regex extractor that scans vault markdown, finds wikilinks, infers typed edges (works_at, attended, founded, invested_in, advises, member_of, lives_in, drives, owns, represents, clients, attends_school), and writes a typed-edges.jsonl index at vault root. Adopted as auto-link pattern.
creator: claude
created: <run-date>
source: your-brain v2 upgrade (C)
model: none (deterministic regex)
---

# /typed-links

## Purpose

Pluto's wikilinks `[[X]]` carry no relationship type. The reader (Claude, pluto, Obsidian graph view) sees that page A mentions entity B, but not *how* A relates to B. `/typed-links` solves this with a zero-LLM regex pass that runs across the vault and extracts **typed edges**:

```
[[Alice Example]] works at [[Acme Law Firm]]
→ EDGE: works_at(alice-example, acme-law-firm)

[[Alice Example]] drove the [[2022 Example Sports Car]] until the totaling event date
→ EDGE: drove(alice-example, 2022-example-sports-car)

[[Pluto]] attends [[Example University]]
→ EDGE: attends_school(pluto, example-university)
```

The output (`typed-edges.jsonl` at vault root) is a structured graph that Claude can query in addition to vector / keyword search.

## When to run

- Manually: `/typed-links` or "extract typed links" or "wire the graph"
- After `/sync` finishes (suggest at end of `/sync` summary)
- After `/refine` makes structural changes
- On cron via the dream cycle (Phase 2 scheduled task)
- After a large content drop (a large content drop, OpenAI export, etc.)

## Conventions followed

- `conventions/quality.md` — output cites source page + line range for every edge
- `conventions/page-format.md` — reads compiled-truth section preferentially; weights timeline-section evidence lower (timeline events are append-only history, less indicative of current state)
- `conventions/test-before-bulk.md` — first run on a 3-5 page sample; show pluto the extracted edges + confidence; await greenlight for full vault

## End-to-end behavior

### 1. Discover input

- Walk `00 Notes/` recursively, including `people/`, `companies/`, `places/`, `concepts/`, `vehicles/`, `saved-chats/`, `email-threads/`, `sources/`, `videos/`, `research/`.
- Walk `01 Journals/daily/`.
- Walk `03 Projects/*/` (excluding `inputs/voice-samples/` and any `node_modules/`).
- Skip `_template.md`, `_blocklist.md`, `lint-reports/`, `media/`, `.obsidian/`.
- Output: list of markdown file paths.

### 2. Parse each file

For each file:

- Strip frontmatter (preserve `slug` and `type` fields for the page's own identity).
- Strip fenced code blocks (```...``` and ~~~...~~~).
- Strip inline code (`...`).
- Find all wikilinks `[[Page Name]]` and `[[Page Name|Display Text]]`.
- For each wikilink, capture the surrounding context window (≈120 chars before, ≈120 chars after, single line preferred).

### 3. Apply pattern cascade

Run the surrounding context against the pattern cascade (in priority order — first match wins):

| Pattern (regex, case-insensitive) | Edge type |
|---|---|
| `\bfounded\b.{0,40}\[\[` or `co[- ]?founder\b.{0,40}\[\[` | `founded` |
| `\binvested in\b.{0,40}\[\[` or `\bbacker of\b.{0,40}\[\[` | `invested_in` |
| `\badvises\b.{0,40}\[\[` or `\badvisor to\b.{0,40}\[\[` | `advises` |
| `\b(CEO\|CTO\|CFO\|COO\|VP\|director\|head of)\b[^\[]{0,40}\[\[` then `(of\|at)\s*\[\[` | `works_at` |
| `\bworks at\b.{0,30}\[\[` or `\bemployed by\b.{0,30}\[\[` | `works_at` |
| `\bmember of\b.{0,30}\[\[` or `\bjoined\b.{0,30}\[\[` | `member_of` |
| `\battended\b.{0,30}\[\[` (in meeting page context — type:meeting in frontmatter) | `attended` |
| `\battends\b.{0,30}\[\[` (in school/college context — keyword "school", "university", "college") | `attends_school` |
| `\b(lives\|lived) in\b.{0,30}\[\[` or `\bfrom\b\s*\[\[` (with place type) | `lives_in` |
| `\b(drives\|drove\|owns\|owned\|totaled)\b.{0,30}\[\[` (with vehicle type) | `drives` (current) or `drove` (past) |
| `\bclient\b.{0,30}\[\[` or `\b\[\[.*\]\] is a client\b` | `client_of` |
| `\brepresents\b.{0,30}\[\[` (lawyer/legal context) | `represents` |
| `\bretained\b.{0,30}\[\[` (legal/professional service) | `retained` |
| `\bmentions?\b.{0,30}\[\[` (fallback for chat / email context) | `mentions` |
| (no pattern matched) | `references` (low-confidence default) |

Each match emits an edge.

### 4. Resolve target

Each wikilink targets a page name. Resolve to a slug:

- Exact filename match in `00 Notes/{type}/`: use the canonical slug.
- Alias resolution: if the target page has frontmatter `aliases: [...]`, match against those.
- Slug-not-found: emit edge with `target_status: unresolved` so `/lint` can flag dead links.

### 5. Score confidence

- Pattern matched + target resolved + within compiled-truth section: **0.9–1.0**
- Pattern matched + target resolved + within timeline section: **0.6–0.8**
- Pattern matched + target unresolved: **0.5** (flag as dead-link candidate)
- Default `references` fallback: **0.2**

### 6. Within-page dedup

If the same `(source, target, type)` edge appears multiple times within one page, collapse to one edge with `evidence_count: N`. Don't emit duplicates.

### 7. Multi-type allowance

The same `(source, target)` pair CAN have multiple types — e.g. a person can `works_at` AND `advises` the same company. Emit each as a separate edge.

### 8. Stale-link reconciliation

If a previous run produced an edge for `(source, target, type)` and the current run doesn't, mark the old edge as `stale: true` in the output. `/refine` can then prune.

### 9. Write `typed-edges.jsonl`

Append-style write to `typed-edges.jsonl` at vault root. Each line:

```json
{"source":"00 Notes/people/alice-example.md","source_slug":"alice-example","target_slug":"acme-law-firm","type":"works_at","confidence":0.92,"evidence":"...civilian counsel [[Alice Example]] of [[Acme Law Firm]]...","section":"compiled-truth","extracted_at":"<recent-month>-15T14:30:00Z","run_id":"typed-links-<run-date>"}
```

### 10. Summary report

Print:
- N edges extracted across M source pages
- Top-10 most-connected entities (highest in-degree)
- Unresolved targets (dead-link candidates)
- Stale edges from prior run

Also write a summary to `00 Notes/lint-reports/typed-links-YYYY-MM-DD.md`.

## Implementation

The pattern cascade is implemented in `05 Skills/scripts/typed-links-extract.py`. Run:

```
python "05 Skills/scripts/typed-links-extract.py" --vault "<your-vault>"
```

Flags:
- `--vault PATH` — vault root (required)
- `--sample N` — process only N files (for test-before-bulk)
- `--dry-run` — extract but don't write `typed-edges.jsonl`
- `--since YYYY-MM-DD` — incremental, only files modified after date
- `--out PATH` — alternate output path

## Failure modes prevented

Without typed-links, asking Claude "who works at Conway and Gary Myers" requires Claude to grep the vault, read prose, and infer the relationship — slow and unreliable. With typed-links, the answer is one line in `typed-edges.jsonl`: filter `type: works_at, target_slug: acme-law-firm`.

## Limitations honest

Regex extraction misses things LLM extraction would catch — passive voice ("the firm Alice represents"), pronominal reference ("she works at Acme; she met with..."), implicit relationships. That's the tradeoff for zero LLM cost. Tier-2/3 enrichment passes (via `/refine`) can LLM-enrich the most-connected entities; typed-links handles the long tail at zero cost.

## Next steps after first run

1. Inspect the top-10 most-connected entities — do they match pluto's intuition of who/what is central?
2. Inspect unresolved targets — these are dead wikilinks or alias-mismatch candidates for `/refine`.
3. Spot-check 5 random edges for false positives. If false-positive rate > 10%, tune patterns in `extract.py`.
4. Re-run on cron via dream-cycle scheduled t
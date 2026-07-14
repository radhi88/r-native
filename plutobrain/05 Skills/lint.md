---
name: lint
description: Read-only vault health check. Reports orphans, dead wikilinks, unexpanded stubs, duplicate-name candidates, missing frontmatter, missing backlinks, and stale claims. Mirrors claude-obsidian's "lint the wiki" command.
---

# /lint

## Purpose
Vault hygiene. Over time, vaults accumulate orphans (notes nothing links to), dead wikilinks (links to notes that don't exist), unexpanded stubs (created and forgotten), and duplicates. `/lint` does a full health scan and reports findings. Read-only by default — you decides what to fix.

## When to invoke
- `/lint` — full vault scan
- `/lint <folder>` — scan a specific folder (e.g., `/lint 00 Notes/concepts/`)
- "lint the wiki," "check the vault," "vault health check"

## Recommended cadence
Monthly. Or whenever the vault feels messy.

## Behavior

### Step 1 — Scan all notes
Walk every `.md` file in the vault (skip `.obsidian/`, `.git/`, `inbox/.last-sync`). Build internal indexes:
- File index: every note path
- Backlinks index: who links TO each note
- Frontmatter index: notes with/without YAML frontmatter
- Stub index: notes with `type: <stub category>` or `status: stub` in frontmatter

### Step 2 — Run 9 health categories

**1. Orphans** — Notes with zero incoming wikilinks. Excludes:
- Vault root files (`CLAUDE.md`, `GOALS.md`, `patterns.md`, `hot.md`, `index.md`, `SETUP GUIDE.md`)
- Daily journal entries (orphaned daily notes are normal)
- Project root `CLAUDE.md` files
- Vault skills: `05 Skills/*.md` (invoked by name, not wikilink)
- Slash commands: `.claude/commands/*.md` (invoked by `/<name>`, not wikilink)
- Claude Code skills: `.claude/skills/*.md` (same logic)
- Agent definitions: `.claude/agents/*.md` (same logic)

**2. Dead wikilinks** — `[[Wikilinks]]` that point to non-existent notes.

**3. Unexpanded stubs** — Stub notes (`status: stub` in frontmatter) that have:
- No content beyond the stub template
- Last modified date ≥ 60 days ago
Either expand them or archive.

**4. Duplicate-name candidates** — Notes with similar names suggesting potential merges:
- Exact filename match across folders
- Levenshtein distance < 3 within the same entity-type folder (e.g., two `00 Notes/concepts/X.md` and `00 Notes/concepts/X-trading.md`)

**5. Missing frontmatter** — Notes without YAML frontmatter (`---` block at top). Skip if note is a vault-root meta file or a daily journal.

**6. Missing backlinks on stubs** — Stub notes that don't list any "First mentioned in" / "Mentioned in" backlinks. Either the stub was created manually without source attribution, or `/sync` didn't append the backlink correctly.

**7. Stale claims** — Notes whose frontmatter `last_verified` (if present) is > 90 days old AND content makes time-sensitive claims (numbers, dates, prices).

**8. Index drift** — Files in the vault that don't appear in `index.md`, or `index.md` entries that point to missing files.

**9. Stale open flags** — Active flags in `00 Notes/open-flags.md` that were filed > 30 days ago. Surface each with its filing date and original description so you can either resolve it (move to Resolved with a note) or restate why it's still pending.

### Step 3 — Write report
Output: `00 Notes/lint-reports/YYYY-MM-DD-lint.md`

```markdown
---
type: lint-report
date: YYYY-MM-DD
total_notes_scanned: <count>
issues_found: <count>
---

# Lint Report — YYYY-MM-DD

## Summary
- Notes scanned: <count>
- Issues found: <count>
- Vault health: <healthy | needs-attention | drifting>

## 1. Orphans (<count>)
*Excludes: vault root meta, daily journals, project root `CLAUDE.md`, `05 Skills/*.md`, and `.claude/{commands,skills,agents}/*.md` — all of those are invoked by name rather than by wikilink, so absence of incoming wikilinks is by design.*

- `path/to/note.md`
- ...

## 2. Dead wikilinks (<count>)
| In note | Link target (missing) |
|---|---|
| `path/note-a.md` | `[[Missing Note]]` |

## 3. Unexpanded stubs (<count>)
- `00 Notes/people/Someone.md` (stub since YYYY-MM-DD)

## 4. Duplicate-name candidates (<count>)
- `00 Notes/concepts/Goldbach.md` ↔ `00 Notes/concepts/Goldbach-Power-Of-3.md`

## 5. Missing frontmatter (<count>)
- `path/to/note.md`

## 6. Stubs without backlinks (<count>)
- `00 Notes/concepts/Foo.md` (created YYYY-MM-DD, no source)

## 7. Stale time-sensitive claims (<count>)
- `path/to/note.md` (last_verified: YYYY-MM-DD, mentions specific numbers)

## 8. Index drift (<count>)
- File not in index: `path/to/note.md`
- Index entry without file: `path/to/missing.md`

## 9. Stale open flags (<count>)
- **YYYY-MM-DD** (<days>d old) — <original flag description>

## Recommended actions
- <Suggest specific actions for the highest-impact fixes>
```

### Step 4 — Optional fix prompts
After report, offer you specific fixes:
- "Expand or archive these 5 stubs?"
- "Fix index.md drift (auto, write changes)?"
- "Add missing frontmatter to these 3 notes?"
- Each fix is gated on you's confirmation. Lint never modifies content silently.

### Step 5 — Print summary
Show counts per category and the report path. You opens the report in Obsidian.

## Permissions
- ✅ Scan all vault files (read-only)
- ✅ Write the lint report under `00 Notes/lint-reports/`
- ❌ Modify any other notes — fixes only happen with explicit you confirmation

## Notes
- Lint is read-only by default. Even when you says "fix it," each fix is one-by-one with confirmation.
- Don't lint runs/active artifacts (those are work-in-flight).
- Don't lint inbox/ (that's `/sync`'s job).

## Log entry
After the lint completes, append a one-line entry to `[[log.md]]` at the vault root:
- Format: `## [YYYY-MM-DD HH:MM] lint | <issue counts or 'clean'> -> <report path>`
- Example: `## [2026-05-08 09:14] lint | 3 orphans + 5 dead wikilinks + 2 duplicate-name candidates -> 00 Notes/lint-reports/lint-2026-05-08.md`
- Append-only — never edit existing log entries.

## New checks (added 2026-05)

In addition to orphans / dead wikilinks / unexpanded stubs / duplicate-name candidates / missing frontmatter / index drift, `/lint` now also reports:

### Missing TLDR
Any note (any type) without a `## TLDR` section is flagged. TLDR is required because skills index-scan TLDRs before deciding to load full content. A note without a TLDR forces full-page loads on every search, wasting tokens.

**Auto-fix offer:** lint can suggest a generated TLDR per page (user approves before insertion).

### Missing Counter-Arguments & Data Gaps section
Any concept page (`type: concept`), source page (`type: source`), or synthesis page in `00 Notes/research/` without a `## Counter-Arguments & Data Gaps` section is flagged.

**Auto-fix offer:** lint suggests running `/divergence-check` on flagged pages to populate the section.

### Contradiction detection
Lint scans page bodies for claims that contradict claims in other pages. Flags pairs of pages with conflicting content for user review.

**Examples of contradictions to flag:**
- Page A says "X is the best Y" — Page B says "Y has fundamental problems and we should avoid it"
- Page A says event happened on date X — Page B says same event happened on date Y
- Page A's `status: active` — Page B references it as `status: archived`

**Output format:**
```
CONTRADICTION:
 [[Page A]] says: "<excerpt>"
 [[Page B]] says: "<excerpt>"
 Suggested action: review and reconcile, OR document the disagreement on both pages.
```

### Stale claims
Pages whose newest source citation is older than the page's last update by 6+ months are flagged as potentially stale. Suggests `/autoresearch` to refresh.

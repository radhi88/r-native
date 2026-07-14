---
name: refine
description: On-demand vault refinement — walks notes interactively to enrich, delete, merge, or recategorize. Universal across all entity types and note categories. The cleanup + context-enrichment pass that complements /sync's create-only behavior.
---

# /refine

## Purpose

`/sync` creates and routes notes. Over time the vault accumulates noise (low-value stubs that came in incidentally), drift (notes that need recategorization), thin context (stubs that haven't grown), and duplicates. `/refine` is the cleanup + enrichment pass that fixes these by walking notes interactively and asking you what to do with each.

`/refine` is **on-demand**, not scheduled. Run when:
- You feel the vault is getting cluttered
- After a big `/sync` that created lots of new stubs (e.g., the gmail-extract import)
- Periodically to grow context on existing stubs as new related content lands
- Before a `/lint` review when you want to clean rather than just see issues
- Any time you says "let's clean up the vault" or similar

## Scope arguments

```
/refine # Walk EVERYTHING — all stubs and notes (longest run)
/refine companies # 00 Notes/companies/
/refine people # 00 Notes/people/
/refine places # 00 Notes/places/
/refine concepts # 00 Notes/concepts/ (recursive into subfolders)
/refine concepts/trading # Specific subfolder
/refine vehicles # 00 Notes/vehicles/
/refine sources # 00 Notes/sources/
/refine email-threads # 00 Notes/email-threads/
/refine saved-chats # 00 Notes/saved-chats/
/refine research # 00 Notes/research/
/refine setup # 00 Notes/setup/
/refine projects # 03 Projects/ (recursive)
/refine <specific-file-path> # Single file
```

Default scope when invoked with no args: prompt you to choose, with counts displayed for each scope so he can pick a manageable batch.

## Behavior — walks each note in scope

For each note in scope, in order (alphabetical by filename within folders):

### Step 1 — Read the note + gather context
- Read full note content
- Search vault for incoming wikilinks (who else references this note?)
- Search saved-chats / email-threads / sources / research for references to the entity
- Check the entity's frontmatter (type, status, tags, created date, source)

### Step 2 — Propose action

Present to you:
```
[note 7 of 31]
File: 00 Notes/companies/<name>.md
Type: company
Created: 2026-04-29 from gmail-life-extract
Status: stub
Backlinks: 3 incoming (X, Y, Z)
References: 4 mentions across vault content
Content: <2-3 sentence preview>

Proposed action: <KEEP | DELETE | ENRICH | MERGE | MOVE | RENAME>
Reasoning: <one-line explanation of why this action is proposed>
```

Action proposals based on:
- **DELETE**: No vault content meaningfully references the entity beyond the original creation source. Looks like incidental noise (e.g., a service mentioned once in a vendor receipt). You confirms.
- **MERGE**: Another stub exists for what looks like the same entity (e.g., `Hunter.io` and `hunterio.com` would be merge candidates). Propose target stub; you confirms or chooses.
- **MOVE**: Frontmatter type doesn't match folder location, OR the entity fits a more specific subfolder (e.g., a trading concept in concepts/ root should move to concepts/trading/).
- **RENAME**: Filename doesn't match canonical name (e.g., `Hunter-io.md` should be `Hunter.io.md` to match real domain).
- **ENRICH**: Vault has substantive references that the stub doesn't yet incorporate. Claude proposes additional content sections based on existing references.
- **KEEP**: Stub is fine as-is; no changes proposed.

### Step 3 — You chooses

You responds with:
- `keep` — accept proposal as KEEP, no changes
- `delete` — confirm deletion (Claude removes file + cleans up wikilinks pointing to it)
- `enrich` — accept proposed enrichment; Claude writes the additions
- `merge <target>` — merge into target stub; Claude combines content + redirects backlinks
- `move <new-path>` — relocate file to new path; Claude updates frontmatter type if needed
- `rename <new-name>` — rename file; Claude updates wikilinks pointing to old name
- `skip` — leave alone for now, move to next
- `quit` — stop the run; resume later from where left off

Multi-step actions can be combined: `enrich, then move concepts/trading/` would do both.

### Step 4 — Execute and persist

- Execute the chosen action
- Update `00 Notes/lint-reports/refine-<YYYY-MM-DD>.md` with the action taken
- Update `index.md` if structure changed
- Move to next note

### Step 5 — On scope completion

Print summary:
- Notes walked
- Actions taken (counts by type)
- Notes deleted (list)
- Stubs merged (list of merges)
- Stubs enriched (list)
- Stubs moved (list of relocations)
- Time elapsed
- Vault health check: any wikilinks now broken from deletions

## Resumability

Long runs can be paused (`quit`) and resumed. `/refine` saves progress to `00 Notes/lint-reports/refine-progress-<YYYY-MM-DD>.json` with the list of notes already processed in the current scope. Re-running `/refine <same-scope>` picks up where it left off.

## Enrichment proposal sources

When proposing ENRICH action, Claude searches:
1. `00 Notes/saved-chats/` — Claude conversations that mention the entity
2. `00 Notes/email-threads/` — gmail correspondence
3. `00 Notes/sources/` — ingested documents (URLs, PDFs)
4. `00 Notes/research/` — research outputs
5. Vault root meta files (`CLAUDE.md`, `GOALS.md`, `patterns.md`, identity hubs)

Proposed enrichment is shown as a diff: existing stub on left, new content additions on right. You approves before writing.

## Permissions

Per you's standing /sync grant + this skill's purpose:
- ✅ Delete files when you explicitly confirms
- ✅ Move files between folders
- ✅ Rename files (and update wikilinks pointing to the old name)
- ✅ Merge stubs (combine content, append backlinks from merged stub to target)
- ✅ Enrich stubs with content drawn from existing vault references
- ❌ Modify journal entries, voice samples, or saved-chat bodies (those are you's writings — protected)
- ❌ Delete files without explicit per-file confirmation (one wrong batch action could lose real work)

## When NOT to use

- During a `/sync` run (race condition on stub creation)
- For reorganizing folder structure (use direct file ops or `/sync rebuild-index` instead)
- For one-off fixes to a single known file (just edit it directly)

## Output

- `00 Notes/lint-reports/refine-<YYYY-MM-DD>.md` — full action log of the session
- (optionally) `00 Notes/lint-reports/refine-progress-<YYYY-MM-DD>.json` — resume state if quit mid-run

## Log entry
After the refine pass completes (or pauses), append a one-line entry to `[[log.md]]` at the vault root:
- Format: `## [YYYY-MM-DD HH:MM] refine | <scope> | <action counts>`
- Example: `## [2026-04-30 17:18] refine | companies (notes 1-14 of 35) | 3 DELETE, 4 ENRICH, 7 KEEP — paused at note 14, resume key in refine-progress-2026-04-30.json`
- Append-only — never edit existing log entries. If a refine pass spans multiple sessions (resume), each session gets its own log entry.

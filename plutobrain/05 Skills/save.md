---
name: save
description: Save the current Claude conversation (or pasted content) to the vault as a clean wiki note with frontmatter, entity wikilinks, and index updates. Pairs with /sync (which handles inbox items) — /save handles live conversations.
---

# /save

## Purpose
When you is mid-conversation with Claude (in this Claude Code session, Claude Desktop with MCP, or anywhere) and wants to lock the conversation into the vault as durable knowledge, `/save` does it cleanly. The output is graph-connected (wikilinks injected, stubs created, index updated) so future Claude sessions can find and reuse it.

## When to invoke
- You types `/save` or `/save <title>`
- You says "save this conversation," "lock this in," "remember this," "add this to my brain"
- After a particularly useful debugging session, decision conversation, or research thread

## Behavior

### Step 1 — Determine title and destination
- If invoked as `/save <title>`, use the provided title (slug it for the filename).
- If invoked as just `/save`, ask you: "What should this be titled?"
- Suggest a slug-friendly title if you provides a long one.

### Step 2 — Determine save location
Based on conversation content, propose a destination:
- Project-specific conversation → `03 Projects/<project>/notes/<title>.md`
- Trade or trading concept → `03 Projects/[your-content-project]/voice-samples/` or `00 Notes/concepts/<topic>.md` if conceptual
- Personal reflection → `01 Journals/reflections/<date>-<title>.md`
- Research / explanation → `00 Notes/saved-chats/<title>.md` (default)
- Decision / pre-mortem-adjacent → `04 Reviews/<period>/<title>.md`

Default fallback: `00 Notes/saved-chats/YYYY-MM-DD-<slug>.md`. Confirm with you if non-default.

### Step 3 — Write the note with structured frontmatter
```markdown
---
type: saved-chat
title: <title>
created: YYYY-MM-DD
source: claude-conversation
session_context: <one line — what was the topic / what triggered the save>
tags: [<auto-extracted tags>]
status: live
---

# <title>

> Saved from a Claude conversation on YYYY-MM-DD.

## TL;DR
<2-3 sentence summary of what was discussed and concluded>

## Conversation summary
<Compressed narrative of the discussion. Not a verbatim transcript — an
articulated, edited version that captures the key reasoning steps. Drop
filler exchanges. Keep the substance.>

## Decisions / conclusions
- <Each concrete decision or conclusion that came out of the conversation>

## Open questions
- <Anything still unresolved>

## Related
<Wikilinks injected for entities/projects/concepts mentioned. Per /sync rules.>
```

### Step 4 — Entity extraction + wikilinks
Run the same entity extraction as `/sync`:
- Identify people, projects, places, concepts, companies, dates
- For existing canonical notes: inject `[[wikilinks]]`
- For new significant entities: create stub notes (per `/sync` permissions)
- For one-off mentions: leave as plain text

### Step 5 — Update index.md and hot.md
- Append a line to `index.md` under the appropriate section
- Add this saved-chat to `hot.md` "Recently referenced notes" (it's now hot)

### Step 6 — Append backlinks
For every stub note that this saved-chat references (via wikilinks), append a backlink to the stub's "First mentioned in" / "Mentioned in" list.

### Step 7 — Confirm
Print to you:
- Path written
- Title locked
- Wikilinks injected (count + 3 examples)
- New stubs created (list)
- index.md / hot.md updated

## Permissions
- ✅ Create new notes anywhere in the vault per route logic
- ✅ Create stub notes for new entities (same as /sync)
- ✅ Append to index.md and hot.md
- ❌ Edit you's existing journals or notes without asking

## Versioning
Skill added 2026-04-29 alongside the other claude-obsidian-inspired commands (/autoresearch, /canvas, /lint, /ingest). Pairs with `/sync` (inbox processing) — both share entity extraction + wikilink + stub creation logic.

## Log entry
After the save completes, append a one-line entry to `[[log.md]]` at the vault root:
- Format: `## [YYYY-MM-DD HH:MM] save | <conversation title> -> <path>`
- Example: `## [2026-04-30 10:42] save | Scope C YouTube channel integration build -> 00 Notes/saved-chats/2026-04-30-scope-c-youtube-integration.md`
- Append-only — never edit existing log entries.

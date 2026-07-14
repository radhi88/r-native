---
name: sync
description: Cross-context ingestion. Processes inbox/ items, extracts entities, generates wikilinks for graph population, creates stub notes for new entities, routes content to its proper home. Replaces and supersedes inbox-route.
---

# /sync

## Purpose
You interacts with Claude across many contexts: this Claude Code session in the vault, Claude Desktop with filesystem MCP, claude.ai web, other Claude Code sessions in sister projects ([your-business-folder], [automation-project]), phone via Dispatch, voice memos. **`inbox/` is the universal capture zone.** This skill is the universal ingestion: anything that lands in `inbox/` from any context gets type-detected, entity-extracted, wikilink-injected, stub-noted where appropriate, and routed to its proper home.

The point of the skill: **populate the Obsidian graph view with real cross-references** so the vault is a true second brain, not a filing cabinet.

## When to run
- You says `/sync`, "run sync", "process my inbox," "sync everything," or similar.
- Whenever `inbox/` has more than ~5–10 items.
- After dropping in an export from another context (claude.ai chat export, Claude Desktop chat without MCP auto-write, voice transcript).
- Suggest running it at the start of each daily-note creation.

## End-to-end behavior

### 1. Scan
- List all items in `inbox/` (skip `README.md` and `.last-sync`).
- Read `inbox/.last-sync` (if exists) to get last run timestamp. Process only items modified after that timestamp unless you says "resync everything."
- Show count + filenames.

### 2. For each item: detect type
Detect from filename + content:
- **Raw note** — short markdown or text snippet, unstructured
- **Chat export** — markdown with role tags (`User:`, `Assistant:`, `Human:`, `Claude:`, `**You**`, etc.)
- **Voice transcription** — Whisper output style (timestamps `[00:01:23]`, monologue text)
- **Screenshot** — `.png`/`.jpg`/`.jpeg`
- **Trade journal** — mentions ICT terms, P&L numbers, futures contracts, specific session dates
- **Project artifact** — references a known project name from `03 Projects/`
- **Idea capture** — short, action-oriented ("I want to…", "What if…", "Build a…")
- **Reflection / journal** — first-person retrospective tone, no timestamps
- **Mixed / ambiguous** — flag for you to confirm

### 3. For each item: extract entities
Run a single Claude API call over the item content with the explicit objective: identify
- **People** mentioned (names; family, friends, business contacts, public figures)
- **Projects** mentioned ([Your Business], , [your-content-project], [automation-project], you-mind, etc.)
- **Places** mentioned (cities, locations, venues)
- **Concepts / topics** mentioned (ICT, Goldbach, Tesla 369, peptides, prop firms, etc.)
- **Dates** mentioned (resolve to YYYY-MM-DD where possible — "last Tuesday" → actual date)
- **Companies / brands** mentioned (brand and company names mentioned in the content)

Output: a structured list per item with category + value pairs.

### 4. For each entity: link or stub
For each extracted entity:

**Search the vault** for an existing canonical note matching the entity name (fuzzy match — case-insensitive, partial-match acceptable). Look in:
- `00 Notes/people/`, `00 Notes/places/`, `00 Notes/concepts/`, `00 Notes/companies/` (entity stub locations)
- `03 Projects/` (project notes by folder name)
- `01 Journals/daily/` (date entities)

**If found:** generate a wikilink `[[Existing Note Name]]` to inject into the destination content.

**If not found AND entity is significant** (mentioned multiple times in the item, OR matches a tracked entity-type, OR you previously flagged it as track-worthy):
- **Create a stub note** at:
 - People: `00 Notes/people/<name>.md`
 - Places: `00 Notes/places/<place-slug>.md`
 - Concepts: `00 Notes/concepts/<concept-slug>.md`
 - Companies: `00 Notes/companies/<company-slug>.md`
 - Projects: **DO NOT auto-create.** Surface to you: "Detected possible new project '<name>' — create `03 Projects/<slug>/` structure now?" Projects are bigger commitments; require greenlight.

**Stub note content:**
```markdown
---
type: <person|place|concept|company>
created: YYYY-MM-DD
source: sync from inbox
status: stub
---

# <Entity Name>

> Stub note. Add context as it emerges. Auto-created by /sync.

## First mentioned in
- [[<source-note-name>]] — YYYY-MM-DD

## Notes
*(populate as needed)*
```

**If not found AND entity is one-off** (mentioned once, no significance signal): **leave as plain text.** Don't pollute the vault with stubs for casually mentioned entities.

### 5. For each item: route to destination
For each item, present to you:
- Filename
- 2–3 sentence preview
- Detected type
- Extracted entities (grouped by category)
- **Proposed destination** (Claude's best guess based on type + entities)

**Auto-route (no confirmation) when** type AND destination are both >90% confident:
- Daily journal entry with today's date → `01 Journals/daily/YYYY-MM-DD.md`
- Trade journal mentioning today's session → daily note for today
- Chat export tagged for a specific project → that project's folder
- Idea matching an existing project's track → that project's `inputs/<track>/ideas.md`

**Otherwise ask** with options:
- Specific project: `03 Projects/<project>/<subfolder>/`
- General notes: `00 Notes/<category>/`
- Journal: `01 Journals/`
- Long-term planning: `02 Chess Moves (Long-Term Planning)/`
- Reviews: `04 Reviews/<period>/`
- Archive (delete)
- Create a new project (you names it; stub `03 Projects/<slug>/CLAUDE.md` is created)
- Create a new folder (you names + locates it)
- Keep in inbox (must give reason)

You can also free-form: "this is a marketing idea" — Claude interprets and routes.

### 6. Inject wikilinks

#### General rule
Before writing routed content to its destination, replace plain entity mentions with wikilinks. **Be conservative** — only link the entities Claude extracted in step 3. Don't link every mention of common words. First mention per entity per note typically gets the wikilink; subsequent mentions stay plain.

#### Chat exports specifically (locked 2026-04-29)
For files of `type: chat-export` (claude.ai bulk exports, Claude Desktop chat saves, any conversational artifact): **do not modify the chat body**. Chats are you's prior writings to Claude — protected by the "don't edit you's notes/journals/writings" rule from `CLAUDE.md`.

Instead, insert a synthetic `## Concepts referenced` section ABOVE the chat body (typically immediately above the `## Conversation` heading), grouped by entity type. Only include groups that have entries:

```
## Concepts referenced

Companies: [[Stub A]], [[Stub B]]
Concepts: [[Stub C]], [[Stub D]]
People: [[Stub E]]
```

If a chat has no extracted entities matching existing or newly-created stubs, insert the placeholder:

```
## Concepts referenced
*(no vault entities referenced in this chat)*
```

The placeholder makes processing-state self-evident — future `/sync` and `/lint` runs can confirm a chat was processed (had no entities) versus skipped (was never processed).

#### Other note types
Research notes (`/autoresearch`), source notes (`/ingest`), and saved-chat outputs from `/save` follow the general rule with body-level injection — those are synthesized notes, not you's own writings, so inline wikilinks are acceptable.

### 7. Append backlinks to stub notes
For each stub note that was just referenced, append to its "First mentioned in" list a backlink to the destination note that was just written:
```
- [[<destination-note-name>]] — YYYY-MM-DD
```

This is what makes the **graph view actually populate** — every stub becomes a hub of references.

### 8. Update `hot.md` (vault root)
Append to or rewrite the "Currently active threads" / "Recently referenced notes" / "Recent decisions" sections of `hot.md` at vault root to reflect what was just routed and what is now top of mind. The "Currently active threads" section should reflect 3–7 things you is actively working on. "Recently referenced notes" should be a rolling list of the last ~10 distinct notes touched.

### 9. Append deferrals to `00 Notes/open-flags.md`
If anything in this run was deferred rather than acted on (an image-durability flag, a "decide later" item surfaced during routing, a one-off batch task that should run after more data accumulates, etc.), append a row to `00 Notes/open-flags.md` under `## Active flags`:

```
- **YYYY-MM-DD** — <description; what was deferred, why, and what condition resolves it>
```

Idempotent: don't append if the same deferral is already present (match on description substring). The `open-flags.md` file is durable across `/sync` runs (unlike `hot.md` which gets rewritten) — it's the canonical home for "do this later" items. `/lint` surveils it for stale flags. When you resolves a flag, move it to `## Resolved flags` (don't delete) with a resolution date.

### 10. Update `index.md` (vault root)
If new notes, stub notes, or new folders were created during this run, append them to `index.md` in the appropriate section. Do not regenerate the whole file — append/insert. You can run `/sync rebuild-index` if a full regeneration is ever needed.

### 11. Update `.last-sync`
Write current timestamp to `inbox/.last-sync`.

### 12. Report
Print:
- N items processed
- Routing breakdown (X to projects, Y to journals, Z to notes, W archived, V kept)
- Stub notes created (list with paths)
- Wikilinks generated (count + 3 examples)
- Project structures created (if any)
- Items needing manual review (with reasons)

If any pattern from `patterns.md` was triggered by routed content (e.g., a captured "let's build a new agent system" idea matches Impulsive Project Initiation), surface the pattern at the end of the report by name.

## Permissions granted to /sync
Per you's explicit grant 2026-04-29:
- ✅ Create stub notes for new entities (people, places, concepts, companies)
- ✅ Create new files in any vault folder if needed for routing
- ✅ Create new folders if existing structure doesn't fit
- ✅ Create new project structures under `03 Projects/<slug>/` **with you's confirmation per project**
- ✅ Adjust directory structure if existing structure doesn't fit (with brief explanation in report)
- ❌ Delete content from existing notes without asking
- ❌ Move existing notes without asking
- ❌ Modify you's existing journals or writings (per `CLAUDE.md` rule)

## Cross-context capture map
How content gets into `inbox/` from various Claude contexts:

| Context | How it lands in `inbox/` |
|---|---|
| This Claude Code session (in the vault) | Direct write — `/sync` not needed for content created here |
| Other Claude Code session (e.g., [your-business-folder], [automation-project]) | The session writes directly to `C:\Users\you\Documents\you-mind\inbox\` using the absolute path |
| Claude Desktop with filesystem MCP | Claude Desktop writes directly via filesystem MCP server. **Setup doc:** `00 Notes/setup/filesystem-mcp-for-claude-desktop.md` |
| claude.ai web (no filesystem) | You exports the chat (built-in feature or copy/paste) → drops the export into `inbox/` (via cloud-sync folder if remote) |
| Phone via Dispatch / iPhone Notes / etc. | Drops to a cloud-synced folder mirrored into `inbox/` (OneDrive recommended — you already has it) |
| Voice memos | Transcribe (Whisper or OS native) → drop transcript into `inbox/` |

## Versioning
Replaces `05 Skills/inbox-route.md` (deprecated 2026-04-29). The old skill was a flat routing pass; `/sync` adds entity extraction, wikilink injection, stub-note creation, and graph population.

## Log entry
After the run completes, append a one-line entry to `[[log.md]]` at the vault root:
- Format: `## [YYYY-MM-DD HH:MM] sync | <one-line summary>`
- Example: `## [2026-05-07 14:23] sync | 8 inbox items routed: 5 chats, 2 sources, 1 idea-capture; 3 stubs created (companies); 1 deferral`
- Append-only — never edit existing log entries (per the immutable-layers convention in `[[CLAUDE]]`).

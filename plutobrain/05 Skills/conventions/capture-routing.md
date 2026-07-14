---
type: convention
name: capture-routing
creator: claude
created: <run-date>
source: your-brain v2 upgrade (C)
---

# Capture & Routing

> How items get from raw capture to final home in the vault, and which layer they live in.

## Capture zone

`inbox/` at vault root is the **universal capture zone**. Every context that produces vault-bound content writes here first:

- This Claude Code session in `<your-home>\`
- Claude Desktop with filesystem MCP
- Claudian (Obsidian plugin)
- claude.ai web (via paste-and-save)
- Other Claude Code sessions in sister projects (`dial-lab-sales`, `content-automation`)
- Phone via Dispatch / cloud sync
- Voice memos (transcribe then drop)
- Obsidian Web Clipper (via `media/from-clipper/`)

Captured items are **never routed at capture time**. Routing is `/sync`'s job. Capture-then-route is faster and lossier-safe than routing-at-capture.

## Routing pipeline (run by `/sync`)

1. **Scan** — list `inbox/*`; check `inbox/.last-sync` timestamp; process new items only unless told otherwise.
2. **Type-detect** — raw note vs chat export vs voice transcript vs screenshot vs trade journal vs project artifact vs idea vs reflection.
3. **Extract entities** — people, companies, places, concepts, vehicles, projects, dates, companies/brands.
4. **Link or stub** — wikilink existing entities; create stubs for new ones that clear the notability gate (`conventions/quality.md`).
5. **Route** — move the item to its final home based on type.
6. **Append `[[log.md]]`** — one-line chronological entry.

## Final homes by type

| Type | Final home |
|---|---|
| Raw note | `00 Notes/saved-chats/` OR appropriate entity hub |
| Chat export | `00 Notes/saved-chats/YYYY-MM-DD-slug.md` |
| Voice transcript | `00 Notes/sources/voice/YYYY-MM-DD-slug.md` |
| Screenshot | `media/images/` + reference in source note |
| Trade journal | `03 Projects/trading/journals/YYYY-MM-DD.md` |
| Project artifact | `03 Projects/<project>/inputs/` or appropriate subfolder |
| Idea capture | `00 Notes/concepts/` if it's a concept, else `02 Chess Moves/` |
| Reflection | `01 Journals/daily/YYYY-MM-DD.md` reflection section |

## Immutable vs synthesized layer

Routing must respect these boundaries:

**Immutable (LLM may move/delete/rename whole files, but never edits the body):**
- `00 Notes/sources/` after first ingestion
- `00 Notes/email-threads/`
- `01 Journals/daily/`
- `03 Projects/content-workflow/inputs/voice-samples/`

**Synthesized (LLM owns continuously):**
- `00 Notes/{people,companies,places,concepts,vehicles}/`
- `00 Notes/{research,canvases,lint-reports}/`
- `00 Notes/videos/`
- `index.md`, `hot.md`, `_blocklist.md`

**Mixed (LLM proposes; pluto approves):**
- `00 Notes/saved-chats/` — LLM writes body, pluto refines TL;DR/Decisions/Open questions
- `03 Projects/<project>/CLAUDE.md`
- `CLAUDE.md`, `GOALS.md`, `patterns.md`

See `CLAUDE.md` "Immutable vs synthesized layers" for the full enforcement set.

## Skills that must follow this

`sync`, `ingest`, `save`, `refine`, `weekly-update`.

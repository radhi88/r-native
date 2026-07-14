# PlutoBrain — Meta Layer

> Your second-brain root config. PlutoBrain is a personal AI knowledge OS — Obsidian + Claude Code + 13 skills + a self-awareness layer. Replace placeholders with your real info, then run `/brain-setup` skill for an interview-driven fill.

## Required reading before responding
Before responding to any significant request, read in this order:
1. This `CLAUDE.md`
2. `hot.md` — session cache; tells you what the user has been working on recently so you don't re-orient from scratch
3. `GOALS.md`
4. `patterns.md`
5. `index.md` — only if you need to check whether a canonical note for some entity already exists

Reference these explicitly when relevant rather than reasoning from scratch.

## Who I am
{{REPLACE: Your name, age, location. Neurotype/cognitive style if relevant. Job/income source. Major commitments (school, business, military, etc.). Vehicle/lifestyle if it matters for context. Relationships that matter for advisory work. Major life events that have shaped you (positive and negative). Be specific — Claude reads this every session and uses it to ground ALL advice.}}

EXAMPLE (replace with your own):
> Sample User, 28, Austin TX. Software engineer at a mid-size SaaS company. Married, no kids yet. Side projects: a productivity blog and an Etsy shop selling laser-cut wood art. Recovering perfectionist — tends to overplan and underexecute. Recently quit alcohol (March 2026), starting to feel sharper. Drives a 2022 Honda Civic.

## What this brain is for
{{REPLACE: Describe what kinds of thinking/work this brain supports. Be specific about WHICH workflows live here vs which ones live elsewhere.}}

EXAMPLE:
> Strategic thinking partner across my parallel workflows: blog content, side-business operations, financial planning, and personal reflection. The brain holds shared context — notes, goals, journals, project references — and reasons across all of it as my general-of-the-army layer. NOT for client work — that lives in `~/work/clients/` with its own Claude Code config.

## Communication preferences (apply to ALL conversations in this brain)
{{CUSTOMIZE THESE — they shape every response Claude gives you}}

- Be blunt and direct. Do not gentle-hedge. Blunt does not mean harsh.
- Ask clarifying questions before advising. Never assume completeness from my prompts.
- Draw information out of me. Confirm understanding before acting.
- Flag impulsive or excitement-driven patterns when you see them. Cross-reference `patterns.md`. When a known pattern is recurring, name it explicitly rather than reasoning from scratch.
- Push me toward closing loops, not opening new ones.
- Analyze probabilities and outcomes for significant decisions. Surface the highest-probability path toward my stated goals.
- When you create a file, mark it with `(C)` in the filename or in frontmatter.
- Do not edit my notes, journals, or writings without asking first.

## Strengths / weaknesses
{{REPLACE with honest self-assessment. Claude uses this to give you advice that fits your actual operating profile, not who you wish you were.}}

EXAMPLE:
> Strong at writing and synthesizing complex info. Good builder, ships products. Weaknesses: scope creep, says yes to too many opportunities, neglects health on heavy work weeks, conflict-avoidant in personal relationships.

## Capture & routing
- The `inbox/` folder at the vault root is the **universal capture zone** across every Claude context: this Claude Code session, Claude Desktop (via filesystem MCP), other Claude Code sessions in sister projects, claude.ai web (via export drop), phone Dispatch (via cloud sync), voice memos (transcribe and drop).
- The `sync` skill processes inbox contents end-to-end: detects type, extracts entities (people, projects, places, concepts, companies, dates), generates wikilinks for graph population, creates stub notes for new entities, and routes content to its proper home in the vault. Run `/sync` weekly or whenever inbox has more than ~10 items.
- When the user says "save this to inbox" or "add this to my inbox," add the item to `inbox/` with a timestamped filename. Do not try to route at capture time — `/sync` handles routing.
- `/sync` has standing permission to create stub notes and new files/folders as routing requires.

## Immutable vs synthesized layers
The vault has layered editability — structured as raw sources → wiki → schema. Skills enforce these boundaries.

**Immutable (LLM reads but never edits the body):**
- `00 Notes/sources/` — source notes after `/ingest`. Append to `## My take` only; never rewrite the TL;DR / Key claims / quoted material.
- `00 Notes/email-threads/` — email correspondence captured during gmail extracts. Thread bodies are reality-of-record.
- `01 Journals/daily/` — your daily reflections. You author; LLM never rewrites.

**Synthesized (LLM owns and continuously updates):**
- `00 Notes/{people,companies,places,concepts,vehicles}/` — entity stubs and hubs. LLM enriches sections, appends `## Mentioned in` backlinks, merges duplicates, prunes via `/refine`.
- `00 Notes/{research,canvases,lint-reports}/` — derived synthesis outputs.
- `index.md`, `hot.md`, `_blocklist.md` — registry / cache files.

**Mixed (LLM authors first; user refines selectively):**
- `00 Notes/saved-chats/` — `/save` writes the body; user can refine TL;DR, Decisions, or Open questions sections.
- `03 Projects/<project>/CLAUDE.md` and project docs — initial structure by `/new-project`; evolved by both user and the LLM.
- `CLAUDE.md`, `GOALS.md`, `patterns.md` — LLM proposes additions; user approves before they land.

**Skill enforcement:**
- `/refine` may KEEP / DELETE / MERGE / MOVE / RENAME on immutable items but never edits their body content.
- `/sync` routes inbox items but does not rewrite already-routed sources.
- `/lint` is read-only — flag issues without modifying.
- `/ingest` writes new source notes; never overwrites existing ones (it appends or creates a new dated source instead).

## Daily notes
- Daily notes live at `01 Journals/daily/YYYY-MM-DD.md`.
- The template is at `01 Journals/_daily-template.md`.
- When the user says "create today's note," "start my day," or similar, copy the template to today's date and open it.
- When the user says "end my day" or asks to fill in reflection, prompt for the reflection section of today's note.

## Skills available in this layer
Skills live in `05 Skills/` and are invoked by name (or by `/<name>` when typed):

**Core meta**
- `brain-setup` — interview-driven CLAUDE.md generator. Run this first after cloning the template.
- `new-project` — interview-driven project creation under `03 Projects/`.
- `weekly-update` — refresh context and CLAUDE.md files across the brain.
- `deep-context-fill` — gap-targeted CLAUDE.md depth interview. Run once after setup.
- `pre-mortem` — on-demand decision pre-mortem before significant commitments.

**Knowledge graph**
- `sync` — universal cross-context ingestion of `inbox/`. Entity extraction, wikilink injection, stub creation, routing.
- `save` — save the current Claude conversation as a structured wiki note with frontmatter and wikilinks.
- `ingest` — process a single specified source (URL, PDF, file, paste) into a structured source note in `00 Notes/sources/<domain>/`. **Wiki-mutating** (5–15 page touches per ingest via the densification pass — built into the densification pass).
- `query` — run a question against the vault as a knowledge base. Searches relevant pages, synthesizes a cited answer, and **files the answer back as a durable wiki page** so explorations compound.
- `autoresearch` — 3-round autonomous web research loop on a topic. Searches, fetches, synthesizes, gap-fills, cites sources. Output to `00 Notes/research/`.
- `canvas` — generate or extend Obsidian Canvas (.canvas) files for visual maps of vault content. Output to `00 Notes/canvases/`.
- `lint` — read-only vault health check. Reports orphans, dead wikilinks, unexpanded stubs, duplicate-name candidates, missing frontmatter, index drift, **missing TLDRs, missing Counter-Arguments sections, contradictions between pages**. Output to `00 Notes/lint-reports/`.
- `refine` — on-demand vault cleanup + enrichment. Walks notes interactively to enrich, delete, merge, or recategorize.
- `divergence-check` — bias-check pass on concept and synthesis pages. Generates strongest counter-arguments, surfaces tensions with other notes, identifies data gaps. Run quarterly or after one-sided source ingestion.

All knowledge-graph skills share entity extraction + wikilink + stub-note creation logic and have standing permission to create new stub notes and new files/folders during routing. All skills append a one-line entry to `[[log.md]]` (vault root, append-only chronological record).

## Active projects
{{REPLACE with your active projects. Add a one-paragraph summary for each. Reference each project's own CLAUDE.md.}}

EXAMPLE:
- `your-content-project` — active project (work happens IN the vault). Sub-project of weekly blog post production. See `03 Projects/your-content-project/CLAUDE.md`.

## Reference projects
External codebases documented in the vault for context. Code lives elsewhere; the vault has structured reference docs only. **Reference projects are NOT for active development inside the vault.**

{{REPLACE with your reference projects}}

EXAMPLE:
- `side-business-ref` — your side business operational docs. Code/files at `~/work/side-business/`. See `03 Projects/side-business-ref/CLAUDE.md`.

## Binary assets — `media/` folder
All non-markdown assets live under `media/` at the vault root:
- `media/images/` — pasted screenshots, embedded images, downloaded illustrations
- `media/pdfs/` — PDFs ingested via `/ingest`, downloaded references
- `media/audio/` — voice memos, audio attachments
- `media/from-clipper/` — assets carried in by Obsidian Web Clipper
- `media/from-notion/` — assets localized from Notion exports

**Obsidian default attachment location:** set Obsidian → Settings → Files & Links → Default location for new attachments → "In the folder specified below" → `media/images`. After this, pasting an image into any note auto-saves it under `media/images/` instead of cluttering the note's folder.

## Two-Claude workflow protocol
This vault is operated by two Claude instances:

1. **Strategist Claude (terminal)** — full context across the vault meta files, projects, etc. Generates strategic responses, scrutinizes Editor Claude outputs, surfaces patterns from `patterns.md`, drafts the next reply for you.
2. **Executor Claude (in your editor of choice)** — operates inside the vault. Executes skills, walks routing prompts, writes files, generates wikilinks, populates the graph.

**The flow:** you invoke a skill in Editor Claude → Editor Claude reports back → you paste Editor Claude's output to Strategist Claude → Strategist generates the next reply → you paste that into Editor Claude → repeat.

**When to bypass the strategist:** trivial confirmations ("y" / "n" / "proceed"), real-time data only you know (numbers, names, dates), simple format choices. Use the strategist for: routing decisions, scope decisions, scrutinizing Editor Claude's plan before letting it run, generating voice-tuned text outputs, deciding when to push back on Editor Claude if it drifts from the skill spec.

## Customization checklist (do these before first real session)
- [ ] Replace `{{YOUR_VAULT_NAME}}` everywhere
- [ ] Replace the `Who I am` section
- [ ] Replace the `What this brain is for` section
- [ ] Customize `Communication preferences` to your taste
- [ ] Fill in `Strengths / weaknesses` honestly
- [ ] Add your active projects to `Active projects` section
- [ ] Add your reference projects to `Reference projects` section
- [ ] Run `/brain-setup` skill for an interview-driven fill of any gaps
- [ ] After 1 week of use: run `/deep-context-fill` to pull deeper context from your real notes

## Wiki note format (every note follows this)

See `00 Notes/_NOTE_FORMAT.md` for the canonical reference. Brief summary:

- Every note has a YAML frontmatter block (type, created, updated, tags, status)
- Every note opens with a one-sentence **TLDR** — required, used by skills for index-scan before deciding to load full content
- Concept pages, source pages, and synthesis pages MUST include a `## Counter-Arguments & Data Gaps` section — populated by `/divergence-check`
- Every note ends with `## Mentioned in` — auto-maintained by `/sync` and `/refine`

## Token-budget tiers (progressive disclosure)

Skills follow this discipline to keep responses fast and cheap:

- **L0 (~200 tokens)** — every session: snippet of `CLAUDE.md` + current `hot.md` focus
- **L1 (~1-2K tokens)** — session start: full `hot.md`, `index.md`, recent log entries
- **L2 (~2-5K tokens)** — search results: TLDRs of relevant pages
- **L3 (~5-20K tokens)** — full articles: load ONLY after L0-L2 indicate the page is needed

**
---
type: convention
name: brain-first
creator: claude
created: <run-date>
source: your-brain v2 upgrade (C)
---

# Brain-First Lookup

> Before any external API call, web search, or "I don't know" response, run the vault lookup sequence. The vault is the system of record about pluto's life — anything pluto-adjacent should be answered from the vault before reaching outside.

## The 5-step lookup

When a request touches an entity (person, company, project, place, concept, vehicle, date, event) or a topic pluto has previously engaged with:

1. **Check `index.md`** for a canonical page name match.
2. **Check `hot.md`** for recent context — what pluto has been working on lately may already have the answer.
3. **Grep the vault** for the entity name + variants — `00 Notes/{people,companies,places,concepts,vehicles}/`, `03 Projects/`, `00 Notes/saved-chats/`, `00 Notes/sources/`, `01 Journals/daily/`.
4. **Read the matched pages** — compiled truth above `---`, timeline below for evidence.
5. **Only THEN** decide whether external lookup is needed.

## When to skip the lookup

- Pure factual questions unrelated to pluto's life ("what's the capital of France").
- Coding tasks operating on code files only.
- Computational questions ("compute the 50th Fibonacci number").
- When pluto has explicitly said "skip the brain, just answer."

If unsure whether a question is pluto-adjacent, run the lookup. The cost is low; the cost of answering without context is high.

## Failure mode this prevents

Without brain-first, Claude answers from training-data priors and ignores 12 months of accumulated vault context. Pluto then has to re-state things he's already written down. The vault becomes write-only. Brain-first makes the vault actually compound.

## Skills that must follow this

`query`, `save`, `ingest`, `sync`, `refine`, `autoresearch`, `weekly-update`, `pre-mortem`, and any future skill that responds to a pluto question or generates content about a pluto-adjacent entity. The strategist Claude (Cowork / Claude Code session in `<your-home>\`) follows this on every turn.

## Verification

`/lint` checks for skills that don't cite this convention by name. Skills missing the reference are flagged in the next lint report.

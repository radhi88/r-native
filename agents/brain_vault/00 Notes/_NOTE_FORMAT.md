# Wiki Note Format

> Reference template for how notes in this vault should be structured. Skills (`/sync`, `/ingest`, `/save`, `/refine`) follow these conventions. Update this file if you change conventions; skills will adapt.

## Universal structure (every note follows this)

```markdown
---
type: [person | company | concept | place | source | saved-chat | research | etc.]
created: YYYY-MM-DD
updated: YYYY-MM-DD # auto-updated by skills
status: [active | dormant | archived]
tags: [tag1, tag2]
---

# {{Note Title}}

## TLDR
*One-sentence summary at the top. Skills read this FIRST when deciding whether to load full content. Saves tokens. Saves time. Required.*

## {{Main content sections — type-specific}}

(see type-specific schemas below)

---

## Counter-Arguments & Data Gaps
*Required on concept pages and any synthesis page. The LLM populates this section with the strongest objections to the page's claims, contradicting evidence (if any), and acknowledged data gaps. Fights confirmation bias.*

- **Counter-argument 1:** ...
- **Data gap 1:** ...
- **Tension with:** [[Other Note]] — describe the contradiction

## Mentioned in
*Auto-maintained by `/sync` and `/refine`. Lists notes that link to this one.*

- [[Daily 2026-05-04]]
- [[Project Brief X]]
```

---

## Type-specific schemas

### Person
```yaml
type: person
relationship: [family | friend | collaborator | client | acquaintance]
first-met: YYYY-MM-DD
last-contact: YYYY-MM-DD
```
Sections: TLDR · Context · Conversations (chronological) · Counter-Arguments & Data Gaps · Mentioned in

### Company
```yaml
type: company
industry: [SaaS | hardware | media | etc.]
relationship: [vendor | client | competitor | tracking | none]
```
Sections: TLDR · What they do · Why they matter to me · My experience · Counter-Arguments · Mentioned in

### Concept
```yaml
type: concept
domain: [productivity | finance | health | etc.]
maturity: [exploring | working-theory | adopted | rejected]
```
Sections: TLDR · The idea · Why it matters · Examples · Sources · Counter-Arguments & Data Gaps (REQUIRED) · Related · Mentioned in

### Source (from /ingest)
```yaml
type: source
source-url: https://...
source-author: ...
ingested: YYYY-MM-DD
domain: [folder under sources/]
```
Sections: TLDR · Key claims (bulleted, immutable after ingest) · Quoted highlights (immutable) · My take (you author this) · Counter-Arguments & Data Gaps · Connected concepts

### Saved Chat (from /save)
```yaml
type: saved-chat
context: [claude-code | claude-desktop | claude-ai-web | mobile]
topic: ...
```
Sections: TLDR · Decisions (bulleted) · Open questions · Conversation summary · Counter-Arguments (if conclusions reached) · Mentioned in

---

## Token-budget tiers (progressive disclosure)

Skills follow this discipline:

| Tier | Budget | When loaded |
|---|---|---|
| **L0** | ~200 tokens | EVERY session — project context: `CLAUDE.md` snippet + `hot.md` |
| **L1** | ~1-2K tokens | Session start — full `hot.md`, `index.md`, recent log entries |
| **L2** | ~2-5K tokens | Search results — TLDRs of relevant pages |
| **L3** | ~5-20K tokens | Full articles — load ONLY after L0-L2 indicate this page is needed |

**The discipline:** never read full articles until you've consulted L0-L2 first. This keeps Claude fast and cheap on simple queries.

---

## Why TLDR is mandatory

When `index.md` is large or `/query` is searching across many pages, the LLM does an "index scan" — it reads TLDRs first, then decides which pages to load fully. Without TLDRs, every search loads multiple full pages, wasting tokens and time.

**Rule:** if a note doesn't have a TLDR, `/lint` flags it as an issue.

---

## Why Counter-Arguments & Data Gaps is mandatory on concept pages

If you ingest 5 articles praising a framework, your wiki will be biased toward that framework. The Counter-Arguments section forces the LLM to surface the strongest objection — even if no source explicitly made it. This is your bias check.

**Rule:** every concept page MUST have a Counter-Arguments & Data Gaps section. `/lint` flags missing ones. `/refine` populates them when found missing.

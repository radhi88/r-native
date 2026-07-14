---
type: convention
name: quality
creator: claude
created: <run-date>
source: your-brain v2 upgrade (C)
---

# Quality Standards

> The minimum bar every page in the vault must clear. Skills that write to the vault enforce these on output.

## Citation standard

Every claim in a synthesized page (above the `---` divider) that came from an external or internal source gets a citation. Format:

- **Internal source:** `[[source-note-name]]` wikilink to a `00 Notes/sources/` or other vault page.
- **External source:** `[Title or short label](url)` markdown link.
- **Date-of-knowledge:** if the fact is time-sensitive, include the date inline — e.g. *"Sample Education Benefit coverage extends through 2028 (per [[<run-date>-vre-conversation]], <run-date>)."*
- **Conversation source:** `[[YYYY-MM-DD-saved-chat-name]]` link.

A claim with no traceable source either gets a citation, gets a `[?]` marker for "claimed but unverified", or doesn't go in the synthesized section.

## Backlink standard

Entity pages (`00 Notes/{people,companies,places,concepts,vehicles}/`) have a `## Mentioned in` section at the bottom listing pages that reference the entity. `/sync` and `/refine` maintain this — manual additions are also welcome.

Anchor format: `- [[page-name]] — short context phrase (YYYY-MM-DD)`.

## Notability gate

A new entity stub gets created (via `/sync` or otherwise) only when one of these is true:

1. Entity is mentioned 2+ times across distinct sources (per `conventions/tiered-enrichment.md`).
2. Entity is materially significant to a tracked thread — open loop, active project, named in `GOALS.md`, named in `patterns.md`, named in a live `03 Projects/*/CLAUDE.md`.
3. Pluto explicitly says "track this."

Bare mentions of incidental people / companies / places do not auto-create stubs. They get the wikilink with the stub-on-creation deferred. This prevents stub bloat.

## Source attribution on synthesized pages

Pages in `00 Notes/{people,companies,places,concepts,vehicles}/research,canvases,saved-chats}` are synthesized by Claude. Frontmatter MUST include:

```yaml
creator: claude
source: <skill name or "manual">
created: YYYY-MM-DD
```

Pages in `01 Journals/daily/` and `00 Notes/sources/` are authored by pluto / source content. Frontmatter MUST include:

```yaml
creator: pluto  # or "external-source"
source: <where it came from>
```

This drives the immutable-vs-synthesized layer enforcement (see `CLAUDE.md` "Immutable vs synthesized layers").

## LLM-artifact bans

These phrases / patterns are LLM tells and should NOT appear in vault content:

- "It's worth noting that..."
- "In conclusion..."
- "Delve into..."
- Lists where every item starts with the same emoji
- Triple-nested bullet structures more than 3 deep without prose
- "I hope this helps!" / "Let me know if..."
- Em-dash overuse for hedging

`/lint` checks for these and flags pages that need rewriting.

## Skills that must follow this

Every skill that writes synthesized content: `save`, `ingest`, `sync`, `refine`, `query`, `autoresearch`, `canvas`, `weekly-update`, `new-project`, `pre-mortem`.

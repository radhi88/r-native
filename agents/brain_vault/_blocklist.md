---
type: meta
created: {{TODAY}}
status: active
tags: [meta, blocklist, vault-policy]
---

# Vault Blocklist

> Entities that have been considered and rejected as vault noise. Do NOT re-create stubs for these names during any stub-creating pass (`/sync`, `/ingest`, `/autoresearch`, etc.).
>
> Read this file before any stub creation. If a new signal seems substantive enough to override a block, surface to the user for review rather than creating silently.
>
> Manually maintained. Do NOT auto-rewrite during `/sync`. Sibling to `CLAUDE.md` / `GOALS.md` / `patterns.md` at vault root.

## How this file is used

Any process that creates entity stubs (people, companies, concepts, places, etc.) must:
1. Check the entity name against this blocklist before creating
2. If matched, skip creation
3. If the new signal seems substantive enough to override the block (genuinely new operational relationship, not just a recurring promo email or echo of historical data), surface to the user with the new signal for explicit override

When `/refine` deletes a stub for noise reasons, the entity name + reason is appended here automatically.

## How to add to the blocklist

Add an entry under the relevant category. Format:

```
- **[Entity Name]** — short reason (date)
```

Example:

```
- **Generic Newsletter Co.** — promotional emails only, no operational relationship (2026-04-15)
- **Random Networking Event Person** — one-time interaction, no follow-up planned (2026-04-22)
```

## Categories — start populating these as you encounter noise

### Companies — confirmed deleted

(empty)

### People — confirmed deleted

(empty)

### Concepts — confirmed deleted

(empty)

### Places — confirmed deleted

(empty)

---

## Override protocol

If something on this blocklist re-appears in your inbox with significantly more signal than before (e.g. a former noise-source becomes a real business contact), update the blocklist entry to note the override and create the canonical note.

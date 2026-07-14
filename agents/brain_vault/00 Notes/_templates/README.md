---
type: template-index
creator: claude
created: <run-date>
source: your-brain v2 upgrade (C)
---

# Entity Templates

> Compiled-truth + timeline templates for each entity type. Used by `/sync` when creating stubs, and by Obsidian's Templater plugin if you want to insert manually.

See `05 Skills/conventions/page-format.md` for the format spec.

## Templates

- [[person.md]] — people
- [[company.md]] — companies, organizations, brands
- [[concept.md]] — ideas, frameworks, technical concepts
- [[place.md]] — cities, venues, locations
- [[vehicle.md]] — cars, motorcycles, etc.

## Placeholders

`{{NAME}}` and `{{slug}}` are replaced by the skill creating the stub. `{{YYYY-MM-DD}}` becomes today's date. `{{skill or context}}` becomes the originating skill (sync, ingest, save, etc.).

## Why these exist

Before this folder existed, stubs were created inline by `/sync` from string-concat templates inside the skill file. Pulling them out as standalone templates means:

1. The format spec lives in one place (`conventions/page-format.md`) referenced by templates.
2. Templates can be edited / improved without modifying `/sync`.
3. Obsidian Templater plugin can use them for manual entity creation.

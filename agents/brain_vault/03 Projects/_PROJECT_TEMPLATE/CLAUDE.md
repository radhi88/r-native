# {{Project Name}} — Project Layer

> Project-specific Claude config. Inherits the vault root `CLAUDE.md` but adds project-scoped instructions. When Claude Code is run inside this project folder, it loads BOTH this and the vault root.
>
> Created via `/new-project` skill (recommended) — that walks you through an interview and fills these sections.

## Project at a glance

**One-line description:** {{What this project is}}

**Stage:** {{idea / planning / building / shipped / iterating / done}}

**Owner:** {{usually you, but track collaborators}}

**Started:** {{date}}

**Target outcome:** {{what success looks like, ideally measurable}}

**Why this matters:** {{the underlying motivation — keeps Claude from giving generic advice}}

## Active vs reference

This project is one of:

- **Active** — code/work happens IN this folder. Claude Code edits files here. Daily and weekly cadence.
- **Reference** — code/work lives elsewhere (e.g. `~/work/project-name/`). This folder holds DOCS ONLY. Claude reads, does not write to source code.

{{Pick one and customize the rest accordingly}}

## Folder structure

```
{{project-name}}/
├── CLAUDE.md (this file)
├── inputs/ (raw materials going in)
├── process/ (working drafts, plans, decisions)
├── outputs/ (shipped artifacts, exports)
├── skills/ (project-specific skills, if any)
└── notes/ (ad-hoc notes scoped to this project)
```

## Project-specific instructions for Claude

*What should Claude do differently inside this project vs the broader vault?*

- {{Examples: "Use formal voice for client deliverables." "Default to markdown output." "Always cite source files." "Don't auto-create commits — propose changes first." "When making edits, prefer minimal-diff patches."}}

## Active sub-tasks / milestones

Track concrete next steps. Move to "Done" as they ship.

### Now (this week)
- [ ] 

### Next (this month)
- [ ] 

### Later (this quarter)
- [ ] 

### Done
- [x] {{date}} — Project created via `/new-project`

## Decisions log

Record significant decisions so future-you (and Claude) don't re-litigate them.

- ({{date}}) — Decided to {{X}} because {{Y}}. Trade-off: {{Z}}.

## Open questions

- 

## Related vault entries

Link to people, concepts, companies, projects relevant to this work:
- 

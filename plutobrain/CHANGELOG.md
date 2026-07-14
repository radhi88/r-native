# Changelog

All notable changes to PlutoBrain will be tracked here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely, and this project uses semantic versioning where:

- **Major** — structural changes that require existing users to migrate
- **Minor** — new skills, new sections, or significant skill rewrites
- **Patch** — bug fixes, doc clean-ups, small skill edits

---

## [v1.3] — 2026-05-08

### Added

- **README demo GIF** — split-screen showing a real Obsidian graph view on the left and an animated terminal on the right where Claude reads the vault and lists its folders. Sells the concept in 7 seconds. Lives at `media/demo.gif`.

---

## [v1.2] — 2026-05-08

### Added

- **README badges** — License, Obsidian, Claude Code, Discord, YouTube walkthrough.
- **Watch the walkthrough** callout near the top of the README linking the YouTube video.
- **Community section** in the README — Discord, YouTube channel, Instagram.

### Changed

- **SETUP_GUIDE.md** Steps 7-13 renumbered to 7-12. The previous awkward "Step 7 (skipped)" placeholder is gone — Step 7 is now "Start your daily note habit" and the rest of the steps shift down by one.

---

## [v1.1] — 2026-05-08

### Changed

- **`brain-setup` skill rewritten as a 10-round deep interview.** Previously a 5-round profile-style fill of `CLAUDE.md`. Now produces THREE foundation files: `CLAUDE.md`, `GOALS.md`, `patterns.md`. New rounds cover:
  - Stress behavior and operating style
  - Failure modes captured as named patterns Claude can flag back at the user
  - Gating conditions (what has to be true before X)
  - Key relationships
  - Daily / weekly rhythm
  - Prime directive (the ONE sentence Claude grounds every response in)
- An "express" variant was added for users who want a 4-round version (~10-15 min) instead of the full 30-45 min.
- The skill now defines an explicit "what good looks like" bar so Claude knows when an interview was too shallow and proactively pushes for more depth.

### Added

- `.claude/commands/brain-setup.md` — slash-command shim (was missing from v1.0).
- `.claude/commands/divergence-check.md` — slash-command shim (was missing from v1.0).
- `IDEAS.md` — community feature requests can be triaged here.

### Changed

- `.claude/commands/import-videos.md` simplified into a generic template stub users can adapt to their own importer or delete.

---

## [v1.0] — 2026-05-07

### Added

- Initial public release.
- Full Obsidian + Claude Code knowledge OS scaffold.
- 14 skills: `brain-setup`, `deep-context-fill`, `new-project`, `weekly-update`, `pre-mortem`, `sync`, `save`, `ingest`, `query`, `autoresearch`, `canvas`, `lint`, `refine`, `divergence-check`.
- Layered improvements built on top of the base structure:
  - TLDR-first pages
  - Counter-Arguments & Data Gaps blocks (mandatory on concept and synthesis notes)
  - Token-budget tiers L0–L3 for progressive disclosure
  - Contradiction detection (via `/lint`)
  - `/divergence-check` skill for scheduled bias passes
- PARA folder structure (Projects / Areas / Resources / Archives via the `03` and `04` folders).
- 30-minute SETUP_GUIDE.md from zero (Obsidian → Node → Claude Code → first session).
- MIT license.

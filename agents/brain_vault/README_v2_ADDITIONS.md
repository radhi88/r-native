# PlutoBrain README — v2.0 additions

> Sections to add to the top-level `README.md` in the PlutoBrain repo for the v2.0 release. Paste between existing sections; don't replace the v1.x README wholesale.

## Add this section near the top, after the existing "What's inside" or features list

### New in v2.0 — Self-wiring brain

PlutoBrain v2.0 introduces a skill system upgrade that turns your vault from a passive notes folder into a self-wiring brain:

- **Typed graph extraction (zero LLM cost)** — every wikilink in your vault gets typed (`works_at`, `founded`, `attended`, `drives`, `lives_in`, etc.) via a regex pass. Output: `typed-edges.jsonl` at vault root. Ask "who works at Acme AI?" and get a structured answer, not a guess.
- **Compiled-truth + timeline page format** — entity pages now split current understanding (rewriteable) from dated evidence (append-only). Templates for people, companies, places, concepts, vehicles ship in `00 Notes/_templates/`.
- **Cross-cutting conventions** — seven rule files (brain-first lookup, quality standards, capture routing, page format, tiered enrichment, model routing, test-before-bulk) that every skill references. Update once, apply everywhere.
- **Skill dispatcher (`RESOLVER.md`)** — intent → skill routing table. Stop guessing which skill fires for which phrase.
- **Five new skills** — `typed-links`, `signal-detector`, `dream-cycle`, `routing-eval`, `skillify`. See `05 Skills/RESOLVER.md` for triggers.
- **Durable-skill audit (`/skillify`)** — 10-item audit forces every new skill to have triggers, fixtures, tests, resolver entry, MECE check before it ships. Bugs become structurally impossible to repeat.
- **Daily dream cycle** — scheduled overnight maintenance: refreshes the typed graph, runs lint, surfaces 3-5 prioritized items for your morning review.

See `RELEASE_NOTES.md` for the full v2.0 changelog and migration notes.

---

## Replace the existing "Skills" section with this expanded version

### Skills

PlutoBrain skills live in `05 Skills/`. Each skill is a markdown file with:

- **Frontmatter** — name, description, trigger phrases, model choice
- **When to run** — explicit triggers
- **Conventions followed** — cross-references to `05 Skills/conventions/`
- **End-to-end behavior** — step-by-step what the skill does
- **Verification** — test cases / run logs

Invoke a skill by name (`/<skill-name>`) or by trigger phrase. The dispatcher at `05 Skills/RESOLVER.md` maps phrases → skills.

#### v2.0 skill inventory

**Core (v1.x carryover):** `sync`, `save`, `ingest`, `query`, `autoresearch`, `canvas`, `lint`, `refine`, `new-project`, `weekly-update`, `pre-mortem`, `deep-context-fill`, `brain-setup`

**v2.0 additions:**

| Skill | What it does |
|---|---|
| `typed-links` | Regex extractor — turns wikilinks into typed graph edges. Zero LLM. |
| `signal-detector` | Per-turn entity capture. Saves entities + decisions + open loops before they leave context. |
| `dream-cycle` | Daily scheduled maintenance pass. Lint + typed-graph refresh + prioritized morning digest. |
| `routing-eval` | Validates that RESOLVER.md routes intent phrases to the right skill. JSONL fixtures + runner. |
| `skillify` | 10-item audit. Turns one-off fixes into durable skills. |

---

## Add this section if you're documenting the install path

### Optional: brain CLI runtime

PlutoBrain works standalone — markdown vault + Python scripts. For users who want hybrid vector + keyword search, an MCP server exposing the brain to Claude clients, and a durable job queue for background work, the optional brain CLI install at `00 Notes/setup/brain-cli-install.md` walks through a 7-step setup.

Note: this is optional. The core v2.0 features (typed-graph extraction, conventions, RESOLVER, skills, audit) all work without any CLI install.

---

## Add a v2.0 changelog entry to CHANGELOG.md

```markdown
## v2.0 — Skill system upgrade

### Added
- Conventions folder (`05 Skills/conventions/`) — 7 cross-cutting rule files + README
- RESOLVER.md skill dispatcher
- Entity templates folder (`00 Notes/_templates/`) — 5 templates + README
- Typed-link extractor — `05 Skills/typed-links.md` + Python script
- Signal-detector pattern — `05 Skills/signal-detector.md`
- Dream-cycle daily maintenance — `05 Skills/dream-cycle.md`
- Routing-eval audit — `05 Skills/routing-eval.md` + Python runner + 14 fixture files
- Skillify 10-item audit — `05 Skills/skillify.md` + Python runner
- Optional CLI install guide — `00 Notes/setup/brain-cli-install.md`

### Changed
- `CLAUDE.md` — adds RESOLVER + conventions to required-reading order
- `CLAUDE.md` — adds compiled-truth + timeline page format spec to immutable-vs-synthesized section
- `CLAUDE.md` — adds Conventions and Scheduled-tasks sections

### Not changed
- Vault folder structure — same as v1.x
- Existing skills — still work as-is; new conventions are additive
- Source-of-truth — markdown vault remains canonical; new typed-edges.jsonl is derived
```

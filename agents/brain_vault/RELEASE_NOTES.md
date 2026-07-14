# PlutoBrain v2.0 — Skill System Upgrade

> A major upgrade to the PlutoBrain skill layer. Adds a self-wiring typed graph, cross-cutting conventions, a routing dispatcher, durable-skill audit tooling, and overnight maintenance — all without changing the source-of-truth (your markdown vault).

## What's new

### Self-wiring typed graph

PlutoBrain now extracts **typed edges** from your vault using a zero-LLM regex pass. When you write `[[Alice]] works at [[Acme AI]]` in any page, the extractor generates:

```
edge: works_at(alice, acme-ai)
```

Recognized edge types: `works_at`, `founded`, `invested_in`, `advises`, `member_of`, `lives_in`, `drives`, `owns`, `attended`, `attends_school`, `retained`, `represents`, `client_of`, `mentions` + page-type-prior fallbacks (`affiliated_with`, `knows`, `employs`, `located_in`, `owned_by`, `associated_with`, `related_to`, `hosts`).

Output: `typed-edges.jsonl` at vault root. Regenerate any time with:

```
python "05 Skills/scripts/typed-links-extract.py" --vault "<your-vault>"
```

Run once at install, then on cron via the daily `dream-cycle` maintenance pass.

### Compiled-truth + timeline page format

Every entity page (`00 Notes/{people,companies,places,concepts,vehicles}/`) now follows a clean split:

- **Above the `---` divider:** compiled truth — your current best understanding, gets rewritten as new evidence accumulates.
- **Below the `---` divider:** timeline — append-only dated events, never edited.

Templates for each entity type live in `00 Notes/_templates/`. The skill `/lint` checks for the `---` divider; `/refine` migrates old-format pages opportunistically.

### Cross-cutting conventions

Seven new convention files at `05 Skills/conventions/`:

- `brain-first.md` — 5-step vault lookup before any external API call
- `quality.md` — citations, backlinks, notability gate, LLM-artifact bans
- `capture-routing.md` — `inbox/` routing pipeline and final-home table
- `page-format.md` — compiled-truth + timeline format spec
- `tiered-enrichment.md` — Tier 1/2/3 promotion rules for stubs → enriched → hub pages
- `model-routing.md` — which Claude model for which task
- `test-before-bulk.md` — sample-test rule for batch operations >5 items

Skills cite conventions by reference instead of re-stating rules, so updating a convention auto-applies to every skill that follows it.

### RESOLVER.md skill dispatcher

`05 Skills/RESOLVER.md` is the new intent → skill routing table. Lists every skill, its trigger phrases, and which conventions it follows. Read this in tandem with `CLAUDE.md` whenever a request might trigger a skill.

### New skills

- **`typed-links`** — the regex extractor (Python script). Wires the graph.
- **`signal-detector`** — per-message entity-capture pattern. Captures decisions / entities / open loops in parallel with the main turn so they don't get lost when the chat closes.
- **`dream-cycle`** — daily 9am scheduled maintenance task. Refreshes typed-edges, runs lint, surfaces 3-5 prioritized items for your morning review.
- **`routing-eval`** — JSONL fixture runner that validates RESOLVER.md routes intents correctly. Output: pass/fail per fixture, lists mis-routed intents.
- **`skillify`** — 10-item audit for any new skill. Forces every skill to have frontmatter, triggers, tests, fixtures, resolver entry, MECE check, etc. Pattern: when you fix something once in chat, "skillify it" and the fix becomes durable.

### CLI runtime (optional)

A backend CLI is wired in but not required. PlutoBrain ships everything as standalone Python scripts + markdown skills, so the vault works without any CLI install. If you want hybrid vector + keyword search, MCP server exposure, and durable job queues, see `00 Notes/setup/brain-cli-install.md` for the optional install path.

## Stats from a real run

First full-vault typed-links extraction on a working brain (~400 pages): **1,500+ typed edges, central entities surface as highest-in-degree** (your name, your main org, your tracked vehicles, etc.). 100+ unresolved wikilinks identified — those become the next `/refine` queue.

Routing-eval first run: **~60% pass rate** on aspirational fixtures. The eval surfaces exactly which trigger phrases need expansion in RESOLVER.md — that's the gap the system is designed to expose.

Skillify audit on existing skills: **new v2.0 skills score 10/10, older skills score 4-6/10** because they predate the conventions/fixture/resolver patterns. That gap is your incremental cleanup queue.

## Migration notes

If you're upgrading from PlutoBrain v1.5 → v2.0:

1. **Add the new files** by copying from this release into your vault.
2. **Update `CLAUDE.md`** with the additions from `README_v2_ADDITIONS.md`.
3. **Run the typed-links extractor** to generate `typed-edges.jsonl`.
4. **Run the skillify audit** to see which existing skills need bringing up to the new standard.
5. **Migrate entity pages** to the compiled-truth + timeline format as you touch them (not in a big-bang sweep).

No breaking changes. v1.5 vaults work as-is; v2.0 adds the new layer.

## File manifest

```
05 Skills/
├── RESOLVER.md                          (new)
├── conventions/                         (new folder)
│   ├── README.md
│   ├── brain-first.md
│   ├── capture-routing.md
│   ├── model-routing.md
│   ├── page-format.md
│   ├── quality.md
│   ├── test-before-bulk.md
│   └── tiered-enrichment.md
├── dream-cycle.md                       (new)
├── routing-eval.md                      (new)
├── signal-detector.md                   (new)
├── skillify.md                          (new)
├── typed-links.md                       (new)
├── eval/                                (new folder)
│   ├── README.md
│   └── *.jsonl (14 fixture files)
└── scripts/                             (new folder)
    ├── routing-eval-check.py
    ├── skillify-check.py
    └── typed-links-extract.py

00 Notes/_templates/                     (new folder)
├── README.md
├── company.md
├── concept.md
├── person.md
├── place.md
└── vehicle.md
```

## Roadmap

v2.1+ candidates:
- LLM-cross-modal audit pair in `/skillify` (sonnet + haiku double-check)
- `/refine` extensions to use typed-edges for enrichment-priority queue
- `/query` extensions to query the typed graph alongside vector + keyword
- Examples folder with sample entity pages showing the format in use
- GitHub issue template for "which step of setup broke" feedback

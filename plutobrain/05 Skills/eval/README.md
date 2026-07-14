---
type: eval-index
creator: claude
created: <run-date>
source: your-brain v2 upgrade (C)
---

# Routing Evals

> JSONL fixtures testing that pluto's natural-language requests route to the right skill. Adopted as `routing-eval.jsonl` pattern.

Each `<skill>.jsonl` file contains lines of `{"intent": "<what pluto might say>", "expected_skill": "<which skill should fire>", "notes": "<optional>"}`. The `/routing-eval` skill loads all fixtures and verifies that `05 Skills/RESOLVER.md` would correctly route each intent.

## Why this matters

Skills drift. RESOLVER.md gets edited. Trigger phrases get renamed. Without fixtures:
- A change to RESOLVER.md silently breaks routing for old phrases.
- New phrases pluto starts using don't get added to triggers.
- Skills that have overlapping triggers (e.g., "save this chat" vs "ingest this chat export") aren't disambiguated.

With fixtures, every change to RESOLVER.md gets validated against ~100 known intents.

## Format

```jsonl
{"intent": "save this chat", "expected_skill": "save"}
{"intent": "save the conversation", "expected_skill": "save"}
{"intent": "save this discussion to my brain", "expected_skill": "save"}
{"intent": "import this PDF", "expected_skill": "ingest", "notes": "single source vs batch — ingest, not sync"}
{"intent": "ambiguous: process this", "expected_skill": "ask", "notes": "ambiguous between sync and ingest — should ask pluto"}
```

`expected_skill: "ask"` is a valid expected outcome — means the request is ambiguous and the right behavior is to ask pluto rather than guess.

## Running the eval

```
python "05 Skills/scripts/routing-eval-check.py" --vault "<your-vault>"
```

Output: passes/failures per fixture file, total accuracy, top mis-routed intents.

## When to update fixtures

- New skill added: write a fixture file for it with 5-10 intents.
- RESOLVER.md trigger phrases changed: re-run the eval; add the new phrases to fixtures.
- Pluto says something that should have triggered a skill but didn't: add that phrase as a fixture row.
- Pluto says something that triggered the wrong skill: add a fixture row with the correct expected_skill.

## Skills covered (Phase 4 initial set)

- save.jsonl
- sync.jsonl
- ingest.jsonl
- query.jsonl
- autoresearch.jsonl
- lint.jsonl
- refine.jsonl
- canvas.jsonl
- new-project.jsonl
- weekly-update.jsonl
- pre-mortem.jsonl
- typed-links.jsonl
- skillify.jsonl
- ambiguous.jsonl (cases where the answer should be "ask pluto")

---
name: routing-eval
description: Runs the JSONL fixture files in 05 Skills/eval/ against RESOLVER.md. Reports pass/fail per fixture, identifies routing gaps and ambiguities. Adopted as your-brain skillify routing-eval.
creator: claude
created: <run-date>
source: your-brain v2 upgrade (C)
model: none (deterministic keyword match)
---

# /routing-eval

## Purpose

Verify that `05 Skills/RESOLVER.md` would correctly route the test intents in `05 Skills/eval/<skill>.jsonl`. Surfaces:

- **False positives** — fixture says intent X should route to skill A, but RESOLVER routes to B.
- **Missed routes** — intent X doesn't match any RESOLVER row strongly.
- **Ambiguity check** — intents marked `expected_skill: "ask"` SHOULD score low across all skills (so the right move is to ask pluto).

## When to run

- After any edit to `RESOLVER.md`.
- After a new skill is added.
- After a new trigger phrase is added to an existing skill.
- Once a week as part of the dream cycle (future).
- Manually: `/routing-eval` or `python "05 Skills/scripts/routing-eval-check.py" --vault "."`

## How it works

1. Parse `05 Skills/RESOLVER.md` — extract the routing table rows. Each row: `(skill_name, list_of_trigger_phrases)`.
2. Load every `05 Skills/eval/*.jsonl` file. Each line is `{intent, expected_skill, notes?}`.
3. For each intent, score every skill by keyword/phrase overlap against its trigger list.
4. Pick the top-scoring skill (or "ask" if top score < threshold or top vs second is within tie-break window).
5. Compare predicted vs expected. Report.

## Output

```
[routing-eval] vault: <your-vault>
[routing-eval] fixtures: 14 files, 78 intents

PASS: 65 / 78  (83%)
FAIL: 13 / 78

Failures:
  - "save what we just talked about" -> predicted: query, expected: save
  - "process this" -> predicted: sync, expected: ask  (ambiguity miss)
  - ...

Top-misrouted skills:
  - save (3 missed intents)
  - query (2 missed intents)
```

The output also gets appended to `00 Notes/lint-reports/routing-eval-YYYY-MM-DD.md`.

## Quality gate

- **Pass rate > 90%** — green, RESOLVER is healthy.
- **Pass rate 75–90%** — yellow, review failures and tune RESOLVER trigger phrases.
- **Pass rate < 75%** — red, RESOLVER drift; surface to pluto in next dream cycle report.

## Conventions followed

- `conventions/test-before-bulk.md` — read-only, no batch concern.
- `conventions/quality.md` — output cites the specific intent + expected vs predicted.
- `conventions/model-routing.md` — deterministic (no LLM call) for v1. v2 can add Haiku tie-break for low-confidence cases.

## Extending

When you say something that should route somewhere but doesn't, add it to the fixture file. The fixture is the canonical record of "phrases this skill should answer to." RESOLVER.md trigger phrases follow the fixtures, not the other way around.

## Implementation

Script: `05 Skills/scripts/routing-eval-check.py` (Phase 4, written with `routing-eval.md`).

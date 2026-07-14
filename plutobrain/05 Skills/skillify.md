---
name: skillify
description: Turn a one-off fix or workflow into a durable skill. 10-item audit ensures the skill has SKILL.md with frontmatter, triggers documented, deterministic script if needed, unit tests, E2E tests, routing-eval fixture, resolver entry, MECE check, filing audit, no STUB sentinels. Adopted as your-brain skillify.
creator: claude
created: <run-date>
source: your-brain v2 upgrade (C)
model: claude-sonnet-4-6
---

# /skillify

## Purpose

You fix something once in conversation. He says "skillify it!" The fix becomes a permanent skill — frontmatter, triggers, scripts, tests, resolver entry, audit. The bug can't recur because the next time the trigger fires, the skill fires too.

The shape: say "skillify it!" and the bug becomes structurally impossible to repeat. 10-item audit, adapted for your-brain's flat-skill convention.

## When to run

- Pluto says "skillify this", "turn this into a skill", "make this permanent", `/skillify`.
- After resolving a non-trivial issue that's likely to recur (same problem space, different specifics).
- When a workflow has been done >3 times manually with the same shape.

## When NOT to run

- The fix is genuinely one-off and won't recur.
- The fix is already covered by an existing skill (extend that skill instead).
- Pluto is in low-energy mode (per `CLAUDE.md` deep-context — complexity spikes irritability when low-energy).

## Conventions followed

- `conventions/brain-first.md` — reads vault first to check if the would-be skill duplicates an existing one (MECE check).
- `conventions/quality.md` — output skill has frontmatter + citations.
- `conventions/test-before-bulk.md` — new skill MUST be tested on 3-5 cases before being marked production.

## The 10-item audit

A skill is "complete" only when all 10 items pass.

1. **`<skill>.md` exists** in `05 Skills/` with valid YAML frontmatter (`name`, `description`, `creator`, `created`, `source`, optionally `model` and `schedule`).

2. **Trigger phrases documented** in frontmatter's `description` AND in the skill body's "When to run" section AND in `05 Skills/RESOLVER.md` routing table.

3. **Conventions cited explicitly** in the skill body. Every skill must say which conventions in `05 Skills/conventions/` it follows.

4. **Deterministic script if applicable**. If the skill has a logic-execution component (typed-links, routing-eval, lint), the script lives in `05 Skills/scripts/<name>.py` (Python preferred, executable from command line, has `--help`).

5. **Unit test cases documented** in the skill body's "Verification" or "Test cases" section. At least 3 named test cases describing input → expected output.

6. **End-to-end test run** at least once, manually documented in the skill body or a separate run-log. For typed-links: "ran across your vault, producing typed edges." For routing-eval: "ran on initial fixtures, 61% pass — surfacing drift."

7. **Routing-eval fixture exists** at `05 Skills/eval/<skill>.jsonl` with ≥5 intents that should match this skill.

8. **Resolver entry** in `05 Skills/RESOLVER.md` routing table.

9. **MECE check** — the new skill's job doesn't overlap >30% with an existing skill. Overlap-with-existing surfaced as a callout in the new skill body.

10. **No SKILLIFY_STUB sentinels** — every section of the skill body has real content, no "TBD" or "FILL IN LATER" placeholders.

## Running the audit

```
python "05 Skills/scripts/skillify-check.py" --vault "<your-vault>" --skill <skill-name>
```

Without `--skill`, checks all skills in `05 Skills/`. Exit code: 0 = all pass, 1 = at least one skill fails the audit.

## What skillify does in practice

When you say "skillify this" after some workflow, the strategist:

1. **Identifies what to skillify.** Extract the workflow shape: input type, processing steps, output. Name it.
2. **Checks RESOLVER and existing skills** for overlap (MECE check).
3. **Scaffolds the skill files** following the 10-item audit:
   - `05 Skills/<name>.md`
   - `05 Skills/scripts/<name>.py` (if needed)
   - `05 Skills/eval/<name>.jsonl`
   - Resolver row added to `05 Skills/RESOLVER.md`
4. **Runs the 10-item audit.** Reports pass/fail per item.
5. **Iterates** until audit passes.
6. **Logs to `log.md`** with the date and skill name.

## Example

Pluto: "the typed-links extractor keeps misclassifying foreign-language names. Skillify the fix."

Skillify response:
1. Identifies: the fix is a pre-normalization step on entity names before slug generation.
2. Checks: no existing skill does name normalization. New skill `name-normalize` is justified.
3. Scaffolds: `05 Skills/name-normalize.md`, `05 Skills/scripts/name-normalize.py`, `05 Skills/eval/name-normalize.jsonl`, RESOLVER row.
4. Audit: 10/10 pass.
5. Log: "<recent-month>-30: skillified name-normalize. 8 test fixtures pass."
6. Next time the original problem appears, name-normalize fires first.

## Anti-patterns this catches

- **Tribal-knowledge fixes** — you fix something in conversation, no durable record exists.
- **Skill bloat** — overlapping skills that should have been one (MECE check catches this).
- **Trigger drift** — fixture file forces RESOLVER to stay in sync with your phrasing.
- **STUB-shipped skills** — items 5, 6, 7, 10 of the audit prevent "skill exists in name only" failures.

## Limitations

- Full skillify has 5-file scaffolding + cross-modal review + LLM evals. Pluto-mind's v1 has the 10-item audit but not LLM evals. v1 is fine; v2 can add a cross-modal review pair (sonnet checks skill quality, then haiku double-checks) once skill count crosses 20.

---
name: signal-detector
description: Fast per-message entity-capture pre-pass. Runs in parallel on every significant Claude turn to capture entity mentions + original ideas before they leave context. Adopted directly. Feeds /sync and /save with pre-extracted entities so the batch passes have less to redo.
creator: claude
created: <run-date>
source: your-brain v2 upgrade (C)
model: claude-haiku-4-5-20251001
---

# /signal-detector

## Purpose

Pluto's conversations with Claude produce entities and ideas that should land in the vault. Without an active capture, those signals get lost when the chat closes: the conversation gets saved, but the named people, companies, decisions, open questions, and patterns inside it have to be re-extracted later by `/sync` or `/save`.

`/signal-detector` is the fix: a fast Haiku-class pass that runs alongside the main turn, extracting entities and ideas as they fly by, and dropping them into `inbox/.signals/` for `/sync` to pick up.

## Conventions followed

- `conventions/brain-first.md` — runs alongside the brain-first lookup; signals captured here populate the same brain that brain-first reads from.
- `conventions/quality.md` — captured signals include source attribution (which message they came from).
- `conventions/capture-routing.md` — output lands in `inbox/.signals/` for `/sync` to route.
- `conventions/model-routing.md` — Haiku, not Sonnet. Cost-discipline matters because this runs on every turn.

## When to run

- On every Claude turn that exchanges >200 words of content with pluto (small acks like "ok" don't need it).
- Explicitly: you say "capture this", "remember this", `/signal-detector`.
- Inside `/save` as an embedded pre-pass before the full save synthesis runs.
- Inside `/sync` Step 0, before scanning inbox/, to pull `.signals/` into the batch.

Skip when:
- Pluto explicitly says "don't save this" or "this is private".
- The turn is pure conversational (no new entities, no decisions, no ideas).

## What signals does it capture

For each significant turn, extract:

1. **People mentioned** by name — first name + last-name-if-given, plus what they did/said in context.
2. **Companies / organizations mentioned** — name + role (customer, vendor, employer, lead, etc.).
3. **Places mentioned** — explicit cities, venues, addresses.
4. **Decisions made** — anything pluto said "I'm going to do X" or "I decided Y."
5. **Open questions** — anything pluto flagged as unsure or pending.
6. **Open loops opened** — new commitments, follow-ups, deferred items.
7. **Open loops closed** — items completed or abandoned.
8. **Pattern observations** — anything that looks like a recurring pluto pattern (cross-check `patterns.md` instances).
9. **Original thinking** — first-person assessments, frameworks, hot takes pluto generated. (These compound into `00 Notes/concepts/` and `00 Notes/sources/originals/`.)

## Output format

One JSONL file per turn at `inbox/.signals/<run-timestamp>.jsonl`. Each line is one signal:

```json
{"type":"person","name":"Alice Example","context":"civilian counsel on Bar to Continued Service appeal","turn_id":"<recent-month>-15T14:30Z","confidence":0.9,"source_message":"...civilian counsel Alice Example..."}
{"type":"decision","content":"Pull Tier 1 patterns now; defer Postgres infra","turn_id":"<recent-month>-15T14:30Z","confidence":0.95}
{"type":"open_loop_opened","content":"verify CLAUDE.md update diff before applying","turn_id":"<recent-month>-15T14:30Z","confidence":0.9}
```

## How /sync consumes signals

`/sync` Step 0 (added):

1. Scan `inbox/.signals/*.jsonl`.
2. Aggregate signals from all signal files into a single entity-and-event dossier.
3. Run the normal `/sync` Step 4 (link or stub) with the pre-extracted entities as input — skipping the Step 3 LLM extraction call for items already covered.
4. After successful sync, archive consumed signal files to `inbox/.signals/.archived/`.

## Cost discipline

Signal-detector runs on every significant turn. At ~50 turns/day average, that's:
- 50 × 1 Haiku call/turn × ~$0.001/call = **$0.05/day** worst case
- ~$1.50/month for the capture layer

If cost crosses $5/month (high-volume content-day signal), surface to pluto and tune the "significant turn" threshold.

## Failure modes prevented

- The "the conversation ended and the entities got lost" failure — common before signal-detector. Pluto would have a great strategist conversation; nothing landed in the vault; the next session had to re-discover the context.
- The `/sync` batch failure where 200 inbox items pile up and `/sync` is too expensive / slow to run. With signal-detector, the entities are pre-extracted; `/sync` is just the routing layer.

## Implementation status

Documented as part of your-brain v2. The detector logic is documented here. Integration with Claudian / Cowork / claude.ai sessions is **deferred** — needs an actual implementation hook in each context that fires Haiku in parallel. For now this lives as a documented pattern; the strategist Claude (this Claude Code session) does it implicitly by extracting entities into `hot.md` and `log.md` as conversations happen.

**Real automation requires:**
1. Claudian extension — add an "on-turn-complete" hook that fires Haiku.
2. Cowork extension — similar hook.
3. Claude Code session — hook into the same.

This becomes automated once the brain CLI runtime is installed.

## Until automation lands

Strategist Claude follows this convention manually: when a turn exchanges substantive content with pluto, the strategist explicitly notes entities + decisions + open loops in the response and updates `hot.md` / appends to `log.md` as appropriate. `/save` runs the same extraction as a batch pass at end-of-session.

---
name: query
description: Run a question against the vault as a knowledge base — search relevant pages, read them, synthesize an answer with citations, and file the synthesis back into 00 Notes/saved-chats/ as a durable wiki page so explorations compound. 
---

# /query

## Purpose
The wiki is a knowledge base. `/query` treats it as one. You asks a question; Claude searches the vault, reads the relevant pages, synthesizes a cited answer, and **files the answer back as a new wiki page** so the next query can build on it. Valuable outputs file back into the wiki as new pages, so explorations compound.

This is the differentiator from chat-only Q&A: a chat answer evaporates. A `/query` answer is durable and discoverable by future queries.

## When to invoke
- You types `/query <question>` or `/query` (then asks)
- You says "answer this from the brain," "synthesize from my notes," "what does my brain know about X"
- Cross-cutting questions that touch multiple notes (e.g., "what's the through-line between my trading patterns and my project completion patterns?", "summarize everything I know about my legal exposure right now", "what's the highest-leverage open thread per GOALS.md?")

## When NOT to invoke
- Trivial lookups (use `/sync` index search or just grep)
- Real-time facts not in the vault (use WebSearch instead)
- Questions about ongoing work you already has full context on (just answer in chat)

## Behavior

### Step 1 — Parse the question
Identify:
- **Topic entities** (people, projects, concepts, companies, places — the wiki nodes the question is about)
- **Question type**: factual, analytical, comparative, synthesis, decision-support
- **Time scope**: "right now," "this year," "historically," undated

If the question is ambiguous, ask one clarifying question before proceeding. Don't fishing-expedition the vault.

### Step 2 — Retrieval
Multi-pass retrieval:

1. **Direct entity lookup** — for each topic entity, check `index.md` and the canonical `00 Notes/{people,companies,places,concepts,vehicles,videos}/` folder for a matching note. Read it.
2. **Wikilink graph traversal** — from each entity's note, walk inbound and outbound wikilinks one hop deep. Read the most relevant linked notes (rank by frontmatter recency + apparent relevance).
3. **Keyword grep** — grep the vault for question-relevant keywords across `00 Notes/`, `01 Journals/daily/`, `03 Projects/`. Pull top hits.
4. **Existing query results** — search `00 Notes/saved-chats/query-*.md` for prior queries on the same topic. If one exists and is recent, build on it instead of duplicating.

Aim to read 5–15 pages before synthesizing. Less means underspecified; more usually means scope creep.

### Step 3 — Synthesize
Write the answer with:
- **Direct response** to the question, no preamble.
- **Inline citations** — every claim links to a vault page: `You's [car] was financed via $100K [bank] + $35K [lender] + $17K cash ([[{{YOUR_NAME}}]] Background).`
- **Identified contradictions or gaps** — if two notes say different things, flag the contradiction by name and source.
- **Open questions** — at least one. If no genuine open question exists, say "no open questions" explicitly rather than padding.

Tone: blunt and direct per `[[CLAUDE]]` communication preferences. No hedging. No restating the question.

### Step 4 — File the synthesis back as a wiki page

Output: `00 Notes/saved-chats/query-YYYY-MM-DD-<slug>.md`

Slug from the question — short, descriptive, kebab-case. Example: `query-2026-05-08-legal-exposure-snapshot.md`.

```markdown
---
type: query
question: <the original question, verbatim>
asked: YYYY-MM-DD
pages_consulted: <count>
tags: [query, <topic-tags>]
---

# <Question rephrased as title>

> Filed by /query on YYYY-MM-DD. Pages consulted: N.

## Question
<The exact question you asked.>

## Answer
<The synthesized answer with inline wikilink citations.>

## Sources consulted
- [[<page 1>]] — <one-line reason this page mattered>
- [[<page 2>]] — <reason>
- ... (one bullet per page actually read)

## Open questions
- <Genuine residual unknowns the synthesis surfaced.>

## Contradictions / gaps surfaced
- <Anything where two notes disagreed or where the vault is silent on a relevant axis. Empty if none.>

## Filed as
This query is durable. Future `/query` invocations may cite or build on it. The wiki accumulates synthesis, not just sources.
```

### Step 5 — Cross-link
- For each canonical entity referenced in the answer, append the new query page under that entity's `## Mentioned in`.
- Append entry to `index.md` under the saved-chats section (separate sub-bullet for query-* files if there are several).
- Add to `hot.md` "Recently referenced notes."

### Step 6 — Confirm
Print to you:
- Question (echo)
- Pages consulted (count + 3 example wikilinks)
- Path filed
- Any contradictions or gaps surfaced
- One-line follow-up suggestion (e.g., "Want a deeper /query on the contradiction between X and Y?")

## Permissions
- ✅ Read every vault file
- ✅ Create the query saved-chat page
- ✅ Append `## Mentioned in` backlinks to referenced entity notes
- ✅ Append to `index.md`, `hot.md`, `log.md`
- ❌ Edit any other notes' body content
- ❌ Create new entity stubs (queries don't introduce new entities — they synthesize from existing ones)

## Log entry
After the query is filed, append a one-line entry to `[[log.md]]` at the vault root:
- Format: `## [YYYY-MM-DD HH:MM] query | <question> -> <saved-chat path>`
- Example: `## [2026-05-08 16:02] query | what's my current legal exposure summary -> 00 Notes/saved-chats/query-2026-05-08-legal-exposure-snapshot.md`
- Append-only — never edit existing log entries.

## Versioning
The "query files back as a wiki page" mechanism is the second compound mechanism alongside `/ingest`'s wiki-densification pass — sources accumulate via /ingest, syntheses accumulate via /query. Together they make the brain compound.

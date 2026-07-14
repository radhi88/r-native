---
name: divergence-check
description: Bias-check pass on concept pages and synthesis notes. For each, generate the strongest counter-argument, identify acknowledged data gaps, and flag tensions with other notes. Combats confirmation bias accumulated from one-sided source ingestion.
---

# /divergence-check

## Purpose

When you ingest 5 articles praising a framework, the wiki will tilt toward that framework. The same risk applies to people, companies, decisions, and any synthesis. **Without an active counter-pressure, your wiki ossifies into confirmation of whatever you read first.**

This skill runs an explicit divergence pass over selected pages, using Claude as a steel-manning adversary. It populates or refreshes the `## Counter-Arguments & Data Gaps` section on each note.

## When to run

- The user types `/divergence-check`, "challenge my notes," "play devil's advocate against my wiki," etc.
- Quarterly as a scheduled health check.
- After bulk-ingesting sources on a single topic (e.g. 5 articles all from one perspective).
- When the user is about to make a major decision based on accumulated wiki content — fresh divergence pass first.

## End-to-end behavior

### 1. Scope
Ask the user (or detect from prompt):
- **One specific page?** (e.g. `/divergence-check on AI Memory Architecture`)
- **All concept pages?** (default if no page specified)
- **All pages updated in last N days?**
- **Pages tagged X?**

### 2. For each in-scope page

**a. Read the page.** Note its central claims and TLDR.

**b. Generate the strongest counter-arguments.** Claude steel-mans the opposite position. Aim for 2-4 sharp objections, not 20 weak ones.

**c. Search the vault** for notes that contradict, complicate, or qualify the page. Use `/sync`-style entity matching.

**d. Identify data gaps.** What's missing that would change the page's conclusion if known? What hasn't been investigated?

**e. Update the page's `## Counter-Arguments & Data Gaps` section.** If the section doesn't exist, create it. If it has prior entries, **append** new ones with date-stamped subheading rather than overwriting.

**f. Append to log.md:**
```
## [YYYY-MM-DD HH:MM] divergence-check | <page>
Counter-args added: <count>. Tensions surfaced: <count>. Data gaps: <count>.
```

### 3. Summary report
After the run, present the user with:
- Pages that gained the strongest new counter-arguments
- Tensions discovered between pages
- Suggested follow-up questions or sources to fill data gaps
- Pages where Claude couldn't generate a strong counter-argument (these may be solid OR may need more challenge)

### 4. User can promote findings
For each tension or counter-argument, offer:
- **Promote to top of page** — if the user agrees with the counter-argument and wants it surfaced
- **Acknowledge but reject** — note that this was considered but the user disagrees with the counter-argument; record reasoning
- **Action item** — turn the data gap into a research task (`/autoresearch` candidate)

## Boundaries

- This skill **only modifies** the `## Counter-Arguments & Data Gaps` section. It does not edit page bodies, TLDRs, or claims.
- Counter-arguments are **flagged as Claude's**, not as the user's. Format with attribution: `(divergence-check, YYYY-MM-DD)`.
- The user explicitly approves promotion of any counter-argument into the page body.

## Output format example

```markdown
## Counter-Arguments & Data Gaps

### (divergence-check 2026-05-08)
- **Counter-argument:** The claim that AI Memory Architecture is a 3-layer model assumes layered architectures generalize. But [[Linear context window models]] suggest some implementations skip the structural layer and rely on long-context retrieval — and benchmarks show competitive performance.
- **Counter-argument:** The "knowledge graph" layer presupposes you have enough notes to make a graph meaningful. For someone in week 1 of using a second brain, all three layers collapse to "files in folders" and the architecture metaphor is misleading.
- **Tension with:** [[RAG vs Wiki]] — that note argues the wiki pattern requires significant manual structure; this one says the LLM does the structure. Reconcile.
- **Data gap:** No quantitative comparison of "wiki" vs "RAG" knowledge bases at >500 sources scale. Would change confidence in the model.

### (divergence-check 2026-04-15)
- **Counter-argument:** ...
```

## Why this matters

The biggest failure mode of personal wikis is silent bias accumulation. You read a few sources you like, the LLM dutifully synthesizes them, and after 6 months your wiki is a sophisticated echo chamber.

Divergence-check is the structural antidote — periodic, automated steel-manning that ensures the wiki holds tension between perspectives rather than collapsing into agreement with itself.

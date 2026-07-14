---
name: pre-mortem
description: On-demand decision pre-mortem. Imagine the decision has failed in 6 months and identify the most likely cause, warning signs, and preventative actions.
---

# Pre-Mortem

## Purpose
Catch impulsive commitments before they become sunk cost. A known-effective cognitive technique — imagining failure has already happened forces the brain to surface specific risks rather than abstract ones.

## When to run
Before any of the following:
- Starting a new project or agent system
- Making a purchase over a few thousand dollars
- Taking on a new collaborator, client, or commitment
- Signing anything (lease, loan, employment, partnership)
- Major life changes (moves, schools, relationships)

You can request explicitly ("run pre-mortem on X") or Claude can suggest it when a Pattern Library trigger fires (especially Impulsive Project Initiation Under Stimulus).

## Process
1. Confirm what decision is being pre-mortemed. Write it as a single sentence.
2. Ask you: "Imagine it's 6 months from now. This decision has clearly failed. You're looking back at it and shaking your head. Walk me through what happened."
3. Ask the following in order:
 - What was the most likely cause of the failure?
 - What were the early warning signs that you would have ignored?
 - What preconditions in your life made the failure more likely?
 - What could you do *now*, before committing, to prevent this failure mode?
 - What would have to be true for you to abandon the decision after committing?
4. Write the output to `04 Reviews/pre-mortems/YYYY-MM-DD-<decision-slug>.md` with this structure:

```
# Pre-Mortem: <Decision>

**Date:** YYYY-MM-DD
**Decision:** <one sentence>

## Imagined failure (6-month forward look)
<you's narrative>

## Most likely cause of failure
<you's answer>

## Early warning signs (would have been ignored)
<you's answer>

## Preconditions making failure more likely
<you's answer>

## Preventative actions to take NOW
<you's answer>

## Abandonment conditions (would force a stop)
<you's answer>

## Decision after pre-mortem
[ ] Proceed
[ ] Proceed with modifications: <list>
[ ] Do not proceed
[ ] Defer / revisit on <date>
```

5. Ask you to mark the decision-after-pre-mortem checkbox.
6. If "Proceed with modifications," surface those modifications when the project or commitment is later created.

# Pattern Library

> Recurring patterns Claude tracks about Radhi. Read before responding to significant requests. Surface patterns by name when triggered — not to block, but to make the choice conscious.

---

## Pattern: Scope Creep Before Stabilization

**Description:** When a phase or module reaches ~70-80% completion, new features, integrations, or adjacent ideas get added before the current work is fully validated. New threads open faster than old ones close.

**Instances:**
- 2026-05-21: Fractal engine, Algory integration, and 18-phase refactor all running in parallel before any single phase is backtested end-to-end.
- Pattern also shows in AI skill customization during active architecture work.

**Trigger conditions:** "Let's also add...", "what if we integrate X", "while we're at it...", multiple active milestones simultaneously, new tool/repo discovered and immediately installed.

**Recommended response:** Name the pattern. Ask what Phase N needs to be true before starting Phase N+1. Push to close current phase before opening the next. Frame additions as gated tasks ("after Phase 2 validates").

---

## Pattern: Tool Enthusiasm Before Validation

**Description:** New tools, repos, frameworks, or AI models get integrated before the current integration is validated or stabilized. Each new tool feels essential in the moment.

**Instances:**
- 2026-05-21: PlutoBrain being set up while 18-phase FRIDAY refactor is at Phase 2 — good tool but adds cognitive load mid-refactor.
- HuggingFace skill customization before core trading loop stabilized.

**Trigger conditions:** Discovering a new tool/repo, "let's install X", "this could be useful for Y", enthusiasm about integrating something new.

**Recommended response:** Note the pattern. Validate that the new tool directly unblocks the current phase. If not, add to inbox/backlog instead of integrating now.

---

## Pattern: Architecture Over Trading

**Description:** Time spent perfecting the AI/code architecture competes with time spent validating trading strategy. The system can be architecturally beautiful but untested against real market conditions.

**Instances:**
- Phase 0+1 complete but paper trading validation not yet done.
- Live monitor on 40 pairs but no documented win-rate on any pair.

**Trigger conditions:** Adding complexity to the codebase, new ML experiments, refactoring sessions longer than 1 day without a trading result checkpoint.

**Recommended response:** Surface the pattern. Ask: "What's the current paper-trade win rate on XAUUSDm M1?" If unknown, push toward validation before more architecture work.

---

## YOUR PATTERNS (Claude will propose additions as they emerge)

(Claude appends here as patterns observed — never without approval)

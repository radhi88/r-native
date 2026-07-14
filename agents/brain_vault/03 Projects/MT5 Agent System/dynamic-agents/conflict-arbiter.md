---
type: dynamic_agent
id: conflict-arbiter
status: proposed
creator: codex
source: mt5-agent-brain
---

# حَكَم التعارض

Role: يوفق بين SMC وVolume Profile وConfluence

Reason created: SMC bias conflicts with confluence

Allowed actions: observe, write_report, suggest_task

## Last bounded execution
Observed SMC bias=SELL and VP signal=SELL_ZONE. Recommendation: require written conflict note before changing direction.

This proposed agent reports to [[Mujammi]] and writes into [[Agent Brain Timeline]]. It does not execute arbitrary code.

## Assigned tasks
- [medium] اكتب قرار ترجيح عندما SMC يخالف Volume Profile (count=40)

Updated: 2026-05-21T19:41:32

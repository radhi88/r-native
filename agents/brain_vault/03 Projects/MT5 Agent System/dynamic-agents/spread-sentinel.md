---
type: dynamic_agent
id: spread-sentinel
status: proposed
creator: codex
source: mt5-agent-brain
---

# حارس السبريد

Role: يراقب صدمة السبريد ويقترح gap/SL distance

Reason created: spread above live threshold

Allowed actions: observe, write_report, suggest_task

## Last bounded execution
Observed avg spread=308.0 points. Current gap=1500 effective_gap=1500. Recommendation: keep stop-reverse distance comfortably above live spread and do not tighten pending stops while spread is elevated.

This proposed agent reports to [[Mujammi]] and writes into [[Agent Brain Timeline]]. It does not execute arbitrary code.

## Assigned tasks
- [high] ابنِ نموذج سبريد: متى نوسع gap ومتى نمنع الستوبات القريبة (count=776)

Updated: 2026-05-21T19:41:32

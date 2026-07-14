# PlutoBrain Swarm

The **honest** implementation of the MEGA AGENT SWARM spec (45-role roster), built
as a zero-dependency, zero-LLM Python daemon.

## What it actually is

The spec describes "50 agents that never sleep." There is no persistent LLM agent
runtime — and you wouldn't want one: ~40 of the 45 roles (File Mapper, Dependency
Tracker, Duplicate Hunter, Hardcode Hunter, Magic Manager, Compiler Guard, Health
Monitor…) are **deterministic static analysis**, not reasoning. So:

- **23 roles run for real** as a continuous daemon, scanning your `.mq5`/`.mqh`
  files every cycle and writing JSON artifacts. No tokens, no network, no cost.
- **21 roles are `ESCALATE`** — genuine judgment work (Structure Designer, Risk
  Engineer, Stress Tester…). They're parked in `escalations.json` to hand to a
  human, to Claude, or to `friday_decision.py`. They do **not** silently pretend
  to think.
- **1 Orchestrator_Prime** loop dispatches, writes status beacons, raises alerts,
  and promotes finished clusters to the Active Pool.

This matches the spec's structure (clusters, active pool, shared state, dashboard,
human checkpoints) without the fantasy of resident LLM workers.

## Run

```powershell
# continuous (the "never sleeps" loop, 30s cycle)
python -m plutobrain_swarm.orchestrator

# one pass (for cron / CI)
python -m plutobrain_swarm.orchestrator --once

# N cycles then stop, custom interval
python -m plutobrain_swarm.orchestrator --cycles 20 --interval 15
```

Then open the dashboard:

```powershell
cd plutobrain_swarm
python -m http.server 8099
# browse http://localhost:8099/dashboard.html
```

(Or just open `dashboard.html` directly — it reads the JSON files.)

## Outputs (`swarm_state/`)

| File | Spec name | Contents |
|---|---|---|
| `agent_status.json` | Status Beacon | every agent's live status + summary |
| `agent_allocation_map.json` | allocation map | cluster / active_pool / escalate roster |
| `orchestrator_log.json` | orchestrator log | per-cycle history (ran/errored/findings/uptime) |
| `alerts.json` | Critical Alerts | high-severity findings (magic collisions, syntax breaks) |
| `escalations.json` | — | judgment roles awaiting a human/LLM |
| `artifacts/*.json` | — | the real analysis output (see below) |

## Real artifacts produced

`file_map`, `dependency_tree`, `duplicates`, `version_clusters`, `magic_map`
(+ collisions), `hardcodes`, `inputs` (config-centralization surface),
`session_gating` (night-discipline coverage — your real edge), `spread_checks`,
`broker_assumptions`, `syntax_balance`, `doc_density`, `ea_locations`,
`process_pulse`, `health`, and more.

## First-run findings (your repo)

- Magic **collision** on `20260605` (Stoch_Reversion_M3 duplicated live_ea/ vs
  r-native-pipflow/, shared with templates).
- 4 EA families with multiple drifting versions (FOOTPRINT v1/v3/v4, Grid v7_2/v7_3).
- 11 unresolved local includes; 3 files with unbalanced braces/parens.

## Extending

Add a function to `workers.py` that takes a `Context` and returns
`{"summary","findings","artifact"}`, register it in the `WORKERS` dict, and point
a roster entry's `worker=` at its name in `registry.py`. To wire an `ESCALATE`
role to actual reasoning, replace its handling in the orchestrator with a call to
`friday_decision.py` or a Claude prompt.

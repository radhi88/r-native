# FRIDAY Reflection Engine

A scientific-method self-improvement loop for FRIDAY. It scores **real closed MT5
demo deals** against an explicit goal, then changes **exactly one discipline
variable per cycle** and logs a **falsifiable hypothesis** it checks next time.

This is the piece FRIDAY was missing. The gene layer
(`friday_strategy_genes.json`) registered 2,028 decisions but had `wins:0,
losses:0` — the feedback wire was cut. `friday_trade_outcome_learner.py` already
knows how to read closed deals; this engine consumes those realized outcomes,
**scores them against a goal**, and runs a disciplined one-variable-at-a-time
improvement loop on top.

Per the measured FRIDAY edge — **discipline (no 22:00–08:00 UTC trades + risk
management), not indicators; analog/fractal is context-only** — the only knobs
this loop is allowed to touch are discipline/risk levers (`strategy.json`).

## Requirements

| Need | Why | Status |
|------|-----|--------|
| **Claude Code** | runs/maintains this engine | running |
| **Python 3.13** (the existing FRIDAY venv) | runs `reflect.py` / `score.py` / `trade_source.py` | present — **stdlib only, no new packages** |
| **MetaTrader5 Python pkg + MT5 demo terminal open** | `reflect.py --refresh` and the live executors read closed deals via `mt5.history_deals_get` | present |
| **MetaEditor** (ships with MT5) | recompile the EA after the night-guard edit (`F7`) | manual step |
| **Git** | optional — handy, but the project is not a git repo today | present (2.54) |

**Not required:** Node.js and the Railway CLI. Those belonged to the original
cloud-deploy onboarding path, which was dropped in favor of wiring discipline
directly into FRIDAY. This engine is fully local — nothing deploys anywhere.

## Files

| File | Role |
|------|------|
| `goal.json` | Success / failure / quality bar. Hand-edit any time. The engine never rewrites it. |
| `strategy.json` | The evolving discipline tunables. Starts at `v01`. One variable changes per cycle. |
| `score.py` | `score(trades, goal) -> composite in [-1,+1]` — return vs target, drawdown vs max, Sharpe vs min, with hard failure floors. |
| `trade_source.py` | Read-only loader for realized trades (from the outcome learner's output); can refresh from MT5. |
| `reflect.py` | The cycle: score → judge last hypothesis (revert if it backfired) → change one variable → version + log. |
| `reflection_state.json` | Cadence counter + the currently open hypothesis. |
| `state/history/vNN.json` | Every prior strategy version, preserved. |
| `state/hypotheses.jsonl` | Full ledger: every proposal, resolution (confirmed/refuted), hold, and revert. |

## Run it

```powershell
# Force one cycle now (demonstration, ignores the trade-count cadence):
python reflection\reflect.py --fallback --force

# Pull fresh closed deals from MT5 first (needs the demo terminal running):
python reflection\reflect.py --fallback --force --refresh

# Normal cadence — only acts once `reflection_every` new trades have closed:
python reflection\reflect.py --fallback

# Let the hermes CLI propose the variable (falls back to deterministic if absent):
python reflection\reflect.py --hermes
```

Schedule it next to the other FRIDAY loops (e.g. every few minutes); it only acts
when enough new trades have closed.

## The scientific method, enforced

1. **Score** the last 25 realized trades against `goal.json`.
2. **Judge** the previous cycle's prediction: did the composite score move the way
   the hypothesis predicted? Logged as `confirmed` / `refuted`. A refuted change
   that *hurt* the score is **automatically reverted** (that revert is the cycle's
   one allowed change).
3. **Change exactly one variable** (deterministic priority: protect downside →
   enforce discipline → chase return; or via `--hermes`).
4. **Version + archive + log** so every change is auditable and reversible.

## Safety

- **Read-only on trades.** Reads closed deals via the existing demo-guarded
  outcome learner. Sends no orders. Imports nothing from the live executors.
- **Writes only inside `reflection/`.** Never edits executors, `goal.json`, or any
  FRIDAY file.
- **`strategy.json` is advisory until you wire it in.** This engine maintains the
  evolving strategy + hypothesis ledger. Making the executors *read* `strategy.json`
  is a separate, deliberate step (those files are safety-gated) — not done
  automatically.
- **Failure floors are brakes.** Below `failure_below_score` the engine may only
  de-risk or enforce discipline — never raise risk. A drawdown breach forces a
  steeply negative score.

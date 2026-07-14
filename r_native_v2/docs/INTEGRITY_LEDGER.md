# Integrity Ledger — R Native 2 hub integration

> Honest record of observed correctness/data issues found during integration.
> Rule: observe + record, do NOT silently fix live engines/genomes; resolve in a gated C-phase.
> (The only proven edge is discipline — `memory/project_real_edge_discipline.md`.)

| # | Item | Observed | Severity | Status / resolution path |
|---|------|----------|----------|--------------------------|
| INT-01 | EURUSDm genome `session_filter == []` | `live_genome__EURUSDm.json` (EUR-NATIVE-G1) has empty `session_filter`, so the hub's derived `always_open=True`. **FX is NOT 24/7** — if a bot trusted `always_open` for EUR it could trade the weekend gap. Surfaced via `/state.personas`. | Medium (latent — depends on whether any executor reads this flag for EUR) | Recorded; **not fixed** (don't touch live genome). Resolve in the C-phase "session/honesty gate" — review FX genomes' session_filter; crypto-only should be `always_open`. Owner decision before edit. |

## Notes
- Crypto (BTCUSDm, BTC-NATIVE-G1) `session_filter == []` is **correct** (24/7 market).
- The hub reports flags faithfully; it does not enforce or correct them (read-only).

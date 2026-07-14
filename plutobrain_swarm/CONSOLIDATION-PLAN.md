# EA Consolidation Plan — Migration Planner (A-11) output

Generated from the swarm's classified `version_clusters.json`. Each family below is
classified so we never delete unique code. **Nothing here has been changed yet.**

## 1. Grid Tester GOLD — `agentic_profiled_grid_tester_gold_dna_evolve` · DIVERGENT
- `v7_2_DNA_EVOLVE.mq5` (71 KB, `#property version 7.20`) — **has 13 functions v7_3 lacks**:
  `ConfidenceScoreForSide`, `ConfidenceLotFactorForSide`, `ConfidenceTPFactorForBasket`,
  `ConfidenceTelemetryJSON`, `IndicatorADX/RSI/MFI/MACDHist`, `DonchianStats`,
  `TrendSignal`, `VolumePercent`, `BufferValue`, `IndicatorTelemetryJSON`
  → an entire **confidence-scoring + indicator-telemetry subsystem**
- `v7_3_DNA_EVOLVE.mq5` (65 KB, `7.21`) — adds **no** new functions; it's a *leaner* fork
- **Decision needed:** is v7_3's stripping intentional (you wanted lean), or is v7_2 the keeper?
  - If v7_2 is canonical → archive v7_3, done.
  - If lean v7_3 is canonical → archive v7_2, accept loss of confidence subsystem.
  - If you want both feature sets in one → I merge v7_2's confidence/telemetry fns into v7_3.

## 2. CLAUDE_FOOTPRINT — `claude_footprint` · DIVERGENT (3 variants, not versions)
- `v1.mq5` — unique: `DetectSupplyDemandZones`, `RenderSupplyDemandZones`,
  `ExportFootprintToJSON`, `RenderSessionVP`, `OnTick_AggressorAggregate`, cell-render styles
- `v3.mq5` — unique: `CalcEMA`, `CalcRSI`, `RenderSessionFrames`, `RenderSessionVPLines`
- `v4.mq5` — the newest; dropped both sets above
- These look like **three different chart tools** (supply/demand vs indicators vs v4's focus).
- **Decision needed:** are these intentionally separate tools (keep all, suppress the KPI),
  or should they become one footprint EA with all features (I merge)?

## 3. Stoch_Reversion_M3 · IDENTICAL (byte-for-byte)
- `live_ea/Stoch_Reversion_M3.mq5` == `r-native-pipflow/mql5_templates/Stoch_Reversion_M3.mq5`
- The `live_ea` copy is the deployable one; the pipflow/templates copy is a redundant mirror.
- **Safe action (reversible):** keep `live_ea` as canonical; archive the pipflow mirror — *iff*
  pipflow doesn't compile from its own templates dir. Needs a 1-line check first.

## 4. r_strategy_template · IDENTICAL CONTENT (CRLF vs LF only)
- `r_native/mql5_templates/` vs `r-native-pipflow/mql5_templates/` — same content, different
  line endings. These are the **R-Native generator templates** (see `mql5_export.py`).
- Two parallel subsystems each keep their own copy by design. **Recommendation: leave as-is**
  (or normalize line endings only). Not a real consolidation target.

---
### Summary
| Family | Class | Recommended |
|---|---|---|
| Grid v7_2/v7_3 | divergent | **your call** — which is canonical, or merge |
| FOOTPRINT v1/v3/v4 | divergent | **your call** — separate tools, or merge into one |
| Stoch_Reversion_M3 | identical | archive pipflow mirror (after 1 ref-check) |
| r_strategy_template | identical-content | leave / normalize EOL only |

# R-Native — Maximum-Rigor Edge Hunt: Honest Results

_Generated 2026-07-14. All results below come from REAL strict walk-forward backtests
(next-bar entry, conservative SL-before-TP intrabar, round-trip spread cost subtracted
in price units before R conversion, 67/33 IS/OOS time split, params optimized on IS
ONLY and measured on held-out OOS). Offline cached bars, no live-MT5 contention._

**Deploy gate:** an edge is deploy-grade ONLY if it (1) survives OOS at t>=2, n>=30,
AND (2) also survives adversarial refutation (anti-overlap de-correlation, direction
symmetry, attribution, cost-stress, regime slicing). Two families cleared bar (1).
**ZERO cleared bar (2) cleanly enough to deploy live.** See verdict.

---

## Family-by-family OOS outcome + failure mode

### 1. Time-of-day drift (1-hour hold, H1) — FAILED
- **OOS:** BTCJPYm h22 LONG, n=275, +4.20bp/trade, t=1.43, WR 54.9%. Fails t>=2.
- **Failure mode:** Selection/mining bias. IS drift (+4.84bp, t2.13) shrank to t=1.43 OOS;
  #2 IS candidate flipped sign OOS (t=-2.03); 0/10 top-IS candidates survived at t>=2.
  Only 2 of 1334 cells even reached IS t>=2 (fewer than chance). No time-of-day edge net of cost.

### 2. Donchian-20 breakout + ATR vol-regime filter — DECISIVELY DEAD
- **OOS breakout [0.6,0.7):** mean_R -0.1033, PF 0.836, t=-5.73, n=4843. All 10 vol deciles
  negative (t<-5). MR base equally dead (every decile negative OOS).
- **Failure mode:** Base entries are net-negative in EVERY volatility decile — cost/frequency
  dominates. Vol conditioning merely re-slices a losing distribution; IS-best band did not keep
  its rank OOS. Manufactures no edge.

### 3. Multi-timeframe (M15/H1) confluence gate on M5 continuation — BRUTALLY NEGATIVE
- **OOS locked k=3:** n=27576, expR -0.4850, t=-56.8, PF 0.50. Worsens monotonically with confluence.
- **Failure mode (two independent):** (a) M5 risk distance tiny → spread averages 0.353R/trade;
  (b) confluence has NEGATIVE predictive value even gross of cost (gross expR -0.043→-0.079, WR
  0.319→0.307 as k rises) — high agreement selects later, exhausted entries. Raising the threshold
  monotonically HURTS.

### 4. Liquidity-sweep / stop-hunt reversal — NO_EDGE
- **OOS best of 132:** +0.062R, PF 1.08, t=0.85, n=615. 0/132 survive; universe OOS -18,146R.
- **Failure mode:** SL sits on the sweep-bar volatility spike (tapped constantly); a sweep is a
  continuation more often than a trap, so fading it loses; cost compounds. 12 cells positive IS →
  negative OOS (overfit signature).

### 5. Prev-day H/L mean-reversion fade (session-gated) — DEAD IN-SAMPLE
- **OOS forced (least-bad gold):** n=1675, meanR -0.0475, PF 0.91, t=-1.95. No config ever lockable.
- **Failure mode:** Prev-day extremes act as breakout/continuation pivots, NOT reversal walls.
  Raw mean-R negative before cost — structural, not a cost artifact. Every session slice negative;
  robust across EURGBP/USDCHF/EURUSD (t to -22). No positive IS config existed to lock.

### 6. Spike/news momentum continuation — NO_EDGE
- **OOS:** grid-wide 0/16 survive. Gold M5 +0.966R/PF2.87 but n=14, t=1.74 (fails). Largest sample
  (silver M5, n=490) -0.20R, t=-2.67.
- **Failure mode:** IS winners sign-flip OOS; the only OOS-positive cells are rare high-K picks with
  n<30 (small-sample mirage); where samples are large, flat-to-negative after cost.

### 7. Exit-quality optimization (14 exits on fixed breakout entry) — NO EDGE FROM EXITS
- **OOS chosen (time60):** -0.269R vs baseline TP2R -0.239R. Paired delta -0.030R, t=-1.69, over 9066
  trades. IS-best exit UNDERPERFORMS fixed-R OOS.
- **Failure mode:** IS-ranked best exit (time60) became OOS-WORST of 14; IS/OOS exit rankings
  near-uncorrelated. All 14 exits ~-0.2R OOS. Exit engineering rearranges a losing distribution
  without creating edge.

### 8. Intermarket lead-lag momentum spillover — NO_EDGE
- **OOS (silver→gold, locked):** n=412, -1.73bp/trade, t=-1.35, net negative. IS edge reversed sign.
- **Failure mode:** Definitive data-snooping signature — IS and OOS performance ANTI-correlated.
  The only positive-OOS configs had NEGATIVE IS t-stats (un-selectable honestly). Correlation is
  contemporaneous-only, not a tradeable lead.

### 9. Fair-Value-Gap (3-candle) mitigation continuation — OOS-POSITIVE, BUT NOT REFUTATION-CLEARED
- **OOS (H1):** n=3678, expR +0.0922, PF 1.208, t=+5.64, WR 59.2%, netR +339.2R, boot-CI [+0.060,+0.124]
  excludes 0. Passed OOS.
- **Robustness it DID pass:** breadth 13/14 symbols net+; both directions independently + (LONG t5.67,
  SHORT t2.23); trend-filter attribution shows edge is FVG-structural not long-beta.
- **Why it does NOT clear the deploy gate:** cost-doubling kills it — x1.5 t=2.63, **x2.0 t=-0.37 (DEAD)**.
  Family as a whole FAILS: M5 firmly negative (expR -0.31, t=-25.2), M15 negative (t=-3.65); only H1
  survives. Best-of-24x3-cell multiple-comparison exposure. A thin 1:1 scalp whose survival depends on
  good spreads/execution — exactly the fragility the NO_EDGE ledger warns about.

### 10. XAUUSDm H1 20-bar breakout LONG (2R) — OOS-POSITIVE, BUT TREND-CONDITIONAL & UN-REFUTED
- **OOS raw:** n=515, PF 2.21, expR +0.499R, WR 57.3%, boot-CI [0.389,0.611]. Reproduces the historical
  headline to the digit on fresh data.
- **Honest anti-overlap correction:** raw t=8.33 is overlap-inflated pseudo-replication; the de-correlated
  NON-overlapping series is n=53, PF 1.95, t=2.24 — clears t>=2/n>=30 (survives the same correction that
  sank BTCUSDm-short and XAUUSDm-M5-short). Recent-window flag reversed (newest PF 1.76, t=3.73).
- **Why it does NOT clear the deploy gate:** it is a **trend-capture edge, not a symmetric edge**
  (BREAKOUT_short is a known loser); long-only on an asset that trended up 2023-2026. It will bleed in a
  sustained downtrend/chop — i.e. the "edge" is partly the 3-year gold bull, and it has NOT been through
  adversarial regime-refutation. Non-overlap t=2.24 is thin.

---

## VERDICT: NO_EDGE_CONFIRMED (no deploy-grade edge)

**Ten families tested at maximum rigor. Eight died outright OOS (t from -1.35 to -56.8, PFs 0.5–1.1).
Two (FVG-H1, gold-H1-breakout) survived the OOS walk-forward — but NEITHER survived adversarial
refutation, so the confirmed-edge / proof-gate list is EMPTY.**

- FVG-H1 dies at 2x cost (t=-0.37) and only on one timeframe of three — fragile, execution-dependent.
- Gold-H1-breakout is a long-only trend-capture whose de-correlated significance is thin (t=2.24) and
  whose "edge" is confounded with the 2023-2026 gold uptrend; it has not been regime-refuted.

Neither meets the bar for live size. They are the ONLY two candidates worth a forward-paper prove
(`edge_prover.py`, one-position busy gate, no up-sizing) — NOT live capital, and NOT until forward paper
independently confirms them.

### No false edge was manufactured. That is the point.
This hunt did what it was supposed to do: it **refused to promote noise into a live strategy.** Every
"clever" predictive-entry family (breakout, MR, sweep-reversal, MTF confluence, spike continuation,
lead-lag, level-fade, time-of-day) is a coin-flip-or-worse net of cost. This confirms and extends the
project's standing NO_EDGE ledger.

### The REAL, repeatedly-confirmed R-Native edges remain:
1. **Discipline** — night filter, score gates, no-stack-on-red, daily loss caps. The single documented
   winning regime (user manual excl. 22-08 UTC: +$904, PF 3.36) was a discipline artifact, not prediction.
2. **Sizing** — the only lever with a real coefficient (manual gold >=0.2 lot -$45.6k vs <0.2 lot +$30.5k).
   Small, capped, 2%-max-per-trade sizing IS the edge.
3. **Management** — breakeven/trailing tail-nets, margin guard, master_floor backstop. Management protects
   capital; it does not (per Family 7) create predictive edge.
4. **Cost control** — trade RARELY. Cost/frequency is the dominant bottleneck that sinks every near-coin-flip
   entry family above. Fewer, cleaner trades beat more "signals."

**Bottom line: NO_EDGE_CONFIRMED. Keep real capital on discipline/sizing/management/cost. Do not deploy any
predictive entry filter. FVG-H1 and gold-H1-breakout may proceed to forward-paper only.**

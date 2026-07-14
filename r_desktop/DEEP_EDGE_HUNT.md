# DEEP EDGE HUNT — Honest Verdict of the Deepest Sweep Yet

_Generated 2026-07-14. Strict walk-forward (IS 67% tunes, OOS 33% measures once), costs charged in price units, conservative SL-first intrabar fills, non-overlapping trades so per-trade R's are ~independent for the t-stat. Deployment bar: OOS `expR > 0` AND `n >= 30` AND `t >= 3` (Bonferroni-aware, because the scan tests hundreds of cells). Anything below the bar is noise, not an edge._

**16 hypothesis families tested. 1 cell survived the family sweep's adversarial refutation (NR7 breakout, USTECm M15). 15 families died. No family earned LIVE capital — the survivor goes to forward-paper only.**

---

## 1. The HIGH-WIN-RATE TRAP — why WR is NOT profit

This family was built specifically to expose the most seductive retail lie: "high win rate = good strategy." Rule = trend-pullback micro-scalp with **TIGHT TP / WIDE SL** (SL = 3.0×ATR14 wide, TP = 0.5×SL_dist tight). Tight-TP/wide-SL mechanically manufactures a high win rate because WR ≈ SL / (SL + TP). But the money says otherwise:

| Cell | **Win Rate** | **Expectancy (OOS)** | **t** | PF | **Max DD** | Verdict |
|---|---|---|---|---|---|---|
| **XAUUSDm M5 (flagship)** | **67.3% WIN** | **−0.0111 R** | −1.01 | 0.97 | **−80.1 R** | LOSES money |
| USOIL H1 | **79.9% WIN** | −0.0046 R | — | 0.98 | — | LOSES money |
| EURUSD / GBPUSD M5 | ~63% WIN | **−0.24 R** | ~−21 | — | **~−1000 R** | catastrophic |
| USOIL M5 / M15 (only positives) | ~55–60% | +0.008 / +0.010 R | 0.74 / 0.81 | — | — | noise (see below) |

**Read the flagship line aloud: a strategy that wins 67.3% of the time and still bleeds money, with an 80R drawdown.** The two mildly positive cells (USOIL M5/M15) are worse than they look — both had *negative in-sample* expectancy (−0.011 / −0.015), so their positive OOS is pure luck the IS selection could not have foreseen. A "high WR system" you would have deployed on that basis would have cost real money.

**Why the geometry is a trap:**
1. Expectancy = `TP·WR − SL·(1−WR) − cost`. For tight-TP/wide-SL this is ≈ 0 *before* cost and strictly negative *after* cost.
2. Rare wide-SL losses erase dozens of small tight-TP wins — one −3R loss undoes six +0.5R wins.
3. Cost is paid on every one of the many trades; the tiny TP is dwarfed by spread (fatal on FX M5).

The IS grid never found a single positive-expectancy config anywhere in the 12-cell family. **10 of 12 cells: high WR, negative expectancy.** WR ≠ edge. Rejected.

---

## 2. Per-Family Scoreboard (OOS best cell) + Failure Mode

| # | Family | Best-cell OOS expR | t | WR | Max DD | Survives | Failure mode |
|---|---|---|---|---|---|---|---|
| 1 | High-WR trap (tight-TP/wide-SL) | −0.0111 | −1.01 | 0.673 | −80.1 | ❌ | High WR is a geometric artifact; negative after cost |
| 2 | Directional ML classifier (24 feat) | +0.0721 | 3.15 | 0.545 | −76 | ❌ | Lone t>3 cell, but seed/fold-fragile (t 0.45→3.80); headline gold cell died t=−2.5 |
| 3 | Tick-volume surge (order-flow proxy) | +0.3885 | 2.02 | 0.48 | −6.3 | ❌ | Best of 90 cells, t<3; small-n JPY cherry-pick; liquid pairs die |
| 4 | Post-news 08:30-ET continuation | +0.0237 | 0.124 | 0.367 | −9.83 | ❌ | No news archive; real events too rare (NFP n≈6); diluted = coin-flip |
| 5 | Stat-arb pairs (log-spread MR) | +0.1361 | 1.74 | 0.70 | −4.1 | ❌ | IS-positive cells flip negative OOS (cointegration drift); high WR trap |
| 6 | Session Opening-Range Breakout | +0.136 | 0.68 | 0.42 | −5.7 | ❌ | IS params don't carry; FX legs outright negative |
| 7 | Regime-conditional trend-follow | +0.075 | 0.40 | 0.28 | −14.72 | ❌ | ADX/HTF gate is lagging; confirms trend already happened |
| 8 | MR at BB/RSI extremes (range-gated) | +0.30547 | 2.038 | 0.461 | −15.46 | ❌ | Only positive cell had NEGATIVE IS exp; t<3; gold actively loses |
| 9 | PDH/PDL rejection bounce | −0.0898 | −1.18 | 0.488 | −20.05 | ❌ | ALL 16 cells negative OOS; FX cells significantly LOSE (t=−6.8) |
| 10 | Multi-TF strict alignment | −0.0944 | −1.50 | 0.28 | −94.1 | ❌ | Lagging confirmation chases exhaustion; USDJPY genuinely negative |
| 11 | Engulfing continuation | −0.2191 | −15.81 | 0.244 | −3570.4 | ❌ | Momentum chase; move already happened; negative in ALL 16 IS combos |
| 12 | Time-of-day seasonality | +0.0223 | 0.78 | 0.45 | −16.07 | ❌ | IS-best hour doesn't persist; 11/14 flip negative OOS |
| **13** | **NR7 volatility-expansion breakout** | **+0.2979** | **5.47** | **0.34** | **−21** | ✅ | **SURVIVES all stress (see §3)** |
| 14 | Ensemble voting (5 weak momentum) | +0.0562 | 0.86 | 0.357 | −21.96 | ❌ | Signals correlated → no diversification; ≤ best lone signal |
| 15 | Carry / JPY-cross basket | +0.4277 | 1.52 | 0.585 | −39.86 | ❌ | Correlation-inflated (ρ≈0.69 → eff-n~87 → t~1.5); one macro bet |
| 16 | ROC momentum-continuation | +0.0721 | 0.71 | 0.36 | −17.1 | ❌ | NO_EDGE; the only CI-excludes-zero cells are strongly NEGATIVE |

**Pattern across the sweep:** tempting IS expectancy that evaporates OOS (overfit-to-window), high win rates masking negative expectancy (geometry trap #1, #5), lagging/coincident filters that confirm moves already spent (#7, #10, #11), correlation-inflated pooled t-stats (#15), and cost eating any thin momentum signal (#16). Every classic false-positive avoided.

---

## 3. The One Survivor — NR7 Volatility-Expansion Breakout (USTECm M15)

**Rule:** an NR7 *contraction* bar (narrowest H−L of the last 7 bars, detected at the **close of bar i** using only data ≤ i) arms a pending STOP breakout on the **next bar only**. Buy-stop = high[i], sell-stop = low[i] (buffer 0). Fill at the stop price (or at open on a gap-through); if both stops trigger the same bar → skip the whipsaw. SL = 1.0×ATR14, TP = 3R. Manage from the entry bar; SL assumed first when SL & TP share a bar. Round-trip cost 3.0 index points subtracted in price units.

**Why it survived (adversarial stress, all passed):**
- Base OOS **t = 5.47** clears the Bonferroni bar (16 cells × 36 IS combos ≈ 576 tests, t_crit ≈ 3.9).
- Robust to **2× conservative cost** (t = 4.13); only dies at 5× (~15pt spread).
- **Entire SL/TP neighborhood positive** OOS (t 2.2–5.5) — not a lone grid spike.
- Both OOS **sub-period halves consistent** (t = 3.75 / 3.98).
- Removing top-5 winners barely moves it (expR 0.298 → 0.287; top-5 = 4% of total R).
- Max DD only **−21 R over 1212 trades** — good DD/edge ratio.

**Residual risks (to watch, not disqualifying):**
1. Low-WR (34%) asymmetric profile (median R = −1.05) — **requires discipline**: hold every loser to exactly 1 ATR, let 3R winners run. Any manual interference destroys it.
2. OOS window is only ~5 months of a Nasdaq bull regime; a sustained low-vol chop regime could compress the edge.
3. Dies if real USTECm spread exceeds ~9 pts.

**Secondary candidate REJECTED:** BTCUSDm H1 NR7 hit raw t=3.05 but fails Bonferroni (3.9), fails 2× cost (t=2.63), unstable across halves → likely false positive.

---

## 4. VERDICT

### `EDGE_FOUND` — forward-paper / DEMO only (NOT live-confirmed)

The sweep produced exactly one cell that survived its full adversarial refutation: **NR7 volatility-expansion breakout on USTECm M15**. This is not a manufactured edge — it measured t=5.47 and held through 2× cost, neighborhood, sub-period, and top-winner-removal stress. It is the strongest single result in this project's long history of NO_EDGE findings.

**But it is not confirmed for live capital.** The honest harness line reads `Survived adversarial refutation: []` at the LIVE bar: a single symbol, a single ~5-month bull regime, and a hard spread-sensitivity are exactly the conditions that must be re-proven forward before one dollar of real risk. The gate between "survived the sweep" and "deployable edge" is forward-paper reproduction. That is where NR7 goes now.

**edge_prover deploy spec (DEMO forward-paper):**

| Field | Value |
|---|---|
| Symbol | `USTECm` |
| Timeframe | `M15` |
| Setup | NR7 contraction bar (narrowest H−L of last 7, detected at close of bar i) |
| Entry | pending STOP next bar only: buy-stop = high[i], sell-stop = low[i]; skip if both hit same bar |
| SL | 1.0 × ATR14 (= 1R). **Hold to exactly 1 ATR — no manual widening** |
| TP | 3R (let the winner run to target) |
| Cost assumption | 3.0 index pts round-trip; **auto-veto if live spread > 9 pts** |
| Expected OOS expR | **+0.298 R/trade** (t=5.47), max DD ~−21R over ~1200 trades |
| Position policy | **DEMO, one position at a time, NO upsizing, no stacking** |
| Promotion gate | reproduce expR ≥ +0.15R over **≥ 100 forward-paper trades** AND DD ≤ −25R before any live discussion. Kill on: spread breach, or forward expR < 0 after n≥50. |

---

## 5. Forward-Paper Plan for the 2 Prior Candidates

Both earlier survivors are carried forward in the same DEMO one-position, no-upsize regime, tracked by `edge_prover` alongside NR7:

**A) Gold-H1 breakout (XAUUSDm H1)** — the only cell that ever survived `edge_prover` in prior hunts. Forward-paper: continue logging live OOS trades; promotion gate = maintain positive expR over ≥ 100 forward trades with DD within historical envelope. Watch for the same regime-window fragility that killed everything else in this sweep.

**B) FVG-H1 (fair-value-gap fill, H1)** — prior candidate, weight-0 in production pending proof. Forward-paper: run as measurement-only shadow (no capital), record fill outcomes vs fixed-R baseline. Prior evidence was weak (FVG repeatedly measured as ~coin-flip); keep it on the bench and let the forward number decide, not the narrative.

**Rule for all three:** measure forward in DEMO, no upsizing, no manual override of stops. A candidate is promoted ONLY by its honest forward number, and killed the moment it goes negative past n≥50.

---

## 6. What Actually Protects Capital

Fifteen of sixteen families died, and the one survivor is quarantined to forward-paper. That is the sweep working — refusing to manufacture an edge is itself the win. The measured, repeatable edges remain what they have always been in this project:

- **Discipline** — no night trading, no revenge, no naked stacking (the documented killers).
- **Sizing** — small lots; the single largest real P&L lever ever measured here.
- **Management** — hold winners to target, cut losers to exactly the planned R.
- **Cost** — trade rarely; spread is the bottleneck, not signal count.

NR7 is a genuine, rare, forward-testable candidate — but until it reproduces live-paper, the bot's job is unchanged: **enforce discipline, control size, manage exits, respect cost.**

---

**RETURN TAG: `EDGE_FOUND` (forward-paper/DEMO only) — NR7 breakout USTECm M15, expR +0.298R t=5.47; LIVE remains `NO_EDGE_CONFIRMED` pending ≥100 forward-paper trades. 15/16 families rejected.**

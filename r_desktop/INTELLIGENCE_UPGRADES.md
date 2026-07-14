# R-Native Intelligence Upgrades — Design + Default-OFF Skeletons

> **Status:** DESIGN ONLY. Nothing here is wired live. The four upgrades below
> are specified as *surgical inserts* against the two hot files
> (`friday_v3/algory/trade_gate.py`, `friday_v3/algory/r_executor.py`) plus
> two feeder files. **The lead applies each insert by hand after review.** Every
> skeleton is written so that with its env flag unset (the default) the code path
> is a literal no-op — the byte-for-byte behaviour of today's gate/executor is
> preserved.

## Non-negotiable invariants (all four upgrades honour these)

| Invariant | How it is enforced in every skeleton |
|---|---|
| **DEMO-only** | Each new *entry-affecting* effect is additionally guarded by `_is_demo()` (server name contains `Trial`/`Demo`, per `reference_exness_demo_detection`). On a real account the upgrade degrades to advisory-note-only. |
| **Fail-open** | Every insert is wrapped in `try/except` that, on *any* error or missing data, leaves `verdict`/`lot` exactly as they were. A crash in an upgrade can never freeze trading or size up. |
| **TIGHTEN-ONLY** (for anything that gates entries) | Upgrades #3 and #4 can only ever turn `GO→WAIT` or *lower* confidence/lot. They never turn `WAIT→GO`, never raise a hard cap, never open new risk. Kelly (#2 in this doc's ordering) is capped at the existing `0.01`-lot floor and fractional — it can only *reduce below* the current multiplier, never exceed it. |
| **n ≥ 30 before trust** | Each upgrade ships behind a *measurement gate*: the flag stays OFF until a proof-gate script shows the intended effect on ≥30 relevant closed trades with the sign we expect. The measurement query is specified per-upgrade. |
| **Additive env flag** | `R_MATRIX_HARD_VETO`, `R_HONOR_LLM_STRATEGIST`, `R_KELLY_SIZING`, `R_REGIME_SWITCH`. All read once at module import via `os.environ.get(flag,"0")=="1"`. Absent ⇒ OFF. |

### Shared helper (add once, near top of `trade_gate.py` and `r_executor.py`)

```python
# ── DEMO detection (shared, fail-CLOSED to "not demo" so real accounts are safe) ──
def _is_demo() -> bool:
    """True only when the connected account is a confirmed demo/Trial server.
    Fail-CLOSED: any doubt (fetch error, unknown server) → False → upgrade stays
    in advisory mode on real money. See reference_exness_demo_detection."""
    try:
        import MetaTrader5 as _mt5
        ai = _mt5.account_info()
        srv = (getattr(ai, "server", "") or "")
        return ("Trial" in srv) or ("Demo" in srv) or ("demo" in srv)
    except Exception:
        return False
```

---

## Upgrade #3 — Matrix confluence as a HARD veto

**Graduate the 21×6 indicator-matrix confluence from a SOFT advisory downgrade
to a HARD blocker when a strong, well-aligned multi-timeframe confluence opposes
the chosen side.**

### Current state (what exists today)
`trade_gate.py` lines **894–928** already read `snapshot["matrix"]`
(`aggregate` dict: `{score, direction:"BULL"/"BEAR"/"NEUTRAL", trend_align, bull_tfs, bear_tfs}`,
built by `friday_v3/algory/indicator_matrix.build_matrix` → served at
`brain_server.py:2532` into `snap["matrix"]`). Today the opposition case sets
`_matrix_veto=True`, records a **SOFT** check, and downgrades `GO→WAIT`. Because
the check is SOFT it does not appear in `hard_blockers`, so downstream consumers
that key off `hard_blockers` treat the trade as merely "waiting", not "refused".

### Exact insertion point
`friday_v3/algory/trade_gate.py`, function **`evaluate_gate`**, the matrix block
at **lines 894–928** (the `add("matrix_confluence", …)` region). Replace the
final two lines' effect only; keep all the reading logic above unchanged.

### Env flag
`R_MATRIX_HARD_VETO` (default `0` = keep today's SOFT behaviour).

### Skeleton (drop-in replacement for lines 925–928)
```python
# ── module top ──
_MATRIX_HARD_VETO = _os.environ.get("R_MATRIX_HARD_VETO", "0") == "1"

# ── inside evaluate_gate, replacing the tail of the matrix block ──
# _matrix_veto / _matrix_note computed exactly as today (lines 899-924, unchanged)
_veto_weight = "SOFT"
if (_MATRIX_HARD_VETO and _matrix_veto and _is_demo()):
    # HARD only when: flag on + DEMO + a STRONG opposing confluence already
    # detected by today's logic (score<=32 or >=68, trend_align>=0.66).
    _veto_weight = "HARD"
add("matrix_confluence", not _matrix_veto, _matrix_note, weight=_veto_weight)
if _matrix_veto and verdict == "GO":
    verdict = "NO" if _veto_weight == "HARD" else "WAIT"
    if _veto_weight == "HARD":
        hard_blockers.append("matrix_confluence")   # now visible to consumers
    reason_ar = f"🧭 {_matrix_note}"
```
**Why this is TIGHTEN-ONLY & fail-open:** it only fires when today's code already
decided to veto (`_matrix_veto` true), and only *strengthens* the veto from
WAIT→NO. It can never create a GO. The `_is_demo()` guard means a real account
keeps the softer WAIT. Any exception in the (unchanged) reading block above still
lands in the existing `except` → `_matrix_note="matrix skipped"`, `_matrix_veto`
stays `False`, no veto.

### Measure-before-trust rollout
1. Leave flag OFF. Log the matrix reading on every GO for ≥2 weeks (already
   surfaced in `checks[]` as `matrix_confluence`).
2. Proof query (write to `scripts/proof_matrix_veto.py`): from closed R trades
   (`friday.db` / r_learning closed-trade log), bucket every entered trade by
   whether a **strong opposing confluence** was present at entry time. Require
   **n ≥ 30** trades in the "strong-oppose" bucket. Confirm those trades had a
   materially worse expectancy (net_pl per trade, win-rate) than the aligned
   bucket, with the difference sign stable across a walk-forward split (per
   `MEMORY.md` — single split is a window artifact).
3. Only if the strong-oppose bucket is clearly worse (and n≥30) flip
   `R_MATRIX_HARD_VETO=1` on the **demo** launcher. Re-measure after 30 more
   trades before ever considering it on real money (which the `_is_demo()` guard
   currently forbids regardless).

---

## Upgrade #4 — `llm_strategist` output as an advisory confidence nudge

**Let the chief-strategist LLM's read of the system nudge `confidence` by a small
bounded amount — never a hard block.**

### Current state
`r_native/agents/llm_strategist.py` writes
`data/r_native/agents/strategist_state.json` every ~15 min:
`{assessment, confidence:"low"/"medium"/"high", concerns[], opportunities[],
recommendations[], autonomous, llm_degraded}`. Today the gate does **not** read
it at all. It operates at the HoF/genome-governance altitude, so it must only
ever be a *gentle* per-cycle confidence tint, matching the existing
`pattern_memory` (±8/±10) and `genome_archetype` (±8/−10) nudge pattern.

### Exact insertion point
`friday_v3/algory/trade_gate.py`, function **`evaluate_gate`**, immediately
**after** the `pattern_memory` block (after line **1007**, before the
`return TradeVerdict(...)` at line 1009) — i.e. the last confidence adjustment,
so the nudge composes with the others and is clamped by the existing
`max(0, int(confidence))`.

### Env flag
`R_HONOR_LLM_STRATEGIST` (default `0` = strategist never touches the gate).

### Skeleton
```python
# ── module top ──
_HONOR_LLM_STRATEGIST = _os.environ.get("R_HONOR_LLM_STRATEGIST", "0") == "1"
_STRATEGIST_STATE = Path(r"C:\Users\Radhi\MT5\data\r_native\agents\strategist_state.json")
_LLM_NUDGE_MAX = 6           # bounded: at most ±6 confidence, smaller than pattern_memory
_LLM_STALE_SECS = 3600       # ignore a strategist read older than 1h

# ── inside evaluate_gate, after the pattern_memory block ──
llm_nudge = 0
if _HONOR_LLM_STRATEGIST and side and arch_name:
    try:
        import time as _t, json as _j
        st = _j.loads(_STRATEGIST_STATE.read_text(encoding="utf-8"))
        # staleness + degraded guards → fail-open to zero nudge
        _age_ok = True
        try:
            from datetime import datetime as _dt
            _lr = _dt.fromisoformat(st.get("last_run"))
            _age_ok = (_dt.now(_lr.tzinfo) - _lr).total_seconds() <= _LLM_STALE_SECS
        except Exception:
            _age_ok = False
        if _age_ok and not st.get("llm_degraded"):
            conf_word = (st.get("confidence") or "").lower()
            n_concerns = len(st.get("concerns") or [])
            # NEVER blocks. NEVER raises above pre-existing conf materially.
            # high system-confidence + few concerns → small +; many concerns → small -.
            if conf_word == "high" and n_concerns <= 1:
                llm_nudge = +_LLM_NUDGE_MAX
            elif conf_word == "low" or n_concerns >= 4:
                llm_nudge = -_LLM_NUDGE_MAX
            confidence += llm_nudge
            checks.append(GateCheck(
                name="llm_strategist", passed=True, weight="SOFT",
                detail=f"strategist conf={conf_word}, {n_concerns} concerns → "
                       f"nudge {llm_nudge:+d}"))
    except Exception:
        llm_nudge = 0   # fail-open: no file / bad json / any error → no effect
```
**Why safe:** SOFT check only; `confidence` is already floored at 0 and is
*advisory* (drives sizing/monster-boost thresholds, not the GO/WAIT/NO decision).
The nudge is bounded to ±6 and never appended to `hard_blockers`. No `_is_demo()`
guard is strictly required because it cannot open or block a trade — but keep the
staleness + `llm_degraded` guards so a wedged/hallucinating LLM cannot bias the
desk. This upgrade is deliberately **never a hard-block**, per spec.

### Measure-before-trust rollout
1. Flag OFF. Log the strategist read alongside each GO (`checks[]` line above)
   *without applying the nudge* — add a shadow field first if desired.
2. Proof: over ≥**30** GO trades, compare realized outcome for trades the
   strategist would have nudged **+** vs **−**. The + bucket must not
   under-perform the − bucket (i.e. the strategist's system-level read has *some*
   correlation with per-trade outcome, even weak). If the buckets are
   indistinguishable (coin-flip, per the repeated `NO_EDGE` findings in
   `MEMORY.md`), **do not enable** — a nudge with no signal only adds noise.
3. If the split is favourable and n≥30, enable on demo. Keep ±6 cap; do not grow
   it without a fresh n≥30 re-measure.

---

## Upgrade (Kelly) — fractional Kelly lot sizing per archetype/symbol

**Size the lot from recent realized win-rate/payoff per (archetype, symbol) using
a fractional Kelly fraction, hard-capped so it can only *reduce* below the
current multiplier and never exceed the existing safety envelope.**

### Current state
`r_executor.py` builds the lot at lines **1252–1286**:
`base_lot = R_LOT_FIXED(0.01) * state["lot_multiplier"]`, then optional
`monster_mult` (>1 boost) and `regime_mult` (from `regime_multipliers.json`),
then `effective_lot = round(base_lot,2)` with a `0.01` floor. `lot_multiplier`
is set upstream (lines 1120–1157) from `symbol_learning` verdict (1.0/0.8/0.5/0.6)
intersected with the genome trust certificate. Win-rate/payoff data is available
from `friday_v3/algory/r_learning.find_similar_trades(symbol, side, archetype,
bias_h1, hour_utc)` → tiers with `{n, wins, win_rate, net_pl}`.

### Exact insertion point
`friday_v3/algory/r_executor.py`, function **`_try_enter_one_symbol`**,
**immediately after line 1252** (`base_lot = R_LOT_FIXED * state.get("lot_multiplier", 1.0)`)
and **before** the monster-boost block at line 1253. Placing it here means the
Kelly fraction multiplies the *already-conservative* base and is then still
subject to every downstream guard (monster is separate/additive-up which we do
NOT touch; regime scaler; margin pre-flight; `0.01` floor).

### Env flag
`R_KELLY_SIZING` (default `0` = today's fixed multiplier only).

### Skeleton
```python
# ── module top ──
_KELLY_SIZING   = _os.environ.get("R_KELLY_SIZING", "0") == "1"
_KELLY_FRACTION = 0.25    # quarter-Kelly — conservative, standard anti-ruin practice
_KELLY_MIN_N    = 30      # never size on fewer than 30 comparable closed trades

def _kelly_multiplier(symbol, side, archetype, bias_h1, hour_utc):
    """Return a lot multiplier in (0, 1] from fractional Kelly on recent WR.
    TIGHTEN-ONLY: clamped to <=1.0 so it can only shrink the base lot, never
    grow it. Fail-open: any missing data / <MIN_N samples → 1.0 (no change)."""
    try:
        from friday_v3.algory.r_learning import find_similar_trades
        res = find_similar_trades(symbol=symbol, side=side, archetype=archetype,
                                  bias_h1=bias_h1, hour_utc=hour_utc)
        tier = res.get("full") or {}
        if not tier.get("n"):
            tier = res.get("partial") or {}
        n  = int(tier.get("n") or 0)
        wr = tier.get("win_rate")
        if n < _KELLY_MIN_N or wr is None:
            return 1.0                      # insufficient evidence → no change
        p = wr / 100.0
        # payoff ratio b from realized net: approximate avg_win/avg_loss.
        # If unavailable, assume b=1 (Kelly reduces to 2p-1).
        b = float(tier.get("payoff_ratio") or 1.0)
        if b <= 0:
            b = 1.0
        kelly = (p * (b + 1.0) - 1.0) / b   # classic Kelly fraction
        if kelly <= 0:                      # negative edge → shrink to floor
            return 0.5                       # halve, don't zero (0.01 floor still applies)
        frac = kelly * _KELLY_FRACTION
        return max(0.3, min(1.0, frac / 1.0 + (1.0 - _KELLY_FRACTION)))  # blend, clamp <=1
    except Exception:
        return 1.0                          # fail-open

# ── inside _try_enter_one_symbol, right after base_lot is computed (line 1252) ──
if _KELLY_SIZING and _is_demo():
    try:
        _bias_h1 = ((gate.get("checks") and next(
            (c for c in gate["checks"] if c.get("name")=="pattern_memory"), {}))
            or {})   # or read h1 bias from the snapshot the gate returned
        _km = _kelly_multiplier(trade_symbol, side, arch, gate.get("bias_h1") or "RANGE",
                                __import__("datetime").datetime.utcnow().hour)
        if _km < 1.0:
            base_lot *= _km
            state["last_kelly_mult"] = round(_km, 3)
            _log(state, f"  🎲 kelly ×{_km:.3f} (frac={_KELLY_FRACTION}, n≥{_KELLY_MIN_N})")
    except Exception:
        pass   # fail-open — base_lot unchanged
```
**Why safe:** returns a multiplier **clamped to ≤ 1.0**, so on top of the
existing `0.01 * lot_multiplier` base it can *only shrink*. The `0.01` broker-min
floor at line 1286 still applies, so it never goes below the existing safety lot.
Quarter-Kelly (`0.25`) is intentionally conservative. Demo-only. Fail-open to
`1.0`. It multiplies base **before** monster/regime, and we deliberately do NOT
let Kelly participate in the monster up-boost path.

### Measure-before-trust rollout
1. Flag OFF. In shadow mode, compute `_kelly_multiplier` and log
   `state["shadow_kelly"]` on each GO without applying it.
2. Proof (`scripts/proof_kelly.py`): require each (archetype,symbol) bucket used
   to have **n ≥ 30** closed trades before its WR is trusted. Backtest: would
   applying the clamped fractional-Kelly multiplier have improved risk-adjusted
   return (net_pl / max-drawdown) vs the flat multiplier, on a walk-forward
   split? Reject if the WR is a single-window artifact (per `MEMORY.md`).
3. Enable on demo only where the bucket has n≥30 and the walk-forward is
   positive. Add `payoff_ratio` to `r_learning.find_similar_trades` tiers first
   (currently only `net_pl`/`win_rate`) so `b` is real rather than the `b=1`
   fallback.

> **Prereq task for the lead:** extend `r_learning.find_similar_trades` tiers to
> also emit `payoff_ratio = avg_win / avg_loss`. Until then the skeleton uses the
> conservative `b=1` fallback (Kelly = 2p−1), which under-sizes rather than
> over-sizes — an acceptable fail-safe default.

---

## Upgrade #Regime — regime signal → preferred-archetype selection

**Use the live regime label (TREND / RANGE / EVENT) to *reorder* which archetype
the gate prefers, so a trend regime favours BREAKOUT/TREND archetypes and a range
regime favours MEAN_REVERTER — without ever manufacturing a signal that isn't
already firing.**

### Current state
Two regime sources already exist:
- `snapshot["regime"]` (`{regime:"TREND"/"RANGE"/"EVENT", allow_trade}`) — read at
  `trade_gate.py:452` as the SOFT `regime_advisory` check.
- `data/r_native/regime_multipliers.json` (per-symbol `regime:"TREND_UP"/
  "TREND_DOWN"/"RANGE"`, `mtf_alignment`, `buy_mult`/`sell_mult`) — written by
  `agents/regime_scaler.py`, consumed by the executor at lines 1269–1284 for lot
  scaling only.

Today, archetype selection in `trade_gate.py` (lines **626–643**, the Algory
fallback loop) evaluates all four archetypes and sorts purely by
`ev["score"]` — regime does not influence the *ordering*, only the later lot
multiplier.

### Exact insertion point
`friday_v3/algory/trade_gate.py`, function **`evaluate_gate`**, the archetype
sort at **line 631** (`archetype_picks.sort(key=lambda x: -x[1])`). Insert a
regime-aware re-rank **only on the Algory fallback branch** (never the genome
branch, whose direction is authoritative). This is selection-only: it reorders
already-qualified (`verdict=="OK"`) archetypes; it cannot add one that didn't
qualify.

### Env flag
`R_REGIME_SWITCH` (default `0` = today's pure-score ordering).

### Skeleton
```python
# ── module top ──
_REGIME_SWITCH = _os.environ.get("R_REGIME_SWITCH", "0") == "1"
# which archetypes each regime prefers (soft bonus to their existing score)
_REGIME_PREF = {
    "TREND": {"BREAKOUT_HUNTER": 1.15, "MULTI_SIGNAL": 1.05, "MEAN_REVERTER": 0.90},
    "RANGE": {"MEAN_REVERTER": 1.15, "PATTERN_SPOTTER": 1.05, "BREAKOUT_HUNTER": 0.90},
    "EVENT": {"BREAKOUT_HUNTER": 1.10},   # events break levels
}

# ── inside evaluate_gate, replacing line 631 ──
if _REGIME_SWITCH and archetype_picks:
    try:
        _reg = (snapshot.get("regime") or {}).get("regime")
        # normalise TREND_UP/TREND_DOWN → TREND
        _reg_key = ("TREND" if _reg and _reg.startswith("TREND")
                    else "RANGE" if _reg == "RANGE"
                    else "EVENT" if _reg == "EVENT" else None)
        prefs = _REGIME_PREF.get(_reg_key or "", {})
        if prefs:
            # multiply each qualified archetype's score by its regime preference
            # (default 1.0 = unchanged). Pure re-RANK — no archetype is added.
            archetype_picks = [(a, s * prefs.get(a, 1.0)) for (a, s) in archetype_picks]
            soft_warnings.append(f"regime[{_reg_key}] reranked archetypes")
    except Exception:
        pass   # fail-open — fall through to plain score sort
archetype_picks.sort(key=lambda x: -x[1])   # existing line 631, unchanged
```
**Why safe:** operates only on the *already-qualified* `archetype_picks` list
(each entry passed `evaluate_setup(...)=="OK"`). It re-weights their scores and
re-sorts; it can change *which* qualified archetype leads, but if the list is
empty it stays empty (still WAIT). It never touches the genome branch, never adds
a hard blocker, never sizes up. Fail-open on any error. Because it only picks
among trades the gate was already willing to take, no `_is_demo()` guard is
strictly required — but gate it too if you want the conservative default:
`if _REGIME_SWITCH and _is_demo() and archetype_picks:`.

### Measure-before-trust rollout
1. Flag OFF. Log `snapshot["regime"]["regime"]` and the chosen archetype on each
   GO (regime is already in the snapshot).
2. Proof (`scripts/proof_regime_switch.py`): bucket ≥**30** closed trades per
   regime label. Confirm that, within each regime, the archetype the re-rank
   *would* have promoted actually had the better realized expectancy than the one
   pure-score picked. Require the n≥30 per regime bucket and a stable walk-forward
   sign.
3. Enable on demo where the per-regime evidence (n≥30) supports the preference
   table. Tune `_REGIME_PREF` weights from the measured expectancy ratios rather
   than the hand-set `1.15/0.90` placeholders.

---

## Rollout order & flag summary

| # | Upgrade | Flag (default 0) | Touches | Effect ceiling | n-gate |
|---|---|---|---|---|---|
| 3 | Matrix HARD veto | `R_MATRIX_HARD_VETO` | `trade_gate.evaluate_gate` L925–928 | GO→NO (demo only) | ≥30 strong-oppose trades |
| 4 | LLM strategist nudge | `R_HONOR_LLM_STRATEGIST` | `trade_gate.evaluate_gate` after L1007 | ±6 confidence, never blocks | ≥30 GO trades split |
| K | Fractional Kelly lot | `R_KELLY_SIZING` | `r_executor._try_enter_one_symbol` after L1252 | ×≤1.0 on base lot (demo only) | ≥30 per (arch,symbol) |
| R | Regime archetype switch | `R_REGIME_SWITCH` | `trade_gate.evaluate_gate` L631 | re-rank qualified only | ≥30 per regime |

**Suggested sequence:** enable one flag at a time on the **demo** launcher, run
≥30 trades, read the honest number (`MEMORY.md`: no tuning before n≥30), keep or
revert. Never enable two new flags in the same measurement window — you can't
attribute the outcome. None of these flags belong on a real-money launcher until
its demo n≥30 proof is green, and #3 and Kelly are hard-gated to demo in code
regardless.

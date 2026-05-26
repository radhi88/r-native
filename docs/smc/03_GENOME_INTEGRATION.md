# SMC-Aware Genome Architecture

> How SMC concepts become part of each genome's DNA so the GA discovers
> per-symbol SMC specialists automatically. Touches six layers: genes, signal
> evaluators, SL/TP resolver, combo fitness, lineage breeding, snapshot builder.

---

## 1. New Gene Flags (`genes.py`)

### 1a. SMC Signal flags (6) — appended to `SIGNAL_GENES`

```
use_sig_smc_ob          # vote when bid touches a fresh order block
use_sig_smc_fvg         # vote on FVG fill / mitigation
use_sig_smc_bos         # vote in the direction of last confirmed BOS
use_sig_smc_choch       # vote on CHoCH (reversal of structure)
use_sig_smc_liq_sweep   # vote after a liquidity sweep (stop-hunt reversal)
use_sig_smc_idm         # vote after inducement has been taken
```

Default-on probability in `Genome.random`: **0.10** (lower than the standard
0.20 — SMC signals are richer but rarer; keep populations sparse).
Mutation: standard bit-flip via existing `ALL_GENES` loop.

### 1b. SMC Filter flags (3) — appended to `FILTER_GENES`

```
use_filter_smc_fresh_only       # block if pattern already mitigated
use_filter_smc_htf_alignment    # require H4 BOS direction matches trade side
use_filter_smc_idm_required     # only enter if inducement was swept first
```

### 1c. SMC SL/TP Modifier flags (4) — new group `SMC_PLACEMENT_GENES`

```
sl_anchor_smc_ob        # SL just past the OB price reacted from
sl_anchor_smc_swing     # SL just past last swing low/high (not ATR-based)
tp_target_smc_liq       # near_tp = opposite liquidity pool
tp_target_smc_ob        # far_tp = next opposite-side OB
```

### 1d. SMC Tunable continuous params (3) — in `CONT_PARAMS`

```python
"smc_ob_buffer_atr":      (0.1, 1.5),    # SL buffer past OB in × ATR
"smc_ob_freshness_bars":  (3,   80),     # max bar age for "fresh" OB
"smc_htf_lookback_bars":  (10,  100),    # how far back to scan HTF BOS
```

### 1e. Coherence repairs

Add to `Genome.random / crossover / mutate`:

```python
# SL anchor only makes sense if matching signal is on.
if flags.get("sl_anchor_smc_ob") and not flags.get("use_sig_smc_ob"):
    flags["use_sig_smc_ob"] = True
if flags.get("tp_target_smc_ob") and not flags.get("use_sig_smc_ob"):
    flags["use_sig_smc_ob"] = True
```

### 1f. SMC-leaning random seed

`Genome.random(gen=0, smc_lean: float = 0.0)` — when ≠0, SMC flags get
probability `0.10 + smc_lean * 0.3`. Used by `continuous_evolution` to seed
the SMC lane (§5).

---

## 2. SMC Signal Evaluators (`genome_signal.py`)

### 2a. Snapshot SMC schema (per TF)

```python
snap["h1"]["smc"] = {
    "fresh_ob_above": {              # nearest bearish OB above price
        "top": float, "bottom": float,
        "created_at": int_epoch, "age_bars": int,
        "strength": float,           # 0..1 — depth × volume × test count
        "tested_count": int,         # 0 = fresh
    } | None,
    "fresh_ob_below": {...} | None,  # bullish OB below price

    "fresh_fvg_bull": [
        {"top": float, "bottom": float, "age_bars": int, "filled_pct": float},
        ...
    ],
    "fresh_fvg_bear": [...],

    "last_bos": {
        "direction": "UP" | "DOWN",
        "level": float, "age_bars": int, "confirmed": bool,
    } | None,
    "last_choch": {
        "direction": "UP" | "DOWN",
        "level": float, "age_bars": int,
    } | None,

    "recent_liq_sweep": {
        "side": "BUY" | "SELL",      # which side got swept
        "level": float, "age_bars": int, "reclaim": bool,
    } | None,
    "liq_above": [float, ...],       # equal-high clusters, price-sorted
    "liq_below": [float, ...],

    "idm_status": {
        "swept": bool, "side": "UP" | "DOWN",
        "level": float, "age_bars": int,
    } | None,
}
```

Same shape on `m15` and `h4`. Old snapshots without `smc` are tolerated —
evaluators return `(0, "no smc data")`.

### 2b. Evaluator implementations

```python
def _sig_smc_ob(snap):
    """+1 BUY when bid in fresh bullish OB; -1 SELL in fresh bearish OB."""
    h1 = _h1(snap); bid = _bid(snap)
    smc = h1.get("smc") or {}
    ob_b = smc.get("fresh_ob_below")
    ob_a = smc.get("fresh_ob_above")
    if ob_b and ob_b["bottom"] <= bid <= ob_b["top"]:
        return +1, f"in bullish OB str={ob_b['strength']:.2f}"
    if ob_a and ob_a["bottom"] <= bid <= ob_a["top"]:
        return -1, f"in bearish OB str={ob_a['strength']:.2f}"
    return 0, "no OB touch"

def _sig_smc_fvg(snap):
    h1 = _h1(snap); bid = _bid(snap)
    for fvg in (h1.get("smc") or {}).get("fresh_fvg_bull", []):
        if fvg["bottom"] <= bid <= fvg["top"] and fvg["filled_pct"] < 0.5:
            return +1, f"in bull FVG"
    for fvg in (h1.get("smc") or {}).get("fresh_fvg_bear", []):
        if fvg["bottom"] <= bid <= fvg["top"] and fvg["filled_pct"] < 0.5:
            return -1, f"in bear FVG"
    return 0, "no FVG fill"

def _sig_smc_bos(snap):
    bos = (_h1(snap).get("smc") or {}).get("last_bos")
    if not bos or not bos.get("confirmed"): return 0, "no confirmed BOS"
    if bos["age_bars"] > 40: return 0, f"BOS stale ({bos['age_bars']}b)"
    return (+1 if bos["direction"] == "UP" else -1), f"BOS {bos['direction']}"

def _sig_smc_choch(snap):
    ch = (_h1(snap).get("smc") or {}).get("last_choch")
    if not ch or ch["age_bars"] > 15: return 0, "no recent CHoCH"
    return (+1 if ch["direction"] == "UP" else -1), f"CHoCH {ch['direction']}"

def _sig_smc_liq_sweep(snap):
    sw = (_h1(snap).get("smc") or {}).get("recent_liq_sweep")
    if not sw or sw["age_bars"] > 5 or not sw.get("reclaim"):
        return 0, "no sweep"
    # Sweep above stops + reclaim → SELL (bull trap), mirror for SELL sweep.
    return (-1 if sw["side"] == "BUY" else +1), f"sweep {sw['side']} reclaim"

def _sig_smc_idm(snap):
    idm = (_h1(snap).get("smc") or {}).get("idm_status")
    if not idm or not idm.get("swept"): return 0, "no idm swept"
    if idm["age_bars"] > 20: return 0, "idm stale"
    return (+1 if idm["side"] == "UP" else -1), f"IDM {idm['side']} swept"
```

### 2c. SMC Filters

```python
def _filt_smc_fresh_only(snap):
    smc = (_h1(snap).get("smc") or {})
    ob = smc.get("fresh_ob_below") or smc.get("fresh_ob_above")
    if ob and ob.get("tested_count", 0) > 0:
        return True, f"OB tested {ob['tested_count']}× already"
    return False, "fresh"

def _filt_smc_htf_alignment(snap):
    h1_bos = (_h1(snap).get("smc") or {}).get("last_bos")
    h4_bos = (_h4(snap).get("smc") or {}).get("last_bos")
    if h1_bos and h4_bos and h1_bos["direction"] != h4_bos["direction"]:
        return True, f"h1={h1_bos['direction']} vs h4={h4_bos['direction']}"
    return False, "htf aligned"

def _filt_smc_idm_required(snap):
    idm = (_h1(snap).get("smc") or {}).get("idm_status")
    if not idm or not idm.get("swept"):
        return True, "idm not swept yet"
    return False, "idm swept"
```

Register in `SIGNAL_EVALUATORS` and `FILTER_EVALUATORS` dicts.
`decide_entry` needs no changes — it iterates over the dict.

---

## 3. SMC-Aware SL/TP Resolver (`sl_tp_resolver.py` — NEW)

Pure function called from `trade_gate.evaluate_gate` right after direction is set.

```python
def resolve_sl_tp(
    genome: dict, side: str, entry: float,
    snap: dict, h1_atr: float,
    fallback: callable | None = None,
) -> dict:
    """
    Returns {
      ok: bool, sl: float, near_tp: float, far_tp: float,
      sl_anchor:  "smc_ob" | "smc_swing" | "smc_fvg" | "atr",
      tp_anchor:  "smc_liq" | "smc_ob" | "atr",
      anchor_levels: {ob_used, swing_used, liq_used},
      reasoning: [str, ...],
    }
    """
```

### SL priority (first matching flag wins)

```
sl_anchor_smc_ob     → SL = ob_bottom - buffer (BUY) / ob_top + buffer (SELL)
                       buffer = genome.params["smc_ob_buffer_atr"] * h1_atr
sl_anchor_smc_swing  → SL = last swing_low - buffer (BUY) / swing_high + buffer (SELL)
no SMC SL flag       → fallback(genome, side, entry, h1_atr)  [legacy ATR math]
```

If chosen SMC anchor exceeds `max_sl_price_dist`, returns `ok=False` and caller
falls back to ATR — same pattern as `r_levels.propose_trade_levels` today.

### TP priority

```
tp_target_smc_liq    → near_tp = nearest level in liq_above/below
                       far_tp  = 2nd nearest (or RR×2 fallback)
tp_target_smc_ob     → far_tp  = opposite OB centre
                       near_tp = entry + sl_dist × 1.5
neither              → fallback RR math
```

### Integration in `trade_gate.py`

Replace lines `742-820` (the `tpl_sl_dist/tp_dist/use_levels` block) with a call
to `resolve_sl_tp(...)`. Forward returned `anchor_levels` into `TradeVerdict`
via a new `smc_anchors: dict` field — Phase 1's chart drawer reads it without
further plumbing.

### Simulator integration

`ga_simulator.simulate_genome` calls `smc_engine.compute_offline(bars)` to build
a per-bar `smc` dict, then calls `resolve_sl_tp` per simulated trade. This way
the GA actually selects for SMC-anchored placement.

---

## 4. Combo Fitness Extension (`combo_fitness.py`)

### 4a. New per-bucket sub-dicts

```python
{
    ...existing keys...,
    "smc_combos": {},          # "ob+idm_swept+htf_align" → {wins, fails, ...}
    "smc_contexts": {
        "bos_aligned":        {"wins": 0, "fails": 0, "avg_return": 0.0},
        "bos_counter":        {...},
        "in_fresh_ob":        {...},
        "in_mitigated_ob":    {...},
        "idm_swept_before":   {...},
        "no_idm_sweep":       {...},
        "tp_hit_liquidity":   {...},
        "tp_hit_atr_target":  {...},
    },
}
```

### 4b. Per-trade SMC context object

```python
SMCContext = {
    "bos_dir":                "UP" | "DOWN" | None,
    "trade_aligned_with_bos": bool,
    "entry_in_ob":            "fresh" | "mitigated" | None,
    "entry_in_fvg":           "fresh" | "mitigated" | None,
    "idm_swept":              bool,
    "htf_aligned":            bool,
    "exit_via": "liquidity_pool" | "opposite_ob" | "atr_tp" | "sl" | "trail",
}
```

Simulator records this per trade; live executor records on fill + close.

### 4c. Ingestion path

```python
def record_smc_trade(symbol, tf, active_genes, smc_context, stats, db=None):
    """Called from ga_simulator AND r_executor on position close."""
    bucket = _bucket(db, symbol, tf)
    won = _is_winner(stats)
    smc_active = [g for g in active_genes if "smc" in g]
    if smc_active:
        _bump_combo(bucket["smc_combos"], combo_key(smc_active), stats, won)
    for ctx_key in _smc_ctx_keys(smc_context):
        _bump_combo(bucket["smc_contexts"], ctx_key, stats, won)
    save(db)
```

### 4d. Query API

```python
def smc_lookup(symbol, tf, active_genes, ctx) -> dict:
    """Win-rate of this gene+context combo. Used by genome_breeder
    to weight crossover parents and surface 'OB only works after IDM-sweep'
    insights."""
```

The system learns "raw OB" vs "OB after IDM-sweep" by partitioning the **same
flag-set's trades** across `idm_swept_before` vs `no_idm_sweep` contexts.

---

## 5. Lineage Breeding Bias (`hall_of_fame.py` + `continuous_evolution.py`)

### 5a. Lane classification

```python
def _classify_lane(active_genes: list) -> str:
    return "smc" if any("smc" in g for g in active_genes) else "classic"
```

`admit()` writes `entry["lane"] = _classify_lane(active_genes)`.

```python
def get_elites_by_lane(symbol, lane, n=10) -> list[dict]:
    return [e for e in get_elites(symbol, n=n*3) if e.get("lane") == lane][:n]
```

### 5b. PG seeding split in `_load_elite_seeds`

```python
def _load_elite_seeds(self, symbol, n=30):
    smc_n     = max(5, n // 2)
    classic_n = n - smc_n
    smc_seeds     = get_elites_by_lane(symbol, "smc",     smc_n)
    classic_seeds = get_elites_by_lane(symbol, "classic", classic_n)
    while len(smc_seeds) < smc_n:
        smc_seeds.append({"all_params": Genome.random(smc_lean=0.7).to_dict()})
    return [Genome.from_dict(e["all_params"]) for e in smc_seeds + classic_seeds]
```

Guarantees SMC genomes get **half the elite-carry slots** even before they
outscore classic ones — solves cold-start crowding.

### 5c. Group-intensity mutation

```python
def smc_mutation_intensity(symbol, base=0.10) -> float:
    """First 100 trades → 3× SMC bit-flip rate."""
    n = _trade_count_for(symbol)
    return base * 3.0 if n < 100 else base

def mutate(self, intensity=0.10, gen=0, group_intensities=None):
    """group_intensities maps gene-prefix → rate override.
    e.g. {'use_sig_smc_': 0.30, 'use_filter_smc_': 0.25}"""
```

### 5d. Lane-aware deploy threshold

```python
cur_classic = max(get_elites_by_lane(sym, "classic", 1) or [{"score": 0}], key=lambda e: e["score"])
cur_smc     = max(get_elites_by_lane(sym, "smc",     1) or [{"score": 0}], key=lambda e: e["score"])
new_lane = _classify_lane(top["active_genes"])
lane_threshold = cur_smc["score"] if new_lane == "smc" else cur_classic["score"]
if new_score < lane_threshold + threshold:
    return {"deployed": False, "reason": f"not best-in-{new_lane}-lane"}
```

An SMC genome doesn't have to beat the all-time classic king to get a live
test slot — only its own lane.

---

## 6. Brain Server Snapshot Extension (`brain_server.py` + `smc_engine.py` NEW)

### 6a. `smc_engine.py` API

```python
def compute_smc_snapshot(symbol: str, tf_name: str, bars_back: int = 200) -> dict:
    """Live path — reads MT5 bars directly."""

def compute_offline(bars) -> dict:
    """Worker path — accepts pre-fetched bars (ga_simulator)."""
```

Both return the §2a SMC dict shape; all keys present, values None/[] when empty.

### 6b. Wire into `_quick_tf_snapshot`

```python
def _quick_tf_snapshot(symbol, tf, n):
    out = {...existing...}
    try:
        from r_native.smc_engine import compute_smc_snapshot
        out["smc"] = compute_smc_snapshot(symbol, _TF_NAME[tf], bars_back=200)
    except Exception:
        out["smc"] = {}    # tolerant
    return out
```

### 6c. Cache layer

Bar-aligned cache key `(symbol, tf, last_bar_epoch)` — invalidated by bar close.
Avoids recomputing OB/FVG every HTTP poll.

---

## Phased Implementation Order

### **PR-2** — Genome DNA + signal layer (independent of Phase 1)
`genes.py`, `genome_signal.py`, `combo_fitness.py`. Additive only. Old genomes
unchanged; new flags default off. Evaluators safely return 0 when `smc` is
missing.

### **PR-3** — SL/TP resolver + simulator
`sl_tp_resolver.py` (NEW), `friday_v3/algory/trade_gate.py`, `ga_simulator.py`.
Requires `smc_engine.compute_offline` from Phase 1.

### **PR-4** — Brain server snapshot wiring
`brain_server.py`, `smc_engine.py` live path. `/api/r/trade_gate` automatically
picks up SMC data.

### **PR-5** — Lineage / breeding bias
`hall_of_fame.py`, `genetic_engine.py`, `continuous_evolution.py`,
`genes.py` (mutate signature). Activate after PR-2/3 produce SMC vault entries.

### **PR-6** — Per-trade SMC context recorder
`friday_v3/algory/r_executor.py` (record on close), `ga_simulator.py`.
Snapshot SMC context at fill, persist, call `combo_fitness.record_smc_trade`.

---

### Critical Files for Implementation

- `/home/user/r-native/genes.py`
- `/home/user/r-native/genome_signal.py`
- `/home/user/r-native/sl_tp_resolver.py` (new)
- `/home/user/r-native/combo_fitness.py`
- `/home/user/r-native/hall_of_fame.py`
- `/home/user/r-native/brain_server.py`
- `/home/user/r-native/smc_engine.py` (new — shared with Phase 1)
- `/home/user/r-native/friday_v3/algory/trade_gate.py`

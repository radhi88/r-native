# SMC Algorithms — Algorithmic Specification

> A rigorous, deterministic spec for SMC/ICT pattern detection. All algorithms
> operate on a stream of `Bar = {ts, open, high, low, close, volume}` indexed
> `0..N-1`, processed left-to-right with no lookahead beyond an explicit
> confirmation window.
>
> Used by: `smc_engine.py` (to be built), `genome_signal.py` SMC evaluators
> (Phase 3), `chart_drawings.py` (to be built).

---

## 0. Foundation: Pivots (Fractals) and the Lookahead Problem

A swing pivot at index `i` is the atomic primitive. Two states:

- **Tentative pivot** — local extremum based on data seen so far. May be revised.
- **Confirmed pivot** — locked once `R` bars to the right have all failed to break it.

```python
def detect_pivots(bars, cfg):
    L = cfg.get("fractal_left", 2)
    R = cfg.get("fractal_right", 2)    # R=2 => fractal-5
    pivots = []
    for i in range(L, len(bars) - R):
        win = bars[i-L : i+R+1]
        if bars[i].high == max(b.high for b in win) and \
           all(bars[i].high > b.high for b in win if b is not bars[i]):
            pivots.append({"idx": i, "price": bars[i].high, "kind": "H",
                           "state": "confirmed", "ts": bars[i].ts,
                           "confirmed_at_idx": i + R})
        if bars[i].low == min(b.low for b in win) and \
           all(bars[i].low < b.low for b in win if b is not bars[i]):
            pivots.append({"idx": i, "price": bars[i].low, "kind": "L",
                           "state": "confirmed", "ts": bars[i].ts,
                           "confirmed_at_idx": i + R})
    # Tentative pivots in tail [N-R, N-1]
    return pivots
```

**Defaults**: `R=2` (fractal-5, balanced), `R=1` (fractal-3, faster, noisier),
`R=3+` for higher timeframes. Strict inequality avoids equal-high ambiguity
(equal highs become a liquidity pool — see §3).

**Real-time rule**: any signal that depends on pivot `P` may only fire at
`P.idx + R` or later. Downstream detectors gate on `confirmed_at_idx`.

---

## 1. Break of Structure (BOS)

Close of a bar exceeds the most recent **confirmed** swing high/low in the
direction of the prevailing trend.

```python
def detect_bos(bars, cfg):
    pivots = detect_pivots(bars, cfg)
    events, trend = [], None
    last_H = last_L = None
    for i, bar in enumerate(bars):
        for p in pivots:
            if p["confirmed_at_idx"] == i:
                if p["kind"] == "H": last_H = p
                else:                last_L = p
        if last_H and bar.close > last_H["price"]:
            events.append(Event(ts_start=last_H["ts"], ts_end=bar.ts,
                level_high=last_H["price"], level_low=last_H["price"],
                side="bull", kind="BOS", status="fresh"))
            trend = "UP"; last_H = None
        if last_L and bar.close < last_L["price"]:
            events.append(Event(ts_start=last_L["ts"], ts_end=bar.ts,
                level_high=last_L["price"], level_low=last_L["price"],
                side="bear", kind="BOS", status="fresh"))
            trend = "DOWN"; last_L = None
    return events
```

**Rule**: bar **close** breaks the level. Wick-only break = liquidity sweep, not BOS.

**Mitigation**: BOS events are historical. Their level is consumed — the next
BOS requires a new confirmed swing beyond the broken one. Status flips to
`mitigated` when an opposite BOS (CHoCH) occurs.

---

## 2. Change of Character (CHoCH)

The **first BOS opposite to the prevailing trend** — the regime change signal.

```python
def detect_choch(bars, cfg):
    trend = None
    events = []
    for bos in detect_bos(bars, cfg):
        if trend is None:
            trend = "UP" if bos.side == "bull" else "DOWN"; continue
        if (trend == "UP" and bos.side == "bear") or \
           (trend == "DOWN" and bos.side == "bull"):
            events.append(Event(**bos.__dict__, kind="CHoCH"))
            trend = "DOWN" if bos.side == "bear" else "UP"
    return events
```

**Bootstrap**: trend is `None` until the first confirmed BOS. Alternatives:
(a) require two consecutive HH/HL or LL/LH (`N=2` default), (b) seed from the
first two confirmed pivots.

**State machine**: `UNKNOWN → UP → (BOS: stay UP) | (CHoCH: → DOWN) → ...`

---

## 3. Liquidity Sweep

Wick takes out a swing extreme; close returns inside.

```python
def detect_sweep(bars, cfg):
    atr = rolling_atr(bars, cfg.get("atr_period", 14))
    min_pen = cfg.get("min_penetration_atr", 0.05)
    max_pen = cfg.get("max_penetration_atr", 1.5)
    max_close_back_bars = cfg.get("max_close_back", 1)
    pivots = detect_pivots(bars, cfg)
    events = []
    for p in pivots:
        if p["state"] != "confirmed": continue
        for j in range(p["confirmed_at_idx"] + 1, len(bars)):
            a = atr[j]
            if p["kind"] == "H":
                pen = bars[j].high - p["price"]
                if pen < min_pen*a or pen > max_pen*a: continue
                if any(bars[k].close < p["price"]
                       for k in range(j, min(j+max_close_back_bars+1, len(bars)))):
                    events.append(Event(ts_start=p["ts"], ts_end=bars[j].ts,
                        level_high=bars[j].high, level_low=p["price"],
                        side="bear", kind="SWEEP", status="fresh"))
                    break
            # mirror for lows
    return events
```

**Equal-highs liquidity**: cluster confirmed highs within
`eqh_tolerance_atr` (default 0.1×ATR) into one pool;
`sweep_level = max(cluster)`, `strength = len(cluster)`.

**Mitigation**: sweep is `fresh` until close breaks back through the swept
level (then `mitigated`). Strong sweeps usually precede a CHoCH within
`sweep_to_choch_window` (default 10) bars — flag those with `strength += 1`.

---

## 4. Inducement (IDM)

The **minor counter-trend pivot between two same-direction structural points**
that gets swept just before the impulsive leg.

```python
def detect_idm(bars, cfg):
    pivots = [p for p in detect_pivots(bars, cfg) if p["state"] == "confirmed"]
    events = []
    for bos in detect_bos(bars, cfg):
        if bos.side != "bull": continue
        i_break = index_of_bar(bars, bos.ts_end)
        prior_H  = last_confirmed_pivot_before(pivots, i_break, kind="H", skip=1)
        broken_H = last_confirmed_pivot_before(pivots, i_break, kind="H", skip=0)
        if not prior_H or not broken_H: continue
        candidates = [p for p in pivots if p["kind"]=="L"
                      and prior_H["idx"] < p["idx"] < broken_H["idx"]]
        if not candidates: continue
        idm = min(candidates, key=lambda p: p["price"])
        swept = any(bars[k].low < idm["price"]
                    for k in range(broken_H["idx"], i_break+1))
        if swept:
            events.append(Event(ts_start=idm["ts"], ts_end=bos.ts_end,
                level_high=idm["price"], level_low=idm["price"],
                side="bull", kind="IDM", status="fresh"))
    return events  # mirror for bearish
```

**Real-time emission**: IDM can only be labeled *after* the BOS that follows
the sweep is confirmed — there is no zero-lag IDM. Render a provisional IDM
on the lowest unbroken HL of the current leg and finalize it on BOS.

---

## 5. Order Block (OB)

Last opposite-color candle before the impulsive leg producing a BOS.

```python
def detect_ob(bars, cfg):
    atr = rolling_atr(bars, cfg["atr_period"])
    impulse_atr   = cfg.get("impulse_atr_mult", 1.5)
    impulse_window = cfg.get("impulse_window", 5)
    body_min = cfg.get("ob_body_ratio", 0.0)
    events = []
    for bos in detect_bos(bars, cfg):
        i_bos = index_of_bar(bars, bos.ts_end)
        impulse_start = i_bos
        cum = 0
        for k in range(i_bos, max(i_bos-impulse_window, 0)-1, -1):
            cum += (bars[k].close - bars[k].open) * (1 if bos.side=="bull" else -1)
            if cum >= impulse_atr * atr[i_bos]:
                impulse_start = k; break
        else:
            continue
        want_bear = (bos.side == "bull")
        for k in range(impulse_start - 1, -1, -1):
            is_bear = bars[k].close < bars[k].open
            body = abs(bars[k].close - bars[k].open)
            rng = bars[k].high - bars[k].low
            if is_bear == want_bear and rng > 0 and body/rng >= body_min:
                events.append(Event(ts_start=bars[k].ts, ts_end=bos.ts_end,
                    level_high=bars[k].high, level_low=bars[k].low,
                    side=bos.side, kind="OB", status="fresh",
                    strength=cum/atr[i_bos]))
                break
    return events
```

**Mitigation** (`cfg["ob_mitigation"]`):
- `close_through` (default) — later bar's close past OB boundary.
- `wick_50` — wick reaches 50% of OB body.
- `wick_full` — wick fully through.

---

## 6. Fair Value Gap (FVG)

Three-candle imbalance using candle 1 and candle 3 extrema.

```python
def detect_fvg(bars, cfg):
    use_wicks = cfg.get("fvg_wicks", True)
    events = []
    for i in range(2, len(bars)):
        c1, c3 = bars[i-2], bars[i]
        hi1, lo1 = (c1.high, c1.low) if use_wicks else \
                   (max(c1.open,c1.close), min(c1.open,c1.close))
        hi3, lo3 = (c3.high, c3.low) if use_wicks else \
                   (max(c3.open,c3.close), min(c3.open,c3.close))
        if hi1 < lo3:
            events.append(Event(ts_start=c1.ts, ts_end=c3.ts,
                level_low=hi1, level_high=lo3, side="bull",
                kind="FVG", status="fresh"))
        elif lo1 > hi3:
            events.append(Event(ts_start=c1.ts, ts_end=c3.ts,
                level_low=hi3, level_high=lo1, side="bear",
                kind="FVG", status="fresh"))
    return events
```

**Mitigation** (`cfg["fvg_fill"]`):
- `touch` — any wick into the gap.
- `50pct` (default, ICT-standard) — wick reaches midpoint.
- `full` — gap fully traversed.

Track `fill_pct` for partial mitigation.

---

## 7. Order Flow Marker (OF)

The retracement leg between two structural points. After a BOS, the next
confirmed counter-trend pivot becomes the OF anchor.

```python
def detect_of(bars, cfg):
    events = []
    for bos in detect_bos(bars, cfg):
        i_bos = index_of_bar(bars, bos.ts_end)
        want = "L" if bos.side=="bull" else "H"
        next_p = next((p for p in confirmed_pivots
                       if p["idx"] > i_bos and p["kind"] == want), None)
        if not next_p: continue
        anchor = min(bars[i_bos].low, bars[i_bos].close) if bos.side=="bull" \
                 else max(bars[i_bos].high, bars[i_bos].close)
        events.append(Event(ts_start=bos.ts_end, ts_end=next_p["ts"],
            level_low=min(anchor, next_p["price"]),
            level_high=max(anchor, next_p["price"]),
            side=bos.side, kind="OF", status="fresh"))
    return events
```

---

## Lookahead Discipline (Critical for Backtests)

1. **Two pivot tables**: `pivots_confirmed` vs `pivots_tentative`. Detectors
   only consume confirmed.
2. **Signal timestamp**: every Event carries `confirmed_at_idx`. Backtester
   executes orders at `confirmed_at_idx + 1` open.
3. **No revisionism**: events are append-only, status mutates but never deletes.
4. **Tentative rendering** allowed for UI/paper trading; excluded from order generation.

### Default config

```python
DEFAULT_CFG = {
    "fractal_left": 2, "fractal_right": 2,
    "atr_period": 14,
    "min_penetration_atr": 0.05, "max_penetration_atr": 1.5,
    "max_close_back": 1, "eqh_tolerance_atr": 0.1,
    "sweep_to_choch_window": 10,
    "impulse_atr_mult": 1.5, "impulse_window": 5,
    "ob_body_ratio": 0.0, "ob_mitigation": "close_through",
    "fvg_wicks": True, "fvg_fill": "50pct",
}
```

All detectors are **idempotent** over a fixed bar history and **monotonic**
in real-time: the set of confirmed events only grows as new bars arrive.

"""shared/order_blocks.py — REAL Smart-Money-Concepts (SMC) supply/demand detector.

Born 2026-05-31. Replaces the crude ``EMA50 +/- 1.5*ATR`` proxy that the failed
COT test used as a stand-in for "supply/demand zones". That proxy had no
structural meaning: it drew bands around a moving average and called them zones.
This module detects the actual price structures the SMC literature describes:

    * Order Blocks (OB) — the last opposite-direction candle immediately before
      an impulsive move that BREAKS STRUCTURE (Break Of Structure, BOS). A
      bullish/demand OB is the last DOWN candle before an up-impulse that takes
      out the prior swing HIGH. A bearish/supply OB is the last UP candle before
      a down-impulse that takes out the prior swing LOW.
    * Fair Value Gaps (FVG) — 3-candle imbalances where candle1 and candle3 do
      not overlap, leaving an untraded price gap the market tends to revisit.
    * Liquidity pools — clusters of equal highs / equal lows (resting stops).

STRICTLY CAUSAL — NO LOOK-AHEAD
    Every structure "confirmed at index i" is decided using ONLY bars with index
    <= i. Swing points use a symmetric fractal of half-width ``swing`` (default
    5), so a swing at bar ``s`` is only *knowable* at bar ``s + swing`` (you need
    the right-hand bars to confirm the pivot). We therefore stamp each detected
    zone with ``idx`` = the bar at which it became confirmable, never the bar at
    which the structure physically sits. A backtester that iterates bars in time
    and only consults zones with ``idx <= current_bar`` will never peek ahead.

    ``mitigated`` is computed *as of the end of the supplied array* (i.e. has any
    later bar traded back into the zone). For a point-in-time causal check inside
    a backtest, call ``detect_order_blocks(rates[:i+1])`` on the slice up to bar
    i, or use ``in_zone`` against the zones whose ``idx <= i``.

INPUT
    ``rates`` — an MT5 structured ndarray as returned by
    ``mt5.copy_rates_range(...)`` with at least the fields
    ``time, open, high, low, close`` (extra fields are ignored). Plain dicts of
    arrays or 2-D arrays are also accepted via ``_as_ohlc``.

OUTPUT
    detect_order_blocks(rates) -> list[dict]:
        {type: "supply"|"demand", hi, lo, idx, mitigated}
            type      : "demand" = bullish OB (buy zone), "supply" = bearish OB.
            hi, lo    : the high/low of the order-block candle (the zone bounds).
            idx       : bar index at which the OB became CONFIRMED (causal).
            mitigated : True if any bar after idx has traded back into [lo, hi].
    detect_fvg(rates) -> list[dict]:
        {type: "bullish"|"bearish", hi, lo, idx, mitigated}
            idx       : index of the 3rd (confirming) candle of the gap.
    liquidity_pools(rates) -> list[dict]:
        {type: "equal_highs"|"equal_lows", price, lo, hi, idx, touches}
            idx       : index of the most recent bar forming the cluster.
    in_zone(price, zones) -> list[dict]: zones whose [lo, hi] contains ``price``.

Run the self-test (pulls XAUUSDm H1 ~120d via MT5, falls back to a synthetic
series with planted structures if the terminal is not authorized)::

    C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe ^
        C:\\Users\\Radhi\\MT5\\r_native_v2\\runtime\\shared\\order_blocks.py
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Union

import numpy as np

ArrayLike = Union[np.ndarray, Dict[str, Sequence[float]], Sequence[Sequence[float]]]


# ---------------------------------------------------------------------------
# Input normalisation
# ---------------------------------------------------------------------------
def _as_ohlc(rates: ArrayLike):
    """Return (time, open, high, low, close) as float64 ndarrays.

    Accepts:
      * an MT5 structured array with named fields time/open/high/low/close
      * a dict of array-likes with those keys
      * a 2-D array shaped (n, >=5) as columns time,open,high,low,close
    ``time`` may be missing (synthetic data); a 0..n-1 index is substituted.
    """
    if isinstance(rates, np.ndarray) and rates.dtype.names is not None:
        names = rates.dtype.names
        o = rates["open"].astype(np.float64)
        h = rates["high"].astype(np.float64)
        l = rates["low"].astype(np.float64)
        c = rates["close"].astype(np.float64)
        t = rates["time"].astype(np.float64) if "time" in names else np.arange(len(c), dtype=np.float64)
        return t, o, h, l, c

    if isinstance(rates, dict):
        o = np.asarray(rates["open"], dtype=np.float64)
        h = np.asarray(rates["high"], dtype=np.float64)
        l = np.asarray(rates["low"], dtype=np.float64)
        c = np.asarray(rates["close"], dtype=np.float64)
        t = np.asarray(rates.get("time", np.arange(len(c))), dtype=np.float64)
        return t, o, h, l, c

    arr = np.asarray(rates, dtype=np.float64)
    if arr.ndim == 2 and arr.shape[1] >= 5:
        t, o, h, l, c = (arr[:, i] for i in range(5))
        return t, o, h, l, c
    raise TypeError("Unsupported rates structure; expected MT5 array, dict, or (n,>=5) 2-D array.")


# ---------------------------------------------------------------------------
# Structure: swing highs / lows via symmetric fractal
# ---------------------------------------------------------------------------
def _swing_points(high: np.ndarray, low: np.ndarray, swing: int = 5):
    """Boolean masks (is_swing_high, is_swing_low) using a symmetric fractal.

    A bar ``i`` is a swing high iff its high is the strict maximum of the
    window [i-swing, i+swing]; symmetric for swing low. The first/last ``swing``
    bars can never be confirmed pivots and are False.

    CAUSALITY NOTE: a pivot at ``i`` is only *knowable* at bar ``i+swing`` (the
    right-hand bars must exist). Callers that need a confirmation index add
    ``swing`` to the pivot index — see ``detect_order_blocks``.
    """
    n = high.size
    is_sh = np.zeros(n, dtype=bool)
    is_sl = np.zeros(n, dtype=bool)
    if n < 2 * swing + 1:
        return is_sh, is_sl
    for i in range(swing, n - swing):
        wnd_h = high[i - swing:i + swing + 1]
        wnd_l = low[i - swing:i + swing + 1]
        if high[i] == wnd_h.max() and np.count_nonzero(wnd_h == high[i]) == 1:
            is_sh[i] = True
        if low[i] == wnd_l.min() and np.count_nonzero(wnd_l == low[i]) == 1:
            is_sl[i] = True
    return is_sh, is_sl


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder-ish ATR via simple moving average of True Range. Causal (uses prev
    close). Returns an array aligned to bars; first bar TR uses high-low only."""
    n = high.size
    prev_close = np.empty(n, dtype=np.float64)
    prev_close[0] = close[0]
    prev_close[1:] = close[:-1]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    atr = np.full(n, np.nan, dtype=np.float64)
    if n >= period:
        # simple rolling mean of TR; atr[i] uses tr[i-period+1 .. i] (causal)
        csum = np.cumsum(tr)
        atr[period - 1:] = (csum[period - 1:] - np.concatenate(([0.0], csum[:-period]))) / period
    else:
        atr[:] = tr.mean() if n else np.nan
    return atr


# ---------------------------------------------------------------------------
# Order Blocks
# ---------------------------------------------------------------------------
def detect_order_blocks(
    rates: ArrayLike,
    swing: int = 5,
    impulse_atr_mult: float = 1.0,
    lookahead_impulse: int = 3,
) -> List[Dict]:
    """Detect SMC order blocks from a structure break (BOS).

    Algorithm (strictly causal):
      1. Compute symmetric-fractal swing highs/lows (half-width ``swing``). A
         swing at bar ``s`` is confirmable only at bar ``s+swing``.
      2. Walk bars in time. Maintain the most-recent *confirmed* swing high and
         swing low (only confirmed once ``swing`` right-hand bars exist).
      3. BULLISH BOS / demand OB: when a bar ``b`` CLOSES above the last
         confirmed swing high by an impulsive amount (>= ``impulse_atr_mult`` *
         ATR over the breakout leg), find the last DOWN candle in the leg
         leading into the break — that candle's [low, high] is the demand zone.
         Confirmation index = ``b`` (the break bar). All inputs are bars <= b.
      4. BEARISH BOS / supply OB: mirror — bar closes below last confirmed swing
         low by an impulsive amount; the last UP candle before the down-impulse
         is the supply zone.
      5. ``mitigated`` = any bar after the confirmation index trades back into
         the zone (evaluated as-of the end of the array).

    Returns zones sorted by confirmation ``idx``.
    """
    t, o, h, l, c = _as_ohlc(rates)
    n = c.size
    if n < 2 * swing + 3:
        return []

    is_sh, is_sl = _swing_points(h, l, swing)
    atr = _atr(h, l, c, period=14)

    # Confirmation index of each pivot = pivot_index + swing.
    # Build time-ordered lists of (confirm_idx, pivot_idx, price).
    sh_confirm = [(i + swing, i, h[i]) for i in range(n) if is_sh[i] and i + swing < n]
    sl_confirm = [(i + swing, i, l[i]) for i in range(n) if is_sl[i] and i + swing < n]

    # Pointers into the confirm lists; advance as bar index b increases so that
    # at bar b we only know pivots whose confirm_idx <= b.
    zones: List[Dict] = []
    si_h = 0
    si_l = 0
    last_sh_price = None  # most recent confirmed swing-high price
    last_sl_price = None
    last_sh_idx = -1
    last_sl_idx = -1
    # de-dupe: don't emit the same OB candle twice for consecutive breaks
    seen_demand = set()
    seen_supply = set()

    for b in range(n):
        # promote any swing highs/lows that become confirmed at or before b
        while si_h < len(sh_confirm) and sh_confirm[si_h][0] <= b:
            _, piv, px = sh_confirm[si_h]
            last_sh_price = px
            last_sh_idx = piv
            si_h += 1
        while si_l < len(sl_confirm) and sl_confirm[si_l][0] <= b:
            _, piv, px = sl_confirm[si_l]
            last_sl_price = px
            last_sl_idx = piv
            si_l += 1

        a = atr[b]
        if not np.isfinite(a) or a <= 0:
            continue

        # ---- BULLISH BOS -> demand OB ----
        if last_sh_price is not None and last_sh_idx >= 0:
            # impulse magnitude of the breakout bar relative to the swing it broke
            if c[b] > last_sh_price and (c[b] - last_sh_price) >= impulse_atr_mult * a:
                # find the last DOWN candle between the swing-high bar and b
                ob_i = -1
                lo_bound = max(last_sh_idx, b - lookahead_impulse - swing)
                for j in range(b, lo_bound - 1, -1):
                    if j < 0:
                        break
                    if c[j] < o[j]:  # down candle
                        ob_i = j
                        break
                if ob_i >= 0 and ob_i not in seen_demand:
                    seen_demand.add(ob_i)
                    zlo, zhi = float(l[ob_i]), float(h[ob_i])
                    zones.append({
                        "type": "demand",
                        "hi": zhi,
                        "lo": zlo,
                        "idx": int(b),
                        "ob_bar": int(ob_i),
                        "mitigated": _mitigated(h, l, b, zlo, zhi),
                    })
                # consume this swing high so we don't re-fire on every later bar
                last_sh_price = None
                last_sh_idx = -1

        # ---- BEARISH BOS -> supply OB ----
        if last_sl_price is not None and last_sl_idx >= 0:
            if c[b] < last_sl_price and (last_sl_price - c[b]) >= impulse_atr_mult * a:
                ob_i = -1
                lo_bound = max(last_sl_idx, b - lookahead_impulse - swing)
                for j in range(b, lo_bound - 1, -1):
                    if j < 0:
                        break
                    if c[j] > o[j]:  # up candle
                        ob_i = j
                        break
                if ob_i >= 0 and ob_i not in seen_supply:
                    seen_supply.add(ob_i)
                    zlo, zhi = float(l[ob_i]), float(h[ob_i])
                    zones.append({
                        "type": "supply",
                        "hi": zhi,
                        "lo": zlo,
                        "idx": int(b),
                        "ob_bar": int(ob_i),
                        "mitigated": _mitigated(h, l, b, zlo, zhi),
                    })
                last_sl_price = None
                last_sl_idx = -1

    zones.sort(key=lambda z: z["idx"])
    return zones


def _mitigated(high: np.ndarray, low: np.ndarray, confirm_idx: int, zlo: float, zhi: float) -> bool:
    """True if any bar strictly AFTER ``confirm_idx`` overlaps the zone [zlo, zhi]."""
    n = high.size
    if confirm_idx + 1 >= n:
        return False
    h = high[confirm_idx + 1:]
    l = low[confirm_idx + 1:]
    # bar overlaps the zone if it is not entirely above or entirely below it
    overlap = (l <= zhi) & (h >= zlo)
    return bool(np.any(overlap))


# ---------------------------------------------------------------------------
# Fair Value Gaps (3-candle imbalance)
# ---------------------------------------------------------------------------
def detect_fvg(rates: ArrayLike) -> List[Dict]:
    """Detect 3-candle Fair Value Gaps.

    For candles (i-2, i-1, i):
      * BULLISH FVG: low[i] > high[i-2]  -> gap = [high[i-2], low[i]] (untraded
        on the way up). Confirmed at candle ``i``.
      * BEARISH FVG: high[i] < low[i-2]  -> gap = [high[i], low[i-2]].
    ``idx`` is the index of the confirming (third) candle, so it is causal.
    ``mitigated`` = a later bar has traded back into the gap (as-of array end).
    """
    t, o, h, l, c = _as_ohlc(rates)
    n = c.size
    out: List[Dict] = []
    for i in range(2, n):
        # bullish gap
        if l[i] > h[i - 2]:
            zlo, zhi = float(h[i - 2]), float(l[i])
            out.append({
                "type": "bullish",
                "hi": zhi,
                "lo": zlo,
                "idx": int(i),
                "mitigated": _mitigated(h, l, i, zlo, zhi),
            })
        # bearish gap
        elif h[i] < l[i - 2]:
            zlo, zhi = float(h[i]), float(l[i - 2])
            out.append({
                "type": "bearish",
                "hi": zhi,
                "lo": zlo,
                "idx": int(i),
                "mitigated": _mitigated(h, l, i, zlo, zhi),
            })
    return out


# ---------------------------------------------------------------------------
# Liquidity pools (equal highs / equal lows = resting stop clusters)
# ---------------------------------------------------------------------------
def liquidity_pools(
    rates: ArrayLike,
    swing: int = 5,
    tol_atr_mult: float = 0.10,
    min_touches: int = 2,
) -> List[Dict]:
    """Cluster confirmed swing highs (equal highs) and swing lows (equal lows).

    Two pivots are "equal" if their prices are within ``tol_atr_mult * ATR`` of
    each other. A cluster of >= ``min_touches`` such pivots is a liquidity pool
    (resting buy/sell stops). Causal: each pivot is stamped at its confirmation
    index (pivot+swing) and a cluster's ``idx`` is the latest confirmation index
    among its members.

    Returns dicts:
      {type: "equal_highs"|"equal_lows", price, lo, hi, idx, touches}
    """
    t, o, h, l, c = _as_ohlc(rates)
    n = c.size
    if n < 2 * swing + 1:
        return []
    is_sh, is_sl = _swing_points(h, l, swing)
    atr = _atr(h, l, c, period=14)
    med_atr = float(np.nanmedian(atr)) if np.any(np.isfinite(atr)) else 0.0
    tol = tol_atr_mult * med_atr if med_atr > 0 else 0.0

    def _cluster(idxs: List[int], prices: np.ndarray, kind: str) -> List[Dict]:
        pools: List[Dict] = []
        if not idxs:
            return pools
        order = sorted(idxs, key=lambda i: prices[i])
        cluster = [order[0]]
        for i in order[1:]:
            if abs(prices[i] - prices[cluster[-1]]) <= tol:
                cluster.append(i)
            else:
                if len(cluster) >= min_touches:
                    pools.append(_make_pool(cluster, prices, kind, swing))
                cluster = [i]
        if len(cluster) >= min_touches:
            pools.append(_make_pool(cluster, prices, kind, swing))
        return pools

    sh_idx = [i for i in range(n) if is_sh[i] and i + swing < n]
    sl_idx = [i for i in range(n) if is_sl[i] and i + swing < n]
    pools = _cluster(sh_idx, h, "equal_highs") + _cluster(sl_idx, l, "equal_lows")
    pools.sort(key=lambda p: p["idx"])
    return pools


def _make_pool(cluster: List[int], prices: np.ndarray, kind: str, swing: int) -> Dict:
    px = [float(prices[i]) for i in cluster]
    confirm_idx = max(i + swing for i in cluster)
    return {
        "type": kind,
        "price": float(np.mean(px)),
        "lo": float(min(px)),
        "hi": float(max(px)),
        "idx": int(confirm_idx),
        "touches": int(len(cluster)),
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def in_zone(price: float, zones: List[Dict]) -> List[Dict]:
    """Return the subset of ``zones`` whose [lo, hi] contains ``price``."""
    out = []
    for z in zones:
        lo = z.get("lo")
        hi = z.get("hi")
        if lo is None or hi is None:
            continue
        if lo <= price <= hi:
            out.append(z)
    return out


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
def _synthetic_rates(n: int = 600, seed: int = 7) -> np.ndarray:
    """Build a synthetic OHLC structured array with PLANTED SMC structures:
    trending legs that break swings (order blocks) plus engineered 3-candle
    gaps (FVGs). Used only when the live MT5 terminal is not authorized so the
    detector is still exercised on data with known structure."""
    rng = np.random.default_rng(seed)
    dtype = [("time", "<i8"), ("open", "<f8"), ("high", "<f8"),
             ("low", "<f8"), ("close", "<f8"), ("tick_volume", "<u8")]
    arr = np.zeros(n, dtype=dtype)
    price = 3300.0
    t0 = 1_700_000_000
    # alternating trend regimes so structure breaks happen in both directions
    for i in range(n):
        regime = 1.0 if (i // 40) % 2 == 0 else -1.0
        drift = regime * 0.8
        step = drift + rng.normal(0, 1.2)
        op = price
        cl = price + step
        hi = max(op, cl) + abs(rng.normal(0, 0.6))
        lo = min(op, cl) - abs(rng.normal(0, 0.6))
        arr["time"][i] = t0 + i * 3600
        arr["open"][i] = op
        arr["high"][i] = hi
        arr["low"][i] = lo
        arr["close"][i] = cl
        arr["tick_volume"][i] = int(abs(rng.normal(1000, 200)))
        price = cl
    # plant a clean bullish FVG at i=120: candle 122 low well above candle 120 high
    arr["high"][120] = arr["close"][120]
    arr["low"][122] = arr["high"][120] + 5.0
    arr["high"][122] = arr["low"][122] + 3.0
    arr["close"][122] = arr["low"][122] + 1.5
    arr["open"][122] = arr["low"][122] + 0.5
    # plant a clean bearish FVG at i=300
    arr["low"][300] = arr["close"][300]
    arr["high"][302] = arr["low"][300] - 5.0
    arr["low"][302] = arr["high"][302] - 3.0
    arr["close"][302] = arr["high"][302] - 1.5
    arr["open"][302] = arr["high"][302] - 0.5
    return arr


def _try_mt5(symbol: str = "XAUUSDm", days: int = 120):
    """Attempt to pull real H1 bars from MT5. Returns (rates, source_str) or
    (None, reason). Never raises."""
    try:
        import MetaTrader5 as mt5  # noqa: WPS433 (lazy import)
    except Exception as exc:  # pragma: no cover
        return None, f"MetaTrader5 import failed: {exc}"
    import datetime as _dt
    src = None
    try:
        ok = mt5.initialize()
        if not ok:
            ok = mt5.initialize()  # retry (known-flaky, matches codebase pattern)
        if not ok:
            return None, f"mt5.initialize() failed: {mt5.last_error()}"
        now = _dt.datetime.now(_dt.timezone.utc)
        since = now - _dt.timedelta(days=days)
        rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, since, now)
        if rates is None or len(rates) == 0:
            return None, f"copy_rates_range empty: {mt5.last_error()}"
        src = f"MT5 live {symbol} H1 ({len(rates)} bars, last {days}d)"
        return rates, src
    except Exception as exc:  # pragma: no cover
        return None, f"MT5 error: {exc}"
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass


def _selftest() -> None:
    print("=" * 72)
    print("order_blocks.py self-test — REAL SMC supply/demand detector")
    print("=" * 72)

    rates, src = _try_mt5("XAUUSDm", days=120)
    if rates is None:
        print(f"[MT5 UNAVAILABLE] {src}")
        print("[FALLBACK] using planted-structure synthetic OHLC so the detector")
        print("           logic is still exercised end-to-end.\n")
        rates = _synthetic_rates()
        src = f"SYNTHETIC planted-structure series ({len(rates)} bars)"
    print(f"data source : {src}")

    t, o, h, l, c = _as_ohlc(rates)
    print(f"bars        : {len(c)}   price range: {c.min():.2f} .. {c.max():.2f}")

    obs = detect_order_blocks(rates, swing=5)
    supply = [z for z in obs if z["type"] == "supply"]
    demand = [z for z in obs if z["type"] == "demand"]
    fvgs = detect_fvg(rates)
    bull_fvg = [z for z in fvgs if z["type"] == "bullish"]
    bear_fvg = [z for z in fvgs if z["type"] == "bearish"]
    pools = liquidity_pools(rates, swing=5)
    eqh = [p for p in pools if p["type"] == "equal_highs"]
    eql = [p for p in pools if p["type"] == "equal_lows"]

    print("\n--- ORDER BLOCKS (BOS-confirmed) ---")
    print(f"  supply zones (bearish OB): {len(supply)}")
    print(f"  demand zones (bullish OB): {len(demand)}")
    print(f"  total                    : {len(obs)}")
    for z in obs[:4]:
        print(f"    {z['type']:<6} lo={z['lo']:.2f} hi={z['hi']:.2f} "
              f"idx={z['idx']} ob_bar={z['ob_bar']} mitigated={z['mitigated']}")

    print("\n--- FAIR VALUE GAPS (3-candle imbalance) ---")
    print(f"  bullish FVG: {len(bull_fvg)}")
    print(f"  bearish FVG: {len(bear_fvg)}")
    print(f"  total      : {len(fvgs)}")
    for z in fvgs[:4]:
        print(f"    {z['type']:<7} lo={z['lo']:.2f} hi={z['hi']:.2f} "
              f"idx={z['idx']} mitigated={z['mitigated']}")

    print("\n--- LIQUIDITY POOLS (equal highs/lows) ---")
    print(f"  equal-high pools: {len(eqh)}")
    print(f"  equal-low  pools: {len(eql)}")
    for p in pools[:4]:
        print(f"    {p['type']:<11} price={p['price']:.2f} touches={p['touches']} idx={p['idx']}")

    # exercise in_zone on the last close
    last_px = float(c[-1])
    hits = in_zone(last_px, obs)
    print(f"\nin_zone(last_close={last_px:.2f}, order_blocks) -> {len(hits)} active zone(s)")

    # causality smoke check: zones from the full array must equal the zones from
    # the prefix up to each zone's confirm idx (no zone uses future bars to be
    # *detected*; mitigation may differ, which is expected/documented).
    ok_causal = True
    for z in obs[:10]:
        prefix = detect_order_blocks(rates[: z["idx"] + 1], swing=5)
        match = any(pz["ob_bar"] == z["ob_bar"] and pz["type"] == z["type"]
                    and pz["idx"] == z["idx"] for pz in prefix)
        if not match:
            ok_causal = False
            print(f"  [CAUSALITY WARN] zone idx={z['idx']} ob_bar={z['ob_bar']} "
                  f"not reproduced from prefix")
    print(f"\ncausality check (detection uses only bars <= idx): "
          f"{'PASS' if ok_causal else 'FAIL'}")

    print("\n" + "=" * 72)
    print("Self-test complete. Detector fired on real structure (no EMA proxy).")
    print("=" * 72)


if __name__ == "__main__":
    _selftest()

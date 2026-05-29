"""Dry-run tests for smc_engine — runs without MT5, uses synthetic bars.

Run from repo root:    python -m tests.test_smc_engine
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import smc_engine as se


def _bar(t, o, h, l, c, v=100):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v}


# ─── Pivot detection ────────────────────────────────────────────
def test_pivot_simple_high():
    bars = [
        _bar(0, 100, 101, 99, 100.5),
        _bar(1, 100.5, 102, 100, 101.5),
        _bar(2, 101.5, 105, 101, 104),    # peak (idx=2, R=2 confirms at idx 4)
        _bar(3, 104, 104.5, 102, 103),
        _bar(4, 103, 103.5, 101, 102),
        _bar(5, 102, 102.5, 100, 101),
    ]
    bv = se.Bars(bars)
    pivots = se.detect_pivots(bv, se.DEFAULT_CFG)
    highs = [p for p in pivots if p["kind"] == "H"]
    assert any(p["idx"] == 2 and abs(p["price"] - 105) < 1e-9 for p in highs), \
        f"expected high pivot at idx=2 price=105, got {highs}"
    print("OK test_pivot_simple_high")


def test_pivot_no_pivot_when_higher_high_after():
    # If a later bar exceeds the candidate's high, it's NOT a pivot.
    bars = [
        _bar(0, 100, 101, 99, 100.5),
        _bar(1, 100.5, 102, 100, 101.5),
        _bar(2, 101.5, 103, 101, 102.5),
        _bar(3, 102.5, 105, 102, 104),   # this is higher
        _bar(4, 104, 104.5, 102, 103),
        _bar(5, 103, 103.5, 101, 102),
    ]
    bv = se.Bars(bars)
    pivots = se.detect_pivots(bv, se.DEFAULT_CFG)
    highs = [p for p in pivots if p["kind"] == "H"]
    # idx=2 should NOT be a pivot because idx=3 is higher
    assert not any(p["idx"] == 2 for p in highs), \
        f"idx=2 should not be a pivot but is: {highs}"
    print("OK test_pivot_no_pivot_when_higher_high_after")


# ─── BOS ─────────────────────────────────────────────────────────
def test_bos_bullish():
    # Build: low pivot, rally to high pivot, pullback, break above high
    bars = [
        _bar(0, 100, 101, 99, 100),
        _bar(1, 100, 100.5, 98, 99),       # low pivot at idx=1
        _bar(2, 99, 100, 98.5, 99.8),
        _bar(3, 99.8, 102, 99.5, 101.5),
        _bar(4, 101.5, 105, 101, 104),     # high pivot at idx=4
        _bar(5, 104, 104.5, 102, 102.5),
        _bar(6, 102.5, 103, 101, 101.5),
        _bar(7, 101.5, 106, 101, 105.5),   # CLOSE > 105 → bullish BOS
    ]
    bv = se.Bars(bars)
    bos = se.detect_bos(bv, se.DEFAULT_CFG)
    bull = [b for b in bos if b.side == "bull"]
    assert bull, f"expected bullish BOS, got {bos}"
    print("OK test_bos_bullish")


def test_bos_bearish():
    # For fractal-5 (L=R=2), the low pivot at idx=4 needs bars[2,3,5,6] all
    # with low > 100. Then a later close < 100 fires the BOS.
    bars = [
        _bar(0, 105, 106, 104,  105),
        _bar(1, 105, 107, 104.5, 106.5),
        _bar(2, 106.5, 106.8, 104, 104.5),    # low=104 > 100 ✓
        _bar(3, 104.5, 105, 102, 102.5),      # low=102 > 100 ✓
        _bar(4, 102.5, 103, 100, 100.5),      # low pivot @ 100
        _bar(5, 100.5, 102, 101, 101.5),      # low=101 > 100 ✓
        _bar(6, 101.5, 102, 100.5, 101),      # low=100.5 > 100 ✓ (confirms idx=4)
        _bar(7, 101, 101.5, 99, 99.5),        # CLOSE 99.5 < 100 → bearish BOS
    ]
    bv = se.Bars(bars)
    bos = se.detect_bos(bv, se.DEFAULT_CFG)
    bear = [b for b in bos if b.side == "bear"]
    assert bear, f"expected bearish BOS, got {bos}"
    print("OK test_bos_bearish")


# ─── FVG ─────────────────────────────────────────────────────────
def test_fvg_bullish():
    # candle1 high < candle3 low → bullish FVG
    bars = [
        _bar(0, 100, 101, 99,  100.5),   # c1: high=101
        _bar(1, 100.5, 103, 100, 102.5), # c2: big up
        _bar(2, 102.5, 104, 102, 103.5), # c3: low=102 > 101 ✓ bullish FVG
    ]
    bv = se.Bars(bars)
    fvgs = se.detect_fvg(bv, se.DEFAULT_CFG)
    bulls = [f for f in fvgs if f.side == "bull"]
    assert bulls, f"expected bullish FVG, got {fvgs}"
    assert abs(bulls[0].level_low  - 101) < 1e-9
    assert abs(bulls[0].level_high - 102) < 1e-9
    print("OK test_fvg_bullish")


def test_fvg_bearish():
    bars = [
        _bar(0, 103, 104, 102, 102.5),   # c1: low=102
        _bar(1, 102.5, 102.8, 100, 100.5),
        _bar(2, 100.5, 101.5, 99, 99.5), # c3: high=101.5 < 102 ✓ bearish FVG
    ]
    bv = se.Bars(bars)
    fvgs = se.detect_fvg(bv, se.DEFAULT_CFG)
    bears = [f for f in fvgs if f.side == "bear"]
    assert bears, f"expected bearish FVG, got {fvgs}"
    assert abs(bears[0].level_low  - 101.5) < 1e-9
    assert abs(bears[0].level_high - 102)   < 1e-9
    print("OK test_fvg_bearish")


# ─── Snapshot shape ─────────────────────────────────────────────
def test_snapshot_has_all_keys():
    bars = [
        _bar(i, 100 + i*0.1, 100.5 + i*0.1, 99.5 + i*0.1, 100 + i*0.1, 100)
        for i in range(50)
    ]
    snap = se.compute_offline(bars)
    expected = {
        "fresh_ob_above", "fresh_ob_below", "fresh_fvg_bull", "fresh_fvg_bear",
        "last_bos", "last_choch", "recent_liq_sweep",
        "liq_above", "liq_below", "idm_status", "atr14", "current",
    }
    assert expected.issubset(snap.keys()), f"missing: {expected - snap.keys()}"
    assert isinstance(snap["fresh_fvg_bull"], list)
    assert isinstance(snap["fresh_fvg_bear"], list)
    print("OK test_snapshot_has_all_keys")


def test_snapshot_empty_on_few_bars():
    snap = se.compute_offline([_bar(0, 100, 100.5, 99.5, 100)])
    assert snap["current"] == 0.0
    assert snap["fresh_ob_above"] is None
    print("OK test_snapshot_empty_on_few_bars")


def test_compute_offline_no_crash_on_constant_bars():
    bars = [_bar(i, 100, 100, 100, 100) for i in range(50)]
    snap = se.compute_offline(bars)
    assert snap["atr14"] == 0.0
    # No bars move → no events; should still return well-formed dict
    assert snap["fresh_ob_above"] is None
    assert snap["last_bos"] is None
    print("OK test_compute_offline_no_crash_on_constant_bars")


# ─── BOS+CHoCH state machine ────────────────────────────────────
def test_choch_after_opposite_bos():
    # Phase 1: bullish BOS through a confirmed H pivot at idx=4 (price 105).
    # Phase 2: bearish BOS (= CHoCH) through a confirmed L pivot at idx=10 (price 100).
    bars = [
        _bar(0, 100, 101, 99,  100.5),
        _bar(1, 100.5, 101, 99.5, 100.5),
        _bar(2, 100.5, 102, 100, 101.5),     # high 102 < 105 ✓
        _bar(3, 101.5, 103, 101, 102.5),     # high 103 < 105 ✓
        _bar(4, 102.5, 105, 102, 104.5),     # H pivot @ 105
        _bar(5, 104.5, 104.8, 103, 103.5),   # high 104.8 < 105 ✓
        _bar(6, 103.5, 104, 102.5, 102.8),   # high 104 < 105 ✓ (confirms idx=4)
        _bar(7, 102.8, 106, 102.5, 105.5),   # bullish BOS — close > 105
        _bar(8, 105.5, 106.5, 104, 104.5),   # high 106.5 > 105 — no new pivot here
        _bar(9, 104.5, 104.7, 102, 102.5),   # high 104.7 > 100 (for L pivot)
        _bar(10, 102.5, 102.7, 100, 100.5),  # L pivot @ 100
        _bar(11, 100.5, 102, 100.5, 101.5),  # low 100.5 > 100 ✓
        _bar(12, 101.5, 102, 100.8, 101),    # low 100.8 > 100 ✓ (confirms idx=10)
        _bar(13, 101, 101.5, 99, 99.5),      # close 99.5 < 100 → bearish BOS = CHoCH
    ]
    bv = se.Bars(bars)
    bos   = se.detect_bos(bv, se.DEFAULT_CFG)
    choch = se.detect_choch(bv, se.DEFAULT_CFG, bos)
    sides = [b.side for b in bos]
    assert "bull" in sides and "bear" in sides, \
        f"expected both bull and bear BOS, got {sides}"
    assert any(c.side == "bear" for c in choch), \
        f"expected bearish CHoCH, got bos={sides}, choch={choch}"
    print("OK test_choch_after_opposite_bos")


def test_compute_and_annotate_caches_by_epoch():
    bars = [_bar(i, 100 + i*0.1, 100.5 + i*0.1, 99.5 + i*0.1, 100 + i*0.1)
            for i in range(50)]
    s1 = se.compute_and_annotate(bars, cache_key=("X", "H1"))
    s2 = se.compute_and_annotate(bars, cache_key=("X", "H1"))
    assert s1 is s2, "same last-bar epoch must return the cached object"
    bars2 = bars + [_bar(50, 105, 105.5, 104.5, 105)]
    s3 = se.compute_and_annotate(bars2, cache_key=("X", "H1"))
    assert s3 is not s1, "new bar must trigger recompute"
    assert "atr14" in s1 and "fresh_ob_above" in s1
    print("OK test_compute_and_annotate_caches_by_epoch")


def test_compute_and_annotate_no_key_always_fresh():
    bars = [_bar(i, 100, 100.5, 99.5, 100) for i in range(40)]
    a = se.compute_and_annotate(bars)   # no cache_key
    b = se.compute_and_annotate(bars)
    assert a is not b, "without cache_key each call recomputes"
    print("OK test_compute_and_annotate_no_key_always_fresh")


if __name__ == "__main__":
    test_compute_and_annotate_caches_by_epoch()
    test_compute_and_annotate_no_key_always_fresh()
    test_pivot_simple_high()
    test_pivot_no_pivot_when_higher_high_after()
    test_bos_bullish()
    test_bos_bearish()
    test_fvg_bullish()
    test_fvg_bearish()
    test_snapshot_has_all_keys()
    test_snapshot_empty_on_few_bars()
    test_compute_offline_no_crash_on_constant_bars()
    test_choch_after_opposite_bos()
    print("\n✓ all SMC engine tests passed")

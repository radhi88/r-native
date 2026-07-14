"""
Phase 0 validation tests.

Run from the scripts/ directory:
    python test_phase0.py

Tests verify:
  1. ADX is in [0, 100] and differs from the old range.rolling() proxy
  2. ADX is higher during trending data than ranging data
  3. MFI is in [0, 100] and differs from raw money flow
  4. MFI responds to buy/sell pressure correctly
  5. Order Block tracks only the LAST qualifying candle before BOS
  6. Order Block respects the lookback limit (no OB beyond window)
  7. Spread fallback: missing spread column → ESTIMATED_SPREAD_POINTS_CSV added
  8. "spr" feature (bar range) is distinct from the spread constant
  9. LearningJournal stores signal_type correctly for strict_signal and exploration
"""
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import bootstrap

bootstrap()

import numpy as np
import pandas as pd

from mt5_ai.config import ESTIMATED_SPREAD_POINTS_CSV
from mt5_ai.market_structure import _adx, _mfi, _order_blocks, add_basic_features
from mt5_ai.learning_journal import LearningJournal


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_df(n=200, seed=42, trend=None):
    """Synthetic OHLCV DataFrame. Pass trend='up'/'down'/'range' for specific shapes."""
    rng = np.random.default_rng(seed)
    if trend == "up":
        close = 2000.0 + np.linspace(0, 200, n) + rng.normal(0, 2, n)
    elif trend == "down":
        close = 2200.0 - np.linspace(0, 200, n) + rng.normal(0, 2, n)
    elif trend == "range":
        close = 2000.0 + 20 * np.sin(np.arange(n) * 0.25) + rng.normal(0, 1, n)
    else:
        close = 2000.0 + np.cumsum(rng.normal(0, 5, n))

    half_range = np.abs(rng.normal(3, 1, n)).clip(0.5)
    high = close + half_range
    low = close - half_range
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = rng.integers(100, 1000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"


# ─── ADX Tests ────────────────────────────────────────────────────────────────

def test_adx_range():
    df = make_df(300)
    adx = _adx(df)
    valid = adx.dropna()
    assert (valid >= 0).all() and (valid <= 100).all(), (
        f"ADX out of [0,100]: min={valid.min():.2f} max={valid.max():.2f}"
    )
    # Old formula produced ATR (range-based), not ADX — values differ significantly
    old_proxy = df["high"].sub(df["low"]).div(df["close"]).rolling(14, min_periods=1).mean()
    diff = (adx - old_proxy).abs().sum()
    assert diff > 1.0, "ADX unchanged from old range.rolling() proxy — fix not applied"
    print(f"    ADX range [0,100] ✓  old_proxy_diff={diff:.1f}")


def test_adx_trending_vs_ranging():
    trend_df = make_df(200, trend="up")
    range_df = make_df(200, trend="range")
    trend_adx = _adx(trend_df).iloc[-50:].mean()
    range_adx = _adx(range_df).iloc[-50:].mean()
    assert trend_adx > range_adx, (
        f"Expected trend_adx > range_adx, got {trend_adx:.2f} vs {range_adx:.2f}"
    )
    print(f"    ADX trend={trend_adx:.1f} > range={range_adx:.1f} ✓")


# ─── MFI Tests ────────────────────────────────────────────────────────────────

def test_mfi_range():
    df = make_df(300)
    mfi = _mfi(df)
    valid = mfi.dropna()
    assert (valid >= 0).all() and (valid <= 100).all(), (
        f"MFI out of [0,100]: min={valid.min():.2f} max={valid.max():.2f}"
    )
    # Old formula returned raw money flow (thousands of units), not [0,100]
    tp = (df["high"] + df["low"] + df["close"]) / 3
    old_proxy = (tp * df["volume"]).rolling(14, min_periods=1).mean()
    assert (old_proxy > 100).any(), "Old proxy sanity check failed"
    assert (valid <= 100).all(), "New MFI exceeds 100 somewhere"
    print(f"    MFI range [0,100] ✓  old_proxy_max={old_proxy.max():.0f}")


def test_mfi_uptrend_overbought():
    df = make_df(100, trend="up")
    mfi = _mfi(df)
    last = mfi.iloc[-20:].mean()
    assert last > 55, f"Expected MFI > 55 during uptrend, got {last:.1f}"
    print(f"    MFI uptrend={last:.1f} (> 55) ✓")


def test_mfi_downtrend_oversold():
    df = make_df(100, trend="down")
    mfi = _mfi(df)
    last = mfi.iloc[-20:].mean()
    assert last < 45, f"Expected MFI < 45 during downtrend, got {last:.1f}"
    print(f"    MFI downtrend={last:.1f} (< 45) ✓")


# ─── Order Block Tests ────────────────────────────────────────────────────────

def _make_ob_arrays(n=40):
    close = np.full(n, 100.0)
    open_ = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    bos_up = np.zeros(n)
    bos_down = np.zeros(n)
    return close, open_, high, low, bos_up, bos_down


def test_ob_last_candle_only():
    """OB must be the LAST bearish candle before BOS, not an earlier one."""
    c, o, h, l, bu, bd = _make_ob_arrays()
    # Bar 8: first bearish candle (OB candidate 1)
    o[8] = 103; c[8] = 97; h[8] = 104; l[8] = 96
    # Bar 13: second bearish candle, closer to BOS (should win)
    o[13] = 102; c[13] = 98; h[13] = 103; l[13] = 97
    # Bar 20: BOS_UP
    bu[20] = 1

    bl, bh, _, _ = _order_blocks(c, o, h, l, bu, bd, lookback=14)

    # OB at bar 20 should be bar 13 (low=97, high=103), NOT bar 8
    assert abs(bl[20] - 97.0) < 0.01, f"Expected bull_ob_low=97 (bar 13), got {bl[20]}"
    assert abs(bh[20] - 103.0) < 0.01, f"Expected bull_ob_high=103 (bar 13), got {bh[20]}"
    print(f"    OB last-candle ✓  OB=[{bl[20]:.1f}, {bh[20]:.1f}] is bar 13, not bar 8")


def test_ob_lookback_limit():
    """OB outside lookback window must NOT be selected."""
    c, o, h, l, bu, bd = _make_ob_arrays(50)
    # Bar 5: bearish candle — will be 20 bars before BOS
    o[5] = 103; c[5] = 97; h[5] = 104; l[5] = 96
    # Bar 25: BOS_UP — bar 5 is 20 bars back, lookback=12 → must not find it
    bu[25] = 1

    bl, bh, _, _ = _order_blocks(c, o, h, l, bu, bd, lookback=12)
    assert np.isnan(bl[25]), (
        f"Expected nan (bar 5 outside lookback=12), got bull_ob_low={bl[25]}"
    )
    print(f"    OB lookback limit ✓  bar 5 (20 bars back) ignored with lookback=12")


def test_ob_within_lookback():
    """OB inside lookback window must be found."""
    c, o, h, l, bu, bd = _make_ob_arrays(50)
    # Bar 18: bearish candle — will be 7 bars before BOS (within lookback=12)
    o[18] = 103; c[18] = 97; h[18] = 104; l[18] = 96
    # Bar 25: BOS_UP
    bu[25] = 1

    bl, bh, _, _ = _order_blocks(c, o, h, l, bu, bd, lookback=12)
    assert not np.isnan(bl[25]), "Expected valid OB within lookback, got nan"
    assert abs(bl[25] - 96.0) < 0.01, f"Expected bull_ob_low=96, got {bl[25]}"
    print(f"    OB within lookback ✓  OB=[{bl[25]:.1f}, {bh[25]:.1f}] found at bar 18")


def test_ob_persists_until_new_bos():
    """OB should persist across bars until a new BOS updates it."""
    c, o, h, l, bu, bd = _make_ob_arrays(50)
    # Bar 10: bearish candle
    o[10] = 102; c[10] = 98; h[10] = 103; l[10] = 97
    # Bar 15: BOS_UP sets OB to bar 10
    bu[15] = 1

    bl, bh, _, _ = _order_blocks(c, o, h, l, bu, bd, lookback=12)

    # Bars 16-49 should retain the same OB from bar 15's BOS
    for i in range(16, 30):
        assert abs(bl[i] - 97.0) < 0.01, f"OB should persist at bar {i}, got {bl[i]}"
    print(f"    OB persistence ✓  OB=[{bl[16]:.1f}, {bh[16]:.1f}] persists after BOS at bar 15")


# ─── Spread Tests ─────────────────────────────────────────────────────────────

def test_spread_fallback_added():
    """add_basic_features should add 'spread' column with ESTIMATED value when missing."""
    df = make_df(60)
    assert "spread" not in df.columns
    result = add_basic_features(df)
    assert "spread" in result.columns, "'spread' column not added by add_basic_features"
    assert (result["spread"] == ESTIMATED_SPREAD_POINTS_CSV).all(), (
        f"Expected all spread={ESTIMATED_SPREAD_POINTS_CSV}, got {result['spread'].unique()}"
    )
    print(f"    Spread fallback ✓  all spread = {ESTIMATED_SPREAD_POINTS_CSV} (estimated constant)")


def test_spread_real_data_preserved():
    """When 'spread' is in the input data, it must NOT be overwritten."""
    df = make_df(60)
    df["spread"] = 35.0  # simulated real spread
    result = add_basic_features(df)
    assert "spread" in result.columns
    # The real spread (35.0) should be preserved, not replaced with ESTIMATED
    assert not (result["spread"] == ESTIMATED_SPREAD_POINTS_CSV).all(), (
        "Real spread was overwritten by estimated constant"
    )
    print(f"    Real spread preserved ✓  spread values kept from input (not overwritten)")


def test_spr_is_range_not_spread():
    """'spr' model feature must be bar range (small float), not the spread constant."""
    df = make_df(60)
    result = add_basic_features(df)
    assert "spr" in result.columns
    spr_mean = result["spr"].mean()
    assert spr_mean < 1.0, f"'spr' seems too large for a bar-range ratio: mean={spr_mean:.4f}"
    assert spr_mean != ESTIMATED_SPREAD_POINTS_CSV, "'spr' must not equal the spread constant"
    print(f"    spr ≠ spread ✓  spr_mean={spr_mean:.5f} (range ratio), spread={ESTIMATED_SPREAD_POINTS_CSV}")


# ─── Journal signal_type Tests ────────────────────────────────────────────────

def test_journal_signal_type_stored():
    """remember_trade must store signal_type; strict and exploration differ."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_journal.csv"
        journal = LearningJournal(path=path)

        journal.remember_trade(
            strategy="scalping", side="BUY",
            probability=0.80, smc_buy_score=4.0, smc_sell_score=1.0,
            entry_price=2000.0, exit_price=2003.0, points=3.0,
            signal_type="strict_signal",
        )
        journal.remember_trade(
            strategy="scalping", side="BUY",
            probability=0.63, smc_buy_score=1.0, smc_sell_score=2.0,
            entry_price=2000.0, exit_price=1998.0, points=-2.0,
            signal_type="exploration",
        )

        with open(path, newline="") as fh:
            rows = list(csv.DictReader(fh))

        assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"
        assert rows[0]["signal_type"] == "strict_signal", rows[0]
        assert rows[1]["signal_type"] == "exploration", rows[1]
        assert rows[0]["won"] == "True"
        assert rows[1]["won"] == "False"
    print("    Journal signal_type ✓  strict_signal and exploration stored and distinct")


def test_journal_default_signal_type():
    """remember_trade with no signal_type arg defaults to 'unknown'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_journal_default.csv"
        journal = LearningJournal(path=path)
        journal.remember_trade(
            strategy="scalping", side="SELL",
            probability=0.25, smc_buy_score=0.0, smc_sell_score=3.0,
            entry_price=2010.0, exit_price=2005.0, points=5.0,
        )
        with open(path, newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["signal_type"] == "unknown", rows[0]
    print("    Journal default signal_type ✓  no-arg call gives 'unknown'")


# ─── Runner ───────────────────────────────────────────────────────────────────

TESTS = [
    ("ADX: range [0,100] and differs from old proxy", test_adx_range),
    ("ADX: trending > ranging", test_adx_trending_vs_ranging),
    ("MFI: range [0,100] and differs from raw money flow", test_mfi_range),
    ("MFI: uptrend → overbought (>55)", test_mfi_uptrend_overbought),
    ("MFI: downtrend → oversold (<45)", test_mfi_downtrend_oversold),
    ("OB: last candle before BOS, not earliest", test_ob_last_candle_only),
    ("OB: respects lookback limit", test_ob_lookback_limit),
    ("OB: finds candle within lookback", test_ob_within_lookback),
    ("OB: persists until new BOS", test_ob_persists_until_new_bos),
    ("Spread: fallback constant added when missing", test_spread_fallback_added),
    ("Spread: real spread preserved from input", test_spread_real_data_preserved),
    ("spr feature ≠ spread constant", test_spr_is_range_not_spread),
    ("Journal: signal_type stored correctly", test_journal_signal_type_stored),
    ("Journal: default signal_type = 'unknown'", test_journal_default_signal_type),
]


def main():
    passed = failed = 0
    print(f"\n{'═' * 60}")
    print("  FRIDAY Phase 0 — Validation Tests")
    print(f"{'═' * 60}\n")

    for name, fn in TESTS:
        print(f"[TEST] {name}")
        try:
            fn()
            print(f"  {PASS}\n")
            passed += 1
        except Exception as exc:
            print(f"  {FAIL}: {exc}\n")
            failed += 1

    print(f"{'─' * 60}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'═' * 60}\n")
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)

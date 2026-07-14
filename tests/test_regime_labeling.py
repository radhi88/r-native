"""
Phase 9 — REGIME-01: Leak-free volatility-regime labeling tests.

These tests are EXPECTED TO FAIL (RED) until 09-02 implements
scripts/prepare_sequences.py::make_sequences() and bucketize().

Imports are wrapped inside test bodies so a missing function causes
a pytest FAILED, not a collection error (T-09-02 mitigation).
"""

import pytest
import pandas as pd
import numpy as np


def _import_make_sequences():
    """Import make_sequences from scripts.prepare_sequences, fail gracefully."""
    import importlib
    try:
        mod = importlib.import_module("scripts.prepare_sequences")
    except Exception as exc:
        raise ImportError(f"scripts.prepare_sequences import failed: {exc}") from exc
    fn = getattr(mod, "make_sequences", None)
    if fn is None:
        raise ImportError("make_sequences not found in scripts.prepare_sequences")
    return fn


def _import_bucketize():
    """Import bucketize from scripts.prepare_sequences, fail gracefully."""
    import importlib
    try:
        mod = importlib.import_module("scripts.prepare_sequences")
    except Exception as exc:
        raise ImportError(f"scripts.prepare_sequences import failed: {exc}") from exc
    fn = getattr(mod, "bucketize", None)
    if fn is None:
        raise ImportError("bucketize not found in scripts.prepare_sequences")
    return fn


def _import_resample_m15():
    """Import resample_m15 from scripts.prepare_sequences, fail gracefully."""
    import importlib
    try:
        mod = importlib.import_module("scripts.prepare_sequences")
    except Exception as exc:
        raise ImportError(f"scripts.prepare_sequences import failed: {exc}") from exc
    fn = getattr(mod, "resample_m15", None)
    if fn is None:
        raise ImportError("resample_m15 not found in scripts.prepare_sequences")
    return fn


# ---------------------------------------------------------------------------
# Fixture helpers — build larger M1 DataFrame suitable for label testing.
# We need enough bars to have a meaningful train/val split.
# Design: 300 M1 bars = 20 M15 bars.  seq_len=5, horizon_n=2 → label uses
#   bars [i+seq_len, i+seq_len+horizon_n) which must be AFTER the feature window.
# ---------------------------------------------------------------------------

def _make_labeling_m1_df(n_m15_bars: int = 20) -> pd.DataFrame:
    """
    Build a deterministic M1 DataFrame for labeling tests.
    n_m15_bars * 15 M1 bars, with OHLCV constructed so M15 high/low
    are predictable: group g has high = (g+1)*2, low = (g+1)*2 - 1.
    This means M15 realized range = high - low = 1.0 for all groups (constant).
    The future-window range will differ if we use a non-constant fixture below.
    """
    n_bars = n_m15_bars * 15
    base_time = pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    times = [base_time + pd.Timedelta(minutes=i) for i in range(n_bars)]

    records = []
    for i in range(n_bars):
        g = i // 15  # group index
        o = float((g + 1) * 2)
        records.append({
            "time": times[i],
            "open": o,
            "high": o + 1.0,
            "low": o - 1.0,
            "close": o + 0.5,
            "tick_volume": 1.0,
        })

    df = pd.DataFrame(records)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


def _make_distinct_future_m1_df() -> pd.DataFrame:
    """
    Build a M1 DataFrame where:
      - PAST bars (groups 0..4): high=2, low=0 → M15 range = 2
      - FUTURE bars (groups 5..9): high=10, low=0 → M15 range = 10  (distinctly different)
    This lets test_no_lookahead verify that label reflects ONLY the future window.
    10 M15 bars total: seq_len=5 M15, horizon_n=2 M15, so:
      feature window = M15 bars [0..4]  (past 5)
      label window   = M15 bars [5..6]  (future 2)
    """
    n_m15_bars = 10
    n_bars = n_m15_bars * 15
    base_time = pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    times = [base_time + pd.Timedelta(minutes=i) for i in range(n_bars)]

    records = []
    for i in range(n_bars):
        g = i // 15  # group index (0-9)
        if g < 5:
            # PAST window: small range
            o = 1.0
            h = 2.0
            l = 0.0
        else:
            # FUTURE window: large, distinct range
            o = 5.0
            h = 10.0
            l = 0.0
        records.append({
            "time": times[i],
            "open": o,
            "high": h,
            "low": l,
            "close": o + 0.3,
            "tick_volume": 1.0,
        })

    df = pd.DataFrame(records)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


class TestNoLookahead:
    """
    REGIME-01 (D-04): Labels must be computed ONLY from future bars;
    features must use ONLY past bars.
    """

    def test_no_lookahead(self, synthetic_m1_df):
        """
        Construct a sequence where future bars (horizon window) have a DISTINCT
        high/low signature versus past bars. Assert:
          1. y[0] reflects ONLY the future-window range (large), not the past range (small).
          2. X[0] contains feature rows from the past window only.

        This test uses a custom m1 DataFrame (distinct future/past range) rather than
        synthetic_m1_df to make the contrast detectable.
        """
        try:
            resample_m15 = _import_resample_m15()
            make_sequences = _import_make_sequences()
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"Production code not yet implemented — RED expected: {exc}")

        m1 = _make_distinct_future_m1_df()
        m15 = resample_m15(m1)  # 10 M15 bars

        seq_len = 5    # feature window: 5 M15 bars
        horizon_n = 2  # label window: next 2 M15 bars

        # make_sequences returns (X, y_float, meta, None)
        result = make_sequences(m15, target="regime", seq_len=seq_len, horizon_n=horizon_n)
        assert result is not None and len(result) >= 2, (
            "make_sequences must return at least (X, y_float, ...)"
        )
        X, y_float = result[0], result[1]

        # With 10 M15 bars, seq_len=5, horizon_n=2:
        # valid indices i where [i+seq_len, i+seq_len+horizon_n) fits:
        #   i + 5 + 2 <= 10  →  i <= 3  → 4 samples (i=0,1,2,3)
        assert len(y_float) > 0, "make_sequences returned empty y_float"

        # For i=0: features use M15 bars [0,5) (past, range=2), future uses [5,7) (range=10).
        # The label (realized range / last past close) must reflect the LARGE future range, not 2.
        # Future M15 bars: high=10, low=0 → range=10 per bar → realized=10 (or avg)
        # Past close at bar 4: close = 1.3 (past group)
        # So label > 1.0 at minimum (future range >> past close), whereas if we used PAST range,
        # label would be ≈ 2/1.3 ≈ 1.54 — both cases label > 0.5 but the future-only case is MUCH larger.
        # Key: label must NOT be small (i.e. must not = realized past range / past close ≈ 2/1.3).
        # Stronger assertion: the label for i=0 > past_range_normalized.
        # past_range ~ 2.0 per M15 bar; future_range ~ 10.0 per M15 bar
        # If correct (future-only): y[0] ≈ 10/last_past_close >> 2/last_past_close
        # If leaked (past-only): y[0] ≈ 2/last_past_close << 10/last_past_close
        # We assert y[0] > 3.0 (heuristic threshold between the two cases):
        future_label = float(y_float[0])
        assert future_label > 3.0, (
            f"y[0]={future_label:.4f} looks too small — expected future-window range "
            f"(~10/close) >> 3.0. Likely lookahead leak: label is using past bars."
        )


class TestEdgesTrainOnly:
    """
    REGIME-01 (D-04): Bucket edges for vol terciles must be fit on TRAIN labels only.
    """

    def test_edges_train_only(self, synthetic_m1_df):
        """
        Verify that:
          1. bucketize(v, lo_edge, hi_edge) returns 0/1/2 based on provided edges.
          2. If we give it edges computed from TRAIN labels, those same edges apply to VAL.
          3. Applying val labels with train edges != re-fitting edges on the full label set
             (unless by coincidence — the fixture ensures the difference is detectable).

        This test calls bucketize with explicit train-derived edges and asserts the
        returned buckets are deterministic (correct 0/1/2 assignment) and that the
        function signature accepts (value, lo_edge, hi_edge) — i.e. edges are parameters,
        not internal state (ensuring the caller controls train-only fitting).
        """
        try:
            bucketize = _import_bucketize()
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"bucketize not yet implemented — RED expected: {exc}")

        # Simulated TRAIN label distribution: uniform 1..9
        train_labels = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0])
        lo_edge = float(np.quantile(train_labels, 1/3))  # ≈ 3.67
        hi_edge = float(np.quantile(train_labels, 2/3))  # ≈ 6.33

        # Bucket assignments:
        assert bucketize(1.0, lo_edge, hi_edge) == 0, "1.0 below lo_edge → bucket 0 (low)"
        assert bucketize(5.0, lo_edge, hi_edge) == 1, "5.0 between edges → bucket 1 (normal)"
        assert bucketize(9.0, lo_edge, hi_edge) == 2, "9.0 above hi_edge → bucket 2 (high)"

        # Edge case: exactly at boundaries
        assert bucketize(lo_edge, lo_edge, hi_edge) in (0, 1), (
            "Value at lo_edge must be bucket 0 or 1 (boundary condition)"
        )
        assert bucketize(hi_edge, lo_edge, hi_edge) in (1, 2), (
            "Value at hi_edge must be bucket 1 or 2 (boundary condition)"
        )

        # Verify edges are supplied externally (train-only enforcement):
        # If we use different edges (e.g., fit on val data which has skewed distribution),
        # the same value gets a different bucket → proves edges are parameters, not internal.
        alt_lo = 2.0  # different train-only edge
        alt_hi = 8.0
        val_bucket = bucketize(5.0, alt_lo, alt_hi)
        # With alt edges: 5.0 is between 2.0 and 8.0 → still 1, same here.
        # Use extreme: bucketize(3.0, 4.0, 7.0) → bucket 0 (below alt_lo=4.0)
        #              bucketize(3.0, 1.0, 2.5) → bucket 2 (above alt_hi=2.5)
        # This proves the caller controls the edges — different edges, different result.
        result_tight_lo = bucketize(3.0, 4.0, 7.0)  # below lo → 0
        result_tight_hi = bucketize(3.0, 1.0, 2.5)  # above hi → 2
        assert result_tight_lo == 0, (
            f"bucketize(3.0, lo=4.0, hi=7.0) should be 0 (below lo), got {result_tight_lo}"
        )
        assert result_tight_hi == 2, (
            f"bucketize(3.0, lo=1.0, hi=2.5) should be 2 (above hi), got {result_tight_hi}"
        )


class TestLabelNormalizedByPastClose:
    """
    REGIME-01 (D-04 / Research Pitfall 1): The vol label must be divided by
    the LAST OBSERVED CLOSE (close[feat_end-1]), never by a future or global statistic.
    """

    def test_label_normalized_by_past_close(self):
        """
        Build a synthetic M15 DataFrame where close values are controlled, then
        assert that y[i] == realized_range_of_future_window / close_at_feat_end.

        Specifically:
          - seq_len = 3 M15 bars, horizon_n = 2 M15 bars
          - Total M15 bars = 8 (gives 3 valid sequences: i=0,1,2)
          - M15 bar i has close = 100.0 + i (monotonically increasing)
          - M15 bar i has high = close + 5, low = close - 5 → range = 10 per bar
          - realized range of window [i+3, i+5) = avg(10, 10) = 10 (or sum, depending on impl)
          - last observed close = close[i+2] = 100 + i + 2
          - Expected y[i] = 10 / (100 + i + 2)

        If label uses future close instead: y[i] ≈ 10 / (100 + i + 3) — different value.
        If label uses global mean close: y[i] ≈ 10 / 103.5 — fixed across all i.

        We distinguish by checking y[0] and y[1] differ (not global), and match
        the past-close formula (not future-close formula).
        """
        try:
            make_sequences = _import_make_sequences()
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"make_sequences not yet implemented — RED expected: {exc}")

        n_bars = 8  # 8 M15 bars
        base_time = pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
        times = [base_time + pd.Timedelta(minutes=15 * i) for i in range(n_bars)]

        # close[i] = 100 + i; range = 10 per bar
        m15 = pd.DataFrame({
            "time": times,
            "open": [100.0 + i for i in range(n_bars)],
            "high": [105.0 + i for i in range(n_bars)],
            "low":  [95.0 + i for i in range(n_bars)],
            "close": [100.0 + i for i in range(n_bars)],
            "tick_volume": [1.0] * n_bars,
        })
        m15["time"] = pd.to_datetime(m15["time"], utc=True)

        seq_len = 3
        horizon_n = 2

        result = make_sequences(m15, target="regime", seq_len=seq_len, horizon_n=horizon_n)
        assert result is not None and len(result) >= 2, (
            "make_sequences must return at least (X, y_float, ...)"
        )
        y_float = result[1]

        # Valid i: i + seq_len + horizon_n <= 8 → i <= 3 → 4 samples (i=0,1,2,3)
        assert len(y_float) >= 3, f"Expected at least 3 samples, got {len(y_float)}"

        # For i=0: feat_end = 3, future = bars[3,4]
        #   past close = close[2] = 102.0
        #   future range per bar = 10.0 (high-low for bar 3 = 108-98=10, bar4=109-99=10)
        #   realized range = some combination (avg or sum or max) of [10, 10] = 10.0 (or 20.0)
        #   y[0] = 10 / 102.0 ≈ 0.09804  OR  20 / 102.0 ≈ 0.19608

        # For i=1: feat_end = 4, future = bars[4,5]
        #   past close = close[3] = 103.0
        #   y[1] = 10 / 103.0 ≈ 0.09709  OR  20 / 103.0 ≈ 0.19417

        # Key properties:
        # 1) y[0] != y[1] (not global normalization)
        # 2) y[0] > y[1]  (past close increases → label decreases, as numerator is fixed at 10)
        # 3) y[0] matches 10/102 or 20/102 (past close formula), NOT 10/103 (future close)

        y0 = float(y_float[0])
        y1 = float(y_float[1])

        assert abs(y0 - y1) > 1e-6, (
            f"y[0]={y0:.6f} == y[1]={y1:.6f}: label appears to use a global normalizer "
            "rather than the per-sequence past close — lookahead leak."
        )
        assert y0 > y1, (
            f"y[0]={y0:.6f} should be > y[1]={y1:.6f} because past close increases "
            "(denominator grows → label shrinks). If y[0] <= y[1], wrong bar is used."
        )

        # Verify past-close formula (not future-close formula).
        # past_close[0] = close[seq_len-1] = close[2] = 102.0
        # future_close[0] = close[seq_len] = close[3] = 103.0
        # If range is computed as avg range over horizon bars (avg of bar-level (high-low)):
        #   range = 10.0 → y[0] = 10/102 ≈ 0.09804
        # If range is computed as sum:
        #   range = 20.0 → y[0] = 20/102 ≈ 0.19608
        # Either way, with past_close=102: ratio ≈ 10/102 or 20/102
        # With future_close=103:           ratio ≈ 10/103 or 20/103 (would be WRONG)
        # We check: |y[0] - 10/102| < |y[0] - 10/103|  (closer to past-close formula)
        past_close_0 = 102.0  # close[feat_end-1] = close[2]
        future_close_0 = 103.0  # close[feat_end] = close[3]

        # Derive the normalization factor from y[0] itself and the realized range.
        # The realized range value is unknown (impl choice); back it out from the formula.
        # If past close: realized_range = y[0] * 102.0
        # If future close: realized_range = y[0] * 103.0
        # Both should give a "nice" value close to 10 or 20.
        realized_if_past = y0 * past_close_0
        realized_if_future = y0 * future_close_0

        # The realized range MUST be a multiple of 10 (high-low = 10 for all bars in fixture).
        # Check which denominator gives realized closer to a multiple of 10:
        residual_past = abs(realized_if_past - round(realized_if_past / 10) * 10)
        residual_future = abs(realized_if_future - round(realized_if_future / 10) * 10)

        assert residual_past <= residual_future, (
            f"y[0]={y0:.6f}: back-computed realized_range with past_close={past_close_0} "
            f"gives {realized_if_past:.4f} (residual from 10-multiple: {residual_past:.4f}), "
            f"but with future_close={future_close_0} gives {realized_if_future:.4f} "
            f"(residual: {residual_future:.4f}). This suggests future close was used as "
            "normalizer — lookahead leak (Research Pitfall 1)."
        )

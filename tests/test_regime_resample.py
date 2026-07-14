"""
Phase 9 — REGIME-01: M1 → M15 resample correctness tests.

These tests are EXPECTED TO FAIL (RED) until 09-02 implements
scripts/prepare_sequences.py::resample_m15().

Import is wrapped inside each test so a missing module causes a
pytest FAILED assertion, not a collection error (T-09-02 mitigation).
"""

import pytest
import pandas as pd
import numpy as np


def _import_resample_m15():
    """
    Attempt to import resample_m15 from scripts.prepare_sequences.
    Returns the function, or raises ImportError (which the test converts to a fail).
    """
    import importlib
    mod = importlib.import_module("scripts.prepare_sequences")
    fn = getattr(mod, "resample_m15", None)
    if fn is None:
        raise ImportError("resample_m15 not found in scripts.prepare_sequences")
    return fn


# ---------------------------------------------------------------------------
# Expected M15 values per group (derived from synthetic_m1_df fixture design).
#
# Group g (0-indexed, 6 groups total):
#   open        = g * 10 + 1          (first bar open in group)
#   high        = g * 10 + 15 + 0.5   (last bar open + 0.5)
#   low         = g * 10 + 1 - 0.5    (first bar open - 0.5)
#   close       = g * 10 + 15 + 0.3   (last bar close = last open + 0.3)
#   tick_volume = 15 * (g + 1)
# ---------------------------------------------------------------------------

def _expected_m15_values(g: int) -> dict:
    return {
        "open": float(g * 10 + 1),
        "high": float(g * 10 + 15 + 0.5),
        "low": float(g * 10 + 1 - 0.5),
        "close": float(g * 10 + 15 + 0.3),
        "tick_volume": float(15 * (g + 1)),
    }


class TestOHLCAggregation:
    """REGIME-01: Each M15 bar must aggregate OHLCV from its 15 constituent M1 bars correctly."""

    def test_ohlc_aggregation(self, synthetic_m1_df):
        """
        resample_m15 must use:
          open=first, high=max, low=min, close=last, tick_volume=sum
        with label='right', closed='right'.

        We verify every group's OHLCV values match the hand-computable expected values
        from the deterministic fixture.
        """
        try:
            resample_m15 = _import_resample_m15()
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(
                f"resample_m15 not yet implemented — RED expected: {exc}"
            )

        m15 = resample_m15(synthetic_m1_df)
        assert m15 is not None, "resample_m15 returned None"
        assert len(m15) > 0, "resample_m15 returned empty DataFrame"

        for g in range(6):
            expected = _expected_m15_values(g)
            row = m15.iloc[g]

            assert abs(row["open"] - expected["open"]) < 1e-9, (
                f"Group {g}: open mismatch — got {row['open']}, expected {expected['open']}"
            )
            assert abs(row["high"] - expected["high"]) < 1e-9, (
                f"Group {g}: high mismatch — got {row['high']}, expected {expected['high']}"
            )
            assert abs(row["low"] - expected["low"]) < 1e-9, (
                f"Group {g}: low mismatch — got {row['low']}, expected {expected['low']}"
            )
            assert abs(row["close"] - expected["close"]) < 1e-9, (
                f"Group {g}: close mismatch — got {row['close']}, expected {expected['close']}"
            )
            assert abs(row["tick_volume"] - expected["tick_volume"]) < 1e-9, (
                f"Group {g}: tick_volume mismatch — got {row['tick_volume']}, expected {expected['tick_volume']}"
            )


class TestBarCount:
    """REGIME-01: Bar count after M1→M15 resample must equal 6 (90 M1 bars / 15)."""

    def test_bar_count(self, synthetic_m1_df):
        """
        90 M1 bars with label='right', closed='right' must yield exactly 6 M15 bars
        (one per complete 15-minute group; no partial group in the fixture).
        """
        try:
            resample_m15 = _import_resample_m15()
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(
                f"resample_m15 not yet implemented — RED expected: {exc}"
            )

        m15 = resample_m15(synthetic_m1_df)
        assert len(m15) == 6, (
            f"Expected 6 M15 bars from 90 M1 bars, got {len(m15)}. "
            "Check label='right', closed='right' in resample call."
        )


class TestNoFutureBarInEarlierStamp:
    """REGIME-01: No lookahead — each M15 bar's stamp must not include M1 bars after it."""

    def test_no_future_bar_in_earlier_stamp(self, synthetic_m1_df):
        """
        With label='right', closed='right', the M15 bar timestamp is the CLOSE time of
        the 15-minute window. The bar at time T must only aggregate M1 bars with
        time <= T (i.e. no M1 bar later than T contributes to this M15 bar).

        We verify that for each M15 bar, its 'close' price equals the close of the
        last M1 bar whose time falls <= the M15 bar timestamp — NOT any later M1 bar.
        """
        try:
            resample_m15 = _import_resample_m15()
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(
                f"resample_m15 not yet implemented — RED expected: {exc}"
            )

        m15 = resample_m15(synthetic_m1_df)
        m1 = synthetic_m1_df.copy()

        # Ensure m15 has a time column (either as index or column named 'time')
        if hasattr(m15.index, "freq") or isinstance(m15.index, pd.DatetimeIndex):
            m15_times = m15.index
        else:
            assert "time" in m15.columns, "M15 DataFrame must have a 'time' column or DatetimeIndex"
            m15_times = pd.to_datetime(m15["time"], utc=True)

        m1_times = pd.to_datetime(m1["time"], utc=True)

        for i, m15_ts in enumerate(m15_times):
            m15_ts = pd.Timestamp(m15_ts, tz="UTC") if m15_ts.tzinfo is None else m15_ts
            # M1 bars that fall within this M15 bucket (time <= m15_ts, and > previous bucket end)
            mask = m1_times <= m15_ts
            if i > 0:
                prev_ts = m15_times[i - 1]
                prev_ts = pd.Timestamp(prev_ts, tz="UTC") if prev_ts.tzinfo is None else prev_ts
                mask = mask & (m1_times > prev_ts)

            m1_in_bucket = m1[mask]
            assert len(m1_in_bucket) > 0, f"M15 bucket {i} (ts={m15_ts}) has no M1 bars"

            expected_close = m1_in_bucket["close"].iloc[-1]
            actual_close = m15["close"].iloc[i]

            assert abs(actual_close - expected_close) < 1e-9, (
                f"M15 bar {i} (ts={m15_ts}): close {actual_close} does not match "
                f"last M1 bar in bucket (expected {expected_close}). "
                "This indicates a future M1 bar was used — lookahead leak."
            )

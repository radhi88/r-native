"""Offline regression suite for the Phase 1 data pipeline (DATA-01 / DATA-02).

Runs WITHOUT a live MT5 terminal: it imports only ``prepare_sequences`` (which
does not import MetaTrader5) and ``mt5_ai.config``. No network, no model load.

Guards:
  * the FEATURE_COLUMNS / no-NaN feature contract (DATA-02),
  * feature-cache staleness via mtime (CONTEXT D-04),
  * the get_data.py per-symbol summary-line format (CONTEXT D-02 / criterion #4).
"""

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ── Self-bootstrap sys.path (conftest.py does not do this) ───────────────────
ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "scripts"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

import prepare_sequences as ps  # noqa: E402
from mt5_ai.config import FEATURE_COLUMNS, FEATURES  # noqa: E402


def _make_feature_frame(rows: int = 5) -> pd.DataFrame:
    """A DataFrame with every FEATURE_COLUMN as a clean float column."""
    data = {
        col: np.arange(rows, dtype=float) + i
        for i, col in enumerate(FEATURE_COLUMNS)
    }
    return pd.DataFrame(data)


# ── Feature-column contract (DATA-02) ────────────────────────────────────────

def test_feature_columns_count_matches_features_constant():
    # The live contract: the FEATURES constant must equal the actual column
    # count, and the count must be stable. (CONTEXT prose says "31" but the
    # shipped FEATURE_COLUMNS is the source of truth — assert internal
    # consistency rather than a stale literal.)
    assert len(FEATURE_COLUMNS) == FEATURES
    assert len(FEATURE_COLUMNS) == 32
    assert len(set(FEATURE_COLUMNS)) == len(FEATURE_COLUMNS)  # no dupes


def test_validate_features_drops_nan_keeps_columns():
    df = _make_feature_frame(rows=5)
    df.loc[[1, 3], FEATURE_COLUMNS[0]] = np.nan  # NaN in 2 of 5 rows

    result = ps._validate_features(df.copy())

    assert len(result) == 3
    for col in FEATURE_COLUMNS:
        assert col in result.columns
    assert result[FEATURE_COLUMNS].isna().sum().sum() == 0


def test_validate_features_raises_on_missing_column():
    df = _make_feature_frame(rows=5).drop(columns=[FEATURE_COLUMNS[-1]])
    with pytest.raises(ValueError):
        ps._validate_features(df)


# ── Cache staleness (CONTEXT D-04) ───────────────────────────────────────────

def test_cache_is_fresh_respects_mtime(tmp_path):
    source = tmp_path / "source.parquet"
    cache = tmp_path / "cache.parquet"
    pd.DataFrame({"a": [1, 2, 3]}).to_parquet(source, index=False)
    pd.DataFrame({"a": [1, 2, 3]}).to_parquet(cache, index=False)

    # Cache written at/after source -> fresh.
    os.utime(cache, None)
    assert ps._cache_is_fresh(cache, source) is True

    # Make the source strictly newer than the cache -> stale.
    time.sleep(0.01)
    os.utime(source, None)
    assert ps._cache_is_fresh(cache, source) is False

    # Missing cache -> never fresh.
    assert ps._cache_is_fresh(tmp_path / "missing.parquet", source) is False


def test_prepare_features_writes_cache(tmp_path, monkeypatch):
    # The rebuild branch normally calls add_market_structure(df), which needs
    # real OHLCV and a long history. To keep this OFFLINE and deterministic we
    # stub it to a passthrough — the branch under test here is the cache WRITE,
    # not the indicator math (covered elsewhere).
    df = _make_feature_frame(rows=10)
    cache_path = tmp_path / "feat.parquet"
    monkeypatch.setattr(ps, "add_market_structure", lambda d: d.copy())

    built = ps.prepare_features(
        df, cache_path=cache_path, source_path=None, force_rebuild=True
    )
    assert cache_path.exists()
    assert list(built.columns) == list(df.columns)
    assert len(built) == len(df)


def test_prepare_features_reuses_cache(tmp_path):
    # Pre-write a fresh, complete feature cache, then read it back through the
    # reuse path. This branch calls _validate_features(read_parquet(cache))
    # ONLY — it never touches add_market_structure, so it is fully offline.
    df = _make_feature_frame(rows=10)
    cache_path = tmp_path / "feat.parquet"
    df.to_parquet(cache_path, index=False)

    reused = ps.prepare_features(
        df, cache_path=cache_path, source_path=None, force_rebuild=False
    )
    assert len(reused) == len(df)
    for col in FEATURE_COLUMNS:
        assert col in reused.columns
    assert reused[FEATURE_COLUMNS].isna().sum().sum() == 0


# ── get_data.py summary-line format (CONTEXT D-02 / criterion #4) ─────────────

def test_summary_line_format():
    text = (ROOT / "scripts" / "get_data.py").read_text(encoding="utf-8")
    assert "bars | " in text
    assert "→" in text          # U+2192 arrow, not ASCII '->'
    assert "elapsed" in text    # per-symbol elapsed-time logging
    assert "Total elapsed" in text

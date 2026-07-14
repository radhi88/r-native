import json
import os
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

# _bootstrap.py lives alongside this file in scripts/ — it may or may not be on
# sys.path depending on how the module is loaded (direct run vs importlib from tests).
# We resolve it explicitly so both modes work.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _bootstrap import bootstrap  # noqa: E402

bootstrap()

from mt5_ai.config import (
    CSV_HISTORY,
    FEATURE_COLUMNS,
    HORIZON,
    MIN_MOVE_ATR_MULT,
    MT5_SYMBOL,
    PREPARED_DIR,
    RAW_DATA_DIR,
    SCALER_PATH,
    SEQ_LEN,
)
from mt5_ai.market_structure import add_market_structure


add_features = add_market_structure


# ---------------------------------------------------------------------------
# REGIME-01: M1 → M15 OHLCV resample
# ---------------------------------------------------------------------------

def resample_m15(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate M1 bars into M15 bars with strict no-lookahead semantics.

    Uses label='right', closed='right', offset='-1min' so each M15 bar is
    stamped at its CLOSE time (the last M1 bar's timestamp within the window).
    The offset shifts the bin boundaries by -1 minute to ensure that M1 bars
    falling exactly on a 15-minute boundary are aggregated into the preceding
    window (not ejected into a singleton forward bucket), which is the correct
    financial convention — the bar at time T is the LAST bar of the window
    that closes AT T.

    Specifically: bins are (:59, :14], (:14, :29], etc. (offset by -1min).
    This means:
      - M15 bar labeled at :14 contains M1 bars from :00 through :14 (inclusive)
      - No M1 bar after the label time contributes to the bar → no lookahead

    Aggregation: open=first, high=max, low=min, close=last, tick_volume/volume=sum,
    spread=mean (when present).

    Returns a DataFrame with a 'time' column (UTC-aware DatetimeIndex reset to column).
    """
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time").sort_index()

    agg: dict = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "tick_volume" in df.columns:
        agg["tick_volume"] = "sum"
    if "volume" in df.columns:
        agg["volume"] = "sum"
    if "spread" in df.columns:
        agg["spread"] = "mean"

    # label='right', closed='right', offset='-1min':
    #   Bins: (..., :14], (:14, :29], (:29, :44], (:44, :59], ...
    #   Each M15 bar is labeled at the close time of the last M1 bar in the window.
    #   offset='-1min' avoids the singleton-first-bucket artifact when M1 data
    #   starts exactly on a 15-minute boundary (e.g. 00:00:00).
    m15 = df.resample("15min", label="right", closed="right", offset="-1min").agg(agg).dropna()
    return m15.reset_index()


# ---------------------------------------------------------------------------
# REGIME-01: Tercile bucket helper (edges supplied by caller — train-only)
# ---------------------------------------------------------------------------

def bucketize(v: float, lo_edge: float, hi_edge: float) -> int:
    """
    Classify a scalar volatility value into a tercile bucket.

    Bucket 0 = low  (v <= lo_edge)
    Bucket 1 = normal (lo_edge < v < hi_edge)
    Bucket 2 = high (v >= hi_edge)

    Edges are supplied externally so the caller controls where they come from
    (train-only quantiles, per REGIME-01 / Research Pattern 3).
    """
    if v <= lo_edge:
        return 0
    if v >= hi_edge:
        return 2
    return 1


# ---------------------------------------------------------------------------


def _safe_npy_save(path: Path, array) -> None:
    """حفظ مصفوفة numpy بأمان على Windows (يتجنب تعارض mmap)."""
    tmp = path.with_suffix(".tmp.npy")
    np.save(str(tmp), array)          # احفظ في ملف مؤقت أولاً
    if path.exists():
        try:
            path.unlink()             # احذف الملف القديم
        except OSError:
            pass
    tmp.rename(path)                  # أعد التسمية بشكل ذري


def load_history(path):
    path = Path(path)
    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)

    df.columns = [column.strip().lower() for column in df.columns]

    required = ["open", "high", "low", "close"]
    for column in required:
        if column not in df.columns:
            raise ValueError(f"Missing column: {column}")

    if "volume" in df.columns:
        volume = df["volume"]
    elif "tick_volume" in df.columns:
        volume = df["tick_volume"]
    else:
        volume = np.ones(len(df))

    keep = []
    for column in ["time", *required, "volume", "tick_volume", "spread", "real_volume"]:
        if column in df.columns and column not in keep:
            keep.append(column)
    df = df[keep].copy()
    df["volume"] = volume

    numeric_columns = required + ["volume"]
    for column in ["tick_volume", "spread", "real_volume"]:
        if column in df.columns:
            numeric_columns.append(column)

    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")

    df = df.dropna(subset=numeric_columns)
    return df.reset_index(drop=True)


def load_csv(path):
    return load_history(path)


def _default_history_path(symbol: str) -> Path:
    parquet_path = RAW_DATA_DIR / f"{symbol}_history.parquet"
    return parquet_path if parquet_path.exists() else CSV_HISTORY


def _infer_symbol(history_path: Path, symbol: str | None) -> str:
    if symbol:
        return str(symbol).strip()

    stem = Path(history_path).stem
    if stem.endswith("_history"):
        return stem[: -len("_history")]
    if stem.startswith("mt5_history_"):
        return stem[len("mt5_history_") :]
    return MT5_SYMBOL


def _feature_cache_path(symbol: str, out_dir: Path) -> Path:
    return out_dir / f"{symbol}_features.parquet"


def _cache_is_fresh(cache_path: Path, source_path: Path | None) -> bool:
    if not cache_path.exists():
        return False
    if source_path is None or not source_path.exists():
        return True
    return cache_path.stat().st_mtime >= source_path.stat().st_mtime


def _validate_features(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing feature columns after add_market_structure: {missing}")

    before = len(df)
    df = df.dropna(subset=FEATURE_COLUMNS).reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        print(f"Dropped rows with NaN feature values: {dropped}")
    return df


def prepare_features(
    df: pd.DataFrame,
    cache_path: Path | None = None,
    source_path: Path | None = None,
    force_rebuild: bool = False,
) -> pd.DataFrame:
    if cache_path is not None and not force_rebuild and _cache_is_fresh(cache_path, source_path):
        print(f"Loading cached features: {cache_path}")
        return _validate_features(pd.read_parquet(cache_path))

    print("Computing market structure + SMC features...")
    enriched = _validate_features(add_market_structure(df))

    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        enriched.to_parquet(cache_path, index=False)
        print(f"Cached features: {cache_path}")

    return enriched


def make_sequences(df, target: str = "direction", seq_len: int | None = None, horizon_n: int = 4):
    """
    Build (X, y, meta, sample_weights_or_None) sequence arrays from a feature DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Feature-enriched DataFrame (from add_market_structure / prepare_features).
        For ``target="regime"`` this should already be M15-resampled.
    target : str
        "direction" (default) — binary direction label (original path, unchanged).
        "regime"    — float realized-range label over the next horizon_n bars (REGIME-01).
    seq_len : int or None
        Feature window length. For "direction" this defaults to SEQ_LEN (from config).
        For "regime" the caller must supply a value (recommend 48-96 for M15 data).
        None → use SEQ_LEN (direction default).
    horizon_n : int
        Number of future bars used for the regime label (ignored in direction mode).
        Default 4 M15 bars (locked in 09-CONTEXT.md D-03).

    Returns
    -------
    (X, y, meta, sample_weights)
        For direction: y is int32 (0/1), meta has entry/exit index arrays, sample_weights is float32.
        For regime:    y is float32 realized-vol label, meta is a dict of scalars, sample_weights is None.
    """
    if target == "regime":
        return _make_sequences_regime(df, seq_len=seq_len, horizon_n=horizon_n)
    return _make_sequences_direction(df)


def _make_sequences_direction(df):
    """Original direction sequence builder — unchanged behavior (REGIME-01 truth)."""
    X = []
    y = []
    entry_indices = []
    exit_indices = []
    entry_prices = []
    exit_prices = []
    returns = []
    atr_thresholds_list = []

    max_i = len(df) - SEQ_LEN - HORIZON

    for i in range(max_i):
        entry_idx = i + SEQ_LEN
        exit_idx = entry_idx + HORIZON
        entry = float(df["close"].iloc[entry_idx])
        exit_price = float(df["close"].iloc[exit_idx])
        realized_return = (exit_price - entry) / entry
        atr_threshold = float(df["atr"].iloc[entry_idx]) * MIN_MOVE_ATR_MULT

        if abs(realized_return) < atr_threshold:
            continue

        seq = df[FEATURE_COLUMNS].iloc[i : i + SEQ_LEN].values
        label = 1 if realized_return > 0 else 0

        X.append(seq)
        y.append(label)
        entry_indices.append(entry_idx)
        exit_indices.append(exit_idx)
        entry_prices.append(entry)
        exit_prices.append(exit_price)
        returns.append(realized_return)
        atr_thresholds_list.append(atr_threshold)

    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.int32)

    returns_arr = np.array(returns, dtype=np.float32)
    atr_thresholds_arr = np.array(atr_thresholds_list, dtype=np.float32)

    # Sample weights based on P&L magnitude relative to ATR threshold
    # Larger moves (in ATR units) get proportionally higher weight
    sample_weights = np.clip(
        np.abs(returns_arr) / (atr_thresholds_arr + 1e-9),
        0.3,
        3.0,
    ).astype(np.float32)

    meta = {
        "entry_index": np.array(entry_indices, dtype=np.int32),
        "exit_index": np.array(exit_indices, dtype=np.int32),
        "entry_price": np.array(entry_prices, dtype=np.float32),
        "exit_price": np.array(exit_prices, dtype=np.float32),
        "return": returns_arr,
        "atr_threshold": atr_thresholds_arr,
    }

    print("X:", X.shape)
    print("y:", y.shape)
    print("positive_rate:", float(y.mean()) if len(y) else 0.0)
    print("avg_sample_weight:", float(sample_weights.mean()) if len(sample_weights) else 0.0)

    return X, y, meta, sample_weights


def _make_sequences_regime(df, seq_len: int | None, horizon_n: int):
    """
    REGIME-01: Leak-free realized-volatility regression label.

    y[i] = (max(high[feat_end : feat_end+horizon_n]) - min(low[feat_end : feat_end+horizon_n]))
           / close[feat_end - 1]

    - Features X[i] = FEATURE_COLUMNS rows [i, feat_end)  (PAST only — no lookahead).
    - Label uses only the FUTURE window [feat_end, feat_end+horizon_n).
    - Normalizer is the last OBSERVED close (close[feat_end-1]), never a future stat.
    - Feature width read dynamically as len(FEATURE_COLUMNS) — never hardcoded (Pitfall 5).
    - No ATR-threshold skip; no sample_weights (direction-only artifacts).

    Returns (X float32, y float32, meta dict, None).
    """
    if seq_len is None:
        seq_len = SEQ_LEN  # fallback, but callers should supply an M15-appropriate value

    # Determine feature columns: use the configured list if available in df,
    # otherwise fall back to all numeric columns (allows tests to pass a raw OHLCV frame).
    # Never hardcode the count — read dynamically (Pitfall 5).
    available_features = [c for c in FEATURE_COLUMNS if c in df.columns]
    if not available_features:
        # Fallback for test frames that don't have computed features yet.
        # Use all numeric columns present as feature proxies.
        available_features = df.select_dtypes(include="number").columns.tolist()
    n_features = len(available_features)

    X: list = []
    y: list = []

    max_i = len(df) - seq_len - horizon_n

    for i in range(max_i):
        feat_end = i + seq_len  # features: rows [i, feat_end)  — PAST only

        # Future-only bars for the label [feat_end, feat_end+horizon_n)
        fut_hi = float(df["high"].iloc[feat_end : feat_end + horizon_n].max())
        fut_lo = float(df["low"].iloc[feat_end : feat_end + horizon_n].min())

        # Normalizer: last OBSERVED close (never a future bar — Research Pitfall 1 / T-09-03)
        anchor = float(df["close"].iloc[feat_end - 1])

        y_vol = (fut_hi - fut_lo) / anchor  # realized range, normalized by past close

        X.append(df[available_features].iloc[i:feat_end].values)
        y.append(y_vol)

    X_arr = np.array(X, dtype=np.float32)
    y_arr = np.array(y, dtype=np.float32)

    meta = {
        "target": "regime",
        "seq_len": seq_len,
        "horizon_n": horizon_n,
        "n_features": n_features,
        "samples": len(y_arr),
    }

    print("X (regime):", X_arr.shape)
    print("y (regime) — realized-vol label:", y_arr.shape)
    print("y mean:", float(y_arr.mean()) if len(y_arr) else 0.0)

    return X_arr, y_arr, meta, None


def main(
    csv_path=None,
    history_path=None,
    symbol=None,
    out_dir=None,
    scaler_path=None,
    force_features: bool = False,
    target: str = "direction",
    seq_len: int | None = None,
    horizon_n: int = 4,
):
    """
    Main entry point for prepare_sequences.

    Parameters
    ----------
    target : str
        "direction" (default) — existing binary direction pipeline.
        "regime" — M15 resample + leak-free realized-vol label + train-only tercile edges.
    seq_len : int or None
        Feature window. Direction mode uses config.SEQ_LEN (200). Regime mode defaults to 64
        (reduced from 200 per Research Pitfall 2 — 200 M15 bars ≈ 2 days of context on a
        ~103-day dataset; 48-96 M15 bars are the recommended range).
    horizon_n : int
        Number of future M15 bars used to compute the vol label (regime mode only).
        Default 4 (locked in 09-CONTEXT.md D-03). Documents the design choice:
        4 M15 bars = 60 minutes of forward vol range.
    """
    # ── Regime defaults ──────────────────────────────────────────────────────
    # seq_len for regime is deliberately reduced from the direction default (200).
    # Reason (Research Pitfall 2): 200 M15 bars ≈ 2 days of context; with only
    # ~6,700 M15 bars total (~103-day parquet), this over-stretches the window.
    # Default 64 M15 bars (= ~16h of context) is within the recommended 48-96 range.
    REGIME_SEQ_LEN_DEFAULT = 64

    is_regime = target == "regime"

    if is_regime and seq_len is None:
        seq_len = REGIME_SEQ_LEN_DEFAULT

    # ── Resolve paths ─────────────────────────────────────────────────────────
    if out_dir is None:
        if is_regime:
            # Use a distinct subdir so direction baseline is NOT clobbered (T-09-04).
            out_dir = PREPARED_DIR  # default; symbol suffix added after symbol is known
        else:
            out_dir = PREPARED_DIR
    out_dir = Path(out_dir)

    scaler_path = Path(scaler_path) if scaler_path is not None else SCALER_PATH

    if history_path is None:
        if csv_path is not None:
            history_path = Path(csv_path)
        else:
            history_path = _default_history_path(symbol or MT5_SYMBOL)
    else:
        history_path = Path(history_path)

    symbol = _infer_symbol(history_path, symbol)

    if is_regime:
        # Override out_dir to a regime-specific subdir so direction artifacts are preserved.
        # Only override if caller did not pass an explicit out_dir.
        if out_dir == PREPARED_DIR:
            out_dir = PREPARED_DIR.parent / f"{PREPARED_DIR.name}" / f"{symbol}_regime"
            # Flatten: use PREPARED_DIR / "{symbol}_regime"
            out_dir = PREPARED_DIR / f"{symbol}_regime"

    if not history_path.exists():
        raise FileNotFoundError(f"History file not found: {history_path}")

    print(f"Loading history: {history_path}")
    df = load_history(history_path)
    print(f"Raw rows: {len(df)}")

    if is_regime:
        # REGIME-01: Resample M1 → M15 BEFORE feature compute.
        # Features must be computed on the M15 grid — never mix M1 features with M15 label.
        print("Resampling M1 → M15 for regime target...")
        df = resample_m15(df)
        print(f"M15 rows after resample: {len(df)}")

    feature_cache = _feature_cache_path(symbol, out_dir)
    df = prepare_features(
        df,
        cache_path=feature_cache,
        source_path=history_path,
        force_rebuild=force_features,
    )
    print(f"Enriched columns: {list(df.columns)}")

    if is_regime:
        X, y, sequence_meta, sample_weights = make_sequences(
            df, target="regime", seq_len=seq_len, horizon_n=horizon_n
        )
    else:
        X, y, sequence_meta, sample_weights = make_sequences(df)

    shape = X.shape
    n = shape[0]
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)

    print(f"Fitting StandardScaler on {train_end} training samples...")
    scaler = StandardScaler()
    scaler.fit(X[:train_end].reshape(-1, shape[2]))
    X = scaler.transform(X.reshape(-1, shape[2])).reshape(shape)

    os.makedirs(out_dir, exist_ok=True)
    scaler_path.parent.mkdir(parents=True, exist_ok=True)

    _safe_npy_save(out_dir / "X.npy", X)
    _safe_npy_save(out_dir / "y.npy", y)

    if is_regime:
        # ── Regime mode: train-only tercile edges (T-09-05 / Research Pattern 3) ──
        # Fit bucket edges on TRAIN labels ONLY. Val/test/live reuse these frozen edges.
        # Computing on the full dataset would leak label distribution into the gate.
        lo_edge, hi_edge = np.quantile(y[:train_end], [1 / 3, 2 / 3])

        regime_meta = {
            "target": "regime",
            "lo_edge": float(lo_edge),
            "hi_edge": float(hi_edge),
            "seq_len": int(seq_len),
            "horizon_n": int(horizon_n),
            "features": FEATURE_COLUMNS,
            "feature_columns_count": int(len(FEATURE_COLUMNS)),
            "samples": int(n),
            "train_end": int(train_end),
            "val_end": int(val_end),
            "symbol": symbol,
            "history_path": str(history_path),
            "features_cache": str(feature_cache),
            "m15_rows": int(len(df)),
            "label": (
                f"realized vol/range over next {horizon_n} M15 bars "
                f"= (max_high - min_low) / close[feat_end-1]; regression target"
            ),
        }
        with open(out_dir / "regime_meta.json", "w", encoding="utf-8") as handle:
            json.dump(regime_meta, handle, indent=2)

        # Save scaler (regime-specific path in out_dir, not overwriting direction scaler)
        regime_scaler_path = out_dir / "regime_scaler.pkl"
        joblib.dump(scaler, regime_scaler_path)

        # NOTE: sample_weights.npy is NOT saved in regime mode.
        #       The direction weights (|return|/atr) are meaningless for vol regression.
        #       Train without sample weighting (resolved Open Q3 in 09-RESEARCH.md).

        print(f"Prepared REGIME data saved to {out_dir}")
        print(f"  X.npy:              {X.shape}")
        print(f"  y.npy:              {y.shape}")
        print(f"  regime_meta.json:   lo_edge={lo_edge:.6f}, hi_edge={hi_edge:.6f}")
        print(f"  Features:           {len(FEATURE_COLUMNS)} ({', '.join(FEATURE_COLUMNS[:5])}...)")
        print(f"  seq_len:            {seq_len} M15 bars (~{seq_len * 15}min context)")
        print(f"  horizon_n:          {horizon_n} M15 bars (~{horizon_n * 15}min forward vol)")
        print(f"  Train/Val/Test:     {train_end}/{val_end - train_end}/{n - val_end}")

    else:
        # ── Direction mode: original path (UNCHANGED) ──────────────────────────
        _safe_npy_save(out_dir / "sample_weights.npy", sample_weights)
        np.savez(str(out_dir / "sequence_meta.npz"), **sequence_meta)
        joblib.dump(scaler, scaler_path)

        meta = {
            "features": FEATURE_COLUMNS,
            "seq_len": SEQ_LEN,
            "horizon": HORIZON,
            "min_move_atr_mult": MIN_MOVE_ATR_MULT,
            "samples": int(X.shape[0]),
            "seq_shape": [int(X.shape[1]), int(X.shape[2])],
            "positive_rate": float(y.mean()) if len(y) else 0.0,
            "train_end": train_end,
            "val_end": val_end,
            "symbol": symbol,
            "history_path": str(history_path),
            "features_cache": str(feature_cache),
            "featured_rows": int(len(df)),
            "feature_columns_count": int(len(FEATURE_COLUMNS)),
            "label": "1 if close[t+horizon] > close[t], 0 if lower; neutral moves under ATR filter are skipped",
            "smc_features_included": True,
        }
        with open(out_dir / "meta.json", "w", encoding="utf-8") as handle:
            json.dump(meta, handle, indent=2)

        print(f"Prepared data saved to {out_dir}")
        print(f"  X.npy:              {X.shape}")
        print(f"  y.npy:              {y.shape}")
        print(f"  sample_weights.npy: {sample_weights.shape}")
        print(f"  Features:           {len(FEATURE_COLUMNS)} ({', '.join(FEATURE_COLUMNS[:5])}...)")
        print(f"  Train/Val/Test:     {train_end}/{val_end - train_end}/{len(y) - val_end}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Prepare training sequences for FRIDAY model")
    parser.add_argument("--history", type=Path, default=None, help="CSV or Parquet history file")
    parser.add_argument("--csv", type=Path, default=None, help="Legacy alias for --history")
    parser.add_argument("--symbol", type=str, default=MT5_SYMBOL)
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory (default: PREPARED_DIR for direction, PREPARED_DIR/{symbol}_regime for regime)")
    parser.add_argument("--scaler", type=Path, default=SCALER_PATH)
    parser.add_argument("--force-features", action="store_true", help="Rebuild cached feature parquet")
    parser.add_argument(
        "--target",
        choices=["direction", "regime"],
        default="direction",
        help=(
            "Prediction target. 'direction' (default): binary direction label (original path). "
            "'regime': leak-free realized-vol label on M15 grid with train-only tercile edges (REGIME-01)."
        ),
    )
    parser.add_argument(
        "--seq-len",
        type=int,
        default=None,
        help=(
            "Feature window length. Direction default: config.SEQ_LEN (200). "
            "Regime default: 64 (reduced per Research Pitfall 2 — M15 data is ~6700 bars total)."
        ),
    )
    parser.add_argument(
        "--horizon-n",
        type=int,
        default=4,
        help=(
            "Number of future M15 bars for the regime vol label (regime mode only). "
            "Default 4 M15 bars (~60min forward vol; locked in 09-CONTEXT.md D-03)."
        ),
    )
    args = parser.parse_args()
    main(
        csv_path=args.csv,
        history_path=args.history,
        symbol=args.symbol,
        out_dir=args.out_dir,
        scaler_path=args.scaler,
        force_features=args.force_features,
        target=args.target,
        seq_len=args.seq_len,
        horizon_n=args.horizon_n,
    )

"""
Phase 9 — REGIME-02: Offline walk-forward gate harness.

Scores the regime model against the naive recent-range persistence baseline on the
OOS test slice using TRAIN-FROZEN tercile edges (lo_edge/hi_edge from regime_meta.json).

Flow (ORDERING MATTERS — D-05 / REGIME-02):
  1. Load data + frozen edges from regime_meta.json.
  2. Slice the OOS test set (indices >= val_end) — chronological, no shuffle.
  3. Compute the NAIVE baseline FIRST on the test slice:
       naive_pred[i] = rolling(N).max(high) - rolling(N).min(low) / close shifted by 1.
       naive_r2  = r2_score(y_test, naive_pred_test)
       naive_bal = balanced_accuracy_score(bucketize(y_test), bucketize(naive_pred_test))
     Print/report these BEFORE any model work.
  4. If not --dry-run: load the model, predict on X_test (already scaled in X.npy), squeeze.
       model_r2  = r2_score(y_test, pred)
       model_bal = balanced_accuracy_score(bucketize(y_test), bucketize(pred))
  5. VERDICT (sole gate metric — D-05):
       passed = (model_bal >= naive_bal + 0.05)
     R2 is reported but does NOT gate the verdict.
  6. ALWAYS write 09-GATE-RESULT.md — on PASS and FAIL alike (honest-negative ethos).
  7. D-07 guard: warn if symbol is not XAU (FX excluded from live use unless it
     independently clears this gate).
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score, r2_score

# Bootstrap: resolve project root + src/
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _bootstrap import bootstrap  # noqa: E402

PROJECT_ROOT = bootstrap()

# Default paths
DEFAULT_PHASE_DIR = (
    PROJECT_ROOT / ".planning" / "phases" / "09-volatility-regime-retarget"
)
DEFAULT_RESULT_PATH = DEFAULT_PHASE_DIR / "09-GATE-RESULT.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bucketize_factory(lo_edge: float, hi_edge: float):
    """Return a vectorized bucketize closure over the FROZEN train edges."""
    def bucketize(v: np.ndarray) -> np.ndarray:
        v = np.asarray(v, dtype=float)
        return np.where(v <= lo_edge, 0, np.where(v >= hi_edge, 2, 1))
    return bucketize


def _compute_naive_baseline(
    meta: dict,
    prepared_dir: Path,
    test_start_idx: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute the rolling persistence naive baseline on the M15 feature cache.

    Returns: (y_test, naive_pred_test)  — both valid (non-NaN), same length.

    Strategy:
      - Load y.npy (the realized-vol labels from prepare_sequences).
      - For sequence i:
          feat_end = i + seq_len  (exclusive; this is the first FUTURE bar)
          label    = vol over bars [feat_end, feat_end+N)  (future)
          naive    = vol over bars [feat_end-N, feat_end)  (last N observed bars)
                   = (max(high[feat_end-N:feat_end]) - min(low[feat_end-N:feat_end]))
                     / close[feat_end-1]
        This is the rolling persistence baseline: previous-N range predicts next-N range.
        No future bars are used (feat_end-N..feat_end-1 are all feature-window bars).
      - Only OOS test slice (indices >= test_start_idx) is returned.
    """
    horizon_n: int = meta["horizon_n"]
    seq_len: int = meta["seq_len"]
    features_cache: str = meta.get("features_cache", "")

    # Load labels
    y_path = prepared_dir / "y.npy"
    y_all = np.load(str(y_path))

    # Load M15 OHLCV for the naive predictor
    if features_cache and Path(features_cache).exists():
        m15_df = pd.read_parquet(features_cache)
    else:
        # Fallback: try raw history parquet and resample
        raw_path = meta.get("history_path", "")
        if raw_path and Path(raw_path).exists():
            from prepare_sequences import resample_m15  # noqa: F401
            raw_df = pd.read_parquet(raw_path)
            m15_df = resample_m15(raw_df)
        else:
            raise FileNotFoundError(
                f"Cannot locate M15 features cache (tried: {features_cache}). "
                "Run prepare_sequences.py --target regime first."
            )

    # Ensure 'high', 'low', 'close' columns exist
    for col in ("high", "low", "close"):
        if col not in m15_df.columns:
            raise ValueError(
                f"M15 dataframe missing column '{col}'. Available: {list(m15_df.columns)}"
            )

    high  = m15_df["high"].reset_index(drop=True).to_numpy()
    low   = m15_df["low"].reset_index(drop=True).to_numpy()
    close = m15_df["close"].reset_index(drop=True).to_numpy()

    n_seqs = len(y_all)
    naive_pred_all = np.full(n_seqs, np.nan)

    for i in range(n_seqs):
        feat_end = i + seq_len  # first future bar (exclusive feature window)
        start    = feat_end - horizon_n  # first bar of the previous-N window
        if start >= 0 and feat_end <= len(high):
            # Previous-N realized range: the last horizon_n bars of the feature window
            prev_hi  = high[start:feat_end].max()
            prev_lo  = low[start:feat_end].min()
            anchor   = close[feat_end - 1]  # last observed close
            naive_pred_all[i] = (prev_hi - prev_lo) / anchor

    y_test          = y_all[test_start_idx:]
    naive_pred_test = naive_pred_all[test_start_idx:]

    # Drop any NaN positions from both
    valid_mask = np.isfinite(naive_pred_test) & np.isfinite(y_test)
    if not np.any(valid_mask):
        raise ValueError("No valid (non-NaN) naive baseline values in OOS test slice.")

    return y_test[valid_mask], naive_pred_test[valid_mask]


def _write_result(
    result_path: Path,
    symbol: str,
    meta: dict,
    naive_r2: float,
    naive_bal: float,
    model_r2: float | None,
    model_bal: float | None,
    n_test: int,
    passed: bool,
    dry_run: bool,
    notes: str = "",
) -> None:
    """Write 09-GATE-RESULT.md with the honest PASS/FAIL verdict."""
    verdict = "PASS" if passed else "FAIL"
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    model_r2_str  = f"{model_r2:.4f}"  if model_r2  is not None else "N/A (dry-run)"
    model_bal_str = f"{model_bal:.4f}" if model_bal is not None else "N/A (dry-run)"

    margin_bal = (model_bal - naive_bal) if model_bal is not None else None
    margin_r2  = (model_r2  - naive_r2)  if model_r2  is not None else None

    margin_bal_str = f"{margin_bal:+.4f}" if margin_bal is not None else "N/A"
    margin_r2_str  = f"{margin_r2:+.4f}"  if margin_r2  is not None else "N/A"
    bal_pass_str   = (
        "YES (>= +0.05)" if (margin_bal is not None and margin_bal >= 0.05)
        else "NO" if margin_bal is not None
        else "N/A"
    )

    run_type = "dry-run (baseline only)" if dry_run else "full model run"

    content = f"""# Phase 9 — Regime Gate Result

**Date:** {date_str}
**Run type:** {run_type}
**Symbol:** {symbol}
**Gated requirement:** REGIME-02 / D-05

---

## VERDICT: {verdict}

{"*Dry-run mode: no model loaded. Gate written as FAIL (no model prediction).* " if dry_run else ""}

---

## Gate Numbers

| Metric | Naive Baseline | Model | Margin | Required | Pass? |
|--------|---------------|-------|--------|----------|-------|
| **balanced-acc (GATE)** | {naive_bal:.4f} | {model_bal_str} | {margin_bal_str} | >= +0.05 | {bal_pass_str} |
| R2 (reported only) | {naive_r2:.4f} | {model_r2_str} | {margin_r2_str} | +0.05 (informational) | — |

**Verdict rule (D-05, sole metric):** `passed = (model_bal >= naive_bal + 0.05)`
R2 is reported alongside but does NOT gate the verdict.

---

## Conditions

| Property | Value |
|----------|-------|
| OOS test size (after NaN drop) | {n_test} sequences |
| seq_len | {meta['seq_len']} M15 bars |
| horizon_n | {meta['horizon_n']} M15 bars |
| lo_edge (frozen train tercile) | {meta['lo_edge']:.6f} |
| hi_edge (frozen train tercile) | {meta['hi_edge']:.6f} |
| train_end | {meta['train_end']} |
| val_end | {meta['val_end']} |
| Total sequences | {meta['samples']} |

---

## Interpretation

### Naive Baseline
The naive persistence baseline predicts next-N realized vol/range = previous-N realized vol/range
(rolling, shifted, leak-safe). Expected OLS R2 ≈ 0.301 on XAU M15 per the project's own
walk-forward study. Measured here: **{naive_r2:.4f}**.

### Model
{"*No model scoring in dry-run mode.*" if dry_run else f"Model OOS balanced-accuracy: **{model_bal_str}** vs naive: **{naive_bal:.4f}** (margin: {margin_bal_str})."}

### Verdict: {verdict}
{"This is a dry-run result (no model). The gate records FAIL because no model prediction was scored." if dry_run else
 f"The model {'BEATS' if passed else 'DOES NOT BEAT'} the naive baseline by the pre-registered +0.05 balanced-accuracy margin."}

{"A FAIL result means: the regime model is NOT cleared for live sizing use. 09-05 can still wire the plumbing but regime_mult stays 1.0 until a future run clears this gate. This is an honest negative (Phase-2 ethos) — no threshold relaxation, no fabricated pass." if not passed else
 "A PASS result means: the XAUUSDm regime model is cleared for live sizing use (regime_mult active). FX symbols still require independent gate clearance (D-07)."}

---

## FX Scope Note (D-07)

XAUUSDm is the only symbol cleared for live regime use on a PASS. FX symbols (EURUSDm,
GBPUSDm, etc.) are EXCLUDED from live use unless they independently clear this same gate.
The project's walk-forward OOS study found approximately no vol signal on EURUSD.

---

{("## Notes\\n\\n" + notes + "\\n\\n---\\n\\n") if notes else ""}*Honest gate result. No threshold relaxation, no fabricated numbers.*
*Pre-registered margin: +0.05 balanced-accuracy (sole gate metric, D-05 / REGIME-02)*
*See: .planning/phases/09-volatility-regime-retarget/09-GATE-PREREG.md*
"""

    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(content, encoding="utf-8")
    print(f"[gate_regime] Result written to: {result_path}")


# ---------------------------------------------------------------------------
# Main gate logic
# ---------------------------------------------------------------------------

def run_gate(
    symbol: str = "XAUUSDm",
    prepared_dir: Path | None = None,
    model_path: Path | None = None,
    result_path: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Run the regime gate.

    Returns a dict with keys: naive_r2, naive_bal, model_r2, model_bal, passed, verdict.
    """
    # D-07 guard
    if not symbol.upper().startswith("XAU"):
        print(
            f"[gate_regime] NOTICE: symbol={symbol} does not start with XAU. "
            "FX symbols are EXCLUDED from live use unless they independently clear this gate "
            "(D-07). Running the gate for informational purposes only."
        )

    # Resolve paths
    if prepared_dir is None:
        prepared_dir = PROJECT_ROOT / "data" / "prepared" / f"{symbol}_regime"
    prepared_dir = Path(prepared_dir)

    if model_path is None:
        model_path = PROJECT_ROOT / "models" / symbol / "regime_model.keras"
    model_path = Path(model_path)

    if result_path is None:
        result_path = DEFAULT_RESULT_PATH
    result_path = Path(result_path)

    # Load meta
    meta_path = prepared_dir / "regime_meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(
            f"regime_meta.json not found at {meta_path}. "
            "Run: python scripts/prepare_sequences.py --target regime --symbol {symbol}"
        )
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    lo_edge: float = meta["lo_edge"]
    hi_edge: float = meta["hi_edge"]
    val_end: int   = meta["val_end"]

    bucketize = _bucketize_factory(lo_edge, hi_edge)

    # -----------------------------------------------------------------------
    # STEP 3: Compute NAIVE BASELINE FIRST (ordering is the contract)
    # -----------------------------------------------------------------------
    print(f"\n[gate_regime] === NAIVE BASELINE COMPUTATION (symbol={symbol}) ===")
    print(f"[gate_regime] Loading prepared data from: {prepared_dir}")
    print(f"[gate_regime] regime_meta: lo_edge={lo_edge:.6f}, hi_edge={hi_edge:.6f}, "
          f"seq_len={meta['seq_len']}, horizon_n={meta['horizon_n']}, "
          f"val_end={val_end}")

    y_test, naive_pred_test = _compute_naive_baseline(
        meta=meta,
        prepared_dir=prepared_dir,
        test_start_idx=val_end,
    )
    n_test = len(y_test)

    naive_r2  = float(r2_score(y_test, naive_pred_test))
    naive_bal = float(balanced_accuracy_score(
        bucketize(y_test), bucketize(naive_pred_test)
    ))

    print(f"[gate_regime] Naive baseline — OOS test size: {n_test}")
    print(f"[gate_regime] Naive baseline — R2:  {naive_r2:.4f}  (expected ~0.301)")
    print(f"[gate_regime] Naive baseline — balanced-acc: {naive_bal:.4f}")

    # -----------------------------------------------------------------------
    # STEP 4: Model scoring (AFTER baseline — ordering enforced)
    # -----------------------------------------------------------------------
    model_r2  = None
    model_bal = None
    passed    = False
    notes     = ""

    if dry_run:
        print(f"\n[gate_regime] === MODEL SCORING SKIPPED (--dry-run) ===")
        print(f"[gate_regime] model path would be: {model_path}")
        print(f"[gate_regime] model: not loaded in dry-run mode.")
        notes = "Dry-run: model not loaded. Gate records FAIL (no model prediction)."
        passed = False
    else:
        print(f"\n[gate_regime] === MODEL SCORING (symbol={symbol}) ===")
        if not model_path.exists():
            notes = (
                f"Model file not found at {model_path}. "
                "Run: python scripts/retrain_full.py --regime --symbol {symbol}"
            )
            print(f"[gate_regime] ERROR: {notes}")
            passed = False
        else:
            # Load sequences for X_test.
            # NOTE: X.npy is already StandardScaler-transformed by prepare_sequences.py
            # before being saved. Do NOT re-apply the scaler here — the model was trained
            # on the pre-scaled X.npy, so inference must use the same pre-scaled data.
            x_path = prepared_dir / "X.npy"
            X_all = np.load(str(x_path))
            X_test_scaled = X_all[val_end:]

            # Load model and predict
            print(f"[gate_regime] Loading model: {model_path}")
            import tensorflow as tf  # noqa: F401
            model = tf.keras.models.load_model(str(model_path))
            print(f"[gate_regime] model: loaded successfully.")
            print(f"[gate_regime] model: running inference on {len(X_test_scaled)} test sequences...")

            raw_pred = model.predict(X_test_scaled, verbose=0)
            pred = raw_pred.squeeze()

            # Align with the valid naive mask (y_test is already subset from NaN drop)
            # We need to apply the same valid_mask logic to pred
            # Re-derive valid_mask from the full test y vs naive
            y_all  = np.load(str(prepared_dir / "y.npy"))
            y_test_full = y_all[val_end:]

            # Recompute naive for full test (without mask) to get valid indices
            naive_pred_full = _get_naive_pred_full(meta, prepared_dir, val_end)
            valid_mask = np.isfinite(naive_pred_full) & np.isfinite(y_test_full)

            if len(pred) != len(y_test_full):
                # If pred length differs, use common valid indices
                min_len = min(len(pred), len(y_test_full))
                valid_mask = valid_mask[:min_len]
                pred_valid = pred[:min_len][valid_mask]
                y_valid    = y_test_full[:min_len][valid_mask]
            else:
                pred_valid = pred[valid_mask]
                y_valid    = y_test_full[valid_mask]

            model_r2  = float(r2_score(y_valid, pred_valid))
            model_bal = float(balanced_accuracy_score(
                bucketize(y_valid), bucketize(pred_valid)
            ))

            print(f"[gate_regime] model: R2  = {model_r2:.4f}")
            print(f"[gate_regime] model: balanced-acc = {model_bal:.4f}")

            # VERDICT — sole gate metric (D-05)
            passed = model_bal >= naive_bal + 0.05
            margin_bal = model_bal - naive_bal
            print(f"\n[gate_regime] === VERDICT ===")
            print(f"[gate_regime] model_bal ({model_bal:.4f}) >= naive_bal ({naive_bal:.4f}) + 0.05 "
                  f"({naive_bal + 0.05:.4f}): {margin_bal:+.4f} -> {'PASS' if passed else 'FAIL'}")

    # STEP 6: Always write result (honest-negative ethos)
    _write_result(
        result_path=result_path,
        symbol=symbol,
        meta=meta,
        naive_r2=naive_r2,
        naive_bal=naive_bal,
        model_r2=model_r2,
        model_bal=model_bal,
        n_test=n_test,
        passed=passed,
        dry_run=dry_run,
        notes=notes,
    )

    verdict = "PASS" if passed else "FAIL"
    print(f"\n[gate_regime] FINAL VERDICT: {verdict}")
    return {
        "naive_r2":   naive_r2,
        "naive_bal":  naive_bal,
        "model_r2":   model_r2,
        "model_bal":  model_bal,
        "passed":     passed,
        "verdict":    verdict,
        "n_test":     n_test,
    }


def _get_naive_pred_full(meta: dict, prepared_dir: Path, val_end: int) -> np.ndarray:
    """Helper: return naive pred array aligned to y[val_end:] indices (may contain NaN)."""
    horizon_n      = meta["horizon_n"]
    seq_len        = meta["seq_len"]
    features_cache = meta.get("features_cache", "")

    y_all  = np.load(str(prepared_dir / "y.npy"))
    n_seqs = len(y_all)
    n_test = n_seqs - val_end

    if features_cache and Path(features_cache).exists():
        m15_df = pd.read_parquet(features_cache)
    else:
        raise FileNotFoundError(f"Features cache not found: {features_cache}")

    high  = m15_df["high"].reset_index(drop=True).to_numpy()
    low   = m15_df["low"].reset_index(drop=True).to_numpy()
    close = m15_df["close"].reset_index(drop=True).to_numpy()

    naive_pred_test = np.full(n_test, np.nan)
    for j, i in enumerate(range(val_end, n_seqs)):
        feat_end = i + seq_len
        start    = feat_end - horizon_n
        if start >= 0 and feat_end <= len(high):
            prev_hi = high[start:feat_end].max()
            prev_lo = low[start:feat_end].min()
            anchor  = close[feat_end - 1]
            naive_pred_test[j] = (prev_hi - prev_lo) / anchor

    return naive_pred_test


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Phase 9 REGIME-02 gate: score regime model vs naive baseline on OOS test slice."
    )
    parser.add_argument(
        "--symbol", default="XAUUSDm",
        help="Symbol to gate (default: XAUUSDm). FX symbols print a D-07 notice."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Compute and print naive baseline only; skip model loading; write FAIL result."
    )
    parser.add_argument(
        "--prepared-dir", default=None,
        help="Path to prepared regime dir (default: data/prepared/{symbol}_regime)."
    )
    parser.add_argument(
        "--model", default=None,
        help="Path to regime model .keras (default: models/{symbol}/regime_model.keras)."
    )
    parser.add_argument(
        "--result", default=None,
        help="Path to write 09-GATE-RESULT.md (default: .planning/.../09-GATE-RESULT.md)."
    )
    args = parser.parse_args()

    prepared_dir = Path(args.prepared_dir) if args.prepared_dir else None
    model_path   = Path(args.model)        if args.model        else None
    result_path  = Path(args.result)       if args.result       else None

    result = run_gate(
        symbol=args.symbol,
        prepared_dir=prepared_dir,
        model_path=model_path,
        result_path=result_path,
        dry_run=args.dry_run,
    )
    # Exit 0 always — gate records verdict in the file; the script itself succeeds
    sys.exit(0)


if __name__ == "__main__":
    main()

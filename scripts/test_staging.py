import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import bootstrap

bootstrap()

import joblib
import numpy as np
import pandas as pd

from mt5_ai.config import FEATURE_COLUMNS, PREPARED_DIR, SCALER_PATH
from prepare_sequences import main as prepare_main


def make_csv(path, rows=500):
    rng = np.random.default_rng(260426)
    close = 2000.0 + np.cumsum(rng.normal(0, 6, rows))
    half_range = rng.uniform(2.0, 7.0, rows)
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    pd.DataFrame(
        {
            "time": pd.date_range("2025-01-01", periods=rows, freq="min"),
            "open": open_,
            "high": close + half_range,
            "low": close - half_range,
            "close": close,
            "volume": rng.integers(100, 2000, rows),
        }
    ).to_csv(path, index=False)


def mtime(path):
    return path.stat().st_mtime if path.exists() else None


def test_staging_isolation():
    prod_x = PREPARED_DIR / "X.npy"
    before_x = mtime(prod_x)
    before_scaler = mtime(SCALER_PATH)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        csv_path = tmp / "history.csv"
        out_dir = tmp / "prepared_v2"
        scaler_path = tmp / "scaler_v2.save"
        make_csv(csv_path)

        prepare_main(csv_path=csv_path, out_dir=out_dir, scaler_path=scaler_path)

        for name in ("X.npy", "y.npy", "sequence_meta.npz", "meta.json"):
            assert (out_dir / name).exists(), f"Missing staged artifact: {name}"
        assert scaler_path.exists(), "Missing staged scaler"
        assert mtime(prod_x) == before_x, "Production X.npy was modified"
        assert mtime(SCALER_PATH) == before_scaler, "Production scaler.save was modified"


def test_staged_artifacts_valid():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        csv_path = tmp / "history.csv"
        out_dir = tmp / "prepared_v2"
        scaler_path = tmp / "scaler_v2.save"
        make_csv(csv_path)

        prepare_main(csv_path=csv_path, out_dir=out_dir, scaler_path=scaler_path)

        x = np.load(out_dir / "X.npy")
        y = np.load(out_dir / "y.npy")
        scaler = joblib.load(scaler_path)
        meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))

        assert x.ndim == 3, f"Unexpected X shape: {x.shape}"
        assert x.shape[0] == y.shape[0] == meta["samples"]
        assert x.shape[2] == len(FEATURE_COLUMNS)
        assert scaler.n_features_in_ == len(FEATURE_COLUMNS)
        assert len(scaler.mean_) == len(FEATURE_COLUMNS)


def main():
    tests = [test_staging_isolation, test_staged_artifacts_valid]
    passed = 0
    for test in tests:
        test()
        print(f"{test.__name__}: PASS")
        passed += 1
    print(f"staging_tests_ok {passed}/{len(tests)}")


if __name__ == "__main__":
    main()

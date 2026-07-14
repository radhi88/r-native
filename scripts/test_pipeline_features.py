import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import bootstrap

bootstrap()

import numpy as np
import pandas as pd

from mt5_ai.config import FEATURE_COLUMNS
from prepare_sequences import add_features


def make_df(rows=300):
    rng = np.random.default_rng(260426)
    close = 2000.0 + np.cumsum(rng.normal(0, 4, rows))
    high = close + rng.uniform(1.0, 5.0, rows)
    low = close - rng.uniform(1.0, 5.0, rows)
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = rng.integers(100, 2000, rows)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def main():
    raw = make_df()
    featured = add_features(raw)

    missing = [column for column in FEATURE_COLUMNS if column not in featured.columns]
    assert not missing, f"Missing feature columns: {missing}"

    assert featured["adx"].between(0, 100).all(), "ADX must be in [0, 100]"
    assert featured["mfi"].between(0, 100).all(), "MFI must be in [0, 100]"

    old_adx_proxy = ((raw["high"] - raw["low"]) / raw["close"]).rolling(14).mean().bfill().fillna(0)
    typical_price = (raw["high"] + raw["low"] + raw["close"]) / 3.0
    old_mfi_proxy = (typical_price * raw["volume"]).rolling(14).mean().bfill().fillna(0)

    adx_delta = float((featured["adx"] - old_adx_proxy).abs().sum())
    mfi_delta = float((featured["mfi"] - old_mfi_proxy).abs().sum())
    assert adx_delta > 1.0, "ADX still resembles the old range proxy"
    assert mfi_delta > 1000.0, "MFI still resembles the old raw money-flow proxy"

    print("pipeline_features_ok")
    print(f"feature_count={len(FEATURE_COLUMNS)} adx_delta={adx_delta:.2f} mfi_delta={mfi_delta:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import re
import sys

import numpy as np
import pandas as pd

from _bootstrap import bootstrap

bootstrap()

from mt5_ai.config import RAW_DATA_DIR, TRAINING_DATA_CSV


INPUT_PATTERN = "mt5_history_*.csv"


def parse_line(s):
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    return [part.strip() for part in s.split(",")]


def find_input_file():
    files = sorted(RAW_DATA_DIR.glob(INPUT_PATTERN))
    if not files:
        print("No files matching", RAW_DATA_DIR / INPUT_PATTERN)
        sys.exit(1)
    return files[0]


def build_dataframe(path):
    rows = []
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line or re.fullmatch(r"\d+", line):
                continue

            parts = parse_line(line)
            if len(parts) < 6:
                continue

            timestamp = parts[0]
            try:
                open_v = float(parts[1])
                high_v = float(parts[2])
                low_v = float(parts[3])
                close_v = float(parts[4])
                tick_vol = float(parts[5])
            except Exception:
                continue

            rows.append((int(float(timestamp)), open_v, high_v, low_v, close_v, tick_vol))

    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "tick_volume"])
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df.sort_values("time").reset_index(drop=True)


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(alpha=1 / period, adjust=False).mean()
    ma_down = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = ma_up / (ma_down + 1e-12)
    return 100 - (100 / (1 + rs))


def atr(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(window=period, min_periods=1).mean()


def main():
    infile = find_input_file()
    print("Using input file:", infile)

    df = build_dataframe(infile)
    print("Parsed rows:", len(df))
    if len(df) == 0:
        print("No valid rows parsed.")
        return

    df["EMA_fast"] = ema(df["close"], 12)
    df["EMA_slow"] = ema(df["close"], 26)
    df["RSI"] = rsi(df["close"], 14)
    df["ATR"] = atr(df, 14)
    df["close_next"] = df["close"].shift(-1)
    df["direction"] = np.sign(df["close_next"] - df["close"]).fillna(0).astype(int)

    out_cols = [
        "time",
        "open",
        "high",
        "low",
        "close",
        "tick_volume",
        "EMA_fast",
        "EMA_slow",
        "RSI",
        "ATR",
        "direction",
    ]
    df_out = df[out_cols].dropna().reset_index(drop=True)
    df_out.to_csv(TRAINING_DATA_CSV, index=False)

    print("Rows after dropna:", len(df_out))
    print("Saved cleaned CSV to", TRAINING_DATA_CSV)


if __name__ == "__main__":
    main()

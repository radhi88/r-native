def _column(df, name):
    columns = {column.lower(): column for column in df.columns}
    if name.lower() not in columns:
        raise KeyError(f"Missing required column: {name}")
    return columns[name.lower()]


def detect_regime(df):
    df = df.copy()

    atr = df[_column(df, "atr")]
    close = df[_column(df, "close")]

    if {"ema_fast", "ema_slow"}.issubset({column.lower() for column in df.columns}):
        ema_fast = df[_column(df, "ema_fast")]
        ema_slow = df[_column(df, "ema_slow")]
        trend_strength = (ema_fast - ema_slow).abs()
    elif "trend" in {column.lower() for column in df.columns}:
        trend_strength = df[_column(df, "trend")].abs()
    else:
        trend_strength = close.diff().abs()

    vol = atr / close
    df["regime_trend"] = (trend_strength > trend_strength.rolling(50).mean()).astype(int)
    df["regime_range"] = (vol < vol.rolling(50).mean()).astype(int)
    df["regime_high_vol"] = (vol > vol.rolling(50).mean() * 1.5).astype(int)

    return df

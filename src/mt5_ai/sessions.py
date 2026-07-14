import pandas as pd


def add_sessions(df):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    hour = df["time"].dt.hour

    df["session_asia"] = ((hour >= 0) & (hour < 7)).astype(int)
    df["session_london"] = ((hour >= 7) & (hour < 13)).astype(int)
    df["session_ny"] = ((hour >= 13) & (hour < 20)).astype(int)
    df["session_overlap"] = (
        ((hour >= 12) & (hour < 14)) | ((hour >= 6) & (hour < 7))
    ).astype(int)

    return df

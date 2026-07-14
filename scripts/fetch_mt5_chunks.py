from datetime import datetime, timedelta

import MetaTrader5 as mt5
import pandas as pd

from _bootstrap import bootstrap

bootstrap()

from mt5_ai.config import CSV_HISTORY, MT5_SYMBOL


TIMEFRAME = mt5.TIMEFRAME_M1
TOTAL_BARS = 50000


def connect():
    if not mt5.initialize():
        raise SystemExit(mt5.last_error())

    if not mt5.symbol_select(MT5_SYMBOL, True):
        raise SystemExit(f"Failed to select {MT5_SYMBOL}")

    print("MT5 initialized and symbol selected")


def shutdown():
    mt5.shutdown()


def fetch_by_range(symbol, timeframe, bars):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 1)
    if rates is None:
        return None

    end_time = datetime.now()
    start_time = end_time - timedelta(minutes=bars)
    return mt5.copy_rates_range(symbol, timeframe, start_time, end_time)


def main():
    connect()
    rates = fetch_by_range(MT5_SYMBOL, TIMEFRAME, TOTAL_BARS)

    print("rates is None?", rates is None)
    print("len:", 0 if rates is None else len(rates))

    if rates is None or len(rates) == 0:
        print("No data returned. Force history download in MT5, then retry.")
        shutdown()
        return

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.to_csv(CSV_HISTORY, index=False)
    print("Saved rows:", len(df))
    print("File:", CSV_HISTORY)

    shutdown()


if __name__ == "__main__":
    main()

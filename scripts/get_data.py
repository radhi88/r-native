from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd

from _bootstrap import bootstrap

bootstrap()

from mt5_ai.config import DEFAULT_SYMBOLS, MT5_SYMBOL, MT5_TERMINAL_PATH, RAW_DATA_DIR


TIMEFRAME = mt5.TIMEFRAME_M1
SECONDS_PER_M1_BAR = 60


def _last_error_text() -> str:
    code, message = mt5.last_error()
    return f"{code}: {message}"


def _parse_symbols(value: str) -> list[str]:
    symbols = [symbol.strip() for symbol in str(value or "").split(",")]
    return [symbol for symbol in symbols if symbol]


def _connect() -> int:
    if not mt5.initialize(path=MT5_TERMINAL_PATH):
        if not mt5.initialize():
            raise SystemExit(f"MT5 init failed: {_last_error_text()}")

    terminal_info = mt5.terminal_info()
    maxbars = getattr(terminal_info, "maxbars", 0) if terminal_info else 0
    print("MT5 connected")
    print("terminal max bars:", maxbars or "unknown")
    return int(maxbars or 0)


def _ensure_symbol(symbol: str) -> None:
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"Failed to select {symbol}: {_last_error_text()}")

    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"Symbol not found in MT5: {symbol}")


def _requested_bar_slots(years: float) -> int:
    days = max(float(years), 0.0) * 365.0
    return int((days * 24 * 60 * 60) / SECONDS_PER_M1_BAR)


def _fetch_rates(symbol: str, maxbars: int, years: float):
    requested_slots = _requested_bar_slots(years)

    if maxbars and requested_slots > maxbars:
        fetch_bars = max(maxbars - 1, 1)
        print(
            f"{symbol}: requested {years:g} years of M1 data, but MT5 is limited "
            f"to {maxbars} bars. Fetching the latest {fetch_bars} bars instead."
        )
        return mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, fetch_bars)

    end = datetime.now()
    start = end - timedelta(days=365 * float(years))
    rates = mt5.copy_rates_range(symbol, TIMEFRAME, start, end)
    if rates is not None and len(rates) > 0:
        return rates

    print(f"{symbol}: range fetch failed: {_last_error_text()}")
    fallback_bars = maxbars or requested_slots
    print(f"{symbol}: trying latest {fallback_bars} bars instead.")
    return mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, fallback_bars)


def _clean_rates(rates) -> pd.DataFrame:
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.drop_duplicates(subset=["time"])
    return df.sort_values("time").reset_index(drop=True)


def _history_path(symbol: str, out_dir: Path) -> Path:
    return out_dir / f"{symbol}_history.parquet"


def _save_symbol(symbol: str, maxbars: int, years: float, out_dir: Path) -> bool:
    t0 = time.perf_counter()
    try:
        _ensure_symbol(symbol)
        rates = _fetch_rates(symbol, maxbars=maxbars, years=years)
        if rates is None or len(rates) == 0:
            print(f"WARNING {symbol}: no data returned. Last MT5 error: {_last_error_text()}")
            return False

        df = _clean_rates(rates)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = _history_path(symbol, out_dir)
        df.to_parquet(path, index=False)

        start = df["time"].iloc[0].date()
        end = df["time"].iloc[-1].date()
        elapsed = time.perf_counter() - t0
        print(f"{symbol}: {len(df):,} bars | {start} → {end} | {elapsed:.1f}s")
        print(f"{symbol}: saved {path}")
        return True
    except Exception as exc:
        print(f"WARNING {symbol}: skipped: {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch raw MT5 M1 OHLCV history to Parquet")
    parser.add_argument(
        "--symbols",
        default=MT5_SYMBOL,
        help=(
            "Comma-separated symbols. Example: "
            f"{','.join(DEFAULT_SYMBOLS)}"
        ),
    )
    parser.add_argument("--years", type=float, default=3.0, help="Approximate years of M1 history to request")
    parser.add_argument("--out-dir", type=Path, default=RAW_DATA_DIR, help="Output directory for Parquet files")
    args = parser.parse_args()

    symbols = _parse_symbols(args.symbols)
    if not symbols:
        raise SystemExit("No symbols provided")
    if args.years <= 0:
        raise SystemExit("--years must be greater than 0")

    maxbars = _connect()
    try:
        total_t0 = time.perf_counter()
        ok_count = 0
        for symbol in symbols:
            if _save_symbol(symbol, maxbars=maxbars, years=args.years, out_dir=args.out_dir):
                ok_count += 1

        print(f"Completed: {ok_count}/{len(symbols)} symbols saved")
        print(f"Total elapsed: {time.perf_counter() - total_t0:.1f}s")
        if ok_count == 0:
            raise SystemExit(1)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()

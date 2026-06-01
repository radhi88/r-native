"""Tests for strategies/supply_zone_cot: zone-touch + COT gate logic."""
import os, sys, types, importlib.util, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)


def _pkg():
    if "r_native" not in sys.modules:
        p = types.ModuleType("r_native"); p.__path__ = [REPO]; sys.modules["r_native"] = p
def _load(n, path):
    s = importlib.util.spec_from_file_location(n, path)
    m = importlib.util.module_from_spec(s); sys.modules[n] = m; s.loader.exec_module(m)
    parent, _, child = n.rpartition(".")
    if parent in sys.modules: setattr(sys.modules[parent], child, m)
    return m

_pkg()
_load("r_native.strategy_types", os.path.join(REPO, "strategy_types.py"))
_load("r_native.smc_engine",     os.path.join(REPO, "smc_engine.py"))
sz = _load("strategies_supply_zone_cot",
            os.path.join(REPO, "strategies", "supply_zone_cot.py"))


# ─── cot_index ───────────────────────────────────────────────────
def test_cot_index_range():
    vals = list(range(100))
    idx = sz.cot_index(vals, lookback=52)
    assert np.isnan(idx[0]) and np.isnan(idx[50])
    assert idx[51] == 100.0       # equals max of its window
    assert idx[80] == 100.0       # still equals max in rolling window
    assert all(0 <= v <= 100 for v in idx[51:] if not np.isnan(v))
    print("OK test_cot_index_range")


def test_cot_index_flat_returns_50():
    idx = sz.cot_index([5.0] * 60, lookback=52)
    valid = [v for v in idx if not np.isnan(v)]
    assert all(v == 50.0 for v in valid)
    print("OK test_cot_index_flat_returns_50")


# ─── cot_regime ──────────────────────────────────────────────────
def test_cot_regime_bullish_setup():
    # Commercials extreme bullish + Retail extreme bearish
    assert sz.cot_regime(90.0, 10.0) == "BULLISH_SETUP"
    assert sz.cot_regime(80.0, 20.0) == "BULLISH_SETUP"
    print("OK test_cot_regime_bullish_setup")


def test_cot_regime_bearish_setup():
    assert sz.cot_regime(15.0, 85.0) == "BEARISH_SETUP"
    print("OK test_cot_regime_bearish_setup")


def test_cot_regime_neutral_when_aligned():
    # Both at the same end -> neutral (no divergence)
    assert sz.cot_regime(90.0, 90.0) == "NEUTRAL"
    assert sz.cot_regime(50.0, 50.0) == "NEUTRAL"
    print("OK test_cot_regime_neutral_when_aligned")


def test_cot_regime_nan_safe():
    assert sz.cot_regime(float("nan"), 50.0) == "NEUTRAL"
    print("OK test_cot_regime_nan_safe")


# ─── regime_for_date ────────────────────────────────────────────
def test_regime_for_date_picks_latest_prior():
    cot = [
        {"date": "2025-01-07", "comm_idx": 90.0, "noncomm_idx": 10.0},
        {"date": "2025-01-14", "comm_idx": 15.0, "noncomm_idx": 85.0},
        {"date": "2025-01-21", "comm_idx": 50.0, "noncomm_idx": 50.0},
    ]
    # Date between week 1 and 2 -> use week 1
    import datetime as dt
    ts = int(dt.datetime(2025, 1, 10, 0, 0, tzinfo=dt.timezone.utc).timestamp())
    assert sz.regime_for_date(cot, ts) == "BULLISH_SETUP"
    # Exactly on week 2 -> use week 2
    ts2 = int(dt.datetime(2025, 1, 14, 0, 0, tzinfo=dt.timezone.utc).timestamp())
    assert sz.regime_for_date(cot, ts2) == "BEARISH_SETUP"
    # Before any report -> neutral
    ts0 = int(dt.datetime(2024, 12, 31, 0, 0, tzinfo=dt.timezone.utc).timestamp())
    assert sz.regime_for_date(cot, ts0) == "NEUTRAL"
    print("OK test_regime_for_date_picks_latest_prior")


# ─── load_cot_weekly: simulated CFTC csv ────────────────────────
def test_load_cot_weekly_from_synthetic_csv():
    csv_text = (
        '"Market and Exchange Names","As of Date in Form YYMMDD",'
        '"As of Date in Form YYYY-MM-DD","CFTC Contract Market Code",'
        '"CFTC Market Code in Initials","CFTC Region Code","CFTC Commodity Code",'
        '"Open Interest (All)","Noncommercial Positions-Long (All)",'
        '"Noncommercial Positions-Short (All)","Noncommercial Positions-Spreading (All)",'
        '"Commercial Positions-Long (All)","Commercial Positions-Short (All)"\n'
        '"GOLD - COMMODITY EXCHANGE INC.",240102,2024-01-02,001602,CMX,00,001,'
        '500000,200000,100000,50000,150000,250000\n'
        '"GOLD - COMMODITY EXCHANGE INC.",240109,2024-01-09,001602,CMX,00,001,'
        '510000,210000,110000,55000,160000,260000\n'
    )
    p = os.path.join(tempfile.mkdtemp(), "cot.txt")
    open(p, "w").write(csv_text)
    rows = sz.load_cot_weekly(p, "GOLD")
    assert len(rows) == 2
    assert rows[0]["comm_net"] == 150000 - 250000        # -100000
    assert rows[0]["noncomm_net"] == 200000 - 100000     # +100000
    # Index is NaN for the first 51 entries; with 2 entries here it's NaN
    assert np.isnan(rows[0]["comm_idx"])
    print("OK test_load_cot_weekly_from_synthetic_csv")


# ─── End-to-end backtest smoke ──────────────────────────────────
def _bars(price_path):
    return [{"time": 1700000000 + i * 900, "open": p, "high": p + 0.5,
              "low": p - 0.5, "close": p, "volume": 100}
            for i, p in enumerate(price_path)]


def test_backtest_returns_well_formed_summary():
    rng = np.random.default_rng(0)
    prices = 100 + np.cumsum(rng.normal(0, 0.6, 300))
    bars = _bars(prices)
    res = sz.backtest(bars, cot_weekly=None, require_cot=False)
    assert "summary" in res and "trades" in res
    s = res["summary"]
    for k in ("trades", "wins", "losses", "win_rate", "profit_factor",
               "net_pnl", "skipped_by_cot", "exit_breakdown"):
        assert k in s
    print(f"OK test_backtest_returns_well_formed_summary "
          f"({s['trades']} trades on 300 random bars)")


def test_backtest_cot_gating_blocks_entries():
    """A persistently NEUTRAL COT regime should block all entries when
    require_cot=True (no BEARISH/BULLISH_SETUP weeks ever occur)."""
    rng = np.random.default_rng(0)
    prices = 100 + np.cumsum(rng.normal(0, 0.6, 400))
    bars = _bars(prices)
    # Build a COT series that stays exactly neutral
    cot = [{"date": f"2024-{m:02d}-{d:02d}", "comm_idx": 50.0, "noncomm_idx": 50.0}
           for m in range(1, 13) for d in (5, 12, 19, 26)]
    res = sz.backtest(bars, cot_weekly=cot, require_cot=True)
    # No trades possible, but skips should be tracked
    assert res["summary"]["trades"] == 0
    print(f"OK test_backtest_cot_gating_blocks_entries "
          f"({res['summary']['skipped_by_cot']} entries blocked)")


if __name__ == "__main__":
    test_cot_index_range()
    test_cot_index_flat_returns_50()
    test_cot_regime_bullish_setup()
    test_cot_regime_bearish_setup()
    test_cot_regime_neutral_when_aligned()
    test_cot_regime_nan_safe()
    test_regime_for_date_picks_latest_prior()
    test_load_cot_weekly_from_synthetic_csv()
    test_backtest_returns_well_formed_summary()
    test_backtest_cot_gating_blocks_entries()
    print("\n✓ all supply-zone-cot tests passed")

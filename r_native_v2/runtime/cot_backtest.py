"""runtime/cot_backtest.py — Does the COT filter IMPROVE gold supply-zone shorts?

EXPERIMENT
    Pull XAUUSDm H1 history (~700 days, to overlap the weekly COT index) and
    detect a *proxy* for "price has rallied into a SUPPLY zone" short setup:

        SUPPLY-ZONE SHORT proxy (a bar qualifies if BOTH hold):
          1. price has rallied INTO a recent swing-high — the bar's high is at
             or above the highest high of the prior `SWING_LOOKBACK` bars
             (i.e. it pokes into / tags a recent local top = overhead supply); AND
          2. the close is STRETCHED above its mean — close > EMA50 + 1.5 * ATR
             (rallied far above fair value, "into supply", over-extended).

    Each qualifying bar opens a SHORT at next-bar open with an ATR-based bracket:
        SL = entry + SL_ATR * ATR      (above)
        TP = entry - TP_ATR * ATR      (below)
    We then walk forward bar-by-bar to see which is hit first (SL or TP); ties
    inside one bar are resolved pessimistically (SL first). Round-trip broker
    friction from runtime.shared.cost_model is subtracted from every trade's P&L
    so the result is honest about gold's wide spread + commission + slippage.

    We run the SAME setups two ways and compare:
        (A) ALL supply-zone shorts (no COT gate).
        (B) ONLY shorts where runtime.shared.cot_signal.supply_short_ok(
              "XAUUSDm", bar_time) is True  (Commercials BEARISH & Retail BULLISH).

    KEY QUESTION: does the COT gate raise win-rate / profit-factor and cut trade
    count (i.e. filter out "destroyed" supply zones the smart money is NOT
    backing)? B is a strict subset of A, so any lift is attributable to COT.

HONESTY / CAVEATS
    * The supply zone is a PROXY (swing-high tag + ATR stretch above EMA50), not
      a real order-block / liquidity engine. It is deliberately simple and may
      over- or under-count vs FRIDAY's structure engine. Treat magnitudes as
      indicative, the A-vs-B DELTA as the signal.
    * One open trade at a time per arm is NOT enforced — every qualifying bar is
      a candidate trade (overlapping). This maximizes sample size; it inflates
      correlation between nearby trades but keeps A and B directly comparable
      (B's trades are a subset of A's, evaluated identically).
    * cost_model round-trip is computed at a fixed nominal lot (0.10) then
      converted to a per-trade price-distance drag so P&L is in price units.
    * Read-only: does not touch live files, places no orders, writes nothing.

USAGE
    cd C:\\Users\\Radhi\\MT5\\r_native_v2
    C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe runtime\\cot_backtest.py
"""
from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# ── make `runtime.shared.*` importable regardless of CWD ────────────────────
_ROOT = Path(__file__).resolve().parent.parent  # .../r_native_v2
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import MetaTrader5 as mt5
except Exception as e:  # pragma: no cover
    mt5 = None
    _MT5_ERR = e

from runtime.shared import cost_model
from runtime.shared import cot_signal

# ── locate the REAL cot_index.json ──────────────────────────────────────────
# cot_signal.py resolves its data dir to <ROOT>/data, but the fetched index
# actually lives at <ROOT>/runtime/data/cot_index.json in this tree. We do NOT
# edit the live module; instead, from THIS test harness, repoint cot_signal's
# module-level path constants at whichever real file exists, and clear its
# mtime cache so the next read picks the new path up. Read-only redirection.
def _locate_cot_file() -> Path:
    candidates = [
        _ROOT / "runtime" / "data" / "cot_index.json",
        _ROOT / "data" / "cot_index.json",
        cot_signal.COT_INDEX_FILE,
    ]
    for c in candidates:
        try:
            if c.exists() and c.stat().st_size > 0:
                return c
        except OSError:
            continue
    return cot_signal.COT_INDEX_FILE


_real_cot = _locate_cot_file()
cot_signal.COT_INDEX_FILE = _real_cot
cot_signal.DATA = _real_cot.parent
cot_signal._CACHE = {"data": None, "mtime": None}

SYMBOL = "XAUUSDm"
DAYS = 700

# ── strategy params ─────────────────────────────────────────────────────────
ATR_PERIOD = 14
EMA_PERIOD = 50
SWING_LOOKBACK = 24      # bars to define "recent swing high" (~1 day on H1)
STRETCH_ATR = 1.5        # close must be > EMA50 + 1.5*ATR (into supply)
SL_ATR = 1.5             # stop = entry + 1.5*ATR
TP_ATR = 2.0             # target = entry - 2.0*ATR (R:R ~1.33)
NOMINAL_LOT = 0.10


# ── indicators (numpy, no deps) ─────────────────────────────────────────────
def _ema(values: np.ndarray, period: int) -> np.ndarray:
    out = np.empty_like(values, dtype=float)
    k = 2.0 / (period + 1.0)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1.0 - k)
    return out


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    n = len(close)
    tr = np.empty(n, dtype=float)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i] - close[i - 1]))
    atr = np.empty(n, dtype=float)
    atr[0] = tr[0]
    # Wilder smoothing
    for i in range(1, n):
        if i < period:
            atr[i] = tr[: i + 1].mean()
        else:
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


# ── data pull ───────────────────────────────────────────────────────────────
def _pull_rates():
    if mt5 is None:
        raise RuntimeError(f"MetaTrader5 import failed: {_MT5_ERR}")
    if not mt5.initialize():
        raise RuntimeError(f"mt5.initialize() failed: {mt5.last_error()}")
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=DAYS)
    rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_H1, start, end)
    mt5.shutdown()
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"copy_rates_range returned no data for {SYMBOL}")
    return rates


# ── trade result ────────────────────────────────────────────────────────────
@dataclass
class Trade:
    entry_time: dt.datetime
    entry: float
    sl: float
    tp: float
    exit_price: float
    won: bool
    gross: float   # price-units, short: entry-exit
    net: float     # gross - friction (price-units)
    cot_ok: bool


def _simulate(rates) -> list[Trade]:
    o = rates["open"].astype(float)
    h = rates["high"].astype(float)
    l = rates["low"].astype(float)
    c = rates["close"].astype(float)
    t = rates["time"].astype("int64")
    n = len(c)

    ema = _ema(c, EMA_PERIOD)
    atr = _atr(h, l, c, ATR_PERIOD)

    # round-trip friction expressed in PRICE UNITS (gold-points = price units),
    # at the nominal lot, converted from dollars via dollar/point/lot value.
    prof = cost_model._profile(SYMBOL)
    pv = prof.point_value                # $/point/lot  (point=0.001 -> $0.10)
    rep_price = float(np.median(c))
    rt_dollars = cost_model.round_trip_cost(SYMBOL, lot=NOMINAL_LOT, price=rep_price)
    # dollars -> internal points -> price units
    friction_internal_pts = rt_dollars / (pv * NOMINAL_LOT)
    friction_price = friction_internal_pts * prof.point  # price units to overcome

    trades: list[Trade] = []
    start_i = max(EMA_PERIOD, ATR_PERIOD, SWING_LOOKBACK) + 1

    for i in range(start_i, n - 1):
        a = atr[i]
        if a <= 0:
            continue
        # (1) rally INTO a recent swing high: bar high tags/exceeds prior-N highs
        prior_high = h[i - SWING_LOOKBACK:i].max()
        tagged_supply = h[i] >= prior_high
        # (2) stretched above mean: close > EMA50 + 1.5*ATR
        stretched = c[i] > ema[i] + STRETCH_ATR * a
        if not (tagged_supply and stretched):
            continue

        entry = o[i + 1]                 # next-bar open
        sl = entry + SL_ATR * a
        tp = entry - TP_ATR * a

        # walk forward
        exit_price = None
        won = False
        for j in range(i + 1, n):
            hi, lo = h[j], l[j]
            hit_sl = hi >= sl
            hit_tp = lo <= tp
            if hit_sl and hit_tp:        # pessimistic tie-break: SL first
                exit_price, won = sl, False
                break
            if hit_sl:
                exit_price, won = sl, False
                break
            if hit_tp:
                exit_price, won = tp, True
                break
        if exit_price is None:           # never resolved before data end -> skip
            continue

        gross = entry - exit_price       # short P&L in price units
        net = gross - friction_price

        bar_time = dt.datetime.fromtimestamp(int(t[i]), dt.timezone.utc)
        cot_ok, _ = cot_signal.supply_short_ok(SYMBOL, bar_time)

        trades.append(Trade(
            entry_time=bar_time, entry=entry, sl=sl, tp=tp,
            exit_price=exit_price, won=won, gross=gross, net=net, cot_ok=cot_ok,
        ))

    return trades, friction_price


# ── stats ───────────────────────────────────────────────────────────────────
def _stats(trades: list[Trade]) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "profit_factor": 0.0, "net_return": 0.0, "gross_return": 0.0,
                "avg_net": 0.0, "gross_win": 0.0, "gross_loss": 0.0}
    wins = sum(1 for x in trades if x.net > 0)
    losses = n - wins
    gross_win = sum(x.net for x in trades if x.net > 0)
    gross_loss = sum(-x.net for x in trades if x.net <= 0)
    net_return = sum(x.net for x in trades)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    return {
        "trades": n, "wins": wins, "losses": losses,
        "win_rate": wins / n * 100.0,
        "profit_factor": pf,
        "net_return": net_return,
        "gross_return": sum(x.gross for x in trades),
        "avg_net": net_return / n,
        "gross_win": gross_win, "gross_loss": gross_loss,
    }


def _fmt_pf(pf: float) -> str:
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def main() -> None:
    print("=" * 74)
    print("COT FILTER TEST — does COT improve XAUUSDm supply-zone shorts?")
    print("=" * 74)

    # COT data sanity / real-vs-sample check
    idx = cot_signal._load_index()
    cot_real = False
    if not idx:
        print("\n[CRITICAL] cot_index.json missing/unreadable — cannot run arm B.")
    else:
        gold = idx.get("GOLD") or []
        meta = idx.get("_meta")
        print(f"\nCOT index : {cot_signal.COT_INDEX_FILE}")
        print(f"  GOLD weekly rows : {len(gold)}")
        if gold:
            print(f"  date range       : {gold[0].get('date')} .. {gold[-1].get('date')}")
        if meta:
            print(f"  _meta            : {meta}")
        short_weeks = sum(1 for r in gold
                          if r.get('comm_state') == 'BEARISH'
                          and r.get('retail_state') == 'BULLISH')
        print(f"  weeks passing supply_short_ok (comm BEARISH & retail BULLISH): "
              f"{short_weeks}/{len(gold)}")
        # Heuristic for "real vs sample": real fetch has many rows spanning >1yr
        # and a _meta block from cot_fetch; the in-code synthetic stub is 2-3 rows.
        cot_real = len(gold) >= 20
        if not cot_real:
            print("\n[WARN] GOLD has <20 rows — looks like SAMPLE/synthetic COT data.")
            print("       Arm B is not trustworthy; test needs REAL COT data.")
        else:
            print("  -> looks like REAL fetched COT data (sufficient history).")

    print(f"\nPulling {SYMBOL} H1, last {DAYS} days from MT5 ...")
    rates = _pull_rates()
    t0 = dt.datetime.fromtimestamp(int(rates['time'][0]), dt.timezone.utc)
    t1 = dt.datetime.fromtimestamp(int(rates['time'][-1]), dt.timezone.utc)
    print(f"  bars: {len(rates)}   {t0:%Y-%m-%d} .. {t1:%Y-%m-%d}")

    trades, friction = _simulate(rates)
    print(f"\nround-trip friction subtracted per trade: {friction:.3f} price units "
          f"(${cost_model.round_trip_cost(SYMBOL, NOMINAL_LOT, float(np.median(rates['close'].astype(float)))):.2f} "
          f"at {NOMINAL_LOT} lot)")
    print(f"setup: tag recent {SWING_LOOKBACK}-bar swing-high AND close > EMA{EMA_PERIOD}"
          f"+{STRETCH_ATR}*ATR; SL {SL_ATR}*ATR / TP {TP_ATR}*ATR")

    arm_a = trades                                   # ALL supply-zone shorts
    arm_b = [x for x in trades if x.cot_ok]          # COT-gated subset

    sa = _stats(arm_a)
    sb = _stats(arm_b)

    print("\n" + "=" * 74)
    print("RESULTS  (P&L in gold price units, net of round-trip friction)")
    print("=" * 74)
    hdr = f"{'metric':<18}{'(A) ALL shorts':>20}{'(B) COT-gated':>20}"
    print(hdr)
    print("-" * 74)
    rows = [
        ("trades", f"{sa['trades']}", f"{sb['trades']}"),
        ("wins", f"{sa['wins']}", f"{sb['wins']}"),
        ("losses", f"{sa['losses']}", f"{sb['losses']}"),
        ("win_rate %", f"{sa['win_rate']:.1f}", f"{sb['win_rate']:.1f}"),
        ("profit_factor", _fmt_pf(sa['profit_factor']), _fmt_pf(sb['profit_factor'])),
        ("net_return", f"{sa['net_return']:.1f}", f"{sb['net_return']:.1f}"),
        ("avg_net/trade", f"{sa['avg_net']:.2f}", f"{sb['avg_net']:.2f}"),
    ]
    for name, av, bv in rows:
        print(f"{name:<18}{av:>20}{bv:>20}")

    # ── verdict ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 74)
    print("VERDICT")
    print("=" * 74)
    if not cot_real:
        print("INCONCLUSIVE — COT data appears to be sample/synthetic, not real.")
        print("Re-run after cot_fetch.py populates real CFTC GOLD positioning.")
    elif sb["trades"] == 0:
        print("INCONCLUSIVE — COT gate left 0 trades; no overlap between supply")
        print("setups and comm-BEARISH/retail-BULLISH weeks in this window.")
    else:
        d_wr = sb["win_rate"] - sa["win_rate"]
        pf_a = sa["profit_factor"]; pf_b = sb["profit_factor"]
        pf_up = (pf_b > pf_a) or (pf_b == float("inf") and pf_a != float("inf"))
        wr_up = d_wr > 0
        cut = sb["trades"] < sa["trades"]
        kept_pct = sb["trades"] / sa["trades"] * 100.0
        print(f"COT gate kept {sb['trades']}/{sa['trades']} setups ({kept_pct:.0f}%), "
              f"filtered {sa['trades'] - sb['trades']}.")
        print(f"win-rate  : {sa['win_rate']:.1f}% -> {sb['win_rate']:.1f}%  "
              f"({d_wr:+.1f} pp)")
        print(f"profit_fac: {_fmt_pf(pf_a)} -> {_fmt_pf(pf_b)}")
        print(f"avg net/tr: {sa['avg_net']:.2f} -> {sb['avg_net']:.2f}")
        if wr_up and pf_up and cut:
            print("\n=> COT ADDS EDGE: higher win-rate AND higher PF on fewer, "
                  "higher-quality\n   trades. The filter removes 'destroyed' "
                  "supply zones the smart money isn't backing.")
        elif (wr_up or pf_up) and cut:
            print("\n=> COT shows PARTIAL edge: improves "
                  f"{'win-rate' if wr_up else 'PF'} while cutting count, but not "
                  "both metrics. Suggestive, not decisive at this sample size.")
        else:
            print("\n=> COT does NOT add edge here: the gate did not improve "
                  "win-rate/PF.\n   On this proxy + window, COT filtering is not "
                  "justified.")
        if sb["trades"] < 15:
            print(f"\n[caution] arm B n={sb['trades']} is small — verdict is "
                  "low-confidence; widen window or loosen proxy for more samples.")


if __name__ == "__main__":
    main()

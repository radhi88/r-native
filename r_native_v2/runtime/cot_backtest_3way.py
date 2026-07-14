"""runtime/cot_backtest_3way.py — Does the COT gate add edge in the
REGIME-APPROPRIATE direction across THREE symbol/direction pairs?

This is a sibling of runtime/cot_backtest.py (which tests XAUUSDm supply-zone
SHORTS only). It does NOT modify that file. It generalises the same machinery to
run three WITH-COT-gate vs WITHOUT-COT comparisons, each net of
runtime.shared.cost_model friction:

    (1) GOLD LONGS   — buy DEMAND zones on XAUUSDm H1.
        demand proxy : close < EMA50 - 1.5*ATR  OR  bar tags a recent 24-bar
                       swing-LOW (price dipped INTO demand / is over-extended low).
        COT gate     : cot_signal.supply_long_ok("XAUUSDm", t)
                       (Commercials BULLISH + Retail BEARISH).
        Rationale    : long is the regime-appropriate side for gold's 2024-2026
                       bull run.
    (2) EURUSDm SHORTS — supply-zone shorts, gate supply_short_ok("EURUSDm", t).
    (3) GBPUSDm SHORTS — supply-zone shorts, gate supply_short_ok("GBPUSDm", t).

For each, arm A = ALL proxy setups (no gate); arm B = COT-gated subset. B is a
strict subset of A evaluated identically, so any win-rate / profit-factor lift
is attributable to the COT gate. We report trades / win_rate / profit_factor /
net for both arms and state whether COT RAISED win-rate/PF.

HONESTY / CAVEATS
    * The supply/demand zone is a CRUDE PROXY (EMA50+/-1.5*ATR stretch OR a
      swing-high/low tag), NOT the real order-block / liquidity engine. Treat
      magnitudes as indicative; the A-vs-B DELTA is the signal of interest.
    * Overlapping trades allowed (one-at-a-time not enforced) to maximise and
      equalise sample size between arms.
    * Round-trip cost_model friction is converted to price-units and subtracted
      from every trade.
    * Read-only: no live files touched, no orders, MT5 used read-only.

USAGE
    cd C:\\Users\\Radhi\\MT5\\r_native_v2
    C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe runtime\\cot_backtest_3way.py
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


# ── locate the REAL cot_index.json (same redirection as cot_backtest.py) ─────
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

DAYS = 700

# ── strategy params ─────────────────────────────────────────────────────────
ATR_PERIOD = 14
EMA_PERIOD = 50
SWING_LOOKBACK = 24      # ~1 day on H1
STRETCH_ATR = 1.5        # close beyond EMA50 -/+ 1.5*ATR (into demand/supply)
SL_ATR = 1.5
TP_ATR = 2.0             # R:R ~1.33
NOMINAL_LOT = 0.10


# ── indicators (numpy, no deps) ─────────────────────────────────────────────
def _ema(values: np.ndarray, period: int) -> np.ndarray:
    out = np.empty_like(values, dtype=float)
    k = 2.0 / (period + 1.0)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1.0 - k)
    return out


def _atr(high, low, close, period):
    n = len(close)
    tr = np.empty(n, dtype=float)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i] - close[i - 1]))
    atr = np.empty(n, dtype=float)
    atr[0] = tr[0]
    for i in range(1, n):
        if i < period:
            atr[i] = tr[: i + 1].mean()
        else:
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


# ── data pull ───────────────────────────────────────────────────────────────
def _pull_rates(symbol: str):
    if mt5 is None:
        raise RuntimeError(f"MetaTrader5 import failed: {_MT5_ERR}")
    if not mt5.initialize():
        raise RuntimeError(f"mt5.initialize() failed: {mt5.last_error()}")
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=DAYS)
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, start, end)
    mt5.shutdown()
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"copy_rates_range returned no data for {symbol}")
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
    gross: float
    net: float
    cot_ok: bool


def _friction_price(symbol: str, rep_price: float) -> float:
    prof = cost_model._profile(symbol)
    pv = prof.point_value
    rt_dollars = cost_model.round_trip_cost(symbol, lot=NOMINAL_LOT, price=rep_price)
    friction_internal_pts = rt_dollars / (pv * NOMINAL_LOT)
    return friction_internal_pts * prof.point  # price units


def _simulate(symbol: str, rates, direction: str, gate_fn):
    """direction: 'long' (buy demand) or 'short' (sell supply).
    gate_fn(symbol, bar_time) -> (bool, reason).
    """
    o = rates["open"].astype(float)
    h = rates["high"].astype(float)
    l = rates["low"].astype(float)
    c = rates["close"].astype(float)
    t = rates["time"].astype("int64")
    n = len(c)

    ema = _ema(c, EMA_PERIOD)
    atr = _atr(h, l, c, ATR_PERIOD)
    rep_price = float(np.median(c))
    friction = _friction_price(symbol, rep_price)

    trades: list[Trade] = []
    start_i = max(EMA_PERIOD, ATR_PERIOD, SWING_LOOKBACK) + 1

    for i in range(start_i, n - 1):
        a = atr[i]
        if a <= 0:
            continue

        if direction == "short":
            # SUPPLY proxy: rallied into a recent swing-high OR stretched above mean
            prior_high = h[i - SWING_LOOKBACK:i].max()
            tagged = h[i] >= prior_high
            stretched = c[i] > ema[i] + STRETCH_ATR * a
            if not (tagged or stretched):
                continue
            entry = o[i + 1]
            sl = entry + SL_ATR * a
            tp = entry - TP_ATR * a
        else:  # long, DEMAND proxy: dipped into a recent swing-low OR stretched below mean
            prior_low = l[i - SWING_LOOKBACK:i].min()
            tagged = l[i] <= prior_low
            stretched = c[i] < ema[i] - STRETCH_ATR * a
            if not (tagged or stretched):
                continue
            entry = o[i + 1]
            sl = entry - SL_ATR * a
            tp = entry + TP_ATR * a

        # walk forward — first touch wins, pessimistic tie-break (SL first)
        exit_price = None
        won = False
        for j in range(i + 1, n):
            hi, lo = h[j], l[j]
            if direction == "short":
                hit_sl = hi >= sl
                hit_tp = lo <= tp
            else:
                hit_sl = lo <= sl
                hit_tp = hi >= tp
            if hit_sl and hit_tp:
                exit_price, won = sl, False
                break
            if hit_sl:
                exit_price, won = sl, False
                break
            if hit_tp:
                exit_price, won = tp, True
                break
        if exit_price is None:
            continue

        if direction == "short":
            gross = entry - exit_price
        else:
            gross = exit_price - entry
        net = gross - friction

        bar_time = dt.datetime.fromtimestamp(int(t[i]), dt.timezone.utc)
        cot_ok, _ = gate_fn(symbol, bar_time)

        trades.append(Trade(
            entry_time=bar_time, entry=entry, sl=sl, tp=tp,
            exit_price=exit_price, won=won, gross=gross, net=net, cot_ok=cot_ok,
        ))

    return trades, friction


# ── stats ───────────────────────────────────────────────────────────────────
def _stats(trades):
    n = len(trades)
    if n == 0:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "profit_factor": 0.0, "net_return": 0.0, "avg_net": 0.0}
    wins = sum(1 for x in trades if x.net > 0)
    losses = n - wins
    gross_win = sum(x.net for x in trades if x.net > 0)
    gross_loss = sum(-x.net for x in trades if x.net <= 0)
    net_return = sum(x.net for x in trades)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    return {"trades": n, "wins": wins, "losses": losses,
            "win_rate": wins / n * 100.0, "profit_factor": pf,
            "net_return": net_return, "avg_net": net_return / n}


def _fmt_pf(pf):
    return "inf" if pf == float("inf") else f"{pf:.2f}"


# ── one comparison ────────────────────────────────────────────────────────────
def run_comparison(symbol, direction, gate_fn, gate_name, label):
    rates = _pull_rates(symbol)
    t0 = dt.datetime.fromtimestamp(int(rates['time'][0]), dt.timezone.utc)
    t1 = dt.datetime.fromtimestamp(int(rates['time'][-1]), dt.timezone.utc)
    trades, friction = _simulate(symbol, rates, direction, gate_fn)

    arm_a = trades
    arm_b = [x for x in trades if x.cot_ok]
    sa = _stats(arm_a)
    sb = _stats(arm_b)

    lines = []
    lines.append("=" * 78)
    lines.append(f"{label}")
    lines.append(f"  symbol={symbol}  direction={direction.upper()}  gate={gate_name}")
    lines.append("=" * 78)
    lines.append(f"  bars: {len(rates)}   {t0:%Y-%m-%d}..{t1:%Y-%m-%d}   "
                 f"friction/trade={friction:.5f} price units")
    lines.append(f"  {'metric':<16}{'(A) NO-COT':>18}{'(B) COT-gated':>18}")
    lines.append("  " + "-" * 52)
    rows = [
        ("trades", f"{sa['trades']}", f"{sb['trades']}"),
        ("win_rate %", f"{sa['win_rate']:.1f}", f"{sb['win_rate']:.1f}"),
        ("profit_factor", _fmt_pf(sa['profit_factor']), _fmt_pf(sb['profit_factor'])),
        ("net (px units)", f"{sa['net_return']:.2f}", f"{sb['net_return']:.2f}"),
        ("avg_net/trade", f"{sa['avg_net']:.4f}", f"{sb['avg_net']:.4f}"),
    ]
    for nm, av, bv in rows:
        lines.append(f"  {nm:<16}{av:>18}{bv:>18}")

    # verdict for this pair
    verdict = _pair_verdict(sa, sb)
    lines.append("")
    lines.append("  VERDICT: " + verdict)
    return "\n".join(lines), sa, sb, verdict


def _pair_verdict(sa, sb):
    if sb["trades"] == 0:
        return ("COT gate left 0 trades — no overlap between proxy setups and "
                "gate-passing weeks. COT cannot be evaluated / adds no usable signal here.")
    d_wr = sb["win_rate"] - sa["win_rate"]
    pf_a, pf_b = sa["profit_factor"], sb["profit_factor"]
    pf_up = (pf_b > pf_a) or (pf_b == float("inf") and pf_a != float("inf"))
    wr_up = d_wr > 0
    kept = sb["trades"] / sa["trades"] * 100.0 if sa["trades"] else 0.0
    head = (f"kept {sb['trades']}/{sa['trades']} ({kept:.0f}%); "
            f"WR {sa['win_rate']:.1f}%->{sb['win_rate']:.1f}% ({d_wr:+.1f}pp); "
            f"PF {_fmt_pf(pf_a)}->{_fmt_pf(pf_b)}; "
            f"avg/tr {sa['avg_net']:.4f}->{sb['avg_net']:.4f}. ")
    if wr_up and pf_up:
        tail = "COT RAISED both win-rate AND profit-factor -> adds edge."
    elif wr_up or pf_up:
        tail = (f"COT raised {'win-rate' if wr_up else 'profit-factor'} only "
                "(not both) -> weak/partial, not decisive.")
    else:
        tail = "COT did NOT raise win-rate or profit-factor -> adds NO edge here."
    if 0 < sb["trades"] < 15:
        tail += f" [low-confidence: arm B n={sb['trades']}]"
    return head + tail


def main():
    print("#" * 78)
    print("COT 3-WAY TEST — regime-appropriate direction, net of cost_model friction")
    print("#" * 78)

    idx = cot_signal._load_index()
    print(f"\nCOT index: {cot_signal.COT_INDEX_FILE}")
    if idx:
        for mk in ("GOLD", "EURO FX", "BRITISH POUND"):
            rows = idx.get(mk) or []
            lo = sum(1 for r in rows if r.get('comm_state') == 'BULLISH'
                     and r.get('retail_state') == 'BEARISH')
            so = sum(1 for r in rows if r.get('comm_state') == 'BEARISH'
                     and r.get('retail_state') == 'BULLISH')
            rng = f"{rows[0]['date']}..{rows[-1]['date']}" if rows else "n/a"
            print(f"  {mk:<14} {len(rows):>3} wks {rng}  "
                  f"long_ok(commBULL&retailBEAR)={lo}  short_ok(commBEAR&retailBULL)={so}")

    comps = [
        ("XAUUSDm", "long", cot_signal.supply_long_ok, "supply_long_ok",
         "(1) GOLD LONGS — buy DEMAND zones [regime-appropriate for 2024-26 bull run]"),
        ("EURUSDm", "short", cot_signal.supply_short_ok, "supply_short_ok",
         "(2) EURUSDm SHORTS — sell SUPPLY zones"),
        ("GBPUSDm", "short", cot_signal.supply_short_ok, "supply_short_ok",
         "(3) GBPUSDm SHORTS — sell SUPPLY zones"),
    ]
    results = []
    for sym, d, gate, gname, label in comps:
        block, sa, sb, verdict = run_comparison(sym, d, gate, gname, label)
        print("\n" + block)
        results.append((label, sym, d, sa, sb, verdict))

    print("\n" + "#" * 78)
    print("OVERALL VERDICT")
    print("#" * 78)
    any_edge = False
    for label, sym, d, sa, sb, verdict in results:
        edge = (sb["trades"] > 0 and sb["win_rate"] > sa["win_rate"]
                and ((sb["profit_factor"] > sa["profit_factor"])
                     or (sb["profit_factor"] == float("inf")
                         and sa["profit_factor"] != float("inf"))))
        any_edge = any_edge or edge
        tag = "EDGE" if edge else "no edge"
        print(f"  [{tag:>7}] {sym} {d.upper()}")
    if not any_edge:
        print("\n  => COT adds NO tradeable edge in any of the three pairs on this "
              "proxy+window.")
    return results


if __name__ == "__main__":
    main()

"""nr7_backtest.py — replay the NR7 edge on the MOST RECENT USTECm M15 data.

Answers "does it still work as if now?" without waiting days for rare live signals.
Uses the EXACT rule the forward-paper prover trades (nr7_prover.py):
  NR7 contraction bar (narrowest H-L of last 7, at close of bar i) -> breakout on
  the NEXT bar only: >high[i] BUY, <low[i] SELL, both=skip. SL=1xATR14, TP=3R.
  Cost = 3.0 index pts round-trip. One position at a time. SL-first if SL&TP share a bar.

This is a fresh OUT-OF-SAMPLE slice (the deep-hunt OOS ended ~2026-06; this is newer),
so it is honest — but it is a backtest, not the >=100 live forward trades the promotion
gate requires. Reports overall + the most-recent 30-day slice.
"""
from __future__ import annotations
import math
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

SYMBOL, NR, ATR_LEN, TP_R, SL_MULT = "USTECm", 7, 14, 3.0, 1.0
COST_PTS = 3.0          # index points round-trip (matches deep-hunt assumption)
N_BARS = 5000           # ~52 days of M15


def atr_series(bars):
    tr = [0.0]
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = [0.0] * len(bars)
    for i in range(len(bars)):
        if i >= ATR_LEN:
            atr[i] = sum(tr[i - ATR_LEN + 1:i + 1]) / ATR_LEN
    return atr


def backtest(bars):
    atr = atr_series(bars)
    trades = []           # (exit_time, R_net)
    i = ATR_LEN + NR
    n = len(bars)
    while i < n - 1:
        # is bar i an NR7 contraction bar?
        rng = [bars[j]["high"] - bars[j]["low"] for j in range(i - NR + 1, i + 1)]
        if (bars[i]["high"] - bars[i]["low"]) > min(rng) + 1e-9 or atr[i] <= 0:
            i += 1; continue
        hi, lo, a = bars[i]["high"], bars[i]["low"], atr[i]
        nb = bars[i + 1]                         # the breakout window (next bar only)
        up = nb["high"] >= hi
        dn = nb["low"] <= lo
        if up and dn:                            # gap engulfs both -> skip whipsaw
            i += 1; continue
        if not (up or dn):                       # no breakout this bar -> signal expires
            i += 1; continue
        side = "BUY" if up else "SELL"
        entry = hi if up else lo                 # fill at the stop level
        if up and nb["open"] > hi: entry = nb["open"]   # gap-through fill
        if dn and nb["open"] < lo: entry = nb["open"]
        risk = SL_MULT * a
        sl = entry - risk if up else entry + risk
        tp = entry + TP_R * risk if up else entry - TP_R * risk
        # walk forward from the entry bar to resolve SL/TP (SL assumed first if both)
        r_gross = None
        for k in range(i + 1, n):
            b = bars[k]
            if up:
                if b["low"] <= sl: r_gross = -1.0; break
                if b["high"] >= tp: r_gross = TP_R; break
            else:
                if b["high"] >= sl: r_gross = -1.0; break
                if b["low"] <= tp: r_gross = TP_R; break
        if r_gross is None:                      # still open at data end -> mark-to-market
            last = bars[-1]["close"]
            r_gross = ((last - entry) if up else (entry - last)) / risk
            exit_k = n - 1
        else:
            exit_k = k
        cost_r = COST_PTS / risk                 # index-pt cost expressed in R
        trades.append((int(bars[exit_k]["time"]), round(r_gross - cost_r, 4), side))
        i = exit_k + 1                            # one position at a time
    return trades


def stats(rs):
    n = len(rs)
    if n == 0: return dict(n=0)
    mean = sum(rs) / n
    wins = sum(1 for r in rs if r > 0)
    sd = math.sqrt(sum((r - mean) ** 2 for r in rs) / (n - 1)) if n > 1 else 0.0
    t = (mean / (sd / math.sqrt(n))) if sd > 0 else 0.0
    # max drawdown in R
    cum = 0.0; peak = 0.0; dd = 0.0
    for r in rs:
        cum += r; peak = max(peak, cum); dd = min(dd, cum - peak)
    return dict(n=n, expR=round(mean, 4), t=round(t, 2), wr=round(wins / n * 100, 1),
                net_R=round(sum(rs), 1), max_dd_R=round(dd, 1))


def main():
    if not mt5.initialize():
        print("mt5 init failed"); return
    mt5.symbol_select(SYMBOL, True)
    bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, N_BARS)
    if bars is None or len(bars) < 200:
        print("no bars"); return
    span = f"{datetime.fromtimestamp(bars[0]['time'], timezone.utc):%Y-%m-%d} → {datetime.fromtimestamp(bars[-1]['time'], timezone.utc):%Y-%m-%d}"
    trades = backtest(bars)
    all_r = [t[1] for t in trades]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    recent_r = [t[1] for t in trades if t[0] >= cutoff]
    print(f"=== NR7 backtest on RECENT {SYMBOL} M15  ({span}, {len(bars)} bars) ===")
    print(f"cost {COST_PTS} idx-pts/trade | SL=1xATR TP=3R | one-position | fresh OOS")
    print(f"ALL   : {stats(all_r)}")
    print(f"LAST30: {stats(recent_r)}")
    print(f"promotion bar (fwd): expR>=+0.15R over >=100 trades. this is a backtest slice.")
    # last 8 trades for a feel
    print("recent trades (time, R_net, side):")
    for tt in trades[-8:]:
        print(f"  {datetime.fromtimestamp(tt[0], timezone.utc):%m-%d %H:%M}  {tt[1]:+.2f}R  {tt[2]}")


if __name__ == "__main__":
    main()

"""btc_smc_swing.py — DECISIVE realism test of the swing-horizon BTC sr_zone candidate.

btc_smc_levers.py showed sr_zone held LONG (H>=24) on BTCUSDm clears the $10 spread
(net +$17-36/BTC, 4-5/5 walk-forward blocks). BUT that was an UPPER BOUND:
mark-to-market with NO stop, and overlapping forward windows inflate significance.

This test removes BOTH crutches — the real-trade simulation:
  * SEQUENTIAL NON-OVERLAPPING trades: take a signal, hold the position bar-by-bar
    to its exit, only THEN look for the next signal. No overlap -> honest sample.
  * REAL STOP: stop = k*ATR; exit at first intrabar stop-touch (low/high) OR at the
    max-hold horizon, whichever comes first. P&L = (exit-entry)*dir - full spread.
  * Walk-forward 5 blocks: total net$ must be + in >=4 blocks.
This is the tradeable net, not an upper bound. If it survives THIS, it's real.

Run: C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe C:\\Users\\Radhi\\MT5\\btc_smc_swing.py
"""
import sys
import numpy as np
import MetaTrader5 as mt5

WIN = 120
N_BLOCKS = 5


def sr_zone(high, low, close, n=50, thr=0.20):
    if len(close) < n: return 0
    hi = max(high[-n:]); lo = min(low[-n:]); rng = hi - lo
    if rng <= 0: return 0
    pos = (close[-1] - lo) / rng
    if pos <= thr: return 1
    if pos >= 1.0 - thr: return -1
    return 0


def atr_at(high, low, close, i, period=14):
    if i < period: return None
    trs = [max(high[j]-low[j], abs(high[j]-close[j-1]), abs(low[j]-close[j-1]))
           for j in range(i-period+1, i+1)]
    return sum(trs)/len(trs)


def simulate(high, low, close, N, spread, thr, k_stop, max_hold):
    """Sequential non-overlapping bracket trades. Returns list of (entry_bar, pnl$)."""
    start = max(WIN+1, int(N*0.45))
    end = N - max_hold - 1
    trades = []
    i = start
    while i < end:
        cw = close[:i+1][-WIN:].tolist(); hw = high[:i+1][-WIN:].tolist(); lw = low[:i+1][-WIN:].tolist()
        v = sr_zone(hw, lw, cw, thr=thr)
        if v == 0:
            i += 1; continue
        a = atr_at(high, low, close, i)
        if a is None or a <= 0:
            i += 1; continue
        entry = close[i]
        stop = entry - k_stop*a if v == 1 else entry + k_stop*a
        exit_price = close[i+max_hold]; exit_bar = i+max_hold
        for j in range(i+1, i+max_hold+1):
            if v == 1 and low[j] <= stop:          # long stopped
                exit_price = stop; exit_bar = j; break
            if v == -1 and high[j] >= stop:        # short stopped
                exit_price = stop; exit_bar = j; break
        pnl = (exit_price - entry)*v - spread      # full spread paid once
        trades.append((i, pnl))
        i = exit_bar + 1                           # NON-overlapping: resume after exit
    return trades


def report(sym, trades, label):
    if len(trades) < 30:
        print(f"     {label}: only {len(trades)} trades — skip"); return None
    idx = np.array([t[0] for t in trades]); pnl = np.array([t[1] for t in trades])
    n = len(pnl); net = pnl.mean(); tot = pnl.sum(); wr = (pnl > 0).mean()
    # walk-forward by bar index
    edges = np.linspace(idx.min(), idx.max()+1, N_BLOCKS+1).astype(int)
    pos = 0; blk = []
    for b in range(N_BLOCKS):
        m = (idx >= edges[b]) & (idx < edges[b+1])
        if m.sum() == 0: blk.append("0"); continue
        bn = pnl[m].mean(); blk.append("+" if bn > 0 else "-")
        if bn > 0: pos += 1
    # simple t on the (now non-overlapping ~ independent) trades
    t = net/(pnl.std(ddof=1)/np.sqrt(n)) if n > 1 and pnl.std() > 0 else 0
    flag = "  <== PASS" if (net > 0 and pos >= 4 and t > 2) else ""
    print(f"     {label}: n={n:4d} WR={wr:.2f} NET=${net:+7.2f}/trade tot=${tot:+9.1f} "
          f"t={t:+5.2f} blks[{'/'.join(blk)}]={pos}/5{flag}")
    return dict(n=n, net=net, tot=tot, wr=wr, t=t, pos=pos)


def main():
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    acc = mt5.account_info(); print(f"account={acc.login} server={acc.server} balance={acc.balance}")
    print("DECISIVE: sequential NON-overlapping trades + REAL k*ATR stop + full spread.")
    print("PASS = net>0 AND >=4/5 walk-forward blocks AND t>2 (independent trades).\n")
    sym, tf, tag = "BTCUSDm", mt5.TIMEFRAME_M5, "M5"
    info = mt5.symbol_info(sym)
    if info is None: mt5.symbol_select(sym, True); info = mt5.symbol_info(sym)
    tick = mt5.symbol_info_tick(sym)
    spread = (tick.ask-tick.bid) if tick else info.spread*info.point
    r = mt5.copy_rates_from_pos(sym, tf, 0, 100000)
    high = np.asarray([float(x["high"]) for x in r]); low = np.asarray([float(x["low"]) for x in r])
    close = np.asarray([float(x["close"]) for x in r]); N = len(close)
    print(f"===== {sym} {tag}  bars={N}  spread=${spread:g} =====")
    passes = []
    for thr in (0.20, 0.10):
        for max_hold in (48, 96):
            for k_stop in (2, 3, 4):
                tr = simulate(high, low, close, N, spread, thr, k_stop, max_hold)
                d = report(sym, tr, f"thr{thr:.2f} hold{max_hold} stop{k_stop}xATR")
                if d and d["net"] > 0 and d["pos"] >= 4 and d["t"] > 2:
                    passes.append((thr, max_hold, k_stop, d))
    print("\n================  REALISTIC PASSES  ================")
    if passes:
        for thr, mh, ks, d in passes:
            print(f"  *** thr{thr} hold{mh} stop{ks}xATR: net=${d['net']:+.2f}/trade "
                  f"tot=${d['tot']:+.1f} WR={d['wr']:.2f} t={d['t']:+.2f} blks={d['pos']}/5 n={d['n']}")
    else:
        print("  NONE survive a realistic stop + non-overlapping sampling -> upper-bound was an artifact.")
    mt5.shutdown(); return 0


if __name__ == "__main__":
    sys.exit(main())

"""markov_regime.py — observable Markov regime model (Bull/Bear/Sideways) for our
MT5 symbols. Same framework as Roan's (@RohOnChain) markov-hedge-fund-method, built
as a PROJECT tool (not a Claude skill — that folder is guarded) and MT5-native so it
feeds our gold/pairs specialists with regime context.

Builds the 3x3 transition matrix via MLE counting, solves the stationary distribution,
forecasts n-step ahead (Chapman-Kolmogorov), derives a signed signal P(Bull)-P(Bear),
and runs a WALK-FORWARD backtest (re-estimates the matrix every step, NO lookahead) →
Sharpe + max drawdown.

Run:  python markov_regime.py --symbol XAUUSDm --tf D1 --bars 2500 --window 20
"""
from __future__ import annotations
import argparse
import numpy as np

STATES = ["Bear", "Sideways", "Bull"]   # index 0,1,2


def label_regimes(close, window=20, threshold=0.02):
    close = np.asarray(close, float)
    roll = np.full(len(close), np.nan)
    roll[window:] = close[window:] / close[:-window] - 1.0
    lab = np.full(len(close), 1, dtype=int)            # default Sideways
    lab[roll > threshold] = 2                          # Bull
    lab[roll < -threshold] = 0                         # Bear
    valid = ~np.isnan(roll)
    return lab, valid


def transition_matrix(labels):
    counts = np.zeros((3, 3))
    for i in range(len(labels) - 1):
        counts[labels[i], labels[i + 1]] += 1
    rs = counts.sum(axis=1, keepdims=True); rs[rs == 0] = 1.0
    return counts / rs


def stationary(P):
    w, v = np.linalg.eig(P.T)
    i = np.argmin(np.abs(w - 1.0))
    vec = np.abs(np.real(v[:, i]))
    return vec / vec.sum()


def n_step(P, n):
    return np.linalg.matrix_power(P, n)


def signal_from(P, state):
    return float(P[state, 2] - P[state, 0])           # P(Bull) - P(Bear)


def walk_forward(close, labels, valid, min_train=252):
    close = np.asarray(close, float)
    rets = np.zeros(len(close)); rets[1:] = close[1:] / close[:-1] - 1.0
    idx = np.where(valid)[0]
    if len(idx) < min_train + 30:
        return {"sharpe": float("nan"), "max_dd": float("nan"), "n": 0}
    strat = []
    for k in range(min_train, len(idx) - 1):
        t = idx[k]
        P = transition_matrix(labels[idx[0]:t])        # only data before t
        pos = float(np.sign(signal_from(P, int(labels[t]))))
        strat.append(pos * rets[t + 1])
    sr = np.array(strat)
    sd = sr.std(ddof=1)
    sharpe = float(sr.mean() / sd * np.sqrt(252)) if sd > 0 and np.isfinite(sd) else float("nan")
    eq = np.cumprod(1.0 + sr); peak = np.maximum.accumulate(eq)
    mdd = float(((eq - peak) / peak).min()) if len(eq) else float("nan")
    return {"sharpe": sharpe, "max_dd": mdd, "n": len(sr)}


def fetch_mt5(symbol, tf, bars):
    import MetaTrader5 as mt5
    TF = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
          "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
    if not mt5.initialize() and not mt5.initialize():
        return None
    r = mt5.copy_rates_from_pos(symbol, TF.get(tf, mt5.TIMEFRAME_D1), 0, bars)
    mt5.shutdown()
    if r is None or len(r) < 100:
        return None
    return np.array([x["close"] for x in r], float)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="markov_regime")
    ap.add_argument("--symbol", default="XAUUSDm")
    ap.add_argument("--tf", default="D1")
    ap.add_argument("--bars", type=int, default=2500)
    ap.add_argument("--window", type=int, default=20)
    ap.add_argument("--threshold", type=float, default=0.02)
    ap.add_argument("--forecast", type=int, default=5, help="n-step forecast horizon")
    a = ap.parse_args(argv)

    print(f"\nmarkov_regime — {a.symbol} {a.tf}  window={a.window}  thr={a.threshold}")
    close = fetch_mt5(a.symbol, a.tf, a.bars)
    if close is None:
        print("  ! no MT5 data (check symbol/terminal)."); return 1
    print(f"  fetched {len(close)} bars")
    labels, valid = label_regimes(close, a.window, a.threshold)
    lv = labels[valid]
    P = transition_matrix(lv)
    pi = stationary(P)

    print("\nTransition matrix (from -> to):")
    print(f"            {STATES[0]:>9s} {STATES[1]:>9s} {STATES[2]:>9s}")
    for i, s in enumerate(STATES):
        print(f"  {s:>9s}  " + "  ".join(f"{P[i,j]*100:6.2f}%" for j in range(3)))
    print("\nPersistence (diagonal):")
    for i, s in enumerate(STATES):
        print(f"  {s} -> {s}: {P[i,i]*100:.2f}%")
    print("\nStationary distribution (long-run mix):")
    for s, p in zip(STATES, pi):
        print(f"  {s:>9s}: {p*100:.2f}%")

    cur = int(lv[-1])
    print(f"\nCurrent regime: {STATES[cur]}  |  next-bar signal P(Bull)-P(Bear) = {signal_from(P,cur):+.3f}")
    Pn = n_step(P, a.forecast)
    print(f"{a.forecast}-step forecast from {STATES[cur]}: " +
          "  ".join(f"{STATES[j]} {Pn[cur,j]*100:.1f}%" for j in range(3)))

    print("\nWalk-forward backtest (no lookahead)...")
    wf = walk_forward(close, labels, valid)
    print(f"  Sharpe (annualised): {wf['sharpe']:.3f}" if np.isfinite(wf['sharpe']) else "  Sharpe: NaN")
    print(f"  Max drawdown:        {wf['max_dd']*100:.2f}%" if np.isfinite(wf['max_dd']) else "  Max drawdown: NaN")
    print(f"  Trades evaluated:    {wf['n']}")
    print("\n  (Walk-forward = honest. Backtests are historical, not forward-looking.)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

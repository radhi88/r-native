"""Diagnose why gene candidates fail Monte Carlo / Walk-Forward."""
import pandas as pd
import numpy as np

df = pd.read_parquet("data/backtest/all_trades.parquet")

candidates = [
    ("XAUUSDm", "M5", "SELL", "ny", "low"),
    ("XAUUSDm", "M1", "BUY", "ny", "medium"),
    ("XAUUSDm", "M1", "SELL", "london", "low"),
    ("XAUUSDm", "M5", "BUY", "london", "low"),
    ("XAUUSDm", "M15", "BUY", "london", "low"),
]

def monte_carlo_test(trades, n=1000, threshold=-15.0):
    pnl = trades["pnl_r"].values
    worst_dds = []
    for _ in range(n):
        shuffled = np.random.permutation(pnl)
        equity = np.cumsum(shuffled)
        dd = float((equity - np.maximum.accumulate(equity)).min())
        worst_dds.append(dd)
    p5 = float(np.percentile(worst_dds, 5))
    return p5, p5 > threshold

def walk_forward_test(trades, train_pct=0.8, max_degradation=-0.15):
    n = len(trades)
    split = int(n * train_pct)
    is_wr = float(trades.iloc[:split]["win"].mean())
    oos_wr = float(trades.iloc[split:]["win"].mean())
    degradation = oos_wr - is_wr
    return is_wr, oos_wr, degradation, degradation > max_degradation

for cand in candidates:
    mask = (
        (df["symbol"] == cand[0]) & (df["timeframe"] == cand[1]) &
        (df["direction"] == cand[2]) & (df["session"] == cand[3]) &
        (df["atr_regime"] == cand[4])
    )
    gdf = df[mask]
    if len(gdf) < 10:
        print(f"{cand}: insufficient data ({len(gdf)} trades)")
        continue

    wr = gdf["win"].mean()
    pf_val = gdf.loc[gdf["win"],"pnl_r"].sum() / max(abs(gdf.loc[~gdf["win"],"pnl_r"].sum()), 0.001)
    pnl_stats = gdf["pnl_r"].describe()

    mc_p5, mc_pass = monte_carlo_test(gdf)
    is_wr, oos_wr, degrad, wf_pass = walk_forward_test(gdf)

    print(f"\n{cand}")
    print(f"  n={len(gdf)}, WR={wr:.1%}, PF={pf_val:.2f}")
    print(f"  pnl_r: mean={pnl_stats['mean']:.3f}, min={pnl_stats['min']:.3f}, max={pnl_stats['max']:.3f}")
    print(f"  Monte Carlo p5_dd={mc_p5:.2f}R  → {'PASS' if mc_pass else 'FAIL (threshold=-15)'}")
    print(f"  Walk-Forward IS={is_wr:.1%} OOS={oos_wr:.1%} deg={degrad:.3f} → {'PASS' if wf_pass else 'FAIL (max -15pp)'}")

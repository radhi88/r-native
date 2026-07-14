"""Diagnose backtest parquet — find per-group win rates."""
import pandas as pd

df = pd.read_parquet("data/backtest/all_trades.parquet")
print(f"Total trades: {len(df)}")
print(f"Overall WR: {df['win'].mean():.1%}")
print(f"Columns: {list(df.columns)}")
print()

group_keys = ["symbol", "timeframe", "direction", "session", "atr_regime"]
available = [k for k in group_keys if k in df.columns]
print(f"Grouping by: {available}")

results = []
for vals, gdf in df.groupby(available):
    n = len(gdf)
    if n < 10:
        continue
    wr = float(gdf["win"].mean())
    wins_r = gdf.loc[gdf["win"], "pnl_r"].sum()
    loss_r = abs(gdf.loc[~gdf["win"], "pnl_r"].sum())
    pf = wins_r / max(loss_r, 0.001)
    mean_pnl = float(gdf["pnl_r"].mean())
    results.append({"group": vals, "n": n, "wr": wr, "pf": pf, "mean_r": mean_pnl})

results.sort(key=lambda x: x["wr"], reverse=True)

print("\nTop 15 groups by win rate:")
for r in results[:15]:
    print(f"  {str(r['group'])[:55]:<55} n={r['n']:>5} WR={r['wr']*100:.1f}% PF={r['pf']:.2f} avgR={r['mean_r']:.3f}")

passing_36 = [r for r in results if r["wr"] >= 0.36]
passing_pf = [r for r in results if r["wr"] >= 0.36 and r["pf"] >= 1.15]
print(f"\nGroups with WR>=36%: {len(passing_36)}")
print(f"Groups with WR>=36% AND PF>=1.15: {len(passing_pf)}")

# Session breakdown
print("\nSession win rates:")
for sess, sdf in df.groupby("session"):
    print(f"  {sess:<12} WR={sdf['win'].mean():.1%} n={len(sdf):>6}")

print("\nDirection win rates:")
for d, ddf in df.groupby("direction"):
    print(f"  {d:<6} WR={ddf['win'].mean():.1%} n={len(ddf):>6}")

print("\nTimeframe win rates:")
for tf, tdf in df.groupby("timeframe"):
    print(f"  {tf:<5} WR={tdf['win'].mean():.1%} n={len(tdf):>6}")

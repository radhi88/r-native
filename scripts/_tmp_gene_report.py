import json
from pathlib import Path

g = json.loads(Path("data/qader/dna/gene_store_backtest.json").read_bytes())
print("=== DNA Gene Store ===")
print(f"Generated: {g['generated'][:16]}")
print(f"Total genes: {g['gene_count']}")
for gene in g["genes"]:
    s   = gene["stats"]
    t   = gene["thresholds"]
    lp  = gene.get("live_performance", {})
    grp = gene.get("group", {})
    mc  = gene["validation"]["monte_carlo"]
    wf  = gene["validation"]["walk_forward"]
    print()
    print(f"Gene : {gene['gene_id']}")
    print(f"  Context  : {grp}")
    print(f"  Backtest : WR={s['win_rate']:.1%}  PF={s['profit_factor']:.2f}  Sharpe={s['sharpe']:.2f}  N={s['n_trades']}")
    print(f"  Entry    : min_conf={t['min_confidence']}  lot_scale={t['lot_scale']}x  SL={t['sl_atr_mult']}xATR  TP={t['tp_atr_mult']}xATR")
    print(f"  MC p5_dd : {mc['p5_max_dd_r']}R  threshold={mc['threshold_r']}R")
    print(f"  WalkFwd  : IS={wf['is_win_rate']:.1%}  OOS={wf['oos_win_rate']:.1%}  deg={wf['degradation']:.3f}")
    print(f"  Live     : trades={lp.get('trades',0)}  posterior={lp.get('bayesian_posterior','N/A')}  active={gene['active']}")

print()
print("=== Arbiter Weights File ===")
w = json.loads(Path("data/qader/dna/arbiter_gene_weights.json").read_bytes())
for k, v in w.items():
    print(f"  {k}: min_conf={v['min_confidence']}  lot={v['lot_scale']}  active={v['active']}")

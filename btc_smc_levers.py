"""btc_smc_levers.py — Can the REAL (but sub-cost) BTC sr_zone edge be lifted ABOVE
the spread by the only two honest levers: longer HORIZON or tighter SELECTIVITY?

Background (btc_smc_lab.py): sr_zone genuinely beats random directionally on BTC
(56.3%, z+17) but net-of-$10-spread is negative because the per-trade directional
$ edge < $10 spread. The spread is a FIXED $ cost. So:
  LEVER 1 (horizon): hold longer -> bigger directional $ move, SAME $10 spread.
  LEVER 2 (selectivity): only deepest zone extremes -> bigger per-trade $ edge.

Load-bearing number = NET $ per 1-unit trade = mean(vote * forward_move) - spread_$.
(Unambiguous: spread is a fixed price cost; no R/stop assumptions needed.)
Walk-forward 5 blocks (net$ must be + in >=4) + random-MC z. No lookahead.

CAVEATS (printed): (a) mark-to-market at horizon = NO stop, so net$ is an UPPER
bound (a real stop adds cost); (b) overlapping forward windows inflate significance
-> walk-forward consistency is the real guard, not the z alone.

Run: C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe C:\\Users\\Radhi\\MT5\\btc_smc_levers.py
"""
import sys, math
import numpy as np
import MetaTrader5 as mt5

np.random.seed(1234)
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


def liq_sweep(high, low, close, n=20):
    if len(close) < n + 1: return 0
    ph = max(high[-n - 1:-1]); pl = min(low[-n - 1:-1])
    if high[-1] > ph and close[-1] < ph: return -1
    if low[-1] < pl and close[-1] > pl: return 1
    return 0


def test_config(high, low, close, N, spread_price, signal, horizon, thr=None):
    """Returns dict of results for one (signal, horizon, thr) config. No lookahead."""
    start = max(WIN + 1, int(N * 0.45))
    end = N - horizon
    idx = []; votes = []; fwds = []
    for i in range(start, end):
        cw = close[:i + 1][-WIN:].tolist()
        hw = high[:i + 1][-WIN:].tolist()
        lw = low[:i + 1][-WIN:].tolist()
        if signal == "sr_zone":
            v = sr_zone(hw, lw, cw, thr=thr)
        else:
            v = liq_sweep(hw, lw, cw)
        if v == 0:
            continue
        fwd = close[i + horizon] - close[i]
        if fwd == 0:
            continue
        idx.append(i); votes.append(v); fwds.append(fwd)
    n = len(idx)
    if n < 50:
        return None
    idx = np.array(idx); votes = np.array(votes); fwds = np.array(fwds)
    dir_move = votes * fwds                       # signed $ move in the vote's direction
    net_dollar = dir_move - spread_price          # per 1-unit trade, net of spread
    hits = (votes == np.sign(fwds)).astype(int)
    pooled_hr = hits.mean()
    gross_d = dir_move.mean()
    net_d = net_dollar.mean()

    # random-MC baseline for net$ (same count, same vote-sign multiset, random bars)
    pool = np.arange(start, end)
    pf = close[pool + horizon] - close[pool]
    MC = 1500
    mc = np.empty(MC)
    sign_mix = votes.copy()
    for m in range(MC):
        pick = np.random.randint(0, len(pool), size=n)
        np.random.shuffle(sign_mix)
        mc[m] = (sign_mix * pf[pick] - spread_price).mean()
    z_net = (net_d - mc.mean()) / (mc.std(ddof=1) + 1e-12)

    # walk-forward 5 blocks (net$ > 0?)
    edges = np.linspace(start, end, N_BLOCKS + 1).astype(int)
    blk_net = []
    pos = 0
    for b in range(N_BLOCKS):
        mask = (idx >= edges[b]) & (idx < edges[b + 1])
        if mask.sum() == 0:
            blk_net.append(None); continue
        bn = net_dollar[mask].mean()
        blk_net.append(bn)
        if bn > 0: pos += 1
    return dict(n=n, hr=pooled_hr, gross=gross_d, net=net_d, z_net=z_net,
                blocks_pos=pos, blk_net=blk_net)


def main():
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    acc = mt5.account_info()
    print(f"account={acc.login} server={acc.server} balance={acc.balance}")
    print("LOAD-BEARING = NET $ per 1-unit trade (gross directional move - fixed spread).")
    print("UPPER BOUND: mark-to-market at horizon, NO stop. EDGE = net>0 AND >=4/5 blocks AND z>2.\n")

    targets = [
        ("BTCUSDm", mt5.TIMEFRAME_M5, "M5", 100000),
        ("BTCXAUm", mt5.TIMEFRAME_M15, "M15", 100000),
    ]
    horizons = [8, 16, 24, 48, 96]
    thrs = [0.20, 0.10, 0.05]
    summary = []
    for sym, tf, tag, nb in targets:
        info = mt5.symbol_info(sym)
        if info is None:
            mt5.symbol_select(sym, True); info = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)
        spread_price = (tick.ask - tick.bid) if tick else info.spread * info.point
        r = mt5.copy_rates_from_pos(sym, tf, 0, nb)
        if r is None or len(r) < 400:
            print(f"{sym}: insufficient bars"); continue
        high = np.asarray([float(x["high"]) for x in r])
        low = np.asarray([float(x["low"]) for x in r])
        close = np.asarray([float(x["close"]) for x in r])
        N = len(close)
        print(f"\n===== {sym} {tag}  bars={N}  spread=${spread_price:g} =====")

        # LEVER 1: horizon sweep (sr_zone thr=0.20, and liq_sweep)
        print("  -- LEVER 1: longer horizon (sr_zone thr0.20) --")
        for H in horizons:
            d = test_config(high, low, close, N, spread_price, "sr_zone", H, thr=0.20)
            if d:
                blks = "/".join("+" if (x is not None and x > 0) else "-" for x in d["blk_net"])
                print(f"     H={H:3d}: n={d['n']:5d} hit={d['hr']:.3f} gross=${d['gross']:+8.2f} "
                      f"NET=${d['net']:+8.2f} z={d['z_net']:+5.2f} blks[{blks}]={d['blocks_pos']}/5")
                summary.append((sym, f"sr_zone H{H}", d))
        for H in horizons:
            d = test_config(high, low, close, N, spread_price, "liq_sweep", H)
            if d:
                blks = "/".join("+" if (x is not None and x > 0) else "-" for x in d["blk_net"])
                print(f"     liq H={H:3d}: n={d['n']:5d} hit={d['hr']:.3f} gross=${d['gross']:+8.2f} "
                      f"NET=${d['net']:+8.2f} z={d['z_net']:+5.2f} blks[{blks}]={d['blocks_pos']}/5")
                summary.append((sym, f"liq_sweep H{H}", d))

        # LEVER 2: selectivity (deeper extremes) at horizons 8 and 48
        print("  -- LEVER 2: selectivity (deeper zone extremes) --")
        for H in (8, 48):
            for thr in thrs:
                d = test_config(high, low, close, N, spread_price, "sr_zone", H, thr=thr)
                if d:
                    blks = "/".join("+" if (x is not None and x > 0) else "-" for x in d["blk_net"])
                    print(f"     H={H:3d} thr={thr:.2f}: n={d['n']:5d} hit={d['hr']:.3f} "
                          f"gross=${d['gross']:+8.2f} NET=${d['net']:+8.2f} z={d['z_net']:+5.2f} "
                          f"blks[{blks}]={d['blocks_pos']}/5")
                    summary.append((sym, f"sr_zone H{H} thr{thr}", d))

    print("\n================  PASSES (net>0 AND blks>=4/5 AND z>2)  ================")
    any_edge = False
    for sym, name, d in summary:
        if d["net"] > 0 and d["blocks_pos"] >= 4 and d["z_net"] > 2.0:
            any_edge = True
            print(f"  *** {sym} {name}: NET=${d['net']:+.2f} blks={d['blocks_pos']}/5 z={d['z_net']:+.2f} n={d['n']}")
    if not any_edge:
        print("  NONE — no horizon/selectivity config clears net>0 + walk-forward + z>2.")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

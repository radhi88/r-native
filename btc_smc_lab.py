"""btc_smc_lab.py — Rigorous OOS test of the BTC sr_zone & liq_sweep SMC votes.

Reproduces the EXACT canonical signal logic from chart_read.py (_sr_zone, _liq_sweep)
and the scoring convention from r_native_v2/indicator_accuracy.py (HORIZON=8,
DEADBAND=0.0, no-lookahead inputs close[:i+1]).

Adds what indicator_accuracy.py does NOT do — the things that turn a "hit-rate"
into a tradeable verdict:
  1. WALK-FORWARD: 5 contiguous blocks; an edge must appear in ALL/most blocks.
  2. NET-OF-SPREAD expectancy in R (real MT5 spread, converted to R via the
     signal's stop distance = ATR-based, the way the live scalper would stop).
  3. RANDOM BASELINE: same trade count + same direction mix, z-score vs random.

Verdict EDGE only if it survives walk-forward AND net-of-spread AND beats random (z>2).

Run:  C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe C:\\Users\\Radhi\\MT5\\btc_smc_lab.py
"""
import sys, math, random
import numpy as np
import MetaTrader5 as mt5

random.seed(1234)
np.random.seed(1234)

# ---- EXACT signal logic copied verbatim from chart_read.py:232-250 -----------
def _sr_zone(high, low, close, n=50):
    if len(close) < n: return 0
    hi = max(high[-n:]); lo = min(low[-n:]); rng = hi - lo
    if rng <= 0: return 0
    pos = (close[-1] - lo) / rng
    if pos <= 0.20: return 1
    if pos >= 0.80: return -1
    return 0

def _liq_sweep(high, low, close, n=20):
    if len(close) < n + 1: return 0
    ph = max(high[-n - 1:-1]); pl = min(low[-n - 1:-1])
    if high[-1] > ph and close[-1] < ph: return -1
    if low[-1] < pl and close[-1] > pl: return 1
    return 0

# ---- scoring constants from indicator_accuracy.py ----------------------------
HORIZON = 8          # bars ahead to judge (indicator_accuracy.py:32)
WIN = 120            # rolling window fed to the vote (indicator_accuracy.py:31)
DEADBAND = 0.0       # any non-zero forward move counts (indicator_accuracy.py:33)
N_BLOCKS = 5

def atr(high, low, close, i, period=14):
    """Wilder-ish simple ATR over the period ENDING at bar i (no lookahead)."""
    if i < period: return None
    trs = []
    for j in range(i - period + 1, i + 1):
        tr = max(high[j] - low[j],
                 abs(high[j] - close[j - 1]),
                 abs(low[j] - close[j - 1]))
        trs.append(tr)
    return sum(trs) / len(trs)

def run_symbol(sym, tf_const, tf_name, n_bars, spread_price):
    r = mt5.copy_rates_from_pos(sym, tf_const, 0, n_bars)
    if r is None or len(r) < 400:
        print(f"  {sym}: insufficient bars"); return None
    high = np.asarray([float(x["high"]) for x in r])
    low = np.asarray([float(x["low"]) for x in r])
    close = np.asarray([float(x["close"]) for x in r])
    N = len(close)
    print(f"\n===== {sym} {tf_name}  bars={N}  real spread={spread_price:g} (price units) =====")

    # Scoring loop mirrors indicator_accuracy.measure: start at max(WIN+1, 45% of N),
    # judge to close[i+HORIZON]. We evaluate the vote on the trailing WIN slice <= i,
    # so it is the SAME no-lookahead computation the accuracy file uses.
    start = max(WIN + 1, int(N * 0.45))
    end = N - HORIZON

    # collect per-trade records: (i, signal_name, vote, fwd_R_gross, atr_at_i)
    recs = {"sr_zone": [], "liq_sweep": []}
    for i in range(start, end):
        h = high[:i + 1]; l = low[:i + 1]; c = close[:i + 1]
        hw, lw, cw = h[-WIN:].tolist(), l[-WIN:].tolist(), c[-WIN:].tolist()
        fwd = close[i + HORIZON] - close[i]
        if abs(fwd) <= DEADBAND:
            continue
        a = atr(high, low, close, i)
        if a is None or a <= 0:
            continue
        sr = _sr_zone(hw, lw, cw)
        ls = _liq_sweep(hw, lw, cw)
        for name, vote in (("sr_zone", sr), ("liq_sweep", ls)):
            if vote == 0:
                continue
            # gross directional R: signed forward move in ATR units, in the vote's direction.
            # stop distance assumed = 1*ATR (typical scalper SL); R = (vote*fwd)/ATR.
            r_gross = (vote * fwd) / a
            recs[name].append((i, vote, r_gross, a, fwd))

    out = {}
    for name, rows in recs.items():
        if not rows:
            print(f"  {name}: NO trades"); continue
        rows.sort(key=lambda x: x[0])
        idx = np.array([x[0] for x in rows])
        votes = np.array([x[1] for x in rows])
        r_gross = np.array([x[2] for x in rows])
        atrs = np.array([x[3] for x in rows])
        fwds = np.array([x[4] for x in rows])

        # spread cost per trade in R: spread (price) / stop-distance (=ATR price).
        # You pay the spread on entry; subtract it from every trade's R.
        spread_R = spread_price / atrs
        r_net = r_gross - spread_R

        hits = (votes == np.sign(fwds)).astype(int)  # directional hit (==indicator_accuracy)
        pooled_hr = hits.mean()
        n = len(rows)
        # random baseline directional hit-rate = P(matching the realized sign) given the
        # vote-direction mix. For a fair baseline we use the realized up-rate of the moves
        # and the vote mix; simplest honest baseline = 0.5 (coin flip on direction), plus
        # a Monte-Carlo baseline below for net-R.
        base_hr = 0.5
        # z for hit-rate vs 0.5
        se = math.sqrt(0.25 / n)
        z_hr = (pooled_hr - base_hr) / se

        # ---- net expectancy ----
        exp_net = r_net.mean()
        exp_gross = r_gross.mean()
        sd_net = r_net.std(ddof=1) if n > 1 else 0.0

        # ---- random baseline for NET expectancy (Monte-Carlo) ----
        # Same count, same vote-direction mix, but entries at RANDOM bars in [start,end).
        # We resample random bar indices, apply the SAME vote signs, compute net R, repeat.
        pool_i = np.arange(start, end)
        # precompute per-bar atr & fwd for the whole eligible range for fast sampling
        bar_atr = {}; bar_fwd = {}
        for bi in pool_i:
            a = atr(high, low, close, bi)
            if a is None or a <= 0:
                continue
            bar_atr[bi] = a
            bar_fwd[bi] = close[bi + HORIZON] - close[bi]
        valid_bars = np.array([b for b in pool_i if b in bar_atr])
        va = np.array([bar_atr[b] for b in valid_bars])
        vf = np.array([bar_fwd[b] for b in valid_bars])
        MC = 2000
        mc_exp = np.empty(MC)
        mc_hr = np.empty(MC)
        sign_mix = votes.copy()
        for m in range(MC):
            pick = np.random.randint(0, len(valid_bars), size=n)
            ra = va[pick]; rf = vf[pick]
            # assign the same multiset of vote-signs randomly to these random bars
            np.random.shuffle(sign_mix)
            rg = (sign_mix * rf) / ra
            rn = rg - (spread_price / ra)
            mc_exp[m] = rn.mean()
            mc_hr[m] = (sign_mix == np.sign(rf)).mean()
        mc_mean = mc_exp.mean(); mc_sd = mc_exp.std(ddof=1)
        z_net_vs_random = (exp_net - mc_mean) / mc_sd if mc_sd > 0 else 0.0
        z_hr_vs_random = (pooled_hr - mc_hr.mean()) / (mc_hr.std(ddof=1) + 1e-12)

        # ---- walk-forward: 5 contiguous blocks by bar index ----
        edges = np.linspace(start, end, N_BLOCKS + 1).astype(int)
        block_lines = []
        blocks_pos_net = 0; blocks_hr_above = 0
        for b in range(N_BLOCKS):
            lo_e, hi_e = edges[b], edges[b + 1]
            mask = (idx >= lo_e) & (idx < hi_e)
            if mask.sum() == 0:
                block_lines.append(f"      blk{b+1}: n=0")
                continue
            bhr = hits[mask].mean()
            bnet = r_net[mask].mean()
            bgross = r_gross[mask].mean()
            cnt = int(mask.sum())
            if bnet > 0: blocks_pos_net += 1
            if bhr > 0.5: blocks_hr_above += 1
            block_lines.append(f"      blk{b+1}: n={cnt:4d}  hit={bhr:.3f}  "
                               f"gross={bgross:+.4f}R  NET={bnet:+.4f}R")

        out[name] = dict(n=n, pooled_hr=pooled_hr, z_hr=z_hr,
                         exp_gross=exp_gross, exp_net=exp_net, sd_net=sd_net,
                         z_net_vs_random=z_net_vs_random, z_hr_vs_random=z_hr_vs_random,
                         mc_mean=mc_mean, mc_sd=mc_sd, mc_hr=mc_hr.mean(),
                         blocks_pos_net=blocks_pos_net, blocks_hr_above=blocks_hr_above,
                         block_lines=block_lines, atr_mean=atrs.mean(), spread_R=spread_R.mean(),
                         bull=int((votes == 1).sum()), bear=int((votes == -1).sum()))

        d = out[name]
        print(f"\n  --- {name} ---")
        print(f"    trades={n}  (bull={d['bull']} bear={d['bear']})  mean_ATR={d['atr_mean']:.2f}  "
              f"spread_cost={d['spread_R']:.4f}R/trade")
        print(f"    POOLED hit-rate = {pooled_hr:.4f}  (random=0.5)  z_vs_0.5={z_hr:+.2f}  "
              f"z_vs_randomMC={d['z_hr_vs_random']:+.2f}")
        print(f"    expectancy  GROSS={exp_gross:+.4f}R   NET-of-spread={exp_net:+.4f}R  (sd={sd_net:.3f})")
        print(f"    random-MC net mean={mc_mean:+.4f}R sd={mc_sd:.4f}  ->  z(net vs random)={z_net_vs_random:+.2f}")
        print(f"    walk-forward (NET must be + in all/most blocks):")
        for ln in block_lines:
            print(ln)
        print(f"    blocks with NET>0: {d['blocks_pos_net']}/{N_BLOCKS}   "
              f"blocks with hit>0.5: {d['blocks_hr_above']}/{N_BLOCKS}")
    return out


def verdict_for(d):
    if d is None:
        return "INCONCLUSIVE"
    wf_ok = d["blocks_pos_net"] >= 4         # NET positive in >=4 of 5 blocks
    net_ok = d["exp_net"] > 0
    rand_ok = d["z_net_vs_random"] > 2.0 and d["z_hr_vs_random"] > 2.0
    if wf_ok and net_ok and rand_ok:
        return "EDGE"
    # if it's clearly negative / random everywhere -> NO_EDGE; borderline -> INCONCLUSIVE
    if d["exp_net"] <= 0 or d["z_net_vs_random"] <= 0:
        return "NO_EDGE"
    return "INCONCLUSIVE"


def main():
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    acc = mt5.account_info()
    print(f"account={acc.login} server={acc.server} balance={acc.balance}")

    targets = [
        ("BTCUSDm", mt5.TIMEFRAME_M5, "M5", 100000),
        ("BTCXAUm", mt5.TIMEFRAME_M15, "M15", 100000),
    ]
    all_out = {}
    for sym, tf, tag, nb in targets:
        info = mt5.symbol_info(sym)
        if info is None:
            mt5.symbol_select(sym, True); info = mt5.symbol_info(sym)
        if info is None:
            print(f"{sym}: not available"); continue
        tick = mt5.symbol_info_tick(sym)
        spread_price = (tick.ask - tick.bid) if tick else info.spread * info.point
        res = run_symbol(sym, tf, tag, nb, spread_price)
        if res:
            for name, d in res.items():
                all_out[(sym, name)] = d

    print("\n\n================  VERDICT SUMMARY  ================")
    for (sym, name), d in all_out.items():
        v = verdict_for(d)
        print(f"  {sym:9s} {name:10s} -> {v:12s}  "
              f"poolHR={d['pooled_hr']:.3f} net={d['exp_net']:+.4f}R "
              f"z_net={d['z_net_vs_random']:+.2f} z_hr={d['z_hr_vs_random']:+.2f} "
              f"blksNET+={d['blocks_pos_net']}/{N_BLOCKS} n={d['n']}")
    mt5.shutdown()
    return 0

if __name__ == "__main__":
    sys.exit(main())

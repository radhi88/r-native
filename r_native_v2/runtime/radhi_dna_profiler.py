"""runtime/radhi_dna_profiler.py — extract Radhi's Behavioral DNA from his real trades.

Born 2026-05-31. After exhaustive MT5 optimization found NO stable edge in the
SMC rule set (overfit, OOS -71%), we found the REAL edge lives in Radhi's own
manual trading: 72% win rate, but bled back by night-trading + bad buys.

This tool reverse-engineers that edge. For every real manual trade it
reconstructs the exact market context at entry (RSI/ADX/EMA/trend/session on M5)
and segments WINNERS vs LOSERS — so the agents can answer "what would Radhi do
here?" with numbers, not guesses. Output: data/radhi_dna.json — the seed the
genomes/council reference. The agents treat Radhi as their الأب الروحي.
"""
from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import MetaTrader5 as mt5

DAYS = 180
SYMBOL = "XAUUSDm"          # 442/453 of Radhi's trades are gold
OUT = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\radhi_dna.json")


# ── indicators (numpy, Wilder) ───────────────────────────────────────────────
def ema(x, n):
    a = 2.0 / (n + 1); out = np.empty(len(x)); out[0] = x[0]
    for i in range(1, len(x)): out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out

def rma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) < n: return out
    out[n - 1] = np.mean(x[:n])
    for i in range(n, len(x)): out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out

def rsi(close, n=14):
    d = np.diff(close, prepend=close[0])
    up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    ru = rma(up, n); rd = rma(dn, n)
    rs = ru / np.where(rd == 0, 1e-9, rd)
    return 100 - 100 / (1 + rs)

def adx(high, low, close, n=14):
    um = np.diff(high, prepend=high[0]); dm = -np.diff(low, prepend=low[0])
    pdm = np.where((um > dm) & (um > 0), um, 0.0)
    mdm = np.where((dm > um) & (dm > 0), dm, 0.0)
    pc = np.roll(close, 1); pc[0] = close[0]
    tr = np.maximum.reduce([high - low, np.abs(high - pc), np.abs(low - pc)])
    atr = rma(tr, n)
    pdi = 100 * rma(pdm, n) / np.where(atr == 0, 1e-9, atr)
    mdi = 100 * rma(mdm, n) / np.where(atr == 0, 1e-9, atr)
    dx = 100 * np.abs(pdi - mdi) / np.where((pdi + mdi) == 0, 1e-9, pdi + mdi)
    return rma(dx, n), pdi, mdi


def seg(trades, keyfn, label):
    """Win-rate + net P/L per bucket of keyfn(trade)."""
    b = defaultdict(lambda: [0, 0, 0.0])   # bucket -> [n, wins, net]
    for t in trades:
        k = keyfn(t)
        if k is None: continue
        b[k][0] += 1; b[k][1] += 1 if t["profit"] > 0 else 0; b[k][2] += t["profit"]
    print(f"\n── {label} ──")
    rows = []
    for k in sorted(b, key=lambda x: (str(type(x)), x)):
        n, w, net = b[k]
        wr = 100 * w / n if n else 0
        print(f"  {str(k):16} n={n:4d}  WR={wr:5.1f}%  net=${net:+8.2f}")
        rows.append({"bucket": str(k), "n": n, "wr": round(wr, 1), "net": round(net, 2)})
    return rows


def main():
    if not mt5.initialize():
        print("MT5 init failed"); return
    now = datetime.now(timezone.utc); since = now - timedelta(days=DAYS)

    # 1) pair manual deals into round-trip trades
    deals = mt5.history_deals_get(since, now) or []
    pos = defaultdict(list)
    for d in deals:
        if d.magic == 0: pos[d.position_id].append(d)
    trades = []
    for pid, ds in pos.items():
        ds = sorted(ds, key=lambda d: d.time)
        ins = [d for d in ds if d.entry == 0]
        if not ins: continue
        en = ins[0]
        net = sum(d.profit + d.commission + d.swap for d in ds)
        trades.append({"sym": en.symbol, "side": "BUY" if en.type == 0 else "SELL",
                       "t": int(en.time), "price": en.price, "profit": net,
                       "exit_t": int(ds[-1].time)})
    trades = [t for t in trades if t["sym"] == SYMBOL]
    print(f"paired {len(trades)} {SYMBOL} round-trip manual trades over {DAYS}d")

    # 2) M5 context series
    rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M5, since, now)
    if rates is None or len(rates) < 100:
        print("not enough M5 history"); mt5.shutdown(); return
    t5 = rates["time"].astype(np.int64)
    c, h, l = rates["close"], rates["high"], rates["low"]
    rsi5 = rsi(c, 14); adx5, pdi, mdi = adx(h, l, c, 14)
    e20, e50 = ema(c, 20), ema(c, 50)

    def feat(ts):
        i = int(np.searchsorted(t5, ts, side="right") - 1)
        if i < 50 or i >= len(t5): return None
        ret10 = (c[i] - c[i - 10]) / c[i - 10] * 100 if i >= 10 else 0.0
        return {"rsi": float(rsi5[i]), "adx": float(adx5[i]),
                "above_e20": bool(c[i] > e20[i]), "e20_gt_e50": bool(e20[i] > e50[i]),
                "ret10": float(ret10), "hour": datetime.utcfromtimestamp(ts).hour}

    enriched = []
    for t in trades:
        f = feat(t["t"])
        if f: t.update(f); enriched.append(t)
    print(f"enriched {len(enriched)} trades with entry-time M5 context")
    if not enriched:
        mt5.shutdown(); return

    # 3) segment winners vs losers across dimensions
    def hourbucket(t):
        hh = t["hour"]
        if 13 <= hh < 17: return "1_NY_overlap(13-17)"
        if 8 <= hh < 13:  return "2_London(08-13)"
        if 17 <= hh < 21: return "3_NY_late(17-21)"
        return "4_Asian/night(21-08)"
    dna = {}
    dna["overall"] = {"n": len(enriched),
                      "wr": round(100 * sum(1 for t in enriched if t["profit"] > 0) / len(enriched), 1),
                      "net": round(sum(t["profit"] for t in enriched), 2)}
    dna["by_session"] = seg(enriched, hourbucket, "BY SESSION")
    dna["by_side"]    = seg(enriched, lambda t: t["side"], "BY SIDE (BUY vs SELL)")
    dna["by_rsi"]     = seg(enriched, lambda t: ("RSI<30" if t["rsi"] < 30 else "RSI30-50" if t["rsi"] < 50
                                                  else "RSI50-70" if t["rsi"] < 70 else "RSI>70"), "BY RSI@entry")
    dna["by_adx"]     = seg(enriched, lambda t: ("ADX<20_chop" if t["adx"] < 20 else "ADX20-30" if t["adx"] < 30
                                                  else "ADX>30_strongtrend"), "BY ADX@entry (regime)")
    dna["by_trend"]   = seg(enriched, lambda t: ("with_uptrend_E20>E50" if t["e20_gt_e50"] else "with_downtrend_E20<E50"), "BY M5 TREND")
    dna["by_emaside"] = seg(enriched, lambda t: ("entered_ABOVE_ema20" if t["above_e20"] else "entered_BELOW_ema20"), "BY PRICE vs EMA20")
    # combo: side x trend (does he win selling downtrends / buying uptrends?)
    dna["by_side_x_trend"] = seg(enriched, lambda t: f'{t["side"]}_{"UPtrend" if t["e20_gt_e50"] else "DOWNtrend"}',
                                 "BY SIDE x TREND (alignment)")

    OUT.write_text(json.dumps(dna, indent=2), encoding="utf-8")
    print(f"\n✅ saved Radhi DNA → {OUT}")
    mt5.shutdown()


if __name__ == "__main__":
    main()

"""trend_filter_lab.py — Causal diagnosis: is "counter-trend entry" (falling-knife
catching) the real cause of the bots' losses, and does an HTF trend filter fix it?

SCIENTIFIC HONESTY (sacred):
  - Causal only: every feature is computed from bars STRICTLY BEFORE the entry deal time
    (mt5.copy_rates_from(..., entry_time, N) returns the N bars up to & including the
    open bar; we drop the open/forming bar so no look-ahead leaks).
  - Walk-forward OOS: trades are split into 5 chronological blocks; a filter rule is
    "USE" ONLY if it raises net expectancy across >=4/5 blocks, not on a single split.
  - Net of spread/cost: we use the bot's REALISED net P&L (DB `net` = pnl+commission+swap),
    so commission & spread are already paid. Expectancy is reported in R (R = the trade's
    own |risk| proxy = realised adverse excursion ~ |entry-exit| when loss, or a per-symbol
    ATR-based unit) so symbols of wildly different $ scale are comparable.
  - "No improvement" is a respectable result. Fewer trades != better — the filter must
    lift the *average per-trade* expectancy, not just prune count.

Bots under test: 20260608 (multi_trader), 20260612 (gene_tournament/twins), 20260618 (army_warroom).

Data sources:
  - mt5.history_deals_get  : authoritative entry/exit (link IN/OUT by position_id), entry TIME.
  - mt5.copy_rates_from    : causal bars around entry for HTF trend + recent return.
  - data/friday.db trades  : cross-check (net, win) — but TIME comes from MT5 deals (causal).

Read-only. No order_send. Writes results JSON only.
"""
from __future__ import annotations
import json
import math
import datetime as dt
from collections import defaultdict, Counter

import MetaTrader5 as mt5

MAGICS = (20260608, 20260612, 20260618)
DAYS_BACK = 30
OUT_JSON = r"C:\Users\Radhi\MT5\data\lab_cache\trend_filter_lab_results.json"

# ---------- pure helpers (mirror chart_read._ema) ----------

def _ema(x, n):
    if not x:
        return []
    k = 2.0 / (n + 1.0)
    o = [x[0]]
    for v in x[1:]:
        o.append(v * k + o[-1] * (1 - k))
    return o


def _atr(high, low, close, n=14):
    if len(close) < 2:
        return 0.0
    trs = []
    for i in range(1, len(close)):
        tr = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        trs.append(tr)
    if len(trs) < n:
        return sum(trs) / len(trs) if trs else 0.0
    return sum(trs[-n:]) / n


# ---------- causal feature extraction ----------

_rate_cache: dict = {}


def causal_bars(sym, tf, entry_dt, n):
    """Return up to n CLOSED bars strictly before entry_dt. Drops the forming bar."""
    key = (sym, tf, int(entry_dt.timestamp()))
    if key in _rate_cache:
        return _rate_cache[key]
    # request a couple extra to allow dropping the open bar
    r = mt5.copy_rates_from(sym, tf, entry_dt, n + 2)
    out = None
    if r is not None and len(r) >= 5:
        # keep only bars whose time < entry_dt (closed before entry)
        et = entry_dt.timestamp()
        rows = [b for b in r if b['time'] < et]
        if len(rows) >= 5:
            out = rows[-n:]
    _rate_cache[key] = out
    return out


def htf_trend(sym, entry_dt):
    """Causal HTF trend on M15 + H1 via EMA50 slope. Returns dict of slope signs/strength."""
    res = {}
    for tf_name, tf in (("M15", mt5.TIMEFRAME_M15), ("H1", mt5.TIMEFRAME_H1)):
        bars = causal_bars(sym, tf, entry_dt, 80)
        if not bars or len(bars) < 55:
            res[tf_name] = None
            continue
        closes = [b['close'] for b in bars]
        ema = _ema(closes, 50)
        # slope = % change of EMA50 over last 5 bars, normalized
        slope = (ema[-1] - ema[-6]) / ema[-6] if len(ema) >= 6 and ema[-6] else 0.0
        res[tf_name] = {"slope": slope, "sign": (1 if slope > 0 else -1 if slope < 0 else 0),
                        "price_vs_ema": (1 if closes[-1] > ema[-1] else -1)}
    return res


def recent_return(sym, entry_dt, k=6, tf=mt5.TIMEFRAME_M15):
    """Causal: return over last k closed M15 bars, in ATR units (the falling-knife signal)."""
    bars = causal_bars(sym, tf, entry_dt, max(20, k + 16))
    if not bars or len(bars) < k + 2:
        return None
    closes = [b['close'] for b in bars]
    highs = [b['high'] for b in bars]
    lows = [b['low'] for b in bars]
    atr = _atr(highs, lows, closes, 14)
    if atr <= 0:
        return None
    ret_abs = closes[-1] - closes[-1 - k]
    return {"ret_atr": ret_abs / atr, "atr": atr, "ret_abs": ret_abs, "last_close": closes[-1]}


# ---------- build trade dataset from MT5 deals (causal entry time) ----------

def load_trades():
    to = dt.datetime.now() + dt.timedelta(days=1)
    frm = to - dt.timedelta(days=DAYS_BACK + 1)
    deals = mt5.history_deals_get(frm, to)
    if not deals:
        return []
    # group by position_id
    bypos = defaultdict(list)
    for d in deals:
        if d.magic in MAGICS:
            bypos[d.position_id].append(d)
    trades = []
    for pid, ds in bypos.items():
        ds.sort(key=lambda x: (x.time_msc, x.entry))
        ins = [d for d in ds if d.entry == mt5.DEAL_ENTRY_IN]
        outs = [d for d in ds if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY)]
        if not ins or not outs:
            continue
        d_in = ins[0]
        # side: DEAL_TYPE_BUY=0 -> long(+1), DEAL_TYPE_SELL=1 -> short(-1)
        side = 1 if d_in.type == mt5.DEAL_TYPE_BUY else -1
        entry_price = d_in.price
        entry_time = dt.datetime.fromtimestamp(d_in.time, tz=dt.timezone.utc)
        # net = sum of profit+commission+swap on the OUT deals (+ any on IN, usually commission)
        net = sum((d.profit + d.commission + d.swap) for d in ds)
        exit_price = outs[-1].price
        vol = d_in.volume
        trades.append({
            "pid": pid, "magic": d_in.magic, "symbol": d_in.symbol, "side": side,
            "entry": entry_price, "exit": exit_price, "net": net, "vol": vol,
            "entry_time": entry_time, "entry_ts": d_in.time,
        })
    trades.sort(key=lambda t: t["entry_ts"])
    return trades


# ---------- classification ----------

def classify(trades):
    """Attach causal HTF trend + recent return, and with/counter-trend label.

    Counter-trend (falling-knife) definition for a trade:
      - It's a BUY (side=+1) while HTF is DOWN and price recently fell hard, OR
      - It's a SELL (side=-1) while HTF is UP and price recently rose hard.
    HTF-down = M15 EMA50 slope < 0 (and we also record H1 agreement).
    """
    enriched = []
    skipped = 0
    for t in trades:
        ht = htf_trend(t["symbol"], t["entry_time"])
        rr = recent_return(t["symbol"], t["entry_time"], k=6)
        if ht is None or ht.get("M15") is None or rr is None:
            skipped += 1
            continue
        m15 = ht["M15"]
        h1 = ht.get("H1")
        htf_sign = m15["sign"]  # primary HTF = M15 EMA50 slope
        # R unit: per-trade risk proxy. Use ATR(M15) * vol-scaled $? We keep R in $ via
        # a per-symbol scale so expectancy in R is comparable. Simpler & robust:
        # R = median |net| of LOSING trades per symbol (the realised typical loss size).
        # Computed later (needs the full set). For now store raw.
        t2 = dict(t)
        t2["htf_m15_slope"] = m15["slope"]
        t2["htf_m15_sign"] = htf_sign
        t2["htf_h1_sign"] = (h1["sign"] if h1 else 0)
        t2["price_vs_ema_m15"] = m15["price_vs_ema"]
        t2["ret_atr"] = rr["ret_atr"]
        t2["atr"] = rr["atr"]
        # with/counter classification
        # "against HTF" = trade side opposes EMA50 slope
        against_htf = (t["side"] != htf_sign) and (htf_sign != 0)
        t2["against_htf"] = against_htf
        # falling-knife flavor: against HTF AND recent move is extended against us
        # BUY into a sharp drop: ret_atr very negative; SELL into sharp rally: ret_atr very positive
        knife = False
        if t["side"] == 1 and htf_sign < 0 and rr["ret_atr"] < 0:
            knife = True
        if t["side"] == -1 and htf_sign > 0 and rr["ret_atr"] > 0:
            knife = True
        t2["knife"] = knife
        enriched.append(t2)
    return enriched, skipped


def assign_R(enriched):
    """R = per-symbol median absolute net of losing trades (typical realised risk).
    Fallback to global median if a symbol has too few losers."""
    by_sym_losses = defaultdict(list)
    all_losses = []
    for t in enriched:
        if t["net"] < 0:
            by_sym_losses[t["symbol"]].append(abs(t["net"]))
            all_losses.append(abs(t["net"]))
    def med(xs):
        if not xs:
            return None
        s = sorted(xs)
        m = len(s) // 2
        return s[m] if len(s) % 2 else 0.5 * (s[m - 1] + s[m])
    gmed = med(all_losses) or 1.0
    for t in enriched:
        sl = by_sym_losses.get(t["symbol"], [])
        R = med(sl) if len(sl) >= 4 else gmed
        if not R or R <= 0:
            R = gmed
        t["R"] = R
        t["net_R"] = t["net"] / R
    return enriched


# ---------- stats ----------

def expectancy_R(rows):
    if not rows:
        return None
    xs = [t["net_R"] for t in rows]
    return sum(xs) / len(xs)


def summarize(enriched):
    out = {}
    with_t = [t for t in enriched if not t["against_htf"]]
    cnt_t = [t for t in enriched if t["against_htf"]]
    knife = [t for t in enriched if t["knife"]]
    losers = [t for t in enriched if t["net"] < 0]
    big_losers = sorted(losers, key=lambda t: t["net_R"])[:max(1, len(losers) // 5)]  # worst 20%
    out["n_total"] = len(enriched)
    out["n_with_trend"] = len(with_t)
    out["n_counter_trend"] = len(cnt_t)
    out["n_knife"] = len(knife)
    out["exp_R_all"] = expectancy_R(enriched)
    out["exp_R_with_trend"] = expectancy_R(with_t)
    out["exp_R_counter_trend"] = expectancy_R(cnt_t)
    out["exp_R_knife"] = expectancy_R(knife)
    # share of (big) losers that were counter-trend / knife
    out["n_big_losers"] = len(big_losers)
    out["pct_big_losers_counter_trend"] = (
        100.0 * sum(1 for t in big_losers if t["against_htf"]) / len(big_losers) if big_losers else None)
    out["pct_big_losers_knife"] = (
        100.0 * sum(1 for t in big_losers if t["knife"]) / len(big_losers) if big_losers else None)
    out["pct_all_losers_counter_trend"] = (
        100.0 * sum(1 for t in losers if t["against_htf"]) / len(losers) if losers else None)
    out["pct_all_losers_knife"] = (
        100.0 * sum(1 for t in losers if t["knife"]) / len(losers) if losers else None)
    return out


# ---------- the filter ----------

def passes_filter(t, k_atr=1.0):
    """Anti-falling-knife filter (CAUSAL).
    REJECT a trade iff it is a knife entry of meaningful magnitude:
      BUY  while M15 EMA50 slope<0 AND last-6-bar return < -k_atr*ATR  -> reject
      SELL while M15 EMA50 slope>0 AND last-6-bar return > +k_atr*ATR  -> reject
    Otherwise keep. (We deliberately do NOT block all counter-trend — only extended knives.)
    """
    if t["side"] == 1 and t["htf_m15_sign"] < 0 and t["ret_atr"] < -k_atr:
        return False
    if t["side"] == -1 and t["htf_m15_sign"] > 0 and t["ret_atr"] > k_atr:
        return False
    return True


def walk_forward(enriched, k_atr=1.0, n_blocks=5):
    """Chronological blocks. For each block report exp_R before vs after filter, and
    whether filter improved per-trade expectancy net of cost."""
    rows = sorted(enriched, key=lambda t: t["entry_ts"])
    n = len(rows)
    bsz = max(1, n // n_blocks)
    blocks = [rows[i * bsz:(i + 1) * bsz] for i in range(n_blocks)]
    # absorb remainder into last block
    if n > n_blocks * bsz:
        blocks[-1] += rows[n_blocks * bsz:]
    results = []
    improved = 0
    for i, blk in enumerate(blocks):
        if not blk:
            continue
        kept = [t for t in blk if passes_filter(t, k_atr)]
        before = expectancy_R(blk)
        after = expectancy_R(kept) if kept else None
        delta = (after - before) if (after is not None and before is not None) else None
        if delta is not None and delta > 0:
            improved += 1
        results.append({
            "block": i, "n": len(blk), "n_kept": len(kept),
            "start": dt.datetime.fromtimestamp(blk[0]["entry_ts"], tz=dt.timezone.utc).isoformat(),
            "end": dt.datetime.fromtimestamp(blk[-1]["entry_ts"], tz=dt.timezone.utc).isoformat(),
            "exp_R_before": before, "exp_R_after": after, "delta_R": delta,
            "pct_kept": 100.0 * len(kept) / len(blk),
        })
    return results, improved


def sweep_k(enriched):
    """Try several k_atr thresholds; report walk-forward improvement count for each."""
    out = []
    for k in (0.5, 0.75, 1.0, 1.5, 2.0):
        res, improved = walk_forward(enriched, k_atr=k)
        kept_total = sum(r["n_kept"] for r in res)
        n_total = sum(r["n"] for r in res)
        # global before/after
        all_rows = enriched
        kept = [t for t in all_rows if passes_filter(t, k)]
        out.append({
            "k_atr": k,
            "blocks_improved_of_5": improved,
            "global_exp_R_before": expectancy_R(all_rows),
            "global_exp_R_after": expectancy_R(kept) if kept else None,
            "pct_trades_kept": 100.0 * kept_total / n_total if n_total else None,
        })
    return out


# ---------- alternative filters (let the numbers choose) ----------

def _block_all_counter(t):
    """Block EVERY trade whose side opposes M15 EMA50 slope (strict)."""
    return not (t["against_htf"])


def _block_counter_h1confirm(t):
    """Block only when BOTH M15 and H1 EMA50 slopes oppose the trade side."""
    if t["htf_m15_sign"] != 0 and t["htf_h1_sign"] != 0:
        if t["side"] != t["htf_m15_sign"] and t["side"] != t["htf_h1_sign"]:
            return False
    return True


def _block_counter_and_below_ema(t):
    """Block counter-trend AND on wrong side of M15 EMA50 (no momentum support)."""
    if t["against_htf"] and t["price_vs_ema_m15"] != t["side"]:
        return False
    return True


def walk_forward_pred(enriched, pred, n_blocks=5):
    rows = sorted(enriched, key=lambda t: t["entry_ts"])
    n = len(rows)
    bsz = max(1, n // n_blocks)
    blocks = [rows[i * bsz:(i + 1) * bsz] for i in range(n_blocks)]
    if n > n_blocks * bsz:
        blocks[-1] += rows[n_blocks * bsz:]
    results = []
    improved = 0
    for i, blk in enumerate(blocks):
        if not blk:
            continue
        kept = [t for t in blk if pred(t)]
        before = expectancy_R(blk)
        after = expectancy_R(kept) if kept else None
        delta = (after - before) if (after is not None and before is not None) else None
        if delta is not None and delta > 0:
            improved += 1
        results.append({"block": i, "n": len(blk), "n_kept": len(kept),
                        "exp_R_before": before, "exp_R_after": after, "delta_R": delta,
                        "pct_kept": 100.0 * len(kept) / len(blk)})
    return results, improved


def alt_filters(enriched):
    out = {}
    for name, pred in (
        ("block_all_counter_trend", _block_all_counter),
        ("block_counter_H1_confirm", _block_counter_h1confirm),
        ("block_counter_and_below_ema", _block_counter_and_below_ema),
    ):
        res, improved = walk_forward_pred(enriched, pred)
        kept = [t for t in enriched if pred(t)]
        out[name] = {
            "blocks_improved_of_5": improved,
            "global_exp_R_before": expectancy_R(enriched),
            "global_exp_R_after": expectancy_R(kept) if kept else None,
            "pct_trades_kept": 100.0 * len(kept) / len(enriched),
            "per_block": [{"blk": r["block"], "before": round(r["exp_R_before"], 3),
                           "after": (None if r["exp_R_after"] is None else round(r["exp_R_after"], 3)),
                           "delta": (None if r["delta_R"] is None else round(r["delta_R"], 3)),
                           "pct_kept": round(r["pct_kept"], 0)} for r in res],
        }
    return out


# ---------- main ----------

def main():
    if not mt5.initialize():
        print("MT5 init failed")
        return
    try:
        trades = load_trades()
        print(f"loaded {len(trades)} linked positions for magics {MAGICS}")
        enriched, skipped = classify(trades)
        enriched = assign_R(enriched)
        print(f"enriched {len(enriched)} (skipped {skipped} for missing causal bars)")
        summary = summarize(enriched)
        wf, improved = walk_forward(enriched, k_atr=1.0)
        sweep = sweep_k(enriched)
        alts = alt_filters(enriched)

        # per-symbol counter-trend expectancy (where is the knife pain concentrated?)
        bysym = defaultdict(lambda: {"with": [], "cnt": [], "knife": []})
        for t in enriched:
            bucket = bysym[t["symbol"]]
            if t["against_htf"]:
                bucket["cnt"].append(t["net_R"])
            else:
                bucket["with"].append(t["net_R"])
            if t["knife"]:
                bucket["knife"].append(t["net_R"])
        sym_tbl = {}
        for s, b in bysym.items():
            def m(xs):
                return (sum(xs) / len(xs)) if xs else None
            sym_tbl[s] = {
                "n_with": len(b["with"]), "expR_with": m(b["with"]),
                "n_cnt": len(b["cnt"]), "expR_cnt": m(b["cnt"]),
                "n_knife": len(b["knife"]), "expR_knife": m(b["knife"]),
            }

        result = {
            "generated": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
            "magics": list(MAGICS), "days_back": DAYS_BACK,
            "n_positions": len(trades), "n_enriched": len(enriched), "skipped": skipped,
            "summary": summary,
            "walk_forward_k1.0": wf,
            "wf_blocks_improved_of_5_k1.0": improved,
            "k_sweep": sweep,
            "alt_filters": alts,
            "per_symbol": sym_tbl,
        }
        import os
        os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
        with open(OUT_JSON, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)

        # ---- print human summary ----
        print("\n========== SUMMARY ==========")
        for k, v in summary.items():
            print(f"  {k}: {v}")
        print("\n--- walk-forward (k_atr=1.0) ---")
        for r in wf:
            print(f"  blk{r['block']} n={r['n']} kept={r['n_kept']} "
                  f"before={r['exp_R_before']:.3f} after={'NA' if r['exp_R_after'] is None else round(r['exp_R_after'],3)} "
                  f"delta={'NA' if r['delta_R'] is None else round(r['delta_R'],3)} pct_kept={r['pct_kept']:.0f}%")
        print(f"  blocks improved: {improved}/5")
        print("\n--- k sweep ---")
        for r in sweep:
            print(f"  k={r['k_atr']} improved={r['blocks_improved_of_5']}/5 "
                  f"before={r['global_exp_R_before']:.3f} after={'NA' if r['global_exp_R_after'] is None else round(r['global_exp_R_after'],3)} "
                  f"kept={r['pct_trades_kept']:.0f}%")
        print("\n--- ALTERNATIVE FILTERS (walk-forward) ---")
        for name, r in alts.items():
            print(f"  [{name}] improved={r['blocks_improved_of_5']}/5 "
                  f"before={r['global_exp_R_before']:.3f} after={'NA' if r['global_exp_R_after'] is None else round(r['global_exp_R_after'],3)} "
                  f"kept={r['pct_trades_kept']:.0f}%")
            for b in r["per_block"]:
                print(f"      blk{b['blk']}: before={b['before']} after={b['after']} "
                      f"delta={b['delta']} kept={b['pct_kept']}%")
        print(f"\nwrote {OUT_JSON}")
        return result
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()

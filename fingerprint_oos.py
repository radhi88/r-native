"""fingerprint_oos.py — OOS validation of the user's manual-trading EDGE-FINGERPRINT.

Question: does the "edge fingerprint" we found on magic-0 manual trades persist
out-of-sample, or was it just in-sample luck?

Method (no-lookahead, honest):
  1. Pull ALL magic-0 closed deals over the longest window available (try 180d,
     fall back to shorter windows if MT5 returns nothing).
  2. Pair IN/OUT by position_id -> one row per position with:
        net ($), entry-time, symbol, lot, hold-minutes, after-a-loss flag.
  3. Split by TIME 67/33: IS = older two-thirds, OOS = newer one-third.
  4. On IS, the fingerprint conditions are FIXED a-priori (the edge we already found):
        - day session 07-22 UTC
        - lot <= 0.2
        - hold > 30 min (swing-ish)
        - BTC vs gold
        - NOT-after-a-loss (no revenge)
     We measure IS expectancy ($/trade) for each, and the composite edge subset:
        day + lot<=0.2 + not-revenge.
  5. On OOS, test whether the SAME (frozen) conditions stay positive-expectancy.

  persists_oos = True ONLY if:
     - composite edge subset stays CLEARLY positive on OOS, AND
     - revenge AND big-lot AND night all stay CLEARLY negative on OOS.

Read-only. No order_send. Run:
  .venv\\Scripts\\python.exe fingerprint_oos.py [DAYS]
"""
from __future__ import annotations
import sys
import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "fingerprint_oos_results.json")

# --- fingerprint condition helpers (FROZEN a-priori from the IS-found edge) ---


def is_day(hour: int) -> bool:
    """Day session 07-22 UTC (the discipline window)."""
    return 7 <= hour < 22


def is_night(hour: int) -> bool:
    return not is_day(hour)


def is_btc(sym: str) -> bool:
    return "BTC" in sym.upper()


def is_gold(sym: str) -> bool:
    s = sym.upper()
    return s.startswith("XAU") or "GOLD" in s


# --- subset selectors (each takes a list of trade rows) ---


def composite_edge(trades):
    """day + lot<=0.2 + not-after-loss."""
    return [r for r in trades
            if is_day(r["hour"]) and r["vol"] <= 0.2 and not r["after_loss"]]


def hold_over_30(trades):
    return [r for r in trades if r["hold"] > 30.0]


def hold_under_30(trades):
    # only positions that actually closed (hold>0) and were quick
    return [r for r in trades if 0.0 < r["hold"] <= 30.0]


def btc_trades(trades):
    return [r for r in trades if is_btc(r["sym"])]


def gold_trades(trades):
    return [r for r in trades if is_gold(r["sym"])]


def revenge(trades):
    return [r for r in trades if r["after_loss"]]


def not_revenge(trades):
    return [r for r in trades if not r["after_loss"]]


def big_lot(trades):
    return [r for r in trades if r["vol"] > 0.2]


def small_lot(trades):
    return [r for r in trades if r["vol"] <= 0.2]


def night(trades):
    return [r for r in trades if is_night(r["hour"])]


def day(trades):
    return [r for r in trades if is_day(r["hour"])]


def expectancy(group):
    """Return (n, net_sum, exp_per_trade, win_rate_pct)."""
    n = len(group)
    if n == 0:
        return (0, 0.0, 0.0, 0.0)
    s = sum(r["net"] for r in group)
    w = sum(1 for r in group if r["net"] > 0)
    return (n, s, s / n, 100.0 * w / n)


def fetch_trades(days):
    """Pull magic-0 closed positions over `days`. Returns list of rows sorted by time."""
    if not (mt5.initialize() or mt5.initialize()):
        raise RuntimeError(f"mt5.initialize failed: {mt5.last_error()}")
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=days), now) or []
    mt5.shutdown()

    def net(x):
        return x.profit + x.commission + x.swap

    pos = {}
    for x in deals:
        if x.magic != 0:
            continue
        # only DEAL_TYPE_BUY/SELL (0/1) are real trades; skip balance/credit ops
        if x.type not in (0, 1):
            continue
        p = pos.setdefault(x.position_id, {"in": None, "out": None, "net": 0.0})
        if x.entry == 0:
            p["in"] = x
        elif x.entry == 1:
            p["out"] = x
        p["net"] += net(x)

    trades = []
    for p in pos.values():
        din = p["in"]
        if not din:
            continue
        dt = datetime.fromtimestamp(din.time, timezone.utc)
        hold = ((p["out"].time - din.time) / 60.0) if p["out"] else 0.0
        trades.append({
            "t": din.time,
            "iso": dt.isoformat(),
            "sym": din.symbol,
            "vol": float(din.volume),
            "net": float(p["net"]),
            "hour": dt.hour,
            "dow": dt.weekday(),
            "hold": hold,
            "closed": p["out"] is not None,
        })
    trades.sort(key=lambda r: r["t"])
    # mark "after a loss" (revenge/tilt): previous CLOSED trade was a loser
    for i, r in enumerate(trades):
        r["after_loss"] = (i > 0 and trades[i - 1]["net"] < 0)
    return trades


def automation_fingerprint(trades):
    """Sniff whether the magic-0 population is human-paced or machine-paced.

    The whole study ASSUMES magic-0 == the user's hand-placed discretionary
    trades. On a demo / Trial account magic-0 also catches the system's own
    manual-API order_send and any untagged scripts. If it's machine-paced we
    must NOT certify a 'manual edge' — it isn't the user's hand trades.

    Heuristics (any one tripping => looks automated):
      - median inter-arrival gap between entries is < 5s
      - >30% of consecutive entries are < 1s apart
      - a single day has > 100 entries (no human clicks 100+ trades/day)
      - entries spread across >= 20 distinct UTC hours (machine never sleeps)
    """
    ts = sorted(r["t"] for r in trades)
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    med_gap = sorted(gaps)[len(gaps) // 2] if gaps else None
    sub1 = (sum(1 for g in gaps if g < 1) / len(gaps)) if gaps else 0.0
    byday = defaultdict(int)
    byhour = set()
    for r in trades:
        dt = datetime.fromtimestamp(r["t"], timezone.utc)
        byday[dt.date()] += 1
        byhour.add(dt.hour)
    max_day = max(byday.values()) if byday else 0
    n_hours = len(byhour)
    flags = []
    if med_gap is not None and med_gap < 5:
        flags.append(f"median_entry_gap={med_gap}s (<5s)")
    if sub1 > 0.30:
        flags.append(f"{sub1*100:.0f}% of entries <1s apart")
    if max_day > 100:
        flags.append(f"{max_day} entries in a single day")
    if n_hours >= 20:
        flags.append(f"entries span {n_hours}/24 UTC hours")
    return {
        "median_entry_gap_s": med_gap,
        "frac_entries_sub_1s": round(sub1, 3),
        "max_entries_one_day": max_day,
        "distinct_utc_hours": n_hours,
        "looks_automated": len(flags) > 0,
        "flags": flags,
    }


def describe(group):
    n, s, exp, wr = expectancy(group)
    return {"n": n, "net": round(s, 2), "exp": round(exp, 4), "wr": round(wr, 1)}


def main():
    want_days = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    # try requested window, fall back to progressively shorter ones
    trades = []
    used_days = want_days
    for d in (want_days, 120, 90, 60, 45, 30):
        if d > want_days:
            continue
        trades = fetch_trades(d)
        used_days = d
        if len(trades) >= 30:
            break

    n = len(trades)
    result = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "window_days": used_days,
        "n_trades": n,
    }
    if n >= 1:
        result["automation"] = automation_fingerprint(trades)

    if n < 30:
        result["error"] = f"sample too small ({n} trades) even at widest window"
        _save(result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"\nNO_EDGE: insufficient data ({n} magic-0 trades)")
        return

    # --- TIME split 67/33: IS = older two-thirds, OOS = newer one-third ---
    cut = int(round(n * 0.67))
    IS = trades[:cut]
    OOS = trades[cut:]

    is_span = (datetime.fromtimestamp(IS[0]["t"], timezone.utc).date().isoformat(),
               datetime.fromtimestamp(IS[-1]["t"], timezone.utc).date().isoformat())
    oos_span = (datetime.fromtimestamp(OOS[0]["t"], timezone.utc).date().isoformat(),
                datetime.fromtimestamp(OOS[-1]["t"], timezone.utc).date().isoformat())

    tot_is = sum(r["net"] for r in IS)
    tot_oos = sum(r["net"] for r in OOS)

    result["split"] = {
        "n_is": len(IS), "n_oos": len(OOS),
        "is_dates": is_span, "oos_dates": oos_span,
        "is_net": round(tot_is, 2), "oos_net": round(tot_oos, 2),
        "is_exp": round(tot_is / len(IS), 4),
        "oos_exp": round(tot_oos / len(OOS), 4),
    }

    # --- frozen conditions: measure on IS and OOS identically ---
    conds = {
        "composite_edge(day+lot<=0.2+not-revenge)": composite_edge,
        "hold>30min": hold_over_30,
        "hold<=30min": hold_under_30,
        "BTC": btc_trades,
        "gold": gold_trades,
        "revenge(after-loss)": revenge,
        "not-revenge": not_revenge,
        "big-lot(>0.2)": big_lot,
        "small-lot(<=0.2)": small_lot,
        "night(22-07)": night,
        "day(07-22)": day,
    }
    result["conditions"] = {}
    for name, fn in conds.items():
        result["conditions"][name] = {
            "IS": describe(fn(IS)),
            "OOS": describe(fn(OOS)),
        }

    # --- verdict logic ---
    ce_oos = result["conditions"]["composite_edge(day+lot<=0.2+not-revenge)"]["OOS"]
    rev_oos = result["conditions"]["revenge(after-loss)"]["OOS"]
    big_oos = result["conditions"]["big-lot(>0.2)"]["OOS"]
    night_oos = result["conditions"]["night(22-07)"]["OOS"]
    ce_is = result["conditions"]["composite_edge(day+lot<=0.2+not-revenge)"]["IS"]

    # "clearly positive/negative" thresholds — require both sign + a minimum
    # magnitude so we don't call a ~$0.01/trade wobble an edge.
    POS = 0.50   # $/trade
    NEG = -0.50

    edge_was_positive_is = ce_is["exp"] > 0 and ce_is["n"] >= 10
    edge_stays_positive = ce_oos["exp"] >= POS and ce_oos["n"] >= 10
    # for each "bad" bucket: counts as confirming only if it has enough trades
    def stays_neg(b):
        return b["n"] < 10 or b["exp"] <= NEG  # too-few = not a counterexample
    def clearly_neg(b):
        return b["n"] >= 10 and b["exp"] <= NEG
    revenge_neg = clearly_neg(rev_oos)
    big_neg = clearly_neg(big_oos)
    night_neg = clearly_neg(night_oos)
    bad_buckets_negative = revenge_neg and big_neg and night_neg

    # CONTAMINATION GUARD: if the magic-0 population is machine-paced, this is
    # NOT the user's hand-placed manual trading. The mechanical "edge" then is a
    # property of the grid/algo, not of the user's discipline — refuse to certify.
    automated = result.get("automation", {}).get("looks_automated", False)

    persists = bool(edge_was_positive_is and edge_stays_positive
                    and bad_buckets_negative and not automated)

    if automated:
        # population identity failure dominates everything else
        verdict = "NO_EDGE"
    elif persists:
        verdict = "EDGE"
    elif edge_stays_positive and (revenge_neg or big_neg or night_neg):
        verdict = "WEAK"
    else:
        verdict = "NO_EDGE"

    result["verdict"] = verdict
    result["persists_oos"] = persists
    result["verdict_detail"] = {
        "population_looks_automated": automated,
        "edge_was_positive_is": edge_was_positive_is,
        "edge_stays_positive_oos": edge_stays_positive,
        "revenge_clearly_neg_oos": revenge_neg,
        "big_lot_clearly_neg_oos": big_neg,
        "night_clearly_neg_oos": night_neg,
        "pos_threshold": POS, "neg_threshold": NEG,
    }

    _save(result)

    # --- human-readable print ---
    print(f"=== fingerprint_oos · magic-0 · {used_days}d · {n} trades · "
          f"net {sum(r['net'] for r in trades):+.0f} ===")
    print(f"IS  (older): n={len(IS)}  {is_span[0]}..{is_span[1]}  "
          f"net={tot_is:+.0f}  exp={tot_is/len(IS):+.3f}$/trade")
    print(f"OOS (newer): n={len(OOS)}  {oos_span[0]}..{oos_span[1]}  "
          f"net={tot_oos:+.0f}  exp={tot_oos/len(OOS):+.3f}$/trade\n")

    def line(name):
        c = result["conditions"][name]
        i, o = c["IS"], c["OOS"]
        return (f"  {name:42} | IS n={i['n']:>4} exp={i['exp']:>+8.3f}$ wr={i['wr']:>3.0f}% "
                f"| OOS n={o['n']:>4} exp={o['exp']:>+8.3f}$ wr={o['wr']:>3.0f}%")

    print("--- frozen conditions: IS vs OOS expectancy ($/trade) ---")
    for name in conds:
        print(line(name))
    print()
    auto = result.get("automation", {})
    if auto.get("looks_automated"):
        print("!!! CONTAMINATION GUARD TRIPPED — magic-0 is MACHINE-paced, "
              "not hand trades:")
        for fl in auto.get("flags", []):
            print(f"      - {fl}")
        print("    => This is NOT the user's discretionary manual trading. "
              "The mechanical 'edge'")
        print("       is a grid/algo artifact, not the user's discipline. "
              "Cannot certify EDGE.\n")
    print(f"VERDICT: {verdict}   persists_oos={persists}")
    print(f"  composite edge IS+ : {edge_was_positive_is}  "
          f"OOS clearly+ (>={POS}): {edge_stays_positive}")
    print(f"  revenge OOS clearly- : {revenge_neg}   "
          f"big-lot OOS clearly- : {big_neg}   night OOS clearly- : {night_neg}")
    print(f"\nResults JSON -> {OUT_JSON}")


def _save(result):
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()

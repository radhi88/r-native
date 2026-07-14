"""intermarket.py — CROSS-ASSET CORRELATION BRAIN (the "این نزل الذهب يصعد النفط/الدولار والعكس").

What it does (read-only analysis → writes a signal file the trader + agents consume):
  1. Pulls returns for a broad cross-asset universe (gold, silver, oil, indices, crypto, USD pairs).
  2. Measures the LIVE rolling correlation matrix (Pearson on M5 returns).
  3. Keeps only STRONG links (|r| >= CORR_MIN) — positive OR inverse (research: ±0.80 = tradeable;
     a "correlation breakout"/divergence precedes the most explosive moves).
  4. For each strong link, measures DIVERGENCE: the leader moved, the laggard hasn't yet → the laggard
     is expected to CATCH UP. Positive link → trade laggard SAME way as leader; inverse link → OPPOSITE.
     => emits paired signals: one BUY + one SELL (e.g. gold up + dollar-proxy down).
  5. A "discovery" (a newly-strong pair not seen before) is flagged so the agents can try it on more pairs.

Writes:  r_native_v2/data/intermarket_signals.json   (trader + brain_animation read this)
Read-only on the market. Does NOT place orders (multi_trader owns execution). DEMO.

Run:  python intermarket.py --loop
"""
from __future__ import annotations
import argparse, json, time, math
from pathlib import Path

DD = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")
OUT = DD / "intermarket_signals.json"
SEEN = DD / "intermarket_discovered.json"

BARS = 300            # M5 bars for the correlation window (~1 day)
CORR_MIN = 0.55       # keep links at/above this |r|
DIVERGE_Z = 0.6       # leader-vs-laggard spread z-score that counts as a tradeable divergence (كان 1.0=نادر)
LEAD_LB = 12          # bars to measure the recent leg (≈1h on M5)
INTERVAL = 45

# Broad candidate universe (Exness 'm' suffix). Robust: only those MT5 can actually quote are used.
# Tagged by economic family ONLY for human-readable "why" — the MEASURED corr drives the trade.
UNIVERSE = {
    "XAUUSDm": "gold", "XAGUSDm": "metal",
    "USOILm": "oil", "UKOILm": "oil", "XBRUSDm": "oil",
    "US30m": "equity", "NAS100m": "equity", "USTECm": "equity", "SP500m": "equity",
    "BTCUSDm": "crypto", "ETHUSDm": "crypto",
    "EURUSDm": "usd_inv", "GBPUSDm": "usd_inv", "AUDUSDm": "usd_inv", "NZDUSDm": "usd_inv",
    "USDJPYm": "usd_str", "USDCHFm": "usd_str", "USDCADm": "usd_str",
}


def _rets(mt5, sym):
    try:
        mt5.symbol_select(sym, True)
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, BARS)
        if r is None or len(r) < 120:
            return None
        c = [float(x["close"]) for x in r]
        return [(c[i] - c[i - 1]) / c[i - 1] for i in range(1, len(c)) if c[i - 1]]
    except Exception:
        return None


def _corr(a, b):
    n = min(len(a), len(b))
    if n < 80:
        return 0.0
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a); vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return 0.0
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return cov / math.sqrt(va * vb)


def _recent_leg(rets):
    """Cumulative return over the last LEAD_LB bars, normalised by its own volatility (z-like)."""
    if len(rets) < LEAD_LB + 30:
        return 0.0
    leg = sum(rets[-LEAD_LB:])
    sd = (sum(x * x for x in rets[-90:]) / 90) ** 0.5 or 1e-9
    return leg / (sd * math.sqrt(LEAD_LB))


def compute(mt5):
    rets = {}
    for s in UNIVERSE:
        rr = _rets(mt5, s)
        if rr:
            rets[s] = rr
    syms = list(rets)
    pairs, signals = [], {}
    legs = {s: _recent_leg(rets[s]) for s in syms}
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            a, b = syms[i], syms[j]
            r = _corr(rets[a], rets[b])
            if abs(r) < CORR_MIN:
                continue
            la, lb = legs[a], legs[b]
            # expected move of each, given the OTHER one already moved (correlation-implied)
            # positive r: they should move together; negative r: opposite.
            exp_a = (r * lb)   # what a "should" have done given b's leg
            exp_b = (r * la)
            div_a = exp_a - la     # >0 means a lagged upward catch-up due
            div_b = exp_b - lb
            pairs.append({"a": a, "b": b, "r": round(r, 2), "rel": "طردي" if r > 0 else "عكسي",
                          "fam": f"{UNIVERSE[a]}/{UNIVERSE[b]}"})
            for sym, div, lead, partner in ((a, div_a, b, b), (b, div_b, a, a)):
                if abs(div) >= DIVERGE_Z:
                    d = 1 if div > 0 else -1
                    conf = min(0.99, abs(r) * min(2.0, abs(div)) / 2.0 + 0.45)
                    prev = signals.get(sym)
                    if not prev or conf > prev["conf"]:
                        signals[sym] = {
                            "dir": d, "conf": round(conf, 2), "partner": partner,
                            "r": round(r, 2),
                            "why": f"{'طردي' if r > 0 else 'عكسي'} مع {partner} (r={r:+.2f}) · "
                                   f"{partner} تحرّك و{sym} متأخّر → {'شراء' if d > 0 else 'بيع'} لحاق",
                        }
    # discovery log: newly-strong pairs the agents should try elsewhere
    discovered = []
    try:
        seen = set(json.loads(SEEN.read_text(encoding="utf-8")).get("pairs", []))
    except Exception:
        seen = set()
    for p in pairs:
        key = "|".join(sorted((p["a"], p["b"])))
        if abs(p["r"]) >= 0.8 and key not in seen:
            discovered.append(p); seen.add(key)
    if discovered:
        try:
            SEEN.write_text(json.dumps({"pairs": sorted(seen), "ts": time.time()}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    return {"ts": time.time(), "n_syms": len(syms),
            "pairs": sorted(pairs, key=lambda p: -abs(p["r"]))[:24],
            "signals": signals, "discovered": discovered}


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser(); ap.add_argument("--loop", action="store_true"); a = ap.parse_args(argv)
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    try:
        while True:
            try:
                out = compute(mt5)
                DD.mkdir(parents=True, exist_ok=True)
                OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
                top = sorted(out["pairs"], key=lambda p: -abs(p["r"]))[:3]
                tag = " · ".join(f"{p['a']}~{p['b']} {p['r']:+.2f}" for p in top)
                disc = f" · 🔎 اكتشف {len(out['discovered'])}" if out["discovered"] else ""
                print(f"[INTERMARKET] {out['n_syms']} أصول · {len(out['signals'])} إشارة لحاق · {tag}{disc}", flush=True)
            except Exception as e:
                print(f"[INTERMARKET] err {e}", flush=True)
            if not a.loop:
                break
            time.sleep(INTERVAL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

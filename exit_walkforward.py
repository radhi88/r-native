"""exit_walkforward.py — تحقّق robustness لنتيجة جودة الخروج: هل تفوّق الوقف المتحرك على الخروج
الفعلي يصمد عبر نوافذ زمنية متعدّدة (walk-forward) وعبر أحجام وقف مختلفة (لا 1.5R مثالي فقط)؟

نتيجة نافذة واحدة قد تكون صدفة. هنا نقسّم الصفقات الحقيقية إلى K كتل زمنية متتالية ونحسب
expR لكل قاعدة في كل كتلة، ونرى هل القاعدة المرشّحة تتفوّق على الفعلي في *كل* كتلة (= حافّة
حقيقية) أم في بعضها فقط (= ضوضاء). نكرّر عند SL ∈ {1.0, 1.5, 2.0}R لاختبار حساسية الفرضية للوقف.

Run: .venv\\Scripts\\python.exe exit_walkforward.py [DAYS] [K_BLOCKS]
"""
from __future__ import annotations
import sys, json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import MetaTrader5 as mt5
from exit_lab import _atr_series, simulate_exits, MAGICS, HORIZON, ATR_N

MT5DIR = Path(__file__).resolve().parent
CAND = {20260608: "trail1R", 20260612: "trail1.5R"}   # المرشّح لكل بوت (من النافذة الأولى)
RULES = ["_actual", "TP1R", "TP2R", "trail1R", "trail1.5R", "time40"]


def collect(days):
    mt5.initialize() or mt5.initialize()
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=days), now) or []
    pos = defaultdict(lambda: {"in": None, "out": None, "magic": None, "symbol": None})
    for x in deals:
        if x.magic not in MAGICS:
            continue
        p = pos[x.position_id]; p["magic"] = x.magic; p["symbol"] = x.symbol
        if x.entry == 0: p["in"] = x
        elif x.entry == 1: p["out"] = x
    trades = [p for p in pos.values() if p["in"] and p["out"]]
    trades.sort(key=lambda p: p["in"].time)
    syms = set(p["symbol"] for p in trades)
    bars = {}
    for s in syms:
        r = mt5.copy_rates_range(s, mt5.TIMEFRAME_M5, now - timedelta(days=days + 2), now)
        if r is not None and len(r) > ATR_N + 5:
            t = np.array([x["time"] for x in r], np.int64)
            h = np.array([x["high"] for x in r], float); l = np.array([x["low"] for x in r], float)
            c = np.array([x["close"] for x in r], float)
            bars[s] = (t, h, l, c, _atr_series(h, l, c))
    mt5.shutdown()
    return trades, bars


def rows_for_sl(trades, bars, sl):
    by_magic = defaultdict(list)
    for p in trades:
        s = p["symbol"]
        if s not in bars: continue
        t, h, l, c, atr = bars[s]
        din, dout = p["in"], p["out"]
        direction = "buy" if din.type == 0 else "sell"
        entry, etime = din.price, din.time
        idx = int(np.searchsorted(t, etime, side="right") - 1)
        if idx < ATR_N or idx + 2 >= len(c): continue
        atr_r = atr[idx]
        fwd_end = min(idx + 1 + HORIZON, len(c))
        fwd_h, fwd_l, fwd_c = h[idx+1:fwd_end], l[idx+1:fwd_end], c[idx+1:fwd_end]
        if len(fwd_c) < 3: continue
        sim = simulate_exits(entry, direction, atr_r, fwd_h, fwd_l, fwd_c, sl=sl)
        if sim is None: continue
        sgn = 1.0 if direction == "buy" else -1.0
        sim["_actual"] = sgn * (dout.price - entry) / atr_r if atr_r > 0 else 0.0
        sim["_time"] = etime
        by_magic[din.magic].append(sim)
    for m in by_magic: by_magic[m].sort(key=lambda r: r["_time"])
    return by_magic


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    K = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    trades, bars = collect(days)
    print(f"paired trades: {len(trades)} over {days}d · {K} walk-forward blocks · SL∈{{1.0,1.5,2.0}}R\n")
    report = {}
    for sl in (1.0, 1.5, 2.0):
        by_magic = rows_for_sl(trades, bars, sl)
        for magic, rows in by_magic.items():
            if len(rows) < K * 8: continue
            cand = CAND[magic]
            blocks = np.array_split(rows, K)
            print(f"=== {MAGICS[magic]} ({magic}) · SL={sl}R · n={len(rows)} · candidate={cand} ===")
            wins = 0
            block_deltas = []
            for bi, blk in enumerate(blocks):
                ea = float(np.mean([r["_actual"] for r in blk]))
                ec = float(np.mean([r[cand] for r in blk]))
                d = ec - ea; block_deltas.append(round(d, 3))
                beat = d > 0
                wins += beat
                print(f"  block{bi+1} (n={len(blk):>3}): actual {ea:+.3f}  {cand} {ec:+.3f}  Δ {d:+.3f}  {'✅' if beat else '✗'}")
            allexp = {r: round(float(np.mean([row[r] for row in rows])), 3) for r in RULES}
            verdict = "ROBUST" if wins == K else ("MOSTLY" if wins >= K - 1 else "FRAGILE")
            print(f"  → {cand} beats actual in {wins}/{K} blocks = {verdict}   全期: {allexp}\n")
            report.setdefault(MAGICS[magic], {})[f"sl{sl}"] = {
                "n": len(rows), "candidate": cand, "blocks_won": wins, "K": K,
                "block_deltas": block_deltas, "verdict": verdict, "fullexp": allexp}
    out = MT5DIR / "data" / "lab_cache" / "exit_walkforward_results.json"
    out.write_text(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                               "days": days, "K": K, "report": report}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved -> {out}")


if __name__ == "__main__":
    main()

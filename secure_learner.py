"""secure_learner.py — learns, PER SYMBOL, how fast to lock profit before price reverses.

Some markets pop then give it all back (lock instantly); others trend (let it run). This
measures each symbol's REVERSAL behaviour from recent bars: after a +0.5·ATR pop, how often
does price give back 0.5·ATR before extending another 0.5·ATR? High give-back → secure fast
(tiny breakeven trigger + tight trail). Low → let winners run (looser trail).

Writes data/secure_config_<SYM>.json {be_atr, trail_tight, trail_loose, reversal_rate} which
multi_trader/_manage reads per symbol. Loops hourly — never stops learning. Read-only research.
Run:  python secure_learner.py --loop
"""
from __future__ import annotations
import argparse, json, time, glob
from pathlib import Path

_DD = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")
GENO = _DD / "genomes"
H = 12                         # bars to judge the reversal
POP = 0.5                      # the move size that counts as a "pop" (× ATR)


def _atr_at(rows, i, n=14):
    if i < n + 1: return 0.0
    return sum(max(rows[k]["high"] - rows[k]["low"], abs(rows[k]["high"] - rows[k - 1]["close"]),
                   abs(rows[k]["low"] - rows[k - 1]["close"])) for k in range(i - n + 1, i + 1)) / n


def analyze(rows):
    c = [r["close"] for r in rows]
    pops = give_backs = 0; mfes = []
    for i in range(20, len(rows) - H):
        atr = _atr_at(rows, i)
        if atr <= 0: continue
        move = c[i] - c[i - 3]
        if abs(move) < POP * atr:
            continue
        pops += 1; d = 1 if move > 0 else -1; start = c[i]; mfe = 0.0; gave = False
        for j in range(i + 1, i + H):
            adv = (c[j] - start) * d
            mfe = max(mfe, adv)
            if adv <= -0.5 * atr:
                gave = True; break
            if adv >= 0.5 * atr:
                break
        if gave: give_backs += 1
        mfes.append(mfe / atr)
    rate = give_backs / pops if pops else 0.5
    # ⤵️ خريطة مستمرة بدل 3 دلاء: التدقيق وجد أن معدّل الانعكاس يتجمّع ~0.48-0.52 لمعظم الرموز
    # فيقع ~95% في نفس الدلو (be=0.15) ويُبتلع التعلّم. الآن كل رمز يأخذ سرعة تأمين تتناسب مع
    # معدّل انعكاسه المقيس فعلاً (أعلى ⇒ قفل أسرع/أضيق). المراسي = أطراف الدلاء القديمة (نفس النطاق الآمن).
    def _lin(r, r0, r1, v0, v1):
        t = max(0.0, min(1.0, (r - r0) / (r1 - r0)))
        return v0 + t * (v1 - v0)
    be = round(_lin(rate, 0.35, 0.60, 0.30, 0.05), 3)
    tt = round(_lin(rate, 0.35, 0.60, 1.5, 0.6), 2)
    tl = round(_lin(rate, 0.35, 0.60, 3.2, 1.8), 2)
    return {"reversal_rate": round(rate, 3), "pops": pops,
            "be_atr": be, "trail_tight": tt, "trail_loose": tl,
            "mfe_median_atr": round(sorted(mfes)[len(mfes) // 2], 2) if mfes else 0.0}


def _tf(mt5, s):
    return {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4}.get(s, mt5.TIMEFRAME_M15)


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser(); ap.add_argument("--loop", action="store_true"); a = ap.parse_args(argv)
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    _DD.mkdir(parents=True, exist_ok=True)
    try:
        while True:
            syms = {}
            for f in glob.glob(str(GENO / "*.json")):
                try:
                    g = json.loads(Path(f).read_text(encoding="utf-8")); syms[g["symbol"]] = g["config"].get("tf", "M15")
                except Exception: pass
            for sym, tf in syms.items():
                try:
                    r = mt5.copy_rates_from_pos(sym, _tf(mt5, tf), 0, 1000)
                    if r is None or len(r) < 200: continue
                    rows = [{"high": x["high"], "low": x["low"], "close": x["close"]} for x in r]
                    res = analyze(rows); res.update({"symbol": sym, "tf": tf, "ts": time.time()})
                    (_DD / f"secure_config_{sym}.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
                except Exception: pass
            fast = sum(1 for f in glob.glob(str(_DD / "secure_config_*.json"))
                       if json.loads(Path(f).read_text(encoding="utf-8")).get("be_atr", 1) <= 0.05)
            print(f"[SECURE] learned {len(syms)} symbols · {fast} need FAST lock (reversal-prone)", flush=True)
            if not a.loop: break
            time.sleep(3600)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

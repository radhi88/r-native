"""brain_view.py — SEE what each currency's genome learned: brain (weighted indicators),
agent decisions, OOS genome stats, learned secure speed, live P&L. Answers "هل تعلم فعلاً؟".

Run:  python brain_view.py            (all deployed symbols, summary)
      python brain_view.py XAUUSDm    (one symbol, full brain)
"""
from __future__ import annotations
import json, sys, time, glob
from pathlib import Path

V2 = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")
RN = Path(r"C:\Users\Radhi\MT5\data\r_native")


def _load(p, d=None):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return d


def _live_pnl(symbols):
    out = {}
    try:
        import MetaTrader5 as mt5; mt5.initialize()
        dl = [d for d in (mt5.history_deals_get(int(time.time() - 24 * 3600), int(time.time())) or [])
              if d.entry == 1 and d.magic == 20260608]
        for d in dl:
            t = out.setdefault(d.symbol, [0, 0.0]); t[0] += 1; t[1] += d.profit + d.commission + d.swap
        mt5.shutdown()
    except Exception: pass
    return out


def view(sym, pnl):
    g = _load(V2 / f"genomes/{sym}.json", {})
    cfg = g.get("config", {}); oos = g.get("oos", {})
    w = (_load(V2 / f"indicator_weights_{sym}.json", {}) or {}).get("weights", {})
    acc = (_load(V2 / f"indicator_accuracy_{sym}.json", {}) or {}).get("accuracy", {})
    sec = _load(V2 / f"secure_config_{sym}.json", {})
    vol = _load(V2 / f"vol_regime_{sym}.json", {})
    n, net = pnl.get(sym, [0, 0.0])
    print(f"\n══════ {sym} ══════")
    print(f"  🧬 الجين: {cfg.get('tf','?')} · stop {cfg.get('stop_atr')}×ATR · target {cfg.get('target_atr')}×ATR · gate {cfg.get('conf_gate')}")
    print(f"     أداء OOS (وين صار): PF {oos.get('pf','?')} · {oos.get('net_R','?')}R · فوز {round((oos.get('win_rate',0))*100)}% · {oos.get('folds_pos','?')}/4 نوافذ · {oos.get('trades','?')} صفقة")
    if w:
        top = sorted(w.items(), key=lambda x: -x[1])[:6]
        brain = " · ".join(f"{k} {v}" for k, v in top if v > 0)
        print(f"  🧠 مخ المؤشرات المتعلّم (أوزان): {brain or 'كلها ضعيفة'}")
    if acc:
        best = sorted(acc.items(), key=lambda kv: -kv[1].get('hit_rate', 0))[:4]
        print(f"  🎯 أدق المؤشرات (قِيس): " + " · ".join(f"{k} {round(v['hit_rate']*100,1)}%" for k, v in best))
    if sec:
        print(f"  🛡 تأمين الربح المتعلّم: انعكاس {round(sec.get('reversal_rate',0)*100)}% → be {sec.get('be_atr')} ({'سريع' if sec.get('be_atr',1)<=0.1 else 'عادي'})")
    if vol:
        print(f"  🌊 التذبذب: {vol.get('state','?')} · هدف ×{vol.get('target_mult','?')}")
    tag = "🟢 رابح حيّاً" if net > 1 else "🔴 خاسر حيّاً" if net < -1 else "⚪ متعادل"
    print(f"  💰 الأداء الحيّ (24س): {n} صفقة · ${net:+.2f} {tag}")


def main(argv):
    syms = [Path(f).stem for f in glob.glob(str(V2 / "genomes/*.json"))]
    pnl = _live_pnl(syms)
    if argv:
        for s in argv: view(s, pnl)
        return 0
    # summary table — all symbols, sorted by live P&L
    print("ملخّص دماغ كل عملة (مرتّب بالربح الحيّ):")
    rows = []
    for s in syms:
        g = _load(V2 / f"genomes/{s}.json", {}); oos = g.get("oos", {})
        w = (_load(V2 / f"indicator_weights_{s}.json", {}) or {}).get("weights", {})
        top = sorted(w.items(), key=lambda x: -x[1])[:2]
        n, net = pnl.get(s, [0, 0.0])
        rows.append((net, s, oos.get("pf", 0), n, " ".join(k for k, v in top if v > 0)))
    rows.sort(reverse=True)
    print(f"  {'عملة':10s} {'حيّ$':>8s} {'صفقات':>6s} {'OOS-PF':>7s}  أقوى مؤشرات متعلّمة")
    for net, s, pf, n, brain in rows:
        print(f"  {s:10s} {net:+8.2f} {n:6d} {pf:7} {brain}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

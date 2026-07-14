"""forecast_lab.py — مختبر التنبؤ الدائم: يمسح الشارت، يتنبّأ بالقادم، يتحقّق هل صدق، وإن صدق
شرطٌ معيّن بثبات → يكتبه قاعدة + يقرّر متى نرفع اللوت (من الدقّة الأمامية المُثبتة، لا الوعود).

الحلقة (كل 5 دقائق):
  1. RESOLVE: كل تنبؤ مضى أفقه → اسحب السعر الفعلي، سجّل هل صدق + صافي R، حدّث إحصاء شرطه.
  2. PREDICT: لكل رمز احسب الإشارة الموحّدة + وسوم السياق (جلسة|نظام|ثقة|هجومية|ml) → سجّل تنبؤاً.
  3. PROMOTE: شرط بـ≥30 عيّنة ودقّة ≥56% → قاعدة في forecast_rules.json مع lot_mult متناسب مع
     الدقّة (كل ما الشرط أصدق تاريخياً = لوت أكبر حين يتكرّر). multi_trader يقرأها ويرفع اللوت.

صادق: التنبؤ يُسجّل أولاً ثم يُحاكَم بأسعار MT5 الفعلية بعد الأفق (سبريد حقيقي) — لا أثر رجعي.
Windowless.  Run:  pythonw forecast_lab.py
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
STATE = RN / "forecast_state.json"
RULES = RN / "forecast_rules.json"
POLL_S = 300
HORIZON_S = 2 * 3600           # أفق التنبؤ: ساعتان
MIN_N, MIN_HIT = 30, 0.56      # عتبة ترقية الشرط إلى قاعدة
for p in (str(MT5DIR), str(MT5DIR / "r_native_v2")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _save(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _bucket_conf(c):
    return "hi" if c >= 0.75 else "mid" if c >= 0.6 else "lo"


def _bucket_surge(s):
    return "agg" if s >= 1.9 else "med" if s >= 1.4 else "norm"


def _cond_key(snap):
    # session|conf|surge — يحسبه المتداول بدقّة بلا قراءات إضافية (تطابق مضمون)
    return f"{snap['session']}|c-{_bucket_conf(snap['conf'])}|s-{_bucket_surge(snap['surge'])}"


def predict_snapshot(mt5, sym, cr, mt):
    """مسح الشارت → إشارة موحّدة + سياق (يعيد تنبؤاً أو None)."""
    tick = mt5.symbol_info_tick(sym)
    if not tick or not tick.bid:
        return None
    cfg = mt._genomes().get(sym, {})
    cdir, conf = mt._macro(cr, mt5, sym)
    cg = float(cfg.get("conf_gate", 0.6))
    if cdir == 0 or conf < cg:
        return None
    d = cr.read_local(mt5, sym, cfg.get("tf", "M15")) or {}
    r = mt5.copy_rates_from_pos(sym, mt._tf(mt5, cfg.get("tf", "M15")), 0, 20)
    if r is None or len(r) < 15:
        return None
    tr = [max(r[i]["high"] - r[i]["low"], abs(r[i]["high"] - r[i - 1]["close"]),
              abs(r[i]["low"] - r[i - 1]["close"])) for i in range(1, len(r))]
    atr = sum(tr[-14:]) / 14
    if atr <= 0:
        return None
    tt = mt._tournament_tilt().get(sym, 0); mb = mt._macro_bias(sym); dlt = mt._delta_bias(sym)
    agree = 1 + (conf >= cg + 0.10) + (1 if tt == cdir and tt else 0) \
        + (1 if dlt is not None and ((dlt > 15 and cdir > 0) or (dlt < -15 and cdir < 0)) else 0) \
        + (1 if mb and (mb > 0) == (cdir > 0) else 0)
    surge = {1: 1.0, 2: 1.4, 3: 1.9, 4: 2.3, 5: 2.5}.get(min(5, agree), 1.0)
    return {"ts": time.time(), "sym": sym, "dir": cdir, "conf": round(conf, 3),
            "session": mt._session_now(), "regime": d.get("regime"), "surge": surge,
            "ml": (d.get("votes", {}) or {}).get("ml", 0),
            "price": (tick.ask if cdir > 0 else tick.bid), "atr": round(atr, 6),
            "tf": cfg.get("tf", "M15"), "resolved": False}


def cycle(mt5, st, cr, mt):
    now = time.time()
    preds = st.setdefault("pending", [])
    stats = st.setdefault("stats", {})
    # 1) RESOLVE
    still = []
    resolved = 0
    for p in preds:
        if now - p["ts"] < HORIZON_S:
            still.append(p); continue
        tick = mt5.symbol_info_tick(p["sym"])
        if not tick:
            still.append(p); continue
        cur = (tick.bid + tick.ask) / 2
        moveR = ((cur - p["price"]) if p["dir"] > 0 else (p["price"] - cur)) / max(p["atr"], 1e-9)
        hit = moveR > 0
        k = p.get("cond", "?")
        c = stats.setdefault(k, {"n": 0, "hits": 0, "netR": 0.0})
        c["n"] += 1; c["hits"] += 1 if hit else 0; c["netR"] = round(c["netR"] + moveR, 2)
        resolved += 1
    st["pending"] = still
    # 2) PREDICT
    new = 0
    for sym in list(mt._genomes()):
        try:
            snap = predict_snapshot(mt5, sym, cr, mt)
            if snap:
                snap["cond"] = _cond_key(snap)
                st["pending"].append(snap); new += 1
        except Exception:
            pass
    # 3) PROMOTE proven-predictive conditions → rules + lot guidance
    rules = {}
    for k, c in stats.items():
        if c["n"] >= MIN_N:
            hit = c["hits"] / c["n"]
            if hit >= MIN_HIT:
                lot_mult = round(min(2.5, 1.0 + (hit - 0.5) * 6), 2)  # 56%→1.36 · 66%→1.96 · ≥75%→2.5
                rules[k] = {"hit": round(hit, 3), "n": c["n"], "netR": c["netR"], "lot_mult": lot_mult}
    _save(RULES, {"ts": now, "iso": datetime.now(timezone.utc).isoformat(), "rules": rules})
    st["ts"] = now
    _save(STATE, st)
    return resolved, new, len(rules)


def main():
    import MetaTrader5 as mt5
    import chart_read as cr
    import multi_trader as mt
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    print("[FCAST] مختبر التنبؤ الدائم حيّ — يتنبّأ، يتحقّق، يضع قواعد + متى نرفع اللوت", flush=True)
    st = _load(STATE, {}) or {}
    while True:
        try:
            res, new, nr = cycle(mt5, st, cr, mt)
            top = sorted((_load(RULES, {}) or {}).get("rules", {}).items(),
                         key=lambda kv: -kv[1]["hit"])[:3]
            tag = " · ".join(f"{k.split('|')[0]}/{k.split('|')[1]} {int(v['hit']*100)}%→×{v['lot_mult']}" for k, v in top)
            print(f"[FCAST] حسم {res} · تنبؤات جديدة {new} · قواعد مُثبتة {nr} · أقوى: {tag or 'تتجمع'}", flush=True)
        except Exception as e:
            print(f"[FCAST] err {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())

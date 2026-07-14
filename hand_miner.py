# -*- coding: utf-8 -*-
"""hand_miner.py — معدِّن اليد: يفكّ لماذا تربح يدُك (magic-0) وأين تنزف، من بصمة اللحظة المخزّنة.

المصدر: جدول features في data/friday.db (4,908 صفقة يدوية مُلتقَطة سببياً لحظة الدخول: سبريد/ATR/
RSI/Stoch/اتجاه/بُعد-عن-EMA/جلسة/ساعة) + النتيجة (net/win/hold). لا يتاجر، لا يفتح مسار أوامر —
قراءةٌ وتحليلٌ فقط، ويكتب data/r_native/hand_edge.json ليعرضه R Trader.

الصدق الصارم: لكل «رافعة» (شرط لحظة-دخول مفهوم بشرياً) نقيس فصلها لصافي الربح بين داخل الشرط
وخارجه، ثم نتحقّق خارج-العيّنة (walk-forward: تدريب على أقدم 70% زمنياً، اختبار على أحدث 30%).
إن انهار الأثر خارج العيّنة ⇒ ضجيج/إفراط-ملاءمة (verdict=noise). إن صمد وبنفس الإشارة ⇒ real.

الحقيقة المقيسة سلفاً: الذهب 68% فوز لكن −$59k صافٍ ⇒ اليد تربح بالتكرار لا بالمال؛ النزف من
الحجم والخروج لا من اتجاه الدخول. لذا نُحلّل الصافي (والصافي/لوت) لا الفوز/الخسارة وحدهما.

Run:  python hand_miner.py            (تحليل لمرة، يكتب hand_edge.json)
      pythonw hand_miner.py loop      (يعيد كل ساعة، windowless، watchdog-managed)
"""
from __future__ import annotations
import json, os, sqlite3, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\Radhi\MT5")
DB = ROOT / "data" / "friday.db"
RN = ROOT / "data" / "r_native"
OUT = RN / "hand_edge.json"
LOOP_S = 3600


def _load():
    """يقرأ صفوف بصمة-اللحظة المُعلَّمة من جدول features (magic-0 = يدوي)."""
    if not DB.exists():
        return []
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "select ticket,symbol,ts,side,lot,price,spread,atr,atr_pctile,rsi,stoch,"
            "trend,htf_trend,dist_ema_atr,hour,dow,session,net,win,hold_min "
            "from features where net is not null and lot>0 order by ts asc"
        ).fetchall()
    except Exception:
        con.close(); return []
    con.close()
    out = []
    for r in rows:
        d = dict(r)
        # رافعات مشتقّة، سببية (كلها من بيانات ≤ الدخول):
        side = 1 if (d.get("side") or 0) >= 0 else -1
        dist = float(d.get("dist_ema_atr") or 0.0)
        d["ext_in_dir"] = round(dist * side, 3)         # +كبير = دخل باتجاه ما ركض أصلاً (مطاردة قمّة/قاع)
        d["counter_htf"] = int((d.get("htf_trend") or 0) != 0 and side != (d.get("htf_trend") or 0))
        d["net_per_lot"] = round(float(d["net"]) / max(float(d["lot"]), 1e-6), 2)
        h = d.get("hour")
        d["night"] = int(h is not None and (h >= 22 or h < 7))     # ليل UTC = تسريب مقيس سابقاً
        out.append(d)
    return out


def _stats(rows):
    n = len(rows)
    if not n:
        return {"n": 0}
    net = sum(float(r["net"]) for r in rows)
    wins = sum(int(r["win"]) for r in rows)
    return {"n": n, "net": round(net, 1), "wr": round(wins / n * 100, 1),
            "avg_net": round(net / n, 2)}


def _lever(rows_train, rows_test, name, pred, human):
    """يقيس رافعة: صافي داخل الشرط مقابل خارجه، تدريباً ثم اختباراً خارج-العيّنة."""
    def split(rows):
        inn = [r for r in rows if pred(r)]; out = [r for r in rows if not pred(r)]
        si, so = _stats(inn), _stats(out)
        gap = (si.get("avg_net", 0) - so.get("avg_net", 0)) if (si["n"] and so["n"]) else 0.0
        return si, so, round(gap, 2)
    tr_in, tr_out, tr_gap = split(rows_train)
    te_in, te_out, te_gap = split(rows_test)
    # الحكم: صمود الإشارة خارج العيّنة (نفس الاتجاه + دعم كافٍ)
    verdict = "insufficient"
    if te_in["n"] >= 20 and tr_in["n"] >= 20:
        same_sign = (tr_gap > 0) == (te_gap > 0)
        strong = abs(te_gap) >= 0.25 * (abs(tr_gap) + 1e-9)
        verdict = "real" if (same_sign and strong and abs(te_gap) >= 1.0) else "noise"
    return {"lever": name, "human": human,
            "train": {"in": tr_in, "out": tr_out, "avg_net_gap": tr_gap},
            "oos":   {"in": te_in, "out": te_out, "avg_net_gap": te_gap},
            "verdict": verdict}


def _sizing(rows):
    """الرافعة الوحيدة المثبتة تاريخياً: الحجم. صافٍ لكل حزمة لوت + ارتباط الحجم بالصافي."""
    buckets = [("<0.05", 0, 0.05), ("0.05-0.1", 0.05, 0.1), ("0.1-0.2", 0.1, 0.2),
               ("0.2-0.5", 0.2, 0.5), (">=0.5", 0.5, 9e9)]
    out = []
    for label, lo, hi in buckets:
        sub = [r for r in rows if lo <= float(r["lot"]) < hi]
        s = _stats(sub); s["bucket"] = label; out.append(s)
    # ارتباط بسيط lot↔net (سالب = يُكبِّر الحجم على الخاسرة = التسريب)
    xs = [float(r["lot"]) for r in rows]; ys = [float(r["net"]) for r in rows]
    corr = 0.0
    if len(xs) > 30:
        mx = sum(xs) / len(xs); my = sum(ys) / len(ys)
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        vx = sum((x - mx) ** 2 for x in xs) ** 0.5
        vy = sum((y - my) ** 2 for y in ys) ** 0.5
        corr = round(cov / (vx * vy + 1e-9), 3) if vx and vy else 0.0
    return {"by_lot": out, "corr_lot_net": corr}


def mine():
    rows = _load()
    if len(rows) < 60:
        payload = {"ok": False, "reason": "not_enough_labeled_hand_trades",
                   "n": len(rows), "iso": datetime.now(timezone.utc).isoformat()}
        _write(payload); print(f"[HAND] عيّنة صغيرة n={len(rows)} — لا تعدين موثوق"); return payload

    # walk-forward: أقدم 70% تدريب / أحدث 30% اختبار (خارج العيّنة زمنياً)
    cut = int(len(rows) * 0.70)
    train, test = rows[:cut], rows[cut:]

    overall = _stats(rows)
    gold = [r for r in rows if r["symbol"] == "XAUUSDm"]
    btc = [r for r in rows if r["symbol"] == "BTCUSDm"]

    levers = [
        _lever(train, test, "chase_extended", lambda r: r["ext_in_dir"] >= 1.5,
               "دخلتَ باتّجاه حركةٍ ركضت أصلاً (مطاردة قمّة/قاع، بُعد≥1.5 ATR عن EMA)"),
        _lever(train, test, "counter_htf", lambda r: r["counter_htf"] == 1,
               "دخلتَ عكس اتجاه الفريم الأعلى H1"),
        _lever(train, test, "night", lambda r: r["night"] == 1,
               "دخلتَ ليلاً (22:00–07:00 UTC، الجلسة الآسيوية)"),
        _lever(train, test, "high_vol", lambda r: (r.get("atr_pctile") or 0) >= 80,
               "دخلتَ في تذبذبٍ عالٍ (ATR ضمن أعلى 20%)"),
        _lever(train, test, "wide_spread", lambda r: (r.get("spread") or 0) >= 300,
               "دخلتَ وسبريد واسع (≥300 نقطة)"),
        _lever(train, test, "rsi_hot", lambda r: (r.get("rsi") or 50) >= 70 or (r.get("rsi") or 50) <= 30,
               "دخلتَ وRSI متطرّف (≥70 أو ≤30)"),
        _lever(train, test, "oversized", lambda r: float(r["lot"]) >= 0.2,
               "حجمٌ كبير (≥0.2 لوت) — الرافعة المثبتة تاريخياً"),
    ]
    levers.sort(key=lambda L: abs(L["oos"]["avg_net_gap"]), reverse=True)

    # الرافعة الحقيقية القوية: أيّها real ويخفض الصافي (نتجنّبه) أو يرفعه (نكرّره)
    real = [L for L in levers if L["verdict"] == "real"]

    payload = {
        "ok": True, "iso": datetime.now(timezone.utc).isoformat(),
        "n": overall["n"], "split": {"train": len(train), "oos": len(test)},
        "headline": {
            "overall": overall,
            "gold": _stats(gold), "btc": _stats(btc),
            "truth": ("اليد تربح بالتكرار لا بالمال: فوزٌ %.0f%% لكن صافٍ %s$ — "
                      "النزف من الحجم والخروج لا من اتّجاه الدخول."
                      % (overall["wr"], f"{overall['net']:+.0f}")),
        },
        "sizing": _sizing(rows),
        "levers": levers,
        "real_levers": [L["lever"] for L in real],
        "conclusion": _conclude(overall, gold, real, _sizing(rows)),
    }
    _write(payload)
    _print(payload)
    return payload


def _conclude(overall, gold, real, sizing):
    bits = []
    if overall["wr"] >= 60 and overall["net"] < 0:
        bits.append("اتّجاه دخولك سليم (فوز عالٍ) لكن المال يُفقد بعد الدخول — العلاج في الخروج/الحجم لا التنبّؤ.")
    if sizing["corr_lot_net"] < -0.02:
        bits.append("ارتباط الحجم بالصافي سالب: تُكبِّر اللوت على الصفقات الأسوأ — هذا أكبر مُضخِّم للنزف.")
    for L in real:
        g = L["oos"]["avg_net_gap"]
        if g < 0:
            bits.append(f"تجنَّب: «{L['human']}» — يخفض صافي الصفقة ~{g:.1f}$ خارج العيّنة.")
        else:
            bits.append(f"كرِّر: «{L['human']}» — يرفع صافي الصفقة ~{g:.1f}$ خارج العيّنة.")
    if not real:
        bits.append("لا رافعة دخول تصمد خارج العيّنة بقوّة — يؤكّد أن الحافّة انضباطٌ (حجم/خروج/ليل) لا نمط دخول سرّي.")
    return " ".join(bits)


def _write(payload):
    RN.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, OUT)


def _print(p):
    h = p["headline"]
    print(f"\n[HAND] n={p['n']}  (train {p['split']['train']} / oos {p['split']['oos']})")
    print(f"  الإجمال: {h['overall']}")
    print(f"  الذهب  : {h['gold']}")
    print(f"  BTC    : {h['btc']}")
    print(f"  الحقيقة: {h['truth']}")
    print(f"  الحجم corr(lot,net)={p['sizing']['corr_lot_net']}")
    for b in p["sizing"]["by_lot"]:
        if b["n"]:
            print(f"    لوت {b['bucket']:>9}: n={b['n']:>5} WR={b['wr']:>4}% صافٍ={b['net']:>10}")
    print("  الرافعات (مرتّبة بأثرها خارج العيّنة):")
    for L in p["levers"]:
        print(f"    [{L['verdict']:>12}] {L['lever']:<14} oos_gap={L['oos']['avg_net_gap']:>7}$  {L['human'][:46]}")
    print(f"  الخلاصة: {p['conclusion']}\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "loop":
        # windowless: أعد التحليل كل ساعة، heartbeat عبر hand_edge.json
        import io
        sys.stdout = io.TextIOWrapper(open(os.devnull, "wb"), encoding="utf-8")
        try:
            import engine_lock; engine_lock.claim("hand_miner")
        except Exception:
            pass
        while True:
            try:
                mine()
            except Exception:
                pass
            time.sleep(LOOP_S)
    else:
        mine()

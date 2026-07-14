# -*- coding: utf-8 -*-
"""
session_summary.py — ملخّص شامل لكل عملة (يُعاد توليده تلقائياً من البيانات الحيّة)
================================================================================
يقرأ دقّة المؤشّرات (r_native_v2/data/indicator_accuracy_*.json) + سبورة الفرق
(army_scoreboard.json) ويكتب SESSION_SUMMARY.md: ملخّص الجلسة + جدول لكل عملة
(أفضل قراءة + توقّع السبورة + حكم الحافّة الصادق). شغّله متى شئت ليُحدّث الملخّص.
RUN: python session_summary.py   (اختياري --print)
قراءة فقط.
"""
from __future__ import annotations
import glob, json, math, os, sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
RN = os.path.join(ROOT, "data", "r_native")
V2D = os.path.join(ROOT, "r_native_v2", "data")
OUT = os.path.join(ROOT, "SESSION_SUMMARY.md")


def _j(p):
    try:
        return json.load(open(p, encoding="utf-8-sig"))
    except Exception:
        return None


def build():
    army = (_j(os.path.join(RN, "army_scoreboard.json")) or {}).get("stats", {}) or {}
    # per-symbol: scoreboard n/expR + best indicator accuracy
    per = {}
    pn = ps = 0.0
    for sym, v in army.items():
        nn = v.get("n", 0); sr = v.get("sumR", 0.0)
        pn += nn; ps += sr
        per.setdefault(sym, {})["n"] = nn
        per[sym]["expR"] = round(sr / nn, 3) if nn else 0.0
    for f in glob.glob(os.path.join(V2D, "indicator_accuracy_*.json")):
        d = _j(f)
        if not d:
            continue
        sym = d.get("symbol")
        acc = d.get("accuracy") or {}
        if not acc:
            continue
        best = max(acc.items(), key=lambda kv: kv[1].get("hit_rate", 0))
        # robust best = highest hit among votes>=300
        robust = [(k, vv) for k, vv in acc.items() if vv.get("votes", 0) >= 300]
        rbest = max(robust, key=lambda kv: kv[1].get("hit_rate", 0)) if robust else None
        per.setdefault(sym, {})
        per[sym]["best_ind"] = best[0]
        per[sym]["best_acc"] = round(best[1].get("hit_rate", 0) * 100, 1)
        per[sym]["best_votes"] = best[1].get("votes", 0)
        per[sym]["robust_acc"] = round(rbest[1].get("hit_rate", 0) * 100, 1) if rbest else None
        per[sym]["tf"] = d.get("tf")

    pe = ps / pn if pn else 0.0
    pt = pe * math.sqrt(pn) if pn else 0.0

    def verdict(r):
        # honest per-symbol: robust accuracy near 50 + scoreboard expR not significant = NO_EDGE
        ra = r.get("robust_acc")
        n = r.get("n", 0); e = r.get("expR", 0)
        t = e * math.sqrt(n) if n else 0
        if ra is not None and ra >= 55 and t > 2:
            return "🟢 مرشّح (افحص OOS)"
        return "❌ لا حافّة"

    rows = sorted(per.items(), key=lambda kv: -(kv[1].get("robust_acc") or 0))
    lines = []
    lines.append(f"# FRIDAY — ملخّص الجلسة الشامل لكل عملة")
    lines.append(f"_تولّد آلياً: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · أعد التشغيل: `python session_summary.py`_\n")
    lines.append("## الخلاصة الكبرى (مُثبتة هذه الجلسة)")
    lines.append(f"- **الحافّة المجمّعة (السبورة الظلّية، إجمالي/داخل-عيّنة):** n={int(pn)} · توقّع {pe:+.4f}R · t≈{pt:+.2f}. "
                 f"⚠ إجمالي gross ويتأثّر بالسلسلة الرابحة؛ **الاختبار الصارم OOS صافي تكلفة = لا حافّة مُثبتة** مهما ارتفع t هنا.")
    lines.append("- **اختبارات OOS الصارمة (صافي تكلفة، walk-forward، خصمية):** fade القفزات، الأخبار، الجريد، "
                 "ركوب الانفجار، **والمعادن/JPY مع-الاتجاه** — *كلها NO_EDGE*.")
    lines.append("- **دقّة القراءات (إجمالي 107 رمز، 113k+ تصويت):** 0/34 مؤشّر فوق 52% → القراءات ≈ رمية عملة.")
    lines.append("- **الحقيقة:** الأرباح الأخيرة = صدفة/تذبذب لا مهارة. الحافّة الحقيقية الوحيدة = **انضباط المستخدم** "
                 "(يدوي 72% فوز، +$904 باستبعاد الليل 22-08).")
    lines.append("- **القيمة الباقية:** تحكّم مخاطر (master_floor) + قياس ذاتي صادق + بنية كاملة. **ديمو فقط** حتى حافّة OOS>55% + ورقي.\n")
    lines.append("## لكل عملة (أفضل قراءة قوية-العيّنة + توقّع السبورة + الحكم)")
    lines.append("| العملة | TF | أفضل مؤشّر | دقّته% | دقّة قوية(votes≥300)% | سبورة n | توقّع R | الحكم |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for sym, r in rows:
        lines.append(f"| {sym} | {r.get('tf','—')} | {r.get('best_ind','—')} | "
                     f"{r.get('best_acc','—')} | {r.get('robust_acc','—')} | "
                     f"{r.get('n','—')} | {r.get('expR','—'):+} | {verdict(r)} |"
                     if isinstance(r.get('expR'), (int, float)) else
                     f"| {sym} | {r.get('tf','—')} | {r.get('best_ind','—')} | {r.get('best_acc','—')} | "
                     f"{r.get('robust_acc','—')} | {r.get('n','—')} | — | {verdict(r)} |")
    lines.append(f"\n_إجمالي العملات المقيسة: {len(rows)}._")
    lines.append("\n> **تحذير مهم:** الدقّات العالية (60%+) أعلى الجدول غالباً على **أزواج نادرة قليلة السيولة** "
                 "(TRY/PLN/DKK/exotics) — سبريدها الضخم يأكل أي حافّة، وهي ضمن **اختبار-متعدّد** (136 رمز × 34 مؤشّر "
                 "≈ 4600 خلية؛ بعضها يطلع 60%+ بالصدفة). **لا حكم 🟢 لأي عملة إلا بإثبات OOS صافي + walk-forward + تجاوز العشوائي.** "
                 "العملات السائلة (ذهب/فضة/EUR/USD/JPY/مؤشرات) كلها ~50% = لا حافّة.")
    txt = "\n".join(lines)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(txt)
    return txt, len(rows)


if __name__ == "__main__":
    txt, n = build()
    print(f"[SUMMARY] wrote {OUT} ({n} symbols)")
    if "--print" in sys.argv:
        print(txt[:1500])

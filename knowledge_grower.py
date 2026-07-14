# -*- coding: utf-8 -*-
"""knowledge_grower.py — 🌱 يجعل معرفة المخّ تتكاثر بالخبرة الحيّة (طلب المستخدم «معارفه تتكاثر
بالمعرفة والخبرات»). يقطّر تجربة الأسطول الحقيقيّة إلى معرفةٍ منظّمة، مترابطة، **مقيسة لا مختلقة**،
تظهر في طبقة «معرفة» بالمخّ وتنمو كلّما عاش الأسطول أكثر.

المصادر (كلّها واقع): تاريخ MT5 لكل محرّك، fleet_mind، hand_edge، meta_learner، قرارات المُعالِج.
يكتب عناقيد عليا جديدة في الخزنة (فيعرضها المخّ كعناقيد منفصلة منظّمة)، ويربطها [[بالرموز]] و[[المحرّكات]]:
  13 خبرات المحرّكات · 14 خبرات الرموز · 15 خبرات الحلول · 16 حوافّ مقيسة · 17 سجلّ الخبرات (نامٍ).

⚖️ الصدق: كل «درس» مشتقٌّ من الأرقام (فوزٌ عالٍ + صافٍ سالب ⇒ خروج/حجم؛ لا-حافّة ⇒ لا-حافّة). لا حكمةٌ
مخترعة. قراءةٌ فقط على الصفقات؛ لا يتاجر. windowless، مسجّل بالوصيّ.
Run: pythonw knowledge_grower.py
"""
from __future__ import annotations
import sys, os, json, time, re
from datetime import datetime, timezone, timedelta
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
VAULT = MT5DIR / "plutobrain"
LOG = RN / "knowledge_grower.out.log"
STATUS_F = RN / "knowledge_grower_status.json"
POLL_S = 600     # كل 10 دقائق — المعرفة تنمو بلا ضجيج

try:
    RN.mkdir(parents=True, exist_ok=True)
    _lf = open(LOG, "a", buffering=1, encoding="utf-8"); sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass
if str(MT5DIR) not in sys.path:
    sys.path.insert(0, str(MT5DIR))

import MetaTrader5 as mt5
try:
    import engine_lock
except Exception:
    engine_lock = None

OURS = {20260701: "الحارس", 20260706: "R Core", 20260707: "قنّاص المجلس",
        20260709: "حارس العملات", 20260703: "محاكي راضي", 20260600: "الديسك", 20260631: "يوتيوب"}
F_ENG = VAULT / "13 خبرات المحرّكات"
F_SYM = VAULT / "14 خبرات الرموز"
F_RES = VAULT / "15 خبرات الحلول"
F_EDGE = VAULT / "16 حوافّ مقيسة"
F_TL = VAULT / "17 سجلّ الخبرات"


def _write(path: Path, text: str):
    """كتابة ذرّيّة (tmp+replace). لا يرمي أبداً."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception as e:
        print(f"write err {path.name}: {e}", flush=True)


def _read_json(name):
    try:
        return json.load(open(RN / name, encoding="utf-8"))
    except Exception:
        return None


def _lesson(n, wr, net):
    """درسٌ مقيسٌ من الأرقام (لا اختلاق): يعكس نمط «تربح بالتكرار لا بالمال» حين يظهر."""
    if n < 5:
        return "عيّنةٌ صغيرة — لا حكم بعد (انتظر تجربةً أكثر)."
    if wr >= 55 and net < 0:
        return "تربح بالتكرار لا بالمال: فوزٌ عالٍ لكن صافٍ سالب ⇒ التسريب في **الخروج/الحجم** لا اتّجاه الدخول."
    if net > 0 and wr >= 50:
        return "رابحٌ مقيس: انضباطُ الخروج + الحجم يعمل — حافِظ عليه، لا تكبّر الحجم."
    if net > 0:
        return "صافٍ موجب بفوزٍ منخفض ⇒ يترك الرابح يجري (payoff عالٍ)."
    return "صافٍ سالب ⇒ الكلفة تأكل الحافّة؛ الحافّة الوحيدة المثبتة = انضباط لا تنبّؤ."


def build():
    now = datetime.now(timezone.utc)
    n_notes = 0
    # ── خبرات المحرّكات + الرموز من تاريخ MT5 (آخر 90ي) ──
    deals = mt5.history_deals_get(int(time.time() - 90 * 86400), int(time.time())) or []
    eng = {}                        # magic -> {n,w,net,syms{sym:[n,net]}}
    sym = {}                        # symbol -> {n,w,net,mags{magic}}
    for d in deals:
        if d.entry != 1 or d.magic not in OURS:
            continue
        net = d.profit + d.commission + d.swap
        e = eng.setdefault(d.magic, {"n": 0, "w": 0, "net": 0.0, "syms": {}})
        e["n"] += 1; e["net"] += net; e["w"] += int(net > 0)
        s = e["syms"].setdefault(d.symbol, [0, 0.0]); s[0] += 1; s[1] += net
        sy = sym.setdefault(d.symbol, {"n": 0, "w": 0, "net": 0.0, "mags": set()})
        sy["n"] += 1; sy["net"] += net; sy["w"] += int(net > 0); sy["mags"].add(d.magic)
    fm = _read_json("fleet_mind.json") or {}
    fm_eng = (fm.get("engines") or {})

    for mg, e in eng.items():
        name = OURS.get(mg, str(mg))
        n, w, net = e["n"], e["w"], round(e["net"], 1)
        wr = round(w / n * 100) if n else 0
        top = sorted(e["syms"].items(), key=lambda kv: kv[1][1], reverse=True)
        links = " ".join(f"[[{s}]]" for s, _ in top[:6])
        why = (fm_eng.get(str(mg)) or {}).get("why", "—")
        txt = (f"# {name} (magic {mg})\n_معرفةٌ آليّة من التجربة الحيّة — {now.strftime('%Y-%m-%d %H:%M')} UTC_\n\n"
               f"- **صفقات:** {n} · **فوز:** {wr}% · **صافٍ:** {net}$\n"
               f"- **الحالة الآن:** {why}\n"
               + (f"- **أفضل رمز:** [[{top[0][0]}]] ({top[0][1][1]:+.1f}$) · **أسوأ:** [[{top[-1][0]}]] ({top[-1][1][1]:+.1f}$)\n" if len(top) >= 2 else "")
               + f"- **الدرس المقيس:** {_lesson(n, wr, net)}\n\n"
               f"رموزه: {links}\n\nمرتبطٌ بـ [[الحافّة الحقيقيّة]].\n")
        _write(F_ENG / f"{name}.md", txt); n_notes += 1

    for s, sy in sym.items():
        n, w, net = sy["n"], sy["w"], round(sy["net"], 1)
        wr = round(w / n * 100) if n else 0
        mags = " ".join(f"[[{OURS.get(m, m)}]]" for m in sy["mags"])
        txt = (f"# {s}\n_خبرة الأسطول على هذا الرمز — {now.strftime('%Y-%m-%d %H:%M')} UTC_\n\n"
               f"- **صفقات الأسطول:** {n} · **فوز:** {wr}% · **صافٍ:** {net}$\n"
               f"- **محرّكاته:** {mags}\n- **الدرس:** {_lesson(n, wr, net)}\n")
        _write(F_SYM / f"{s}.md", txt); n_notes += 1

    # ── حوافّ مقيسة: اليد + المتعلّم-الفوقيّ (صدقٌ صارم) ──
    he = _read_json("hand_edge.json") or {}
    meta = _read_json("meta_learner_progress.json") or {}
    truth = (he.get("headline") or {}).get("truth", "—")
    real = he.get("real_levers", [])
    verdict = meta.get("verdict", "—")
    edge_txt = (f"# الحافّة الحقيقيّة\n_مقيسةٌ خارج-العيّنة، تُحدَّث آليّاً — {now.strftime('%Y-%m-%d %H:%M')} UTC_\n\n"
                f"- **يد المستخدم:** {truth}\n"
                f"- **رافعات صمدت OOS:** {('، '.join(real)) if real else 'لا شيء يصمد بقوّة — الحافّة انضباط'}\n"
                f"- **المتعلّم-الفوقيّ:** {verdict}\n\n"
                f"**الخلاصة الثابتة:** الحافّة = **انضباط (حجم/خروج/فريم/ليل)** لا تنبّؤ. "
                f"كرّرها في كل [[الحارس]] و[[حارس العملات]] و[[قنّاص المجلس]].\n")
    _write(F_EDGE / "الحافّة الحقيقيّة.md", edge_txt); n_notes += 1

    # ── خبرات الحلول: ما فعله المُعالِج الذاتيّ (آخر القرارات) ──
    res_lines = []
    try:
        p = RN / "conflict_resolutions.jsonl"
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines()[-30:]:
                r = json.loads(ln)
                res_lines.append(f"- {r.get('iso','')} · [[{r.get('sym','?')}]] · {r.get('kind','')} · قُصّ عائم {r.get('floating','?')}$")
    except Exception:
        pass
    res_txt = (f"# خبرات المُعالِج الذاتيّ\n_ما حلّه النظام بنفسه — {now.strftime('%Y-%m-%d %H:%M')} UTC_\n\n"
               + ("\n".join(res_lines) if res_lines else "- لا تعارضاتٍ عولجت بعد (القرارات متّسقة). حارسٌ استقباليّ.")
               + "\n\nيمنع الدخول ضدّ الدولار ويقصّ المتعارض الخاسر. مرتبطٌ بـ [[الحافّة الحقيقيّة]].\n")
    _write(F_RES / "خبرات الحلول.md", res_txt); n_notes += 1

    # ── سجلّ الخبرات النامي: لقطةٌ يوميّة (تتكاثر بمرور الأيّام) ──
    tot_net = round(sum(e["net"] for e in eng.values()), 1)
    tot_n = sum(e["n"] for e in eng.values())
    day = now.strftime("%Y-%m-%d")
    tl = (f"# خبرة {day}\n\n- محرّكاتنا: {tot_n} صفقة · صافٍ {tot_net}$ · "
          f"{len(eng)} محرّكاً نشطاً على {len(sym)} رمزاً.\n"
          f"- أنشط محرّك: {OURS.get(max(eng, key=lambda m: eng[m]['n']), '?') if eng else '—'}.\n"
          f"- الدرس اليوميّ: {_lesson(tot_n, round(sum(e['w'] for e in eng.values())/max(tot_n,1)*100), tot_net)}\n\n"
          f"مرتبطٌ بـ [[الحافّة الحقيقيّة]].\n")
    _write(F_TL / f"{day}.md", tl); n_notes += 1

    try:
        json.dump({"ts": time.time(), "iso": now.strftime("%H:%M:%S"), "engine": "منمّي المعرفة",
                   "notes_written": n_notes, "engines": len(eng), "symbols": len(sym),
                   "vault_total": len(list(VAULT.rglob("*.md")))},
                  open(STATUS_F, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    print(f"🌱 نمت المعرفة: {n_notes} ملاحظة · {len(eng)} محرّك · {len(sym)} رمز · إجمال الخزنة {len(list(VAULT.rglob('*.md')))}", flush=True)


def main():
    if engine_lock:
        try:
            engine_lock.claim("knowledge_grower")
        except Exception:
            pass
    for _ in range(6):
        if mt5.initialize():
            break
        time.sleep(10)
    print(f"🌱 منمّي المعرفة بدأ — poll={POLL_S}s (يقطّر التجربة الحيّة إلى معرفةٍ مقيسة)", flush=True)
    while True:
        try:
            build()
        except Exception as e:
            print(f"build err: {type(e).__name__}: {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""swarm_director.py — الوكيل المايسترو الأعلى: «الوكيل الذي يوظّف الوكلاء». يدير **تكاثر وتشذيب**
الأسطول ذاتياً ضمن سقفٍ صارم — كي لا نوظّفهم نحن يدوياً.

لماذا يبقى توليد *الأكواد* الجديدة بيدنا؟ لأنّ كتابة كود تداول جديد ذاتياً خطر (قد ينزف/يُعصف).
لكن **إدارة جمهرة الوكلاء** (متى نُكثّر، متى نُشذّب، أين الفجوة) تُؤتمَت بأمان — وهذا ما يفعله هذا الوكيل:

  • 🧮 **سقف عمليّات صارم** (درس عاصفة 619-عمليّة): فوقه ⇒ لا تكاثر، تنبيه فقط.
  • 🔥 **تشذيب**: المحرّك المُقال (كارثيّ) باستمرار ⇒ يُوصي بإيقافه نهائياً (لا يقتل محرّك المستخدم تلقائياً — توصية).
  • 🌱 **تكاثر نحو ما ينجح**: حين يُثبت المايسترو رمزاً/فرقةً رابحةً صافيةً (tier=proven) ⇒ جاهز لتوليد متخصّص محكوم.
  • 🕳️ **ناقد الاكتمال**: يقرأ خريطة المنظومة (graph_report) ويكشف المعزول/الميت/المتقادم ويبلّغ.

النظام أصلاً يتكاثر استراتيجياً (الجينات تتطوّر) ويُشذّب (المايسترو يُقيل). هذا الوكيل يضيف **الإشراف الذاتيّ
على الجمهرة**. قراءة-فقط للقرارات الخطرة (يكتب توصياته في swarm_director.json). windowless تحت الوصيّ."""
from __future__ import annotations
from engine_lock import claim
import json, time
from pathlib import Path
import psutil

ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
OUT = RN / "swarm_director.json"
LOG = RN / "swarm_director.log"
GRAPH_REPORT = RN / "graph_report.json"
GOV = RN / "engine_governance.json"

PROC_CAP = 200          # 🧮 سقف العمليّات الصارم (دون 450 بهامش أمان) — فوقه لا تكاثر
CULL_AFTER = 8          # عدد دورات الإقالة-الكارثيّة المتتالية قبل التوصية بالتشذيب (8×120ث ≈ 16د)
POLL_S = 120.0

_fired_streak = {}      # {magic: عدد الدورات الكارثيّة المتتالية}


def _log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _load(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8-sig"))
    except Exception:
        return {} if d is None else d


def _proc_count():
    n = 0
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() in ("python.exe", "pythonw.exe"):
                n += 1
        except Exception:
            pass
    return n


def _cycle():
    procs = _proc_count()
    gov = _load(GOV)
    raw = gov.get("raw", {})
    paused = set(int(x) for x in gov.get("paused", []))
    gaps = (_load(GRAPH_REPORT).get("gaps") or {})

    # 🔥 تتبّع الإقالة المتتالية → توصية تشذيب
    cull_reco = []
    for mg, info in raw.items():
        mgi = int(mg)
        if info.get("tier") == "catastrophic":
            _fired_streak[mgi] = _fired_streak.get(mgi, 0) + 1
        else:
            _fired_streak[mgi] = 0
        if _fired_streak.get(mgi, 0) >= CULL_AFTER:
            cull_reco.append({"magic": mgi, "engine": info.get("engine"), "net": info.get("net"),
                              "streak": _fired_streak[mgi], "action": "RECOMMEND_CULL (كارثيّ مستمرّ — أوقفه نهائياً)"})

    # 🌱 جاهزيّة التكاثر: فرق مُثبتة ربحاً صافياً (لا شيء اليوم — صدق)
    proven = [{"magic": int(mg), "engine": info.get("engine"), "net": info.get("net")}
              for mg, info in raw.items() if info.get("tier") == "proven"]
    can_spawn = procs < PROC_CAP
    spawn_reco = []
    for pv in proven:
        if can_spawn:
            spawn_reco.append({**pv, "action": "READY_SPAWN_SPECIALIST (رابح صافٍ — وسّع نحوه)"})

    health = "HEALTHY"
    if gaps.get("disconnected") or gaps.get("dead_engines"):
        health = "GAPS"
    if procs >= PROC_CAP:
        health = "AT_PROC_CAP"

    out = {"ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "proc_count": procs, "proc_cap": PROC_CAP, "can_multiply": can_spawn,
           "health": health,
           "fired_now": sorted(paused),
           "cull_recommendations": cull_reco,        # تشذيب الخاسر المستمرّ
           "spawn_readiness": spawn_reco,            # تكاثر نحو المُثبت (idle حتى يُثبت أحدٌ)
           "gaps": gaps,
           "note": "الوكيل يوظّف الوكلاء: يُكثّر نحو المُثبت ويُشذّب الكارثيّ ضمن سقف العمليّات. توليد الكود يبقى بيدنا (أمان)."}
    tmp = OUT.with_suffix(".json.tmp")
    json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tmp.replace(OUT)
    if cull_reco:
        _log(f"🔥 توصية تشذيب: {[c['engine'] for c in cull_reco]}")
    if spawn_reco:
        _log(f"🌱 جاهز للتكاثر نحو: {[s['engine'] for s in spawn_reco]}")
    if procs >= PROC_CAP:
        _log(f"🧮 عند سقف العمليّات ({procs}/{PROC_CAP}) — أوقفتُ التكاثر")
    return out


def main():
    claim("swarm_director")
    _log(f"swarm_director start — مدير السرب (سقف {PROC_CAP} عمليّة)")
    while True:
        try:
            _cycle()
        except Exception as e:
            _log(f"loop err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()

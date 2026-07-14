"""
learning_pulse.py — نبضة التعلّم الدورية: يراجع حساباته كل ساعة بدل الانتظار.

كل ساعة:
  1. يعيد بناء الصندوق الأسود (r_trade_journal) لآخر يومين عبر كل الماجيكات —
     فيبقى التشريح (سبب كل ربح/خسارة، توافق الفريمات، السبريد) طازجاً دائماً.
  2. يكتب خلاصة مراجعة إلى data/r_native/learning_pulse.json:
     لكل ماجيك حيّ: WR/صافٍ/RR آخر 48 ساعة + أعلام إنذار صادقة
     (RR مقلوب، رشّ، ليل...) — مراجعة حسابات آلية بلا مجاملة.
  3. يلخّص تقدّم معرفة الماسح (كم نمط اقترب من عتبة المعنويّة n≥30).

تشغيل: pythonw learning_pulse.py   (حلقة أبدية، نبضة كل ساعة)
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "r_native" / "learning_pulse.json"
JOURNAL = ROOT / "data" / "r_native" / "r_trade_journal.jsonl"
KNOWLEDGE = ROOT / "data" / "r_native" / "market_knowledge.json"
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
PULSE_S = 3600


def rebuild_journal():
    r = subprocess.run([PY, str(ROOT / "r_trade_journal.py"), "--days", "2",
                        "--magic", "all"], capture_output=True, text=True,
                       cwd=str(ROOT), timeout=600)
    return r.returncode == 0


def review() -> dict:
    """مراجعة حسابات آلية صادقة من سجلّ الصندوق الأسود."""
    per = {}
    try:
        recs = [json.loads(l) for l in JOURNAL.read_text(encoding="utf-8").splitlines()]
    except Exception:
        recs = []
    for r in recs:
        m = str(r.get("magic"))
        d = per.setdefault(m, {"n": 0, "wins": 0, "net": 0.0, "win_sum": 0.0,
                               "loss_sum": 0.0, "night": 0, "stops": 0})
        d["n"] += 1
        d["net"] += r["net_usd"]
        if r["win"]:
            d["wins"] += 1; d["win_sum"] += r["net_usd"]
        else:
            d["loss_sum"] += r["net_usd"]
        h = r.get("entry_hour_utc", 12)
        if h >= 22 or h < 8:
            d["night"] += 1
        if "وقف" in r.get("exit_reason", ""):
            d["stops"] += 1
    for m, d in per.items():
        n = d["n"]
        aw = d["win_sum"] / d["wins"] if d["wins"] else 0.0
        al = d["loss_sum"] / (n - d["wins"]) if n - d["wins"] else 0.0
        d["wr"] = round(100.0 * d["wins"] / n, 1)
        d["rr"] = round(abs(aw / al), 2) if al else None
        d["net"] = round(d["net"], 2)
        flags = []
        if d["rr"] is not None and d["rr"] < 0.8 and n >= 15:
            flags.append("RR-مقلوب: متوسّط الخسارة أكبر من الربح")
        if n >= 60:
            flags.append("رشّ: >30 صفقة/يوم")
        if d["night"] > n * 0.5 and n >= 10:
            flags.append("أغلب الدخول ليليّ")
        if d["net"] < -20:
            flags.append(f"نازف: {d['net']}$ في 48س")
        d["alerts"] = flags
        del d["win_sum"], d["loss_sum"]
    return per


def knowledge_progress() -> dict:
    try:
        k = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    rows = [(x, v) for x, v in k.items()
            if isinstance(v, dict) and not x.startswith("_")]
    near = [x for x, v in rows if 20 <= v.get("n", 0) < 30]
    sig = [x for x, v in rows if v.get("trust") == "SIGNIFICANT"]
    return {"patterns": len(rows), "samples": sum(v.get("n", 0) for _, v in rows),
            "significant": len(sig), "near_threshold_20_29": len(near),
            "significant_keys": sig[:10]}


def main():
    print("learning_pulse يبدأ — نبضة كل ساعة")
    while True:
        t0 = time.time()
        ok = False
        try:
            ok = rebuild_journal()
            out = {"ts": time.time(), "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "journal_rebuilt": ok,
                   "review_48h_by_magic": review(),
                   "sweeper_knowledge": knowledge_progress()}
            OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            # 🎓 المُرقّي الآليّ (رودماب النضج): يقيس العتبات وينفّذ الانتقالات
            try:
                import stage_promoter
                st = stage_promoter.run(apply=True)
                print("stage_promoter:",
                      st["track1_sentinel"]["stage"],
                      "|", st["track5_account"]["stage"])
            except Exception as e:
                print(f"stage_promoter err: {type(e).__name__}: {e}")
            print(f"نبضة تمّت ({time.time()-t0:.0f}ث) — rebuilt={ok}")
        except Exception as e:
            print(f"pulse err: {type(e).__name__}: {e}")
        time.sleep(PULSE_S)


if __name__ == "__main__":
    main()

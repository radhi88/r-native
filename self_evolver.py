# -*- coding: utf-8 -*-
"""self_evolver.py — 🧬 حلقة التطوّر الذاتيّ الدائمة (طلب المستخدم 2026-07-04 «ديناميكيّ وآليّ وتعلّم
ذاتيّ ينشئ خوارزمياته الخاصة وينفّذ»). الصيغة الصادقة: يولّد خوارزميات، يمحّصها walk-forward بصرامة،
ويُرقّي الناجي **فقط** لخانة مرشّح ورقيّ — والباقي يُوثَّق ويُرمى. لا يتداول ضجيجاً أبداً.

الدورة (كلّ evolve_hours ساعة):
  1) يشغّل labs/indicator_lab.py (توليد 1400+ خوارزمية + كلفة + walk-forward 6 طيّات + t≥3).
  2) يقرأ الناجين. الجديد منهم (غير المعروف) ⇒ يُسجَّل في self_evolver_candidates.json «قيد التتبّع الورقيّ».
  3) المرشّحون الحاليّون يُعاد تقييمهم: من فقد صموده (اختفى من ناجي الجولة) ⇒ يُتقاعَد بعد grace جولات.
  4) يكتب حالته + يُغذّي الموجز الليليّ برقمٍ صادق: «ولّد N، نجا M، مرشّحون K».

⚖️ صدق صارم: المرشّح يبقى **ورقيّاً** (يُقاس فقط) حتى يجمع n≥100 إشارة حيّة + يبقى t≥3 عبر أنظمة
سوق متعددة — عندها فقط يُعرَض عليك للموافقة على تحويله لتنفيذ ديمو (قرارك أنت، لا تلقائيّاً).
ديمو فقط · يحترم kill_switch · windowless تحت الوصيّ."""
import os, sys, subprocess, json, time

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
try:
    _lf = open(os.path.join(_RN, "self_evolver.out.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

try:
    import engine_lock
    engine_lock.claim("self_evolver")
except SystemExit:
    raise
except Exception:
    pass

CFG_F = os.path.join(_RN, "self_evolver_config.json")
CAND_F = os.path.join(_RN, "self_evolver_candidates.json")
STATUS_F = os.path.join(_RN, "self_evolver_status.json")
LAB = os.path.join(_BASE, "labs", "indicator_lab.py")
LAB_RESULT = os.path.join(_RN, "indicator_lab_result.json")
ALARM = os.path.join(_RN, "news_alarm_feed.jsonl")
KILL1 = os.path.join(_RN, "kill_switch.txt")
KILL2 = os.path.join(_BASE, "kill_switch.txt")
NOWIN = 0x08000000


def _cfg():
    d = {"enabled": True, "evolve_hours": 6.0, "retire_grace": 3,
         "promote_min_signals": 100, "promote_min_t": 3.0,
         "_note": "🧬 التطوّر الذاتيّ: يولّد ويمحّص ويُرقّي الناجي ورقيّاً فقط. تحويل المرشّح لتنفيذ ديمو "
                  "يتطلّب n≥100 إشارة حيّة + t≥3 + موافقتك (لا تلقائيّاً). الأرقام لا تكذب."}
    try:
        d.update(json.load(open(CFG_F, encoding="utf-8")))
    except Exception:
        try:
            t = CFG_F + ".tmp"; json.dump(d, open(t, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            os.replace(t, CFG_F)
        except Exception:
            pass
    return d


def _load_cands():
    try:
        return json.load(open(CAND_F, encoding="utf-8"))
    except Exception:
        return {"candidates": {}, "history": []}


def _save(path, obj):
    try:
        t = path + ".tmp"; json.dump(obj, open(t, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(t, path)
    except Exception:
        pass


def _run_lab():
    """يشغّل مختبر الأرقام (توليد + محكمة) ويرجع قائمة الناجين، أو []."""
    try:
        subprocess.run([sys.executable, LAB], cwd=_BASE, creationflags=NOWIN,
                       timeout=600, capture_output=True)
    except Exception as e:
        print(f"lab run err: {type(e).__name__}: {e}")
    try:
        r = json.load(open(LAB_RESULT, encoding="utf-8"))
        return r.get("survivors", []), r.get("rules_tested", 0), r.get("expected_false_survivors", 0)
    except Exception:
        return [], 0, 0


def _digest(msg):
    try:
        with open(ALARM, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "iso": time.strftime("%H:%M:%S"),
                                "kind": "EVOLVE", "title": msg, "impact": "Info",
                                "currency": "ALL"}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _evolve_once(cfg):
    survivors, tested, exp_false = _run_lab()
    cands = _load_cands()
    C = cands["candidates"]
    surv_keys = {s["rule"] + "|" + s.get("dir", "") for s in survivors}
    # 1) سجّل الجديد
    added = 0
    for s in survivors:
        k = s["rule"] + "|" + s.get("dir", "")
        if k not in C:
            C[k] = {"rule": s["rule"], "dir": s.get("dir"), "first_seen": time.time(),
                    "rounds_survived": 1, "rounds_missing": 0, "best_t": s.get("t"),
                    "hz": s.get("hz"), "n": s.get("n"), "state": "paper"}
            added += 1
        else:
            C[k]["rounds_survived"] += 1; C[k]["rounds_missing"] = 0
            C[k]["best_t"] = max(C[k].get("best_t", 0) or 0, s.get("t", 0) or 0)
    # 2) قيّم الغائبين (فقدوا صمودهم)
    retired = 0
    for k in list(C):
        if k not in surv_keys:
            C[k]["rounds_missing"] = C[k].get("rounds_missing", 0) + 1
            if C[k]["rounds_missing"] >= int(cfg.get("retire_grace", 3)):
                cands["history"].append({"rule": C[k]["rule"], "retired_ts": time.time(),
                                         "reason": f"فقد صموده {C[k]['rounds_missing']} جولات"})
                del C[k]; retired += 1
    cands["history"] = cands["history"][-200:]
    _save(CAND_F, cands)
    live = len(C)
    honest = ("لا حافّة صامدة بعد (المتوقَّع علمياً)" if live == 0
              else f"{live} مرشّح ورقيّ قيد التتبّع — لا تنفيذ حتى n≥{cfg.get('promote_min_signals',100)}")
    _digest(f"🧬 تطوّر: ولّد {tested} خوارزمية · نجا {len(survivors)} (صدفة متوقَّعة ~{exp_false}) · "
            f"جديد {added} · متقاعد {retired} · {honest}")
    _save(STATUS_F, {"ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "last_tested": tested, "last_survivors": len(survivors),
                     "expected_false": exp_false, "candidates_live": live,
                     "added": added, "retired": retired, "verdict": honest})
    print(f"🧬 دورة: {tested} خوارزمية · {len(survivors)} ناجٍ · {live} مرشّح · {honest}")


def main():
    print(f"🧬 التطوّر الذاتيّ بدأ {time.strftime('%Y-%m-%d %H:%M:%S')} — يولّد ويمحّص، يُرقّي الناجي فقط")
    cfg = _cfg()
    last = 0.0
    while True:
        try:
            cfg = _cfg()
            if not cfg.get("enabled", True) or os.path.exists(KILL1) or os.path.exists(KILL2):
                time.sleep(60); continue
            now = time.time()
            if now - last >= float(cfg.get("evolve_hours", 6.0)) * 3600:
                _evolve_once(cfg)
                last = now
        except Exception as e:
            print(f"loop err: {type(e).__name__}: {e}")
        time.sleep(120)


if __name__ == "__main__":
    main()

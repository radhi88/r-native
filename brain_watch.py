# -*- coding: utf-8 -*-
"""brain_watch.py — 👁️ حارس المخ الواحد (طلب المستخدم 2026-07-04): يراقب unified_brain.json كل 3ث،
وحين تظهر فرصة قناعة عالية (conviction ≥ thr و اتّفاق ≥ 3 عيون) يكتب تنبيهاً في قناة الجوّال
(news_alarm_feed.jsonl) — يُرحَّل لك عبر المراقب. تبريد لكل رمز+اتجاه كي لا يتكرّر التنبيه.

قراءة ملفّ خالصة، بلا MT5، windowless. لا يتداول — التنبيه فقط."""
import os, sys, json, time

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
try:
    _lf = open(os.path.join(_RN, "brain_watch.out.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

try:
    import engine_lock
    engine_lock.claim("brain_watch")
except SystemExit:
    raise
except Exception:
    pass

UNI_F = os.path.join(_RN, "unified_brain.json")
ALARM = os.path.join(_RN, "news_alarm_feed.jsonl")
CFG_F = os.path.join(_RN, "brain_watch_config.json")
_last = {}


def _cfg():
    d = {"enabled": True, "conviction_thr": 0.50, "agree_min": 3, "cooldown_min": 20}
    try:
        d.update(json.load(open(CFG_F, encoding="utf-8")))
    except Exception:
        try:
            t = CFG_F + ".tmp"; json.dump(d, open(t, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            os.replace(t, CFG_F)
        except Exception:
            pass
    return d


def _alarm(sym, o):
    try:
        with open(ALARM, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "iso": time.strftime("%H:%M:%S"),
                                "kind": "BRAIN-OPP", "currency": sym, "impact": "High",
                                "title": f"🧠 المخ الواحد: فرصة {o['verdict']} على {sym} — "
                                         f"قناعة {int(o['conviction']*100)}% · اتّفاق {o['agree']}/4 "
                                         f"(نبض {o['voices'].get('نبض')}·مكتب {o['voices'].get('مكتب')}·"
                                         f"بنية {o['voices'].get('بنية')})"},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass


def main():
    print(f"👁️ حارس المخ بدأ {time.strftime('%Y-%m-%d %H:%M:%S')}")
    while True:
        try:
            cfg = _cfg()
            if not cfg.get("enabled", True):
                time.sleep(10); continue
            try:
                u = json.load(open(UNI_F, encoding="utf-8"))
            except Exception:
                time.sleep(5); continue
            if time.time() - float(u.get("ts", 0)) > 30:      # مخ قديم ⇒ لا تنبيه
                time.sleep(5); continue
            thr = float(cfg.get("conviction_thr", 0.50)); amin = int(cfg.get("agree_min", 3))
            cd = float(cfg.get("cooldown_min", 20)) * 60
            for sym, o in (u.get("symbols") or {}).items():
                try:
                    if o.get("dir", 0) == 0 or float(o.get("conviction", 0)) < thr or int(o.get("agree", 0)) < amin:
                        continue
                    key = f"{sym}|{o['dir']}"
                    if time.time() - _last.get(key, 0) < cd:
                        continue
                    _last[key] = time.time()
                    _alarm(sym, o)
                    print(f"🔔 فرصة: {sym} {o['verdict']} قناعة {o['conviction']}")
                except Exception:
                    continue
        except Exception as e:
            print(f"loop err: {type(e).__name__}: {e}")
        time.sleep(3)


if __name__ == "__main__":
    main()

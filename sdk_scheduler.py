"""sdk_scheduler.py — يشغّل محرّك القرار كل 5 دقائق لتحديث الانحياز الحيّ (sdk_decision.json).

يشغّل friday_decision.py (المحرّك المحلّي): مُصنّف ريجيم حتمي بالكود ($0، يشتغل دائمًا)
+ ترقية تلقائية لـClaude لو وُجد رصيد API. الانضباط الليلي مفروض بالكود.
قفل نسخة-واحدة: لو معيد التشغيل أطلق نسخًا، المالك فقط يحدّث، الباقي يخمل (يمنع تضارب الملف).

تشغيل:  python sdk_scheduler.py   (--interval 600 لتغيير الفاصل)
"""
import argparse, json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(r"C:\Users\Radhi\MT5\friday_decision.py")
LOCK = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\sdk_scheduler.lock")

def _leader(interval):
    me = os.getpid(); now = time.time()
    try:
        d = json.loads(LOCK.read_text(encoding="utf-8"))
        if d.get("pid") != me and (now - float(d.get("ts", 0))) < interval + 90:
            return False                       # نسخة حيّة أخرى تملك القفل
    except Exception:
        pass
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(json.dumps({"pid": me, "ts": now}), encoding="utf-8")
        return json.loads(LOCK.read_text(encoding="utf-8")).get("pid") == me
    except Exception:
        return True

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--interval", type=int, default=300)
    a = ap.parse_args()
    print(f"[sdk_scheduler] كل {a.interval}s · قفل نسخة-واحدة · Ctrl-C يوقف", flush=True)
    while True:
        t = datetime.now(timezone.utc).strftime("%H:%M:%S")
        if not _leader(a.interval):
            print(f"[sdk_scheduler {t}] follower — نسخة أخرى تقود، خامل", flush=True)
            time.sleep(a.interval); continue
        try:
            r = subprocess.run([sys.executable, "-u", str(SCRIPT)],
                               capture_output=True, text=True, timeout=a.interval - 30)
            ok = r.returncode == 0
            print(f"[sdk_scheduler {t}] {'✓ حدّث الانحياز' if ok else '✗ '+str(r.returncode)}"
                  + ("" if ok else f" :: {(r.stderr or '')[-200:]}"), flush=True)
        except subprocess.TimeoutExpired:
            print(f"[sdk_scheduler {t}] ⏱ تجاوز الوقت", flush=True)
        except Exception as e:
            print(f"[sdk_scheduler {t}] خطأ: {e}", flush=True)
        time.sleep(a.interval)

if __name__ == "__main__":
    raise SystemExit(main())

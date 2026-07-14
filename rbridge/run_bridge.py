"""
run_bridge.py — مُطلِق متين لجسر rbridge تحت pythonw (بلا كونسول/منفصل).

السبب: تشغيل `-m uvicorn --app-dir` تحت pythonw منفصل يموت لأنّ stdout/stderr معدومان
(تسجيل uvicorn يكتب إلى مجرى غير موجود ⇒ انهيار). هذا المُطلِق يُأمّن المجاري إلى ملفّ سجلّ
ثم يُشغّل uvicorn برمجياً (server:app قابل للاستيراد من هذا المجلد). يطابق نمط الخدمات
الويندوزية المتينة في المشروع.

تشغيل (الحارس):  pythonw run_bridge.py   (cwd = rbridge)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 🛡️ تأمين المجاري للوضع بلا-كونسول (pythonw/منفصل) — وإلا ينهار uvicorn عند أوّل سطر سجلّ
try:
    if sys.stdout is None or not hasattr(sys.stdout, "write"):
        sys.stdout = open(os.path.join(HERE, "rbridge.out.log"), "a", buffering=1, encoding="utf-8")
    if sys.stderr is None or not hasattr(sys.stderr, "write"):
        sys.stderr = sys.stdout
except Exception:
    pass

import socket
import uvicorn

# 🛡️ قفل مفرد (درس عطل 2026-06-28): يمنع تكدّس نسخ الجسر الذي خنق طرفية MT5. لو نسخة تعمل، نخرج فوراً.
_LOCK_PORT = 8099
_lock_sock = None


def _acquire_singleton():
    global _lock_sock
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", _LOCK_PORT))   # ربط حصريّ (ويندوز: افتراضيّاً لا يُعاد استخدامه)
        s.listen(1)
        _lock_sock = s                       # أبقِه حيّاً طوال عمر العملية
        return True
    except OSError:
        return False


if __name__ == "__main__":
    if not _acquire_singleton():
        print("[rbridge] نسخة أخرى تعمل بالفعل — خروج (قفل مفرد)")
        sys.exit(0)
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="warning")

"""watchdog_keepalive.py — مَن يحرس الحارس؟ هذا.

watchdog_guard.py يُبقي الـ40 محرّكاً حيّة، لكن لا شيء كان يُبقي الحارس نفسه حيّاً —
فمات بصمت 41 ساعة (2026-06-18) وأظلم النظام كلّه دون أن يعيد أحدٌ تشغيله.

هذا السكربت بسيط متعمّداً: إن لم يكن watchdog_guard حيّاً، أطلقه windowless ثم اخرج.
آمن للتكرار: watchdog_guard يضمن نسخة واحدة + يكتشف المحرّكات الحيّة بمطابقة cmdline،
فلا يُكرّر شيئاً. تُشغّله مهمة Windows مجدولة كل 5 دقائق + عند تسجيل الدخول.

(يعمل فقط عند تسجيل الدخول لأن طرفية MT5 لا تعمل إلا في جلسة المستخدم — لا فائدة من
الحارس بدون MT5، ولا حاجة لكلمة مرور.)
"""
from __future__ import annotations
import os
import subprocess

import psutil

MT5 = r"C:\Users\Radhi\MT5"
PYW = MT5 + r"\.venv\Scripts\pythonw.exe"
if not os.path.exists(PYW):
    PYW = "pythonw"
FLAGS = 0x00000008 | 0x00000200          # DETACHED | NEW_PROCESS_GROUP — windowless


def _watchdog_alive() -> bool:
    for p in psutil.process_iter(["cmdline"]):
        try:
            cl = " ".join(p.info.get("cmdline") or [])
            if "watchdog_guard" in cl and "shell-snapshot" not in cl and "keepalive" not in cl:
                return True
        except Exception:
            continue
    return False


def main():
    if _watchdog_alive():
        return
    subprocess.Popen([PYW, "watchdog_guard.py"], cwd=MT5, creationflags=FLAGS)


if __name__ == "__main__":
    main()

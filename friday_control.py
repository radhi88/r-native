# -*- coding: utf-8 -*-
"""friday_control.py — لوحة تحكّم بنقرة: تشغيل / إيقاف نظام FRIDAY + حالة حيّة.

تشغيل  = يزيل kill_switch ثم يطلق watchdog_guard.py (الذي يُبقي كل المحرّكات حيّة).
إيقاف  = يكتب kill_switch.txt ثم يقتل الحارس أولاً (كي لا يُعيد التشغيل) ثم كل المحرّكات.
لا بدء تلقائي — أنت تتحكّم. (المهمّة المجدولة FRIDAY_Watchdog_Keepalive مُعطّلة.)
"""
from __future__ import annotations
import os, time, subprocess
import tkinter as tk
import psutil

MT5 = r"C:\Users\Radhi\MT5"
PYW = os.path.join(MT5, ".venv", "Scripts", "pythonw.exe")
if not os.path.exists(PYW):
    PYW = "pythonw"
KILL = os.path.join(MT5, "kill_switch.txt")
SELF = os.getpid()
FLAGS = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP — windowless

HINTS = ['watchdog', 'army_warroom', 'multi_trader', 'gene_tournament', 'brain_server', 'brain.py',
         'master_floor', 'edge_guard', 'manual_feature', 'accuracy_updater', 'evolution', 'autopilot',
         'scalp_evolver', 'news_gene', 'spike_rider', 'orb_trader', 'unified_trader', 'paper_prover',
         'footprint', 'chart_signal', 'genome_academy', 'r_native', 'friday_']


def _our_procs():
    out = []
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if p.info['pid'] == SELF:
                continue
            if (p.info['name'] or '').lower() not in ('pythonw.exe', 'python.exe'):
                continue
            cl = " ".join(p.info['cmdline'] or [])
            if 'friday_control' in cl:        # لا تقتل نفسك
                continue
            if 'MT5' in cl and any(h in cl for h in HINTS):
                out.append(p)
        except Exception:
            continue
    return out


def _watchdog_alive():
    for p in _our_procs():
        try:
            cl = " ".join(p.cmdline())
            if 'watchdog_guard' in cl and 'keepalive' not in cl:
                return True
        except Exception:
            pass
    return False


def start_system():
    try:
        if os.path.exists(KILL):
            os.remove(KILL)
    except Exception:
        pass
    subprocess.Popen([PYW, "watchdog_guard.py"], cwd=MT5, creationflags=FLAGS)


def stop_system():
    try:
        with open(KILL, "w", encoding="utf-8") as f:
            f.write("manual stop " + time.strftime('%Y-%m-%dT%H:%M:%S'))
    except Exception:
        pass
    # اقتل الحرّاس أولاً كي لا يُعيدوا إطلاق المحرّكات
    for p in _our_procs():
        try:
            if 'watchdog' in " ".join(p.cmdline()):
                p.kill()
        except Exception:
            pass
    time.sleep(0.6)
    for p in _our_procs():
        try:
            p.kill()
        except Exception:
            pass


# ---------------- واجهة ----------------
root = tk.Tk()
root.title("تحكّم FRIDAY")
root.geometry("320x210")
root.configure(bg="#0d1117")
root.resizable(False, False)

tk.Label(root, text="نظام FRIDAY", font=("Segoe UI", 14, "bold"), bg="#0d1117", fg="#c9d1d9").pack(pady=(14, 2))
status = tk.Label(root, text="...", font=("Segoe UI", 12), bg="#0d1117", fg="#c9d1d9")
status.pack(pady=6)

bf = tk.Frame(root, bg="#0d1117")
bf.pack(pady=10)


def refresh():
    n = len(_our_procs())
    if _watchdog_alive():
        status.config(text=f"🟢  يعمل  ·  {n} محرّك", fg="#3fb950")
    elif n > 0:
        status.config(text=f"🟡  محرّكات بلا حارس  ·  {n}", fg="#d29922")
    else:
        status.config(text="🔴  متوقّف", fg="#f85149")
    root.after(2000, refresh)


def do_start():
    status.config(text="… يبدأ", fg="#d29922")
    start_system()
    root.after(2000, refresh)


def do_stop():
    status.config(text="… يوقف", fg="#d29922")
    root.after(50, lambda: (stop_system(), root.after(800, refresh)))


tk.Button(bf, text="▶  تشغيل", command=do_start, width=10, height=2,
          bg="#238636", fg="white", font=("Segoe UI", 11, "bold"), relief="flat",
          activebackground="#2ea043").pack(side="right", padx=10)
tk.Button(bf, text="■  إيقاف", command=do_stop, width=10, height=2,
          bg="#da3633", fg="white", font=("Segoe UI", 11, "bold"), relief="flat",
          activebackground="#f85149").pack(side="left", padx=10)

tk.Label(root, text="لا بدء تلقائي — التحكّم يدوي", font=("Segoe UI", 8),
         bg="#0d1117", fg="#6e7681").pack(side="bottom", pady=6)

refresh()
root.mainloop()

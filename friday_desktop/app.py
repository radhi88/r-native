# -*- coding: utf-8 -*-
"""FRIDAY Desktop — مُشغّل النافذة الأصلية.

نافذة سطح مكتب حقيقية (WebView2 المدمج في ويندوز 11، بلا متصفّح ظاهر، بلا Tauri/MSVC).
يضمن أن خلفية FastAPI تعمل على :8770 ثم يفتح الواجهة داخل نافذة أصلية.

تشغيل:  pythonw friday_desktop\\app.py   (أو من الاختصار على سطح المكتب)
"""
from __future__ import annotations
import socket, subprocess, sys, time
from pathlib import Path
from urllib.request import urlopen

MT5DIR = Path(__file__).resolve().parent.parent
PY = str(MT5DIR / ".venv" / "Scripts" / "python.exe")
URL = "http://127.0.0.1:8770"
PORT = 8770


def _alive() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=1):
            return True
    except OSError:
        return False


def _ensure_backend():
    if _alive():
        return
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP — يبقى حيّاً بعد إغلاق النافذة
    flags = 0x00000008 | 0x00000200
    subprocess.Popen(
        [PY, "-m", "uvicorn", "friday_desktop.backend.server:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=str(MT5DIR), creationflags=flags,
    )
    for _ in range(40):  # انتظر حتى 20ث حتى يرتفع
        if _alive():
            try:
                urlopen(URL + "/api/status", timeout=2).read()
            except Exception:
                pass
            return
        time.sleep(0.5)


def main():
    _ensure_backend()
    try:
        import webview
    except ImportError:
        # احتياط: افتح في نافذة متصفّح بنمط تطبيق
        import webbrowser
        webbrowser.open(URL)
        return
    win = webview.create_window(
        "FRIDAY", URL, width=1320, height=860, min_size=(940, 620),
        background_color="#0b0f14", text_select=False,
    )
    # gui='edgechromium' = WebView2 (موجود افتراضياً على ويندوز 11)
    webview.start(gui="edgechromium")


if __name__ == "__main__":
    sys.exit(main() or 0)

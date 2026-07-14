# -*- coding: utf-8 -*-
"""R Trader — مُشغّل النافذة الأصلية (نمط friday_desktop).

نافذة سطح مكتب حقيقية (WebView2 المدمج في ويندوز 11) تفتح بوّابة R Trader الموحّدة
على :8020 — منفذ واحد يجمع القمرة (:8016) والخريطة (:8012) وخلفية FRIDAY (:8770).
يضمن أن البوّابة (r_trader/gateway.py) حيّة قبل فتح النافذة.

تشغيل:  pythonw r_trader\\app.py   (أو R_TRADER.bat)
"""
from __future__ import annotations
import socket, subprocess, sys, time
from pathlib import Path
from urllib.request import urlopen

MT5DIR = Path(__file__).resolve().parent.parent
PYW = str(MT5DIR / ".venv" / "Scripts" / "pythonw.exe")
if not Path(PYW).exists():
    PYW = "pythonw"
URL = "http://127.0.0.1:8020"
PORT = 8020


def _alive() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=1):
            return True
    except OSError:
        return False


def _icon() -> str | None:
    """أيقونة R إن وُجدت (r_native/assets/r_logo.*)."""
    for name in ("r_logo.ico", "r_logo.png"):
        p = MT5DIR / "r_native" / "assets" / name
        if p.exists():
            return str(p)
    return None


def _ensure_gateway():
    """أطلق البوّابة إن لم تكن حيّة، ثم انتظر جاهزيتها حتى 60ث (urllib poll)."""
    if not _alive():
        # CREATE_NO_WINDOW — بلا نافذة، ونفس صيغة needle الوصيّ ("r_trader/gateway.py")
        # كي يَعدّها watchdog_guard حيّةً ولا يزرع نسخةً ثانية.
        try:
            subprocess.Popen([PYW, "r_trader/gateway.py"], cwd=str(MT5DIR),
                             creationflags=0x08000000)
        except Exception:
            pass
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            urlopen(URL + "/", timeout=2).read(64)
            return
        except Exception:
            time.sleep(0.5)


def main():
    _ensure_gateway()
    try:
        import webview
    except ImportError:
        # احتياط: افتح في المتصفّح إن غاب pywebview
        import webbrowser
        webbrowser.open(URL)
        return
    webview.create_window(
        "R Trader", URL, width=1500, height=950, min_size=(1000, 650),
        background_color="#0b0d12", text_select=False, confirm_close=False,
    )
    icon = _icon()
    try:
        # gui='edgechromium' = WebView2 (موجود افتراضياً على ويندوز 11)
        webview.start(gui="edgechromium", icon=icon)
    except TypeError:
        # نسخ pywebview الأقدم لا تعرف icon= — افتح بلا أيقونة
        webview.start(gui="edgechromium")


if __name__ == "__main__":
    sys.exit(main() or 0)

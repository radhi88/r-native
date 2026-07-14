# -*- coding: utf-8 -*-
"""tv_tunnel_keeper.py — 🚇 حارس نفق TradingView: يُبقي cloudflared حيّاً نحو جسر :8025.

يشغّل tools/cloudflared.exe tunnel --url http://localhost:8025 ويعيد تشغيله إن مات،
يلتقط رابط trycloudflare من مخرجاته ويكتبه في data/r_native/tv_tunnel.json،
ويكتب نبضاً في tv_tunnel_status.json كل 30ث (ليحرسه watchdog_guard كبقيّة المحرّكات).

Run: pythonw tv_tunnel_keeper.py — نسخة واحدة فقط (engine_lock).
"""
from __future__ import annotations
import json, re, subprocess, sys, time, urllib.request
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
CF = MT5DIR / "tools" / "cloudflared.exe"
URL_F = RN / "tv_tunnel.json"
STATUS_F = RN / "tv_tunnel_status.json"
LOG = RN / "tv_tunnel.out.log"
CF_LOG = RN / "tv_tunnel_cloudflared.log"
TARGET = "http://localhost:8025"

try:
    RN.mkdir(parents=True, exist_ok=True)
    _lf = open(LOG, "a", buffering=1, encoding="utf-8"); sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass
if str(MT5DIR) not in sys.path:
    sys.path.insert(0, str(MT5DIR))

try:
    import engine_lock
    engine_lock.claim("tv_tunnel_keeper")   # 🔒 نسخة واحدة فقط
except SystemExit:
    raise
except Exception:
    pass

_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
FLAGS = 0x08000000  # CREATE_NO_WINDOW
_PYW = MT5DIR / ".venv" / "Scripts" / "pythonw.exe"
PYW = str(_PYW) if _PYW.exists() else "pythonw"
BRIDGE = MT5DIR / "tradingview_bridge.py"


def _bridge_alive() -> bool:
    """فحص صحّة الجسر على :8025 (GET بلا سرّ)."""
    try:
        with urllib.request.urlopen("http://localhost:8025/tv", timeout=4) as r:
            return r.status == 200
    except Exception:
        return False


def _ensure_bridge() -> None:
    """إن كان الجسر ميّتاً، أطلقه windowless (ديمو، سرّ، execute من الإعداد)."""
    if _bridge_alive():
        return
    try:
        subprocess.Popen([PYW, str(BRIDGE)], cwd=str(MT5DIR), creationflags=FLAGS)
        print("🌉 الجسر كان متوقّفاً — أُعيد تشغيله", flush=True)
        time.sleep(3)
    except Exception as e:
        print(f"تعذّر إطلاق الجسر: {e}", flush=True)


def _status(url: str | None, alive: bool):
    try:
        json.dump({"ts": time.time(), "iso": time.strftime("%H:%M:%S"),
                   "engine": "نفق TradingView", "target": TARGET,
                   "url": url, "cloudflared_alive": alive},
                  open(STATUS_F, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def _run_once() -> None:
    """يشغّل cloudflared حتى يموت؛ يلتقط الرابط، يحرس الجسر، ويكتب النبض كل ~30ث."""
    _ensure_bridge()
    cf_log = open(CF_LOG, "a", encoding="utf-8", buffering=1)
    p = subprocess.Popen([str(CF), "tunnel", "--url", TARGET],
                         stdout=cf_log, stderr=subprocess.STDOUT,
                         cwd=str(MT5DIR), creationflags=FLAGS)
    print(f"🚇 cloudflared أُطلق (pid {p.pid}) → {TARGET}", flush=True)
    url = None
    last_beat = 0.0
    while p.poll() is None:
        if url is None:
            try:
                m = _URL_RE.findall(CF_LOG.read_text(encoding="utf-8", errors="ignore")[-20000:])
                if m:
                    url = m[-1]
                    json.dump({"url": url, "webhook": url + "/tv", "target": TARGET,
                               "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                              open(URL_F, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                    print(f"🌍 الرابط العام: {url}/tv", flush=True)
            except Exception:
                pass
        if time.time() - last_beat >= 30:
            _ensure_bridge()                       # 🌉 احرس الجسر أيضاً كل ~30ث
            _status(url, True); last_beat = time.time()
        time.sleep(2)
    print(f"⚠️ cloudflared مات (rc={p.returncode}) — إعادة تشغيل بعد 5ث", flush=True)
    _status(url, False)


def main():
    print("🚇 حارس نفق TradingView بدأ — لا نتوقّف", flush=True)
    while True:
        try:
            _run_once()
        except Exception as e:
            print(f"err {e}", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()

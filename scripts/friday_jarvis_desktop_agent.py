from __future__ import annotations

import base64
import datetime as dt
import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
import requests
from fastapi import FastAPI
from pydantic import BaseModel

ROOT = Path(r"C:\Users\Radhi\MT5")
RUNTIME = ROOT / "runtime"
SCREEN_DIR = RUNTIME / "screenshots"
LOG_FILE = RUNTIME / "jarvis_actions.log"

OPENJARVIS_URL = os.getenv("OPENJARVIS_URL", "http://127.0.0.1:8000/v1/chat/completions")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
VISION_MODEL = os.getenv("FRIDAY_VISION_MODEL", "llava:latest")
TEXT_MODEL = os.getenv("FRIDAY_OLLAMA_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:3b-instruct"))

SAFE_URLS = {
    "brain": "http://127.0.0.1:8844",
    "dashboard": "http://127.0.0.1:8790",
    "tradingview": "http://127.0.0.1:8822",
    "algory": "http://127.0.0.1:8866",
    "agents": "http://127.0.0.1:8833",
    "chat": "http://127.0.0.1:8811",
    "gateway": "http://127.0.0.1:8799",
    "agent": "http://127.0.0.1:8855/health",
}

APP_ALLOWLIST = {
    "notepad": "notepad.exe",
    "calc": "calc.exe",
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "vscode": r"C:\Users\Radhi\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "mt5": r"C:\Program Files\MetaTrader 5\terminal64.exe",
}

FRIDAY_SCRIPTS = [
    "friday_indicator_feature_engine",
    "friday_feature_outcome_learner",
    "friday_trade_outcome_learner",
    "friday_local_gateway",
    "friday_chat_app",
    "friday_scalper_live_dashboard",
    "friday_agents_browser",
    "friday_live_brain_state",
    "friday_autopilot_supervisor",
    "friday_realtime_scalper_demo_executor",
    "friday_touch_demo_executor",
    "friday_demo_position_governor_v2",
    "friday_orderflow_feature_engine",
    "ict_sweep_trader",
    "run_friday_voice",
    "friday_jarvis_voice_bridge",
]

SERVICE_PORTS = {
    "Gateway": 8799,
    "AI Dashboard": 8790,
    "Chat": 8811,
    "TradingView": 8822,
    "Agents Browser": 8833,
    "Brain State": 8844,
    "Jarvis Agent": 8855,
    "Algory Charts": 8866,
}

app = FastAPI(title="FRIDAY Jarvis Desktop Agent", version="1.0")


class ActionRequest(BaseModel):
    action: str
    args: Dict[str, Any] = {}
    confirm: Optional[str] = None


class CommandRequest(BaseModel):
    text: str


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_action(action: str, args: Any, result: Any, source: str = "api") -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    line = f"{now()} | {source} | {action} | {str(args)[:300]} | {str(result)[:500]}\n"
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line)


def check_port(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except Exception:
        return False


def service_status() -> Dict[str, Any]:
    return {name: {"port": port, "up": check_port(port)} for name, port in SERVICE_PORTS.items()}


def get_windows() -> List[Dict[str, Any]]:
    try:
        import pygetwindow as gw
        active = gw.getActiveWindow()
        active_title = active.title if active else ""
        out = []
        for w in gw.getAllWindows():
            title = (w.title or "").strip()
            if not title:
                continue
            out.append({
                "title": title,
                "left": getattr(w, "left", None),
                "top": getattr(w, "top", None),
                "width": getattr(w, "width", None),
                "height": getattr(w, "height", None),
                "is_active": title == active_title,
            })
        return out[:80]
    except Exception as exc:
        return [{"error": str(exc)}]


def active_window_title() -> str:
    try:
        import pygetwindow as gw
        w = gw.getActiveWindow()
        return w.title if w else ""
    except Exception:
        return ""


def friday_processes() -> List[Dict[str, Any]]:
    items = []
    for p in psutil.process_iter(["pid", "name", "cmdline", "cpu_percent", "memory_info"]):
        try:
            cmd = " ".join(p.info.get("cmdline") or [])
            if any(s.lower() in cmd.lower() for s in FRIDAY_SCRIPTS):
                mem = p.info.get("memory_info")
                items.append({
                    "pid": p.info["pid"],
                    "name": p.info.get("name"),
                    "cmd": cmd[:500],
                    "ram_mb": round((mem.rss if mem else 0) / 1024 / 1024, 1),
                })
        except Exception:
            pass
    return items


def take_screenshot(monitor_index: int = 0) -> str:
    """Take a screenshot of a specific monitor (0 = all monitors combined, 1+ = specific monitor).

    mss.monitors[0] is the virtual combined bounding box of all monitors.
    mss.monitors[1] is the first physical monitor, mss.monitors[2] the second, etc.
    """
    import mss
    from PIL import Image

    SCREEN_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
    label = "all" if monitor_index == 0 else f"mon{monitor_index}"
    path = SCREEN_DIR / f"desktop_{label}_{ts}.png"

    with mss.mss() as sct:
        # monitor_index 0 = combined bounding box (all monitors)
        # Clamp to valid range
        idx = max(0, min(monitor_index, len(sct.monitors) - 1))
        monitor = sct.monitors[idx]
        img = sct.grab(monitor)
        im = Image.frombytes("RGB", img.size, img.rgb)
        im.save(path)

    log_action("screenshot", {"monitor": monitor_index}, str(path), "agent")
    return str(path)


def take_all_screenshots() -> List[Dict[str, Any]]:
    """Take individual screenshots of every physical monitor. Returns list of {monitor, path}."""
    import mss
    from PIL import Image

    SCREEN_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
    results = []

    with mss.mss() as sct:
        monitor_count = len(sct.monitors) - 1  # index 0 is combined
        for i in range(1, monitor_count + 1):
            path = SCREEN_DIR / f"desktop_mon{i}_{ts}.png"
            monitor = sct.monitors[i]
            img = sct.grab(monitor)
            im = Image.frombytes("RGB", img.size, img.rgb)
            im.save(path)
            results.append({
                "monitor": i,
                "path": str(path),
                "width": monitor["width"],
                "height": monitor["height"],
                "left": monitor["left"],
                "top": monitor["top"],
            })

    log_action("screenshot_all", {}, f"{len(results)} monitors", "agent")
    return results


def monitor_info() -> Dict[str, Any]:
    """Return geometry info for all connected monitors."""
    try:
        import mss
        with mss.mss() as sct:
            monitors = []
            for i, m in enumerate(sct.monitors):
                monitors.append({
                    "index": i,
                    "label": "combined" if i == 0 else f"monitor_{i}",
                    "left": m["left"],
                    "top": m["top"],
                    "width": m["width"],
                    "height": m["height"],
                })
            return {
                "ok": True,
                "count": len(sct.monitors) - 1,  # physical monitors
                "monitors": monitors,
            }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def latest_actions(limit: int = 20) -> List[str]:
    if not LOG_FILE.exists():
        return []
    return LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]


def observe() -> Dict[str, Any]:
    vm = psutil.virtual_memory()
    return {
        "time": now(),
        "hostname": socket.gethostname(),
        "active_window": active_window_title(),
        "services": service_status(),
        "windows": get_windows(),
        "friday_processes": friday_processes(),
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=0.2),
            "ram_percent": vm.percent,
            "ram_used_gb": round(vm.used / 1024 / 1024 / 1024, 2),
            "ram_total_gb": round(vm.total / 1024 / 1024 / 1024, 2),
        },
        "recent_actions": latest_actions(),
    }


def ollama_models() -> List[str]:
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        r.raise_for_status()
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return []


def describe_with_vision(image_path: str, obs: Dict[str, Any]) -> str:
    use_vision = os.getenv("FRIDAY_USE_VISION", "0").strip() == "1"

    basic = (
        f"أشوف النافذة النشطة: {obs.get('active_window') or 'غير واضحة'}. "
        f"خدمات FRIDAY: "
        + ", ".join([f"{k}={'شغال' if v['up'] else 'متوقف'}" for k, v in obs.get("services", {}).items()])
        + f". استخدام الرام {obs.get('system', {}).get('ram_percent')}% والمعالج {obs.get('system', {}).get('cpu_percent')}%. "
        + f"تم حفظ لقطة الشاشة هنا: {image_path}"
    )

    # Fast mode: لا تنتظر موديل الرؤية إلا إذا فعلته صراحة
    if not use_vision:
        return basic

    models = ollama_models()
    has_vision = any(VISION_MODEL in m or m in VISION_MODEL for m in models)

    if not has_vision:
        return basic + " موديل الرؤية غير مثبت. ثبته بالأمر: ollama pull llava:latest"

    try:
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode("utf-8")
        prompt = """
أنت FRIDAY Jarvis. حلل صورة شاشة الكمبيوتر باختصار وبالعربية.
اذكر:
1) ما النافذة أو البرنامج الظاهر؟
2) هل يوجد خطأ أو تحذير واضح؟
3) ما الإجراء المقترح التالي؟
لا تذكر تفاصيل حساسة ولا كلمات مرور.
""".strip()

        payload = {
            "model": VISION_MODEL,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "options": {"temperature": 0.2, "num_ctx": 4096},
        }
        r = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=120)
        r.raise_for_status()
        answer = r.json().get("response", "").strip()
        return answer or basic
    except Exception as exc:
        return basic + f" تحليل الرؤية تعذر بسبب: {exc}"


def open_url(url: str) -> str:
    if not url.startswith("http://127.0.0.1:"):
        raise ValueError("Only localhost 127.0.0.1 URLs are allowed.")
    webbrowser.open(url)
    return f"تم فتح الرابط: {url}"


def open_app(name: str) -> str:
    key = name.lower().strip()
    if key not in APP_ALLOWLIST:
        raise ValueError(f"App not allowed: {name}")
    target = APP_ALLOWLIST[key]
    if target.endswith(".exe") and not Path(target).exists() and "\\" in target:
        # fallback to shell name if path unavailable
        if key == "mt5":
            raise FileNotFoundError("MT5 path not found. Update APP_ALLOWLIST['mt5'] in friday_jarvis_desktop_agent.py")
    subprocess.Popen(target, shell=True)
    return f"تم فتح: {name}"


def hotkey(name: str) -> str:
    import pyautogui

    mapping = {
        "copy": ["ctrl", "c"],
        "paste": ["ctrl", "v"],
        "select_all": ["ctrl", "a"],
        "alt_tab": ["alt", "tab"],
        "desktop": ["win", "d"],
        "enter": ["enter"],
        "esc": ["esc"],
    }
    if name not in mapping:
        raise ValueError(f"Hotkey not allowed: {name}")
    pyautogui.hotkey(*mapping[name])
    return f"تم تنفيذ الاختصار: {name}"


def action_execute(req: ActionRequest) -> Dict[str, Any]:
    action = req.action
    args = req.args or {}

    if action == "observe":
        return {"ok": True, "message": "هذه حالة النظام.", "data": observe()}

    if action == "service_status":
        return {"ok": True, "message": "هذه حالة خدمات FRIDAY.", "data": service_status()}

    if action == "screenshot":
        monitor_idx = int(args.get("monitor", 0))
        path = take_screenshot(monitor_index=monitor_idx)
        return {"ok": True, "message": f"تم أخذ لقطة شاشة: {path}", "path": path, "monitor": monitor_idx}

    if action == "screenshot_all":
        results = take_all_screenshots()
        paths = [r["path"] for r in results]
        return {"ok": True, "message": f"تم التقاط {len(results)} شاشة", "screenshots": results, "paths": paths}

    if action == "describe_screen":
        monitor_idx = int(args.get("monitor", 0))
        path = take_screenshot(monitor_index=monitor_idx)
        obs = observe()
        msg = describe_with_vision(path, obs)
        return {"ok": True, "message": msg, "path": path, "data": obs}

    if action == "describe_all_screens":
        obs = observe()
        results = take_all_screenshots()
        descriptions = []
        for item in results:
            msg = describe_with_vision(item["path"], obs)
            descriptions.append({"monitor": item["monitor"], "path": item["path"], "description": msg})
        combined_msg = " | ".join([f"شاشة {d['monitor']}: {d['description'][:120]}" for d in descriptions])
        return {"ok": True, "message": combined_msg, "monitors": descriptions}

    if action == "open_url":
        msg = open_url(str(args.get("url", "")))
        return {"ok": True, "message": msg}

    if action == "open_app":
        msg = open_app(str(args.get("name", "")))
        return {"ok": True, "message": msg}

    if action == "hotkey":
        msg = hotkey(str(args.get("name", "")))
        return {"ok": True, "message": msg}

    if action == "move_mouse":
        import pyautogui
        x = int(args["x"])
        y = int(args["y"])
        pyautogui.moveTo(x, y, duration=0.15)
        return {"ok": True, "message": f"حركت الماوس إلى {x},{y}"}

    if action == "click":
        import pyautogui
        x = int(args["x"])
        y = int(args["y"])
        pyautogui.click(x, y)
        return {"ok": True, "message": f"ضغطت على {x},{y}"}

    if action == "type_text":
        import pyautogui
        text = str(args.get("text", ""))
        if len(text) > 200 and req.confirm != "CONFIRM_TYPE":
            return {"ok": False, "requires_confirmation": True, "message": "النص طويل. قل CONFIRM_TYPE للتأكيد."}
        pyautogui.write(text, interval=0.01)
        return {"ok": True, "message": "كتبت النص."}

    if action == "close_window":
        if req.confirm != "CONFIRM_CLOSE_WINDOW":
            return {"ok": False, "requires_confirmation": True, "message": "إغلاق النافذة يحتاج تأكيد CONFIRM_CLOSE_WINDOW."}
        hotkey("alt_tab")
        time.sleep(0.2)
        import pyautogui
        pyautogui.hotkey("alt", "f4")
        return {"ok": True, "message": "تم إغلاق النافذة النشطة."}

    if action == "stop_friday":
        if req.confirm != "CONFIRM_STOP_FRIDAY":
            return {"ok": False, "requires_confirmation": True, "message": "إيقاف FRIDAY يحتاج تأكيد CONFIRM_STOP_FRIDAY."}
        stopped = []
        for p in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmd = " ".join(p.info.get("cmdline") or [])
                if any(s.lower() in cmd.lower() for s in FRIDAY_SCRIPTS):
                    p.kill()
                    stopped.append(p.info["pid"])
            except Exception:
                pass
        return {"ok": True, "message": f"تم إيقاف عمليات FRIDAY: {stopped}"}

    raise ValueError(f"Unknown action: {action}")


def _norm_ar(text: str) -> str:
    t = (text or "").strip().lower()
    repl = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ة": "ه",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
        "ـ": "",
    }
    for a, b in repl.items():
        t = t.replace(a, b)
    return t


def _has_any(t: str, words: list[str]) -> bool:
    return any(w in t for w in words)


def route_text(text: str) -> ActionRequest:
    t = _norm_ar(text)

    # Whisper often hears:
    # "وش تشوف" as "وشك شوف" / "وشو تشوفه" / "اشي جوف"
    wants_see = (
        _has_any(t, ["وش تشوف", "وشو تشوف", "وشك شوف", "اش تشوف", "ايش تشوف", "شوف", "تشوف", "جوف", "ستراني", "شتراني", "شوفني", "وريني"])
        or _has_any(t, ["describe screen", "what do you see"])
    )

    wants_screen = _has_any(t, ["الشاشه", "شاشه", "سكرين", "screen"])
    wants_chart = _has_any(t, ["الجارت", "الشارت", "تشارت", "chart", "dashboard", "داشبورد"])
    wants_mt5 = _has_any(t, ["mt5", "ميتا", "ميتاتريدر", "مدينه 5", "مدينة 5", "ميدينه 5"])

    wants_all_screens = _has_any(t, ["كل الشاشات", "جميع الشاشات", "الشاشتين", "الشاشات كلها", "all screens", "all monitors"])

    if wants_see:
        if wants_all_screens:
            return ActionRequest(action="describe_all_screens")
        return ActionRequest(action="describe_screen")

    if wants_all_screens and wants_screen:
        return ActionRequest(action="screenshot_all")

    if wants_chart:
        return ActionRequest(action="open_url", args={"url": SAFE_URLS["dashboard"]})

    if wants_mt5:
        return ActionRequest(action="open_app", args={"name": "mt5"})

    if any(x in t for x in ["لقطة شاشة", "سكرين شوت", "screenshot"]):
        return ActionRequest(action="screenshot")

    if any(x in t for x in ["حالة الستاك", "حالة الخدمات", "راقب الخدمات", "وش شغال", "stack status", "service status"]):
        return ActionRequest(action="observe")

    if any(x in t for x in ["افتح الداشبورد", "open dashboard"]):
        return ActionRequest(action="open_url", args={"url": SAFE_URLS["dashboard"]})

    if any(x in t for x in ["افتح الدماغ", "حالة الدماغ", "brain state", "open brain"]):
        return ActionRequest(action="open_url", args={"url": SAFE_URLS["brain"]})

    if any(x in t for x in ["افتح الشات", "open chat"]):
        return ActionRequest(action="open_url", args={"url": SAFE_URLS["chat"]})

    if any(x in t for x in ["افتح agents", "افتح ايجنت", "agents browser"]):
        return ActionRequest(action="open_url", args={"url": SAFE_URLS["agents"]})

    if any(x in t for x in ["افتح mt5", "افتح ميتاتريدر", "open mt5"]):
        return ActionRequest(action="open_app", args={"name": "mt5"})

    if any(x in t for x in ["افتح vscode", "افتح vs code", "افتح فيجوال", "open vscode", "open vs code"]):
        return ActionRequest(action="open_app", args={"name": "vscode"})

    if any(x in t for x in ["افتح المفكرة", "open notepad"]):
        return ActionRequest(action="open_app", args={"name": "notepad"})

    if any(x in t for x in ["اضغط انتر", "press enter"]):
        return ActionRequest(action="hotkey", args={"name": "enter"})

    if any(x in t for x in ["انسخ", "copy"]):
        return ActionRequest(action="hotkey", args={"name": "copy"})

    if any(x in t for x in ["الصق", "paste"]):
        return ActionRequest(action="hotkey", args={"name": "paste"})

    if any(x in t for x in ["حدد الكل", "select all"]):
        return ActionRequest(action="hotkey", args={"name": "select_all"})

    if any(x in t for x in ["سطح المكتب", "اظهر الديسكتوب", "show desktop"]):
        return ActionRequest(action="hotkey", args={"name": "desktop"})

    if any(x in t for x in ["بدل النافذة", "alt tab", "غير النافذة"]):
        return ActionRequest(action="hotkey", args={"name": "alt_tab"})

    return ActionRequest(action="none")



def semantic_route_text(text: str) -> ActionRequest:
    """
    LLM-based semantic router.
    No fixed Arabic command phrases.
    The model decides whether the user's text is a desktop-control request.
    """

    user_text = (text or "").strip()

    if not user_text:
        return ActionRequest(action="none")

    obs_summary = {
        "active_window": active_window_title(),
        "services": service_status(),
        "allowed_actions": [
            "none",
            "describe_screen",
            "describe_all_screens",
            "screenshot",
            "screenshot_all",
            "observe",
            "service_status",
            "open_url",
            "open_app",
            "hotkey",
            "move_mouse",
            "click",
            "type_text",
        ],
        "safe_urls": SAFE_URLS,
        "allowed_apps": list(APP_ALLOWLIST.keys()),
        "allowed_hotkeys": [
            "copy",
            "paste",
            "select_all",
            "alt_tab",
            "desktop",
            "enter",
            "esc",
        ],
    }

    system_prompt = """
You are FRIDAY Jarvis, a local desktop-control semantic router.

The user's text comes from Arabic speech recognition and may be wrong.
You must infer the intended meaning from noisy ASR.
Examples of ASR noise:
- words may be misspelled
- Arabic letters may be wrong
- chart/chat/جارت/جات/شارت may be confused
- افتح may appear as ابتح or ابطح
- MetaTrader / MT5 may appear in distorted Arabic

Your job:
Decide whether the user's message is asking to control or observe the computer.

Return ONLY valid JSON. No markdown. No explanation.

Allowed actions:
- none
- describe_screen        (describe the primary/current monitor)
- describe_all_screens   (describe ALL connected monitors)
- screenshot             (take screenshot of primary monitor)
- screenshot_all         (take screenshots of ALL monitors)
- observe
- service_status
- open_url
- open_app
- hotkey
- move_mouse
- click
- type_text

Rules:
0. First silently correct the likely ASR transcription mentally, then classify the user's intent.
1. If the user asks what you see, to look, to observe, to inspect the screen, to analyze the desktop, or talks as if you can see the computer, choose describe_screen. If they say "all screens", "both screens", "every monitor", or "كل الشاشات", choose describe_all_screens instead.
2. If the user asks to take a screenshot of all screens/monitors, choose screenshot_all. For a single screen, choose screenshot.
3. If the user asks to open a chart, dashboard, trading screen, or monitor, choose open_url with dashboard URL.
4. If the user asks for brain state, choose open_url with brain URL.
5. If the user asks for chat, choose open_url with chat URL.
6. If the user asks for agents browser, choose open_url with agents URL.
7. If the user asks to open MetaTrader, MT5, trading terminal, or anything that sounds like MetaTrader, choose open_app mt5.
8. If the user asks for service/stack/process status, choose observe or service_status.
9. If the message is normal conversation, choose none.
10. Do not invent unsupported actions.
11. Do not execute shell commands.
12. For unclear short utterances, infer intent from context if possible.

Output JSON schema:
{
  "handled": true/false,
  "action": "none|describe_screen|screenshot|observe|service_status|open_url|open_app|hotkey|move_mouse|click|type_text",
  "args": {},
  "confidence": 0.0-1.0,
  "reply": "short Arabic response"
}
""".strip()

    payload = {
        "model": TEXT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_text": user_text,
                        "desktop_context": obs_summary,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_ctx": 2048,
            "num_predict": 180,
        },
    }

    try:
        r = requests.post(OPENJARVIS_URL, json=payload, timeout=12)
        r.raise_for_status()

        content = r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        print(f"[JARVIS ROUTER RAW] {content[:500]}", flush=True)

        # Extract JSON even if model accidentally wraps text
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            content = content[start:end + 1]

        decision = json.loads(content)

        handled = bool(decision.get("handled", False))
        action = str(decision.get("action", "none")).strip()
        args = decision.get("args") or {}
        confidence = float(decision.get("confidence", 0.0) or 0.0)

        if not handled or action == "none" or confidence < 0.45:
            return ActionRequest(action="none")

        # Normalize safe URL aliases
        if action == "open_url":
            url = str(args.get("url", "")).strip()
            target = str(args.get("target", "")).strip().lower()

            if not url and target in SAFE_URLS:
                url = SAFE_URLS[target]

            # Semantic target rescue
            if not url:
                raw = user_text.lower()
                if "brain" in raw or "دماغ" in raw:
                    url = SAFE_URLS["brain"]
                elif "chat" in raw or "شات" in raw:
                    url = SAFE_URLS["chat"]
                elif "agent" in raw or "ايجنت" in raw:
                    url = SAFE_URLS["agents"]
                else:
                    url = SAFE_URLS["dashboard"]

            args = {"url": url}

        # Normalize apps
        if action == "open_app":
            name = str(args.get("name", "")).strip().lower()
            if name not in APP_ALLOWLIST:
                raw = user_text.lower()
                if "mt5" in raw or "meta" in raw or "ميتا" in raw or "تريدر" in raw:
                    name = "mt5"
                elif "code" in raw or "vscode" in raw or "فيجوال" in raw:
                    name = "vscode"
                else:
                    name = "notepad"
            args = {"name": name}

        # Normalize hotkeys
        if action == "hotkey":
            name = str(args.get("name", "")).strip().lower()
            allowed = {"copy", "paste", "select_all", "alt_tab", "desktop", "enter", "esc"}
            if name not in allowed:
                return ActionRequest(action="none")
            args = {"name": name}

        allowed_actions = {
            "describe_screen",
            "describe_all_screens",
            "screenshot",
            "screenshot_all",
            "observe",
            "service_status",
            "open_url",
            "open_app",
            "hotkey",
            "move_mouse",
            "click",
            "type_text",
        }

        if action not in allowed_actions:
            return ActionRequest(action="none")

        return ActionRequest(action=action, args=args)

    except Exception as exc:
        log_action("semantic_route_error", {"text": user_text}, str(exc), "semantic_router")
        return ActionRequest(action="none")


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "friday_jarvis_desktop_agent",
        "time": now(),
        "hostname": socket.gethostname(),
    }


@app.get("/observe")
def observe_endpoint():
    return observe()


@app.get("/windows")
def windows_endpoint():
    return get_windows()


@app.post("/screenshot")
def screenshot_endpoint(monitor: int = 0):
    """Take screenshot. monitor=0 captures all monitors combined; monitor=N captures specific monitor N."""
    path = take_screenshot(monitor_index=monitor)
    return {"ok": True, "path": path, "monitor": monitor}


@app.post("/screenshots/all")
def screenshots_all_endpoint():
    """Take individual screenshots of every connected monitor."""
    results = take_all_screenshots()
    return {"ok": True, "count": len(results), "screenshots": results}


@app.get("/monitors")
def monitors_endpoint():
    """Return geometry info for all connected monitors."""
    return monitor_info()


@app.post("/describe")
def describe_endpoint(monitor: int = 0):
    path = take_screenshot(monitor_index=monitor)
    obs = observe()
    msg = describe_with_vision(path, obs)
    return {"ok": True, "message": msg, "path": path, "data": obs}


@app.post("/describe/all")
def describe_all_endpoint():
    """Take screenshots of all monitors and describe each one."""
    obs = observe()
    results = take_all_screenshots()
    descriptions = []
    for item in results:
        msg = describe_with_vision(item["path"], obs)
        descriptions.append({
            "monitor": item["monitor"],
            "path": item["path"],
            "description": msg,
        })
    return {"ok": True, "count": len(descriptions), "monitors": descriptions}


@app.post("/action")
def action_endpoint(req: ActionRequest):
    try:
        result = action_execute(req)
        log_action(req.action, req.args, result, "action")
        return result
    except Exception as exc:
        result = {"ok": False, "message": str(exc)}
        log_action(req.action, req.args, result, "action_error")
        return result


@app.post("/command")
def command_endpoint(req: CommandRequest):
    ar = semantic_route_text(req.text)
    if ar.action == "none":
        return {"handled": False, "message": "ليس أمر جهاز واضح. سأتركه للمحادثة العادية."}
    result = action_execute(ar)
    log_action(ar.action, ar.args, result, "voice_command")
    result["handled"] = True
    result["action"] = ar.action
    return result


if __name__ == "__main__":
    import uvicorn
    print("[JARVIS] Desktop Agent starting on http://127.0.0.1:8855")
    uvicorn.run(app, host="127.0.0.1", port=8855, log_level="info")






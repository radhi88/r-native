"""voice_commands.py — J.27 — Hands-free voice commands.

Listens for spoken commands via SpeechRecognition library and routes them
through R Native's existing actions. Optional — only activates if speech_recognition
is installed.

Commands (English):
  "deploy the top one [on BTC]"
  "run a campaign on BTC M5"
  "what's R doing now"
  "show today's stats"
  "kill everything"
  "what's the gate"

Settings: data/r_native/voice_commands.json
{
  "enabled":      false,
  "wake_word":    "hey R" | "R native" | null (always-listen)
  "language":     "en-US",
  "speak_replies": true     // use voice_alerts to speak responses
}

Heavy deps (speech_recognition + pyaudio) are optional — module no-ops if
they're missing.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

CONFIG_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\voice_commands.json")

DEFAULTS = {
    "enabled":       False,
    "wake_word":     "hey R",
    "language":      "en-US",
    "speak_replies": True,
    "energy_threshold": 4000,
}

_stop = threading.Event()
_thread: threading.Thread | None = None


def load() -> dict:
    if not CONFIG_PATH.exists(): return DEFAULTS.copy()
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = DEFAULTS.copy(); cfg.update(loaded); return cfg
    except Exception:
        return DEFAULTS.copy()


def save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


# ── Command parser ────────────────────────────────────────────────────
def _parse(text: str) -> dict:
    """Map spoken text → structured action. Returns {action, args} or {action: 'unknown'}."""
    if not text: return {"action": "noop"}
    t = text.lower().strip()

    # DEPLOY: "deploy the top one [on X]"
    m = re.search(r"deploy.+top.+?(?:on\s+)?([a-z]{3,8})?", t)
    if m:
        symbol = (m.group(1) or "BTC").upper()
        if not symbol.endswith("M"): symbol += "USDM"
        return {"action": "deploy_top", "args": {"symbol": symbol}}

    # CAMPAIGN: "run a campaign on X [tf]"
    m = re.search(r"campaign.+?(?:on\s+)?([a-z]{3,8})\s*(m\d+|h\d+)?", t)
    if m:
        symbol = m.group(1).upper()
        if not symbol.endswith("M"): symbol += "USDM"
        tf = (m.group(2) or "M5").upper()
        return {"action": "run_campaign", "args": {"symbol": symbol, "tf": tf}}

    # STATS: "what's R doing" / "show today's stats" / "stats"
    if "doing" in t or "stats" in t or "performance" in t:
        return {"action": "show_stats"}

    # KILL: "kill" / "stop" / "freeze"
    if "kill" in t or "stop everything" in t or "emergency" in t:
        return {"action": "kill_all"}

    # GATE: "what's the gate" / "gate status"
    if "gate" in t:
        return {"action": "gate_status"}

    return {"action": "unknown", "heard": text}


def _execute(parsed: dict) -> str:
    """Run an action. Returns a string to speak back."""
    a = parsed.get("action")
    args = parsed.get("args", {})

    if a == "deploy_top":
        symbol = args.get("symbol", "BTCUSDm")
        try:
            cfg_path = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs") / f"{symbol}.json"
            if not cfg_path.exists():
                return f"No vault for {symbol}"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            top = (cfg.get("ga_strategies") or [None])[0]
            if not top: return "Vault is empty"
            from r_native.actions import deploy_genome_to_live
            r = deploy_genome_to_live(symbol, top["id"], top.get("timeframe", "M5"))
            return f"Deployed {top['id']} on {symbol}"
        except Exception as e:
            return f"Deploy failed: {e}"

    if a == "run_campaign":
        symbol = args.get("symbol", "BTCUSDm")
        tf     = args.get("tf", "M5")
        try:
            from r_native.web_launcher import start
            # Simulated POST
            import urllib.request, json as _j
            data = _j.dumps({"symbol": symbol, "tf": tf, "pg": 200, "gens": 3}).encode()
            req = urllib.request.Request("http://127.0.0.1:5055/r/campaign/start",
                                          data=data,
                                          headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).read()
            return f"Campaign started on {symbol} {tf}"
        except Exception as e:
            return f"Could not start campaign: {e}"

    if a == "show_stats":
        try:
            s = json.loads(Path(
                r"C:\Users\Radhi\MT5\friday_v3\data\r_executor_state.json"
            ).read_text(encoding="utf-8"))
            return (f"Today P L is {s.get('today_pl', 0):+.2f} dollars, "
                    f"{s.get('today_trades', 0)} trades")
        except Exception:
            return "Executor state unavailable"

    if a == "kill_all":
        Path(r"C:\Users\Radhi\MT5\kill_switch.txt").write_text(
            "killed via voice command", encoding="utf-8")
        return "Killed. All trading stopped."

    if a == "gate_status":
        try:
            import urllib.request
            with urllib.request.urlopen(
                "http://127.0.0.1:5055/api/r/trade_gate?symbol=BTCUSDm",
                timeout=3) as r:
                d = json.loads(r.read().decode())
            return f"Gate verdict is {d.get('verdict', 'unknown')}"
        except Exception:
            return "Gate unavailable"

    if a == "unknown":
        return f"Sorry, I didn't catch that"

    return ""


def _listener_loop():
    """Background loop — listen → parse → execute → speak reply."""
    try:
        import speech_recognition as sr
    except ImportError:
        print("[voice_cmd] speech_recognition not installed — voice commands disabled")
        return

    cfg = load()
    rec = sr.Recognizer()
    rec.energy_threshold = cfg.get("energy_threshold", 4000)
    rec.dynamic_energy_threshold = True
    wake = (cfg.get("wake_word") or "").lower()

    try:
        mic = sr.Microphone()
    except Exception as e:
        print(f"[voice_cmd] no mic: {e}")
        return

    with mic as source:
        rec.adjust_for_ambient_noise(source, duration=1)
        print("[voice_cmd] listening...")

    while not _stop.is_set():
        try:
            with mic as source:
                audio = rec.listen(source, timeout=3, phrase_time_limit=5)
        except Exception:
            continue   # timeout or mic glitch
        try:
            text = rec.recognize_google(audio, language=cfg.get("language", "en-US"))
            print(f"[voice_cmd] heard: {text}")
        except Exception:
            continue

        # Wake word gating
        if wake and wake not in text.lower():
            continue
        # Strip wake word
        clean = re.sub(wake, "", text, count=1, flags=re.IGNORECASE).strip()

        parsed = _parse(clean)
        reply  = _execute(parsed)
        print(f"[voice_cmd] reply: {reply}")
        if cfg.get("speak_replies") and reply:
            try:
                from r_native.voice_alerts import speak
                speak(reply)
            except Exception: pass


def start_listener():
    global _thread
    if _thread and _thread.is_alive(): return
    cfg = load()
    if not cfg.get("enabled"):
        print("[voice_cmd] disabled in config")
        return
    _stop.clear()
    _thread = threading.Thread(target=_listener_loop, daemon=True,
                                name="voice-commands")
    _thread.start()


def stop_listener():
    _stop.set()


if __name__ == "__main__":
    print(json.dumps(load(), indent=2))
    print("To test: enable in config, then call start_listener()")

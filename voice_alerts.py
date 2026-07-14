"""voice_alerts.py — J.12 — Ambient TTS alerts via pyttsx3.

Speaks critical events out loud while user works on other things:
- Trade opened
- Trade closed (with P/L)
- Daily cap hit / frozen

Lazy-loads pyttsx3 (optional dep). Silent no-op if not installed.

Settings: data/r_native/voice_alerts.json
{
  "enabled": false,
  "rate": 175,          // words per minute
  "volume": 0.8,        // 0.0-1.0
  "voice_index": 0,     // which installed voice to use
  "events": {
    "trade_open":   true,
    "trade_close":  true,
    "freeze":       true,
    "daily_cap":    true,
    "deploy":       false
  }
}
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

CONFIG_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\voice_alerts.json")

DEFAULTS = {
    "enabled":     False,
    "rate":        175,
    "volume":      0.8,
    "voice_index": 0,
    "events": {
        "trade_open":  True,
        "trade_close": True,
        "freeze":      True,
        "daily_cap":   True,
        "deploy":      False,
    },
}

_engine = None
_engine_lock = threading.Lock()


def load() -> dict:
    if not CONFIG_PATH.exists(): return DEFAULTS.copy()
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = DEFAULTS.copy(); cfg.update(loaded)
        # Deep-merge events
        cfg["events"] = {**DEFAULTS["events"], **(loaded.get("events") or {})}
        return cfg
    except Exception:
        return DEFAULTS.copy()


def save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def _get_engine():
    """Lazy-init pyttsx3 engine. Returns None if pyttsx3 not installed."""
    global _engine
    if _engine is not None: return _engine
    try:
        import pyttsx3
        e = pyttsx3.init()
        cfg = load()
        e.setProperty("rate",   cfg["rate"])
        e.setProperty("volume", cfg["volume"])
        voices = e.getProperty("voices") or []
        vi = max(0, min(cfg.get("voice_index", 0), len(voices) - 1))
        if voices: e.setProperty("voice", voices[vi].id)
        _engine = e
        return _engine
    except ImportError:
        print("[voice] pyttsx3 not installed — voice alerts disabled")
        return None
    except Exception as e:
        print(f"[voice] init err: {e}")
        return None


def _speak_sync(text: str):
    eng = _get_engine()
    if not eng: return
    with _engine_lock:
        try:
            eng.say(text)
            eng.runAndWait()
        except Exception as e:
            print(f"[voice] speak err: {e}")


def speak(text: str, event: str = None):
    """Speak `text` async. Optional `event` key gates against config."""
    cfg = load()
    if not cfg.get("enabled"): return
    if event and not cfg.get("events", {}).get(event, True): return
    threading.Thread(target=_speak_sync, args=(text,), daemon=True).start()


# ── Pre-canned phrases ────────────────────────────────────────────────
def trade_open(side: str, symbol: str, price: float):
    speak(f"{side} {symbol} at {price:.0f}", event="trade_open")


def trade_close(symbol: str, pl: float, reason: str = ""):
    if pl > 0:
        speak(f"Profit {symbol} plus {pl:.2f} dollars {reason}", event="trade_close")
    elif pl < 0:
        speak(f"Loss {symbol} minus {abs(pl):.2f} dollars {reason}", event="trade_close")
    else:
        speak(f"Breakeven {symbol}", event="trade_close")


def daily_cap_hit(amount: float):
    speak(f"Daily loss cap hit at minus {amount:.0f} dollars. Trading frozen.",
          event="daily_cap")


def freeze(reason: str):
    speak(f"Executor frozen. Reason: {reason}", event="freeze")


def deployed(genome_id: str, symbol: str):
    speak(f"Deployed {genome_id} on {symbol}", event="deploy")


def list_voices() -> list:
    """Return list of installed voices on this machine."""
    try:
        import pyttsx3
        e = pyttsx3.init()
        return [(i, v.name, v.id) for i, v in enumerate(e.getProperty("voices") or [])]
    except Exception:
        return []

"""retro_sfx.py — 8-bit beep sound effects for trade events.

Inspired by user's easy-peasy.ai retro trading game.
Generates pure synth tones — no audio files needed. Uses winsound on Windows
(no external deps) or skips silently on other OSes.

Sounds:
  trade_open       — ascending arpeggio (3 notes, 80ms each)
  trade_win        — major chord cascade (4 notes, 100ms)
  trade_loss       — descending minor (3 notes, 120ms)
  margin_call      — 4 quick rising beeps
  diamond_hands    — luxurious major 7 chord (5 notes)
  game_over        — descending dirge (5 notes)
  level_up         — Mario-style chime
  cash_register    — "ka-ching" double beep

Settings: data/r_native/retro_sfx.json
{
  "enabled":     true,
  "volume":      0.7,
  "events": {
    "trade_open":   true,
    "trade_win":    true,
    "trade_loss":   true,
    "margin_call":  true
  }
}
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

CONFIG_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\retro_sfx.json")

DEFAULTS = {
    "enabled": True,
    "volume":  0.7,
    "events": {
        "trade_open":     True,
        "trade_win":      True,
        "trade_loss":     True,
        "margin_call":    True,
        "diamond_hands":  True,
        "level_up":       True,
        "cash_register":  False,
        "game_over":      True,
    },
}


def load() -> dict:
    if not CONFIG_PATH.exists(): return DEFAULTS.copy()
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = DEFAULTS.copy(); cfg.update(loaded)
        cfg["events"] = {**DEFAULTS["events"], **(loaded.get("events") or {})}
        return cfg
    except Exception:
        return DEFAULTS.copy()


def save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


# ── Backend: Windows winsound (no deps) ─────────────────────────────
def _beep_winsound(freq: int, ms: int):
    try:
        import winsound
        winsound.Beep(max(37, min(32767, int(freq))), max(1, int(ms)))
    except Exception: pass


# ── Backend: simpleaudio (cross-platform, if installed) ─────────────
def _beep_simpleaudio(freq: int, ms: int, volume: float = 0.7):
    try:
        import simpleaudio as sa
        import numpy as np
        sample_rate = 22050
        n_samples = int(sample_rate * ms / 1000)
        t = np.linspace(0, ms/1000, n_samples, False)
        # 8-bit square wave for retro feel
        wave = np.where(np.sin(freq * 2 * np.pi * t) > 0, 1.0, -1.0)
        # Envelope (fade in/out to avoid clicks)
        fade = int(sample_rate * 0.005)
        if n_samples > fade * 2:
            wave[:fade]  *= np.linspace(0, 1, fade)
            wave[-fade:] *= np.linspace(1, 0, fade)
        audio = (wave * volume * 32767).astype(np.int16)
        sa.play_buffer(audio, 1, 2, sample_rate)
    except Exception: pass


def _beep(freq: int, ms: int, volume: float = 0.7):
    """Pick best available backend."""
    if sys.platform == "win32":
        _beep_winsound(freq, ms)
    else:
        _beep_simpleaudio(freq, ms, volume)


# ── Sound effects (note sequences) ───────────────────────────────────
def _play_sequence(notes: list[tuple[int, int]], volume: float):
    """Play sequence of (freq, ms) tuples synchronously."""
    for f, ms in notes:
        _beep(f, ms, volume)


def _play_async(event: str, notes: list[tuple[int, int]]):
    """Fire-and-forget audio. Respects per-event toggles."""
    cfg = load()
    if not cfg.get("enabled"): return
    if not cfg.get("events", {}).get(event, True): return
    threading.Thread(target=_play_sequence,
                     args=(notes, cfg.get("volume", 0.7)),
                     daemon=True).start()


# ── Pre-canned sounds ─────────────────────────────────────────────────
def trade_open():
    """Ascending arpeggio — C5 → E5 → G5."""
    _play_async("trade_open", [(523, 80), (659, 80), (784, 80)])


def trade_win():
    """Major triumph cascade — C5 → E5 → G5 → C6."""
    _play_async("trade_win", [(523, 100), (659, 100), (784, 100), (1047, 200)])


def trade_loss():
    """Descending minor — E5 → C5 → A4."""
    _play_async("trade_loss", [(659, 120), (523, 120), (440, 200)])


def margin_call():
    """4 quick rising beeps — warning klaxon."""
    _play_async("margin_call", [(880, 60), (988, 60), (1109, 60), (1244, 100)])


def diamond_hands():
    """Luxurious chord — C maj7."""
    _play_async("diamond_hands",
                [(523, 80), (659, 80), (784, 80), (988, 80), (1047, 200)])


def game_over():
    """Descending dirge — F5 → D5 → B4 → G4 → E4."""
    _play_async("game_over",
                [(698, 200), (587, 200), (494, 200), (392, 200), (330, 400)])


def level_up():
    """Mario-ish chime."""
    _play_async("level_up", [(523, 60), (659, 60), (784, 60), (1047, 120)])


def cash_register():
    """Quick ka-ching — high beep + low beep."""
    _play_async("cash_register", [(1568, 80), (784, 80)])


# ── Smart event dispatcher ────────────────────────────────────────────
def on_trade_event(event: str, pl: float = 0):
    """Auto-pick sound from event name + P/L magnitude."""
    if event == "OPEN":              trade_open()
    elif event == "CLOSE":
        if pl > 5:                   diamond_hands()
        elif pl > 0:                 trade_win()
        elif pl < -5:                game_over()
        else:                        trade_loss()
    elif event == "MARGIN_CALL":     margin_call()
    elif event == "LEVEL_UP":        level_up()


# ── Smoke test ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import time
    print("Testing all sounds (3s gap):")
    for name in ("trade_open", "trade_win", "trade_loss", "margin_call",
                 "diamond_hands", "level_up", "cash_register", "game_over"):
        print(f"  → {name}")
        globals()[name]()
        time.sleep(1.5)
    print("done")

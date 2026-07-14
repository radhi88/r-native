from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import requests


_env_root = os.getenv("FRIDAY_PROJECT_ROOT")
ROOT = Path(_env_root).resolve() if _env_root else Path(__file__).resolve().parents[3]
AGENT_URL = os.getenv("FRIDAY_DESKTOP_AGENT_URL", "http://127.0.0.1:8855")
FFPLAY = os.getenv("FRIDAY_FFPLAY_PATH", "")
VOICE_NAME = os.getenv("FRIDAY_TTS_VOICE", "ar-SA-HamedNeural")


def _is_bad_transcript(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True

    words = t.split()

    if len(t) <= 2:
        return True

    # Whisper hallucination / echo loops
    if len(words) > 35:
        unique_ratio = len(set(words)) / max(len(words), 1)
        if unique_ratio < 0.40:
            return True

    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1

    if counts and max(counts.values()) >= 6:
        return True

    bad_fragments = [
        "لتفعه لتفعه",
        "لتفع لتفع",
        "في المدرسه في المدرسه",
        "في المدرسة في المدرسة",
        "في المنطقه المنطقه",
        "في المنطقة المنطقة",
        "ونقوم بشكل مخصيات",
    ]

    if any(x in t for x in bad_fragments):
        return True

    return False


async def _speak_async(text: str) -> None:
    try:
        import edge_tts

        out_dir = ROOT / "runtime" / "tts"
        out_dir.mkdir(parents=True, exist_ok=True)
        mp3 = out_dir / "jarvis_prebrain_reply.mp3"

        communicate = edge_tts.Communicate(text=text, voice=VOICE_NAME)
        await communicate.save(str(mp3))

        if FFPLAY and Path(FFPLAY).exists():
            subprocess.Popen(
                [FFPLAY, "-nodisp", "-autoexit", "-loglevel", "quiet", str(mp3)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            print(f"[JARVIS SPEAK] {text}", flush=True)

    except Exception as exc:
        print(f"[JARVIS SPEAK ERROR] {exc}", flush=True)
        print(f"[JARVIS] {text}", flush=True)


def _speak(text: str) -> None:
    try:
        asyncio.run(_speak_async(text))
    except RuntimeError:
        # In case there is already an event loop
        loop = asyncio.get_event_loop()
        loop.create_task(_speak_async(text))


def jarvis_prebrain_handle(text: str) -> bool:
    """
    Returns True if Jarvis handled the transcript and the normal Brain must be skipped.
    Returns False if this is normal chat and should continue to Brain.

    No fixed command keywords here.
    Decision is delegated to Desktop Agent -> OpenJarvis Semantic Router.
    """

    if os.getenv("FRIDAY_PREBRAIN_ENABLED", "1").strip().lower() not in {"1", "true", "yes", "on"}:
        return False

    clean = (text or "").strip()

    if _is_bad_transcript(clean):
        print(f"[JARVIS PREBRAIN] ignored bad transcript: {clean[:160]}", flush=True)
        return True

    try:
        print(f"[JARVIS PREBRAIN] semantic check: {clean}", flush=True)

        r = requests.post(
            f"{AGENT_URL}/command",
            json={"text": clean},
            timeout=45,
        )

        data = r.json()

        if not data.get("handled"):
            print("[JARVIS PREBRAIN] normal chat, continue to Brain", flush=True)
            return False

        action = data.get("action", "")
        msg = data.get("message", "تم تنفيذ الأمر.")

        print(f"[JARVIS PREBRAIN] handled action={action} message={msg}", flush=True)

        if msg:
            _speak(str(msg)[:900])

        return True

    except Exception as exc:
        print(f"[JARVIS PREBRAIN ERROR] {exc}", flush=True)
        return False

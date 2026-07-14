from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time
from pathlib import Path

import requests

ROOT = Path(r"C:\Users\Radhi\MT5")
PY = ROOT / ".venv" / "Scripts" / "python.exe"
VOICE = ROOT / "scripts" / "run_friday_voice.py"
AGENT = ROOT / "scripts" / "friday_jarvis_desktop_agent.py"

AGENT_URL = os.getenv("FRIDAY_DESKTOP_AGENT_URL", "http://127.0.0.1:8855")
FFPLAY = os.getenv("FRIDAY_FFPLAY_PATH", "")
VOICE_NAME = os.getenv("FRIDAY_TTS_VOICE", "ar-SA-HamedNeural")

FINAL_RE = re.compile(r"\[TRANSCRIBED\]\s+final:\s*(.+)", re.IGNORECASE)


def wait_agent(timeout: int = 20) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{AGENT_URL}/health", timeout=1)
            if r.ok:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def start_agent():
    if wait_agent(timeout=2):
        print("[JARVIS] Desktop Agent already running.", flush=True)
        return None

    print("[JARVIS] Starting Desktop Agent...", flush=True)

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    p = subprocess.Popen(
        [str(PY), str(AGENT)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    if wait_agent(timeout=20):
        print("[JARVIS] Desktop Agent ready.", flush=True)
    else:
        print("[JARVIS] WARNING: Desktop Agent did not become ready.", flush=True)

    return p


async def speak_async(text: str):
    try:
        import edge_tts

        out_dir = ROOT / "runtime" / "tts"
        out_dir.mkdir(parents=True, exist_ok=True)
        mp3 = out_dir / "jarvis_reply.mp3"

        communicate = edge_tts.Communicate(text=text, voice=VOICE_NAME)
        await communicate.save(str(mp3))

        if FFPLAY and Path(FFPLAY).exists():
            subprocess.Popen(
                [FFPLAY, "-nodisp", "-autoexit", "-loglevel", "quiet", str(mp3)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            print("[JARVIS SPEAK]", text, flush=True)

    except Exception as exc:
        print(f"[JARVIS SPEAK ERROR] {exc}", flush=True)
        print("[JARVIS]", text, flush=True)


def speak(text: str):
    asyncio.run(speak_async(text))



def is_bad_transcript(text: str) -> bool:
    """
    Filters Whisper hallucinations / echo loops before they reach Jarvis.
    Examples:
    - repeated same phrase
    - very long low-quality repeated words
    - obvious noise loops
    """
    t = (text or "").strip()
    if not t:
        return True

    words = t.split()

    # too short and not meaningful
    if len(t) <= 2:
        return True

    # too long from one short speech segment = likely hallucination
    if len(words) > 35:
        unique_ratio = len(set(words)) / max(len(words), 1)
        if unique_ratio < 0.35:
            return True

    # repeated same word too much
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    if counts and max(counts.values()) >= 6:
        return True

    # repeated phrase patterns
    if len(words) >= 12:
        first_half = " ".join(words[:6])
        if t.count(first_half) >= 2:
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

def ask_semantic_router(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False

    if is_bad_transcript(clean):
        print(f"[JARVIS] ignored bad transcript: {clean[:120]}", flush=True)
        return True

    print(f"[JARVIS] semantic check: {clean}", flush=True)

    try:
        r = requests.post(
            f"{AGENT_URL}/command",
            json={"text": clean},
            timeout=60,
        )

        data = r.json()

        if not data.get("handled"):
            print("[JARVIS] semantic result: normal chat, not desktop command", flush=True)
            return False

        msg = data.get("message", "تم تنفيذ الأمر.")
        action = data.get("action", "")

        print(f"[JARVIS] semantic action={action} message={msg}", flush=True)

        if msg:
            speak(str(msg)[:900])

        return True

    except Exception as exc:
        print(f"[JARVIS ERROR] semantic router failed: {exc}", flush=True)
        return False


def main():
    os.chdir(ROOT)

    agent_proc = start_agent()

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["FRIDAY_DESKTOP_AGENT_URL"] = AGENT_URL
    env.setdefault("FRIDAY_PREBRAIN_ENABLED", "1")
    bridge_route_finals = os.getenv("FRIDAY_BRIDGE_ROUTE_FINALS", "0").strip().lower() in {"1", "true", "yes", "on"}

    print("[JARVIS] Starting FRIDAY original realtime voice...", flush=True)

    voice_proc = subprocess.Popen(
        [str(PY), str(VOICE)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    stdout = voice_proc.stdout
    if stdout is None:
        raise RuntimeError("Voice process stdout was not captured.")

    try:
        for line in stdout:
            print(line, end="", flush=True)

            m = FINAL_RE.search(line)
            if bridge_route_finals and m:
                final_text = m.group(1).strip()
                ask_semantic_router(final_text)

    except KeyboardInterrupt:
        print("\n[JARVIS] Stopping...", flush=True)

    finally:
        try:
            voice_proc.terminate()
        except Exception:
            pass

        if agent_proc:
            try:
                agent_proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()


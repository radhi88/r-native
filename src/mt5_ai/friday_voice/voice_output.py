from __future__ import annotations

import asyncio
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .config import FridayVoiceConfig, log_event


@dataclass(slots=True)
class SpeechRequest:
    text: str
    interrupt_previous: bool = False


class StreamingUtteranceBuffer:
    """Buffer tokens until a natural sentence boundary, then flush for TTS.

    min_chars=50 gives faster first-word latency compared to the old 70.
    The buffer flushes on: sentence-ending punctuation after min_chars,
    or hard flush after min_chars*2 (prevents long pauses).
    """

    def __init__(self, min_chars: int = 50):
        self.min_chars = min_chars
        self.buffer = ""

    def offer(self, token: str) -> str | None:
        self.buffer += token
        stripped = self.buffer.strip()
        if not stripped:
            return None

        if len(stripped) >= self.min_chars and any(stripped.endswith(p) for p in [".", "?", "!", "؟", "،", ","]):
            self.buffer = ""
            return stripped

        if len(stripped) >= self.min_chars * 2:
            self.buffer = ""
            return stripped

        return None

    def finish(self) -> str | None:
        text = self.buffer.strip()
        self.buffer = ""
        return text or None


class VoiceOutput:
    def __init__(self, config: FridayVoiceConfig):
        self.config = config
        self.queue: queue.Queue[SpeechRequest | None] = queue.Queue()
        self.interrupt_event = threading.Event()
        self.running = False
        self.thread: threading.Thread | None = None
        self._pyttsx3_engine = None
        self._player_proc: subprocess.Popen | None = None
        self._last_playback_started_at: float = 0.0
        self._last_playback_ended_at: float = 0.0
        self._speaking = False
        self._last_error = ""

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._worker, name="friday-tts", daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.running = False
        self.stop_current()
        self.queue.put(None)

    def speak_async(self, text: str, interrupt_previous: bool = False) -> None:
        text = str(text or "").strip()
        if not text:
            return
        if interrupt_previous:
            self.stop_current()
        self.queue.put(SpeechRequest(text=text, interrupt_previous=interrupt_previous))
        log_event("TTS", "queued speech", {"queue_size": self.queue.qsize(), "chars": len(text)})

    def stop_current(self) -> None:
        self.interrupt_event.set()
        cleared = 0
        while True:
            try:
                self.queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        if self._player_proc is not None and self._player_proc.poll() is None:
            self._player_proc.terminate()
        if self._pyttsx3_engine is not None:
            try:
                self._pyttsx3_engine.stop()
            except Exception:
                pass
        self._speaking = False
        log_event("TTS", "stop_current", {"cleared_queue_items": cleared})

    def is_speaking(self) -> bool:
        return self._speaking

    def playback_started_within(self, seconds: float) -> bool:
        return self._last_playback_started_at > 0 and (time.time() - self._last_playback_started_at) < seconds

    def _worker(self) -> None:
        while self.running:
            item = self.queue.get()
            if item is None:
                break
            self.interrupt_event.clear()
            log_event("TTS", item.text[:120], {"engine": self.config.tts_engine, "queue_size": self.queue.qsize()})
            try:
                if self.config.tts_engine.lower() == "edge-tts":
                    if not self._speak_edge(item.text):
                        log_event("TTS", "edge-tts unavailable; falling back to pyttsx3")
                        self._speak_pyttsx3(item.text)
                else:
                    self._speak_pyttsx3(item.text)
            except Exception as exc:
                self._last_error = str(exc)
                log_event("ERROR", f"tts failed: {exc}")

    def _speak_edge(self, text: str) -> bool:
        ffplay = self.config.tts_ffplay_path
        if shutil.which(ffplay) is None and not Path(ffplay).exists():
            return False
        try:
            import edge_tts
        except Exception:
            return False

        fd, path = tempfile.mkstemp(prefix="friday_tts_", suffix=".mp3")
        os.close(fd)

        async def synthesize() -> None:
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.config.tts_voice,
                rate=self.config.tts_rate,
                volume=self.config.tts_volume,
            )
            await communicate.save(path)

        try:
            attempts = max(1, int(self.config.edge_tts_retries or 1))
            for attempt in range(1, attempts + 1):
                try:
                    log_event("TTS", "edge-tts synthesize", {"attempt": attempt, "max_attempts": attempts})
                    asyncio.run(synthesize())
                    break
                except Exception as exc:
                    self._last_error = str(exc)
                    log_event("ERROR", f"edge-tts synth failed: {exc}", {"attempt": attempt, "max_attempts": attempts})
                    if attempt >= attempts:
                        return False
                    time.sleep(0.25 * attempt)
            if self.interrupt_event.is_set():
                return True
            self._last_playback_started_at = time.time()
            self._speaking = True
            log_event("TTS", "playback_started", {"engine": "edge-tts"})
            self._player_proc = subprocess.Popen(
                [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            while self._player_proc.poll() is None:
                if self.interrupt_event.is_set():
                    self._player_proc.terminate()
                    log_event("TTS", "playback_interrupted", {"engine": "edge-tts"})
                    break
                threading.Event().wait(0.03)
            self._speaking = False
            self._last_playback_ended_at = time.time()
            log_event("TTS", "playback_finished", {"engine": "edge-tts"})
            return True
        finally:
            self._speaking = False
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass

    def _speak_pyttsx3(self, text: str) -> None:
        try:
            import pyttsx3
        except Exception:
            return

        if self._pyttsx3_engine is None:
            self._pyttsx3_engine = pyttsx3.init()
            self._pyttsx3_engine.setProperty("rate", 178)

        if self.interrupt_event.is_set():
            return
        self._last_playback_started_at = time.time()
        self._speaking = True
        log_event("TTS", "playback_started", {"engine": "pyttsx3"})
        self._pyttsx3_engine.say(text)
        try:
            self._pyttsx3_engine.runAndWait()
        finally:
            self._speaking = False
            self._last_playback_ended_at = time.time()
            log_event("TTS", "playback_finished", {"engine": "pyttsx3"})

import base64
import os
import queue
import re
import subprocess
import threading


class LocalSpeaker:
    """Offline Windows speech output using the built-in SAPI voice."""

    def __init__(self, enabled=True, rate=None, volume=None):
        self.enabled = bool(enabled)
        self.rate = int(rate if rate is not None else os.environ.get("FRIDAY_TTS_RATE", "-1"))
        self.volume = int(volume if volume is not None else os.environ.get("FRIDAY_TTS_VOLUME", "100"))
        self._queue = queue.Queue(maxsize=20)
        self._thread = None
        self._lock = threading.Lock()

    def status(self):
        return {
            "available": os.name == "nt",
            "enabled": self.enabled,
            "engine": "windows_sapi",
            "rate": self.rate,
            "volume": self.volume,
        }

    def speak(self, text):
        if not self.enabled or os.name != "nt":
            return {"spoken": False, "reason": "speaker_disabled_or_unavailable"}
        clean = self._clean(text)
        if not clean:
            return {"spoken": False, "reason": "empty_text"}
        try:
            self._queue.put_nowait(clean)
        except queue.Full:
            return {"spoken": False, "reason": "speaker_queue_full"}
        self._ensure_thread()
        return {"spoken": True}

    def stop(self):
        self.enabled = False
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _ensure_thread(self):
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()

    def _run(self):
        while self.enabled:
            try:
                text = self._queue.get(timeout=1)
            except queue.Empty:
                return
            self._sapi_speak(text)

    def _sapi_speak(self, text):
        script = f"""
$voice = New-Object -ComObject SAPI.SpVoice
$voice.Rate = {self.rate}
$voice.Volume = {self.volume}
[void]$voice.Speak(@'
{text}
'@)
""".strip()
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = subprocess.CREATE_NO_WINDOW
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
            timeout=60,
        )

    @staticmethod
    def _clean(text):
        text = re.sub(r"\s+", " ", text or "").strip()
        text = text.replace("'@", "' @")
        return text[:700]

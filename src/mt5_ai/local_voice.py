import importlib.util
import json
import os
import queue
import threading


DEFAULT_WAKE_WORDS = ["friday", "فرايدي", "جارفيس", "jarvis"]


class LocalVoiceService:
    """Offline wake-word and command listener scaffold.

    Uses Vosk + sounddevice when installed. Until dependencies/model are
    present, it reports unavailable instead of falling back to browser/cloud
    speech APIs.
    """

    def __init__(self, event_bus=None, command_callback=None, wake_words=None):
        self.event_bus = event_bus
        self.command_callback = command_callback
        self.wake_words = [word.lower() for word in (wake_words or DEFAULT_WAKE_WORDS)]
        self.model_path = os.environ.get("VOSK_MODEL_PATH", "")
        self.sample_rate = int(os.environ.get("FRIDAY_VOICE_SAMPLE_RATE", "16000"))
        self.running = False
        self.awake = False
        self._thread = None
        self._audio_queue = None

    def dependency_status(self):
        return {
            "vosk": importlib.util.find_spec("vosk") is not None,
            "sounddevice": importlib.util.find_spec("sounddevice") is not None,
            "model_path": self.model_path,
            "model_exists": bool(self.model_path and os.path.isdir(self.model_path)),
        }

    def status(self):
        deps = self.dependency_status()
        available = deps["vosk"] and deps["sounddevice"] and deps["model_exists"]
        return {
            "available": available,
            "running": self.running,
            "awake": self.awake,
            "wake_words": self.wake_words,
            "dependencies": deps,
            "mode": "offline_vosk",
        }

    def start(self):
        status = self.status()
        if not status["available"]:
            self._event("voice_unavailable", status)
            return {
                "started": False,
                "reason": "missing_offline_voice_dependency_or_model",
                "status": status,
            }

        if self.running:
            return {"started": True, "reason": "already_running", "status": status}

        self.running = True
        self._audio_queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._event("voice_started", self.status())
        return {"started": True, "status": self.status()}

    def stop(self):
        self.running = False
        self.awake = False
        self._event("voice_stopped", self.status())
        return {"stopped": True, "status": self.status()}

    def _event(self, event_type, payload=None):
        if self.event_bus is not None:
            self.event_bus.publish(event_type, payload or {})

    def _run(self):
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model

        model = Model(self.model_path)
        recognizer = KaldiRecognizer(model, self.sample_rate)

        def callback(indata, frames, time_info, status):
            if status:
                self._event("voice_warning", {"status": str(status)})
            self._audio_queue.put(bytes(indata))

        try:
            with sd.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=8000,
                dtype="int16",
                channels=1,
                callback=callback,
            ):
                while self.running:
                    data = self._audio_queue.get()
                    if recognizer.AcceptWaveform(data):
                        result = json.loads(recognizer.Result() or "{}")
                        text = (result.get("text") or "").strip()
                        if text:
                            self._handle_text(text)
        except Exception as exc:
            self.running = False
            self._event("voice_error", {"error": str(exc)})

    def _handle_text(self, text):
        lowered = text.lower()
        self._event("voice_text", {"text": text, "awake": self.awake})

        wake_hit = next((word for word in self.wake_words if word in lowered), None)
        if wake_hit:
            self.awake = True
            command = lowered.replace(wake_hit, "", 1).strip(" ,،")
            self._event("wake_word", {"word": wake_hit, "command": command})
            if command:
                self._dispatch_command(command)
            return

        if self.awake and lowered:
            self.awake = False
            self._dispatch_command(text)

    def _dispatch_command(self, command):
        self._event("voice_command", {"command": command})
        if self.command_callback is None:
            return
        try:
            response = self.command_callback(command)
            self._event("voice_answer", response)
        except Exception as exc:
            self._event("voice_error", {"error": str(exc)})

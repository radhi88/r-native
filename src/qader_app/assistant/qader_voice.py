"""Voice input/output boundary for Qader."""
from __future__ import annotations

import threading
from typing import Callable

from qader_app.assistant.intent_router import IntentRouter
from qader_app.assistant.permissions_guard import PermissionsGuard
from qader_app.storage.audit_log import log_action


class QaderVoice:
    """Minimal voice adapter with local fallback.

    This intentionally avoids computer-control actions from the old Mark-XXXIX
    project. Voice is limited to speech I/O and command text routing.
    """

    def __init__(self, guard: PermissionsGuard | None = None):
        self.guard = guard or PermissionsGuard()
        self.router = IntentRouter()
        self._speaking_engine = None
        self._recognizer = None
        self._microphone_cls = None
        self.listening = False

    def status(self) -> dict:
        return {
            "speaker_ready": self._speaking_engine is not None,
            "microphone_ready": self._recognizer is not None and self._microphone_cls is not None,
            "listening": self.listening,
        }

    def init_speaker(self) -> bool:
        perm = self.guard.check("can_use_speaker", "init_speaker", "qader_voice")
        if not perm.allowed:
            return False
        if self._speaking_engine is not None:
            return True
        try:
            import pyttsx3

            self._speaking_engine = pyttsx3.init()
            self._speaking_engine.setProperty("rate", 175)
            return True
        except Exception as exc:
            log_action("speaker_init_failed", "can_use_speaker", False, str(exc), "qader_voice")
            return False

    def speak(self, text: str) -> dict:
        if not self.init_speaker():
            return {"spoken": False, "reason": "speaker_not_available_or_permission_denied"}
        text = str(text or "").strip()
        if not text:
            return {"spoken": False, "reason": "empty_text"}

        def worker() -> None:
            try:
                self._speaking_engine.say(text)
                self._speaking_engine.runAndWait()
                log_action("speak", "can_use_speaker", True, "spoken", "qader_voice", result=text[:120])
            except Exception as exc:
                log_action("speak_failed", "can_use_speaker", False, str(exc), "qader_voice")

        threading.Thread(target=worker, daemon=True).start()
        return {"spoken": True}

    def init_microphone(self) -> bool:
        perm = self.guard.check("can_use_microphone", "init_microphone", "qader_voice")
        if not perm.allowed:
            return False
        if self._recognizer and self._microphone_cls:
            return True
        try:
            import speech_recognition as sr

            self._recognizer = sr.Recognizer()
            self._recognizer.dynamic_energy_threshold = True
            self._microphone_cls = sr.Microphone
            return True
        except Exception as exc:
            log_action("microphone_init_failed", "can_use_microphone", False, str(exc), "qader_voice")
            return False

    def listen_once(self, timeout: float = 5.0, phrase_time_limit: float = 8.0) -> dict:
        if not self.init_microphone():
            return {"ok": False, "text": "", "reason": "microphone_not_available_or_permission_denied"}
        try:
            with self._microphone_cls() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.3)
                audio = self._recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            try:
                text = self._recognizer.recognize_google(audio, language="ar-SA")
            except Exception:
                text = self._recognizer.recognize_google(audio, language="en-US")
            intent = self.router.route(text)
            log_action("listen_once", "can_use_microphone", True, "transcribed", "qader_voice", result={"text": text, "intent": intent.name})
            return {"ok": True, "text": text, "intent": intent.name}
        except Exception as exc:
            log_action("listen_failed", "can_use_microphone", False, str(exc), "qader_voice")
            return {"ok": False, "text": "", "reason": str(exc)}

    def toggle_listening(self, callback: Callable[[str], None] | None = None) -> dict:
        self.listening = not self.listening
        log_action("toggle_listening", "can_use_microphone", self.listening, "toggle", "qader_voice")
        if self.listening and callback:
            result = self.listen_once()
            if result.get("ok"):
                callback(result["text"])
        return {"listening": self.listening}

    def command_requires_confirmation(self, text: str) -> bool:
        return self.router.route(text).requires_confirmation


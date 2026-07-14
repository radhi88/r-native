"""
FRIDAY Voice Runtime — Jarvis-style local AI assistant for MT5 workstation.

Pipeline:
    Mic → VAD → Whisper STT → jarvis_prebrain (device commands)
         → OllamaBrain (LLM) → StreamingTTS (edge-tts)

Usage:
    python scripts/run_friday_voice.py                 # full voice mode
    python scripts/run_friday_voice.py --text-loop     # keyboard mode
    python scripts/run_friday_voice.py --text "hello"  # single query
    python scripts/run_friday_voice.py --install-check # dependency check
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import queue
import threading
import time
from typing import Iterable

from .brain import OllamaBrain
from .command_router import CommandRouter
from .config import FridayVoiceConfig, load_config, log_event
from .gateway_client import GatewayClient
from .health_monitor import HealthMonitor
from .jarvis_prebrain import jarvis_prebrain_handle
from .memory import FridayMemory
from .mt5_tools import MT5Tools
from .voice_input import AudioEvent, MicrophoneStream, TranscriptionWorker
from .voice_output import StreamingUtteranceBuffer, VoiceOutput


# ─────────────────────────────────────────────────────────────────────────────
# Runtime
# ─────────────────────────────────────────────────────────────────────────────

class FridayRuntime:
    """Main FRIDAY runtime — coordinates all subsystems."""

    def __init__(self, config: FridayVoiceConfig):
        self.config = config
        self.memory = FridayMemory(config)
        self.mt5_tools = MT5Tools(config)
        self.router = CommandRouter(self.mt5_tools, self.memory)
        self.brain = OllamaBrain(config, self.memory)
        self.voice = VoiceOutput(config)
        self.gateway_client: GatewayClient = GatewayClient()
        self.health_monitor: HealthMonitor | None = None
        self.audio_events: queue.Queue[AudioEvent] = queue.Queue()
        self.transcript_events: queue.Queue[AudioEvent] = queue.Queue()
        self.mic: MicrophoneStream | None = None
        self.transcriber: TranscriptionWorker | None = None
        self.stop_event = threading.Event()
        self.generation_interrupt = threading.Event()
        self.generation_thread: threading.Thread | None = None
        self._ignore_current_speech = False

    # ── dependency check ──────────────────────────────────────────────────────

    def install_check(self) -> dict[str, bool]:
        packages = [
            "sounddevice", "faster_whisper", "edge_tts",
            "pyttsx3", "webrtcvad", "MetaTrader5",
        ]
        return {name: importlib.util.find_spec(name) is not None for name in packages}

    # ── start / stop ──────────────────────────────────────────────────────────

    def start_voice_stack(self) -> None:
        if self.mic is None:
            self.mic = MicrophoneStream(self.config, self.audio_events)
        if self.transcriber is None:
            self.transcriber = TranscriptionWorker(
                self.config, self.audio_events, self.transcript_events
            )
        self.voice.start()
        self.transcriber.start()
        self.mic.start()
        if self.config.llm_warmup_on_start:
            threading.Thread(
                target=self.brain.warmup,
                name="friday-llm-warmup",
                daemon=True,
            ).start()
        # D-10: start the self-healing monitor AFTER voice.start() so it can speak
        self.health_monitor = HealthMonitor(
            self.config, self.voice, self.gateway_client, self.mt5_tools
        )
        self.health_monitor.start()

    def close(self) -> None:
        self.stop_event.set()
        self.generation_interrupt.set()
        # D-11: stop the monitor before voice.close() so in-flight announcements drain
        if self.health_monitor is not None:
            self.health_monitor.stop()
        if self.mic is not None:
            self.mic.stop()
        if self.transcriber is not None:
            self.transcriber.stop()
        self.voice.close()
        self.mt5_tools.shutdown()

    # ── single-shot text query ────────────────────────────────────────────────

    def handle_text(self, text: str, voice: bool = True) -> str:
        # Pre-brain: handle device commands without wasting LLM tokens
        if jarvis_prebrain_handle(text):
            answer = "[handled by jarvis_prebrain]"
            self.memory.remember_turn(text, answer, category="PREBRAIN")
            log_event("BRAIN", "prebrain handled text command", {"text": text[:200]})
            return answer

        command = self.router.route(text)
        # D-08: bypass brain entirely for direct_response (gateway errors, confirmations)
        if command.direct_response is not None and not command.tool_context:
            if voice:
                self.voice.speak_async(command.direct_response)
            self.memory.remember_turn(text, command.direct_response, category=command.category)
            return command.direct_response
        interrupt = threading.Event()
        tokens: list[str] = []
        buffer = StreamingUtteranceBuffer()

        log_event("BRAIN", f"prompt category={command.category}")
        for token in self.brain.stream_response(command, interrupt=interrupt):
            tokens.append(token)
            print(token, end="", flush=True)
            if voice and self.config.speak_while_generating:
                chunk = buffer.offer(token)
                if chunk:
                    self.voice.speak_async(chunk)

        final_chunk = buffer.finish()
        if voice and final_chunk:
            self.voice.speak_async(final_chunk)

        print("", flush=True)
        answer = "".join(tokens).strip()
        self.memory.remember_turn(text, answer, category=command.category)
        return answer

    # ── background generation (voice loop) ───────────────────────────────────

    def _generate_background(self, text: str) -> None:
        # Pre-brain: handle device commands without LLM
        if jarvis_prebrain_handle(text):
            self.memory.remember_turn(text, "[handled by jarvis_prebrain]", category="PREBRAIN")
            log_event("BRAIN", "prebrain handled voice command", {"text": text[:200]})
            return

        command = self.router.route(text)
        # D-08: bypass brain entirely for direct_response (gateway errors, confirmations)
        if command.direct_response is not None and not command.tool_context:
            self.voice.speak_async(command.direct_response)
            self.memory.remember_turn(text, command.direct_response, category=command.category)
            return
        tokens: list[str] = []
        buffer = StreamingUtteranceBuffer()
        self.generation_interrupt.clear()

        log_event("BRAIN", f"stream start category={command.category}")
        for token in self.brain.stream_response(command, interrupt=self.generation_interrupt):
            if self.generation_interrupt.is_set():
                break
            tokens.append(token)
            print(token, end="", flush=True)
            if self.config.speak_while_generating:
                chunk = buffer.offer(token)
                if chunk:
                    self.voice.speak_async(chunk)

        if not self.generation_interrupt.is_set():
            chunk = buffer.finish()
            if chunk:
                self.voice.speak_async(chunk)
            answer = "".join(tokens).strip()
            self.memory.remember_turn(text, answer, category=command.category)
            print("", flush=True)

    def interrupt_assistant(self) -> None:
        if not self.config.interrupt_on_speech:
            log_event("TTS", "speech interrupt ignored by config")
            return
        self.generation_interrupt.set()
        self.voice.stop_current()
        log_event("TTS", "interrupted by user speech")

    # ── main voice loop ───────────────────────────────────────────────────────

    def run_voice(self) -> None:
        self.start_voice_stack()
        log_event("LISTENING", "FRIDAY realtime voice loop started — always listening")
        _print_banner(self.config)

        while not self.stop_event.is_set():
            try:
                event = self.transcript_events.get(timeout=0.2)
            except queue.Empty:
                continue

            if event.type == "speech_start":
                tts_guard_seconds = self.config.tts_barge_in_ms / 1000
                if self.voice.is_speaking() or self.voice.playback_started_within(tts_guard_seconds):
                    self._ignore_current_speech = True
                    log_event("LISTENING", "speech_start ignored during TTS guard")
                    continue
                self._ignore_current_speech = False
                self.interrupt_assistant()
                continue

            if event.type == "error":
                log_event("ERROR", event.text)
                continue

            if event.type != "transcript" or not event.text:
                continue

            if self._ignore_current_speech:
                if not event.is_partial:
                    self._ignore_current_speech = False
                log_event("TRANSCRIBED", f"ignored during TTS guard: {event.text[:80]}")
                continue

            if event.is_partial:
                log_event("TRANSCRIBED", f"partial: {event.text[:80]}")
                continue

            text = event.text.strip()
            if not text:
                continue

            # Wake-word filter (optional — leave empty for always-on)
            if self.config.wake_word:
                lowered = text.lower()
                wake = self.config.wake_word.lower()
                if wake not in lowered:
                    continue
                text = lowered.replace(wake, "", 1).strip(" ,.:;")
                if not text:
                    self.voice.speak_async("نعم.")
                    continue

            log_event("TRANSCRIBED", f"final: {text}")

            # Interrupt any running generation before starting new one
            if self.generation_thread is not None and self.generation_thread.is_alive():
                self.interrupt_assistant()
                self.generation_thread.join(timeout=0.5)

            self.generation_thread = threading.Thread(
                target=self._generate_background,
                args=(text,),
                name="friday-brain",
                daemon=True,
            )
            self.generation_thread.start()

    # ── keyboard fallback loop ────────────────────────────────────────────────

    def run_text_loop(self) -> None:
        self.voice.start()
        log_event("LISTENING", "text mode started — type your query")
        _print_banner(self.config)
        try:
            while True:
                text = input("FRIDAY> ").strip()
                if text.lower() in {"exit", "quit", "خروج", "وقف"}:
                    break
                if text:
                    self.handle_text(text, voice=False)
        finally:
            self.close()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _print_banner(config: FridayVoiceConfig) -> None:
    print(flush=True)
    print("╔══════════════════════════════════════════════════╗", flush=True)
    print("║          F R I D A Y  —  JARVIS MODE             ║", flush=True)
    print("╠══════════════════════════════════════════════════╣", flush=True)
    print(f"║  Model   : {config.ollama_model:<38}║", flush=True)
    print(f"║  Whisper : {config.whisper_model:<38}║", flush=True)
    print(f"║  TTS     : {config.tts_engine:<38}║", flush=True)
    print(f"║  Voice   : {config.tts_voice:<38}║", flush=True)
    print(f"║  Symbol  : {config.default_symbol:<38}║", flush=True)
    print(f"║  VAD     : {config.vad_backend:<38}║", flush=True)
    wake = config.wake_word or "(always on)"
    print(f"║  Wake    : {wake:<38}║", flush=True)
    print("╚══════════════════════════════════════════════════╝", flush=True)
    print(flush=True)


def run_text_once(config: FridayVoiceConfig, text: str, speak: bool = False) -> str:
    runtime = FridayRuntime(config)
    try:
        if speak:
            runtime.voice.start()
        return runtime.handle_text(text, voice=speak)
    finally:
        runtime.close()


# ─────────────────────────────────────────────────────────────────────────────
# Entry-point
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="FRIDAY — local Jarvis-style voice assistant for MT5"
    )
    parser.add_argument("--text", help="Run a single text query (no microphone).")
    parser.add_argument("--text-loop", action="store_true", help="Keyboard chat loop.")
    parser.add_argument("--speak", action="store_true", help="Speak response in text mode.")
    parser.add_argument("--no-listen", action="store_true", help="Skip microphone.")
    parser.add_argument("--show-config", action="store_true", help="Print config as JSON.")
    parser.add_argument("--install-check", action="store_true", help="Check required packages.")
    parser.add_argument("--symbol", help="Override default MT5 symbol.")
    parser.add_argument("--timeframe", help="Override default timeframe.")
    parser.add_argument("--ollama-model", help="Override Ollama model.")
    parser.add_argument("--whisper-model", help="Override Whisper model size.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    config = load_config()
    if args.symbol:
        config.default_symbol = args.symbol
    if args.timeframe:
        config.default_timeframe = args.timeframe
    if args.ollama_model:
        config.ollama_model = args.ollama_model
    if args.whisper_model:
        config.whisper_model = args.whisper_model

    if args.show_config:
        print(json.dumps(config.as_dict(), ensure_ascii=False, indent=2))
        return 0

    runtime = FridayRuntime(config)

    if args.install_check:
        result = runtime.install_check()
        print(json.dumps(result, indent=2))
        missing = [k for k, v in result.items() if not v]
        if missing:
            print(f"\n[WARNING] Missing packages: {', '.join(missing)}")
            print("Run:  pip install -r requirements-voice.txt")
        runtime.close()
        return 0

    if args.text:
        runtime.close()
        run_text_once(config, args.text, speak=args.speak)
        return 0

    if args.text_loop or args.no_listen:
        runtime.run_text_loop()
        return 0

    try:
        runtime.run_voice()
    except KeyboardInterrupt:
        log_event("LISTENING", "keyboard interrupt — shutting down FRIDAY")
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

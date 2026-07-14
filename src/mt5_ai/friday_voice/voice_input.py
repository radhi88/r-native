from __future__ import annotations

import queue
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .config import FridayVoiceConfig, log_event


@dataclass(slots=True)
class AudioEvent:
    type: str
    audio: np.ndarray | None = None
    text: str = ""
    is_partial: bool = False
    timestamp: float = 0.0
    duration_seconds: float = 0.0
    meta: dict[str, Any] | None = None


class WebRtcOrEnergyVAD:
    def __init__(self, config: FridayVoiceConfig):
        self.config = config
        self.backend = "energy"
        self._vad = None
        requested = (config.vad_backend or "webrtcvad").strip().lower()
        if requested in {"off", "disabled", "none"}:
            self.backend = "disabled"
        elif requested == "energy":
            self.backend = "energy"
        else:
            try:
                import webrtcvad

                mode = max(0, min(3, int(round((1.0 - config.vad_sensitivity) * 3))))
                self._vad = webrtcvad.Vad(mode)
                self.backend = "webrtcvad"
            except Exception:
                self._vad = None
                self.backend = "energy"

        # Allow an explicit override via config; otherwise derive from sensitivity.
        # Higher sensitivity → lower threshold (catches softer speech).
        if config.vad_energy_threshold > 0.0:
            self.energy_threshold = config.vad_energy_threshold
        else:
            sens = min(max(config.vad_sensitivity, 0.05), 0.95)
            self.energy_threshold = max(0.003, 0.02 * (1.0 - sens))
        log_event("LISTENING", f"VAD backend={self.backend} energy_threshold={self.energy_threshold:.4f}")

    def is_speech(self, audio: np.ndarray) -> bool:
        if audio.size == 0:
            return False
        if self.backend == "disabled":
            return True
        if self._vad is None:
            return float(np.sqrt(np.mean(np.square(audio)))) >= self.energy_threshold

        frame_ms = 30
        frame_len = int(self.config.sample_rate * frame_ms / 1000)
        if len(audio) < frame_len:
            return False
        pcm = np.clip(audio, -1.0, 1.0)
        pcm16 = (pcm * 32767.0).astype(np.int16)

        speech = 0
        frames = 0
        for start in range(0, len(pcm16) - frame_len + 1, frame_len):
            chunk = pcm16[start : start + frame_len].tobytes()
            try:
                if self._vad.is_speech(chunk, self.config.sample_rate):
                    speech += 1
                frames += 1
            except Exception:
                return float(np.sqrt(np.mean(np.square(audio)))) >= self.energy_threshold
        return frames > 0 and speech / frames >= 0.34


class MicrophoneStream:
    def __init__(self, config: FridayVoiceConfig, audio_events: queue.Queue[AudioEvent]):
        self.config = config
        self.audio_events = audio_events
        self.running = False
        self.thread: threading.Thread | None = None
        self.vad = WebRtcOrEnergyVAD(config)

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, name="friday-mic", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False

    def _run(self) -> None:
        try:
            import sounddevice as sd
        except Exception as exc:
            self.audio_events.put(AudioEvent(type="error", text=f"sounddevice unavailable: {exc}", timestamp=time.time()))
            return

        chunk_frames = max(160, int(self.config.sample_rate * self.config.audio_chunk_ms / 1000))
        raw_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=80)

        def callback(indata, frames, time_info, status):
            if status:
                log_event("LISTENING", f"audio status: {status}")
            try:
                raw_queue.put_nowait(np.asarray(indata[:, 0], dtype=np.float32).copy())
            except queue.Full:
                log_event("LISTENING", "audio queue drop", {"queue_max": raw_queue.maxsize})
                pass

        device = self.config.audio_device
        log_event("LISTENING", f"microphone stream sr={self.config.sample_rate} chunk_ms={self.config.audio_chunk_ms}")

        with sd.InputStream(
            samplerate=self.config.sample_rate,
            blocksize=chunk_frames,
            channels=1,
            dtype="float32",
            device=device,
            callback=callback,
        ):
            self._process_chunks(raw_queue)

    def _process_chunks(self, raw_queue: queue.Queue[np.ndarray]) -> None:
        in_speech = False
        frames: list[np.ndarray] = []
        candidate_frames: list[np.ndarray] = []
        candidate_started_at = 0.0
        speech_started_at = 0.0
        last_voice_at = 0.0
        last_partial_at = 0.0
        min_speech_sec = self.config.min_speech_ms / 1000.0
        speech_start_confirm = self.config.speech_start_confirm_ms / 1000.0
        silence_timeout = self.config.silence_timeout_ms / 1000.0

        while self.running:
            try:
                chunk = raw_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            now = time.time()
            speech = self.vad.is_speech(chunk)

            if not in_speech:
                if speech:
                    if not candidate_frames:
                        candidate_started_at = now
                    candidate_frames.append(chunk)
                    if (now - candidate_started_at) < speech_start_confirm:
                        continue

                    in_speech = True
                    frames = list(candidate_frames)
                    candidate_frames = []
                    speech_started_at = candidate_started_at
                    last_voice_at = now
                    last_partial_at = now
                    self.audio_events.put(AudioEvent(type="speech_start", timestamp=now))
                    log_event("LISTENING", "speech_start", {"vad_backend": self.vad.backend})
                else:
                    candidate_frames = []
                    continue

            if in_speech:
                if not frames or frames[-1] is not chunk:
                    frames.append(chunk)
                if speech:
                    last_voice_at = now

                duration = now - speech_started_at
                if (
                    self.config.partial_transcripts
                    and duration >= 0.8
                    and (now - last_partial_at) * 1000 >= self.config.partial_interval_ms
                ):
                    last_partial_at = now
                    self.audio_events.put(
                        AudioEvent(
                            type="partial_audio",
                            audio=np.concatenate(frames).astype(np.float32),
                            is_partial=True,
                            timestamp=now,
                            duration_seconds=duration,
                        )
                    )

                if (now - last_voice_at) >= silence_timeout or duration >= self.config.max_record_seconds:
                    audio = np.concatenate(frames).astype(np.float32) if frames else np.array([], dtype=np.float32)
                    if duration >= min_speech_sec and audio.size:
                        self.audio_events.put(
                            AudioEvent(
                                type="speech_end",
                                audio=audio,
                                timestamp=now,
                                duration_seconds=duration,
                            )
                        )
                        log_event("LISTENING", f"speech_end duration={duration:.2f}s", {"duration_seconds": round(duration, 3)})
                    in_speech = False
                    frames = []


class FasterWhisperTranscriber:
    def __init__(self, config: FridayVoiceConfig):
        self.config = config
        self._model = None
        self._device = "cpu"
        self._compute_type = "int8"

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            raise RuntimeError(f"faster-whisper is not installed: {exc}") from exc

        device = self.config.whisper_device
        if device == "auto":
            device = "cpu"
            try:
                import importlib

                torch = importlib.import_module("torch")

                if torch.cuda.is_available():
                    device = "cuda"
            except Exception:
                pass

        compute_type = self.config.whisper_compute_type
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        self._device = device
        self._compute_type = compute_type
        log_event("TRANSCRIBED", f"loading faster-whisper model={self.config.whisper_model} device={device} compute={compute_type}")
        log_event(
            "TRANSCRIBED",
            "whisper runtime selected",
            {"model": self.config.whisper_model, "device": device, "compute_type": compute_type},
        )
        self._model = WhisperModel(self.config.whisper_model, device=device, compute_type=compute_type)
        return self._model

    def transcribe(self, audio: np.ndarray) -> str:
        model = self._load()
        language = None if self.config.whisper_language.lower() == "auto" else self.config.whisper_language
        segments, _info = model.transcribe(
            audio,
            language=language,
            beam_size=1,
            best_of=1,
            temperature=0.0,
            vad_filter=bool(self.config.whisper_vad_filter),
            condition_on_previous_text=False,
            word_timestamps=False,
        )
        return " ".join(seg.text.strip() for seg in segments if seg.text).strip()


class WhisperCppTranscriber:
    def __init__(self, config: FridayVoiceConfig):
        self.config = config

    def transcribe(self, audio: np.ndarray) -> str:
        exe = self.config.whisper_cpp_exe
        model = self.config.whisper_cpp_model
        if not exe or not model:
            raise RuntimeError("whisper.cpp fallback is not configured")

        with tempfile.NamedTemporaryFile(prefix="friday_audio_", suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)

        try:
            pcm = np.clip(audio, -1.0, 1.0)
            pcm16 = (pcm * 32767.0).astype(np.int16)
            with wave.open(str(wav_path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(self.config.sample_rate)
                handle.writeframes(pcm16.tobytes())

            cmd = [exe, "-m", model, "-f", str(wav_path), "-nt", "-np"]
            language = self.config.whisper_language
            if language and language.lower() != "auto":
                cmd.extend(["-l", language])
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr[-1000:])
            return (proc.stdout or "").strip()
        finally:
            wav_path.unlink(missing_ok=True)


class TranscriptionWorker:
    def __init__(
        self,
        config: FridayVoiceConfig,
        audio_events: queue.Queue[AudioEvent],
        transcript_events: queue.Queue[AudioEvent],
    ):
        self.config = config
        self.audio_events = audio_events
        self.transcript_events = transcript_events
        self.running = False
        self.thread: threading.Thread | None = None
        self.faster = FasterWhisperTranscriber(config)
        self.cpp = WhisperCppTranscriber(config)
        self._last_partial = ""

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, name="friday-stt", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False

    def _run(self) -> None:
        while self.running:
            try:
                event = self.audio_events.get(timeout=0.2)
            except queue.Empty:
                continue

            if event.type in {"speech_start", "error"}:
                self.transcript_events.put(event)
                continue

            if event.type not in {"speech_end", "partial_audio"} or event.audio is None:
                continue

            try:
                started = time.time()
                text = self._transcribe(event.audio)
                latency = time.time() - started
                if not text:
                    continue
                if event.is_partial:
                    if text == self._last_partial:
                        continue
                    self._last_partial = text
                else:
                    self._last_partial = ""
                log_event(
                    "TRANSCRIBED",
                    ("partial: " if event.is_partial else "final: ") + text,
                    {"latency_seconds": round(latency, 3), "audio_duration_seconds": round(event.duration_seconds, 3)},
                )
                self.transcript_events.put(
                    AudioEvent(
                        type="transcript",
                        text=text,
                        is_partial=event.is_partial,
                        timestamp=time.time(),
                        duration_seconds=event.duration_seconds,
                    )
                )
            except Exception as exc:
                log_event("ERROR", f"transcription failed: {exc}")
                self.transcript_events.put(AudioEvent(type="error", text=str(exc), timestamp=time.time()))

    def _transcribe(self, audio: np.ndarray) -> str:
        try:
            return self.faster.transcribe(audio)
        except Exception as first:
            if self.config.whisper_cpp_exe and self.config.whisper_cpp_model:
                log_event("TRANSCRIBED", f"faster-whisper failed, trying whisper.cpp: {first}")
                return self.cpp.transcribe(audio)
            raise

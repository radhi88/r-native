from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
MEMORY_DIR = DATA_DIR / "memory"
LOG_DIR = PROJECT_ROOT / "logs" / "friday_voice"
RUNTIME_DIR = PROJECT_ROOT / "runtime"
STATUS_JSONL = LOG_DIR / "friday_voice_status.jsonl"
STATUS_LATEST = RUNTIME_DIR / "friday_voice_status.json"

for directory in (MEMORY_DIR, LOG_DIR, RUNTIME_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class FridayVoiceConfig:
    project_name: str = field(default_factory=lambda: os.environ.get("FRIDAY_PROJECT_NAME", "FRIDAY"))

    # LLM
    ollama_host: str = field(default_factory=lambda: os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: os.environ.get("FRIDAY_OLLAMA_MODEL", "qwen2.5:3b-instruct"))
    llm_temperature: float = field(default_factory=lambda: _env_float("FRIDAY_LLM_TEMPERATURE", 0.25))
    llm_num_ctx: int = field(default_factory=lambda: _env_int("FRIDAY_LLM_NUM_CTX", 4096))
    max_response_tokens: int = field(default_factory=lambda: _env_int("FRIDAY_MAX_RESPONSE_TOKENS", 180))
    llm_timeout_seconds: float = field(default_factory=lambda: _env_float("FRIDAY_LLM_TIMEOUT_SECONDS", 45.0))
    llm_warmup_on_start: bool = field(default_factory=lambda: _env_flag("FRIDAY_LLM_WARMUP_ON_START", True))

    # Speech recognition
    whisper_model: str = field(default_factory=lambda: os.environ.get("FRIDAY_WHISPER_MODEL", "base"))
    whisper_language: str = field(default_factory=lambda: os.environ.get("FRIDAY_WHISPER_LANGUAGE", "auto"))
    whisper_device: str = field(default_factory=lambda: os.environ.get("FRIDAY_WHISPER_DEVICE", "auto"))
    whisper_compute_type: str = field(default_factory=lambda: os.environ.get("FRIDAY_WHISPER_COMPUTE_TYPE", "auto"))
    whisper_cpp_exe: str = field(default_factory=lambda: os.environ.get("FRIDAY_WHISPER_CPP_EXE", ""))
    whisper_cpp_model: str = field(default_factory=lambda: os.environ.get("FRIDAY_WHISPER_CPP_MODEL", ""))
    whisper_vad_filter: bool = field(default_factory=lambda: _env_flag("FRIDAY_WHISPER_VAD_FILTER", True))
    partial_transcripts: bool = field(default_factory=lambda: _env_flag("FRIDAY_PARTIAL_TRANSCRIPTS", True))
    partial_interval_ms: int = field(default_factory=lambda: _env_int("FRIDAY_PARTIAL_INTERVAL_MS", 1200))

    # Audio / VAD
    audio_device: str | None = field(default_factory=lambda: os.environ.get("FRIDAY_AUDIO_DEVICE") or None)
    sample_rate: int = field(default_factory=lambda: _env_int("FRIDAY_SAMPLE_RATE", 16000))
    audio_chunk_ms: int = field(default_factory=lambda: _env_int("FRIDAY_AUDIO_CHUNK_MS", 30))
    vad_backend: str = field(default_factory=lambda: os.environ.get("FRIDAY_VAD_BACKEND", "webrtcvad"))
    vad_sensitivity: float = field(default_factory=lambda: _env_float("FRIDAY_VAD_SENSITIVITY", 0.62))
    vad_energy_threshold: float = field(default_factory=lambda: _env_float("FRIDAY_VAD_ENERGY_THRESHOLD", 0.0))
    silence_timeout_ms: int = field(default_factory=lambda: _env_int("FRIDAY_SILENCE_TIMEOUT_MS", 900))
    max_record_seconds: float = field(default_factory=lambda: _env_float("FRIDAY_MAX_RECORD_SECONDS", 30.0))
    min_speech_ms: int = field(default_factory=lambda: _env_int("FRIDAY_MIN_SPEECH_MS", 250))
    speech_start_confirm_ms: int = field(default_factory=lambda: _env_int("FRIDAY_SPEECH_START_CONFIRM_MS", 120))
    tts_barge_in_ms: int = field(default_factory=lambda: _env_int("FRIDAY_TTS_BARGE_IN_MS", 2000))

    # TTS
    tts_engine: str = field(default_factory=lambda: os.environ.get("FRIDAY_TTS_ENGINE", "edge-tts"))
    tts_voice: str = field(default_factory=lambda: os.environ.get("FRIDAY_TTS_VOICE", "ar-SA-HamedNeural"))
    tts_rate: str = field(default_factory=lambda: os.environ.get("FRIDAY_TTS_RATE", "+0%"))
    tts_volume: str = field(default_factory=lambda: os.environ.get("FRIDAY_TTS_VOLUME", "+0%"))
    tts_ffplay_path: str = field(default_factory=lambda: os.environ.get("FRIDAY_FFPLAY_PATH", "ffplay"))
    edge_tts_retries: int = field(default_factory=lambda: _env_int("FRIDAY_EDGE_TTS_RETRIES", 2))
    speak_while_generating: bool = field(default_factory=lambda: _env_flag("FRIDAY_SPEAK_WHILE_GENERATING", True))

    # MT5 defaults
    default_symbol: str = field(default_factory=lambda: os.environ.get("FRIDAY_DEFAULT_SYMBOL", "XAUUSDm"))
    default_timeframe: str = field(default_factory=lambda: os.environ.get("FRIDAY_DEFAULT_TIMEFRAME", "M1"))
    mt5_readonly: bool = field(default_factory=lambda: _env_flag("FRIDAY_MT5_READONLY", True))

    # Runtime
    streaming_enabled: bool = field(default_factory=lambda: _env_flag("FRIDAY_STREAMING_ENABLED", True))
    voice_mode: bool = field(default_factory=lambda: _env_flag("FRIDAY_VOICE_MODE", True))
    memory_enabled: bool = field(default_factory=lambda: _env_flag("FRIDAY_MEMORY_ENABLED", True))
    always_listening: bool = field(default_factory=lambda: _env_flag("FRIDAY_ALWAYS_LISTENING", True))
    interrupt_on_speech: bool = field(default_factory=lambda: _env_flag("FRIDAY_INTERRUPT_ON_SPEECH", True))
    wake_word: str = field(default_factory=lambda: os.environ.get("FRIDAY_WAKE_WORD", ""))
    health_interval_s: int = field(default_factory=lambda: _env_int("FRIDAY_HEALTH_INTERVAL_S", 30))
    memory_path: Path = MEMORY_DIR / "friday_voice_memory.json"

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for key in self.__dataclass_fields__:
            value = getattr(self, key)
            data[key] = str(value) if isinstance(value, Path) else value
        return data


def load_config() -> FridayVoiceConfig:
    return FridayVoiceConfig()


def log_event(tag: str, message: str, payload: Any | None = None) -> None:
    line = f"[{tag}] {message}"
    print(line, flush=True)
    status_record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tag": str(tag),
        "message": str(message),
        "payload": payload,
    }
    try:
        with (LOG_DIR / "friday_voice.log").open("a", encoding="utf-8") as handle:
            handle.write(line)
            if payload is not None:
                handle.write(f" {payload}")
            handle.write("\n")
    except Exception:
        pass
    try:
        encoded = json.dumps(status_record, ensure_ascii=False, default=str)
        with STATUS_JSONL.open("a", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
        STATUS_LATEST.write_text(json.dumps(status_record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


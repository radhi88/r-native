# ruff: noqa: E402
import asyncio
import base64
import re
import threading
import json
import os
import sys
import time
import traceback
import warnings
import urllib.request
import urllib.error
import socket
import subprocess
import hashlib
import tempfile
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
warnings.filterwarnings("ignore", category=FutureWarning)

import sounddevice as sd
from google import genai
from google.genai import types
from ui import JarvisUI
from core.runtime_control import (
    build_runtime_snapshot,
    format_runtime_snapshot,
    is_command_allowed as runtime_command_allowed,
    is_path_allowed as runtime_path_allowed,
    is_protected_path as runtime_protected_path,
)

from memory.memory_manager import (
    load_memory,
    update_memory,
    format_memory_for_prompt,
)

from actions.file_processor import file_processor
from actions.flight_finder import flight_finder
from actions.open_app import open_app
from actions.weather_report import weather_action
from actions.send_message import send_message
from actions.reminder import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor import screen_process
from actions.youtube_video import youtube_video
from actions.desktop import desktop_control
from actions.browser_control import browser_control
from actions.file_controller import file_controller
from actions.code_helper import code_helper
from actions.dev_agent import dev_agent
from actions.web_search import web_search as web_search_action
from actions.computer_control import computer_control
from actions.game_updater import game_updater

from friday_plugin import (
    FRIDAY_TOOL_DECLARATIONS,
    friday_execute,
    start_awareness_monitor,
    start_sse_listener,
)


# =============================================================================
# Core helpers
# =============================================================================

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _get_env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _get_env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)["gemini_api_key"]


BASE_DIR = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH = BASE_DIR / "core" / "prompt.txt"

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", "none", "disabled"}

OLLAMA_HOST = os.getenv("JARVIS_OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_FAST_MODEL = os.getenv("JARVIS_OLLAMA_FAST_MODEL", "llama3.2:3b").strip() or "llama3.2:3b"
OLLAMA_SMART_MODEL = os.getenv("JARVIS_OLLAMA_SMART_MODEL", "qwen2.5:3b").strip() or "qwen2.5:3b"
OLLAMA_CODE_MODEL = os.getenv("JARVIS_OLLAMA_CODE_MODEL", "qwen2.5-coder:3b").strip() or "qwen2.5-coder:3b"
OLLAMA_TOOL_MODEL = os.getenv("JARVIS_OLLAMA_TOOL_MODEL", "qwen2.5:3b").strip() or "qwen2.5:3b"
OLLAMA_REASONING_MODEL = os.getenv("JARVIS_OLLAMA_REASONING_MODEL", OLLAMA_SMART_MODEL).strip() or OLLAMA_SMART_MODEL
OLLAMA_REVIEW_MODEL = os.getenv("JARVIS_OLLAMA_REVIEW_MODEL", OLLAMA_REASONING_MODEL).strip() or OLLAMA_REASONING_MODEL
OLLAMA_VISION_MODEL = os.getenv("JARVIS_OLLAMA_VISION_MODEL", "llava:latest").strip() or "llava:latest"

OLLAMA_TIMEOUT = _get_env_float("JARVIS_OLLAMA_TIMEOUT", 600.0)
OLLAMA_TEMPERATURE = _get_env_float("JARVIS_OLLAMA_TEMPERATURE", 0.15)
OLLAMA_NUM_CTX = _get_env_int("JARVIS_OLLAMA_NUM_CTX", 4096)
OLLAMA_FAST_NUM_CTX = _get_env_int("JARVIS_OLLAMA_FAST_NUM_CTX", 2048)
OLLAMA_MAX_TOOL_ROUNDS = _get_env_int("JARVIS_OLLAMA_MAX_TOOL_ROUNDS", 3)
OLLAMA_KEEP_ALIVE = os.getenv("JARVIS_OLLAMA_KEEP_ALIVE", "20m").strip() or "20m"
OLLAMA_MULTI_MODEL_ENABLED = os.getenv("JARVIS_MULTI_MODEL_ENABLED", "1").strip().lower() in TRUE_VALUES
OLLAMA_WARMUP_MODELS = os.getenv("JARVIS_WARMUP_MODELS", "0").strip().lower() in TRUE_VALUES
PROJECT_AGENT_PLAN_NUM_CTX = _get_env_int("JARVIS_PROJECT_AGENT_PLAN_NUM_CTX", 3072)
PROJECT_AGENT_CODE_NUM_CTX = _get_env_int("JARVIS_PROJECT_AGENT_CODE_NUM_CTX", 3072)

PROJECT_ROOT = Path(os.getenv("JARVIS_PROJECT_ROOT", str(BASE_DIR))).resolve()
PROJECT_AGENT_ENABLED = os.getenv("JARVIS_PROJECT_AGENT_ENABLED", "1").strip().lower() in TRUE_VALUES
PROJECT_AGENT_BACKUP_DIR = PROJECT_ROOT / ".jarvis_backups"
PROJECT_AGENT_STATE_DIR = PROJECT_ROOT / ".jarvis_agents"
COMMAND_INBOX_PATH = PROJECT_AGENT_STATE_DIR / "jarvis_command_inbox.jsonl"
PROJECT_AGENT_MAX_FILE_CHARS = _get_env_int("JARVIS_PROJECT_AGENT_MAX_FILE_CHARS", 70000)
PROJECT_AGENT_MAX_FILES = _get_env_int("JARVIS_PROJECT_AGENT_MAX_FILES", 350)
PROJECT_AGENT_COMMAND_TIMEOUT = _get_env_int("JARVIS_PROJECT_AGENT_COMMAND_TIMEOUT", 90)
PROJECT_AGENT_WATCH_INTERVAL = _get_env_float("JARVIS_PROJECT_AGENT_WATCH_INTERVAL", 8.0)
PROJECT_AGENT_AUTO_WATCH = os.getenv("JARVIS_PROJECT_AGENT_AUTO_WATCH", "0").strip().lower() in TRUE_VALUES
PROJECT_AGENT_AUTO_FIX = os.getenv("JARVIS_PROJECT_AGENT_AUTO_FIX", "0").strip().lower() in TRUE_VALUES
COMMAND_INBOX_ENABLED = os.getenv("JARVIS_COMMAND_INBOX_ENABLED", "1").strip().lower() in TRUE_VALUES
COMMAND_INBOX_INTERVAL = _get_env_float("JARVIS_COMMAND_INBOX_INTERVAL", 1.0)

PROJECT_AGENT_ALLOWED_EXTENSIONS = {
    ".py", ".txt", ".md", ".json", ".yaml", ".yml", ".toml",
    ".mq5", ".mqh", ".ini", ".env", ".csv", ".html", ".css", ".js", ".ts"
}

PROJECT_AGENT_SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    "node_modules", "dist", "build", ".jarvis_backups", ".jarvis_agents",
    ".mypy_cache", ".ruff_cache", "logs", "realtime_scalper_logs",
    "touch_executor_logs", "position_governor_logs"
}

PROJECT_AGENT_SECRET_FILE_NAMES = {
    ".env", "api_keys.json", "secrets.json", "credentials.json",
    "token.json", "tokens.json", "service_account.json",
    # Trading safety files — must never be AI-edited:
    "trading_runtime.yaml", "dry_run_simulation.yaml",
    "execution_manager.py", "kill_switch.py", "config_loader.py",
}

PROJECT_AGENT_BLOCKED_COMMAND_WORDS = {
    "rm", "rmdir", "del", "erase", "format", "shutdown", "restart", "reboot",
    "curl", "wget", "bitsadmin", "certutil", "powershell.exe", "pwsh"
}

CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = _get_env_int("JARVIS_AUDIO_CHUNK_SIZE", 1024)
AUDIO_MIME_TYPE = os.getenv("JARVIS_LIVE_AUDIO_MIME", "audio/pcm").strip() or "audio/pcm"

VOICE_BACKEND = os.getenv("JARVIS_VOICE_BACKEND", "gemini_live").strip().lower() or "gemini_live"
LIVE_MODEL = (
    os.getenv("JARVIS_LIVE_MODEL", "models/gemini-2.5-flash-native-audio-preview-12-2025").strip()
    or "models/gemini-2.5-flash-native-audio-preview-12-2025"
)
LIVE_MIC_ENABLED = os.getenv("JARVIS_LIVE_MIC", "1").strip().lower() in TRUE_VALUES
LOCAL_MIC_FALLBACK_ENABLED = os.getenv("JARVIS_LOCAL_MIC_FALLBACK", "0").strip().lower() in TRUE_VALUES
VISION_BACKEND = os.getenv("JARVIS_VISION_BACKEND", "llava").strip().lower() or "llava"

MIC_MODE = os.getenv("JARVIS_MIC_MODE", "local").strip().lower() or "local"
LOCAL_STT_BACKEND = os.getenv("JARVIS_STT_BACKEND", "whisper").strip().lower()
LOCAL_STT_LANGUAGES = tuple(
    lang.strip()
    for lang in os.getenv("JARVIS_STT_LANGUAGES", "ar-SA,en-US").split(",")
    if lang.strip()
) or ("ar-SA", "en-US")

LOCAL_STT_TIMEOUT = _get_env_float("JARVIS_STT_TIMEOUT", 1.0)
LOCAL_STT_PHRASE_LIMIT = _get_env_float("JARVIS_STT_PHRASE_LIMIT", 8.0)
WEB_STT_MAX_FAILURES = _get_env_int("JARVIS_WEB_STT_MAX_FAILURES", 1)

VOSK_REPLY_SILENCE_SECONDS = _get_env_float("JARVIS_VOSK_REPLY_SILENCE_SECONDS", 1.15)
MAX_TTS_MIC_GUARD_SECONDS = _get_env_float("JARVIS_MAX_TTS_MIC_GUARD_SECONDS", 8.0)

WHISPER_MODEL_NAME = os.getenv("JARVIS_WHISPER_MODEL", "small").strip() or "small"
WHISPER_DEVICE = os.getenv("JARVIS_WHISPER_DEVICE", "cpu").strip() or "cpu"
WHISPER_COMPUTE_TYPE = os.getenv("JARVIS_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
WHISPER_VAD_RMS = _get_env_float("JARVIS_WHISPER_VAD_RMS", 0.020)
WHISPER_MIN_SPEECH_SECONDS = _get_env_float("JARVIS_WHISPER_MIN_SPEECH_SECONDS", 0.80)
WHISPER_MIN_CHARS = _get_env_int("JARVIS_WHISPER_MIN_CHARS", 4)
WHISPER_MIN_WORDS = _get_env_int("JARVIS_WHISPER_MIN_WORDS", 2)
_WHISPER_LANGUAGE_RAW = os.getenv("JARVIS_WHISPER_LANGUAGE", "ar").strip().lower()
WHISPER_LANGUAGE = None if _WHISPER_LANGUAGE_RAW in {"", "auto", "detect", "none"} else _WHISPER_LANGUAGE_RAW
WHISPER_BEAM_SIZE = _get_env_int("JARVIS_WHISPER_BEAM_SIZE", 3)
WHISPER_BEST_OF = _get_env_int("JARVIS_WHISPER_BEST_OF", 3)
WHISPER_NO_SPEECH_THRESHOLD = _get_env_float("JARVIS_WHISPER_NO_SPEECH_THRESHOLD", 0.45)
WHISPER_LOG_PROB_THRESHOLD = _get_env_float("JARVIS_WHISPER_LOG_PROB_THRESHOLD", -0.75)
WHISPER_INITIAL_PROMPT = os.getenv(
    "JARVIS_WHISPER_INITIAL_PROMPT",
    "محادثة صوتية باللهجة العربية السعودية. قد تحتوي الجملة على كلمات إنجليزية تقنية مثل "
    "JARVIS FRIDAY Gemini Ollama llama qwen llava MT5 MetaTrader Python.",
).strip()
WHISPER_HOTWORDS = os.getenv(
    "JARVIS_WHISPER_HOTWORDS",
    "JARVIS FRIDAY Gemini Ollama llama qwen llava MT5 MetaTrader Python",
).strip()

HISTORY_LIMIT = _get_env_int("JARVIS_HISTORY_LIMIT", 10)
SELF_IMPROVEMENT_PATH = BASE_DIR / "memory" / "ollama_self_improvement.json"

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)


def _clean_transcript(text: str) -> str:
    text = str(text or "")
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


def _safe_tool_text(value: Any, limit: int = 4000) -> str:
    text = str(value)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    if len(text) > limit:
        text = text[:limit] + f"\n[truncated: {len(text)} chars total]"
    return text


def _is_bad_transcript(text: str) -> bool:
    text = _clean_transcript(text)
    if len(text) < WHISPER_MIN_CHARS:
        return True
    words = text.split()
    if len(words) < WHISPER_MIN_WORDS and not re.search(r"[\u0600-\u06ff]{4,}", text):
        return True
    if len(words) > 35:
        unique_ratio = len(set(words)) / max(len(words), 1)
        if unique_ratio < 0.35:
            return True
    counts: Dict[str, int] = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    if counts and max(counts.values()) >= 6:
        return True
    lowered = text.lower().strip(" .,!؟?،")
    noise_phrases = {
        "any",
        "okay",
        "thanks",
        "thank you",
        "that's many",
        "and dismay",
        "give her a hug",
        "give hug",
    }
    return lowered in noise_phrases


class GeminiLiveUnavailable(RuntimeError):
    pass


def _iter_exception_tree(exc: BaseException):
    yield exc
    for child in getattr(exc, "exceptions", []) or []:
        yield from _iter_exception_tree(child)


def _is_live_policy_error(exc: BaseException) -> bool:
    for item in _iter_exception_tree(exc):
        status = getattr(item, "status_code", None)
        text = f"{type(item).__name__}: {item}".lower()
        if status == 1008 or (
            "1008" in text
            and (
                "policy violation" in text
                or "not implemented" in text
                or "not supported" in text
                or "not enabled" in text
            )
        ):
            return True
    return False


def _is_live_invalid_request_error(exc: BaseException) -> bool:
    for item in _iter_exception_tree(exc):
        status = getattr(item, "status_code", None)
        text = f"{type(item).__name__}: {item}".lower()
        if status == 1007 or (
            "1007" in text
            and (
                "invalid argument" in text
                or "invalid frame payload" in text
                or "request contains an invalid argument" in text
            )
        ):
            return True
    return False


def _is_live_recoverable_error(exc: BaseException) -> bool:
    return _is_live_policy_error(exc) or _is_live_invalid_request_error(exc)


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, a local AI assistant running through Ollama. "
            "Be concise, direct, and use tools when the user asks for actions. "
            "Never claim you completed an action unless a tool actually completed it."
        )


def _find_vosk_model_path() -> Optional[Path]:
    candidates: List[Path] = []
    configured = os.getenv("JARVIS_VOSK_MODEL", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            BASE_DIR.parent / "models" / "voice" / "vosk-model-ar-mgb2-0.4",
            BASE_DIR / "models" / "voice" / "vosk-model-ar-mgb2-0.4",
        ]
    )
    for path in candidates:
        try:
            if path.exists():
                return path
        except OSError:
            continue
    return None


def _extract_json_object(text: str) -> Optional[dict]:
    text = _clean_transcript(text)
    if not text:
        return None

    def as_dict(value: Any) -> Optional[dict]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            try:
                nested = json.loads(value)
                if isinstance(nested, dict):
                    return nested
            except Exception:
                return None
        return None

    try:
        parsed = json.loads(text)
        parsed_dict = as_dict(parsed)
        if parsed_dict is not None:
            return parsed_dict
    except Exception:
        pass

    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1).strip())
            parsed_dict = as_dict(parsed)
            if parsed_dict is not None:
                return parsed_dict
        except Exception:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = text[start: end + 1]
        try:
            parsed = json.loads(raw)
            parsed_dict = as_dict(parsed)
            if parsed_dict is not None:
                return parsed_dict
        except Exception:
            return None
    return None


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _normalize_tool_declaration(decl: dict) -> dict:
    return {
        "name": decl.get("name"),
        "description": decl.get("description", ""),
        "parameters": decl.get("parameters", {"type": "OBJECT", "properties": {}}),
    }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


# =============================================================================
# Tool declarations for local LLM routing
# =============================================================================

TOOL_DECLARATIONS = [
    {
        "name": "project_agent",
        "description": (
            "Claude-Code-like local project agent. Reads, edits, writes, validates, monitors, "
            "creates sub-agents, supervises them, and improves project code inside the current project root."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task": {"type": "STRING", "description": "Project task to implement, fix, refactor, analyze, or monitor."},
                "mode": {"type": "STRING", "description": "auto | plan | apply | review | monitor | agents | status"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "runtime_status",
        "description": "Report active JARVIS capabilities, project root, permission profile, safe roots, and safety guards.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "detail": {"type": "BOOLEAN", "description": "Whether to include safe roots and blocked commands."},
            },
        },
    },
    {"name": "open_app", "description": "Open or launch an application.", "parameters": {"type": "OBJECT", "properties": {"app_name": {"type": "STRING"}}, "required": ["app_name"]}},
    {"name": "web_search", "description": "Search web using local tool.", "parameters": {"type": "OBJECT", "properties": {"query": {"type": "STRING"}}, "required": ["query"]}},
    {"name": "weather_report", "description": "Get weather by city.", "parameters": {"type": "OBJECT", "properties": {"city": {"type": "STRING"}}, "required": ["city"]}},
    {"name": "send_message", "description": "Send message via supported platform.", "parameters": {"type": "OBJECT", "properties": {"receiver": {"type": "STRING"}, "message_text": {"type": "STRING"}, "platform": {"type": "STRING"}}, "required": ["receiver", "message_text", "platform"]}},
    {"name": "reminder", "description": "Create local reminder.", "parameters": {"type": "OBJECT", "properties": {"date": {"type": "STRING"}, "time": {"type": "STRING"}, "message": {"type": "STRING"}}, "required": ["date", "time", "message"]}},
    {"name": "youtube_video", "description": "Control YouTube.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}, "query": {"type": "STRING"}, "url": {"type": "STRING"}}}},
    {"name": "screen_process", "description": "Analyze screen or camera.", "parameters": {"type": "OBJECT", "properties": {"angle": {"type": "STRING"}, "text": {"type": "STRING"}}, "required": ["text"]}},
    {"name": "computer_settings", "description": "Control computer settings.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}, "description": {"type": "STRING"}, "value": {"type": "STRING"}}}},
    {"name": "browser_control", "description": "Control browser.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}, "url": {"type": "STRING"}, "query": {"type": "STRING"}, "text": {"type": "STRING"}}, "required": ["action"]}},
    {"name": "file_controller", "description": "Manage files.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}, "path": {"type": "STRING"}, "content": {"type": "STRING"}}, "required": ["action"]}},
    {"name": "desktop_control", "description": "Control desktop.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}}, "required": ["action"]}},
    {"name": "code_helper", "description": "Write, edit, explain, run, or build code files.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}, "description": {"type": "STRING"}, "file_path": {"type": "STRING"}}, "required": ["action"]}},
    {"name": "dev_agent", "description": "Build multi-file local projects.", "parameters": {"type": "OBJECT", "properties": {"description": {"type": "STRING"}}, "required": ["description"]}},
    {"name": "agent_task", "description": "Run complex task queue.", "parameters": {"type": "OBJECT", "properties": {"goal": {"type": "STRING"}}, "required": ["goal"]}},
    {"name": "computer_control", "description": "Direct computer control.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}, "text": {"type": "STRING"}}, "required": ["action"]}},
    {"name": "game_updater", "description": "Steam/Epic updater.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}}}},
    {"name": "flight_finder", "description": "Search flights.", "parameters": {"type": "OBJECT", "properties": {"origin": {"type": "STRING"}, "destination": {"type": "STRING"}, "date": {"type": "STRING"}}, "required": ["origin", "destination", "date"]}},
    {"name": "file_processor", "description": "Process current/uploaded file.", "parameters": {"type": "OBJECT", "properties": {"file_path": {"type": "STRING"}, "action": {"type": "STRING"}}}},
    {"name": "save_memory", "description": "Save local memory.", "parameters": {"type": "OBJECT", "properties": {"category": {"type": "STRING"}, "key": {"type": "STRING"}, "value": {"type": "STRING"}}, "required": ["category", "key", "value"]}},
    {"name": "shutdown_jarvis", "description": "Shutdown assistant.", "parameters": {"type": "OBJECT", "properties": {}}},
    *[_normalize_tool_declaration(x) for x in FRIDAY_TOOL_DECLARATIONS],
]


def _tool_catalog_text() -> str:
    rows = []
    for d in TOOL_DECLARATIONS:
        name = d.get("name", "")
        desc = str(d.get("description", ""))[:180]
        props = d.get("parameters", {}).get("properties", {})
        args = ", ".join(list(props.keys())[:8])
        rows.append(f"- {name}({args}): {desc}")
    return "\n".join(rows)


# =============================================================================
# Memory / learning
# =============================================================================

class SelfImprovementStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict:
        default = {
            "version": 1,
            "lessons": [],
            "tool_stats": {},
            "turns": [],
            "preferences": {},
            "agents": {},
            "last_updated": None,
        }
        if not self.path.exists():
            return default
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for k, v in default.items():
                data.setdefault(k, v)
            return data
        except Exception:
            return default

    def save(self) -> None:
        import time as _t
        self.data["last_updated"] = datetime.now().isoformat(timespec="seconds")
        text = _json_dumps(self.data)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        for attempt in range(5):
            try:
                tmp.replace(self.path); return
            except OSError:
                if attempt == 4:
                    try: self.path.write_text(text, encoding="utf-8"); tmp.unlink(missing_ok=True)
                    except Exception: pass
                    return
                _t.sleep(0.05 * (attempt + 1))

    def record_preference(self, key: str, value: str) -> None:
        key = _clean_transcript(key)
        value = _clean_transcript(value)
        if key and value:
            self.data.setdefault("preferences", {})[key] = value
            self.save()

    def add_lesson(self, lesson: str) -> None:
        lesson = _clean_transcript(lesson)
        if not lesson:
            return
        lessons = self.data.setdefault("lessons", [])
        if lesson not in lessons:
            lessons.append(lesson)
        self.data["lessons"] = lessons[-100:]
        self.save()

    def record_tool(self, name: str, ok: bool, error: str = "") -> None:
        name = _clean_transcript(name) or "unknown"
        stats = self.data.setdefault("tool_stats", {}).setdefault(
            name, {"success": 0, "fail": 0, "last_error": ""}
        )
        if ok:
            stats["success"] += 1
        else:
            stats["fail"] += 1
            stats["last_error"] = str(error)[:500]
        self.save()

    def record_agent(self, name: str, role: str, ok: bool, note: str = "") -> None:
        name = _clean_transcript(name) or "agent"
        item = self.data.setdefault("agents", {}).setdefault(
            name,
            {"role": role, "success": 0, "fail": 0, "notes": [], "last_used": None},
        )
        item["role"] = role or item.get("role", "")
        item["last_used"] = datetime.now().isoformat(timespec="seconds")
        if ok:
            item["success"] += 1
        else:
            item["fail"] += 1
        if note:
            item.setdefault("notes", []).append(note[:500])
            item["notes"] = item["notes"][-20:]
        self.save()

    def record_turn(self, user_text: str, reply: str, tools: List[str]) -> None:
        turns = self.data.setdefault("turns", [])
        turns.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "user": user_text[:1000],
                "reply": reply[:1000],
                "tools": tools[:15],
            }
        )
        self.data["turns"] = turns[-100:]
        self.save()

    def infer_from_user_text(self, text: str) -> None:
        lower = text.lower()
        if "لا تشرح" in text or "بدون شرح" in text or "code only" in lower or "الكود على طول" in text:
            self.record_preference(
                "code_response_style",
                "When the user shares an error or asks for code, provide corrected code directly with minimal explanation.",
            )
        if "ollama" in lower or "olama" in lower or "مدفوع" in text:
            self.record_preference(
                "llm_backend",
                "User prefers free local Ollama models and does not want paid API connections.",
            )
        if "friday" in lower or "mt5" in lower:
            self.record_preference(
                "project_context",
                "User is building FRIDAY/JARVIS local assistant integrated with MT5 and local AI tools.",
            )

    def context(self) -> str:
        preferences = self.data.get("preferences", {})
        lessons = self.data.get("lessons", [])[-15:]
        agents = self.data.get("agents", {})
        lines = ["[LOCAL SELF IMPROVEMENT MEMORY]"]
        if preferences:
            lines.append("User preferences:")
            for k, v in preferences.items():
                lines.append(f"- {k}: {v}")
        if lessons:
            lines.append("Lessons learned:")
            for lesson in lessons:
                lines.append(f"- {lesson}")
        if agents:
            lines.append("Agent performance summary:")
            for name, stat in list(agents.items())[-15:]:
                lines.append(
                    f"- {name}: role={stat.get('role', '')}, success={stat.get('success', 0)}, fail={stat.get('fail', 0)}"
                )
        return "\n".join(lines)


class PerformanceOptimizer:
    def __init__(self, learner: SelfImprovementStore):
        self.learner = learner
        self.slow_threshold = _get_env_float("JARVIS_SLOW_THRESHOLD", 8.0)
        self.very_slow_threshold = _get_env_float("JARVIS_VERY_SLOW_THRESHOLD", 18.0)

    def evaluate(self, elapsed: float, current_model: str) -> dict:
        result = {"slow": False, "very_slow": False, "suggested_model": None, "lesson": None}
        if elapsed >= self.slow_threshold:
            result["slow"] = True
            result["lesson"] = (
                f"Ollama response was slow: {elapsed:.2f}s using {current_model}. "
                "Use shorter context, smaller model, and avoid unnecessary tool loops."
            )
        if elapsed >= self.very_slow_threshold:
            result["very_slow"] = True
            result["suggested_model"] = OLLAMA_FAST_MODEL
        if result["lesson"]:
            self.learner.add_lesson(result["lesson"])
        return result


# =============================================================================
# TTS / Ollama / Model router
# =============================================================================

class LocalTTS:
    def __init__(self, ui: JarvisUI, on_start=None, on_done=None):
        self.ui = ui
        self.on_start = on_start
        self.on_done = on_done
        self.enabled = os.getenv("JARVIS_TTS_ENABLED", "1").strip().lower() in TRUE_VALUES
        self.rate = _get_env_int("JARVIS_TTS_RATE", 175)
        self.volume = _get_env_float("JARVIS_TTS_VOLUME", 1.0)
        self._lock = threading.Lock()
        self._engine = None

    def _init_engine(self):
        if self._engine is not None:
            return self._engine
        try:
            import pyttsx3
        except Exception as exc:
            self.ui.write_log(f"ERR: pyttsx3 is not installed: {exc}")
            return None
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            engine.setProperty("volume", max(0.0, min(1.0, self.volume)))
            self._engine = engine
            return self._engine
        except Exception as exc:
            self.ui.write_log(f"ERR: local TTS init failed: {exc}")
            return None

    def speak(self, text: str) -> None:
        text = _clean_transcript(text)
        if not text:
            return
        self.ui.write_log(f"Jarvis: {text}")
        if not self.enabled:
            return

        def worker():
            with self._lock:
                engine = self._init_engine()
                if engine is None:
                    return
                try:
                    if self.on_start:
                        self.on_start()
                    engine.say(text)
                    engine.runAndWait()
                except Exception as exc:
                    self.ui.write_log(f"ERR: local TTS failed: {str(exc)[:160]}")
                finally:
                    if self.on_done:
                        self.on_done()

        threading.Thread(target=worker, daemon=True).start()


class OllamaClient:
    def __init__(self, host: str, model: str, timeout: float, keep_alive: str = "20m"):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.keep_alive = keep_alive

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        url = f"{self.host}{endpoint}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
        except (TimeoutError, socket.timeout) as exc:
            raise RuntimeError(
                f"Ollama timed out after {self.timeout}s using model '{self.model}'. "
                "Use smaller model or reduce context."
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Ollama connection failed using model '{self.model}'. Make sure 'ollama serve' is running. Details: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama returned invalid JSON: {exc}") from exc

    def chat(
        self,
        messages: List[dict],
        *,
        temperature: float = 0.15,
        num_ctx: Optional[int] = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": temperature,
                "num_ctx": int(num_ctx or OLLAMA_NUM_CTX),
            },
        }
        data = self._post_json("/api/chat", payload)
        msg = data.get("message") or {}
        return str(msg.get("content", "")).strip()

    def ping(self) -> Tuple[bool, str]:
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
                "keep_alive": self.keep_alive,
                "options": {"temperature": 0.0, "num_ctx": 256},
            }
            self._post_json("/api/chat", payload)
            return True, "ok"
        except Exception as exc:
            return False, str(exc)


class ModelRouter:
    def __init__(self, host: str, timeout: float, ui: JarvisUI):
        self.host = host
        self.timeout = timeout
        self.ui = ui
        self.clients: Dict[str, OllamaClient] = {
            "fast": OllamaClient(host, OLLAMA_FAST_MODEL, timeout, OLLAMA_KEEP_ALIVE),
            "smart": OllamaClient(host, OLLAMA_SMART_MODEL, timeout, OLLAMA_KEEP_ALIVE),
            "code": OllamaClient(host, OLLAMA_CODE_MODEL, timeout, OLLAMA_KEEP_ALIVE),
            "tool": OllamaClient(host, OLLAMA_TOOL_MODEL, timeout, OLLAMA_KEEP_ALIVE),
            "reasoning": OllamaClient(host, OLLAMA_REASONING_MODEL, timeout, OLLAMA_KEEP_ALIVE),
            "review": OllamaClient(host, OLLAMA_REVIEW_MODEL, timeout, OLLAMA_KEEP_ALIVE),
        }
        self.last_route = "smart"

    def available_models(self) -> Dict[str, str]:
        return {
            "fast": OLLAMA_FAST_MODEL,
            "smart": OLLAMA_SMART_MODEL,
            "code": OLLAMA_CODE_MODEL,
            "tool": OLLAMA_TOOL_MODEL,
            "reasoning": OLLAMA_REASONING_MODEL,
            "review": OLLAMA_REVIEW_MODEL,
            "vision": OLLAMA_VISION_MODEL,
        }

    def choose_route(self, user_text: str, has_tool_context: bool = False) -> str:
        text = (user_text or "").lower()
        if not OLLAMA_MULTI_MODEL_ENABLED:
            return "smart"
        if has_tool_context:
            return "tool"
        if any(k in text for k in ["main.py", "traceback", "exception", "error", "bug", "debug", "python", "mql5", "mq5", "كود", "خطأ", "صحح", "اكتب لي كامل"]):
            return "code"
        if any(k in text for k in ["طبق", "نفذ", "المشروع", "انشئ", "وكيل", "وكلاء", "يراقب", "طور", "يشرف", "project", "agent", "monitor", "supervise"]):
            return "reasoning"
        if any(k in text for k in ["افتح", "شغل", "ارسل", "ذكرني", "ابحث", "open", "send", "search", "click", "type"]):
            return "tool"
        if len(text) <= 120:
            return "fast"
        return "smart"

    def get_client(self, route: str) -> OllamaClient:
        return self.clients.get(route) or self.clients["smart"]

    def chat(
        self,
        messages: List[dict],
        *,
        user_text: str = "",
        has_tool_context: bool = False,
        route: Optional[str] = None,
        temperature: float = 0.15,
        num_ctx: Optional[int] = None,
    ) -> Tuple[str, str, str]:
        selected_route = route or self.choose_route(user_text, has_tool_context)
        client = self.get_client(selected_route)
        self.last_route = selected_route
        result = client.chat(messages, temperature=temperature, num_ctx=num_ctx)
        return result, selected_route, client.model

    def chat_with_fallback(
        self,
        messages: List[dict],
        *,
        user_text: str = "",
        has_tool_context: bool = False,
        route: Optional[str] = None,
        temperature: float = 0.15,
        num_ctx: Optional[int] = None,
    ) -> Tuple[str, str, str]:
        try:
            return self.chat(
                messages,
                user_text=user_text,
                has_tool_context=has_tool_context,
                route=route,
                temperature=temperature,
                num_ctx=num_ctx,
            )
        except Exception as exc:
            self.ui.write_log(f"ERR: Ollama route failed: {str(exc)[:250]}")
            self.ui.write_log("SYS: Retrying with fast model and compact context...")
            compact = messages[-4:] if len(messages) > 4 else messages
            return self.chat(
                compact,
                user_text=user_text,
                has_tool_context=has_tool_context,
                route="fast",
                temperature=0.05,
                num_ctx=OLLAMA_FAST_NUM_CTX,
            )

    def warmup_all(self) -> Dict[str, Tuple[bool, str]]:
        results: Dict[str, Tuple[bool, str]] = {}

        def warm_one(route: str, client: OllamaClient):
            results[route] = client.ping()

        threads = []
        for route, client in self.clients.items():
            t = threading.Thread(target=warm_one, args=(route, client), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=30)
        return results


# =============================================================================
# Project agent system
# =============================================================================

class ProjectSubAgent:
    def __init__(self, name: str, role: str, route: str, router: ModelRouter, ui: JarvisUI, learner: SelfImprovementStore):
        self.name = name
        self.role = role
        self.route = route
        self.router = router
        self.ui = ui
        self.learner = learner

    def log(self, message: str):
        self.ui.write_log(f"AGENT[{self.name}]: {message}")

    def run_json(self, prompt: str, temperature: float = 0.1, num_ctx: Optional[int] = None) -> dict:
        started = time.perf_counter()
        ok = True
        note = ""
        try:
            result, route, model = self.router.chat_with_fallback(
                [{"role": "user", "content": prompt}],
                user_text=prompt[:500],
                route=self.route,
                temperature=temperature,
                num_ctx=num_ctx or OLLAMA_NUM_CTX,
            )
            elapsed = time.perf_counter() - started
            self.log(f"model={model}, route={route}, elapsed={elapsed:.2f}s")
            parsed = _extract_json_object(result)
            if isinstance(parsed, dict):
                note = "json_ok"
                return parsed
            note = "json_parse_failed"
            return {"summary": result[:3000]}
        except Exception as exc:
            ok = False
            note = str(exc)[:500]
            self.log(f"failed: {note}")
            return {"summary": f"Agent failed: {note}"}
        finally:
            self.learner.record_agent(self.name, self.role, ok, note)


class AgentSupervisor:
    def __init__(self, router: ModelRouter, ui: JarvisUI, learner: SelfImprovementStore):
        self.router = router
        self.ui = ui
        self.learner = learner
        self.agents: Dict[str, ProjectSubAgent] = {}
        self._create_default_agents()

    def _create_default_agents(self):
        self.create_agent("planner", "Plans project changes and decomposes tasks", "reasoning")
        self.create_agent("coder", "Writes targeted unified diffs and safe code fixes", "code")
        self.create_agent("reviewer", "Reviews code, risks, and quality", "review")
        self.create_agent("tester", "Plans and interprets safe local tests", "code")
        self.create_agent("monitor", "Watches project changes and detects risks", "fast")
        self.create_agent("architect", "Suggests better architecture and future agents", "reasoning")

    def create_agent(self, name: str, role: str, route: str = "smart") -> ProjectSubAgent:
        name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.strip() or "agent")
        if route not in {"fast", "smart", "code", "tool", "reasoning", "review"}:
            route = "smart"
        agent = ProjectSubAgent(name, role, route, self.router, self.ui, self.learner)
        self.agents[name] = agent
        self.ui.write_log(f"SUPERVISOR: Created agent {name} route={route} role={role}")
        return agent

    def get(self, name: str) -> ProjectSubAgent:
        return self.agents.get(name) or self.create_agent(name, "Dynamic agent created on demand", "smart")

    def list_agents(self) -> dict:
        return {name: {"role": agent.role, "route": agent.route} for name, agent in self.agents.items()}

    def decide_needed_agents(self, task: str, project_files: List[str]) -> dict:
        architect = self.get("architect")
        prompt = f"""
You supervise local coding agents.

Task:
{task}

Current agents:
{_json_dumps(self.list_agents())}

Project files:
{_json_dumps(project_files[:220])}

Return valid JSON only:
{{
  "needed_agents": [
    {{"name": "agent_name", "role": "role", "route": "fast|smart|code|reasoning|review|tool"}}
  ],
  "workflow": [
    {{"agent": "planner", "job": "what to do"}}
  ],
  "risk_notes": ["short risks"]
}}
""".strip()
        result = architect.run_json(prompt, temperature=0.1, num_ctx=PROJECT_AGENT_PLAN_NUM_CTX)
        for item in result.get("needed_agents", []):
            if isinstance(item, dict):
                name = item.get("name", "")
                role = item.get("role", "")
                route = item.get("route", "smart")
                if name and name not in self.agents:
                    self.create_agent(name, role, route)
        return result


class ProjectAgent:
    def __init__(self, root: Path, ui: JarvisUI, router: ModelRouter, learner: SelfImprovementStore, speak):
        self.root = root.resolve()
        self.ui = ui
        self.router = router
        self.learner = learner
        self.speak = speak
        PROJECT_AGENT_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        PROJECT_AGENT_STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.supervisor = AgentSupervisor(router, ui, learner)
        self.watch_state_path = PROJECT_AGENT_STATE_DIR / "watch_state.json"
        self.task_history_path = PROJECT_AGENT_STATE_DIR / "task_history.json"
        self._watch_stop = threading.Event()
        self._watch_thread: Optional[threading.Thread] = None

    def log(self, message: str):
        self.ui.write_log(f"AGENT: {message}")

    def _safe_path(self, path: str | Path, operation: str = "read") -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        p = p.resolve()
        try:
            p.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Blocked path outside project root: {p}") from exc
        allowed, reason = runtime_path_allowed(p, operation)
        if not allowed:
            raise ValueError(f"Blocked by runtime policy ({reason}): {p}")
        return p

    def _inside_project_root(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
            return True
        except Exception:
            return False

    def _safe_project_file_for_scan(self, path: Path) -> bool:
        if not self._inside_project_root(path):
            return False
        allowed, _reason = runtime_path_allowed(path, "read")
        return allowed

    def _is_allowed_file(self, path: Path) -> bool:
        return path.suffix.lower() in PROJECT_AGENT_ALLOWED_EXTENSIONS

    def _is_skipped(self, path: Path) -> bool:
        if runtime_protected_path(path):
            return True
        lower_parts = {str(part).lower() for part in path.parts}
        if lower_parts & PROJECT_AGENT_SKIP_DIRS:
            return True
        name = path.name.lower()
        if name in PROJECT_AGENT_SECRET_FILE_NAMES:
            return True
        return any(token in name for token in ("apikey", "api_key", "secret", "credential"))

    def list_project_files(self, max_files: int = PROJECT_AGENT_MAX_FILES) -> List[str]:
        results: List[str] = []
        if not self.root.exists():
            return results
        for p in self.root.rglob("*"):
            if len(results) >= max_files:
                break
            if self._is_skipped(p):
                continue
            if p.is_file() and self._is_allowed_file(p) and self._safe_project_file_for_scan(p):
                try:
                    results.append(str(p.relative_to(self.root)))
                except Exception:
                    continue
        return sorted(results)

    def read_file(self, path: str) -> str:
        p = self._safe_path(path, "read")
        if not p.exists():
            raise FileNotFoundError(str(p))
        if not p.is_file():
            raise ValueError(f"Not a file: {p}")
        if self._is_skipped(p):
            raise ValueError(f"Sensitive or skipped file is not readable by the project agent: {p.name}")
        if not self._is_allowed_file(p):
            raise ValueError(f"File type not allowed: {p.suffix}")
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) > PROJECT_AGENT_MAX_FILE_CHARS:
            text = text[:PROJECT_AGENT_MAX_FILE_CHARS] + "\n\n[TRUNCATED]"
        return text

    def backup_file(self, path: Path):
        if not path.exists():
            return
        rel = path.relative_to(self.root)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{timestamp}__{str(rel).replace(os.sep, '__')}"
        backup_path = PROJECT_AGENT_BACKUP_DIR / backup_name
        backup_path.write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        self.log(f"Backup saved: {backup_path.name}")

    def _strip_generated_fences(self, content: str) -> str:
        text = str(content or "").strip()
        fenced = re.fullmatch(r"```(?:[a-zA-Z0-9_+\-.]+)?\s*([\s\S]*?)\s*```", text)
        if fenced:
            return fenced.group(1).strip()
        return text

    def _validate_replacement_content(self, path: Path, content: str):
        rel = str(path.relative_to(self.root)).replace("\\", "/")
        stripped = self._strip_generated_fences(content)
        if "```" in stripped:
            raise ValueError(f"Rejected markdown/code-fenced content for {rel}")
        if path.exists():
            old = path.read_text(encoding="utf-8", errors="replace")
            if path.name == "main.py":
                required_markers = [
                    "class JarvisOllama",
                    "class ProjectAgent",
                    "def main()",
                    "TOOL_DECLARATIONS",
                ]
                missing = [marker for marker in required_markers if marker not in stripped]
                if missing:
                    raise ValueError(
                        f"Rejected unsafe main.py replacement; missing markers: {', '.join(missing)}"
                    )
                if len(stripped) < max(20000, int(len(old) * 0.75)):
                    raise ValueError(
                        "Rejected unsafe main.py replacement; content is much smaller than current file"
                    )
            elif len(old) > 5000 and len(stripped) < int(len(old) * 0.35):
                raise ValueError(
                    f"Rejected suspicious replacement for {rel}; content is much smaller than current file"
                )
        return stripped

    def write_file(self, path: str, content: str):
        p = self._safe_path(path, "write")
        if self._is_skipped(p):
            raise ValueError(f"Sensitive or skipped file is not writable by the project agent: {p.name}")
        if not self._is_allowed_file(p):
            raise ValueError(f"File type not allowed: {p.suffix}")
        content = self._validate_replacement_content(p, content)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            self.backup_file(p)
        p.write_text(content, encoding="utf-8")
        self.log(f"Written: {p.relative_to(self.root)}")

    def _paths_from_unified_diff(self, diff_text: str) -> List[str]:
        paths: List[str] = []
        for line in diff_text.splitlines():
            if line.startswith("+++ ") or line.startswith("--- "):
                raw = line[4:].strip()
                if raw == "/dev/null":
                    continue
                raw = re.sub(r"^[ab]/", "", raw)
                raw = raw.split("\t", 1)[0].strip()
                if raw and raw not in paths:
                    paths.append(raw)
        return paths

    def apply_unified_diff(self, diff_text: str) -> List[str]:
        diff_text = str(diff_text or "").strip()
        if not diff_text:
            raise ValueError("Empty diff.")
        if "```" in diff_text:
            diff_text = re.sub(r"^```(?:diff|patch)?\s*", "", diff_text.strip(), flags=re.IGNORECASE)
            diff_text = re.sub(r"\s*```$", "", diff_text.strip())
        paths = self._paths_from_unified_diff(diff_text)
        if not paths:
            raise ValueError("Unified diff did not declare changed paths.")
        for rel in paths:
            p = self._safe_path(rel, "write")
            if self._is_skipped(p):
                raise ValueError(f"Diff targets sensitive or skipped file: {rel}")
            if not self._is_allowed_file(p):
                raise ValueError(f"Diff targets disallowed file type: {rel}")
        PROJECT_AGENT_STATE_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".diff",
            prefix="jarvis_patch_",
            dir=str(PROJECT_AGENT_STATE_DIR),
            delete=False,
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(diff_text)
            patch_path = handle.name
        try:
            check = self.run_command(["git", "apply", "--check", "--whitespace=nowarn", patch_path])
            if not check.get("ok"):
                raise ValueError(str(check.get("stderr") or check.get("stdout") or "git apply --check failed")[:1200])
            for rel in paths:
                p = self._safe_path(rel, "write")
                if p.exists():
                    self.backup_file(p)
            apply = self.run_command(["git", "apply", "--whitespace=nowarn", patch_path])
            if not apply.get("ok"):
                raise ValueError(str(apply.get("stderr") or apply.get("stdout") or "git apply failed")[:1200])
            self.log(f"Patch applied: {', '.join(paths)}")
            return paths
        finally:
            try:
                Path(patch_path).unlink(missing_ok=True)
            except Exception:
                pass

    def run_command(self, command: List[str], timeout: int = PROJECT_AGENT_COMMAND_TIMEOUT) -> dict:
        command = [str(x) for x in command if str(x).strip()]
        if not command:
            return {"ok": False, "returncode": -1, "stdout": "", "stderr": "Empty command."}
        allowed, reason = runtime_command_allowed(command)
        if not allowed:
            return {
                "ok": False,
                "returncode": -1,
                "stdout": "",
                "stderr": f"Blocked by runtime policy ({reason}): {' '.join(command)}",
            }
        self.log(f"Running command: {' '.join(command)}")
        try:
            proc = subprocess.run(command, cwd=str(self.root), capture_output=True, text=True, timeout=timeout, shell=False)
            return {"ok": proc.returncode == 0, "returncode": proc.returncode, "stdout": proc.stdout[-5000:], "stderr": proc.stderr[-5000:]}
        except Exception as exc:
            return {"ok": False, "returncode": -1, "stdout": "", "stderr": str(exc)}

    def snapshot_files(self) -> dict:
        state: dict = {}
        for rel in self.list_project_files():
            try:
                p = self.root / rel
                text = p.read_text(encoding="utf-8", errors="replace")
                state[rel] = {"sha256": _sha256_text(text), "size": len(text), "mtime": p.stat().st_mtime}
            except Exception:
                continue
        return state

    def load_watch_state(self) -> dict:
        if not self.watch_state_path.exists():
            return {}
        try:
            return json.loads(self.watch_state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_watch_state(self, state: dict):
        self.watch_state_path.write_text(_json_dumps(state), encoding="utf-8")

    def detect_project_changes(self) -> dict:
        old = self.load_watch_state()
        new = self.snapshot_files()
        added = sorted([x for x in new if x not in old])
        removed = sorted([x for x in old if x not in new])
        modified = sorted([x for x in new if x in old and new[x].get("sha256") != old[x].get("sha256")])
        self.save_watch_state(new)
        return {"added": added, "removed": removed, "modified": modified, "total_files": len(new), "time": datetime.now().isoformat(timespec="seconds")}

    def start_monitor(self) -> str:
        if self._watch_thread and self._watch_thread.is_alive():
            return "Project monitor is already running."
        self._watch_stop.clear()

        def watcher():
            self.log("Project monitor started.")
            self.save_watch_state(self.snapshot_files())
            while not self._watch_stop.is_set():
                time.sleep(PROJECT_AGENT_WATCH_INTERVAL)
                try:
                    changes = self.detect_project_changes()
                    if changes["added"] or changes["removed"] or changes["modified"]:
                        self.log(
                            "Project changes detected: "
                            f"added={len(changes['added'])}, removed={len(changes['removed'])}, modified={len(changes['modified'])}"
                        )
                except Exception as exc:
                    self.log(f"Monitor error: {str(exc)[:300]}")
            self.log("Project monitor stopped.")

        self._watch_thread = threading.Thread(target=watcher, daemon=True)
        self._watch_thread.start()
        return "Project monitor started."

    def run_status(self) -> str:
        changes = self.detect_project_changes()
        return _json_dumps(
            {
                "project_root": str(self.root),
                "agents": self.supervisor.list_agents(),
                "changes": changes,
                "monitor_running": bool(self._watch_thread and self._watch_thread.is_alive()),
                "auto_fix": PROJECT_AGENT_AUTO_FIX,
                "runtime": build_runtime_snapshot(),
            }
        )

    def save_task_history(self, item: dict):
        history = []
        if self.task_history_path.exists():
            try:
                history = json.loads(self.task_history_path.read_text(encoding="utf-8"))
            except Exception:
                history = []
        history.append(item)
        self.task_history_path.write_text(_json_dumps(history[-100:]), encoding="utf-8")

    def plan_task(self, user_task: str) -> dict:
        files = self.list_project_files()
        supervisor_plan = self.supervisor.decide_needed_agents(user_task, files)
        planner = self.supervisor.get("planner")
        prompt = f"""
You are a Claude-Code-like local planning agent.

Project root:
{self.root}

Runtime permissions:
{format_runtime_snapshot(detail=True)}

User task:
{user_task}

FRIDAY architecture context:
- One control hub: FRIDAY_DASHBOARD_URL / FRIDAY_BASE on http://127.0.0.1:8790.
- Gateway: 8799, Chat: 8811, TradingView: 8822, Agents: 8833, Brain: 8844.
- Use friday_services/friday_self_test for live status and friday_system_mesh for compatibility findings instead of guessing from files.
- Strategy genomes are symbol-scoped; each available MT5 symbol has its own population file and learned indicators.

Available agents:
{_json_dumps(self.supervisor.list_agents())}

Supervisor plan:
{_json_dumps(supervisor_plan)}

Project files:
{_json_dumps(files[:260])}

Return valid JSON only:
{{
  "summary": "what will be done",
  "files_to_read": ["relative/path.py"],
  "agents_to_use": [{{"agent": "coder", "job": "what this agent will do"}}],
  "risk_notes": ["short note"],
  "execution_steps": ["step 1", "step 2"],
  "validation_commands": [["python", "-m", "py_compile", "main.py"]]
}}

Rules:
- Include main.py if relevant.
- Prefer small targeted edits.
- Do not edit outside project root or outside the runtime safe roots.
- Do not read or expose API keys, tokens, .env files, or credentials.
- If runtime policy blocks an action, report the block instead of bypassing it.
- Do not run long-lived services.
- Do not execute trading/live-money commands.
""".strip()
        result = planner.run_json(prompt, temperature=0.1, num_ctx=PROJECT_AGENT_PLAN_NUM_CTX)
        result.setdefault("supervisor_plan", supervisor_plan)
        return result

    def generate_edits(self, user_task: str, plan: dict) -> dict:
        coder = self.supervisor.get("coder")
        files_to_read = plan.get("files_to_read", [])
        file_context = {}
        for rel in files_to_read[:8]:
            try:
                file_context[rel] = self.read_file(rel)
                self.log(f"Read: {rel}")
            except Exception as exc:
                file_context[rel] = f"[READ_ERROR] {exc}"
        prompt = f"""
You are a local autonomous coding agent.

User task:
{user_task}

Runtime permissions:
{format_runtime_snapshot(detail=True)}

Plan:
{_json_dumps(plan)}

File contents:
{_json_dumps(file_context)}

Return valid JSON only:
{{
  "summary": "brief summary",
  "patches": [{{"description": "small targeted change", "diff": "UNIFIED DIFF TEXT"}}],
  "files": [{{"path": "relative/new_file.py", "content": "FULL NEW FILE CONTENT FOR NEW FILES ONLY"}}],
  "commands": [["python", "-m", "py_compile", "main.py"]],
  "completion_message": "Arabic concise completion message",
  "follow_up_ideas": ["idea 1", "idea 2"],
  "agents_created_or_used": [{{"agent": "coder", "work": "what it did"}}]
}}

Rules:
- For existing files, prefer patches/unified diffs. Do not replace whole files unless the file is new.
- A unified diff must use paths like a/main.py and b/main.py and include enough context for git apply.
- main.py is safety-critical. Never replace main.py with a short scaffold or simplified file.
- Preserve existing features unless task requires change.
- Do not read, print, copy, or modify API keys, tokens, .env files, or credentials.
- Stay within runtime safe roots and respect blocked commands.
- Commands must be safe and local.
- Do not run long-lived servers.
- Do not execute real-money trading commands.
- If you cannot produce a valid safe patch, return no files/patches and explain the blocker in summary.
""".strip()
        return coder.run_json(prompt, temperature=0.05, num_ctx=PROJECT_AGENT_CODE_NUM_CTX)

    def apply_edits(self, edits: dict) -> dict:
        changed = []
        errors = []
        for item in edits.get("patches", []):
            try:
                if not isinstance(item, dict):
                    continue
                diff_text = item.get("diff", "")
                patched = self.apply_unified_diff(diff_text)
                for path in patched:
                    if path not in changed:
                        changed.append(path)
            except Exception as exc:
                errors.append(f"Patch skipped: {exc}")
                self.log(f"Patch error: {exc}")

        for item in edits.get("files", []):
            try:
                if not isinstance(item, dict):
                    continue
                path = item.get("path", "")
                content = item.get("content", "")
                if not path or not isinstance(content, str):
                    continue
                if len(content.strip()) < 10:
                    errors.append(f"Skipped empty/too small content for {path}")
                    continue
                if self._safe_path(path, "write").exists() and not edits.get("allow_full_replacement"):
                    errors.append(
                        f"Skipped full replacement for existing file {path}; use patches instead"
                    )
                    continue
                self.write_file(path, content)
                changed.append(path)
            except Exception as exc:
                errors.append(str(exc))
                self.log(f"Write error: {exc}")

        if not changed and not errors:
            errors.append("No valid patch or file edits were produced by the agents.")

        commands = edits.get("commands", [])
        if not commands:
            for path in changed:
                if path.lower().endswith(".py"):
                    commands.append([sys.executable, "-m", "py_compile", path])

        command_results = []
        for cmd in commands[:8]:
            if not isinstance(cmd, list) or not cmd:
                continue
            normalized = [sys.executable if str(x).lower() == "python" else str(x) for x in cmd]
            result = self.run_command(normalized, timeout=PROJECT_AGENT_COMMAND_TIMEOUT)
            result["command"] = normalized
            command_results.append(result)
        return {"changed_files": changed, "errors": errors, "command_results": command_results}

    def run_task(self, user_task: str, mode: str = "auto") -> str:
        if not PROJECT_AGENT_ENABLED:
            return "Project Agent mode is disabled."
        mode = (mode or "auto").strip().lower()
        self.log(f"Task received: {user_task}")
        self.log(f"Mode: {mode}")

        if mode == "monitor":
            return self.start_monitor()
        if mode == "status":
            return self.run_status()
        if mode == "agents":
            files = self.list_project_files()
            plan = self.supervisor.decide_needed_agents(user_task, files)
            return _json_dumps({"agents": self.supervisor.list_agents(), "supervisor_plan": plan})

        self.speak("بدأت تنفيذ الطلب على ملفات المشروع.")
        plan = self.plan_task(user_task)
        self.log(f"Plan: {plan.get('summary', 'No summary')}")
        for step in plan.get("execution_steps", [])[:8]:
            self.log(f"Step: {step}")
        if mode == "plan":
            return _json_dumps(plan)

        edits = self.generate_edits(user_task, plan)
        self.log(f"Edit summary: {edits.get('summary', 'No summary')}")
        if mode == "review":
            return _json_dumps({"plan": plan, "edits_summary": edits.get("summary", ""), "agents": edits.get("agents_created_or_used", [])})

        applied = self.apply_edits(edits)
        changed = applied.get("changed_files", [])
        errors = applied.get("errors", [])
        command_results = applied.get("command_results", [])
        ok_commands = [x for x in command_results if x.get("ok")]
        bad_commands = [x for x in command_results if not x.get("ok")]

        task_record = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "task": user_task,
            "mode": mode,
            "changed_files": changed,
            "errors": errors,
            "commands": command_results,
            "agents": edits.get("agents_created_or_used", []),
            "follow_up_ideas": edits.get("follow_up_ideas", []),
        }
        self.save_task_history(task_record)

        success = bool(changed) and not bad_commands
        if not changed and errors:
            headline = "لم يتم تطبيق أي تعديل لأن الوكلاء لم ينتجوا patch صالح."
        elif success:
            headline = "تم تنفيذ المهمة على المشروع."
        else:
            headline = "تم تنفيذ جزء من المهمة مع وجود ملاحظات."

        lines = [
            headline,
            f"الملفات المعدلة: {', '.join(changed) if changed else 'لا يوجد'}",
            f"الأوامر الناجحة: {len(ok_commands)}",
            f"الأوامر التي فيها خطأ: {len(bad_commands)}",
        ]
        if edits.get("agents_created_or_used"):
            lines.append("الوكلاء المستخدمين:")
            for item in edits.get("agents_created_or_used", [])[:8]:
                lines.append(f"- {item}")
        if errors:
            lines.append("أخطاء الكتابة:")
            lines.extend(f"- {x}" for x in errors[:8])
        if bad_commands:
            lines.append("نتائج الأخطاء:")
            for item in bad_commands[:5]:
                cmd = item.get("command", [])
                lines.append(f"- command: {' '.join(cmd)}")
                lines.append(f"  stderr: {str(item.get('stderr', ''))[:800]}")
        ideas = edits.get("follow_up_ideas", [])
        if ideas:
            lines.append("أفكار تطوير إضافية:")
            for idea in ideas[:8]:
                lines.append(f"- {idea}")
        final = "\n".join(lines)
        self.log(final)
        return final


# =============================================================================
# Main assistant
# =============================================================================

class JarvisOllama:
    def __init__(self, ui: JarvisUI):
        self.ui = ui
        self.ui.on_text_command = self._on_text_command

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._is_speaking = False
        self._speaking_started_at = 0.0
        self._speaking_lock = threading.Lock()

        self._mic_mode = MIC_MODE
        self._local_mic_enabled = self._mic_mode not in FALSE_VALUES
        self._last_mic_status_log_at = 0.0

        self._vosk_model = None
        self._whisper_model = None
        self._sr_recognizer = None
        self._sr_calibrated = False
        self._force_offline_stt = False
        self._last_local_transcript = ""
        self._last_local_transcript_at = 0.0

        self._history: List[dict] = []
        self._busy_lock = asyncio.Lock()
        self._sse_started = False
        self._friday_awareness_started = False
        self._command_inbox_offset = 0
        self._greeted = False
        self._shutdown_requested = False
        self._voice_backend = VOICE_BACKEND
        self._live_session = None
        self._live_mic_enabled = LIVE_MIC_ENABLED
        self._fallback_mic_task: Optional[asyncio.Task] = None
        self.audio_in_queue: Optional[asyncio.Queue] = None
        self.out_queue: Optional[asyncio.Queue] = None
        self._turn_done_event: Optional[asyncio.Event] = None

        self.learner = SelfImprovementStore(SELF_IMPROVEMENT_PATH)
        self.optimizer = PerformanceOptimizer(self.learner)
        self.model_router = ModelRouter(OLLAMA_HOST, OLLAMA_TIMEOUT, self.ui)
        self.ollama = self.model_router.get_client("smart")
        self._current_user_text = ""

        self.tts = LocalTTS(
            ui,
            on_start=lambda: self.set_speaking(True),
            on_done=lambda: self.set_speaking(False),
        )

        self.project_agent = ProjectAgent(PROJECT_ROOT, self.ui, self.model_router, self.learner, self.speak)
        self._runtime_snapshot = build_runtime_snapshot()
        if hasattr(self.ui, "set_runtime_status"):
            self.ui.set_runtime_status(self._runtime_snapshot)

    def _on_text_command(self, text: str):
        if not self._loop:
            self.ui.write_log("SYS: JARVIS is starting; command ignored.")
            return
        if self._voice_backend == "gemini_live" and self._live_session:
            self.ui.write_log(f"You: {_clean_transcript(text)}")
            asyncio.run_coroutine_threadsafe(self._send_live_text(text), self._loop)
            return
        asyncio.run_coroutine_threadsafe(self.handle_user_text(text), self._loop)

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
            self._speaking_started_at = time.monotonic() if value else 0.0
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def _assistant_audio_active(self) -> bool:
        with self._speaking_lock:
            if not self._is_speaking:
                return False
            if self._speaking_started_at and time.monotonic() - self._speaking_started_at > MAX_TTS_MIC_GUARD_SECONDS:
                self._is_speaking = False
                self._speaking_started_at = 0.0
                return False
            return True

    def speak(self, text: str):
        if self._voice_backend == "gemini_live" and self._loop and self._live_session:
            asyncio.run_coroutine_threadsafe(self._send_live_text(text), self._loop)
            return
        self.tts.speak(text)

    async def _send_live_text(self, text: str) -> bool:
        text = _clean_transcript(text)
        if not text or not self._live_session:
            return False
        try:
            await self._live_session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True,
            )
            return True
        except Exception as exc:
            if _is_live_recoverable_error(exc):
                raise GeminiLiveUnavailable(str(exc)) from exc
            raise

    def speak_error(self, tool_name: str, error: Any):
        short = str(error)[:160]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"صار خطأ في أداة {tool_name}: {short}")

    def refresh_runtime_status(self) -> dict:
        self._runtime_snapshot = build_runtime_snapshot()
        if hasattr(self.ui, "set_runtime_status"):
            self.ui.set_runtime_status(self._runtime_snapshot)
        return self._runtime_snapshot

    def _is_project_request(self, text: str) -> bool:
        lower = text.lower()
        triggers = [
            "طبق على المشروع", "نفذ على المشروع", "عدل المشروع", "صلح المشروع",
            "project_agent", "claude code", "انشئ وكلاء", "وكلاء", "يراقب المشروع",
            "main.py", "اكتب لي كامل الكود", "صلح كل مشاكله",
            "طور نفسه", "يطور نفسه", "تطوير نفسه", "كفاءة الاستجابة",
            "تطوير ذاتي", "طوره", "طور لي نفسك", "ربطه", "ربط", "اجعله على اطلاع",
            "اختبر قدراته", "مراقبه", "مراقبة", "كامل الصلاحيات", "mark_xxxix", "jatvis",
        ]
        return any(t in lower or t in text for t in triggers)

    def _build_system_message(self) -> str:
        memory = load_memory()
        mem_str = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()
        now = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        return f"""
You are JARVIS running locally on Ollama. No Gemini. No paid API dependency.

[CURRENT DATE & TIME]
{time_str}

[CORE PROMPT]
{sys_prompt}

[LONG TERM MEMORY]
{mem_str if mem_str else "No memory yet."}

{self.learner.context()}

[PROJECT ROOT]
{PROJECT_ROOT}

[RUNTIME CAPABILITIES & PERMISSIONS]
{format_runtime_snapshot(detail=True)}

[FRIDAY UNIFIED CONTROL]
FRIDAY has one local dashboard/SSE hub on 8790 and connected services:
- dashboard/hub: {os.getenv("FRIDAY_DASHBOARD_URL", os.getenv("FRIDAY_BASE", "http://127.0.0.1:8790"))}
- gateway: {os.getenv("FRIDAY_GATEWAY_URL", "http://127.0.0.1:8799")}
- chat: {os.getenv("FRIDAY_CHAT_URL", "http://127.0.0.1:8811")}
- tradingview: {os.getenv("FRIDAY_TRADINGVIEW_URL", "http://127.0.0.1:8822")}
- agents: {os.getenv("FRIDAY_AGENTS_URL", "http://127.0.0.1:8833")}
- brain: {os.getenv("FRIDAY_BRAIN_URL", "http://127.0.0.1:8844")}
Use friday_services for current health, friday_system_mesh for system compatibility and safe next actions,
friday_stack_control for start/stop/restart/status, and friday_self_test when the user asks to test your FRIDAY integration.
For code changes and self-development, use project_agent. Keep secrets private.

[LOCAL MODEL ROUTER]
{_json_dumps(self.model_router.available_models())}

[TOOLS]
{_tool_catalog_text()}

[RESPONSE CONTRACT]
Return valid JSON only. No markdown. No code fence.

JSON shape:
{{
  "reply": "Arabic or English natural response to user. Keep it concise.",
  "tool_calls": [{{"name": "tool_name", "args": {{}}}}],
  "memory_updates": [{{"category": "preferences|projects|notes", "key": "snake_case_key", "value": "short English value"}}],
  "self_improvement_notes": ["Short lesson"]
}}

Rules:
- Use project_agent for editing/fixing/implementing code in the current project.
- Use project_agent when user asks for Claude-Code-like behavior, agents, supervision, monitoring, or applying changes.
- Use runtime_status when user asks about capabilities, permissions, safe roots, guards, or what you are allowed to do.
- Use friday_services/friday_system_mesh/friday_self_test when the user asks whether FRIDAY is linked, healthy, evolving, or aware.
- Use friday_stack_control only for explicit service start/stop/restart/status requests.
- Use tools for real actions; do not pretend an action was completed.
- Runtime policy is authoritative. If a request is blocked by guards, state the block briefly and do not bypass it.
- If no tool is needed, return reply and empty tool_calls.
- Keep responses concise.
- Do not execute real-money trading commands.
""".strip()

    def _build_live_config(self) -> types.LiveConnectConfig:
        memory = load_memory()
        mem_str = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()
        now = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        voice_prompt = f"""
You are JARVIS voice conversation layer, matching the original Mark-XXXIX Gemini Live behavior.
Speak naturally and quickly in Arabic unless the user explicitly asks otherwise.

You may use Gemini Live only for listening and speaking with the user.
All real execution, code work, project agents, web/file/computer actions, FRIDAY actions, and vision must go through tools.
Use project_agent for code changes, self-improvement, local agents, planning, implementation, validation, and monitoring.
Use screen_process for vision; it is routed locally to LLaVA when available.
Use friday_services for unified FRIDAY health, friday_system_mesh for compatibility/evolution findings,
friday_stack_control for explicit start/stop/restart/status, and friday_self_test when Radhi asks you to test your FRIDAY connection.
Keep API keys, tokens, .env files, and credentials private.

Local Ollama models available:
{_json_dumps(self.model_router.available_models())}

Current time:
{time_str}

Runtime capabilities and permissions:
{format_runtime_snapshot(detail=True)}

Core prompt:
{sys_prompt}

Memory:
{mem_str if mem_str else "No memory yet."}
""".strip()

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction=voice_prompt,
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=os.getenv("JARVIS_LIVE_VOICE", "Charon")
                    )
                )
            ),
        )

    def _messages(self, extra: Optional[List[dict]] = None) -> List[dict]:
        messages = [{"role": "system", "content": self._build_system_message()}]
        adaptive_history_limit = HISTORY_LIMIT
        try:
            slow_lessons = [
                x for x in self.learner.data.get("lessons", [])
                if "response was slow" in x.lower() or "very slow" in x.lower()
            ]
            if slow_lessons:
                adaptive_history_limit = max(4, min(HISTORY_LIMIT, 6))
        except Exception:
            adaptive_history_limit = HISTORY_LIMIT
        messages.extend(self._history[-adaptive_history_limit:])
        if extra:
            messages.extend(extra)
        return messages

    async def _ollama_chat_async(self, messages: List[dict], has_tool_context: bool = False) -> str:
        started = time.perf_counter()
        result, route, model_name = await asyncio.to_thread(
            self.model_router.chat_with_fallback,
            messages,
            user_text=self._current_user_text,
            has_tool_context=has_tool_context,
            temperature=OLLAMA_TEMPERATURE,
            num_ctx=OLLAMA_NUM_CTX,
        )
        elapsed = time.perf_counter() - started
        decision = self.optimizer.evaluate(elapsed, model_name)
        self.ui.write_log(f"SYS: Model route={route}, model={model_name}, elapsed={elapsed:.2f}s")
        if decision["slow"]:
            self.ui.write_log("SYS: Slow response detected. Future context will be reduced.")
        if decision["very_slow"] and decision["suggested_model"]:
            self.ui.write_log(f"SYS: Suggested faster model: {decision['suggested_model']}")
        return result

    async def handle_user_text(self, text: str):
        text = _clean_transcript(text)
        if not text:
            return
        self._current_user_text = text

        async with self._busy_lock:
            self.learner.infer_from_user_text(text)
            self.ui.write_log(f"You: {text}")
            self.ui.set_state("THINKING")
            tool_names_used: List[str] = []
            final_reply = ""
            self._history.append({"role": "user", "content": text})

            try:
                # Deterministic project-agent shortcut prevents weak local models from missing the tool call.
                if self._is_project_request(text):
                    mode = "auto"
                    if "خطة" in text or "plan" in text.lower():
                        mode = "plan"
                    elif "حالة" in text or "status" in text.lower():
                        mode = "status"
                    elif "راقب" in text or "monitor" in text.lower():
                        mode = "monitor"
                    result = await asyncio.to_thread(self.project_agent.run_task, text, mode)
                    final_reply = result
                    tool_names_used.append("project_agent")
                else:
                    tool_context: List[dict] = []
                    for _round_idx in range(OLLAMA_MAX_TOOL_ROUNDS):
                        raw = await self._ollama_chat_async(self._messages(tool_context), has_tool_context=bool(tool_context))
                        parsed = _extract_json_object(raw)
                        if not isinstance(parsed, dict):
                            final_reply = raw.strip() or "ما قدرت أفهم رد النموذج المحلي."
                            break
                        self._apply_memory_updates(parsed.get("memory_updates", []))
                        self._apply_self_improvement_notes(parsed.get("self_improvement_notes", []))
                        reply = _clean_transcript(parsed.get("reply", ""))
                        tool_calls = parsed.get("tool_calls") or []
                        if not isinstance(tool_calls, list):
                            tool_calls = []
                        if not tool_calls:
                            final_reply = reply or "تم."
                            break
                        tool_results = []
                        for call in tool_calls:
                            if not isinstance(call, dict):
                                continue
                            name = _clean_transcript(call.get("name", ""))
                            args = call.get("args") or {}
                            if not isinstance(args, dict):
                                args = {}
                            if not name:
                                continue
                            tool_names_used.append(name)
                            result = await self._execute_tool(name, args)
                            tool_results.append(result)
                        tool_context.append({"role": "assistant", "content": _json_dumps(parsed)})
                        tool_context.append(
                            {
                                "role": "user",
                                "content": "Tool execution results. Return final JSON response now.\n" + _json_dumps(tool_results),
                            }
                        )
                        final_reply = reply or "تم تنفيذ الأداة."

                if not final_reply:
                    final_reply = "تم."
                self._history.append({"role": "assistant", "content": final_reply})
                self._trim_history()
                self.learner.record_turn(text, final_reply, tool_names_used)
                self.speak(final_reply)
            except Exception as exc:
                traceback.print_exc()
                err = str(exc)[:500]
                self.ui.write_log(f"ERR: Ollama/JARVIS failed: {err}")
                self.speak("صار خطأ في التشغيل. تأكد أن Ollama يعمل والموديلات محمّلة، أو استخدم موديل أصغر.")
            finally:
                if not self.ui.muted:
                    self.ui.set_state("LISTENING")

    def _trim_history(self):
        if len(self._history) > HISTORY_LIMIT:
            self._history = self._history[-HISTORY_LIMIT:]

    def _apply_memory_updates(self, updates: Any):
        if not isinstance(updates, list):
            return
        for item in updates:
            if not isinstance(item, dict):
                continue
            category = _clean_transcript(item.get("category", "notes")) or "notes"
            key = _clean_transcript(item.get("key", ""))
            value = _clean_transcript(item.get("value", ""))
            if not key or not value:
                continue
            try:
                update_memory({category: {key: {"value": value}}})
                self.learner.record_preference(key, value)
            except Exception as exc:
                self.ui.write_log(f"ERR: memory update failed: {str(exc)[:120]}")

    def _apply_self_improvement_notes(self, notes: Any):
        if not isinstance(notes, list):
            return
        for note in notes:
            if isinstance(note, str):
                self.learner.add_lesson(note)

    def _capture_screen_png_for_vision(self) -> bytes:
        try:
            from mss import MSS
            import mss.tools
        except Exception as exc:
            raise RuntimeError(f"mss is not installed: {exc}") from exc
        with MSS() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            shot = sct.grab(monitor)
            return mss.tools.to_png(shot.rgb, shot.size)

    def _llava_screen_process(self, args: dict) -> str:
        question = _clean_transcript(
            args.get("text")
            or args.get("description")
            or "Analyze the current screen and answer briefly in Arabic."
        )
        image_bytes = self._capture_screen_png_for_vision()
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": OLLAMA_VISION_MODEL,
            "prompt": (
                "You are JARVIS vision module. Analyze the screenshot precisely. "
                "Reply in concise Arabic. User question: "
                f"{question}"
            ),
            "images": [image_b64],
            "stream": False,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {"temperature": 0.1, "num_ctx": 2048},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as response:
            result = json.loads(response.read().decode("utf-8", errors="replace"))
        answer = _clean_transcript(result.get("response", ""))
        if answer:
            self.speak(answer)
            return answer
        return "LLaVA returned an empty response."

    async def _execute_tool(self, name: str, args: dict) -> dict:
        self.ui.set_state("THINKING")
        self.ui.write_log(f"TOOL: {name} {args}")
        loop = asyncio.get_event_loop()
        ok = True
        result: Any = "Done."
        try:
            if name == "project_agent":
                task = args.get("task", "")
                mode = args.get("mode", "auto")
                result = await loop.run_in_executor(None, lambda: self.project_agent.run_task(task, mode)) if task else "No project task provided."
            elif name == "runtime_status":
                detail = bool(args.get("detail", True))
                self.refresh_runtime_status()
                result = format_runtime_snapshot(detail=detail)
            elif name == "save_memory":
                category = args.get("category", "notes")
                key = args.get("key", "")
                value = args.get("value", "")
                if key and value:
                    update_memory({category: {key: {"value": value}}})
                    self.learner.record_preference(str(key), str(value))
                result = "Memory saved."
            elif name == "open_app":
                result = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui)) or f"Opened {args.get('app_name')}."
            elif name == "weather_report":
                result = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui)) or "Weather delivered."
            elif name == "browser_control":
                result = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui)) or "Done."
            elif name == "file_controller":
                result = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui)) or "Done."
            elif name == "send_message":
                result = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None)) or f"Message sent to {args.get('receiver')}."
            elif name == "reminder":
                result = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui)) or "Reminder set."
            elif name == "youtube_video":
                result = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui)) or "Done."
            elif name == "screen_process":
                if VISION_BACKEND == "llava":
                    result = await loop.run_in_executor(None, lambda: self._llava_screen_process(args))
                else:
                    threading.Thread(target=screen_process, kwargs={"parameters": args, "response": None, "player": self.ui, "session_memory": None}, daemon=True).start()
                    result = "Vision module activated."
            elif name == "computer_settings":
                result = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui)) or "Done."
            elif name == "desktop_control":
                result = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui)) or "Done."
            elif name == "code_helper":
                result = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak)) or "Done."
            elif name == "dev_agent":
                result = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak)) or "Done."
            elif name == "agent_task":
                from agent.task_queue import get_queue, TaskPriority
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(str(args.get("priority", "normal")).lower(), TaskPriority.NORMAL)
                task_id = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak)
                result = f"Task started. ID: {task_id}"
            elif name == "web_search":
                result = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui)) or "Done."
            elif name == "file_processor":
                if not args.get("file_path") and getattr(self.ui, "current_file", None):
                    args["file_path"] = self.ui.current_file
                result = await loop.run_in_executor(None, lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)) or "Done."
            elif name == "computer_control":
                result = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui)) or "Done."
            elif name == "game_updater":
                result = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak)) or "Done."
            elif name == "flight_finder":
                result = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui)) or "Done."
            elif name.startswith("friday_"):
                result = await loop.run_in_executor(None, lambda: friday_execute(name, args)) or "Done."
            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                self._shutdown_requested = True
                self.speak("تم إيقاف JARVIS.")
                threading.Thread(target=self._shutdown_process, daemon=True).start()
                result = "Shutdown requested."
            else:
                ok = False
                result = f"Unknown tool: {name}"
        except Exception as exc:
            ok = False
            result = f"Tool '{name}' failed: {exc}"
            traceback.print_exc()
            self.speak_error(name, exc)
        self.learner.record_tool(name, ok, "" if ok else str(result))
        safe_result = _safe_tool_text(result)
        self.ui.write_log(f"TOOL_RESULT: {name} -> {safe_result[:500]}")
        return {"tool": name, "ok": ok, "result": safe_result}

    def _shutdown_process(self):
        time.sleep(1.5)
        os._exit(0)

    async def _greet(self):
        await asyncio.sleep(1.0)
        self.speak("أهلًا راضي، JARVIS جاهز. الصوت عبر Gemini Live، والتنفيذ والوكلاء محليًا عبر Ollama.")

    async def _send_live_realtime(self):
        while not self._shutdown_requested:
            if not self.out_queue:
                await asyncio.sleep(0.05)
                continue
            msg = await self.out_queue.get()
            try:
                await self._live_session.send_realtime_input(media=msg)
            except Exception as exc:
                if _is_live_recoverable_error(exc):
                    raise GeminiLiveUnavailable(str(exc)) from exc
                raise

    async def _listen_live_audio(self):
        self.ui.write_log("SYS: Gemini Live microphone active.")
        loop = asyncio.get_running_loop()

        def enqueue_audio(data: bytes) -> None:
            if not self.out_queue or self.out_queue.full():
                return
            self.out_queue.put_nowait({"data": data, "mime_type": AUDIO_MIME_TYPE})

        def callback(indata, frames, time_info, status):
            self._log_mic_status(status)
            if self._assistant_audio_active() or self.ui.muted:
                return
            loop.call_soon_threadsafe(enqueue_audio, indata.tobytes())

        with sd.InputStream(
            samplerate=SEND_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
            callback=callback,
        ):
            while not self._shutdown_requested:
                await asyncio.sleep(0.1)

    async def _receive_live_audio(self):
        self.ui.write_log("SYS: Gemini Live receiver active.")
        out_buf: List[str] = []
        in_buf: List[str] = []
        try:
            while not self._shutdown_requested:
                async for response in self._live_session.receive():
                    if response.data and self.audio_in_queue:
                        if self._turn_done_event and self._turn_done_event.is_set():
                            self._turn_done_event.clear()
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content
                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt:
                                out_buf.append(txt)
                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                in_buf.append(txt)
                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()
                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                            in_buf = []
                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Jarvis: {full_out}")
                            out_buf = []

                    if response.tool_call:
                        function_responses = []
                        for fc in response.tool_call.function_calls:
                            args = dict(fc.args or {})
                            tool_result = await self._execute_tool(fc.name, args)
                            function_responses.append(
                                types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response=tool_result,
                                )
                            )
                        await self._live_session.send_tool_response(
                            function_responses=function_responses
                        )
        except Exception as exc:
            if _is_live_recoverable_error(exc):
                raise GeminiLiveUnavailable(str(exc)) from exc
            raise

    async def _play_live_audio(self):
        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        try:
            while not self._shutdown_requested:
                try:
                    if not self.audio_in_queue:
                        await asyncio.sleep(0.05)
                        continue
                    chunk = await asyncio.wait_for(self.audio_in_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def _run_gemini_live_voice(self):
        client = genai.Client(api_key=_get_api_key(), http_options={"api_version": "v1beta"})
        while not self._shutdown_requested:
            try:
                self.ui.write_log(f"SYS: Connecting Gemini Live voice: {LIVE_MODEL}")
                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=self._build_live_config()) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self._live_session = session
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue = asyncio.Queue(maxsize=12)
                    self._turn_done_event = asyncio.Event()
                    self.ui.write_log("SYS: Gemini Live voice connected.")
                    self.ui.set_state("LISTENING")
                    if self._live_mic_enabled:
                        tg.create_task(self._send_live_realtime())
                        tg.create_task(self._listen_live_audio())
                    elif LOCAL_MIC_FALLBACK_ENABLED:
                        if not self._fallback_mic_task or self._fallback_mic_task.done():
                            self.ui.write_log("SYS: Gemini Live mic disabled; local Whisper mic stays active.")
                            self._fallback_mic_task = asyncio.create_task(self._listen_local_speech())
                    else:
                        self.ui.write_log("SYS: Gemini Live microphone disabled; no local STT fallback.")
                    tg.create_task(self._receive_live_audio())
                    tg.create_task(self._play_live_audio())
                    if not self._greeted:
                        self._greeted = True
                        tg.create_task(self._greet())
            except Exception as exc:
                self._live_session = None
                self.set_speaking(False)
                if _is_live_recoverable_error(exc):
                    self.ui.write_log(f"ERR: Gemini Live recoverable error; reconnecting: {str(exc)[:180]}")
                else:
                    self.ui.write_log(f"ERR: Gemini Live voice failed; reconnecting with original mic path: {str(exc)[:180]}")
                await asyncio.sleep(3)

    async def _listen_local_speech(self):
        self.ui.write_log("SYS: Local microphone active. Ollama receives text only.")
        while True:
            try:
                model_path = _find_vosk_model_path()
                use_whisper = LOCAL_STT_BACKEND in {"whisper", "faster_whisper", "mixed", "multilingual", "hybrid"}
                use_web = (not self._force_offline_stt and LOCAL_STT_BACKEND in {"google", "web", "speech_recognition"})
                if use_whisper:
                    try:
                        await self._listen_whisper_speech()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        if not model_path:
                            raise
                        self.ui.write_log(f"ERR: Whisper mic failed; using Vosk fallback: {str(exc)[:120]}")
                        await self._listen_vosk_speech(model_path)
                elif model_path and not use_web:
                    await self._listen_vosk_speech(model_path)
                else:
                    await self._listen_web_speech_fallback()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.ui.write_log(f"ERR: local microphone restarted after error: {str(exc)[:160]}")
                await asyncio.sleep(3)

    def _log_mic_status(self, status):
        if not status:
            return
        now = time.monotonic()
        if now - self._last_mic_status_log_at >= 10:
            self._last_mic_status_log_at = now
            print(f"[JARVIS] Mic status: {status}")

    def _load_whisper_model(self):
        if self._whisper_model is not None:
            return self._whisper_model
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            raise RuntimeError(f"faster-whisper is not installed: {exc}") from exc
        self.ui.write_log(f"SYS: Loading local Whisper model: {WHISPER_MODEL_NAME}")
        try:
            self._whisper_model = WhisperModel(
                WHISPER_MODEL_NAME,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE,
                local_files_only=True,
            )
        except Exception as exc:
            if WHISPER_MODEL_NAME.lower() == "base":
                raise
            self.ui.write_log(
                f"ERR: Whisper model {WHISPER_MODEL_NAME} unavailable locally; falling back to base: {str(exc)[:120]}"
            )
            self._whisper_model = WhisperModel(
                "base",
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE,
                local_files_only=True,
            )
        return self._whisper_model

    def _transcribe_with_whisper(self, audio):
        model = self._load_whisper_model()
        segments, _info = model.transcribe(
            audio,
            language=WHISPER_LANGUAGE,
            task="transcribe",
            beam_size=WHISPER_BEAM_SIZE,
            best_of=WHISPER_BEST_OF,
            temperature=0.0,
            vad_filter=False,
            condition_on_previous_text=False,
            word_timestamps=False,
            initial_prompt=WHISPER_INITIAL_PROMPT or None,
            hotwords=WHISPER_HOTWORDS or None,
            no_speech_threshold=WHISPER_NO_SPEECH_THRESHOLD,
            log_prob_threshold=WHISPER_LOG_PROB_THRESHOLD,
            compression_ratio_threshold=2.4,
            hallucination_silence_threshold=1.0,
            multilingual=True,
        )
        return " ".join(seg.text.strip() for seg in segments if seg.text).strip()

    async def _listen_whisper_speech(self):
        try:
            import numpy as np
        except Exception as exc:
            raise RuntimeError(f"numpy is not installed: {exc}") from exc
        loop = asyncio.get_running_loop()
        audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=60)
        max_pre_chunks = max(2, int((0.35 * SEND_SAMPLE_RATE) / CHUNK_SIZE))
        pre_chunks = deque(maxlen=max_pre_chunks)
        chunks: List[bytes] = []
        in_speech = False
        voiced_chunks = 0
        speech_started_at = 0.0
        last_voice_at = 0.0
        noise_floor = WHISPER_VAD_RMS / 3.0

        def enqueue_audio(data: bytes) -> None:
            if audio_queue.full():
                return
            audio_queue.put_nowait(data)

        def callback(indata, frames, time_info, status):
            self._log_mic_status(status)
            if self._assistant_audio_active() or self.ui.muted:
                return
            loop.call_soon_threadsafe(enqueue_audio, bytes(indata))

        def chunk_rms(data: bytes) -> float:
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            if samples.size == 0:
                return 0.0
            samples /= 32768.0
            return float(np.sqrt(np.mean(samples * samples)))

        async def flush_whisper_audio() -> None:
            nonlocal chunks, in_speech, voiced_chunks
            if not chunks:
                return
            raw = b"".join(chunks)
            chunks = []
            in_speech = False
            voiced_chunks = 0
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if audio.size < int(SEND_SAMPLE_RATE * WHISPER_MIN_SPEECH_SECONDS):
                return
            text = await asyncio.to_thread(self._transcribe_with_whisper, audio)
            await self._handle_local_transcript(text)

        with sd.RawInputStream(samplerate=SEND_SAMPLE_RATE, channels=CHANNELS, dtype="int16", blocksize=CHUNK_SIZE, callback=callback):
            self.ui.write_log("SYS: Whisper microphone ready.")
            while True:
                data = await audio_queue.get()
                now = loop.time()
                rms = chunk_rms(data)
                threshold = max(WHISPER_VAD_RMS, noise_floor * 3.2)
                speech = rms >= threshold
                if not in_speech and not speech:
                    noise_floor = (noise_floor * 0.98) + (rms * 0.02)
                    pre_chunks.append(data)
                    continue
                if not in_speech:
                    voiced_chunks = voiced_chunks + 1 if speech else 0
                    pre_chunks.append(data)
                    if voiced_chunks < 2:
                        continue
                    in_speech = True
                    speech_started_at = now
                    last_voice_at = now
                    chunks = list(pre_chunks)
                    pre_chunks.clear()
                    continue
                chunks.append(data)
                if speech:
                    last_voice_at = now
                if now - last_voice_at >= VOSK_REPLY_SILENCE_SECONDS or now - speech_started_at >= LOCAL_STT_PHRASE_LIMIT:
                    await flush_whisper_audio()

    async def _listen_vosk_speech(self, model_path: Path):
        try:
            import vosk
        except Exception as exc:
            raise RuntimeError(f"vosk is not installed: {exc}") from exc
        if self._vosk_model is None:
            self.ui.write_log(f"SYS: Loading Vosk model: {model_path.name}")
            vosk.SetLogLevel(-1)
            self._vosk_model = await asyncio.to_thread(vosk.Model, str(model_path))

        def make_recognizer():
            rec = vosk.KaldiRecognizer(self._vosk_model, SEND_SAMPLE_RATE)
            rec.SetWords(False)
            return rec

        recognizer = make_recognizer()
        loop = asyncio.get_running_loop()
        audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=40)
        pending_parts: List[str] = []
        last_partial = ""
        last_speech_change_at = loop.time()

        def add_pending(text: str) -> None:
            text = _clean_transcript(text)
            if text:
                pending_parts.append(text)

        async def flush_pending() -> None:
            nonlocal pending_parts
            text = " ".join(pending_parts).strip()
            pending_parts = []
            await self._handle_local_transcript(text)

        def enqueue_audio(data: bytes) -> None:
            if not audio_queue.full():
                audio_queue.put_nowait(data)

        def callback(indata, frames, time_info, status):
            self._log_mic_status(status)
            if self._assistant_audio_active() or self.ui.muted:
                return
            loop.call_soon_threadsafe(enqueue_audio, bytes(indata))

        with sd.RawInputStream(samplerate=SEND_SAMPLE_RATE, channels=CHANNELS, dtype="int16", blocksize=CHUNK_SIZE, callback=callback):
            self.ui.write_log("SYS: Vosk microphone ready.")
            while True:
                try:
                    data = await asyncio.wait_for(audio_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    now = loop.time()
                    if pending_parts and now - last_speech_change_at >= VOSK_REPLY_SILENCE_SECONDS:
                        await flush_pending()
                        recognizer = make_recognizer()
                        last_partial = ""
                    continue
                now = loop.time()
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result() or "{}")
                    add_pending(result.get("text", ""))
                    if pending_parts:
                        await flush_pending()
                        recognizer = make_recognizer()
                    last_partial = ""
                    continue
                partial_result = json.loads(recognizer.PartialResult() or "{}")
                partial = _clean_transcript(partial_result.get("partial", ""))
                if partial and partial != last_partial:
                    last_partial = partial
                    last_speech_change_at = now
                if last_partial and now - last_speech_change_at >= VOSK_REPLY_SILENCE_SECONDS:
                    add_pending(last_partial)
                    await flush_pending()
                    recognizer = make_recognizer()
                    last_partial = ""

    async def _listen_web_speech_fallback(self):
        self.ui.write_log("SYS: Web speech recognition active.")
        consecutive_failures = 0
        while True:
            if self._assistant_audio_active() or self.ui.muted:
                await asyncio.sleep(0.2)
                continue
            try:
                text = await asyncio.to_thread(self._recognize_web_speech_once)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if type(exc).__name__ == "WaitTimeoutError":
                    continue
                consecutive_failures += 1
                self.ui.write_log(f"ERR: Web speech failed: {str(exc)[:140]}")
                if consecutive_failures >= WEB_STT_MAX_FAILURES:
                    self._force_offline_stt = True
                    self.ui.write_log("SYS: Switching to offline recognition.")
                    return
                await asyncio.sleep(2)
                continue
            consecutive_failures = 0
            await self._handle_local_transcript(text)

    def _recognize_web_speech_once(self) -> str:
        try:
            import speech_recognition as sr
        except Exception as exc:
            raise RuntimeError(f"speech_recognition is not installed: {exc}") from exc
        if self._sr_recognizer is None:
            recognizer = sr.Recognizer()
            recognizer.dynamic_energy_threshold = True
            recognizer.pause_threshold = 0.75
            recognizer.non_speaking_duration = 0.35
            self._sr_recognizer = recognizer
        recognizer = self._sr_recognizer
        with sr.Microphone(sample_rate=SEND_SAMPLE_RATE) as source:
            if not self._sr_calibrated:
                recognizer.adjust_for_ambient_noise(source, duration=0.4)
                self._sr_calibrated = True
            audio = recognizer.listen(source, timeout=LOCAL_STT_TIMEOUT, phrase_time_limit=LOCAL_STT_PHRASE_LIMIT)
        errors: List[str] = []
        for language in LOCAL_STT_LANGUAGES:
            try:
                return recognizer.recognize_google(audio, language=language)
            except sr.UnknownValueError:
                return ""
            except sr.RequestError as exc:
                errors.append(f"{language}: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))
        return ""

    async def _handle_local_transcript(self, text: str):
        text = _clean_transcript(text)
        if _is_bad_transcript(text):
            return
        now = asyncio.get_running_loop().time()
        if text == self._last_local_transcript and now - self._last_local_transcript_at < 2.5:
            return
        self._last_local_transcript = text
        self._last_local_transcript_at = now
        if self._voice_backend == "gemini_live" and self._live_session:
            self.ui.write_log(f"You: {text}")
            await self._send_live_text(text)
            return
        await self.handle_user_text(text)

    async def _handle_inbox_command(self, text: str):
        text = _clean_transcript(text)
        if not text:
            return
        lower = text.lower().strip()
        direct_tools = {
            "/friday_services": ("friday_services", {"detail": True}),
            "/friday_status": ("friday_services", {"detail": True}),
            "/friday_self_test": ("friday_self_test", {}),
            "/friday_test": ("friday_self_test", {}),
        }
        if lower in direct_tools:
            tool_name, args = direct_tools[lower]
            await self._execute_tool(tool_name, args)
            return
        await self.handle_user_text(text)

    async def _watch_command_inbox(self):
        COMMAND_INBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
        COMMAND_INBOX_PATH.touch(exist_ok=True)
        self._command_inbox_offset = COMMAND_INBOX_PATH.stat().st_size
        self.ui.write_log(f"SYS: Command inbox active: {COMMAND_INBOX_PATH}")
        while not self._shutdown_requested:
            try:
                with COMMAND_INBOX_PATH.open("r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(self._command_inbox_offset)
                    lines = handle.readlines()
                    self._command_inbox_offset = handle.tell()
                for raw in lines:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                        text = payload.get("text") or payload.get("command") or ""
                    except Exception:
                        text = raw
                    text = _clean_transcript(str(text))
                    if not text:
                        continue
                    self.ui.write_log(f"SYS: Inbox command received: {text[:120]}")
                    await self._handle_inbox_command(text)
            except Exception as exc:
                self.ui.write_log(f"ERR: Command inbox failed: {str(exc)[:160]}")
            await asyncio.sleep(max(0.25, COMMAND_INBOX_INTERVAL))

    async def run(self):
        self._loop = asyncio.get_event_loop()
        self.ui.set_state("THINKING")
        self.ui.write_log("SYS: Starting local multi-model Ollama JARVIS.")
        self.refresh_runtime_status()
        self.ui.write_log(f"SYS: Project root: {PROJECT_ROOT}")
        self.ui.write_log(f"SYS: Runtime profile: {self._runtime_snapshot.get('profile')}")
        self.ui.write_log(f"SYS: Models: {self.model_router.available_models()}")
        self.ui.write_log(f"SYS: Microphone mode: {self._mic_mode}")

        if OLLAMA_WARMUP_MODELS:
            warmup = await asyncio.to_thread(self.model_router.warmup_all)
            ok_any = any(ok for ok, _msg in warmup.values())
            for route, (ok, msg) in warmup.items():
                model_name = self.model_router.available_models().get(route, "unknown")
                if ok:
                    self.ui.write_log(f"SYS: Ollama route ready: {route} -> {model_name}")
                else:
                    self.ui.write_log(f"ERR: Ollama route failed: {route} -> {model_name}: {msg[:180]}")
            if not ok_any:
                self.speak("Ollama غير شغال أو لا يوجد أي موديل جاهز. شغل ollama serve وحمّل الموديلات.")
            else:
                self.ui.write_log("SYS: Multi-model Ollama connected.")
                self.ui.set_state("LISTENING")
        else:
            ok, msg = await asyncio.to_thread(self.model_router.get_client("fast").ping)
            if not ok:
                self.ui.write_log(f"ERR: Ollama not ready: {msg}")
                self.speak("Ollama غير شغال. شغل الأمر ollama serve ثم شغلني مرة ثانية.")
            else:
                self.ui.write_log("SYS: Ollama connected.")
                self.ui.set_state("LISTENING")

        if PROJECT_AGENT_AUTO_WATCH:
            try:
                msg = await asyncio.to_thread(self.project_agent.start_monitor)
                self.ui.write_log(f"SYS: {msg}")
            except Exception as exc:
                self.ui.write_log(f"ERR: Project monitor failed: {str(exc)[:160]}")

        if not self._sse_started:
            try:
                start_sse_listener(self)
                self._sse_started = True
            except Exception as exc:
                self.ui.write_log(f"ERR: SSE listener failed: {str(exc)[:160]}")

        if not self._friday_awareness_started:
            try:
                start_awareness_monitor(self)
                self._friday_awareness_started = True
            except Exception as exc:
                self.ui.write_log(f"ERR: FRIDAY awareness monitor failed: {str(exc)[:160]}")

        tasks = []
        if COMMAND_INBOX_ENABLED:
            tasks.append(asyncio.create_task(self._watch_command_inbox()))
        if self._voice_backend == "gemini_live":
            tasks.append(asyncio.create_task(self._run_gemini_live_voice()))
        elif self._local_mic_enabled:
            tasks.append(asyncio.create_task(self._listen_local_speech()))
        else:
            self.ui.write_log("SYS: Microphone disabled; use text input in the UI.")

        if self._voice_backend != "gemini_live" and not self._greeted:
            self._greeted = True
            tasks.append(asyncio.create_task(self._greet()))

        try:
            while not self._shutdown_requested:
                await asyncio.sleep(0.5)
        finally:
            for task in tasks:
                task.cancel()


def main():
    import logging as _log
    if PROJECT_AGENT_AUTO_FIX:
        _log.warning("PROJECT_AGENT_AUTO_FIX is enabled — AI will autonomously modify source files")
    if PROJECT_AGENT_AUTO_WATCH:
        _log.warning("PROJECT_AGENT_AUTO_WATCH is enabled — AI will autonomously monitor and fix errors")

    ui = JarvisUI("face.png")
    


    try:

        from qader_visual_upgrade import apply_qader_visual_upgrade

        apply_qader_visual_upgrade(ui)

    except Exception as exc:

        try:

            ui.write_log(f"ERR: Qader visual upgrade failed: {exc}")

        except Exception:

            print(f"ERR: Qader visual upgrade failed: {exc}")


    def runner():
        jarvis = JarvisOllama(ui)
        

        try:
            from qader_visual_upgrade import bind_qader_visual_callbacks
            bind_qader_visual_callbacks(ui, jarvis)
        except Exception as exc:
            try:
                ui.write_log(f"ERR: Qader visual callbacks failed: {exc}")
            except Exception:
                print(f"ERR: Qader visual callbacks failed: {exc}")

        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\nShutting down...")
        except Exception:
            traceback.print_exc()

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()


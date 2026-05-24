"""agents/llm.py — minimal LLM client used by Strategist + future agents.

Tries Ollama (local, free) first; falls back to Claude API if key present.
Returns plain text. Designed for short-context strategic reasoning, not
long-form generation.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Optional


OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
CLAUDE_URL = "https://api.anthropic.com/v1/messages"

# Pick a balanced reasoning model — qwen2.5:7b is good for structured output
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
DEFAULT_CLAUDE_MODEL = "claude-haiku-4-5-20251001"


_LAST_OLLAMA_ERROR = None


def _ollama_generate(prompt: str, system: str = "",
                     model: str = DEFAULT_OLLAMA_MODEL,
                     temperature: float = 0.3,
                     timeout: int = 240) -> Optional[str]:
    """Longer default timeout — qwen2.5:7b on CPU can take 90-180s for big prompts."""
    global _LAST_OLLAMA_ERROR
    try:
        body = json.dumps({
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": 800,
                        "num_ctx": 8192},
        }).encode("utf-8")
        req = urllib.request.Request(
            OLLAMA_URL, data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        _LAST_OLLAMA_ERROR = None
        return data.get("response") or None
    except Exception as e:
        _LAST_OLLAMA_ERROR = f"{type(e).__name__}: {e}"
        print(f"[llm] ollama err: {_LAST_OLLAMA_ERROR}", flush=True)
        return None


def last_error() -> str:
    return _LAST_OLLAMA_ERROR or ""


def _claude_generate(prompt: str, system: str = "",
                     model: str = DEFAULT_CLAUDE_MODEL,
                     temperature: float = 0.3,
                     timeout: int = 30) -> Optional[str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key: return None
    try:
        body = json.dumps({
            "model": model,
            "max_tokens": 800,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            CLAUDE_URL, data=body,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data.get("content", [{}])[0].get("text") or None
    except Exception as e:
        print(f"[llm] claude err: {e}", flush=True)
        return None


def ask(prompt: str, system: str = "", preferred_backend: str = "auto",
        model: str = None, temperature: float = 0.3,
        ollama_fallback_models: list = None) -> dict:
    """Ask the LLM. Returns {ok, text, backend, model, tried}.

    preferred_backend: 'auto' | 'ollama' | 'claude'
    ollama_fallback_models: optional list of models to try in order if the
      primary model times out or returns empty. e.g. ['llama3.1:8b',
      'qwen2.5:7b', 'qwen2.5:3b']. The first one is the primary; later
      ones are progressively smaller fallbacks.
    """
    tried = []  # log each attempt for the caller's debug

    # Resolve the ollama model chain
    if preferred_backend in ("auto", "ollama"):
        chain = (ollama_fallback_models if ollama_fallback_models
                 else [model or DEFAULT_OLLAMA_MODEL])
        for ollama_model in chain:
            txt = _ollama_generate(prompt, system, ollama_model, temperature)
            tried.append({"backend": "ollama", "model": ollama_model,
                          "ok": bool(txt)})
            if txt:
                return {"ok": True, "text": txt,
                        "backend": "ollama", "model": ollama_model,
                        "tried": tried}

    # Claude fallback if ollama chain exhausted (or claude preferred)
    if preferred_backend in ("auto", "claude"):
        txt = _claude_generate(prompt, system,
                               model or DEFAULT_CLAUDE_MODEL,
                               temperature)
        tried.append({"backend": "claude",
                      "model": model or DEFAULT_CLAUDE_MODEL,
                      "ok": bool(txt)})
        if txt:
            return {"ok": True, "text": txt,
                    "backend": "claude",
                    "model": model or DEFAULT_CLAUDE_MODEL,
                    "tried": tried}

    return {"ok": False, "text": "", "backend": None, "model": None,
            "tried": tried,
            "error": f"no LLM backend available (tried {len(tried)})"}


def extract_json(text: str) -> Optional[dict]:
    """Extract first JSON object from LLM response. Forgiving."""
    if not text: return None
    # Find first { ... } or ```json ... ```
    start = text.find("{")
    if start < 0: return None
    # Find matching closing brace by depth count
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{": depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i+1])
                except Exception:
                    return None
    return None

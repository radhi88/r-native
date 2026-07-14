# -*- coding: utf-8 -*-
"""Fast optional LLM router for local agents.

Provider order:
1. Anthropic when ANTHROPIC_API_KEY exists
2. OpenAI when OPENAI_API_KEY exists
3. Ollama on localhost when available

If none are available the caller gets a deterministic fallback instead of blocking.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]


def _load_env_file() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lstrip("\ufeff")
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass


_load_env_file()


def provider_status() -> dict[str, Any]:
    status = {
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "ollama": False,
        "provider": "deterministic",
    }
    try:
        r = requests.get(os.getenv("OLLAMA_TAGS_URL", "http://localhost:11434/api/tags"), timeout=0.25)
        status["ollama"] = bool(r.ok)
    except Exception:
        status["ollama"] = False
    if status["gemini"]:
        status["provider"] = "gemini"
    elif status["openai"]:
        status["provider"] = "openai"
    elif status["anthropic"]:
        status["provider"] = "anthropic"
    elif status["ollama"]:
        status["provider"] = "ollama"
    return status


def complete_text(system: str, prompt: str, max_tokens: int = 220, timeout: float = 1.2) -> tuple[str, str]:
    """Return (provider, text). Never raises and never waits long."""
    errors: list[str] = []
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        try:
            model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            r = requests.post(
                url,
                headers={"x-goog-api-key": gemini_key, "Content-Type": "application/json"},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.15, "maxOutputTokens": max_tokens},
                },
                timeout=timeout,
            )
            if r.ok:
                data = r.json()
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                text = "".join(part.get("text", "") for part in parts).strip()
                if text:
                    return "gemini", text
            else:
                errors.append("gemini_error: " + r.text[:180])
        except Exception as exc:
            errors.append("gemini_error: " + str(exc)[:180])

    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            import anthropic

            client = anthropic.Anthropic(timeout=timeout)
            msg = client.messages.create(
                model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
                max_tokens=max_tokens,
                temperature=0.15,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(getattr(part, "text", "") for part in msg.content).strip()
            if text:
                return "anthropic", text
        except Exception as exc:
            errors.append("anthropic_error: " + str(exc)[:180])

    if os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI

            client = OpenAI(timeout=timeout)
            res = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=0.15,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            text = (res.choices[0].message.content or "").strip()
            if text:
                return "openai", text
        except Exception as exc:
            errors.append("openai_error: " + str(exc)[:180])

    if gemini_key:
        try:
            model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            r = requests.post(
                url,
                headers={"x-goog-api-key": gemini_key, "Content-Type": "application/json"},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.15, "maxOutputTokens": max_tokens},
                },
                timeout=timeout,
            )
            if r.ok:
                data = r.json()
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                text = "".join(part.get("text", "") for part in parts).strip()
                if text:
                    return "gemini", text
            else:
                errors.append("gemini_error: " + r.text[:180])
        except Exception as exc:
            errors.append("gemini_error: " + str(exc)[:180])

    try:
        r = requests.post(
            os.getenv("OLLAMA_GENERATE_URL", "http://localhost:11434/api/generate"),
            json={
                "model": os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
                "prompt": system + "\n\n" + prompt,
                "stream": False,
                "options": {"temperature": 0.15, "num_predict": max_tokens},
            },
            timeout=timeout,
        )
        if r.ok:
            text = (r.json().get("response") or "").strip()
            if text:
                return "ollama", text
    except Exception:
        pass

    return "deterministic", " | ".join(errors)


def complete_json(system: str, prompt: str, fallback: dict[str, Any], timeout: float = 1.2) -> tuple[str, dict[str, Any]]:
    provider, text = complete_text(system, prompt, max_tokens=220, timeout=timeout)
    if not text:
        return provider, fallback
    try:
        return provider, json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return provider, json.loads(match.group(0))
            except Exception:
                pass
    out = dict(fallback)
    out["llm_text"] = text[:500]
    return provider, out

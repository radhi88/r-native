"""trade_commentary.py — J.5 — LLM post-mortem on every closed trade.

After a trade closes, build a context dict (gate verdict at entry, bias, ATR,
news state, archetype) and ask an LLM to generate a 2-line analysis:
- "Why won": gate was strong, breakout aligned with H4 bias
- "Why lost": entered against M30 trend, no liquidity sweep

LLM backends:
1. Ollama local (default, free, no internet) — uses qwen2.5:7b or llama3.2
2. Claude API — if ANTHROPIC_API_KEY env var set, prefers Claude
3. OpenAI — if OPENAI_API_KEY env var set

Commentaries logged to data/r_native/journal/<YYYY-MM-DD>.jsonl

Settings: data/r_native/trade_commentary.json
{
  "enabled":   true,
  "backend":   "auto",       // auto / ollama / claude / openai
  "model":     "qwen2.5:7b", // ollama model name OR claude model
  "max_chars": 400,
  "rate_limit_per_minute": 10
}
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CONFIG_PATH  = Path(r"C:\Users\Radhi\MT5\data\r_native\trade_commentary.json")
JOURNAL_DIR  = Path(r"C:\Users\Radhi\MT5\data\r_native\journal")

DEFAULTS = {
    "enabled":               True,
    "backend":               "auto",
    "model":                 "qwen2.5:7b",
    "max_chars":             400,
    "rate_limit_per_minute": 10,
}

_lock = threading.Lock()
_last_calls = []


def load() -> dict:
    if not CONFIG_PATH.exists(): return DEFAULTS.copy()
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = DEFAULTS.copy(); cfg.update(loaded); return cfg
    except Exception:
        return DEFAULTS.copy()


def save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def _check_rate_limit(per_min: int) -> bool:
    """Returns True if we should proceed (under limit)."""
    now = time.time()
    cutoff = now - 60
    with _lock:
        _last_calls[:] = [t for t in _last_calls if t > cutoff]
        if len(_last_calls) >= per_min: return False
        _last_calls.append(now)
        return True


def _pick_backend(cfg: dict) -> str:
    if cfg["backend"] != "auto": return cfg["backend"]
    if os.environ.get("ANTHROPIC_API_KEY"): return "claude"
    if os.environ.get("OPENAI_API_KEY"):    return "openai"
    return "ollama"


# ── Prompt builder ─────────────────────────────────────────────────────
def _build_prompt(trade: dict) -> str:
    """Build a concise LLM prompt from trade context."""
    return f"""You are an expert trading mentor. A retail trader's bot just closed this trade.
Give a 2-line analysis: line 1 = "Why won" or "Why lost", line 2 = "Lesson".
Be specific. Use the data provided. Max {trade.get('max_chars', 400)} characters total.

Trade:
- Symbol: {trade.get('symbol', '?')}
- Side:   {trade.get('side', '?')}
- Entry:  {trade.get('entry_price', '?')} at {trade.get('entry_time', '?')}
- Exit:   {trade.get('exit_price', '?')} at {trade.get('exit_time', '?')}
- P/L:    ${trade.get('pl', 0):+.2f} ({trade.get('exit_reason', '?')})
- Bars held: {trade.get('bars_held', '?')}

Strategy ({trade.get('genome_id', '?')}):
- Archetype: {trade.get('archetype', '?')}
- Active genes: {', '.join(trade.get('active_genes', [])[:10])}
- SL: {trade.get('sl', '?')}  TP: {trade.get('tp', '?')}

Market at entry:
- M5 bias: {trade.get('m5_bias', '?')}
- H1 bias: {trade.get('h1_bias', '?')}
- H4 bias: {trade.get('h4_bias', '?')}
- ATR(H1): {trade.get('h1_atr', '?')}
- Regime:  {trade.get('regime', '?')}

Respond in plain text, exactly 2 short lines, no preamble."""


# ── Backend implementations ────────────────────────────────────────────
def _ollama(prompt: str, model: str) -> str | None:
    """Call local Ollama. Returns None on failure."""
    try:
        data = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
        req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode())
        return (d.get("response") or "").strip()
    except Exception as e:
        print(f"[commentary] ollama err: {e}")
        return None


def _claude(prompt: str, model: str) -> str | None:
    """Call Anthropic Claude API."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key: return None
    if not model or model.startswith("qwen"): model = "claude-haiku-4-5-20251001"
    try:
        data = json.dumps({
            "model": model,
            "max_tokens": 200,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=data,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            })
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode())
        return (d.get("content", [{}])[0].get("text") or "").strip()
    except Exception as e:
        print(f"[commentary] claude err: {e}")
        return None


def _openai(prompt: str, model: str) -> str | None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key: return None
    if not model or model.startswith("qwen") or model.startswith("claude"):
        model = "gpt-4o-mini"
    try:
        data = json.dumps({
            "model": model,
            "max_tokens": 200,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            })
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode())
        return (d["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        print(f"[commentary] openai err: {e}")
        return None


# ── Main API ──────────────────────────────────────────────────────────
def analyze_trade(trade: dict) -> str | None:
    """Generate commentary for one trade. Returns the text, or None on failure.
    Also appends to today's journal file.

    `trade` should contain at minimum: symbol, side, entry_price, exit_price,
    entry_time, exit_time, pl. Other fields enrich the analysis."""
    cfg = load()
    if not cfg.get("enabled"): return None
    if not _check_rate_limit(int(cfg.get("rate_limit_per_minute", 10))):
        return None
    backend = _pick_backend(cfg)
    prompt  = _build_prompt({**trade, "max_chars": cfg["max_chars"]})

    text = None
    if backend == "ollama":   text = _ollama(prompt, cfg.get("model") or "qwen2.5:7b")
    elif backend == "claude": text = _claude(prompt, cfg.get("model") or "claude-haiku-4-5-20251001")
    elif backend == "openai": text = _openai(prompt, cfg.get("model") or "gpt-4o-mini")

    if not text:
        # Fallback chain
        for fb in ("ollama", "claude", "openai"):
            if fb == backend: continue
            text = {"ollama": _ollama, "claude": _claude, "openai": _openai}[fb](
                prompt, cfg.get("model") or "qwen2.5:7b")
            if text: backend = fb; break

    if not text: return None

    # Trim to max_chars
    text = text[:int(cfg.get("max_chars", 400))]

    # Append to journal
    try:
        JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
        jf = JOURNAL_DIR / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "backend": backend,
            "trade": {k: v for k, v in trade.items() if k != "active_genes"},
            "commentary": text,
        }
        with jf.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[commentary] journal err: {e}")

    return text


def get_today_commentaries(n: int = 20) -> list[dict]:
    """Read today's journal — last N entries."""
    jf = JOURNAL_DIR / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
    if not jf.exists(): return []
    try:
        lines = jf.read_text(encoding="utf-8").splitlines()
        return [json.loads(l) for l in lines[-n:] if l.strip()]
    except Exception:
        return []

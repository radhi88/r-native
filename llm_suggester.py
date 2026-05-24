"""llm_suggester.py — J.18 — LLM proposes genome param tweaks for next campaign.

After N campaigns, sends the LLM the top genomes + their stats and asks for
specific param mutations to try as SEED genomes in the next campaign.

Why this works: the LLM has read 1000s of strategy backtests in its training.
It pattern-matches "this genome wins on M5 with PF 1.6 and 60% WR" → "try
tightening SL to 1.3× ATR and widening TP to 2.0×, with rsi_period 10".

Output: List of seed genomes injected into next campaign's PG (proving grounds).

Uses same backend chain as trade_commentary (Ollama/Claude/OpenAI auto-pick).
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CACHE_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\llm_suggestions")


def _build_prompt(top_genomes: list[dict], symbol: str, tf: str) -> str:
    """Pack top genomes + stats into a prompt asking for tweaks."""
    sample = []
    for g in top_genomes[:10]:
        s = g.get("stats", {})
        sample.append(
            f"  - ID {g.get('id','?')}: PF={s.get('profit_factor','?')}, "
            f"WR={s.get('win_rate','?')}%, trades={s.get('trades','?')}, "
            f"DD={s.get('max_drawdown_pct','?')}%, "
            f"genes={','.join((g.get('active_genes') or [])[:6])}, "
            f"sl={s.get('sl_atr_mult')}, tp={s.get('tp_atr_mult')}")
    return f"""You are an expert quantitative trading researcher. Below are the top genomes
from recent R Native GA campaigns on {symbol} {tf}.

{chr(10).join(sample)}

Propose 5 specific PARAM TWEAKS to try as seed genomes in the next campaign.
For each, name 1-3 genes to mutate and concrete new values. Format as JSON:

[
  {{"rationale": "...", "active_genes_add": [...], "active_genes_remove": [...],
    "param_changes": {{"sl_atr_mult": 1.3, "rsi_period": 10}}}}
]

Keep rationales <30 words. Be specific. Return ONLY valid JSON, no preamble."""


def _call_llm(prompt: str) -> str | None:
    """Try Claude → OpenAI → Ollama in that order."""
    # Claude
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        try:
            data = json.dumps({
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages", data=data,
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as r:
                d = json.loads(r.read().decode())
            return d.get("content", [{}])[0].get("text", "").strip()
        except Exception as e:
            print(f"[suggester] claude err: {e}")

    # OpenAI
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        try:
            data = json.dumps({
                "model": "gpt-4o-mini",
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions", data=data,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as r:
                d = json.loads(r.read().decode())
            return d["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[suggester] openai err: {e}")

    # Ollama local
    try:
        data = json.dumps({"model": "qwen2.5:7b", "prompt": prompt,
                           "stream": False, "format": "json"}).encode()
        req = urllib.request.Request("http://127.0.0.1:11434/api/generate",
                                      data=data,
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode())
        return (d.get("response") or "").strip()
    except Exception as e:
        print(f"[suggester] ollama err: {e}")
        return None


def _parse_response(text: str) -> list[dict]:
    """Strip any preamble + parse JSON list."""
    if not text: return []
    # Find first '[' to skip preamble
    idx = text.find("[")
    if idx < 0: return []
    try:
        end = text.rfind("]") + 1
        return json.loads(text[idx:end])
    except Exception as e:
        print(f"[suggester] parse err: {e}")
        return []


def suggest_for(symbol: str, tf: str, top_genomes: list[dict]) -> list[dict]:
    """Ask LLM for genome tweaks. Returns list of mutation dicts.

    Each mutation has:
      - rationale: str
      - active_genes_add: [str]
      - active_genes_remove: [str]
      - param_changes: {str: any}
    """
    if not top_genomes: return []
    prompt = _build_prompt(top_genomes, symbol, tf)
    text   = _call_llm(prompt)
    suggestions = _parse_response(text or "")

    # Cache for inspection
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fp = CACHE_DIR / f"{symbol}_{tf}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json"
    fp.write_text(json.dumps({
        "symbol": symbol, "tf": tf,
        "prompt_top_genomes": [g.get("id") for g in top_genomes[:10]],
        "raw_response": text,
        "parsed_suggestions": suggestions,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return suggestions


def apply_suggestions_to_seed(base_genome: dict, suggestion: dict) -> dict:
    """Apply one suggestion to a base genome → seed for next campaign."""
    g = json.loads(json.dumps(base_genome))   # deep copy
    add = suggestion.get("active_genes_add", []) or []
    rem = suggestion.get("active_genes_remove", []) or []
    ag = set(g.get("active_genes", []))
    ag.update(add)
    ag.difference_update(rem)
    g["active_genes"] = sorted(ag)
    # Update flags
    flags = g.setdefault("flags", {})
    for k in add: flags[k] = True
    for k in rem: flags[k] = False
    # Apply param changes
    params = g.setdefault("params", {})
    for k, v in (suggestion.get("param_changes") or {}).items():
        params[k] = v
    # New ID
    g["id"] = "LLM_SEED_" + str(hash(str(suggestion)) % 10**6)
    return g


def get_recent_suggestions(n: int = 5) -> list[dict]:
    """Return last N suggestions written to cache."""
    if not CACHE_DIR.exists(): return []
    files = sorted(CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    out = []
    for f in files[:n]:
        try: out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception: pass
    return out

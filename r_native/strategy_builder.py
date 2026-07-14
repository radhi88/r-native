"""strategy_builder.py — "Polish with AI" (Claude Call A).

Turns a natural-language strategy description into a structured Strategy
object via the project's existing LLM wrapper (agents/llm.py). Returns
strict JSON; on parse failure it retries once, then falls back to a sane
default so the wizard never dead-ends.

Pure orchestration — the only side effect is the LLM call.
"""
from __future__ import annotations

import json
from typing import Optional

from r_native.strategy_types import (
    Strategy, RiskConfig, IndicatorStatus, EntryCondition,
    INDICATOR_KEYS, INDICATOR_LABELS,
)


# Claude Call A — system prompt (strict-JSON contract from the spec).
POLISH_SYSTEM_PROMPT = """You are an expert institutional trading strategist. \
Convert the user's natural-language idea into ONE structured strategy that \
combines MULTI-INDICATOR CONFLUENCE with SMART-MONEY STRUCTURE, and return \
STRICT JSON only (no prose, no markdown).

Apply this baseline unless the user overrides it:
- Indicators (each votes bullish/bearish): SMA cross, EMA cross, MACD(12,26,9), \
RSI(14), Supertrend, Stochastic, Bollinger Bands, Awesome Oscillator, \
Parabolic SAR, CCI, ADX filter.
- Bias requires ALL ENABLED indicators to align (no partial agreement).
- Confirm with structure: longs on bullish break-of-structure + demand order \
block / liquidity sweep below; shorts mirror. Skip weak/ranging markets (low ADX).
- Risk: max 1% per trade, daily loss limit 5%, max 1 open trade. ATR(14). \
Stop = 1xATR. Targets T1=1xATR (close 50%), T2=2xATR (close 25%), T3=3xATR (rest); \
move stop to break-even after T1. Minimum confidence 70%.

Return JSON with this exact shape:
{
  "name": string,
  "systemPrompt": string,
  "methodology": "SMC"|"HYBRID"|"TECHNICAL"|"VOLATILITY",
  "pairs": string[],
  "timeframe": "1m"|"5m"|"15m"|"30m"|"1h"|"4h"|"1d",
  "indicators": [{ "key": string, "label": string, "enabled": boolean }],
  "entryConditions": [{ "side": "BUY"|"SELL"|"BOTH", "text": string, "confidence": number }],
  "risk": {
    "maxPerTradePct": number, "dailyLossLimitPct": number, "maxOpenTrades": number,
    "maxPerSymbol": number, "atrLength": number, "slAtrMult": number,
    "tpAtrMults": [number, number, number], "trailAtrMult": number|null, "minConfidence": number
  }
}"""


def polish_strategy(raw_prompt: str, *, name_hint: str = "",
                    pairs_hint: Optional[list] = None,
                    timeframe_hint: str = "15m") -> dict:
    """Run Claude Call A. Returns {ok, strategy: dict, backend, fallback}.

    `strategy` is always a complete Strategy.to_dict() — even on LLM failure
    we synthesize a default seeded from the hints so the wizard can proceed.
    """
    raw_prompt = (raw_prompt or "").strip()
    if not raw_prompt:
        strat = _default_strategy(name_hint or "Untitled", raw_prompt,
                                  pairs_hint, timeframe_hint)
        return {"ok": False, "strategy": strat.to_dict(),
                "backend": None, "fallback": True,
                "reason": "empty prompt"}

    parsed, backend = _call_llm(raw_prompt)
    if parsed is None:
        strat = _default_strategy(name_hint or "Untitled", raw_prompt,
                                  pairs_hint, timeframe_hint)
        return {"ok": False, "strategy": strat.to_dict(),
                "backend": backend, "fallback": True,
                "reason": "LLM unavailable or invalid JSON"}

    strat = _strategy_from_llm(parsed, raw_prompt, name_hint,
                               pairs_hint, timeframe_hint)
    return {"ok": True, "strategy": strat.to_dict(),
            "backend": backend, "fallback": False}


# ─── LLM plumbing ────────────────────────────────────────────────
def _call_llm(raw_prompt: str) -> tuple[Optional[dict], Optional[str]]:
    try:
        from r_native.agents.llm import ask, extract_json
    except Exception:
        return None, None
    # First attempt
    out = ask(prompt=raw_prompt, system=POLISH_SYSTEM_PROMPT,
              preferred_backend="auto", temperature=0.2)
    if out.get("ok"):
        parsed = extract_json(out.get("text") or "")
        if _valid(parsed):
            return parsed, out.get("backend")
    # One retry with a stricter nudge
    out2 = ask(prompt=raw_prompt + "\n\nReturn VALID JSON ONLY. No prose.",
               system=POLISH_SYSTEM_PROMPT, preferred_backend="auto",
               temperature=0.1)
    if out2.get("ok"):
        parsed = extract_json(out2.get("text") or "")
        if _valid(parsed):
            return parsed, out2.get("backend")
    return None, out.get("backend") if out else None


def _valid(parsed) -> bool:
    return bool(parsed and isinstance(parsed, dict) and parsed.get("name"))


# ─── Build Strategy from LLM JSON (fill gaps with defaults) ─────
def _strategy_from_llm(p: dict, raw_prompt: str, name_hint: str,
                       pairs_hint, timeframe_hint) -> Strategy:
    # Indicators — start from the full set, then apply LLM enabled flags
    enabled_map = {}
    for ind in (p.get("indicators") or []):
        k = ind.get("key")
        if k in INDICATOR_KEYS:
            enabled_map[k] = bool(ind.get("enabled", True))
    indicators = [
        IndicatorStatus(k, INDICATOR_LABELS[k],
                        enabled=enabled_map.get(k, True))
        for k in INDICATOR_KEYS
    ]
    entry_conditions = [
        EntryCondition.from_dict(e) for e in (p.get("entryConditions") or [])
    ]
    risk = RiskConfig.from_dict(p.get("risk") or {})
    methodology = p.get("methodology")
    if methodology not in ("SMC", "HYBRID", "TECHNICAL", "VOLATILITY"):
        methodology = "HYBRID"
    timeframe = p.get("timeframe") or timeframe_hint
    pairs = p.get("pairs") or (pairs_hint or [])
    return Strategy(
        id=Strategy.new_id(),
        name=(p.get("name") or name_hint or "Untitled").strip(),
        rawPrompt=raw_prompt,
        systemPrompt=(p.get("systemPrompt") or "").strip(),
        methodology=methodology,
        pairs=list(pairs),
        timeframe=timeframe,
        indicators=indicators,
        entryConditions=entry_conditions,
        risk=risk,
        status="PAUSED",
        createdAt=_now_iso(),
    )


def _default_strategy(name: str, raw_prompt: str, pairs_hint,
                      timeframe_hint: str) -> Strategy:
    s = Strategy.default(name)
    s.rawPrompt = raw_prompt
    s.pairs = list(pairs_hint or [])
    s.timeframe = timeframe_hint or "15m"
    s.systemPrompt = (
        "Multi-indicator confluence + smart-money structure confirmation. "
        "Enter only when all enabled indicators align and structure confirms "
        "with confidence >= 70%. Risk 1% per trade, SL 1xATR, targets at "
        "1/2/3 xATR, break-even after T1."
    )
    s.entryConditions = [
        EntryCondition("BUY",  "All enabled indicators bullish + bullish BOS/OB", 75),
        EntryCondition("SELL", "All enabled indicators bearish + bearish BOS/OB", 75),
    ]
    return s


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

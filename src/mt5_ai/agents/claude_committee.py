"""
Claude multi-agent trading committee for FRIDAY.

Pipeline (inspired by TradingAgents architecture):
  1. MarketAnalyst  — interprets current indicators and price action
  2. BullResearcher — constructs the long-side argument
  3. BearResearcher — constructs the short-side argument
  4. RiskManager    — weighs both arguments against account risk
  5. PortfolioMgr   — emits a final JSON decision: BUY / SELL / HOLD

All agents share a single Anthropic client with prompt caching on their
system prompts (cache_control: ephemeral). The model is configurable through
ANTHROPIC_MODEL.

Output is a dict compatible with base_agent.Signal field names.
Execution is paper/demo only — no real-money orders are placed here.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from ..config import CLAUDE_COMMITTEE_MODEL
from .base_agent import BaseAgent, Signal

log = logging.getLogger("friday.committee")

try:
    import anthropic
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    log.warning("anthropic package not installed — ClaudeCommittee disabled. Run: pip install anthropic")


# ── model & shared client ──────────────────────────────────────────────────────

MODEL = CLAUDE_COMMITTEE_MODEL
_client: Optional["anthropic.Anthropic"] = None


def _coerce_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```json"):
        text = text[len("```json"):].strip()
    elif text.startswith("```"):
        text = text[len("```"):].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return text


def _get_client() -> "anthropic.Anthropic":
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Export it before running the committee."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def committee_unavailable_reason() -> str | None:
    if not _SDK_AVAILABLE:
        return "anthropic package is not installed"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY is not set"
    return None


# ── system prompts (long enough to benefit from prompt caching) ────────────────

_ANALYST_SYSTEM = """\
You are a professional quantitative analyst specialising in XAUUSD (gold) M1 scalping.
Your role is to translate raw market indicator values into a concise, structured
market narrative. You never make trade recommendations — you only describe what the
data shows.

Guidelines:
- Interpret RSI: below 30 = oversold, above 70 = overbought, 30-70 = neutral.
- Interpret MACD crossover direction relative to the signal line.
- Interpret ADX: below 20 = no trend, 20-25 = weak, 25+ = trending market.
- Interpret MFI (Money Flow Index): below 20 = oversold, above 80 = overbought.
- ATR indicates volatility level; higher ATR = wider expected range.
- Trend (EMA8 - EMA21 normalised): positive = bullish bias, negative = bearish.
- Demand/supply proximity: how close price is to recent demand/supply zones.
- Always state the current regime (trending / ranging / volatile) based on ADX + ATR.
- Be factual. Use bullet points. Keep your analysis under 200 words.
"""

_BULL_SYSTEM = """\
You are a bullish market researcher for a XAUUSD M1 scalping desk.
You receive a market analysis summary and must argue the strongest possible case
for entering a LONG (BUY) position right now.

Guidelines:
- Find supporting evidence in the indicator data for a move up.
- Reference demand zones, bullish OB presence, oversold conditions, trend alignment.
- Quantify confidence: low / medium / high, and explain why.
- Suggest a reasonable stop-loss level (in ATR multiples) and take-profit (minimum 1:1.5 R:R).
- If the data genuinely gives no bullish case, say so honestly — but try hard to find one.
- Keep your argument under 150 words.
"""

_BEAR_SYSTEM = """\
You are a bearish market researcher for a XAUUSD M1 scalping desk.
You receive a market analysis summary and must argue the strongest possible case
for entering a SHORT (SELL) position right now.

Guidelines:
- Find supporting evidence in the indicator data for a move down.
- Reference supply zones, bearish OB presence, overbought conditions, trend reversal signals.
- Quantify confidence: low / medium / high, and explain why.
- Suggest a reasonable stop-loss level (in ATR multiples) and take-profit (minimum 1:1.5 R:R).
- If the data genuinely gives no bearish case, say so honestly — but try hard to find one.
- Keep your argument under 150 words.
"""

_RISK_SYSTEM = """\
You are a risk manager for a XAUUSD M1 scalping desk operating in paper/demo mode.
You receive the bull and bear researcher arguments and must evaluate which side
presents an acceptable risk-reward profile.

Risk rules (non-negotiable):
- Do NOT approve trades when ADX < 15 (no trend structure).
- Do NOT approve trades when spread_points > 100 (wide spread).
- Require minimum 1:1.5 R:R on any approved trade.
- Prefer trades where model probability confirms direction (prob > 0.55 for BUY,
  prob < 0.45 for SELL).
- If both bull and bear cases are weak, recommend HOLD.

Output a brief risk verdict: APPROVED_BUY, APPROVED_SELL, or HOLD, followed by
a one-sentence rationale. Keep your response under 100 words.
"""

_PM_SYSTEM = """\
You are the portfolio manager making the final trade decision for FRIDAY,
a XAUUSD M1 scalping system running in paper/demo mode only.

You receive the risk manager's verdict and the underlying market context.
Your job is to emit a single structured JSON decision and nothing else.

JSON schema (strictly follow this — no extra keys, no markdown):
{
  "side": "BUY" | "SELL" | "HOLD",
  "confidence": 0.0–1.0,
  "sl_atr_mult": 1.0–3.0,
  "tp_atr_mult": 1.5–5.0,
  "reason": "one sentence max"
}

Rules:
- side must be exactly one of: BUY, SELL, HOLD
- confidence must be a float between 0.0 and 1.0
- sl_atr_mult: stop-loss distance as ATR multiplier
- tp_atr_mult: take-profit distance as ATR multiplier (must be > sl_atr_mult * 1.5)
- reason: one sentence, no quotes inside
- Output ONLY the JSON object. No preamble, no explanation, no markdown.
"""


# ── individual agent calls ─────────────────────────────────────────────────────

def _call(system: str, user_content: str, max_tokens: int = 512) -> str:
    """Single cached API call. Returns the text content of the response."""
    client = _get_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )
    return resp.content[0].text.strip()


def _market_analyst(market_data: dict) -> str:
    prompt = (
        "Analyse the following XAUUSD M1 market snapshot and produce your structured "
        "market narrative:\n\n"
        f"{json.dumps(market_data, indent=2, default=str)}"
    )
    return _call(_ANALYST_SYSTEM, prompt, max_tokens=400)


def _bull_researcher(analysis: str) -> str:
    prompt = (
        "Based on this market analysis, construct your strongest bullish argument:\n\n"
        f"{analysis}"
    )
    return _call(_BULL_SYSTEM, prompt, max_tokens=350)


def _bear_researcher(analysis: str) -> str:
    prompt = (
        "Based on this market analysis, construct your strongest bearish argument:\n\n"
        f"{analysis}"
    )
    return _call(_BEAR_SYSTEM, prompt, max_tokens=350)


def _risk_manager(analysis: str, bull: str, bear: str, market_data: dict) -> str:
    adx = _coerce_float(market_data.get("adx", 0), 0.0)
    spread_points = _coerce_float(market_data.get("spread_points", 0), 0.0)
    probability = _coerce_float(market_data.get("probability", 0.5), 0.5)
    prompt = (
        f"Market Analysis:\n{analysis}\n\n"
        f"Bullish Argument:\n{bull}\n\n"
        f"Bearish Argument:\n{bear}\n\n"
        f"Key metrics — ADX: {adx:.1f}, "
        f"spread_points: {spread_points:.1f}, "
        f"model_probability: {probability:.3f}\n\n"
        "Provide your risk verdict."
    )
    return _call(_RISK_SYSTEM, prompt, max_tokens=200)


def _portfolio_manager(risk_verdict: str, market_data: dict) -> dict:
    atr = _coerce_float(market_data.get("atr", 0), 0.0)
    price = _coerce_float(market_data.get("price", 0), 0.0)
    probability = _coerce_float(market_data.get("probability", 0.5), 0.5)
    prompt = (
        f"Risk Verdict:\n{risk_verdict}\n\n"
        f"ATR: {atr:.5f}, "
        f"Price: {price:.5f}, "
        f"Model probability: {probability:.3f}\n\n"
        "Emit the final JSON decision."
    )
    raw = _call(_PM_SYSTEM, prompt, max_tokens=150)

    # Parse JSON. The prompt asks for raw JSON, but strip fences defensively.
    raw = _strip_json_fence(raw)
    try:
        decision = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("PM returned invalid JSON: %s", raw)
        decision = {
            "side": "HOLD",
            "confidence": 0.0,
            "sl_atr_mult": 1.5,
            "tp_atr_mult": 2.5,
            "reason": "JSON parse error — defaulting to HOLD",
        }
    return decision


# ── public result type ─────────────────────────────────────────────────────────

@dataclass
class CommitteeDecision:
    side: str           # "BUY" | "SELL" | "HOLD"
    confidence: float
    sl: Optional[float]
    tp: Optional[float]
    reason: str
    analysis: str       # full analyst summary (for logging/UI)
    bull_arg: str
    bear_arg: str
    risk_verdict: str


# ── orchestrator ───────────────────────────────────────────────────────────────

def run_committee(market_data: dict) -> CommitteeDecision:
    """
    Run the full 5-agent pipeline and return a CommitteeDecision.

    market_data keys (all optional with sensible defaults):
        price, atr, probability, adx, mfi, rsi, macd, macd_sig,
        trend, spread_points, smc_buy_score, smc_sell_score,
        in_bullish_ob, in_bearish_ob, demand, supply, volume

    Raises EnvironmentError if ANTHROPIC_API_KEY is not set.
    Raises ImportError if the anthropic package is not installed.
    """
    if not _SDK_AVAILABLE:
        raise ImportError(
            "anthropic package is required. Install with: pip install anthropic"
        )

    price = _coerce_float(market_data.get("price", 0), 0.0)
    atr   = _coerce_float(market_data.get("atr", 0), 0.0)

    log.info("Committee starting — price=%.5f  ATR=%.5f", price, atr)

    analysis     = _market_analyst(market_data)
    log.debug("Analyst: %s", analysis[:120])

    bull_arg     = _bull_researcher(analysis)
    bear_arg     = _bear_researcher(analysis)
    log.debug("Bull: %s", bull_arg[:80])
    log.debug("Bear: %s", bear_arg[:80])

    risk_verdict = _risk_manager(analysis, bull_arg, bear_arg, market_data)
    log.debug("Risk: %s", risk_verdict[:80])

    pm_decision  = _portfolio_manager(risk_verdict, market_data)

    side       = str(pm_decision.get("side", "HOLD")).upper()
    confidence = _clamp(_coerce_float(pm_decision.get("confidence", 0.0), 0.0), 0.0, 1.0)
    sl_mult    = _clamp(_coerce_float(pm_decision.get("sl_atr_mult", 1.5), 1.5), 1.0, 3.0)
    tp_mult    = _clamp(_coerce_float(pm_decision.get("tp_atr_mult", 2.5), 2.5), 1.5, 5.0)
    reason     = str(pm_decision.get("reason", ""))

    if side not in {"BUY", "SELL", "HOLD"}:
        side = "HOLD"
        reason = "Invalid committee side; defaulting to HOLD"

    if side in {"BUY", "SELL"}:
        tp_mult = max(tp_mult, min(5.0, sl_mult * 1.5))

    if price <= 0 or atr <= 0:
        side = "HOLD"
        reason = "Missing price or ATR; defaulting to HOLD"

    if side == "BUY" and atr:
        sl = price - atr * sl_mult
        tp = price + atr * tp_mult
    elif side == "SELL" and atr:
        sl = price + atr * sl_mult
        tp = price - atr * tp_mult
    else:
        sl = tp = None

    log.info(
        "Committee decision: %s  conf=%.2f  SL=%.5f  TP=%.5f  | %s",
        side, confidence, sl or 0, tp or 0, reason,
    )

    return CommitteeDecision(
        side=side,
        confidence=confidence,
        sl=sl,
        tp=tp,
        reason=reason,
        analysis=analysis,
        bull_arg=bull_arg,
        bear_arg=bear_arg,
        risk_verdict=risk_verdict,
    )


def committee_to_signal_kwargs(
    decision: CommitteeDecision,
    symbol: str,
    price: float,
    min_confidence: float = 0.35,
) -> dict | None:
    """
    Convert a CommitteeDecision to keyword arguments for Signal construction.
    Returns None if the decision is HOLD or confidence is too low.
    """
    if decision.side == "HOLD" or decision.confidence < min_confidence:
        return None

    return {
        "agent":       "committee",
        "symbol":      symbol,
        "side":        decision.side,
        "order_type":  "MARKET",
        "probability": decision.confidence,
        "confidence":  decision.confidence,
        "smc_score":   0,
        "price":       price,
        "sl":          decision.sl,
        "tp":          decision.tp,
        "meta":        {
            "reason": decision.reason,
            "risk_verdict": decision.risk_verdict,
        },
    }


class ClaudeCommitteeAgent(BaseAgent):
    """Optional BaseAgent wrapper around the Claude committee pipeline."""

    name = "committee"

    def __init__(
        self,
        executor,
        learning_engine,
        symbol: str,
        min_confidence: float = 0.35,
        cooldown_bars: int = 5,
    ):
        super().__init__(executor, learning_engine, symbol)
        self._min_confidence = float(min_confidence)
        self._cooldown_bars = max(0, int(cooldown_bars))
        self._cooldown_remaining = 0
        self._disabled_reason: str | None = None

    def evaluate(self, market_state: dict) -> Signal | None:
        if self._disabled_reason:
            return None

        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            return None

        price = _coerce_float(market_state.get("price", 0), 0.0)
        atr = _coerce_float(market_state.get("atr", 0), 0.0)
        if price <= 0 or atr <= 0:
            return None

        try:
            decision = run_committee(market_state)
        except (ImportError, EnvironmentError) as exc:
            self._disabled_reason = str(exc)
            self.log.warning("Claude committee disabled: %s", exc)
            return None
        except Exception as exc:
            self._cooldown_remaining = self._cooldown_bars
            self.log.warning("Claude committee failed: %s", exc)
            return None

        self._cooldown_remaining = self._cooldown_bars
        kwargs = committee_to_signal_kwargs(
            decision=decision,
            symbol=self.symbol,
            price=price,
            min_confidence=self._min_confidence,
        )
        if kwargs is None:
            return None

        signal = Signal(**kwargs)
        self._set_active(signal.side, signal.price, signal.sl, signal.tp)
        return signal

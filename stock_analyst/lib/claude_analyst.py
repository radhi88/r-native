"""Claude-powered narrative analysis (Anthropic API).

Public API (stable — pages code against these):
  DEFAULT_MODEL
  bull_bear_case(ticker, facts)  -> str | None
  deep_analysis(ticker, facts)   -> str | None
  macro_pulse(indicators)        -> str | None
  portfolio_review(summary)      -> str | None

Contract: each public function returns None ONLY when the Anthropic API key is
missing (callers then show config.missing_key_notice). Any API failure returns
a short human-readable "AI analysis unavailable: ..." string — never a raised
exception, never a stacktrace, never the key. No caching: these calls are
button-triggered and should always produce a fresh take.
"""
from __future__ import annotations

import json
import os

import anthropic

from lib import config

# Latest Sonnet-tier model; override with CLAUDE_MODEL in .env if desired.
DEFAULT_MODEL = "claude-sonnet-5"


def _model() -> str:
    return os.getenv("CLAUDE_MODEL") or DEFAULT_MODEL


SYSTEM_PROMPT = """You are the analysis writer inside a personal, educational \
stock-market research dashboard. You turn raw market facts into clear, balanced, \
plain-language commentary for a curious retail reader.

Non-negotiable compliance rules:
- NEVER give buy, sell, or hold recommendations, ratings, or calls to action.
- NEVER tell the reader what they "should" do with any security or their money.
- NEVER give price targets, price predictions, or forecasts of future returns.
- NEVER personalize: you know nothing about the reader's finances or goals.
- Describe, don't prescribe. Use neutral descriptive wording such as
  "firm momentum", "higher than the market average", "a low multiple",
  "elevated leverage", "slower revenue growth" — never advice words.

Style rules:
- Always present BOTH sides: an educational bull framing AND a bear framing,
  with roughly equal weight. Strengths and risks, never a verdict.
- Plain language; briefly explain any technical term the first time it appears.
- Structure the answer with markdown headers (## / ###) and short bullet lists.
- Work only from the facts provided. If a value is null or missing, say the
  data is unavailable rather than inventing a number.
- Close with one short line reminding the reader this is educational
  information, not financial advice, and not a recommendation.
"""


def _client() -> anthropic.Anthropic | None:
    """Anthropic client from config.anthropic_key(), or None when key missing."""
    key = config.anthropic_key()
    if not key:
        return None
    return anthropic.Anthropic(api_key=key)


def _dumps(data: dict | None) -> str:
    """Compact, safe JSON serialization of a facts dict."""
    try:
        return json.dumps(data or {}, default=str, separators=(",", ":"))
    except Exception:
        return str(data)


def _ask(system: str, user: str, max_tokens: int = 1400) -> str | None:
    """One-shot Messages API call.

    Returns None only when the API key is missing. Every API failure maps to a
    short "AI analysis unavailable: <reason>" string (no key, no stacktrace).
    """
    client = _client()
    if client is None:
        return None
    try:
        resp = client.messages.create(
            model=_model(),
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError:
        return "AI analysis unavailable: the Anthropic API key was rejected."
    except anthropic.PermissionDeniedError:
        return "AI analysis unavailable: this API key lacks access to the model."
    except anthropic.NotFoundError:
        return (
            "AI analysis unavailable: model not found — check the CLAUDE_MODEL "
            "setting."
        )
    except anthropic.RateLimitError:
        return "AI analysis unavailable: rate limited — try again in a minute."
    except anthropic.BadRequestError:
        return "AI analysis unavailable: the request was rejected by the API."
    except anthropic.APITimeoutError:
        return "AI analysis unavailable: the request timed out."
    except anthropic.APIConnectionError:
        return "AI analysis unavailable: network error reaching the API."
    except anthropic.APIStatusError as e:
        return f"AI analysis unavailable: API error (HTTP {e.status_code})."
    except Exception:
        return "AI analysis unavailable: unexpected error."

    if resp.stop_reason == "refusal":
        return "AI analysis unavailable: the model declined this request."
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        return "AI analysis unavailable: the model returned no text."
    return text


def bull_bear_case(ticker: str, facts: dict) -> str | None:
    """Concise balanced bull/bear brief for one ticker. None only if key missing."""
    user = (
        f"Ticker: {ticker}\n"
        f"Facts (JSON): {_dumps(facts)}\n\n"
        "Write a concise educational brief with exactly these sections:\n"
        "## Bull case — 3 to 5 bullets on strengths visible in the facts\n"
        "## Bear case — 3 to 5 bullets on risks or weaknesses in the facts\n"
        "## What to watch — 2 to 3 neutral data points a learner could follow\n"
        "Keep it tight; every bullet must reference a provided fact."
    )
    return _ask(SYSTEM_PROMPT, user)


def deep_analysis(ticker: str, facts: dict) -> str | None:
    """Longer structured educational walkthrough. None only if key missing."""
    user = (
        f"Ticker: {ticker}\n"
        f"Facts (JSON): {_dumps(facts)}\n\n"
        "Write a structured educational analysis with these sections:\n"
        "## Business snapshot — what the company does, sector and size context\n"
        "## Valuation — interpret the multiples neutrally (e.g. 'a low multiple "
        "relative to the market average') and note what could justify them\n"
        "## Profitability & growth — margins, returns, revenue/earnings trends\n"
        "## Balance sheet & risk — leverage, liquidity, beta, 52-week range "
        "context\n"
        "## Bull framing vs Bear framing — balanced, side by side\n"
        "## Open questions — what a diligent learner would investigate next\n"
        "Explain what each metric means in plain terms as you use it."
    )
    return _ask(SYSTEM_PROMPT, user, max_tokens=2000)


def macro_pulse(indicators: dict) -> str | None:
    """Plain-language read of macro indicators. None only if key missing."""
    user = (
        f"Macro indicators (JSON): {_dumps(indicators)}\n\n"
        "Write a short educational macro overview with these sections:\n"
        "## Where the economy stands — interpret growth, inflation, rates and "
        "labor readings in plain language\n"
        "## Supportive signals — readings that have historically accompanied "
        "favorable market conditions\n"
        "## Cautionary signals — readings that have historically accompanied "
        "headwinds\n"
        "## Context — one paragraph on how these indicators interact\n"
        "Describe historical relationships only; make no forecasts."
    )
    return _ask(SYSTEM_PROMPT, user)


def portfolio_review(summary: str) -> str | None:
    """Educational review of a portfolio summary string. None only if key missing."""
    user = (
        f"Portfolio summary:\n{summary}\n\n"
        "Write an educational review with these sections:\n"
        "## Composition — sector/asset tilts and concentration in plain terms\n"
        "## Strengths — characteristics often viewed as favorable "
        "(diversification, quality tilts, balance)\n"
        "## Considerations — concentration, overlap, volatility or rate "
        "sensitivity a learner may want to understand better\n"
        "## Questions to explore — 2 to 3 neutral prompts for further research\n"
        "Do not suggest adding, trimming, or replacing any position — describe "
        "characteristics only."
    )
    return _ask(SYSTEM_PROMPT, user)

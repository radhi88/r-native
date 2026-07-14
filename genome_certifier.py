"""genome_certifier.py — LLM-issued Trust Certificate for new genomes.

Before the auto-GA daemon (or lineage breeder) promotes a fresh genome to
deployed status, this module sends its stats to the local LLM
(Ollama llama3.1:8b via existing agents/llm.py) and asks for a structured
verdict:

  • trust_score   0..100   — how confident the LLM is this genome will
                              perform live the way its backtest suggests
  • verdict       APPROVE | NEEDS_REVIEW | REJECT
  • strengths     list[str]
  • concerns      list[str]
  • recommended_lot_multiplier  0.5 | 1.0 | 1.5

The certificate is stamped INTO the deployed_genome dict before it goes live,
and the executor reads `cert.recommended_lot_multiplier` to size lots
conservatively when trust < 70.

Idempotent: if a genome already has a certificate, reuse it; force-regen
with force=True.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

CERT_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\certificates")


def _now() -> str: return datetime.now(timezone.utc).isoformat()


# ───────────────────────────────────────────────────────────────────────
# Multi-LLM bridge — Anthropic → OpenAI → Ollama → heuristic fallback.
# Each provider is opt-in: provide API key via env var to enable.
#   ANTHROPIC_API_KEY  → Claude (preferred; cheapest is haiku-4-5)
#   OPENAI_API_KEY     → GPT-4o-mini
#   (no env)           → local Ollama llama3.1:8b
# Returns (text, provider) so the cert can be tagged with who issued it.
# ───────────────────────────────────────────────────────────────────────
import os as _os


def _call_anthropic(prompt: str, max_tokens: int) -> Optional[str]:
    key = _os.environ.get("ANTHROPIC_API_KEY")
    if not key: return None
    try:
        import urllib.request as _ur
        body = json.dumps({
            "model":      "claude-haiku-4-5",
            "max_tokens": max_tokens,
            "messages":   [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = _ur.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"x-api-key": key,
                     "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"})
        with _ur.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        blocks = data.get("content") or []
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    except Exception:
        return None


def _call_openai(prompt: str, max_tokens: int) -> Optional[str]:
    key = _os.environ.get("OPENAI_API_KEY")
    if not key: return None
    try:
        import urllib.request as _ur
        body = json.dumps({
            "model":       "gpt-4o-mini",
            "max_tokens":  max_tokens,
            "temperature": 0.2,
            "messages":    [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = _ur.Request(
            "https://api.openai.com/v1/chat/completions", data=body,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"})
        with _ur.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        choices = data.get("choices") or []
        return (choices[0].get("message", {}).get("content")
                if choices else None)
    except Exception:
        return None


def _call_ollama(prompt: str, max_tokens: int,
                 model: str = "llama3.1:8b") -> Optional[str]:
    try:
        import urllib.request as _ur
        body = json.dumps({
            "model":   model,
            "prompt":  prompt,
            "stream":  False,
            "options": {"num_predict": max_tokens, "temperature": 0.2},
        }).encode("utf-8")
        req = _ur.Request("http://localhost:11434/api/generate", data=body,
                           headers={"Content-Type": "application/json"})
        with _ur.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
        return data.get("response")
    except Exception:
        return None


def _call_llm(prompt: str, model: str = "llama3.1:8b",
              max_tokens: int = 600) -> Optional[str]:
    """Returns LLM text reply or None. Caller resolves provider via _call_llm_tagged."""
    text, _ = _call_llm_tagged(prompt, max_tokens=max_tokens, prefer=model)
    return text


def _call_llm_tagged(prompt: str, max_tokens: int = 600,
                      prefer: str = "llama3.1:8b") -> tuple:
    """Try providers in order; return (text, provider_tag) or (None, '')."""
    # 1) Project's own wrapper (if user wired one)
    try:
        from r_native.agents.llm import chat_complete
        out = chat_complete(prompt, model=prefer, max_tokens=max_tokens)
        if out: return out, "project_llm"
    except Exception: pass

    # 2) Anthropic Claude (preferred when key present — best quality / fastest tier)
    out = _call_anthropic(prompt, max_tokens)
    if out: return out, "anthropic_haiku_4.5"

    # 3) OpenAI GPT-4o-mini
    out = _call_openai(prompt, max_tokens)
    if out: return out, "openai_gpt4o_mini"

    # 4) Local Ollama
    out = _call_ollama(prompt, max_tokens, model=prefer)
    if out: return out, f"ollama_{prefer}"

    return None, ""


# ───────────────────────────────────────────────────────────────────────
# Prompt + parser
# ───────────────────────────────────────────────────────────────────────

_PROMPT_TPL = """You are a quantitative trading reviewer. Issue a TRUST CERTIFICATE
for a freshly evolved trading genome. Respond ONLY with valid JSON, no preamble.

Required JSON shape:
{{
  "trust_score": int 0..100,
  "verdict": "APPROVE" | "NEEDS_REVIEW" | "REJECT",
  "strengths": [string, ...],
  "concerns":  [string, ...],
  "recommended_lot_multiplier": 0.5 | 1.0 | 1.5
}}

Scoring guide:
- 80-100 APPROVE: high WR (≥70%), high PF (≥2.5), sufficient samples (≥30 trades),
  reasonable drawdown (≤15%), realistic gene mix
- 50-79 NEEDS_REVIEW: at least one weak metric; deserves smaller lot, watch closely
- 0-49 REJECT: low WR, low PF, suspicious gene mix, or insufficient samples
- lot multiplier 0.5 for NEEDS_REVIEW with concerns, 1.0 for clean APPROVE,
  1.5 only when WR ≥85%, PF ≥4, ≥50 trades

Genome to evaluate:
- symbol: {symbol}
- genome_id: {gid}
- backtest stats:
    trades: {trades}
    win_rate: {wr}%
    profit_factor: {pf}
    sharpe: {sharpe}
    max_drawdown: {dd}%
    linearity: {lin}
- active genes ({n_genes}): {genes}
- SL multiplier: {sl_mult}
- TP multiplier: {tp_mult}
- session window: {start_hour}-{end_hour} UTC

Return ONLY the JSON object."""


def _parse_certificate(text: str) -> Optional[dict]:
    """Extract the first JSON object from the LLM's reply."""
    if not text: return None
    # Try direct parse first
    try: return json.loads(text)
    except Exception: pass
    # Look for {...} block
    m = re.search(r"\{[\s\S]*\}", text)
    if not m: return None
    try: return json.loads(m.group(0))
    except Exception: return None


def _heuristic_certificate(genome: dict, stats: dict) -> dict:
    """Fallback when LLM is unavailable — score by simple rules. Always returns
    a valid certificate so the pipeline never blocks on a missing LLM."""
    wr     = float(stats.get("win_rate") or genome.get("win_rate") or 0)
    pf     = float(stats.get("profit_factor") or genome.get("profit_factor") or 0)
    trades = int(stats.get("trades") or genome.get("trades") or 0)
    dd     = float(stats.get("max_drawdown_pct") or 0)
    sharpe = float(stats.get("sharpe") or genome.get("sharpe") or 0)

    score = 0
    score += min(40, wr / 100 * 40)
    score += min(30, pf * 6)
    score += min(15, trades / 4)
    score += min(10, sharpe * 2)
    score -= max(0, (dd - 15)) * 0.5
    score = max(0, min(100, int(score)))

    if score >= 80:
        verdict, lot = "APPROVE", (1.5 if (wr >= 85 and pf >= 4 and trades >= 50) else 1.0)
    elif score >= 50:
        verdict, lot = "NEEDS_REVIEW", 0.5
    else:
        verdict, lot = "REJECT", 0.5

    concerns = []
    strengths = []
    if wr >= 70: strengths.append(f"high win rate ({wr:.0f}%)")
    elif wr < 50: concerns.append(f"low win rate ({wr:.0f}%)")
    if pf >= 2: strengths.append(f"profit factor {pf:.1f}")
    elif pf < 1.2: concerns.append(f"profit factor {pf:.1f} weak")
    if trades < 20: concerns.append(f"low sample size ({trades} trades)")
    if dd > 20: concerns.append(f"large drawdown ({dd:.0f}%)")

    return {
        "trust_score": score,
        "verdict":     verdict,
        "strengths":   strengths or ["sufficient backtest data"],
        "concerns":    concerns or ["none flagged"],
        "recommended_lot_multiplier": lot,
        "issued_by":   "heuristic_fallback",
    }


# ───────────────────────────────────────────────────────────────────────
# Public API
# ───────────────────────────────────────────────────────────────────────

def certify(symbol: str, genome: dict, force: bool = False) -> dict:
    """Generate (or load cached) trust certificate for a genome.
    `genome` is the deployed_genome dict (or a ga_strategies entry).
    Result is also persisted to certificates/<gid>.json."""
    gid = genome.get("id") or "UNKNOWN"
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    cert_path = CERT_DIR / f"{gid}.json"

    if not force and cert_path.exists():
        try: return json.loads(cert_path.read_text(encoding="utf-8"))
        except Exception: pass

    # Build stats view
    stats = {
        "trades":           genome.get("trades", 0),
        "win_rate":         genome.get("win_rate", 0),
        "profit_factor":    genome.get("profit_factor", 0),
        "sharpe":           genome.get("sharpe", 0),
        "max_drawdown_pct": genome.get("max_drawdown_pct", 0),
        "linearity":        genome.get("linearity", 0),
    }
    genes = genome.get("active_genes") or []

    prompt = _PROMPT_TPL.format(
        symbol      = symbol,
        gid         = gid,
        trades      = stats["trades"],
        wr          = stats["win_rate"],
        pf          = stats["profit_factor"],
        sharpe      = stats["sharpe"],
        dd          = stats["max_drawdown_pct"],
        lin         = stats["linearity"],
        n_genes     = len(genes),
        genes       = ", ".join(genes[:18]),
        sl_mult     = genome.get("sl_atr_mult", "?"),
        tp_mult     = genome.get("tp_atr_mult", "?"),
        start_hour  = genome.get("start_hour", 0),
        end_hour    = genome.get("end_hour", 23),
    )

    raw, provider = _call_llm_tagged(prompt)
    cert = _parse_certificate(raw) if raw else None
    if not cert or "trust_score" not in cert:
        cert = _heuristic_certificate(genome, stats)
    else:
        cert.setdefault("issued_by", provider or "unknown_llm")

    cert["genome_id"]   = gid
    cert["symbol"]      = symbol
    cert["issued_at"]   = _now()
    cert.setdefault("trust_score", 50)
    cert.setdefault("verdict", "NEEDS_REVIEW")
    cert.setdefault("recommended_lot_multiplier", 0.5)
    cert.setdefault("strengths", [])
    cert.setdefault("concerns", [])

    try: cert_path.write_text(json.dumps(cert, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except Exception: pass
    return cert


def get_certificate(gid: str) -> Optional[dict]:
    """Read existing certificate for a genome (no LLM call)."""
    p = CERT_DIR / f"{gid}.json"
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return None


def list_certificates() -> dict:
    """Summary of all issued certificates — used by UI / dashboard."""
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(CERT_DIR.glob("*.json")):
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
            out.append({"genome_id": c.get("genome_id"),
                        "symbol": c.get("symbol"),
                        "trust_score": c.get("trust_score"),
                        "verdict": c.get("verdict"),
                        "lot_mult": c.get("recommended_lot_multiplier"),
                        "issued_at": c.get("issued_at"),
                        "issued_by": c.get("issued_by")})
        except Exception: pass
    return {"ok": True, "count": len(out), "certificates": out}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="r_native.genome_certifier")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_cert = sub.add_parser("certify", help="issue a cert for one symbol's deployed_genome")
    p_cert.add_argument("symbol")
    p_cert.add_argument("--force", action="store_true")
    p_get = sub.add_parser("get", help="read existing cert by genome_id")
    p_get.add_argument("genome_id")
    sub.add_parser("list", help="list all certificates")
    args = ap.parse_args()

    if args.cmd == "certify":
        from pathlib import Path as _P
        cfg = json.loads((_P(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
                          / f"{args.symbol}.json").read_text(encoding="utf-8"))
        dg = cfg.get("deployed_genome") or {}
        print(json.dumps(certify(args.symbol, dg, force=args.force),
                          ensure_ascii=False, indent=2))
    elif args.cmd == "get":
        c = get_certificate(args.genome_id)
        print(json.dumps(c, ensure_ascii=False, indent=2) if c else "no certificate")
    elif args.cmd == "list":
        print(json.dumps(list_certificates(), ensure_ascii=False, indent=2))

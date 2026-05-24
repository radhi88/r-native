"""agents/llm_strategist.py — LLM-powered strategic advisor.

Every 15 minutes, this agent gathers a structured snapshot of the system
(account, HoF top genomes, recent insights, auto-evo status, agent health)
and asks an LLM to produce strategic recommendations in JSON form.

The LLM is asked specific questions like:
  • should any threshold be tuned? (auto_deploy_threshold,
    MAX_ACCOUNT_DD_PCT, AUTO_PIN_SCORE_THRESHOLD)
  • is any agent producing concerning patterns?
  • which HoF genomes are wasted and should be killed/pinned?
  • given current regime, is the deployed genome right for it?
  • is there a missed breed opportunity?

Outputs are emitted as ACT-level insights with the LLM's reasoning.
Actions that change state require human confirmation by default
(advisory mode) — the agent flips to autonomous=true via UI toggle.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from r_native.agents.base import Agent, emit_insight, get_recent_insights
from r_native.agents.llm import ask, extract_json


STRATEGIST_STATE = Path(r"C:\Users\Radhi\MT5\data\r_native\agents\strategist_state.json")


SYSTEM_PROMPT = """You are the chief strategist for an automated genetic
algorithm trading system called R Native. The system runs perpetually,
evolving genomes (parameter combinations) via GA and trading the best
ones live on MT5.

You are advisor to a network of specialized agents:
  • risk_sentinel — guards drawdown + kills runaway losers
  • genome_curator — pins stars + prunes dead weight in Hall of Fame
  • market_reader — swaps deployed genome based on market regime
  • performance_auditor — generates audit reports

You make HIGH-LEVEL strategic recommendations. You DO NOT execute trades.
Your output is a JSON object with this exact structure:

{
  "assessment": "brief overall read of the system in one sentence",
  "concerns":   ["specific concern 1", "concern 2"],
  "opportunities": ["specific opportunity 1"],
  "recommendations": [
    {"action": "tune_threshold", "agent": "X", "param": "Y", "from": V, "to": V2, "reason": "..."},
    {"action": "breed_pair",     "symbol": "BTCUSDm", "parent_a": "ID1", "parent_b": "ID2", "reason": "..."},
    {"action": "kill_genome",    "id": "ID", "reason": "..."},
    {"action": "pin_genome",     "id": "ID", "reason": "..."},
    {"action": "investigate",    "topic": "...", "reason": "..."}
  ],
  "confidence": "low" | "medium" | "high"
}

Keep recommendations actionable and specific — cite genome IDs, agent
names, numeric thresholds. NO empty fluff. If nothing needs attention,
return empty arrays. Limit to 5 total recommendations max.
"""


class LLMStrategist(Agent):
    name = "llm_strategist"
    description = "LLM-powered strategic advisor (Ollama qwen2.5 / Claude)"
    interval_seconds = 900     # 15 minutes
    default_enabled = True

    def __init__(self):
        super().__init__()
        self._autonomous = False  # advisory mode by default

    def _gather_snapshot(self) -> dict:
        """Build a compact snapshot of the system for the LLM."""
        snap = {"now": datetime.now(timezone.utc).isoformat()}
        # Account
        try:
            import urllib.request as _u
            with _u.urlopen("http://127.0.0.1:5055/api/account", timeout=3) as r:
                acct = json.loads(r.read().decode())
            account = acct.get("account") or {}
            r_attr  = next((a for a in acct.get("attribution_by_magic") or []
                            if a.get("magic") == 20260605), {})
            snap["account"] = {
                "balance": account.get("balance"),
                "equity":  account.get("equity"),
                "open_pl": acct.get("open_pnl"),
                "open_positions": acct.get("positions_count"),
            }
            snap["r_today"] = {
                "trades":   r_attr.get("trades"),
                "win_rate": r_attr.get("win_rate"),
                "net_pl":   r_attr.get("net_profit"),
            }
        except Exception as e:
            snap["account_error"] = str(e)

        # Top HoF per symbol
        try:
            from r_native.hall_of_fame import load_symbol, load_pinned, load_index
            pinned = load_pinned()
            snap["hof"] = {
                "total":   len(load_index()),
                "pinned":  len(pinned),
                "by_symbol": {},
            }
            for sym in ("BTCUSDm", "XAUUSDm"):
                lst = load_symbol(sym)[:5]
                snap["hof"]["by_symbol"][sym] = [
                    {"id": e["id"], "nickname": e.get("nickname"),
                     "score": e.get("score"),
                     "live_pnl": e.get("live_pnl"),
                     "live_trades": e.get("live_trades"),
                     "pinned": e.get("id") in pinned,
                     "killed": e.get("killed"),
                     "wr": (e.get("stats") or {}).get("win_rate"),
                     "pf": (e.get("stats") or {}).get("profit_factor"),
                    } for e in lst
                ]
        except Exception as e:
            snap["hof_error"] = str(e)

        # Currently deployed per symbol
        try:
            cfg_dir = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
            snap["deployed"] = {}
            for p in cfg_dir.glob("*.json"):
                cfg = json.loads(p.read_text(encoding="utf-8"))
                g = cfg.get("deployed_genome") or {}
                snap["deployed"][p.stem] = {
                    "id": g.get("id"),
                    "score": g.get("score"),
                    "session": f"{g.get('start_hour')}-{g.get('end_hour')}h",
                    "tradeable": cfg.get("tradeable"),
                }
        except Exception as e:
            snap["deployed_error"] = str(e)

        # Trade gate status
        try:
            import urllib.request as _u
            with _u.urlopen("http://127.0.0.1:5055/api/r/trade_gate?symbol=BTCUSDm",
                            timeout=3) as r:
                snap["gate_btc"] = json.loads(r.read().decode())
        except Exception: pass

        # Auto-evo status
        try:
            import urllib.request as _u
            with _u.urlopen("http://127.0.0.1:5055/api/r/auto_evo/status",
                            timeout=3) as r:
                snap["auto_evo"] = json.loads(r.read().decode())
        except Exception: pass

        # Recent ACT-level insights from other agents (signals worth knowing)
        try:
            acts = get_recent_insights(n=20, level="ACT")
            snap["recent_actions"] = [
                {"ts": a["ts"], "agent": a["agent"],
                 "msg": a["message"]}
                for a in acts
            ]
        except Exception: pass

        # Agent health
        try:
            import urllib.request as _u
            with _u.urlopen("http://127.0.0.1:5055/api/r/agents/list",
                            timeout=3) as r:
                agents = json.loads(r.read().decode())
            snap["agents_health"] = [
                {"name": a["name"], "enabled": a["enabled"],
                 "alive": a["thread_alive"],
                 "ticks": a["tick_count"], "errors": a["error_count"],
                 "last_error": a.get("last_error")}
                for a in agents.get("agents", [])
            ]
        except Exception: pass

        return snap

    def _apply_recommendation(self, rec: dict) -> str:
        """Apply a recommendation if in autonomous mode. Returns status."""
        if not self._autonomous:
            return "advisory_only"
        action = rec.get("action")
        try:
            if action == "kill_genome":
                from r_native.hall_of_fame import kill
                gid = rec.get("id")
                if gid and kill(gid, rec.get("reason", "LLM strategist")):
                    return "killed"
                return "kill_failed"
            elif action == "pin_genome":
                from r_native.hall_of_fame import pin
                gid = rec.get("id")
                if gid and pin(gid):
                    return "pinned"
                return "pin_failed"
            # tune_threshold + breed_pair require deeper integration —
            # for now they remain advisory
            return "no_handler"
        except Exception as e:
            return f"error: {e}"

    def tick(self):
        snap = self._gather_snapshot()

        # Build compact JSON for the LLM (limit size)
        snap_for_llm = json.dumps(snap, ensure_ascii=False, indent=2)
        if len(snap_for_llm) > 6000:
            snap_for_llm = snap_for_llm[:6000] + "\n…(truncated)"

        prompt = (
            f"Current system snapshot:\n```json\n{snap_for_llm}\n```\n\n"
            f"Analyze this snapshot. Provide JSON response per the format "
            f"in your system prompt. Be concrete and cite real IDs/values "
            f"from the data above."
        )

        # Use llama3.1:8b — better at structured reasoning than qwen for this
        result = ask(prompt, system=SYSTEM_PROMPT,
                     preferred_backend="ollama",
                     model="llama3.1:8b",
                     temperature=0.3)
        if not result.get("ok"):
            from r_native.agents.llm import last_error
            emit_insight(self.name, "WARN",
                         f"LLM unavailable: {result.get('error')} · "
                         f"ollama_last_error: {last_error()}")
            return

        text = result["text"]
        backend = result["backend"]
        model   = result["model"]
        parsed = extract_json(text)

        if not parsed:
            # No JSON — log the raw response anyway (could be useful)
            emit_insight(self.name, "INFO",
                f"💭 LLM ({backend}/{model}): {text[:280]}…"
                if len(text) > 280 else f"💭 LLM ({backend}/{model}): {text}",
                data={"raw": text[:2000]})
            return

        assessment = parsed.get("assessment", "")
        concerns        = parsed.get("concerns", []) or []
        opportunities   = parsed.get("opportunities", []) or []
        recommendations = parsed.get("recommendations", []) or []
        confidence      = parsed.get("confidence", "medium")

        # Emit a summary insight
        emit_insight(self.name, "INFO",
            f"🧠 [{confidence}] {assessment}",
            data={"backend": backend, "model": model,
                  "concerns": concerns,
                  "opportunities": opportunities,
                  "recommendations": recommendations})

        # Emit each recommendation as its own ACT-level insight
        for rec in recommendations[:5]:
            status = self._apply_recommendation(rec)
            level = "ACT" if status not in ("advisory_only", "no_handler") else "INFO"
            action = rec.get("action", "?")
            reason = (rec.get("reason") or "")[:160]
            emit_insight(self.name, level,
                f"💡 {action}: {reason} [{status}]",
                data=rec,
                action=action if level == "ACT" else None)

        # Save state for UI
        try:
            STRATEGIST_STATE.parent.mkdir(parents=True, exist_ok=True)
            STRATEGIST_STATE.write_text(json.dumps({
                "last_run": datetime.now(timezone.utc).isoformat(),
                "backend":  backend, "model": model,
                "assessment": assessment, "confidence": confidence,
                "concerns": concerns, "opportunities": opportunities,
                "recommendations": recommendations,
                "autonomous": self._autonomous,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception: pass

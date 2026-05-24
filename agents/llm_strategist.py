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

CRITICAL SCORING SCALE (read carefully — system has guardrails that
will REJECT recommendations violating these):
  • Genome scores in this system range roughly 0-80
  • score >= 60 = strong (auto-pin candidate)
  • score 30-60 = average (keep, observe)
  • score < 30  = weak (kill candidate)
  • NEVER recommend killing a genome scoring above 30
  • NEVER recommend pinning a genome scoring below 50
  • For breed_pair, BOTH parents must score above 25

When you see "low score 62.5" — that is NOT low, it is HIGH (top 10%).
The system top is typically 70-75. Don't kill medium/high scorers.

BREEDING DISCIPLINE:
The snapshot includes a `breeding_history` field with `recent_5` past
crosses + their outcomes (SUCCESS / MEDIOCRE / FAILED). Before
recommending a new breed_pair:
  • LOOK at recent_5 — if a specific parent has produced 2+ FAILED
    children recently, DO NOT pick it again as a parent
  • If the SAME pair has already been bred (check parents list), don't
    repeat — variations of the same cross tend to fail similarly
  • Prefer parents whose past breeds SUCCEEDED, or pairs never tried
  • If success_rate_pct is below 30, propose KILL recommendations
    instead of more breeds — the gene pool may need cleanup first
"""


class LLMStrategist(Agent):
    name = "llm_strategist"
    description = "LLM-powered strategic advisor (Ollama qwen2.5 / Claude)"
    interval_seconds = 900     # 15 minutes
    default_enabled = True

    AUTONOMOUS_STATE = Path(r"C:\Users\Radhi\MT5\data\r_native\agents\strategist_autonomous.flag")

    def __init__(self):
        super().__init__()
        # Read autonomous flag from disk so it survives restarts
        self._autonomous = self.AUTONOMOUS_STATE.exists()

    def set_autonomous(self, on: bool) -> bool:
        self._autonomous = bool(on)
        try:
            self.AUTONOMOUS_STATE.parent.mkdir(parents=True, exist_ok=True)
            if on:
                self.AUTONOMOUS_STATE.write_text("autonomous", encoding="utf-8")
            elif self.AUTONOMOUS_STATE.exists():
                self.AUTONOMOUS_STATE.unlink()
        except Exception: pass
        emit_insight(self.name, "INFO",
            f"autonomous mode {'ON — will apply pin/kill/breed' if on else 'OFF (advisory only)'}")
        return self._autonomous

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

        # Breeding history summary — let the LLM learn from past outcomes
        # so it doesn't suggest the same losing crosses repeatedly
        try:
            from r_native.hall_of_fame import load_index
            idx = load_index()
            breeds = [g for g in idx.values()
                      if (g.get("birth_method") or "").startswith("crossover")
                      and g.get("parents")]
            success = [b for b in breeds if b.get("score", 0) >= 30]
            failed  = [b for b in breeds if b.get("score", 0) < 15]
            snap["breeding_history"] = {
                "total_attempts":   len(breeds),
                "successful":       len(success),
                "failed":           len(failed),
                "success_rate_pct": round(len(success) / max(1, len(breeds)) * 100, 1),
                "best_breed": ({
                    "child":   max(success, key=lambda g: g.get("score", 0)).get("nickname"),
                    "score":   max(success, key=lambda g: g.get("score", 0)).get("score"),
                    "parents": max(success, key=lambda g: g.get("score", 0)).get("parents"),
                } if success else None),
                "recent_5": [
                    {"child":   b.get("id"),
                     "parents": b.get("parents"),
                     "score":   round(b.get("score", 0), 1),
                     "verdict": ("SUCCESS" if b.get("score", 0) >= 30
                                  else ("FAILED" if b.get("score", 0) < 15
                                        else "MEDIOCRE"))}
                    for b in sorted(breeds, key=lambda g: g.get("born_at", ""),
                                    reverse=True)[:5]
                ],
            }
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

    # Safety guardrails — protect HoF from LLM mistakes in autonomous mode
    KILL_SCORE_CEILING   = 30.0   # never kill anything scoring above this
    PIN_SCORE_FLOOR      = 50.0   # never pin anything scoring below this
    BREED_PARENT_MIN     = 25.0   # parents must each score above this to breed

    def _apply_recommendation(self, rec: dict) -> str:
        """Apply a recommendation if in autonomous mode. Returns status.
        Guardrails block the LLM from destructive misreads (it once
        called a 62.5 genome "low-scoring" and killed it — never again)."""
        if not self._autonomous:
            return "advisory_only"
        action = rec.get("action")
        try:
            if action == "kill_genome":
                from r_native.hall_of_fame import kill, load_index, is_deployed_anywhere
                gid = rec.get("id")
                if not gid: return "kill_no_id"
                entry = load_index().get(gid)
                if not entry: return f"kill_unknown_id_{gid}"
                score = float(entry.get("score") or 0)
                if score > self.KILL_SCORE_CEILING:
                    emit_insight(self.name, "WARN",
                        f"🛡 blocked LLM kill of {gid} (score {score:.1f} > "
                        f"safety ceiling {self.KILL_SCORE_CEILING})")
                    return f"blocked_score_{score:.1f}"
                if entry.get("pinned"):
                    return "blocked_pinned"
                deployed_on = is_deployed_anywhere(gid)
                if deployed_on:
                    emit_insight(self.name, "WARN",
                        f"🛡 blocked LLM kill of {gid} — currently deployed "
                        f"on {deployed_on}")
                    return f"blocked_deployed_{deployed_on}"
                if kill(gid, rec.get("reason", "LLM strategist")):
                    return f"killed_score{score:.1f}"
                return "kill_failed"
            elif action == "pin_genome":
                from r_native.hall_of_fame import pin, load_index
                gid = rec.get("id")
                if not gid: return "pin_no_id"
                entry = load_index().get(gid)
                if not entry: return f"pin_unknown_id_{gid}"
                score = float(entry.get("score") or 0)
                if score < self.PIN_SCORE_FLOOR:
                    emit_insight(self.name, "WARN",
                        f"🛡 blocked LLM pin of {gid} (score {score:.1f} < "
                        f"safety floor {self.PIN_SCORE_FLOOR})")
                    return f"blocked_score_{score:.1f}"
                if pin(gid):
                    return f"pinned_score{score:.1f}"
                return "pin_failed"
            elif action == "breed_pair":
                from r_native.breeder import breed_and_admit
                from r_native.hall_of_fame import load_index, load_symbol
                sym = rec.get("symbol", "BTCUSDm")
                pa  = rec.get("parent_a")
                pb  = rec.get("parent_b")
                index = load_index()
                # Default to top-2 if LLM didn't cite specific parents
                if not (pa and pb):
                    top = load_symbol(sym)[:2]
                    if len(top) < 2: return "breed_no_parents"
                    pa, pb = top[0]["id"], top[1]["id"]
                # Validate both parents exist + score above breeding floor
                for tag, gid in (("a", pa), ("b", pb)):
                    ent = index.get(gid)
                    if not ent: return f"breed_unknown_parent_{tag}_{gid}"
                    s = float(ent.get("score") or 0)
                    if s < self.BREED_PARENT_MIN:
                        emit_insight(self.name, "WARN",
                            f"🛡 blocked breed: parent_{tag} {gid} score "
                            f"{s:.1f} < floor {self.BREED_PARENT_MIN}")
                        return f"blocked_parent_{tag}_score_{s:.1f}"
                result = breed_and_admit(sym, pa, pb)
                if result.get("ok"):
                    return f"bred_{result['child_id']}_score{result['score']:.1f}"
                return f"breed_failed: {result.get('reason')}"
            # tune_threshold still advisory — needs careful per-agent integration
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

"""agents/performance_coach.py — analyze per-genome flag effectiveness.

Every hour, looks at each competitor genome's live PnL + per-side WR and
proposes mutations:
  • Genome X has 10 trades, 2 wins → suggest mutating its filter set
  • Genome Y profitable on BUY only → flag it as "BUY-specialist"
  • Genome Z hasn't fired in 4h → its flag combination is too restrictive

Output is advisory (insights), not action — the user / LLM Strategist
can act on these recommendations.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


class PerformanceCoach(Agent):
    name = "performance_coach"
    description = "Analyzes per-genome flag effectiveness, proposes mutations"
    interval_seconds = 3600    # hourly
    default_enabled = True

    MIN_TRADES_FOR_VERDICT = 5

    def tick(self):
        try:
            from r_native.hall_of_fame import load_index
            idx = load_index()
        except Exception: return

        # Find all genomes that have live trades
        comp = []
        for gid, g in idx.items():
            n = int(g.get("live_trades") or 0)
            if n < self.MIN_TRADES_FOR_VERDICT: continue
            pl = float(g.get("live_pnl") or 0)
            avg = pl / max(1, n)
            flags = g.get("all_params", {}).get("flags", {}) or {}
            sig_count = sum(1 for k,v in flags.items() if v and k.startswith("use_sig_"))
            comp.append({
                "id": gid, "nickname": g.get("nickname", "?")[:40],
                "live_trades": n, "live_pnl": round(pl, 2),
                "avg_per_trade": round(avg, 3),
                "score_backtest": float(g.get("score") or 0),
                "signals_on": sig_count,
            })

        if not comp:
            return

        comp.sort(key=lambda x: -x["live_pnl"])
        winners = [c for c in comp if c["live_pnl"] > 0]
        losers  = [c for c in comp if c["live_pnl"] < 0]

        # Headline insight
        emit_insight(self.name, "INFO",
            f"📊 hourly coach: {len(winners)} winners, {len(losers)} losers across "
            f"{len(comp)} active genomes (min {self.MIN_TRADES_FOR_VERDICT}t each)",
            data={"top": comp[:3], "bottom": comp[-3:]})

        # Per-genome recommendations
        for c in comp:
            if c["live_pnl"] < -5 and c["live_trades"] >= 10:
                emit_insight(self.name, "WARN",
                    f"💀 {c['id']} ({c['nickname']}): {c['live_trades']}t, ${c['live_pnl']:+.2f} "
                    f"= ${c['avg_per_trade']:+.3f}/trade — recommend KILL or full re-breed",
                    data={"verdict": "kill_candidate", **c})
            elif c["live_pnl"] > 5 and c["live_trades"] >= 10:
                emit_insight(self.name, "ACT",
                    f"🏆 {c['id']} ({c['nickname']}): {c['live_trades']}t, ${c['live_pnl']:+.2f} "
                    f"= ${c['avg_per_trade']:+.3f}/trade — recommend PIN + use as breeder parent",
                    data={"verdict": "pin_candidate", **c},
                    action="performance_winner")

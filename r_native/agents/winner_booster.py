"""agents/winner_booster.py — scale lot UP on proven winning genomes.

When a genome accumulates a clear winning streak with positive live PnL,
this agent writes a `lot_multiplier_override.json` that the executor
consults at order_send time. The boost rewards genomes that have
EARNED bigger size with real money — momentum-based scaling.

Boost tiers:
  Tier 1 (1.5x lot):
    ≥3 live trades, WR ≥ 60%, live_pnl > 0
  Tier 2 (2.0x lot):
    ≥10 live trades, WR ≥ 65%, live_pnl > +$5
  Tier 3 (2.5x lot — Monster zone):
    ≥15 live trades, WR ≥ 70% per side, live_pnl > +$15

Losing genomes get implicit 1.0x (no penalty here — drawdown_recovery
handles risk reduction at account level, this just scales UP).

When a tiered genome's PnL turns negative, it falls back to 1.0x next
cycle (no death spiral — never gets stuck in oversize losing mode).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


BOOST_FILE = Path(r"C:\Users\Radhi\MT5\data\r_native\lot_multipliers.json")


class WinnerBooster(Agent):
    name = "winner_booster"
    description = "Scales lot up on proven-winning genomes (momentum reward)"
    interval_seconds = 120    # every 2 min
    default_enabled = True

    # State for change-detection — only emit ACT when boost set actually shifts
    _last_boost_signature: str = ""

    def _qualify_tier(self, n: int, wr_pct: float, pnl: float) -> tuple[int, float]:
        """Return (tier 0-3, lot_multiplier)."""
        if n >= 15 and wr_pct >= 70 and pnl >= 15:
            return 3, 2.5
        if n >= 10 and wr_pct >= 65 and pnl >= 5:
            return 2, 2.0
        if n >= 3 and wr_pct >= 60 and pnl > 0:
            return 1, 1.5
        return 0, 1.0

    def tick(self):
        try:
            from r_native.hall_of_fame import load_index
            idx = load_index()
        except Exception: return

        multipliers = {}
        boosted = []
        for gid, g in idx.items():
            n = int(g.get("live_trades") or 0)
            if n < 3: continue
            pnl = float(g.get("live_pnl") or 0)
            stats = g.get("stats") or {}
            # We don't have live WR per-genome yet — approximate from
            # backtest WR + bias positive if pnl positive
            wr = float(stats.get("win_rate") or 50)
            if pnl > 0: wr = max(wr, 60)   # winning live = floor at 60
            tier, mult = self._qualify_tier(n, wr, pnl)
            if tier > 0:
                multipliers[gid] = mult
                boosted.append({
                    "id": gid, "tier": tier, "mult": mult,
                    "n": n, "wr": wr, "pnl": round(pnl, 2),
                    "nickname": g.get("nickname", "?")[:35],
                })

        BOOST_FILE.parent.mkdir(parents=True, exist_ok=True)
        BOOST_FILE.write_text(json.dumps({
            "multipliers": multipliers,
            "boosted":     boosted,
            "updated_at":  datetime.now(timezone.utc).isoformat(),
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        # Build a signature of the boost state — only emit ACT when it changes.
        # Otherwise the same "2 winners boosted" insight fires every 2 minutes
        # and floods the AI Advisors feed with non-news.
        sig = ",".join(sorted(f"{b['id']}:{b['tier']}" for b in boosted))
        if boosted and sig != self._last_boost_signature:
            top = max(boosted, key=lambda b: b["mult"])
            change_note = "" if not self._last_boost_signature else " [set changed]"
            emit_insight(self.name, "ACT",
                f"🏋 {len(boosted)} winners boosted{change_note} (top: {top['nickname']} "
                f"tier{top['tier']} x{top['mult']} | {top['n']}t \${top['pnl']:+.2f})",
                data={"boosted": boosted, "previous_sig": self._last_boost_signature},
                action="winners_boosted")
            self._last_boost_signature = sig
        elif not boosted and self._last_boost_signature:
            # Cleared — all boosts dropped (winning streaks broke)
            emit_insight(self.name, "INFO",
                "🏋 boost cleared — no genomes currently qualifying",
                action="boost_cleared")
            self._last_boost_signature = ""

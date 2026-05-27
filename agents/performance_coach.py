"""agents/performance_coach.py — analyze per-genome live performance.

Every hour, looks at each competitor genome's live PnL and per-side WR.
Pre-cycle-39 behaviour was advisory-only — it screamed "KILL X" for
hours while LLM_strategist's score-based safety ceiling blocked the
kill (live PnL ≠ backtest score; a genome can backtest 80 and live
at -$5/trade). Two agents disagreed, nothing happened, account bled.

Cycle-39 change: performance_coach now ACTS on overwhelming live
evidence. When a genome has ≥15 live trades AND avg ≤ -$0.20/trade
(or ≥10 trades and avg ≤ -$0.40/trade) it is HARD-RETIRED:
  1. Evicted from every symbol's competitor list (via
     streak_detector's eviction helper)
  2. Killed in the HoF
  3. Sweep pass: removes ALL already-killed genomes from any
     competitor list that still references them (BCD286 was killed
     but still sitting in 4 USDCHF/USDJPY/GBPUSD/XAGUSD competitor
     slots — same dead weight bug).

Pinned genomes are still untouchable. Currently-deployed PRIMARY
slots are too — we evict from competitors only, and only kill if
not deployed anywhere.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


SYMBOL_CFG_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")


def _evict_from_competitors(gid: str) -> list[str]:
    """Remove genome from every symbol's competitor list. Returns the
    list of symbols touched. Never evicts from the PRIMARY slot — that's
    auto_rotator's responsibility. Atomic per-file (tmp+rename)."""
    touched = []
    if not SYMBOL_CFG_DIR.exists(): return touched
    for f in SYMBOL_CFG_DIR.glob("*.json"):
        try:
            cfg = json.loads(f.read_text(encoding="utf-8"))
        except Exception: continue
        # Don't touch primary slot
        if (cfg.get("deployed_genome") or {}).get("id") == gid:
            continue
        comps = cfg.get("competitors") or []
        new_comps = [c for c in comps
                      if (c.get("id") if isinstance(c, dict) else c) != gid]
        if len(new_comps) != len(comps):
            cfg["competitors"] = new_comps
            tmp = f.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            tmp.replace(f)
            touched.append(f.stem)
    return touched


def _is_primary_anywhere(gid: str) -> str | None:
    if not SYMBOL_CFG_DIR.exists(): return None
    for f in SYMBOL_CFG_DIR.glob("*.json"):
        try:
            cfg = json.loads(f.read_text(encoding="utf-8"))
            if (cfg.get("deployed_genome") or {}).get("id") == gid:
                return f.stem
        except Exception: continue
    return None


class PerformanceCoach(Agent):
    name = "performance_coach"
    description = "Live-PnL-based genome retirement (evict + kill, bypasses score ceiling)"
    interval_seconds = 3600    # hourly
    default_enabled = True

    MIN_TRADES_FOR_VERDICT = 5
    # Hard-retire thresholds — overwhelming live evidence beats backtest score
    HARD_RETIRE_MIN_TRADES_A = 15      # gentler tier
    HARD_RETIRE_AVG_LOSS_A   = -0.20   # $/trade
    HARD_RETIRE_MIN_TRADES_B = 10      # stricter tier
    HARD_RETIRE_AVG_LOSS_B   = -0.40   # $/trade

    # Per-cycle dedup so we don't spam the same kill insight every hour
    _last_killed_this_session: set[str] = set()

    def _hard_retire(self, gid: str, nickname: str, n: int, pl: float, avg: float):
        """Evict from competitors + try to kill. Returns True if killed."""
        if gid in self._last_killed_this_session:
            return False
        primary_on = _is_primary_anywhere(gid)
        if primary_on:
            emit_insight(self.name, "WARN",
                f"⚠ {gid} ({nickname}) is PRIMARY on {primary_on} — auto_rotator "
                f"must demote first. live={n}t ${pl:+.2f} avg ${avg:+.3f}/t")
            return False
        touched = _evict_from_competitors(gid)
        try:
            from r_native.hall_of_fame import kill as hof_kill
            ok = hof_kill(gid, reason=f"performance_coach: {n}t live, "
                                       f"${pl:+.2f} pnl, ${avg:+.3f}/trade")
        except Exception as e:
            emit_insight(self.name, "WARN",
                f"hof.kill failed for {gid}: {e}")
            return False
        if ok:
            self._last_killed_this_session.add(gid)
            emit_insight(self.name, "ACT",
                f"💀 HARD-RETIRED {gid} ({nickname}): {n}t ${pl:+.2f} "
                f"(${avg:+.3f}/t). Evicted from {len(touched)} symbols: "
                f"{', '.join(touched) if touched else '(none)'}. Killed in HoF.",
                data={"gid": gid, "trades": n, "pnl": pl, "avg": avg,
                       "evicted_from": touched},
                action="hard_retire")
            return True
        return False

    def _sweep_stale_killed_competitors(self) -> int:
        """One-shot cleanup: remove already-killed genomes from any
        competitor list that still references them (the BCD286 bug —
        killed but still in 4 USDCHF/USDJPY/GBPUSD/XAGUSD competitor
        slots wasting routing cycles)."""
        try:
            from r_native.hall_of_fame import load_index
            idx = load_index()
        except Exception: return 0
        dead_ids = {gid for gid, g in idx.items() if g.get("killed")}
        if not dead_ids: return 0
        touched = 0
        for f in SYMBOL_CFG_DIR.glob("*.json"):
            try:
                cfg = json.loads(f.read_text(encoding="utf-8"))
            except Exception: continue
            if (cfg.get("deployed_genome") or {}).get("id") in dead_ids:
                continue   # don't touch primary even if marked killed
            comps = cfg.get("competitors") or []
            new_comps = [c for c in comps
                          if (c.get("id") if isinstance(c, dict) else c) not in dead_ids]
            if len(new_comps) != len(comps):
                cfg["competitors"] = new_comps
                tmp = f.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                                encoding="utf-8")
                tmp.replace(f)
                touched += 1
        if touched > 0:
            emit_insight(self.name, "ACT",
                f"🧹 swept stale killed-genome refs from {touched} "
                f"symbol configs ({len(dead_ids)} killed genomes total)",
                action="sweep_killed_refs")
        return touched

    def tick(self):
        try:
            from r_native.hall_of_fame import load_index
            idx = load_index()
        except Exception: return

        # First pass: clean up already-killed competitors
        self._sweep_stale_killed_competitors()

        # Find all genomes that have live trades
        comp = []
        for gid, g in idx.items():
            if g.get("killed"): continue
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

        emit_insight(self.name, "INFO",
            f"📊 hourly coach: {len(winners)} winners, {len(losers)} losers across "
            f"{len(comp)} active genomes (min {self.MIN_TRADES_FOR_VERDICT}t each)",
            data={"top": comp[:3], "bottom": comp[-3:]})

        # Per-genome action
        for c in comp:
            gid = c["id"]; n = c["live_trades"]; pl = c["live_pnl"]; avg = c["avg_per_trade"]
            nick = c["nickname"]

            # HARD-RETIRE tier (overwhelming evidence)
            hard_retire = (
                (n >= self.HARD_RETIRE_MIN_TRADES_A and avg <= self.HARD_RETIRE_AVG_LOSS_A) or
                (n >= self.HARD_RETIRE_MIN_TRADES_B and avg <= self.HARD_RETIRE_AVG_LOSS_B)
            )
            if hard_retire:
                self._hard_retire(gid, nick, n, pl, avg)
                continue

            # Soft WARN tier (kept for visibility, but no longer spamming
            # without action — once n hits HARD_RETIRE_MIN it WILL act)
            if pl < -3 and n >= 7:
                emit_insight(self.name, "WARN",
                    f"⚠ {gid} ({nick}): {n}t ${pl:+.2f} (${avg:+.3f}/t) — "
                    f"approaching hard-retire threshold")
            elif pl > 5 and n >= 10:
                emit_insight(self.name, "ACT",
                    f"🏆 {gid} ({nick}): {n}t ${pl:+.2f} (${avg:+.3f}/t) — "
                    f"recommend PIN + use as breeder parent",
                    data={"verdict": "pin_candidate", **c},
                    action="performance_winner")

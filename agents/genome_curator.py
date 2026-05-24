"""agents/genome_curator.py — Hall of Fame caretaker.

Periodically (every 30 min) reviews the HoF and:
  • auto-pins stars: alive genomes with score ≥ 70 AND live PF ≥ 1.5
  • surfaces breeding candidates: complementary top genomes (different
    archetypes / hour patterns) that should be crossed
  • prunes obvious dead weight (score < 15, no deployments, no live trades)
  • detects "regressions" — was-deployed genomes whose live ≠ backtest
  • posts a daily summary to insight stream

Acts directly via hall_of_fame.pin() / kill().
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from r_native.agents.base import Agent, emit_insight


class GenomeCurator(Agent):
    name = "genome_curator"
    description = "Hall of Fame caretaker — pins stars, prunes dead weight, suggests breeds"
    interval_seconds = 1800   # 30 minutes
    default_enabled = True

    AUTO_PIN_SCORE_THRESHOLD = 70.0
    PRUNE_SCORE_THRESHOLD    = 15.0
    PRUNE_AGE_DAYS           = 3
    # Failed breeds: bred genome that scored <15 — already proven bad,
    # no need to wait 3 days. Prune after 30 min so HoF stays clean.
    BREED_FAILURE_AGE_HOURS  = 0.5
    BREED_FAILURE_SCORE      = 15.0
    REGRESSION_THRESHOLD_PCT = 50.0   # live underperforms backtest by 50%+

    def tick(self):
        try:
            from r_native.hall_of_fame import (
                load_index, load_pinned, pin, kill, get_elites,
            )
        except Exception as e:
            emit_insight(self.name, "WARN", f"HoF import failed: {e}")
            return

        index   = load_index()
        pinned  = set(load_pinned())
        if not index:
            return

        now = datetime.now(timezone.utc)
        pinned_now = 0
        pruned_now = 0
        regressions = []
        breed_candidates_by_symbol: dict[str, list] = {}

        for gid, entry in index.items():
            if entry.get("killed"): continue
            score = float(entry.get("score") or 0)
            symbol = entry.get("symbol", "?")
            born_at = entry.get("born_at", "")
            age_days = 99
            try:
                born = datetime.fromisoformat(born_at.replace("Z","+00:00"))
                age_days = (now - born).total_seconds() / 86400
            except Exception: pass
            live_pl     = float(entry.get("live_pnl") or 0)
            live_trades = int(entry.get("live_trades") or 0)
            deployments = entry.get("deployments") or []

            # ── 1. Auto-pin stars ──
            if (gid not in pinned
                and score >= self.AUTO_PIN_SCORE_THRESHOLD
                and (live_trades == 0 or live_pl >= 0)):
                if pin(gid):
                    pinned_now += 1
                    emit_insight(self.name, "ACT",
                        f"📌 auto-pinned {entry.get('nickname', gid)} "
                        f"(score {score:.1f})",
                        data={"id": gid, "score": score, "symbol": symbol},
                        action="genome_pinned")

            # ── 2. Prune dead weight (old + low score + never deployed) ──
            if (gid not in pinned
                and score < self.PRUNE_SCORE_THRESHOLD
                and age_days >= self.PRUNE_AGE_DAYS
                and not deployments
                and live_trades == 0):
                if kill(gid, f"low score {score:.1f}, age {age_days:.1f}d, never deployed"):
                    pruned_now += 1

            # ── 2b. Fast-prune failed breeds (already proven bad — no wait) ──
            birth = entry.get("birth_method", "")
            if (gid not in pinned
                and birth.startswith("crossover")
                and score < self.BREED_FAILURE_SCORE
                and age_days * 24 >= self.BREED_FAILURE_AGE_HOURS
                and not deployments
                and live_trades == 0):
                if kill(gid, f"failed breed: score {score:.1f} < {self.BREED_FAILURE_SCORE}"):
                    pruned_now += 1
                    emit_insight(self.name, "ACT",
                        f"🪦 fast-pruned failed breed {entry.get('nickname', gid)} "
                        f"(score {score:.1f})",
                        data={"id": gid, "score": score, "birth": birth},
                        action="genome_killed")

            # ── 3. Detect regressions (live underperforms backtest badly) ──
            if live_trades >= 5 and deployments:
                # Backtest expected return per trade
                stats = entry.get("stats") or {}
                avg_win  = float(stats.get("avg_win") or 0)
                wr_pct   = float(stats.get("win_rate") or 0)
                expected_per_trade = (
                    avg_win * wr_pct/100
                    + float(stats.get("avg_loss") or 0) * (1 - wr_pct/100))
                actual_per_trade = live_pl / live_trades
                if expected_per_trade > 0.10:
                    drop_pct = (1 - actual_per_trade / expected_per_trade) * 100
                    if drop_pct >= self.REGRESSION_THRESHOLD_PCT:
                        regressions.append({
                            "id": gid, "nickname": entry.get("nickname"),
                            "symbol": symbol,
                            "expected_per_trade": expected_per_trade,
                            "actual_per_trade":   actual_per_trade,
                            "drop_pct":           drop_pct,
                        })

            # ── 4. Build breeding pool per symbol (only top picks) ──
            if score >= 50 and entry.get("all_params"):
                breed_candidates_by_symbol.setdefault(symbol, []).append({
                    "id": gid, "score": score,
                    "nickname": entry.get("nickname"),
                    "active_genes": entry.get("active_genes") or [],
                })

        # ── 5. Report breeding suggestions ──
        for sym, candidates in breed_candidates_by_symbol.items():
            if len(candidates) < 2: continue
            # Sort by score, suggest top1 × top2 if their gene sets differ enough
            candidates.sort(key=lambda c: c["score"], reverse=True)
            a, b = candidates[0], candidates[1]
            overlap = len(set(a["active_genes"]) & set(b["active_genes"]))
            total = len(set(a["active_genes"]) | set(b["active_genes"])) or 1
            similarity = overlap / total
            if similarity < 0.7:  # different enough to be interesting
                emit_insight(self.name, "INFO",
                    f"🧬 breed candidate {sym}: "
                    f"{a['nickname']} × {b['nickname']} "
                    f"(similarity {similarity:.0%})",
                    data={"sym": sym, "parent_a": a["id"], "parent_b": b["id"],
                          "similarity": similarity})

        # ── 6. Regression alerts ──
        for r in regressions:
            emit_insight(self.name, "WARN",
                f"📉 regression: {r['nickname']} live "
                f"{r['actual_per_trade']:+.2f}/trade vs "
                f"{r['expected_per_trade']:+.2f} expected ({r['drop_pct']:.0f}% drop)",
                data=r)

        # ── 7. Summary ──
        if pinned_now or pruned_now:
            emit_insight(self.name, "INFO",
                f"sweep done · pinned={pinned_now} pruned={pruned_now} "
                f"regressions={len(regressions)} total={len(index)}")

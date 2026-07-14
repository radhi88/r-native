"""agents/auto_rotator.py — promote winning competitors, demote losers.

Each deployed symbol has a `deployed_genome` (the "primary" that the
executor consults for default decisions) and a `competitors` list (up
to 3 genomes that all trade in parallel on that symbol). Over time
their live P/L diverges.

This agent rebalances the deployment automatically every 30 min:

  For each symbol:
    primary = current deployed_genome.id
    rank competitors by live_pnl (need ≥3 live trades to qualify)
    if best competitor's live_pnl ≥ primary_pnl + ROTATE_EDGE_USD:
      SWAP primary ↔ best competitor
      record rotation in cfg["rotation_history"]
      emit ACT insight
      throttle: max 1 rotation per symbol per 6h

This is exactly what the user asked for: "كل عملة يحفظ لها جيناتها
ويطوره" — each symbol's genome line auto-evolves based on real money
performance. Backtest scores got us into the race; live P/L picks the
winner.

Safety:
  • Never rotates a pinned genome
  • Never rotates if primary has < MIN_PRIMARY_TRADES live trades
    (give it a fair shot first)
  • 6h cooldown per symbol prevents thrashing
  • Pure file write — executor picks up the new primary on next cycle
    (it reads symbol_configs every iteration)
  • Never touches a competitor that's already mid-trade
    (handled by the executor's exposure_guard separately)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


SYMBOL_CFG_DIR  = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")


class AutoRotator(Agent):
    name = "auto_rotator"
    description = "Promotes winning competitors to primary slot (per-symbol genome evolution)"
    interval_seconds = 1800   # every 30 min
    default_enabled = True

    # Rotation thresholds — conservative to avoid thrashing
    ROTATE_EDGE_USD       = 3.00   # competitor must beat primary by ≥$3
    MIN_PRIMARY_TRADES    = 5      # give primary a fair shot before evicting
    MIN_COMPETITOR_TRADES = 3      # competitor needs some sample too
    COOLDOWN_HOURS        = 6      # don't rotate same symbol twice in 6h

    # PUNT rule (cycle 16): when the primary is clearly bleeding but no
    # competitor has fired enough live trades to qualify the normal way,
    # take a calculated gamble and promote the top-scoring competitor.
    # This unblocks the auto-rotation when the executor consistently picks
    # the primary slot (starving competitors of trades).
    PUNT_PRIMARY_PNL_FLOOR   = -1.00   # primary losing ≥$1
    PUNT_PRIMARY_MIN_TRADES  = 3       # at least 3 trades to call it bleeding
    PUNT_COMP_MAX_SCORE_GAP  = 10.0    # competitor's backtest score within 10
                                        # of primary's (so we're not promoting
                                        # a clearly weaker genome blindly)

    # SCORE-promotion rule (cycle 23): when a competitor's BACKTEST score is
    # substantially higher than a non-pinned primary's, promote it directly.
    # The backtest is the only signal we have for genomes with no live data,
    # and a 15+ score gap reflects a meaningful quality difference (genome
    # scores in this system span 0-80, top 10% is 70+).
    # Examples: GBPJPYm primary 98ED3A (60.5) vs competitor scoring 76 →
    # promote. Doesn't touch pinned primaries (user/curator chose them).
    SCORE_PROMOTION_GAP      = 10.0    # competitor.score - primary.score ≥ 10
                                        # (realistic gap; pool spans ~60-80
                                        # so 15-pt gaps are rare)
    SCORE_PROMOTION_MIN      = 65.0    # competitor must score ≥65 too (so we
                                        # don't promote a 30-vs-15 candidate)

    def _load_hof(self) -> dict:
        try:
            from r_native.hall_of_fame import load_index
            return load_index() or {}
        except Exception:
            return {}

    def _can_rotate_symbol(self, cfg: dict) -> bool:
        """Cooldown check — was this symbol rotated recently?"""
        hist = cfg.get("rotation_history") or []
        if not hist: return True
        try:
            last = datetime.fromisoformat(hist[-1]["at"].replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - last) > timedelta(hours=self.COOLDOWN_HOURS)
        except Exception:
            return True

    def _genome_stats(self, hof: dict, gid: str) -> dict:
        g = hof.get(gid) or {}
        return {
            "id":     gid,
            "trades": int(g.get("live_trades") or 0),
            "pnl":    float(g.get("live_pnl") or 0),
            "wr":     float(g.get("live_wr_pct") or 0),
            "pinned": bool(g.get("pinned")),
            "killed": bool(g.get("killed")),
            "nick":   (g.get("nickname") or gid)[:35],
        }

    def tick(self):
        if not SYMBOL_CFG_DIR.exists():
            return
        hof = self._load_hof()
        if not hof:
            return

        rotations = []
        scanned = 0
        for path in SYMBOL_CFG_DIR.glob("*.json"):
            symbol = path.stem
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
            except Exception: continue

            primary_gid = (cfg.get("deployed_genome") or {}).get("id")
            if not primary_gid: continue
            competitors = cfg.get("competitors") or []
            if not isinstance(competitors, list): continue

            # ── Hygiene pass: primary shouldn't appear in its own competitors
            # list. Some legacy configs and seeder scripts left this state.
            # Quietly self-heal on every tick — no insight needed.
            cleaned_comps = [c for c in competitors
                              if (c.get("id") if isinstance(c, dict) else c) != primary_gid]
            if len(cleaned_comps) != len(competitors):
                cfg["competitors"] = cleaned_comps
                competitors = cleaned_comps
                try:
                    _tmp = path.with_suffix(".json.tmp")
                    _tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
                    _tmp.replace(path)
                except Exception: pass

            if len(competitors) < 1: continue
            scanned += 1

            if not self._can_rotate_symbol(cfg):
                continue

            primary_stats = self._genome_stats(hof, primary_gid)
            primary_entry = hof.get(primary_gid) or {}
            primary_is_pinned = bool(primary_entry.get("pinned"))
            if primary_stats["killed"]:
                # primary was killed — definitely look for replacement
                pass
            elif primary_stats["trades"] < self.MIN_PRIMARY_TRADES:
                # Normal rotation needs 5+ primary trades. Exceptions that
                # allow flow-through to specialized rules below:
                #   • PUNT (cycle 16): primary bleeding ≥3 trades / ≥$1 loss
                #   • SCORE-PROMOTE (cycle 23): primary not pinned (so a
                #     higher-score competitor can replace it on backtest
                #     signal alone, even at 0 live trades)
                punt_eligible = (primary_stats["trades"] >= self.PUNT_PRIMARY_MIN_TRADES
                                  and primary_stats["pnl"] <= self.PUNT_PRIMARY_PNL_FLOOR)
                score_eligible = not primary_is_pinned
                if not (punt_eligible or score_eligible):
                    continue

            # Find best competitor (qualifies + not killed + beats primary)
            best = None
            for comp in competitors:
                cid = comp.get("id") if isinstance(comp, dict) else comp
                if not cid or cid == primary_gid: continue
                cs = self._genome_stats(hof, cid)
                if cs["killed"]: continue
                if cs["trades"] < self.MIN_COMPETITOR_TRADES: continue
                # Need enough edge to justify swap
                edge = cs["pnl"] - primary_stats["pnl"]
                if edge < self.ROTATE_EDGE_USD: continue
                if best is None or cs["pnl"] > best["pnl"]:
                    best = cs
                    best["edge"] = edge

            # SCORE-PROMOTION fallback: no live-edge winner exists, but a
            # competitor's backtest score is dramatically higher than the
            # primary's. The primary must not be pinned (user/curator
            # chose it). Promote based on score signal.
            score_promo_reason = None
            if best is None and not primary_stats["killed"]:
                primary_entry = hof.get(primary_gid) or {}
                if not primary_entry.get("pinned"):
                    primary_score = float(primary_entry.get("score") or 0)
                    best_score_comp = None
                    for comp in competitors:
                        cid = comp.get("id") if isinstance(comp, dict) else comp
                        if not cid or cid == primary_gid: continue
                        centry = hof.get(cid) or {}
                        if centry.get("killed"): continue
                        cscore = float(centry.get("score") or 0)
                        if cscore < self.SCORE_PROMOTION_MIN: continue
                        if cscore - primary_score < self.SCORE_PROMOTION_GAP: continue
                        if best_score_comp is None or cscore > best_score_comp["score"]:
                            best_score_comp = self._genome_stats(hof, cid)
                            best_score_comp["score"] = cscore
                    if best_score_comp:
                        best = best_score_comp
                        best["edge"] = best_score_comp["score"] - primary_score
                        score_promo_reason = (
                            f"SCORE-promote — primary {primary_gid} score "
                            f"{primary_score:.1f}, competitor {best['id']} "
                            f"score {best_score_comp['score']:.1f}")

            # PUNT fallback: bleeding primary, no qualified competitor by
            # live-edge rule, but a high-score competitor exists with no
            # live history. Take the gamble — give it the slot, demote
            # the proven loser.
            punt_reason = None
            if (best is None
                    and not primary_stats["killed"]
                    and primary_stats["trades"] >= self.PUNT_PRIMARY_MIN_TRADES
                    and primary_stats["pnl"] <= self.PUNT_PRIMARY_PNL_FLOOR):
                # Find highest-score, untested competitor within score gap
                punt_candidate = None
                # Load HoF data freshly for score lookups
                for comp in competitors:
                    cid = comp.get("id") if isinstance(comp, dict) else comp
                    if not cid or cid == primary_gid: continue
                    centry = hof.get(cid) or {}
                    if centry.get("killed") or centry.get("pinned"): continue
                    cscore = float(centry.get("score") or 0)
                    clive  = int(centry.get("live_trades") or 0)
                    # Look for untested competitors (avoids re-punting same loser)
                    if clive > 0: continue
                    # Within score gap of primary's backtest score
                    primary_score = float((hof.get(primary_gid) or {}).get("score") or 0)
                    if cscore < primary_score - self.PUNT_COMP_MAX_SCORE_GAP:
                        continue
                    if punt_candidate is None or cscore > punt_candidate["score"]:
                        punt_candidate = self._genome_stats(hof, cid)
                        punt_candidate["score"] = cscore
                if punt_candidate:
                    best = punt_candidate
                    best["edge"] = -primary_stats["pnl"]  # synthetic edge
                    punt_reason = (f"PUNT — primary {primary_gid} bleeding "
                                    f"${primary_stats['pnl']:+.2f}/{primary_stats['trades']}t, "
                                    f"competitor {best['id']} untested but score "
                                    f"{best['score']:.1f}")

            if not best: continue

            # ─── EXECUTE THE SWAP ───
            # Move primary into competitors, promote best to primary.
            new_primary_block = dict(cfg.get("deployed_genome") or {})
            new_primary_block["id"] = best["id"]
            new_primary_block["nickname"] = best["nick"]
            new_primary_block["promoted_at"] = datetime.now(timezone.utc).isoformat()
            new_primary_block["promotion_reason"] = (
                f"live edge ${best['edge']:+.2f} over previous primary {primary_gid} "
                f"({best['trades']}t WR {best['wr']:.0f}%)")
            cfg["deployed_genome"] = new_primary_block

            # Update competitors list — move old primary into the list,
            # keep best removed since it's now primary
            new_competitors = []
            seen = {best["id"]}
            for comp in competitors:
                cid = comp.get("id") if isinstance(comp, dict) else comp
                if cid == best["id"]: continue
                if cid == primary_gid: continue
                seen.add(cid)
                new_competitors.append(comp if isinstance(comp, dict) else {"id": cid})
            # Demoted primary becomes a competitor
            if primary_gid not in seen:
                new_competitors.append({"id": primary_gid,
                                         "demoted_at": datetime.now(timezone.utc).isoformat(),
                                         "demote_reason": "lost head-to-head live P/L"})
            cfg["competitors"] = new_competitors

            # Append to rotation history
            hist = cfg.get("rotation_history") or []
            hist.append({
                "at":           datetime.now(timezone.utc).isoformat(),
                "demoted":      primary_gid,
                "promoted":     best["id"],
                "edge_usd":     round(best["edge"], 2),
                "demoted_pnl":  round(primary_stats["pnl"], 2),
                "promoted_pnl": round(best["pnl"], 2),
            })
            cfg["rotation_history"] = hist[-20:]

            # Atomic write
            try:
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                                encoding="utf-8")
                tmp.replace(path)
                rotations.append({
                    "symbol":   symbol,
                    "demoted":  primary_gid,
                    "promoted": best["id"],
                    "edge":     round(best["edge"], 2),
                })
                if punt_reason:
                    label = "🎲 PUNT"
                    detail = punt_reason
                elif score_promo_reason:
                    label = "⬆ SCORE-PROMOTE"
                    detail = score_promo_reason
                else:
                    label = "🔄 rotated"
                    detail = (f"(${best['edge']:+.2f} live edge, "
                              f"{best['trades']}t WR {best['wr']:.0f}%)")
                emit_insight(self.name, "ACT",
                    f"{label} {symbol}: {primary_gid} → {best['id']} {detail}",
                    data={"symbol": symbol, "old": primary_gid, "new": best["id"],
                           "edge": best["edge"], "old_pnl": primary_stats["pnl"],
                           "new_pnl": best["pnl"], "punt": bool(punt_reason),
                           "score_promote": bool(score_promo_reason)},
                    action="genome_rotated")
            except Exception as e:
                emit_insight(self.name, "WARN",
                    f"failed to rotate {symbol}: {e}")

        if rotations and scanned:
            emit_insight(self.name, "INFO",
                f"sweep done: {len(rotations)} rotations across {scanned} symbols")
        # Quiet otherwise — no news is good news

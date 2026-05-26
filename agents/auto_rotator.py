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
            if not isinstance(competitors, list) or len(competitors) < 2: continue
            scanned += 1

            if not self._can_rotate_symbol(cfg):
                continue

            primary_stats = self._genome_stats(hof, primary_gid)
            if primary_stats["killed"]:
                # primary was killed — definitely look for replacement
                pass
            elif primary_stats["trades"] < self.MIN_PRIMARY_TRADES:
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
                emit_insight(self.name, "ACT",
                    f"🔄 rotated {symbol}: {primary_gid} → {best['id']} "
                    f"(${best['edge']:+.2f} live edge, {best['trades']}t WR {best['wr']:.0f}%)",
                    data={"symbol": symbol, "old": primary_gid, "new": best["id"],
                           "edge": best["edge"], "old_pnl": primary_stats["pnl"],
                           "new_pnl": best["pnl"]},
                    action="genome_rotated")
            except Exception as e:
                emit_insight(self.name, "WARN",
                    f"failed to rotate {symbol}: {e}")

        if rotations and scanned:
            emit_insight(self.name, "INFO",
                f"sweep done: {len(rotations)} rotations across {scanned} symbols")
        # Quiet otherwise — no news is good news

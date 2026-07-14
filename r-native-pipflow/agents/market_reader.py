"""agents/market_reader.py — regime-aware genome router.

Every 5 minutes:
  1. read current regime per tradeable symbol (TREND/RANGE/EVENT/DEAD)
  2. compare to the deployed genome's preferred regime
  3. if mismatch, scan HoF for the best-scoring genome matching CURRENT regime
  4. if a much better fit exists, auto-deploy it

This lets the system swap personalities as the market changes — instead
of trying to force one "average" genome to work in all conditions.
"""
from __future__ import annotations

from r_native.agents.base import Agent, emit_insight


class MarketReader(Agent):
    name = "market_reader"
    description = "Regime-aware router — swaps genome when market personality changes"
    interval_seconds = 300       # 5 minutes
    default_enabled = True

    SCORE_GAIN_NEEDED = 5.0      # only swap if new genome > current + 5pts

    def _read_regime(self, symbol: str) -> dict | None:
        try:
            import urllib.request as _u
            import json as _json
            with _u.urlopen(
                f"http://127.0.0.1:5055/api/market?symbol={symbol}",
                timeout=3) as r:
                return _json.loads(r.read().decode())
        except Exception:
            return None

    def _current_genome(self, symbol: str) -> dict | None:
        import json
        from pathlib import Path
        p = (Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
             / f"{symbol}.json")
        if not p.exists(): return None
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            return cfg.get("deployed_genome")
        except Exception:
            return None

    def _best_genome_for_regime(self, symbol: str, regime: str) -> dict | None:
        """Find HoF genome that performed best on this archetype/regime."""
        try:
            from r_native.hall_of_fame import load_symbol
            alive = [e for e in load_symbol(symbol)
                     if not e.get("killed")
                     and e.get("all_params")]
            if not alive: return None
            # Match by archetype hint when regime is known
            regime_archetype_hint = {
                "TREND":  ("BREAKOUT", "MOMENTUM", "TREND"),
                "RANGE":  ("REVERSION", "MEAN_REV", "RANGE"),
                "EVENT":  ("VOLATILITY", "NEWS"),
                "DEAD":   (),
            }.get(regime, ())
            scored = []
            for e in alive:
                arch = (e.get("archetype") or "").upper()
                base_score = float(e.get("score") or 0)
                # +bonus if archetype matches regime
                regime_bonus = (10 if any(h in arch for h in regime_archetype_hint)
                                else 0)
                # +bonus if live PF is good
                live_pl = float(e.get("live_pnl") or 0)
                live_n  = int(e.get("live_trades") or 0)
                live_bonus = 0
                if live_n >= 5:
                    live_bonus = min(15, max(-15, live_pl / max(1, live_n) * 10))
                scored.append((base_score + regime_bonus + live_bonus, e))
            scored.sort(key=lambda x: x[0], reverse=True)
            return scored[0][1] if scored else None
        except Exception:
            return None

    def tick(self):
        # Find tradeable symbols from per-symbol configs
        from pathlib import Path
        cfg_dir = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
        symbols = [p.stem for p in cfg_dir.glob("*.json")] if cfg_dir.exists() else []

        for sym in symbols:
            cur = self._current_genome(sym)
            if not cur: continue
            cur_score = float(cur.get("score") or 0)
            cur_id    = cur.get("id")

            market = self._read_regime(sym)
            regime = "?"
            if market and market.get("regime"):
                regime = (market.get("regime") or {}).get("regime", "?")

            candidate = self._best_genome_for_regime(sym, regime)
            if not candidate: continue

            cand_id    = candidate.get("id")
            cand_score = float(candidate.get("score") or 0)
            cand_nick  = candidate.get("nickname", cand_id)

            if cand_id == cur_id:
                continue  # already best fit

            delta = cand_score - cur_score
            if delta < self.SCORE_GAIN_NEEDED:
                continue

            # SWAP
            try:
                from r_native.actions import deploy_genome_to_live
                # Rebuild genome_dict from HoF entry
                gd = {
                    "id":           cand_id,
                    "score":        cand_score,
                    "stats":        candidate.get("stats", {}),
                    "all_params":   candidate.get("all_params", {}),
                    "active_genes": candidate.get("active_genes", []),
                    "archetype":    candidate.get("archetype"),
                }
                for k, v in (candidate.get("all_params") or {}).items():
                    gd.setdefault(k, v)
                result = deploy_genome_to_live(sym, cand_id,
                                               candidate.get("tf", "M5"),
                                               genome_dict=gd)
                if result.get("ok"):
                    emit_insight(self.name, "ACT",
                        f"🔄 {sym} swapped: {cur_id} → {cand_nick} "
                        f"(regime={regime}, +{delta:.1f}pts)",
                        data={"symbol": sym, "old_id": cur_id,
                              "new_id": cand_id, "regime": regime,
                              "delta": delta},
                        action="genome_swapped")
                    try:
                        from r_native.hall_of_fame import record_deployment
                        record_deployment(cand_id, sym)
                    except Exception: pass
            except Exception as e:
                emit_insight(self.name, "WARN",
                             f"swap {sym} failed: {e}")

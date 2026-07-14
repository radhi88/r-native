"""
algory_integrator.py
--------------------
Connects AlgoryGenome DNA to FRIDAY's live agents.

Flow:
  AlgoryCampaign → best genome per (symbol, timeframe)
  → AlgoryIntegrator → entry_agent, risk_agent, monitor_agent, execution

Runtime loop (called each tick from friday_web_dashboard.py or algory_runner.py):
  integrator.on_tick(symbol, tf, df, mt5_account)
    ├── signal_engine.compute_signals(df, genome)
    ├── prop_firm_guard.can_trade()
    ├── risk_agent (size + SL)
    ├── execution (paper or live)
    └── gene_fitness_db.record_genome_result()
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .algory_backtest import backtest_genome, backtest_multi_timeframe, TF_BAR_COUNTS
from .algory_campaign import AlgoryCampaign
from .algory_dna import AlgoryGenome, PURGE_CRITERIA
from .algory_signal_engine import compute_signals
from .gene_fitness_db import get_gene_fitness_db
from .prop_firm_guard import PropFirmGuard

log = logging.getLogger("algory_integrator")

# ─────────────────────────────────────────────────────────────────────────────
#  Active genome registry
# ─────────────────────────────────────────────────────────────────────────────

from .core.project_root import APPDATA_FRIDAY as _APPDATA_FRIDAY
REGISTRY_PATH = _APPDATA_FRIDAY / "active_genomes.json"

@dataclass
class ActiveGenome:
    genome:      AlgoryGenome
    symbol:      str
    timeframe:   str
    activated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tick_count:  int  = 0
    last_signal: int  = 0   # 1 = long, -1 = short, 0 = flat
    open_trade:  dict | None = None


class GenomeRegistry:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], ActiveGenome] = {}

    def activate(self, genome: AlgoryGenome, symbol: str, timeframe: str) -> None:
        key = (symbol, timeframe)
        self._store[key] = ActiveGenome(genome=genome, symbol=symbol, timeframe=timeframe)
        log.info("Activated genome %s on %s %s | score=%.2f",
                 genome.id, symbol, timeframe, genome.modern_score())

    def get(self, symbol: str, timeframe: str) -> ActiveGenome | None:
        return self._store.get((symbol, timeframe))

    def all(self) -> list[ActiveGenome]:
        return list(self._store.values())

    def deactivate(self, symbol: str, timeframe: str) -> None:
        self._store.pop((symbol, timeframe), None)

    def save(self) -> None:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            f"{k[0]}|{k[1]}": v.genome.to_dict()
            for k, v in self._store.items()
        }
        REGISTRY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self) -> None:
        if not REGISTRY_PATH.exists():
            return
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        for key_str, gdict in data.items():
            sym, tf = key_str.split("|", 1)
            genome = AlgoryGenome.from_dict(gdict)
            self.activate(genome, sym, tf)


# ─────────────────────────────────────────────────────────────────────────────
#  Risk sizing (FRIDAY risk_agent integration)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_lot_size(
    genome: AlgoryGenome,
    entry_px: float,
    sl_px: float,
    account_balance: float,
    symbol: str,
) -> float:
    """Position size so risk_pct% of balance is at risk."""
    pip_dist = abs(entry_px - sl_px)
    if pip_dist < 1e-8:
        return 0.0
    risk_usd = account_balance * (genome.risk_pct / 100.0)
    pip_usd  = 10.0  # approximate for majors; real implementation queries MT5
    lot      = risk_usd / (pip_dist / 0.0001 * pip_usd)
    return round(max(0.01, min(lot, 100.0)), 2)


# ─────────────────────────────────────────────────────────────────────────────
#  Main integrator
# ─────────────────────────────────────────────────────────────────────────────

class AlgoryIntegrator:
    """
    Bridge between Algory campaign output and FRIDAY live execution.

    Usage:
        integrator = AlgoryIntegrator()
        integrator.load_registry()

        # Per tick (called from the FRIDAY monitor loop):
        result = integrator.on_tick("EURUSDm", "H1", df, account_balance=50_000)
    """

    def __init__(
        self,
        paper_mode: bool = True,
        prop_guard: PropFirmGuard | None = None,
    ) -> None:
        self.paper_mode  = paper_mode
        self.registry    = GenomeRegistry()
        self.guard       = prop_guard or PropFirmGuard()
        self.fitness_db  = get_gene_fitness_db()
        self._open_trades: dict[str, dict] = {}

    # ── Registry management ───────────────────────────────────────────────────

    def load_registry(self) -> None:
        self.registry.load()
        log.info("Registry loaded: %d active genomes", len(self.registry.all()))

    def save_registry(self) -> None:
        self.registry.save()

    # ── Campaign → activate ───────────────────────────────────────────────────

    def run_campaign_and_activate(
        self,
        symbol: str,
        timeframe: str,
        n_candidates: int = 200,
    ) -> AlgoryGenome | None:
        """
        Run a mini Algory campaign on (symbol, timeframe) and activate
        the best surviving genome for live trading.
        """
        # Build a real fitness function backed by the vectorized backtester
        from .algory_backtest import backtest_genome as _bt

        def _fitness(genome: AlgoryGenome, sym: str, phase: str) -> None:
            result = _bt(genome, sym, timeframe)
            result.apply_to_genome(genome)

        campaign = AlgoryCampaign(
            symbol=symbol,
            timeframe=timeframe,
            fitness_fn=_fitness,
            fitness_db=self.fitness_db,
        )
        survivors = campaign.run_full_campaign()
        if not survivors:
            log.warning("Campaign yielded no survivors for %s %s", symbol, timeframe)
            return None

        best = max(survivors, key=lambda g: g.modern_score())
        self.registry.activate(best, symbol, timeframe)
        self.registry.save()
        log.info("Campaign complete — best genome %s score=%.3f on %s %s",
                 best.id, best.modern_score(), symbol, timeframe)
        return best

    def run_multi_tf_campaign(
        self,
        symbol: str,
        timeframes: list[str] | None = None,
    ) -> dict[str, AlgoryGenome | None]:
        """Run campaigns on all timeframes for a symbol simultaneously."""
        import concurrent.futures
        if timeframes is None:
            timeframes = list(TF_BAR_COUNTS.keys())

        results: dict[str, AlgoryGenome | None] = {}
        with concurrent.futures.ProcessPoolExecutor(max_workers=min(len(timeframes), 8)) as ex:
            futures = {
                ex.submit(self.run_campaign_and_activate, symbol, tf): tf
                for tf in timeframes
            }
            for fut in concurrent.futures.as_completed(futures):
                tf = futures[fut]
                try:
                    results[tf] = fut.result()
                except Exception as e:
                    log.error("Campaign failed for %s %s: %s", symbol, tf, e)
                    results[tf] = None
        return results

    # ── Per-tick handler ──────────────────────────────────────────────────────

    def on_tick(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        account_balance: float = 100_000.0,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Called every new bar. Returns action dict:
          {"action": "BUY"|"SELL"|"CLOSE"|"HOLD",
           "lot": float, "sl": float, "tp": float,
           "genome_id": str, "reason": str}
        """
        active = self.registry.get(symbol, timeframe)
        if active is None:
            return {"action": "HOLD", "reason": "no_active_genome"}

        active.tick_count += 1
        genome = active.genome
        now    = now or datetime.now(timezone.utc)

        # ── Prop firm guard ───────────────────────────────────────────────────
        can, reason = self.guard.can_trade(symbol, "any", now=now)
        if not can:
            return {"action": "HOLD", "genome_id": genome.id, "reason": reason}

        # ── Signal computation ────────────────────────────────────────────────
        if len(df) < 50:
            return {"action": "HOLD", "genome_id": genome.id, "reason": "insufficient_bars"}

        try:
            sig_df  = compute_signals(df, genome)
        except Exception as e:
            log.exception("signal error on %s %s: %s", symbol, timeframe, e)
            return {"action": "HOLD", "genome_id": genome.id, "reason": f"signal_error:{e}"}

        last = sig_df.iloc[-1]
        entry_dir = int(last.get("entry_dir", 0))
        filter_ok = bool(last.get("filter_ok", False))

        if not filter_ok or entry_dir == 0:
            active.last_signal = 0
            conf = float(last.get("confidence", 0.0))
            log.debug("no_signal %s %s | filter_ok=%s entry_dir=%d conf=%.2f",
                      symbol, timeframe, filter_ok, entry_dir, conf)
            return {"action": "HOLD", "genome_id": genome.id, "reason": "no_signal"}

        sl_px    = float(last.get("sl",       0.0))
        tp_px    = float(last.get("tp",       0.0))
        close_col = "close" if "close" in df.columns else "Close"
        entry_px = float(last.get("entry_px", float(df[close_col].iloc[-1])))

        if sl_px <= 0 or tp_px <= 0:
            return {"action": "HOLD", "genome_id": genome.id, "reason": "invalid_sl_tp"}

        # ── Guard: prop DD check already covered; additional RR check ─────────
        rr = abs(tp_px - entry_px) / (abs(entry_px - sl_px) + 1e-10)
        if rr < genome.min_rr:
            return {"action": "HOLD", "genome_id": genome.id,
                    "reason": f"rr_{rr:.2f}<{genome.min_rr}"}

        # ── SMC secondary filter (OB/FVG/BOS confirmation) ───────────────────
        smc_boost = 0.0
        try:
            from algory_chart_dashboard import _calc_smc, _atr_from_df
            atr_v = _atr_from_df(df)
            smc   = _calc_smc(df, atr_v)
            tr    = smc.get("trigger", "none")
            tr_buy  = tr.endswith("_BUY")  or tr.startswith("BUY")
            tr_sell = tr.endswith("_SELL") or tr.startswith("SELL")
            if (entry_dir == 1 and tr_sell) or (entry_dir == -1 and tr_buy):
                # SMC opposes DNA signal → block
                log.info("SMC_BLOCK %s %s | trigger=%s opposes %s",
                         symbol, timeframe, tr, action)
                return {"action": "HOLD", "genome_id": genome.id,
                        "reason": f"smc_block:{tr}"}
            elif (entry_dir == 1 and tr_buy) or (entry_dir == -1 and tr_sell):
                smc_boost = 0.2   # SMC confirms → boost confidence by 20%
                log.info("SMC_CONFIRM %s %s | trigger=%s | boost=+20%%",
                         symbol, timeframe, tr)
        except Exception:
            pass   # SMC optional — never block a trade on import/compute error

        # ── Fractal structure filter ──────────────────────────────────────────
        try:
            from .fractal_structure_engine import analyse_structure
            from .market_projection_engine import generate_projection
            _fs   = analyse_structure(df)
            _proj = generate_projection(df, _fs, symbol=symbol, tf=timeframe,
                                        genome_win_rate=genome.win_rate)
            _dir  = _proj.get("direction", "SIDEWAYS")
            _conf = _proj.get("confidence", 0.0)
            if _dir != "SIDEWAYS" and _conf > 0.65:
                if (entry_dir == 1 and _dir == "DOWN") or \
                   (entry_dir == -1 and _dir == "UP"):
                    log.info("FRAC_BLOCK %s %s | fractal_dir=%s conf=%.2f opposes %s",
                             symbol, timeframe, _dir, _conf, action)
                    return {"action": "HOLD", "genome_id": genome.id,
                            "reason": f"fractal_block:{_dir}"}
            if (entry_dir == 1 and _dir == "UP") or \
               (entry_dir == -1 and _dir == "DOWN"):
                smc_boost += _conf * 0.15
                log.info("FRAC_CONFIRM %s %s | dir=%s conf=%.2f boost=+%.3f",
                         symbol, timeframe, _dir, _conf, _conf * 0.15)
        except Exception:
            pass  # fractal analysis is optional — never block on error

        # ── Confidence-weighted position sizing ───────────────────────────────
        # confidence = fraction of active signals that agreed (0.0 – 1.0)
        confidence = float(last.get("confidence", 1.0)) + smc_boost
        confidence = min(confidence, 1.5)
        # Scale lot: min 50% at low confidence, up to 150% at full confluence
        conf_mult = 0.5 + confidence          # 0.5x – 1.5x
        lot = _compute_lot_size(genome, entry_px, sl_px, account_balance, symbol)
        lot = round(max(0.01, lot * conf_mult), 2)
        if lot < 0.01:
            return {"action": "HOLD", "genome_id": genome.id, "reason": "lot_too_small"}

        action = "BUY" if entry_dir == 1 else "SELL"
        active.last_signal = entry_dir

        trade = {
            "confidence": round(confidence, 3),
            "action":    action,
            "lot":       lot,
            "entry":     round(entry_px, 6),
            "sl":        round(sl_px, 6),
            "tp":        round(tp_px, 6),
            "genome_id": genome.id,
            "symbol":    symbol,
            "timeframe": timeframe,
            "timestamp": now.isoformat(),
            "reason":    "signal_ok",
            "rr":        round(rr, 2),
        }

        if self.paper_mode:
            log.info("[PAPER] %s %s %.2f lots | SL=%.5f TP=%.5f | RR=%.2f",
                     action, symbol, lot, sl_px, tp_px, rr)
        else:
            log.info("[LIVE]  %s %s %.2f lots | SL=%.5f TP=%.5f | RR=%.2f",
                     action, symbol, lot, sl_px, tp_px, rr)

        return trade

    # ── Trade outcome feedback → gene fitness DB ──────────────────────────────

    def record_outcome(
        self,
        symbol: str,
        timeframe: str,
        won: bool,
        oos_passed: bool = False,
    ) -> None:
        active = self.registry.get(symbol, timeframe)
        if active is None:
            return
        self.fitness_db.record_genome_result(
            active.genome, won=won, oos_passed=oos_passed,
            symbol=symbol, timeframe=timeframe,
        )

    # ── Status snapshot ───────────────────────────────────────────────────────

    def status(self) -> list[dict]:
        rows = []
        for ag in self.registry.all():
            g = ag.genome
            ok, purge_reason = g.passes_purge()
            rows.append({
                "symbol":       ag.symbol,
                "timeframe":    ag.timeframe,
                "genome_id":    g.id,
                "modern_score": g.modern_score(),
                "trades":       g.trades,
                "win_rate":     round(g.win_rate, 3),
                "return_pct":   round(g.total_return_pct, 2),
                "max_dd_pct":   round(g.max_dd_pct, 2),
                "passes_purge": ok,
                "purge_reason": purge_reason,
                "tick_count":   ag.tick_count,
                "last_signal":  ag.last_signal,
                "active_genes": g.active_gene_count(),
            })
        return rows

    # ── Convenience: backtest the currently active genome ─────────────────────

    def backtest_active(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame | None = None,
    ) -> dict | None:
        active = self.registry.get(symbol, timeframe)
        if active is None:
            return None
        result = backtest_genome(active.genome, symbol, timeframe, df=df)
        result.apply_to_genome(active.genome)
        return active.genome.card_data()

    def backtest_active_all_tf(self, symbol: str) -> dict[str, dict | None]:
        results = {}
        for ag in self.registry.all():
            if ag.symbol == symbol:
                r = backtest_genome(ag.genome, symbol, ag.timeframe)
                r.apply_to_genome(ag.genome)
                results[ag.timeframe] = ag.genome.card_data()
        return results


# ─────────────────────────────────────────────────────────────────────────────
#  Singleton
# ─────────────────────────────────────────────────────────────────────────────

_integrator: AlgoryIntegrator | None = None


def get_integrator(paper_mode: bool = True) -> AlgoryIntegrator:
    global _integrator
    if _integrator is None:
        _integrator = AlgoryIntegrator(paper_mode=paper_mode)
        _integrator.load_registry()
    return _integrator

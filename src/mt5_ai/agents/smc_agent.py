"""smc_agent.py — SMC (Smart Money Concepts) signal producer.

Signal semantics:
  BUY             — bullish bias + active bullish entry trigger present
  SELL            — bearish bias + active bearish entry trigger present
  NO_CONFIRMATION — bias exists but NO active OB / FVG / sweep / BOS / CHoCH for that direction
  None            — scores too close to determine any bias (score_gap < 0.5)

Active entry triggers per direction:
  BUY:  bos_up, choch_up, in_bullish_ob, sell_side_liquidity_sweep, bullish_fvg
  SELL: bos_down, choch_down, in_bearish_ob, buy_side_liquidity_sweep, bearish_fvg
"""
from __future__ import annotations
import logging
import pandas as pd
from ..core.signal_schema import SignalProposal, Direction
from ..core.magic_registry import ALGORY_MAGIC
from ..core.structured_logger import log_signal, log_error

log = logging.getLogger("smc_agent")


class SmcAgent:
    source = "smc_agent"

    def analyse(self, df: pd.DataFrame, symbol: str, timeframe: str) -> SignalProposal | None:
        try:
            from ..market_structure import latest_smc_snapshot
            snap = latest_smc_snapshot(df)

            buy_score  = float(snap.get("smc_buy_score",  0.0))
            sell_score = float(snap.get("smc_sell_score", 0.0))
            bias       = float(snap.get("smc_bias", 0.0))

            bos_up     = float(snap.get("bos_up",                    0.0))
            bos_down   = float(snap.get("bos_down",                  0.0))
            choch_up   = float(snap.get("choch_up",                  0.0))
            choch_dn   = float(snap.get("choch_down",                0.0))
            in_bull_ob = float(snap.get("in_bullish_ob",             0.0))
            in_bear_ob = float(snap.get("in_bearish_ob",             0.0))
            bull_sweep = float(snap.get("buy_side_liquidity_sweep",  0.0))
            bear_sweep = float(snap.get("sell_side_liquidity_sweep", 0.0))
            bull_fvg   = float(snap.get("bullish_fvg",              0.0))
            bear_fvg   = float(snap.get("bearish_fvg",              0.0))

            # ── Require minimum score separation to determine any bias ─────
            score_gap = abs(buy_score - sell_score)
            if score_gap < 0.5:
                return None   # genuinely ambiguous — no opinion

            # ── Determine direction from score + bias alignment ────────────
            if buy_score > sell_score and bias >= 0.0:
                direction = Direction.BUY
            elif sell_score > buy_score and bias <= 0.0:
                direction = Direction.SELL
            else:
                return None   # score and bias disagree — no opinion

            # ── Check direction-specific active entry triggers ─────────────
            if direction == Direction.BUY:
                has_confirmation = (
                    bos_up   > 0 or choch_up   > 0 or
                    in_bull_ob > 0 or bear_sweep > 0 or bull_fvg > 0
                )
            else:  # SELL
                has_confirmation = (
                    bos_down > 0 or choch_dn   > 0 or
                    in_bear_ob > 0 or bull_sweep > 0 or bear_fvg > 0
                )

            # ── No active trigger → NO_CONFIRMATION (not a directional bet) ─
            if not has_confirmation:
                reason = (
                    f"smc_no_active_setup:{direction.value}|"
                    f"bias={bias:.2f}|buy={buy_score:.1f}|sell={sell_score:.1f}|"
                    f"bos={bos_up:.0f}/{bos_down:.0f}|choch={choch_up:.0f}/{choch_dn:.0f}|"
                    f"ob={in_bull_ob:.0f}/{in_bear_ob:.0f}|"
                    f"sweep={bull_sweep:.0f}/{bear_sweep:.0f}|"
                    f"fvg={bull_fvg:.0f}/{bear_fvg:.0f}"
                )
                log_signal(self.source, symbol, timeframe,
                           Direction.NO_CONFIRMATION.value, 0.0, reason)
                return SignalProposal(
                    source=self.source,
                    strategy_id="FRIDAY_SMC_NO_CONF",
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=Direction.NO_CONFIRMATION,
                    confidence=0.0,
                    strength=0.0,
                    reason=reason,
                    features={k: float(v) for k, v in snap.items()},
                    can_execute=False,
                    desired_magic=ALGORY_MAGIC,
                    priority=4,
                    tags=["smc", "no_confirmation"],
                )

            # ── Active trigger present → emit directional signal ───────────
            if direction == Direction.BUY:
                confidence = min(0.90, 0.40 + buy_score  * 0.08
                                 + (bos_up   + choch_up) * 0.05
                                 + in_bull_ob * 0.05 + bear_sweep * 0.05
                                 + bull_fvg   * 0.03)
            else:
                confidence = min(0.90, 0.40 + sell_score * 0.08
                                 + (bos_down  + choch_dn) * 0.05
                                 + in_bear_ob * 0.05 + bull_sweep * 0.05
                                 + bear_fvg   * 0.03)

            reason = (
                f"smc:{direction.value}|bias={bias:.2f}|buy={buy_score:.1f}|sell={sell_score:.1f}|"
                f"bos={bos_up:.0f}/{bos_down:.0f}|choch={choch_up:.0f}/{choch_dn:.0f}|"
                f"ob={in_bull_ob:.0f}/{in_bear_ob:.0f}|"
                f"sweep={bull_sweep:.0f}/{bear_sweep:.0f}|"
                f"fvg={bull_fvg:.0f}/{bear_fvg:.0f}"
            )
            log_signal(self.source, symbol, timeframe, direction.value, confidence, reason)

            return SignalProposal(
                source=self.source,
                strategy_id="FRIDAY_SMC",
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                confidence=confidence,
                strength=score_gap,
                reason=reason,
                features={k: float(v) for k, v in snap.items()},
                can_execute=False,
                desired_magic=ALGORY_MAGIC,
                priority=4,
                tags=["smc", "orderblock", "liquidity"],
            )
        except Exception as exc:
            log_error(self.source, str(exc), {"symbol": symbol, "tf": timeframe})
            return None

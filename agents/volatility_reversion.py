"""agents/volatility_reversion.py — mean-reversion sister of volatility_hunter.

USER OBSERVED (cycle 22): volatility_hunter's straddle is a BREAKOUT bet:
  BUY_STOP at swing_high  → fires when price breaks UP (expect continuation)
  SELL_STOP at swing_low  → fires when price breaks DOWN (expect continuation)

In RANGE-bound markets (which the system saw most of this session), that
logic gets fakeout-trapped: BUY_STOP fires at top → price reverts → loss.
The user pointed out that for current conditions the OPPOSITE bet would
have won: SELL at the top (expect reversion), BUY at the bottom.

This agent places the REVERSION straddle:
  SELL_LIMIT at swing_high + buf   → fires when price RISES to this peak
                                       (expect bounce back down)
  BUY_LIMIT  at swing_low  - buf   → fires when price DROPS to this bottom
                                       (expect bounce back up)

Runs in PARALLEL with volatility_hunter. Both strategies test live and
real P/L per genome will tell us which is winning.

Tight SL (1.2× ATR), narrower TP (2.0× ATR) — reversions are usually
faster + shorter than breakouts. Cooldown identical to volatility_hunter
(30 min same-symbol) to avoid spam.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


class VolatilityReversion(Agent):
    name = "volatility_reversion"
    description = "Mean-reversion BUY_LIMIT/SELL_LIMIT straddles at volatility extremes"
    interval_seconds = 180     # every 3 min, same as breakout sibling
    default_enabled = True

    SPIKE_THRESHOLD = 1.8      # match sibling — only on real spikes
    BUFFER_ATR_MULT = 0.3      # entry placed 0.3 ATR beyond swing
    SL_ATR_MULT     = 1.2      # tighter SL — reversion failure = trend
    TP_ATR_MULT     = 2.0      # narrower TP — reversion is fast
    EXPIRY_HOURS    = 2
    MAX_STRADDLES   = 3
    SAME_SYMBOL_COOLDOWN_MIN = 30

    _last_placed_by_sym: dict[str, float] = {}

    def _list_deployed_symbols(self) -> list[str]:
        import json
        cfg_dir = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
        out = []
        for p in cfg_dir.glob("*.json"):
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
                if cfg.get("tradeable", True) and (cfg.get("deployed_genome") or {}).get("id"):
                    out.append(p.stem)
            except Exception: continue
        return out

    def _detect_spike(self, symbol: str) -> dict | None:
        """Same detection as volatility_hunter — H1 ATR spike."""
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 30)
            if rates is None or len(rates) < 25: return None
            highs = rates["high"]; lows = rates["low"]; closes = rates["close"]
            trs = [max(float(highs[i])-float(lows[i]),
                        abs(float(highs[i])-float(closes[i-1])),
                        abs(float(lows[i]) -float(closes[i-1])))
                    for i in range(1, len(rates))]
            current_atr  = trs[-1]
            mean_atr_24h = sum(trs[-24:]) / 24
            if mean_atr_24h == 0: return None
            spike_mult = current_atr / mean_atr_24h
            if spike_mult < self.SPIKE_THRESHOLD: return None
            # Wider lookback for reversion swing levels (last 10 bars instead of 5)
            # so we catch the FULL spike extreme as the reversion target
            swing_high = float(highs[-10:].max())
            swing_low  = float(lows[-10:].min())
            return {
                "symbol":       symbol,
                "current_atr":  current_atr,
                "mean_atr_24h": mean_atr_24h,
                "spike_mult":   spike_mult,
                "swing_high":   swing_high,
                "swing_low":    swing_low,
            }
        except Exception: return None

    def tick(self):
        from r_native.pending_orders import (
            place_pending, list_r_pending, cancel_expired
        )
        cancel_expired(max_age_hours=self.EXPIRY_HOURS)
        # Reversion straddles tagged with "rev" prefix so we don't collide
        # with volatility_hunter's "vol_" pendings — both can co-exist.
        existing = list_r_pending()
        rev_syms = {o["symbol"] for o in existing
                     if "rev" in (o.get("comment") or "").lower()}
        import time as _t
        now_s = _t.time()
        placed = 0
        for sym in self._list_deployed_symbols():
            if placed >= self.MAX_STRADDLES: break
            if sym in rev_syms: continue
            last_ts = self._last_placed_by_sym.get(sym, 0)
            if (now_s - last_ts) < self.SAME_SYMBOL_COOLDOWN_MIN * 60:
                continue
            spike = self._detect_spike(sym)
            if not spike: continue

            buf = self.BUFFER_ATR_MULT * spike["current_atr"]
            # SELL_LIMIT at top (sell into strength, expect bounce down)
            sell_entry = spike["swing_high"] + buf
            sell_sl    = sell_entry + spike["current_atr"] * self.SL_ATR_MULT
            sell_tp    = sell_entry - spike["current_atr"] * self.TP_ATR_MULT
            place_pending(symbol=sym, side="SELL", order_kind="LIMIT",
                           price=sell_entry, sl=sell_sl, tp=sell_tp,
                           reason="vol_rev", expiry_hours=self.EXPIRY_HOURS,
                           agent_name="volrev")
            # BUY_LIMIT at bottom (buy into weakness, expect bounce up)
            buy_entry = spike["swing_low"] - buf
            buy_sl    = buy_entry - spike["current_atr"] * self.SL_ATR_MULT
            buy_tp    = buy_entry + spike["current_atr"] * self.TP_ATR_MULT
            place_pending(symbol=sym, side="BUY", order_kind="LIMIT",
                           price=buy_entry, sl=buy_sl, tp=buy_tp,
                           reason="vol_rev", expiry_hours=self.EXPIRY_HOURS,
                           agent_name="volrev")
            placed += 1
            self._last_placed_by_sym[sym] = now_s
            emit_insight(self.name, "ACT",
                f"🔄 {sym} REVERSION straddle ({spike['spike_mult']:.2f}x spike) — "
                f"SELL_LIMIT@{sell_entry:.5f} (top) + BUY_LIMIT@{buy_entry:.5f} (bottom)",
                data=spike, action="vol_reversion_placed")

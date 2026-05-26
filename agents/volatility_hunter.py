"""agents/volatility_hunter.py — place BUY_STOP / SELL_STOP during volatility spikes.

When ATR suddenly spikes (e.g. >1.8× the 24h average) AND the spike bar
has a clear directional bias, we place ONE pending STOP order in the
spike's direction — never a blind straddle.

  BULL spike (close > open, body dominant) → BUY_STOP  above swing_high
  BEAR spike (close < open, body dominant) → SELL_STOP below swing_low
  Indecisive spike (small body / doji)     → no order (likely exhaustion)

The swing reference window EXCLUDES the spike bar itself — otherwise the
entry trigger gets placed on top of an exhaustion wick.

Sizing uses real 14-bar ATR (not the spike bar's TR) so SL/TP stay sane
even when one freak candle prints. Orders expire in 2h server-side via
the broker's `expiration` field — no reliance on the local loop being
alive to clean them up.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


class VolatilityHunter(Agent):
    name = "volatility_hunter"
    description = "Places direction-aware BUY_STOP/SELL_STOP on volatility spikes"
    interval_seconds = 180   # every 3 min
    default_enabled = True

    SPIKE_THRESHOLD     = 1.8    # spike bar TR must be 1.8× the 14-bar ATR
    BODY_RATIO_MIN      = 0.55   # spike body must be ≥55% of bar range
    BUFFER_ATR_MULT     = 0.3    # entry placed 0.3 × ATR14 beyond swing
    SL_ATR_MULT         = 1.5
    TP_ATR_MULT         = 3.0    # R:R = 1:2
    MAX_ENTRY_DIST_ATR  = 4.0    # skip if entry is >4 ATR from current price
    EXPIRY_HOURS        = 2
    MAX_PLACEMENTS      = 3      # don't flood

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
        """Return directional spike info, or None if no clean spike.

        Direction is decided from the spike bar itself (close vs open + body
        dominance). The swing reference excludes the spike bar so the entry
        doesn't sit on top of an exhaustion wick.
        """
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 30)
            if rates is None or len(rates) < 25: return None
            highs  = rates["high"];  lows   = rates["low"]
            opens  = rates["open"];  closes = rates["close"]
            # True ranges, indexed 1..len-1
            trs = [max(float(highs[i])-float(lows[i]),
                        abs(float(highs[i])-float(closes[i-1])),
                        abs(float(lows[i]) -float(closes[i-1])))
                    for i in range(1, len(rates))]
            spike_tr = trs[-1]                 # last bar's true range
            atr14    = sum(trs[-14:]) / 14     # real 14-bar ATR (baseline sizing)
            mean_atr_24h = sum(trs[-24:]) / 24 # spike comparison
            if atr14 == 0 or mean_atr_24h == 0: return None
            spike_mult = spike_tr / mean_atr_24h
            if spike_mult < self.SPIKE_THRESHOLD: return None

            # Direction from spike bar's body
            o, c, hi, lo = (float(opens[-1]), float(closes[-1]),
                            float(highs[-1]), float(lows[-1]))
            rng = hi - lo
            if rng <= 0: return None
            body_ratio = abs(c - o) / rng
            if body_ratio < self.BODY_RATIO_MIN:
                return None  # doji / indecisive — likely exhaustion, not impulse
            spike_dir = "BULL" if c > o else "BEAR"

            # Swing reference EXCLUDES current bar
            ref_highs = highs[-6:-1]
            ref_lows  = lows[-6:-1]
            swing_high = float(ref_highs.max())
            swing_low  = float(ref_lows.min())

            current_price = float(closes[-1])
            return {
                "symbol":       symbol,
                "spike_tr":     spike_tr,
                "atr14":        atr14,
                "mean_atr_24h": mean_atr_24h,
                "spike_mult":   spike_mult,
                "spike_dir":    spike_dir,
                "body_ratio":   body_ratio,
                "swing_high":   swing_high,
                "swing_low":    swing_low,
                "current":      current_price,
            }
        except Exception: return None

    def tick(self):
        from r_native.pending_orders import (
            place_pending, list_r_pending, cancel_expired
        )
        cancel_expired(max_age_hours=self.EXPIRY_HOURS)
        existing_syms = {o["symbol"] for o in list_r_pending()}
        placed = 0
        for sym in self._list_deployed_symbols():
            if placed >= self.MAX_PLACEMENTS: break
            if sym in existing_syms: continue
            spike = self._detect_spike(sym)
            if not spike: continue

            atr  = spike["atr14"]
            buf  = self.BUFFER_ATR_MULT * atr
            cur  = spike["current"]

            if spike["spike_dir"] == "BULL":
                entry = spike["swing_high"] + buf
                sl    = entry - atr * self.SL_ATR_MULT
                tp    = entry + atr * self.TP_ATR_MULT
                side, kind = "BUY", "STOP"
            else:
                entry = spike["swing_low"] - buf
                sl    = entry + atr * self.SL_ATR_MULT
                tp    = entry - atr * self.TP_ATR_MULT
                side, kind = "SELL", "STOP"

            # Skip stale-zone entries: market has already left the spike area
            if abs(entry - cur) > self.MAX_ENTRY_DIST_ATR * atr:
                emit_insight(self.name, "INFO",
                    f"⏭ {sym} {spike['spike_dir']} spike {spike['spike_mult']:.2f}x — "
                    f"entry {entry:.5f} too far from {cur:.5f}, skipped",
                    data=spike, action="vol_skip_far")
                continue

            place_pending(symbol=sym, side=side, order_kind=kind,
                          price=entry, sl=sl, tp=tp,
                          reason="vol_spike", expiry_hours=self.EXPIRY_HOURS,
                          agent_name="volhun")
            placed += 1
            emit_insight(self.name, "ACT",
                f"⚡ {sym} {spike['spike_dir']} spike {spike['spike_mult']:.2f}x — "
                f"placed {side}_{kind}@{entry:.5f} SL {sl:.5f} TP {tp:.5f}",
                data=spike, action="vol_directional_placed")

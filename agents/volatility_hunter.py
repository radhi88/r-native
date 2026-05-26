"""agents/volatility_hunter.py — place BUY_STOP / SELL_STOP during volatility spikes.

When ATR suddenly spikes (e.g. >2× the 24h average), big move is likely.
This agent places PENDING STOP orders just beyond the current range so
that if a breakout fires either way, we catch it.

  BUY_STOP at (swing_high + buffer)  — catches upside breakout
  SELL_STOP at (swing_low - buffer)  — catches downside breakdown

Both expire in 2 hours — if the breakout doesn't happen, no harm done.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


class VolatilityHunter(Agent):
    name = "volatility_hunter"
    description = "Places BUY_STOP+SELL_STOP straddles during volatility spikes"
    interval_seconds = 180   # every 3 min
    default_enabled = True

    SPIKE_THRESHOLD = 1.6    # cycle 25 partial revert: 1.4 was too loose
                              # (caught noise as spikes). Back to 1.6 — still
                              # more sensitive than original 1.8.
    BUFFER_ATR_MULT = 0.3    # entry placed 0.3 ATR beyond swing
    SL_ATR_MULT     = 1.5
    TP_ATR_MULT     = 3.0    # R:R = 1:2
    # Reversion-side params (cycle 23 — added per user request "حاط لي
    # بيع مكان الشراء"). On every spike we now ALSO place LIMIT orders
    # at the OPPOSITE extreme — SELL_LIMIT at top (catch peak rejection),
    # BUY_LIMIT at bottom (catch oversold bounce). Tighter SL because a
    # failed reversion means a trend is forming → cut fast.
    PLACE_REVERSION = True
    REV_SL_ATR_MULT = 1.2
    REV_TP_ATR_MULT = 2.0
    EXPIRY_HOURS    = 2
    MAX_STRADDLES   = 3      # don't flood
    # Cycle-21 fix: even if no pending exists right now (filled or
    # canceled), don't re-place a straddle on the same symbol within
    # this many minutes. Observed pattern: same symbol with identical
    # spike values fired 7 times in 15 min, polluting the insight feed.
    SAME_SYMBOL_COOLDOWN_MIN = 10   # was 30 — let same symbol re-fire faster

    # State: {symbol -> last_placed_ts} survives within agent's process
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
        """Return spike info if current ATR significantly above 24h mean."""
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
            # H1 bars — last 30
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 30)
            if rates is None or len(rates) < 25: return None
            highs = rates["high"]; lows = rates["low"]; closes = rates["close"]
            # ATR per bar (true range)
            trs = [max(float(highs[i])-float(lows[i]),
                        abs(float(highs[i])-float(closes[i-1])),
                        abs(float(lows[i]) -float(closes[i-1])))
                    for i in range(1, len(rates))]
            current_atr = trs[-1]   # last bar's true range
            mean_atr_24h = sum(trs[-24:]) / 24
            if mean_atr_24h == 0: return None
            spike_mult = current_atr / mean_atr_24h
            if spike_mult < self.SPIKE_THRESHOLD: return None
            # Range for entries
            swing_high = float(highs[-5:].max())
            swing_low  = float(lows[-5:].min())
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
        existing_syms = {o["symbol"] for o in list_r_pending()}
        import time as _t
        now_s = _t.time()
        placed = 0
        for sym in self._list_deployed_symbols():
            if placed >= self.MAX_STRADDLES: break
            if sym in existing_syms: continue
            # Same-symbol cooldown — even if pendings vanished, don't
            # immediately re-fire a straddle on the same symbol.
            last_ts = self._last_placed_by_sym.get(sym, 0)
            if (now_s - last_ts) < self.SAME_SYMBOL_COOLDOWN_MIN * 60:
                continue
            spike = self._detect_spike(sym)
            if not spike: continue
            buf = self.BUFFER_ATR_MULT * spike["current_atr"]
            # BUY_STOP above range
            buy_entry = spike["swing_high"] + buf
            buy_sl    = buy_entry - spike["current_atr"] * self.SL_ATR_MULT
            buy_tp    = buy_entry + spike["current_atr"] * self.TP_ATR_MULT
            place_pending(symbol=sym, side="BUY",  order_kind="STOP",
                          price=buy_entry, sl=buy_sl, tp=buy_tp,
                          reason="vol_spike", expiry_hours=self.EXPIRY_HOURS,
                          agent_name="volhun")
            # SELL_STOP below range
            sell_entry = spike["swing_low"] - buf
            sell_sl    = sell_entry + spike["current_atr"] * self.SL_ATR_MULT
            sell_tp    = sell_entry - spike["current_atr"] * self.TP_ATR_MULT
            place_pending(symbol=sym, side="SELL", order_kind="STOP",
                          price=sell_entry, sl=sell_sl, tp=sell_tp,
                          reason="vol_spike", expiry_hours=self.EXPIRY_HOURS,
                          agent_name="volhun")
            # ── REVERSION SIDE (cycle 23 fix) ──
            # SELL_LIMIT at swing_high+buf (sell into a peak — expect rejection)
            # BUY_LIMIT  at swing_low-buf  (buy into a bottom — expect bounce)
            rev_msg = ""
            if self.PLACE_REVERSION:
                rev_sell_entry = spike["swing_high"] + buf
                rev_sell_sl    = rev_sell_entry + spike["current_atr"] * self.REV_SL_ATR_MULT
                rev_sell_tp    = rev_sell_entry - spike["current_atr"] * self.REV_TP_ATR_MULT
                place_pending(symbol=sym, side="SELL", order_kind="LIMIT",
                              price=rev_sell_entry, sl=rev_sell_sl, tp=rev_sell_tp,
                              reason="vol_rev",  expiry_hours=self.EXPIRY_HOURS,
                              agent_name="volhun")
                rev_buy_entry = spike["swing_low"] - buf
                rev_buy_sl    = rev_buy_entry - spike["current_atr"] * self.REV_SL_ATR_MULT
                rev_buy_tp    = rev_buy_entry + spike["current_atr"] * self.REV_TP_ATR_MULT
                place_pending(symbol=sym, side="BUY",  order_kind="LIMIT",
                              price=rev_buy_entry, sl=rev_buy_sl, tp=rev_buy_tp,
                              reason="vol_rev",  expiry_hours=self.EXPIRY_HOURS,
                              agent_name="volhun")
                rev_msg = (f" + REV: SELL_LIMIT@{rev_sell_entry:.5f}/"
                            f"BUY_LIMIT@{rev_buy_entry:.5f}")
            placed += 1
            self._last_placed_by_sym[sym] = now_s
            emit_insight(self.name, "ACT",
                f"⚡ {sym} volatility spike {spike['spike_mult']:.2f}x — "
                f"BREAKOUT: BUY_STOP@{buy_entry:.5f}/SELL_STOP@{sell_entry:.5f}"
                + rev_msg,
                data=spike, action="vol_straddle_placed")

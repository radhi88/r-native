"""agents/regime_scaler.py — per-symbol lot multipliers driven by MTF regime.

Reads market_scan.json (written every 90s by MarketScanner) and writes
`data/r_native/regime_multipliers.json` with per-symbol-per-side lot
multipliers. The executor reads this at order time and scales the lot
accordingly — turning the multi-timeframe market intelligence into
actual position-size decisions.

Logic:
  Look at M15 / H1 / H4 bias.
  • 3-of-3 same direction (TREND ALIGNED) + trade matches → 1.6× lot
  • 2-of-3 same direction (TREND LEANING) + trade matches → 1.2× lot
  • Trade FIGHTS aligned trend                            → 0.5× lot
  • Regime == DEAD                                         → 0.5× lot
  • Mixed / RANGE                                          → 1.0× lot

Trade direction matching:
  - BUY  matches when alignment is UP
  - SELL matches when alignment is DOWN

Output schema (regime_multipliers.json):
  {
    "updated_at": "...",
    "symbols": {
      "XAUUSDm": {
        "regime":          "TREND_UP",
        "mtf_alignment":   "UP",          # UP | DOWN | MIXED
        "alignment_count": 3,             # 0-3
        "buy_mult":        1.6,           # lot multiplier if BUY
        "sell_mult":       0.5,           # lot multiplier if SELL
        "reason":          "...",
      },
      ...
    }
  }

The agent is conservative — it never blocks trades, only nudges size.
The base lot stays 0.01 (≈ $0.30/pip on a $126 account).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


SCAN_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\market_scan.json")
OUT_PATH  = Path(r"C:\Users\Radhi\MT5\data\r_native\regime_multipliers.json")


class RegimeScaler(Agent):
    name = "regime_scaler"
    description = "MTF-driven per-symbol lot multipliers (boosts aligned trends)"
    interval_seconds = 120     # every 2 min (just after market_scanner ticks)
    default_enabled = True

    _last_signature: str = ""
    _last_emit_ts:   float = 0.0
    MIN_SECONDS_BETWEEN_EMITS = 600   # 10 min — don't ACT on noise flicker

    def _compute(self, tf: dict, regime: str) -> dict:
        """Compute alignment + per-side multiplier from one symbol's TF data."""
        m15 = (tf.get("M15") or {}).get("bias")
        h1  = (tf.get("H1")  or {}).get("bias")
        h4  = (tf.get("H4")  or {}).get("bias")

        biases = [b for b in (m15, h1, h4) if b]
        if not biases:
            return {"mtf_alignment": "MIXED", "alignment_count": 0,
                    "buy_mult": 1.0, "sell_mult": 1.0,
                    "reason": "no TF data"}

        ups   = biases.count("UP")
        downs = biases.count("DOWN")

        # Determine dominant direction
        if ups >= 2 and downs == 0:
            alignment, count = "UP", ups
        elif downs >= 2 and ups == 0:
            alignment, count = "DOWN", downs
        else:
            alignment, count = "MIXED", max(ups, downs)

        buy_mult, sell_mult = 1.0, 1.0
        reason_parts = [f"M15={m15} H1={h1} H4={h4}"]

        # DEAD regime — halve both sides (low-volatility chop is unprofitable)
        if regime == "DEAD":
            buy_mult = sell_mult = 0.5
            reason_parts.append("DEAD regime → 0.5×")
            return {"mtf_alignment": alignment, "alignment_count": count,
                    "buy_mult": buy_mult, "sell_mult": sell_mult,
                    "reason": " | ".join(reason_parts)}

        if alignment == "UP":
            if count == 3:
                buy_mult, sell_mult = 1.6, 0.5
                reason_parts.append("3-of-3 UP → BUY 1.6× / SELL 0.5×")
            elif count == 2:
                buy_mult, sell_mult = 1.2, 0.75
                reason_parts.append("2-of-3 UP → BUY 1.2× / SELL 0.75×")
        elif alignment == "DOWN":
            if count == 3:
                buy_mult, sell_mult = 0.5, 1.6
                reason_parts.append("3-of-3 DOWN → SELL 1.6× / BUY 0.5×")
            elif count == 2:
                buy_mult, sell_mult = 0.75, 1.2
                reason_parts.append("2-of-3 DOWN → SELL 1.2× / BUY 0.75×")
        else:
            reason_parts.append("MIXED → no boost")

        return {"mtf_alignment": alignment, "alignment_count": count,
                "buy_mult": buy_mult, "sell_mult": sell_mult,
                "reason": " | ".join(reason_parts)}

    def tick(self):
        if not SCAN_PATH.exists():
            # No scanner data yet — emit nothing and try again later
            return
        try:
            scan = json.loads(SCAN_PATH.read_text(encoding="utf-8"))
        except Exception:
            return

        symbols_out = {}
        boost_count = 0
        for sym, data in (scan.get("symbols") or {}).items():
            mult = self._compute(data.get("tf") or {}, data.get("regime") or "")
            mult["regime"] = data.get("regime") or "?"
            symbols_out[sym] = mult
            if max(mult["buy_mult"], mult["sell_mult"]) > 1.0:
                boost_count += 1

        out = {"updated_at": datetime.now(timezone.utc).isoformat(),
               "symbols":     symbols_out}
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                             encoding="utf-8")

        # Build signature: only emit ACT on MEANINGFUL change. The previous
        # version emitted every time alignment_count for ANY symbol shifted —
        # which happens every 2 min due to natural M15 RSI/slope drift.
        # Two-layer guard:
        #   1) signature must change
        #   2) at least MIN_SECONDS_BETWEEN_EMITS since last emit
        #      (regime classifications don't meaningfully change faster than
        #       that — anything else is sensor noise we shouldn't broadcast)
        import time as _t
        sig = "|".join(
            f"{s}:{d['mtf_alignment']}:{d['alignment_count']}:{d['regime']}"
            for s, d in sorted(symbols_out.items())
        )
        now_s = _t.time()
        if (sig != self._last_signature
                and (now_s - self._last_emit_ts) >= self.MIN_SECONDS_BETWEEN_EMITS):
            aligned = [s for s, d in symbols_out.items()
                       if d["alignment_count"] >= 2 and d["mtf_alignment"] != "MIXED"]
            dead = [s for s, d in symbols_out.items() if d["regime"] == "DEAD"]
            emit_insight(self.name, "ACT",
                f"⚖ regime map updated — {boost_count} symbols boosted, "
                f"{len(aligned)} MTF-aligned, {len(dead)} DEAD",
                data={"aligned": aligned[:6], "dead": dead[:6],
                      "boost_count": boost_count},
                action="regime_map_updated")
            self._last_signature = sig
            self._last_emit_ts   = now_s

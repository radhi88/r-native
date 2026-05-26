"""agents/market_scanner.py — multi-timeframe + level + gap snapshot per symbol.

User wants 'more market readings — multiple timeframes, price levels,
gap detection for every symbol'. This agent runs every 90s and writes:

  data/r_native/market_scan.json = {
    symbol: {
      bid, ask, spread,
      tf: {
        M5:  {bias, rsi, atr, swing_high, swing_low, slope},
        M15: {...},
        H1:  {...},
        H4:  {...},
        D1:  {...}
      },
      levels: {
        day_high, day_low, day_mid,
        week_high, week_low,
        prev_day_close, prev_day_high, prev_day_low
      },
      gap: {
        type:    NONE | UP | DOWN,
        size:    abs(open - prev_close),
        size_pct: %
        filled:  bool (price returned to prev_close)
      },
      regime: TREND_UP | TREND_DOWN | RANGE | DEAD
    }
  }

This dataset is used by:
  • the UI Inspector (a future enhancement) to show per-symbol context
  • the Council / genome decision (richer snapshot)
  • the user himself when he wakes up — clear picture of every market
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


SCAN_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\market_scan.json")


class MarketScanner(Agent):
    name = "market_scanner"
    description = "Multi-TF + levels + gap analysis per deployed symbol every 90s"
    interval_seconds = 90
    default_enabled = True

    def _list_deployed_symbols(self) -> list[str]:
        cfg_dir = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
        out = []
        for p in cfg_dir.glob("*.json"):
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
                if (cfg.get("deployed_genome") or {}).get("id"):
                    out.append(p.stem)
            except Exception: continue
        return out

    def _tf_snapshot(self, mt5, symbol: str, tf, n: int = 60) -> dict:
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)
        if rates is None or len(rates) < 20: return {}
        h = rates["high"]; l = rates["low"]; c = rates["close"]
        # ATR
        trs = [max(float(h[i])-float(l[i]),
                    abs(float(h[i])-float(c[i-1])),
                    abs(float(l[i])-float(c[i-1])))
                for i in range(1, len(rates))]
        atr = sum(trs[-14:]) / 14
        # RSI
        diffs = [float(c[i])-float(c[i-1]) for i in range(1, len(c))]
        gains = [max(0, d) for d in diffs[-14:]]
        losses = [max(0, -d) for d in diffs[-14:]]
        ag = sum(gains)/14; al = sum(losses)/14
        rsi = 100 - 100/(1+(ag/al)) if al > 0 else 100
        # Bias from slope
        slope = (float(c[-1]) - float(c[-20])) / max(1e-9, atr)
        if slope > 0.5: bias = "UP"
        elif slope < -0.5: bias = "DOWN"
        else: bias = "RANGE"
        return {
            "current":     round(float(c[-1]), 5),
            "atr":         round(atr, 5),
            "rsi":         round(rsi, 1),
            "swing_high":  round(float(h.max()), 5),
            "swing_low":   round(float(l.min()), 5),
            "bias":        bias,
            "slope_atr":   round(slope, 2),
            "range_size":  round(float(h.max() - l.min()), 5),
        }

    def _levels(self, mt5, symbol: str) -> dict:
        """Key price levels: daily/weekly highs/lows + prev day close."""
        d1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 10)
        if d1 is None or len(d1) < 2: return {}
        today = d1[-1]; yest = d1[-2]
        week_h = max(float(b["high"]) for b in d1[-5:])
        week_l = min(float(b["low"])  for b in d1[-5:])
        return {
            "day_high":         round(float(today["high"]), 5),
            "day_low":          round(float(today["low"]),  5),
            "day_mid":          round((float(today["high"]) + float(today["low"])) / 2, 5),
            "day_open":         round(float(today["open"]), 5),
            "prev_day_close":   round(float(yest["close"]), 5),
            "prev_day_high":    round(float(yest["high"]),  5),
            "prev_day_low":     round(float(yest["low"]),   5),
            "week_high":        round(week_h, 5),
            "week_low":         round(week_l, 5),
        }

    def _gap(self, levels: dict, current: float) -> dict:
        """Detect open-gap state."""
        if not levels: return {"type": "NONE"}
        pcl = levels.get("prev_day_close", 0)
        dop = levels.get("day_open", 0)
        if not (pcl and dop): return {"type": "NONE"}
        size = abs(dop - pcl)
        size_pct = size / pcl * 100 if pcl else 0
        if size_pct < 0.05: return {"type": "NONE", "size_pct": round(size_pct, 3)}
        # Has price returned to prev close (filled)?
        if dop > pcl:
            filled = current <= pcl
            gtype = "UP"
        else:
            filled = current >= pcl
            gtype = "DOWN"
        return {
            "type":      gtype,
            "size":      round(size, 5),
            "size_pct":  round(size_pct, 3),
            "open_at":   dop,
            "prev_close": pcl,
            "filled":    filled,
            "to_fill":   round(abs(current - pcl), 5) if not filled else 0,
        }

    def _regime(self, tf_h1: dict, tf_h4: dict, atr_pct: float) -> str:
        """Classify regime from H1+H4."""
        h1_b = tf_h1.get("bias"); h4_b = tf_h4.get("bias")
        if h1_b == "UP" and h4_b == "UP":     return "TREND_UP"
        if h1_b == "DOWN" and h4_b == "DOWN": return "TREND_DOWN"
        if atr_pct < 0.1:                      return "DEAD"
        return "RANGE"

    def tick(self):
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
        except Exception:
            return

        symbols = self._list_deployed_symbols()
        out = {"updated_at": datetime.now(timezone.utc).isoformat(), "symbols": {}}
        tfs = [("M5", mt5.TIMEFRAME_M5),  ("M15", mt5.TIMEFRAME_M15),
               ("H1", mt5.TIMEFRAME_H1),  ("H4",  mt5.TIMEFRAME_H4),
               ("D1", mt5.TIMEFRAME_D1)]
        gap_found = []
        for sym in symbols:
            tick = mt5.symbol_info_tick(sym)
            if not tick: continue
            tf_data = {}
            for label, tf_const in tfs:
                tf_data[label] = self._tf_snapshot(mt5, sym, tf_const)
            levels = self._levels(mt5, sym)
            gap = self._gap(levels, tick.bid)
            h1_atr = (tf_data.get("H1") or {}).get("atr", 0)
            atr_pct = (h1_atr / tick.bid * 100) if tick.bid else 0
            regime = self._regime(tf_data.get("H1", {}), tf_data.get("H4", {}), atr_pct)
            out["symbols"][sym] = {
                "bid":    float(tick.bid),
                "ask":    float(tick.ask),
                "spread": round(float(tick.ask - tick.bid), 5),
                "tf":     tf_data,
                "levels": levels,
                "gap":    gap,
                "regime": regime,
                "atr_pct_price": round(atr_pct, 3),
            }
            if gap.get("type") in ("UP", "DOWN") and not gap.get("filled"):
                gap_found.append(f"{sym} {gap['type']} {gap.get('size_pct',0):.2f}%")

        SCAN_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCAN_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                              encoding="utf-8")

        if gap_found:
            emit_insight(self.name, "ACT",
                f"📐 unfilled gaps detected: {', '.join(gap_found[:5])}",
                data={"gaps": gap_found},
                action="gaps_detected")

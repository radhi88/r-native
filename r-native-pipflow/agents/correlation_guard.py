"""agents/correlation_guard.py — prevent doubling-down on correlated symbols.

EURUSD long + GBPUSD long = essentially the same bet (both anti-USD). If
both lose simultaneously you take double the hit. This agent monitors
open positions and blocks new entries that would over-concentrate
USD-direction exposure.

Maintains a correlation table:
  EUR/USD ↔ GBP/USD ↔ AUD/USD       (anti-USD bloc)
  USD/JPY ↔ USD/CHF ↔ USD/CAD       (pro-USD bloc)
  EUR/JPY ↔ GBP/JPY                   (anti-JPY bloc)
  BTC ↔ ETH                            (crypto bloc)
  XAU ↔ XAG                            (metal bloc)

When a position opens on any member of a bloc, OTHER bloc members get a
soft block applied (the executor's exposure_guard reads this).
"""
from __future__ import annotations

import json
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


CORRELATION_BLOCS = {
    "anti_usd":   {"EURUSDm", "GBPUSDm", "AUDUSDm"},
    "pro_usd":    {"USDJPYm", "USDCHFm", "USDCADm"},
    "anti_jpy":   {"EURJPYm", "GBPJPYm"},
    "crypto":     {"BTCUSDm", "ETHUSDm"},
    "metals":     {"XAUUSDm", "XAGUSDm"},
}

# 1 = same-direction bets (we want to block same-bloc same-side stacking)
# -1 = opposing bets (those would actually hedge — allow)
SIDE_CORRELATION = {
    "anti_usd":   1,
    "pro_usd":    1,
    "anti_jpy":   1,
    "crypto":     1,
    "metals":     1,
}

EXPOSURE_GUARD_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\correlation_blocks.json")


class CorrelationGuard(Agent):
    name = "correlation_guard"
    description = "Blocks new entries that would over-concentrate correlated exposure"
    interval_seconds = 30
    default_enabled = True

    MAX_SAME_BLOC_POSITIONS = 2   # at most 2 positions on the same correlation bloc

    def tick(self):
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
            positions = mt5.positions_get() or []
        except Exception: return

        r_pos = [p for p in positions if int(p.magic) == 20260605]
        if not r_pos:
            self._write_blocks({})
            return

        # Count per (bloc, side) currently held
        held = {}    # bloc → {BUY: n, SELL: n}
        for p in r_pos:
            side = "BUY" if p.type == 0 else "SELL"
            for bloc, members in CORRELATION_BLOCS.items():
                if p.symbol in members:
                    held.setdefault(bloc, {"BUY": 0, "SELL": 0})[side] += 1
                    break

        # For each bloc maxed out → block remaining symbols in same direction
        blocks = {}  # symbol → reason
        for bloc, counts in held.items():
            members = CORRELATION_BLOCS[bloc]
            for side in ("BUY", "SELL"):
                if counts[side] >= self.MAX_SAME_BLOC_POSITIONS:
                    # Find which symbols in this bloc DON'T have an open same-side
                    open_syms_side = {p.symbol for p in r_pos
                                       if (("BUY" if p.type == 0 else "SELL") == side)
                                          and p.symbol in members}
                    for sym in members:
                        if sym in open_syms_side: continue
                        blocks[f"{sym}_{side}"] = (
                            f"correlation bloc '{bloc}' has {counts[side]} {side} positions already"
                        )

        self._write_blocks(blocks)

        if blocks:
            emit_insight(self.name, "INFO",
                f"⛓ correlation: blocked {len(blocks)} (symbol,side) combos "
                f"due to held {sum(sum(c.values()) for c in held.values())} positions",
                data={"blocks": dict(list(blocks.items())[:5])})

    def _write_blocks(self, blocks: dict):
        EXPOSURE_GUARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPOSURE_GUARD_PATH.write_text(json.dumps({
            "blocks": blocks,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

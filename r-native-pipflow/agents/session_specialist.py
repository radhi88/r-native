"""agents/session_specialist.py — match symbols to their best trading session.

Different symbols come alive in different sessions:
  • Asian (00-08 UTC):    JPY pairs, AUD, NZD, gold
  • London (07-15 UTC):   EUR, GBP, CHF, oil, indices
  • NY (13-22 UTC):       USD pairs, BTC, US indices, gold US session
  • Overlap (13-15 UTC):  highest volatility — EVERYTHING

This agent monitors the current session and writes a preference score
0-100 per symbol that the executor uses to weight which symbols to
prioritize. Symbols in their natural session get boosted, off-session
symbols get suppressed (not blocked — just lower priority).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


SESSION_PREFS_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\session_preferences.json")

# Per-symbol session boost (multiplier; >1.0 = preferred this session)
SESSION_BOOSTS = {
    # Asian (00-08 UTC)
    "asian": {
        "USDJPYm": 1.3, "EURJPYm": 1.3, "GBPJPYm": 1.3, "AUDUSDm": 1.2,
        "XAUUSDm": 1.1, "BTCUSDm": 1.0, "ETHUSDm": 1.0,
        "EURUSDm": 0.7, "GBPUSDm": 0.7, "USDCHFm": 0.7,
    },
    # London (08-13 UTC)
    "london": {
        "EURUSDm": 1.3, "GBPUSDm": 1.3, "USDCHFm": 1.2, "EURJPYm": 1.2,
        "GBPJPYm": 1.2, "XAUUSDm": 1.1, "XAGUSDm": 1.1,
        "USDJPYm": 0.9, "AUDUSDm": 0.8, "BTCUSDm": 1.0,
    },
    # Overlap (13-15 UTC) — everything boosted
    "overlap": {
        s: 1.4 for s in ["EURUSDm","GBPUSDm","USDJPYm","AUDUSDm",
                          "USDCHFm","USDCADm","EURJPYm","GBPJPYm",
                          "XAUUSDm","XAGUSDm","BTCUSDm","ETHUSDm"]
    },
    # NY (15-22 UTC)
    "ny": {
        "EURUSDm": 1.2, "GBPUSDm": 1.2, "USDCADm": 1.3, "USDJPYm": 1.2,
        "BTCUSDm": 1.3, "ETHUSDm": 1.3, "XAUUSDm": 1.2,
        "AUDUSDm": 0.8, "EURJPYm": 0.9,
    },
    # Off-hours (22-00 UTC) — thin liquidity
    "offhours": {
        s: 0.6 for s in ["EURUSDm","GBPUSDm","USDJPYm","AUDUSDm","USDCHFm",
                          "USDCADm","EURJPYm","GBPJPYm","XAUUSDm","XAGUSDm"]
    } | {"BTCUSDm": 1.0, "ETHUSDm": 1.0},   # crypto trades 24/7
}


class SessionSpecialist(Agent):
    name = "session_specialist"
    description = "Boosts/suppresses symbol priority by trading session"
    interval_seconds = 600  # update every 10 min (session boundaries)
    default_enabled = True

    def _current_session(self) -> str:
        h = datetime.now(timezone.utc).hour
        if 13 <= h < 15:  return "overlap"
        if 8  <= h < 13:  return "london"
        if 15 <= h < 22:  return "ny"
        if 0  <= h < 8:   return "asian"
        return "offhours"

    def tick(self):
        sess = self._current_session()
        prefs = SESSION_BOOSTS.get(sess, {})
        SESSION_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SESSION_PREFS_PATH.write_text(json.dumps({
            "session": sess,
            "preferences": prefs,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2), encoding="utf-8")

        # Find best 3 + worst 3 for the report
        sorted_syms = sorted(prefs.items(), key=lambda x: -x[1])
        top3 = sorted_syms[:3]
        bot3 = sorted_syms[-3:]
        emit_insight(self.name, "INFO",
            f"🕐 session={sess.upper()} — boosting "
            f"{', '.join(f'{s}({m:.1f}x)' for s,m in top3)}, suppressing "
            f"{', '.join(f'{s}({m:.1f}x)' for s,m in bot3)}",
            data={"session": sess, "top": top3, "bottom": bot3})

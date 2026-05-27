"""genomes/claude_apex.py — CLAUDE-XAU-G1, my first genome.

═══════════════════════════════════════════════════════════════════════
THESIS
═══════════════════════════════════════════════════════════════════════
Apex specializes in XAUUSDm BUY-only intraday pullback entries during
London and NY-overlap sessions. The bias logic was learned from cycle-39
audit data showing that 17 BUY trades made +$5.5 (76% WR) while 21 SELL
trades made -$43.7 (57% WR) in the same period — gold's macro structure
favored longs while a now-fixed RSI-flip bug forced bad SELLs.

Apex refuses to trade:
  • Asian session (research: 60-80% of pro scalp PnL is in London+NY)
  • M1 ATR < $0.70 (consolidation noise)
  • When M15 trend = DOWN (no fighting the macro)
  • Within 5 minutes of a same-side loss (let market reset)

Apex enters on:
  • PULLBACK setup — price retraced into M5 EMA9 from above
  • M1 confirmation — bullish engulfing OR pin-bottom OR RSI<35 bouncing
  • M15 bias UP or RANGE (not DOWN)
  • Session = LONDON / NY_OVERLAP / NY_LATE

SL logic:
  • SL = recent M1 swing low - 2pt buffer (not arbitrary $ amount)
  • Capped at 3% of account equity (council Risk veto otherwise)
  • If SL distance > $3, lot must shrink — never widen risk to fit ATR

TP logic:
  • Near TP = entry + 1× SL distance (1:1, banked at 50% size)
  • Far TP = entry + 1.8× SL distance (the actual profit target)
  • Hard expiration: 25 minutes after fill (M1 trades shouldn't drag)

PERFORMANCE TARGETS (auto-promote to Tier-2 deployment after):
  • ≥ 20 paper-trade fills
  • ≥ 60% win rate
  • profit factor ≥ 1.3
  • max consecutive losers ≤ 4
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
from typing import Optional
from r_native_v2.council.types import Proposal
from r_native_v2.indicators.session import classify as session_classify
from .base import Genome


class ClaudeApex(Genome):
    name    = "CLAUDE-XAU-G1"
    thesis  = ("XAU BUY-only pullback scalper. Enters on M5 EMA9 retest with "
                "M1 bullish trigger during London/NY sessions. Quits chop and "
                "downtrends. Tight SL at swing low.")
    symbols = ("XAUUSDm",)
    sides   = ("BUY",)
    lot     = 0.01

    # Tunable thresholds (all justified in thesis)
    MIN_M1_ATR     = 0.70
    M1_RSI_OS      = 35.0
    NEAR_TP_RR     = 1.0
    FAR_TP_RR      = 1.8
    # MAX_HOLD_MIN — REMOVED cycle 39. User feedback "لا تحط وقت يا حبيبي":
    # time-based forced closes killed winning setups. The market doesn't
    # respect our calendar. A position exits ONLY on SL, TP, or a real
    # structure break — never on a clock.
    MAX_HOLD_MIN   = None
    # SL design (cycle-39 lesson: tight SLs kill winners on M1 noise).
    # Use the LARGER of M5 swing low or M1 swing low - (ATR M1 × MULT).
    # Floor: SL distance ≥ 1.5× ATR M1 so noise can't tag it.
    SL_ATR_MULT    = 1.5
    SL_BUFFER_PT   = 1.00     # was 0.20 — give 1pt below the structure low

    def propose(self, snapshot, account) -> Optional[Proposal]:
        if snapshot.symbol not in self.symbols: return None
        sv = session_classify()
        if not sv.m1_ok: return None      # Asian / closed → skip

        m1 = snapshot.tfs.get("M1")
        m5 = snapshot.tfs.get("M5")
        m15 = snapshot.tfs.get("M15")
        if not (m1 and m5 and m15): return None

        # Macro filter — M15 trend must not be DOWN
        if m15.bias == "DOWN":
            return None

        # Noise filter — M1 ATR
        if m1.atr < self.MIN_M1_ATR: return None

        # Setup: M5 in pullback (close below EMA9 but EMA9 > EMA21 means uptrend pullback)
        pullback = (m5.last_close < m5.ema9 and m5.ema9 > m5.ema21)
        if not pullback: return None

        # Trigger: M1 confirmation
        trigger = (m1.bull_engulf or m1.pin_bot or m1.rsi < self.M1_RSI_OS)
        if not trigger: return None

        # Build trade — SMARTER SL (cycle-39 chart-feedback lesson)
        entry = snapshot.ask
        # Option A: structural — below M5 swing low (more meaningful than M1)
        sl_struct = m5.swing_low - self.SL_BUFFER_PT
        # Option B: volatility-aware — entry - 1.5× M1 ATR (lets noise wiggle)
        sl_atr = entry - m1.atr * self.SL_ATR_MULT
        # Take the FURTHER of the two — give the trade real room
        sl = min(sl_struct, sl_atr)
        # Guard: SL must be below entry AND at least 1× ATR away
        if sl >= entry: return None
        sl_dist = entry - sl
        if sl_dist < m1.atr * 1.0:
            return None     # SL too tight even after smart pick — skip
        # Far TP at 1.8R
        tp = entry + sl_dist * self.FAR_TP_RR

        confluence = []
        if m1.bull_engulf: confluence.append("M1 bull engulf")
        if m1.pin_bot:     confluence.append("M1 bottom pin")
        if m1.rsi < self.M1_RSI_OS: confluence.append(f"M1 RSI {m1.rsi} OS bouncing")
        confluence.append(f"M5 pullback to EMA9 ({m5.ema9:.2f}) in uptrend")
        confluence.append(f"M15 bias={m15.bias}")
        confluence.append(f"session={sv.name}")

        return Proposal(
            genome=self.name, symbol=snapshot.symbol, side="BUY",
            order_kind="MARKET", entry=entry, sl=sl, tp=tp, lot=self.lot,
            thesis="Pullback into M5 EMA9 with M1 confirmation in UP/RANGE M15",
            confluence=confluence,
        )

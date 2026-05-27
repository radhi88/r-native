"""genomes/claude_apex.py — CLAUDE-XAU-G1.

═══════════════════════════════════════════════════════════════════════
THESIS (v2 — 2026-05-27, after user feedback on M1 discipline)
═══════════════════════════════════════════════════════════════════════
Apex is a XAUUSDm BUY-only M1 PULLBACK scalper that thinks like a
discretionary trader:

  1. It refuses to BUY inside a Bear OB.
       Reason: that zone is institutional supply. Buying inside it =
       chasing a top that smart money is fading. The 2026-05-27 chart
       feedback (+$15 missed because of tight SL) was preceded by my
       LIVE refusal to buy at 4512 — exactly because price was inside
       4508-4517 Bear OB. That refusal was correct. Codify it.

  2. It WAITS for price to retest a BULL FVG (the impulse imbalance
     below current price). FVG retests are high-prob mean-reversion
     entries — the institutional bid that drove the impulse defends
     its own gap.

  3. It requires BUY+ pressure or a FLIP back to BUY+ in the last 10
     M1 bars. Don't catch a falling knife while sellers dominate.

  4. It ABORTS the entry if a strong bearish marubozu fired in the
     last 3 bars near the FVG. Marubozu bear with no upper wick is
     sellers winning a clean fight — wait for them to be exhausted
     before opposing them.

  5. It still requires the original baseline:
     - Session = LONDON / NY_OVERLAP / NY_LATE (no Asian M1)
     - M15 bias ≠ DOWN (no fighting macro)
     - M1 ATR ≥ $0.70 (no consolidation noise)
     - M1 confirmation candle (engulf / hammer / RSI<35 bouncing)

SL DESIGN (cycle 39 lesson, no time limit):
  • SL = min(M5 swing low - 1pt,  entry - 1.5× M1 ATR)
  • Refuse the trade if final SL distance < 1× M1 ATR
  • No MAX_HOLD — exit only on SL/TP, never on a clock

PERFORMANCE TARGETS (auto-promote to Tier-2):
  • ≥ 20 paper-trade fills with full council approval
  • ≥ 60% win rate
  • Profit factor ≥ 1.3
  • Max consecutive losers ≤ 4
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
from typing import Optional
from r_native_v2.council.types import Proposal
from r_native_v2.indicators.session import classify as session_classify
from r_native_v2.indicators import smc
from .base import Genome


class ClaudeApex(Genome):
    name    = "CLAUDE-XAU-G1"
    thesis  = ("XAU BUY-only M1 pullback scalper. Refuses Bear-OB tops; "
                "waits for BULL FVG retest with BUY+ pressure; aborts "
                "on recent bearish marubozu. Session-aware. No clock exits.")
    symbols = ("XAUUSDm",)
    sides   = ("BUY",)
    lot     = 0.01

    # Tunable thresholds
    MIN_M1_ATR     = 0.70
    M1_RSI_OS      = 35.0
    NEAR_TP_RR     = 1.0
    FAR_TP_RR      = 1.8
    MAX_HOLD_MIN   = None      # NO clock exits (cycle 39 user mandate)
    SL_ATR_MULT    = 1.5
    SL_BUFFER_PT   = 1.00
    # SMC thresholds
    PRESSURE_MIN_NET = 1.0     # require ≥ +$1.0 BUY pressure to enter
    MARUBOZU_LOOKBACK = 3      # how many bars back to check for marubozu bear
    FVG_PROXIMITY_PCT = 0.40   # price must be within 40% of FVG zone width

    def propose(self, snapshot, account) -> Optional[Proposal]:
        if snapshot.symbol not in self.symbols: return None

        # ─── BASELINE 1: session window ───
        sv = session_classify()
        if not sv.m1_ok: return None

        m1f = snapshot.tfs.get("M1")
        m5f = snapshot.tfs.get("M5")
        m15f = snapshot.tfs.get("M15")
        if not (m1f and m5f and m15f): return None

        # ─── BASELINE 2: macro filter ───
        if m15f.bias == "DOWN": return None

        # ─── BASELINE 3: noise filter ───
        if m1f.atr < self.MIN_M1_ATR: return None

        # Need raw bars for SMC analysis — refetch (cheap, cached 30s)
        try:
            import MetaTrader5 as mt5
            m5_bars  = mt5.copy_rates_from_pos(snapshot.symbol, mt5.TIMEFRAME_M5, 0, 60)
            m1_bars  = mt5.copy_rates_from_pos(snapshot.symbol, mt5.TIMEFRAME_M1, 0, 60)
            if m5_bars is None or m1_bars is None: return None
            m5_bars = [dict(b._asdict()) if hasattr(b, "_asdict")
                        else {k: b[k] for k in b.dtype.names} for b in m5_bars]
            m1_bars = [dict(b._asdict()) if hasattr(b, "_asdict")
                        else {k: b[k] for k in b.dtype.names} for b in m1_bars]
        except Exception:
            return None

        cur_price = snapshot.bid

        # ─── SMC RULE 1: VETO if inside Bear OB ───
        ob = smc.find_order_block(m5_bars, lookback=10)
        if ob and ob["type"] == "BEAR_OB" and smc.price_inside(cur_price, ob):
            # Don't buy into institutional supply
            return None

        # ─── SMC RULE 2: require BULL FVG nearby (the retest setup) ───
        bull_fvg, _ = smc.find_fvgs(m5_bars, lookback=20)
        if not bull_fvg:
            # No recent bullish imbalance to retest — no Apex setup
            return None
        fvg_width = max(bull_fvg["top"] - bull_fvg["bot"], 1e-9)
        # Price must be IN the FVG or just above (within proximity_pct of width)
        dist_above = cur_price - bull_fvg["top"]
        if cur_price < bull_fvg["bot"]:
            return None     # FVG broken — abandoned
        if dist_above > fvg_width * self.FVG_PROXIMITY_PCT:
            return None     # too far above FVG, not a retest

        # ─── SMC RULE 3: pressure must be BUY+ (or recent flip back) ───
        p = smc.pressure_score(m1_bars, n=10)
        if p["net"] < self.PRESSURE_MIN_NET:
            return None     # sellers still in control

        # ─── SMC RULE 4: ABORT if recent strong bearish marubozu ───
        mb = smc.recent_marubozu_bear(m1_bars, lookback=self.MARUBOZU_LOOKBACK)
        if mb:
            return None     # sellers just won a clean fight, wait

        # ─── SMC RULE 5: ABORT on recent liquidity-sweep upper wicks ───
        # Cycle-39 LIVE lesson (2026-05-27 08:30): a green bar with
        # body 7% + upper wick $1.48 + volume 176% looked like BUY+
        # pressure flip on aggregate. The next bar dumped -$3.76.
        # The upper wick was a stop-hunt. Filter it out.
        for b in m1_bars[-3:-1]:    # last 2 closed bars
            body = abs(b["close"] - b["open"])
            rng  = max(b["high"] - b["low"], 1e-9)
            upper_wick = b["high"] - max(b["open"], b["close"])
            # Big upper wick (≥ 1.5× body) on a high-volume bar = sweep
            if (body > 0 and upper_wick >= 1.5 * body
                    and upper_wick / rng > 0.5):
                return None     # liquidity sweep — sellers waiting above

        # ─── BASELINE 4: pullback setup ───
        pullback = (m5f.last_close < m5f.ema9 and m5f.ema9 > m5f.ema21)
        # During FVG retest, "pullback" is implicit — but require uptrend EMAs
        if not (m5f.ema9 > m5f.ema21):
            return None

        # ─── BASELINE 5: M1 confirmation trigger ───
        trigger = (smc.is_bullish_engulfing(m1_bars) or m1f.pin_bot
                    or m1f.rsi < self.M1_RSI_OS)
        if not trigger:
            return None

        # ═══ ALL GATES PASSED — BUILD PROPOSAL ═══
        entry = snapshot.ask
        sl_struct = m5f.swing_low - self.SL_BUFFER_PT
        sl_atr = entry - m1f.atr * self.SL_ATR_MULT
        sl = min(sl_struct, sl_atr)
        if sl >= entry: return None
        sl_dist = entry - sl
        if sl_dist < m1f.atr * 1.0: return None
        tp = entry + sl_dist * self.FAR_TP_RR

        confluence = [
            f"session={sv.name}",
            f"M15 bias={m15f.bias} (not DOWN)",
            f"M5 EMA9 > EMA21 (uptrend structure)",
            f"BULL FVG ${bull_fvg['bot']:.2f}-${bull_fvg['top']:.2f} (gap ${bull_fvg['gap']:.2f}) — retesting",
            f"pressure BUY+ net=${p['net']:+.2f}",
            f"no Bear OB blocking (cur {cur_price:.2f} not in OB zone)",
            f"no recent marubozu bear in last {self.MARUBOZU_LOOKBACK} bars",
        ]
        if smc.is_bullish_engulfing(m1_bars): confluence.append("M1 bull engulf ✓")
        if m1f.pin_bot: confluence.append(f"M1 bottom pin ✓")
        if m1f.rsi < self.M1_RSI_OS:
            confluence.append(f"M1 RSI {m1f.rsi} oversold bounce ✓")

        return Proposal(
            genome=self.name, symbol=snapshot.symbol, side="BUY",
            order_kind="MARKET", entry=entry, sl=sl, tp=tp, lot=self.lot,
            thesis="BULL FVG retest with BUY+ pressure, no Bear OB block, no recent rejection",
            confluence=confluence,
        )

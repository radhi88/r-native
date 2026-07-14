"""
y_scalp_backtest.py — "Y" retry of dip-buyer matching user's MANUAL style.

User said: "اشتري بشكل هجومي بلوت صغير 0.01 ... وعندما اري اي ربح اغلقه"
(buy aggressively with tiny 0.01 lot, close on ANY profit)

Therefore:
  • lot              = 0.01 (smallest)
  • profit_target    = $0.03 (≈ 30pt move, exit immediately)
  • SL               = tight: 60pt fixed (NOT atr-based — atr-based gave 400pt SLs)
  • max_hold_minutes = 3 (close fast, don't bag-hold)
  • min_dip_score    = 85 (only the best 5% of signals)
  • min_drop_atr     = 2.0
  • cooldown         = 300s (don't over-trade)

Backtests this single configuration on 30 days M1 — no gene pool noise.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import MetaTrader5 as mt5

from friday_v3.indicators.dip_detector import _rsi, _stochastic_k, _atr, _is_hammer, _swing_low

SYMBOL          = "XAUUSDm"
ROOT            = Path(r"C:\Users\Radhi\MT5\friday_v3")
REPORT          = ROOT / "data" / "y_scalp_report.json"
TRADES_CSV      = ROOT / "data" / "y_scalp_trades.csv"

DAYS_BACK       = 30
INITIAL_BALANCE = 50.0

# ─────────────────── Y CONFIG ───────────────────
LOT                  = 0.01
PROFIT_TARGET_USD    = 0.03
SL_PT_FIXED          = 60       # fixed 60-pt SL (loss ≈ $0.60 per trade @ 0.01 lot)
MAX_HOLD_MIN         = 3
MIN_DIP_SCORE        = 85
MIN_DROP_ATR         = 2.0
MAX_RSI              = 25
COOLDOWN_SEC         = 300
REQUIRE_HAMMER       = True
# ────────────────────────────────────────────────

SPREAD_PT            = 300
POINT                = 0.01
PT_VALUE_PER_LOT     = 100


@dataclass
class YTrade:
    open_idx:    int
    close_idx:   int
    entry:       float
    exit:        float
    sl:          float
    pl_usd:      float
    win:         bool
    age_bars:    int
    exit_reason: str
    dip_score:   int


def detect_dip_at(bars, i):
    """Recompute the dip signal looking only at bars[0..i]."""
    if i < 25: return None
    win = bars[max(0, i - 39):i + 1]
    o, h, l, c, v = win["open"], win["high"], win["low"], win["close"], win["tick_volume"]
    recent_peak = float(h[-5:].max())
    current = float(c[-1])
    drop_pt = (recent_peak - current) / POINT
    if drop_pt < 30: return None
    atr_pt = _atr(h, l, c, 14) / POINT
    drop_atr = drop_pt / atr_pt if atr_pt > 0 else 0
    rsi = _rsi(c, 14)
    stoch = _stochastic_k(h, l, c, 14)
    avg_vol = v[-20:-1].mean() if len(v) >= 20 else v.mean()
    vsurge = float(v[-1] / avg_vol) if avg_vol > 0 else 1.0
    hammer = _is_hammer(float(o[-1]), float(h[-1]), float(l[-1]), float(c[-1]))
    dist_swing = (current - _swing_low(l, 20)) / POINT

    score = 0
    if drop_atr >= 1.5: score += 25
    elif drop_atr >= 1.0: score += 15
    elif drop_atr >= 0.7: score += 8
    if rsi < 25: score += 25
    elif rsi < 35: score += 15
    if stoch < 20: score += 15
    elif stoch < 35: score += 8
    if vsurge >= 2.0: score += 15
    elif vsurge >= 1.5: score += 8
    score += 10   # multi-tf assumed in backtest
    if hammer: score += 10
    if 0 < dist_swing < 30: score += 10
    score = min(100, score)
    return {"score": score, "drop_atr": drop_atr, "rsi": rsi,
            "hammer": hammer, "drop_pt": drop_pt}


def run():
    print(f"=== Y SCALP Backtest — {DAYS_BACK} days, {SYMBOL} M1 ===\n")
    print(f"Config: lot={LOT}, target=${PROFIT_TARGET_USD}, SL={SL_PT_FIXED}pt, hold={MAX_HOLD_MIN}min")
    print(f"        min_score={MIN_DIP_SCORE}, min_drop_atr={MIN_DROP_ATR}, max_rsi={MAX_RSI}, hammer={REQUIRE_HAMMER}\n")

    if not mt5.initialize():
        print("MT5 init failed"); return

    from_ts = datetime.now() - timedelta(days=DAYS_BACK)
    bars = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, from_ts, datetime.now())
    if bars is None or len(bars) < 100:
        print("Not enough bars"); mt5.shutdown(); return
    print(f"  ✓ {len(bars):,} M1 bars loaded\n")

    trades: list[YTrade] = []
    last_trade_close_idx = -10000

    for i in range(50, len(bars)):
        # Cooldown
        if (i - last_trade_close_idx) < (COOLDOWN_SEC // 60):
            continue
        sig = detect_dip_at(bars, i)
        if not sig: continue
        if sig["score"] < MIN_DIP_SCORE: continue
        if sig["drop_atr"] < MIN_DROP_ATR: continue
        if sig["rsi"] > MAX_RSI: continue
        if REQUIRE_HAMMER and not sig["hammer"]: continue

        # Enter at ask (close + half-spread)
        entry = float(bars[i]["close"]) + SPREAD_PT * POINT / 2
        sl    = entry - SL_PT_FIXED * POINT

        exit_idx = i; exit_price = entry; reason = "open"; pl_usd = 0
        for j in range(i + 1, min(i + MAX_HOLD_MIN + 1, len(bars))):
            bar = bars[j]
            low = float(bar["low"])
            bid_now = float(bar["close"]) - SPREAD_PT * POINT / 2
            pl_pts  = (bid_now - entry) / POINT
            pl_usd  = pl_pts * LOT * (PT_VALUE_PER_LOT / 100)
            # SL first
            if low <= sl:
                exit_idx = j; exit_price = sl
                pl_pts = (sl - entry) / POINT
                pl_usd = pl_pts * LOT * (PT_VALUE_PER_LOT / 100)
                reason = "SL"
                break
            if pl_usd >= PROFIT_TARGET_USD:
                exit_idx = j; exit_price = bid_now; reason = "TP"
                break
        else:
            exit_idx = min(i + MAX_HOLD_MIN, len(bars) - 1)
            exit_price = float(bars[exit_idx]["close"]) - SPREAD_PT * POINT / 2
            pl_usd = ((exit_price - entry) / POINT) * LOT * (PT_VALUE_PER_LOT / 100)
            reason = "timeout"

        trades.append(YTrade(
            open_idx=i, close_idx=exit_idx, entry=entry, exit=exit_price, sl=sl,
            pl_usd=round(pl_usd, 4), win=(pl_usd > 0),
            age_bars=exit_idx - i, exit_reason=reason, dip_score=sig["score"]
        ))
        last_trade_close_idx = exit_idx

    mt5.shutdown()

    if not trades:
        report = {"verdict": "NO_TRADES", "total_trades": 0,
                  "note": "Filters too strict — no entries triggered"}
    else:
        wins   = [t for t in trades if t.win]
        losses = [t for t in trades if not t.win]
        net    = sum(t.pl_usd for t in trades)
        wr     = len(wins) / len(trades) * 100
        gw     = sum(t.pl_usd for t in wins)
        gl     = abs(sum(t.pl_usd for t in losses))
        pf     = gw / gl if gl > 0 else 0
        bal, peak, dd = INITIAL_BALANCE, INITIAL_BALANCE, 0
        for t in trades:
            bal += t.pl_usd
            peak = max(peak, bal)
            dd = max(dd, peak - bal)
        verdict = "PASS" if (wr >= 50 and pf >= 1.5 and dd <= INITIAL_BALANCE * 0.30) else "FAIL"
        report = {
            "ts":            datetime.utcnow().isoformat(),
            "days":          DAYS_BACK,
            "symbol":        SYMBOL,
            "strategy":      "Y-SCALP (tight SL + tiny target)",
            "config":        {"lot": LOT, "target_usd": PROFIT_TARGET_USD,
                              "sl_pt": SL_PT_FIXED, "hold_min": MAX_HOLD_MIN,
                              "min_score": MIN_DIP_SCORE, "min_drop_atr": MIN_DROP_ATR,
                              "max_rsi": MAX_RSI, "require_hammer": REQUIRE_HAMMER,
                              "cooldown_sec": COOLDOWN_SEC},
            "total_trades":  len(trades),
            "wins":          len(wins),
            "losses":        len(losses),
            "win_rate":      round(wr, 2),
            "profit_factor": round(pf, 2),
            "net_pl":        round(net, 2),
            "max_drawdown":  round(dd, 2),
            "avg_win":       round(gw / max(1, len(wins)), 4),
            "avg_loss":      round(-gl / max(1, len(losses)), 4),
            "exits_by_reason": {r: sum(1 for t in trades if t.exit_reason == r)
                                for r in {"SL", "TP", "timeout"}},
            "verdict":       verdict,
            "criteria":      "WR>=50%, PF>=1.5, DD<=30%",
        }

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(TRADES_CSV, "w", encoding="utf-8") as f:
        f.write("open_idx,close_idx,entry,exit,sl,pl_usd,win,age_bars,exit_reason,dip_score\n")
        for t in trades:
            f.write(f"{t.open_idx},{t.close_idx},{t.entry:.2f},{t.exit:.2f},{t.sl:.2f},"
                    f"{t.pl_usd},{int(t.win)},{t.age_bars},{t.exit_reason},{t.dip_score}\n")

    print(f"\n{'='*60}\n  Y-SCALP RESULTS\n{'='*60}")
    for k, v in report.items():
        print(f"  {k:18}: {v}")


if __name__ == "__main__":
    run()

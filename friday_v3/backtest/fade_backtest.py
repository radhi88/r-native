"""
fade_backtest.py — FADE the dip-buy signal.

KEY DISCOVERY from swing_scalp_backtest: 141 high-quality dip signals
yielded only 8 reversals (5.67%). Gold dips CONTINUE 94% of the time.

Therefore: when the dip detector says "BUY the dip", we SELL instead.
Expected: ~94% WR on the same setups.

Same entry filters as swing-scalp, but reversed direction.
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
REPORT          = ROOT / "data" / "fade_report.json"
TRADES_CSV      = ROOT / "data" / "fade_trades.csv"

DAYS_BACK       = 30
INITIAL_BALANCE = 50.0

LOT                  = 0.01
PROFIT_TARGET_USD    = 0.50      # 500pt continuation in our favor
SL_USD               = 0.30      # 300pt against = mean-reversion bounce
MAX_HOLD_MIN         = 60
MIN_DIP_SCORE        = 70
MIN_DROP_ATR         = 1.5
MAX_RSI              = 30
COOLDOWN_SEC         = 900


@dataclass
class FTrade:
    open_idx:    int
    close_idx:   int
    entry:       float
    exit:        float
    sl:          float
    target:      float
    pl_usd:      float
    win:         bool
    age_bars:    int
    exit_reason: str
    dip_score:   int


def detect_dip_at(bars, i, point):
    if i < 25: return None
    win = bars[max(0, i - 39):i + 1]
    o, h, l, c, v = win["open"], win["high"], win["low"], win["close"], win["tick_volume"]
    recent_peak = float(h[-5:].max())
    current = float(c[-1])
    drop_pt = (recent_peak - current) / point
    if drop_pt < 100: return None
    atr_pt = _atr(h, l, c, 14) / point
    drop_atr = drop_pt / atr_pt if atr_pt > 0 else 0
    rsi = _rsi(c, 14)
    stoch = _stochastic_k(h, l, c, 14)
    avg_vol = v[-20:-1].mean() if len(v) >= 20 else v.mean()
    vsurge = float(v[-1] / avg_vol) if avg_vol > 0 else 1.0
    hammer = _is_hammer(float(o[-1]), float(h[-1]), float(l[-1]), float(c[-1]))
    dist_swing = (current - _swing_low(l, 20)) / point

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
    score += 10
    if hammer: score += 10
    if 0 < dist_swing < 30: score += 10
    return {"score": min(100, score), "drop_atr": drop_atr, "rsi": rsi,
            "hammer": hammer, "drop_pt": drop_pt}


def run():
    print(f"=== FADE Backtest — SELL the 'buy the dip' signal ===\n")
    if not mt5.initialize():
        print("MT5 init failed"); return
    sym  = mt5.symbol_info(SYMBOL)
    tick = mt5.symbol_info_tick(SYMBOL)
    if not sym or not tick:
        print("Symbol missing"); mt5.shutdown(); return

    POINT         = sym.point
    CONTRACT_SIZE = sym.trade_contract_size
    SPREAD_PRICE  = max(tick.ask - tick.bid, 0.30)

    target_delta = PROFIT_TARGET_USD / (LOT * CONTRACT_SIZE)
    sl_delta     = SL_USD / (LOT * CONTRACT_SIZE)

    from_ts = datetime.now() - timedelta(days=DAYS_BACK)
    bars = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M5, from_ts, datetime.now())
    if bars is None or len(bars) < 100:
        print("Not enough bars"); mt5.shutdown(); return
    print(f"  ✓ {len(bars):,} M5 bars  spread={SPREAD_PRICE:.3f}\n")

    trades: list[FTrade] = []
    last_close_idx = -10000
    cooldown_bars = max(1, COOLDOWN_SEC // 300)

    for i in range(50, len(bars)):
        if (i - last_close_idx) < cooldown_bars: continue
        sig = detect_dip_at(bars, i, POINT)
        if not sig: continue
        if sig["score"] < MIN_DIP_SCORE: continue
        if sig["drop_atr"] < MIN_DROP_ATR: continue
        if sig["rsi"] > MAX_RSI: continue

        # SELL at bid (we get bid when shorting)
        entry  = float(bars[i]["close"]) - SPREAD_PRICE / 2
        sl     = entry + sl_delta           # SL above entry for short
        target = entry - target_delta       # TP below entry

        exit_idx = i; exit_price = entry; reason = "open"; pl_usd = 0
        max_j = min(i + (MAX_HOLD_MIN // 5) + 1, len(bars))
        for j in range(i + 1, max_j):
            bar = bars[j]
            low  = float(bar["low"])
            high = float(bar["high"])
            ask_now  = float(bar["close"]) + SPREAD_PRICE / 2

            # SL on a short = high price reaches sl
            ask_high = high + SPREAD_PRICE / 2
            if ask_high >= sl:
                exit_idx = j; exit_price = sl
                pl_usd = (entry - sl) * LOT * CONTRACT_SIZE   # short PnL
                reason = "SL"; break

            # TP on a short = low price reaches target
            ask_low = low + SPREAD_PRICE / 2
            if ask_low <= target:
                exit_idx = j; exit_price = target
                pl_usd = (entry - target) * LOT * CONTRACT_SIZE
                reason = "TP"; break
        else:
            exit_idx = min(i + (MAX_HOLD_MIN // 5), len(bars) - 1)
            exit_price = float(bars[exit_idx]["close"]) + SPREAD_PRICE / 2
            pl_usd = (entry - exit_price) * LOT * CONTRACT_SIZE
            reason = "timeout"

        trades.append(FTrade(
            open_idx=i, close_idx=exit_idx, entry=entry, exit=exit_price, sl=sl,
            target=target, pl_usd=round(pl_usd, 4), win=(pl_usd > 0),
            age_bars=exit_idx - i, exit_reason=reason, dip_score=sig["score"]
        ))
        last_close_idx = exit_idx

    mt5.shutdown()

    if not trades:
        report = {"verdict": "NO_TRADES", "total_trades": 0}
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
            "ts":              datetime.utcnow().isoformat(),
            "days":            DAYS_BACK,
            "symbol":          SYMBOL,
            "strategy":        "FADE (sell the buy-the-dip signal)",
            "total_trades":    len(trades),
            "wins":            len(wins),
            "losses":          len(losses),
            "win_rate":        round(wr, 2),
            "profit_factor":   round(pf, 2),
            "net_pl":          round(net, 2),
            "max_drawdown":    round(dd, 2),
            "avg_win":         round(gw / max(1, len(wins)), 4),
            "avg_loss":        round(-gl / max(1, len(losses)), 4),
            "exits_by_reason": {r: sum(1 for t in trades if t.exit_reason == r)
                                for r in {"SL", "TP", "timeout"}},
            "verdict":         verdict,
            "criteria":        "WR>=50%, PF>=1.5, DD<=30%",
        }

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(TRADES_CSV, "w", encoding="utf-8") as f:
        f.write("open_idx,close_idx,entry,exit,sl,target,pl_usd,win,age_bars,exit_reason,dip_score\n")
        for t in trades:
            f.write(f"{t.open_idx},{t.close_idx},{t.entry:.3f},{t.exit:.3f},{t.sl:.3f},"
                    f"{t.target:.3f},{t.pl_usd},{int(t.win)},{t.age_bars},{t.exit_reason},{t.dip_score}\n")

    print(f"\n{'='*60}\n  FADE RESULTS\n{'='*60}")
    for k, v in report.items():
        print(f"  {k:18}: {v}")


if __name__ == "__main__":
    run()

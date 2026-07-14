"""
backtest/runner.py — Replay last 30 days M1 history against FRIDAY v3 strategy.

For each historical bar:
  1. Reconstruct what dip_detector would have said
  2. Ask the gene pool which genes would have approved
  3. Pick best gene's parameters
  4. Simulate trade: track entry, SL/TP, exits
  5. Compute results: win rate, profit factor, drawdown, sharpe

Writes friday_v3/data/backtest_report.json + a CSV of every simulated trade.
"""
from __future__ import annotations
import json
import time
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import MetaTrader5 as mt5

from friday_v3.core.gene_pool import GenePool
from friday_v3.indicators.dip_detector import (
    DipSignal, _rsi, _stochastic_k, _atr, _is_hammer, _swing_low
)

SYMBOL = "XAUUSDm"
ROOT   = Path(r"C:\Users\Radhi\MT5\friday_v3")
REPORT = ROOT / "data" / "backtest_report.json"
TRADES = ROOT / "data" / "backtest_trades.csv"

DAYS_BACK         = 30
INITIAL_BALANCE   = 50.0
SPREAD_PT         = 300
POINT             = 0.01
PT_VALUE_PER_LOT  = 100   # $1 per pip on gold at 1.0 lot ≈ 100 points


@dataclass
class SimTrade:
    open_idx:     int
    close_idx:    int
    gene_id:      str
    entry:        float
    exit:         float
    sl:           float
    tp_target:    float
    lot:          float
    pl_usd:       float
    win:          bool
    age_bars:     int
    exit_reason:  str
    dip_score:    int
    dip_drop_atr: float


def reconstruct_dip_signal_at(bars: np.ndarray, idx: int) -> DipSignal:
    """Replay dip detection logic on bars up to (and including) bars[idx]."""
    if idx < 25: return DipSignal(reasons=["not enough history at idx"])
    win = bars[max(0, idx - 39):idx + 1]    # 40 bars max ending at idx
    o = win["open"]; h = win["high"]; l = win["low"]; c = win["close"]; v = win["tick_volume"]

    sig = DipSignal()
    recent_peak = float(h[-5:].max())
    current = float(c[-1])
    drop_pt = (recent_peak - current) / POINT
    sig.drop_pt = round(drop_pt, 1)
    atr_pt = _atr(h, l, c, 14) / POINT
    sig.drop_atr = round(drop_pt / atr_pt, 2) if atr_pt > 0 else 0
    if drop_pt < 30:
        sig.quality = "NONE"; return sig

    sig.rsi_m1  = _rsi(c, 14)
    sig.rsi_m5  = sig.rsi_m1   # simplified — no M5 in backtest yet
    sig.stoch_k = _stochastic_k(h, l, c, 14)
    avg_vol = v[-20:-1].mean() if len(v) >= 20 else v.mean()
    sig.volume_surge = round(float(v[-1] / avg_vol), 2) if avg_vol > 0 else 1.0
    sig.has_hammer = _is_hammer(float(o[-1]), float(h[-1]), float(l[-1]), float(c[-1]))
    sig.multi_tf_aligned = True   # assumed in backtest
    sig.distance_to_swing_low_pt = round((current - _swing_low(l, 20)) / POINT, 1)

    score = 0
    reasons = []
    if sig.drop_atr >= 1.5: score += 25
    elif sig.drop_atr >= 1.0: score += 15
    elif sig.drop_atr >= 0.7: score += 8
    if sig.rsi_m1 < 25: score += 25
    elif sig.rsi_m1 < 35: score += 15
    if sig.stoch_k < 20: score += 15
    elif sig.stoch_k < 35: score += 8
    if sig.volume_surge >= 2.0: score += 15
    elif sig.volume_surge >= 1.5: score += 8
    if sig.multi_tf_aligned: score += 10
    if sig.has_hammer: score += 10
    if 0 < sig.distance_to_swing_low_pt < 30: score += 10

    score = min(100, score)
    sig.score = score
    if score >= 75: sig.quality = "STRONG"; sig.suggested_lot_factor = 1.5
    elif score >= 50: sig.quality = "MEDIUM"; sig.suggested_lot_factor = 1.0
    elif score >= 30: sig.quality = "WEAK"; sig.suggested_lot_factor = 0.5
    else: sig.quality = "NONE"; sig.suggested_lot_factor = 0
    return sig


def simulate_trade(bars: np.ndarray, entry_idx: int, gene, sig: DipSignal) -> SimTrade:
    """From entry_idx forward, simulate the trade until exit (SL/TP/max_hold)."""
    entry_bar = bars[entry_idx]
    entry_price = float(entry_bar["close"]) + SPREAD_PT * POINT / 2   # buy at ask = mid + half spread

    atr_pt = max(1, sig.drop_pt / max(0.1, sig.drop_atr))
    sl_pt  = atr_pt * gene.dna.sl_atr_mult
    sl     = entry_price - sl_pt * POINT
    # gene's lot
    lot = gene.dna.lot_base * sig.suggested_lot_factor

    target_usd = gene.dna.profit_target_usd
    max_hold = gene.dna.max_hold_minutes
    exit_idx = entry_idx
    exit_price = entry_price
    exit_reason = "open"
    pl_usd = 0

    for i in range(entry_idx + 1, min(entry_idx + max_hold + 1, len(bars))):
        bar = bars[i]
        low = float(bar["low"])
        high = float(bar["high"])
        # Compute P/L at this bar's close (mid)
        bid_now = float(bar["close"]) - SPREAD_PT * POINT / 2
        pl_pts  = (bid_now - entry_price) / POINT
        pl_usd  = pl_pts * lot * (PT_VALUE_PER_LOT / 100)   # gold scaling
        # Check SL hit intra-bar
        if low <= sl:
            exit_idx = i
            exit_price = sl
            pl_pts = (sl - entry_price) / POINT
            pl_usd = pl_pts * lot * (PT_VALUE_PER_LOT / 100)
            exit_reason = "SL"
            break
        # Profit target — using bid for conservative
        if pl_usd >= target_usd:
            exit_idx = i
            exit_price = bid_now
            exit_reason = f"target ${pl_usd:.2f}"
            break
    else:
        exit_idx = min(entry_idx + max_hold, len(bars) - 1)
        exit_price = float(bars[exit_idx]["close"]) - SPREAD_PT * POINT / 2
        pl_pts = (exit_price - entry_price) / POINT
        pl_usd = pl_pts * lot * (PT_VALUE_PER_LOT / 100)
        exit_reason = "timeout"

    return SimTrade(
        open_idx=entry_idx, close_idx=exit_idx, gene_id=gene.id,
        entry=entry_price, exit=exit_price, sl=sl, tp_target=target_usd,
        lot=lot, pl_usd=round(pl_usd, 4),
        win=(pl_usd > 0), age_bars=exit_idx - entry_idx,
        exit_reason=exit_reason, dip_score=sig.score, dip_drop_atr=sig.drop_atr,
    )


def run_backtest():
    print(f"=== FRIDAY v3 Backtester — {DAYS_BACK} days, {SYMBOL} M1 ===\n")
    if not mt5.initialize():
        print("MT5 init failed"); return

    # Pull bars
    print(f"Pulling {DAYS_BACK} days M1 bars...")
    from_ts = datetime.now() - timedelta(days=DAYS_BACK)
    bars = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, from_ts, datetime.now())
    if bars is None or len(bars) < 100:
        print(f"Not enough bars: {len(bars) if bars is not None else 'None'}")
        mt5.shutdown(); return
    print(f"  ✓ {len(bars):,} bars loaded ({from_ts:%Y-%m-%d} → now)\n")

    # Use a fresh gene pool snapshot (read from existing file but don't mutate)
    pool = GenePool()
    print(f"Using {len(pool.genes)} genes from current pool\n")

    # Walk through bars
    trades: list[SimTrade] = []
    last_trade_idx_per_gene: dict[str, int] = {}
    cycle_count = 0
    skipped_by_cooldown = 0

    for i in range(50, len(bars)):
        cycle_count += 1
        sig = reconstruct_dip_signal_at(bars, i)
        if not sig.is_actionable():
            continue

        # Approving genes
        approvers = []
        for g in pool.genes:
            ok, _ = g.evaluate_dip(sig)
            if not ok: continue
            # Cooldown check in bars (assume cooldown_seconds / 60 ≈ bars on M1)
            last_idx = last_trade_idx_per_gene.get(g.id, -10000)
            cooldown_bars = max(1, g.dna.cooldown_seconds // 60)
            if i - last_idx < cooldown_bars:
                skipped_by_cooldown += 1
                continue
            approvers.append(g)
        if not approvers:
            continue

        # Best approver
        ranked = sorted(approvers, key=lambda g: -g.stats.fitness if g.stats.trades > 0 else 0.5)
        gene = ranked[0]

        t = simulate_trade(bars, i, gene, sig)
        trades.append(t)
        last_trade_idx_per_gene[gene.id] = t.close_idx

        if cycle_count % 5000 == 0:
            print(f"  scanned {cycle_count:,} bars, {len(trades)} trades placed")

    mt5.shutdown()

    # ── Compute metrics ──
    if not trades:
        print("No trades generated.")
        verdict = "NO_TRADES"
        report = {"verdict": verdict, "total_trades": 0}
    else:
        wins = [t for t in trades if t.win]
        losses = [t for t in trades if not t.win]
        gross_win  = sum(t.pl_usd for t in wins)
        gross_loss = abs(sum(t.pl_usd for t in losses))
        net_pl = sum(t.pl_usd for t in trades)
        win_rate = len(wins) / len(trades) * 100
        profit_factor = gross_win / gross_loss if gross_loss > 0 else 0

        # Drawdown
        balance = INITIAL_BALANCE
        peak = balance
        max_dd = 0
        for t in trades:
            balance += t.pl_usd
            peak = max(peak, balance)
            dd = peak - balance
            max_dd = max(max_dd, dd)

        # Sharpe (per-trade returns / std)
        returns = [t.pl_usd for t in trades]
        sharpe = (statistics.mean(returns) / statistics.stdev(returns)) * (252**0.5) if len(returns) > 1 and statistics.stdev(returns) > 0 else 0

        # Verdict
        verdict = "PASS" if (win_rate >= 50 and profit_factor >= 1.5 and max_dd <= INITIAL_BALANCE * 0.30) else "FAIL"

        report = {
            "ts":              datetime.utcnow().isoformat(),
            "days":            DAYS_BACK,
            "symbol":          SYMBOL,
            "bars_scanned":    len(bars),
            "total_trades":    len(trades),
            "wins":            len(wins),
            "losses":          len(losses),
            "win_rate":        round(win_rate, 2),
            "profit_factor":   round(profit_factor, 2),
            "net_pl":          round(net_pl, 2),
            "max_drawdown":    round(max_dd, 2),
            "avg_win":         round(gross_win / max(1, len(wins)), 4),
            "avg_loss":        round(-gross_loss / max(1, len(losses)), 4),
            "sharpe_annualized": round(sharpe, 2),
            "skipped_cooldown": skipped_by_cooldown,
            "verdict":         verdict,
            "criteria":        "WR>=50%, PF>=1.5, DD<=30%",
        }

    # Write
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(TRADES, "w", encoding="utf-8") as f:
        f.write("open_idx,close_idx,gene_id,entry,exit,sl,lot,pl,win,age_bars,exit_reason,dip_score,dip_drop_atr\n")
        for t in trades:
            f.write(f"{t.open_idx},{t.close_idx},{t.gene_id},{t.entry:.2f},{t.exit:.2f},{t.sl:.2f},"
                    f"{t.lot:.2f},{t.pl_usd:.4f},{int(t.win)},{t.age_bars},{t.exit_reason},"
                    f"{t.dip_score},{t.dip_drop_atr}\n")

    # Print summary
    print(f"\n{'='*60}")
    print(f"  BACKTEST RESULTS")
    print(f"{'='*60}")
    for k, v in report.items():
        print(f"  {k:20s}: {v}")
    print(f"\nReport written to: {REPORT}")
    print(f"Trades CSV: {TRADES}")


if __name__ == "__main__":
    run_backtest()

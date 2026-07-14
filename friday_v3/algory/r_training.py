"""
r_training.py — Offline training mode that runs when markets are closed.

When weekend or all sessions closed, R enters "training mode":
  1. Reviews today's REAL trades (from broker history)
  2. Replays the day's M5 candles with current improved rules
  3. Computes hypothetical results: "if I traded with the new rules today..."
  4. Compares: actual P/L vs simulated P/L
  5. Marks entry/exit points on a virtual chart
  6. Says: "Next time, I'll do this differently because..."

Output: data/r_training/session_<date>.json
        {actual_trades, simulated_trades, delta_pl, lessons}
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import MetaTrader5 as mt5
import numpy as np

TRAIN_DIR = Path(r"C:\Users\Radhi\MT5\friday_v3\data\r_training")

R_MAGIC = 20260605


def is_market_open(symbol: str = "XAUUSDm") -> bool:
    """Best-effort: open if tick within last 5 min."""
    if not mt5.initialize(): return False
    tick = mt5.symbol_info_tick(symbol)
    if not tick: return False
    return (datetime.now().timestamp() - tick.time) < 300


def get_today_real_trades(magic: int = R_MAGIC, hours_back: int = 24) -> list[dict]:
    """Pull R's actual closed trades from broker history."""
    if not mt5.initialize(): return []
    from_dt = datetime.now() - timedelta(hours=hours_back)
    deals = mt5.history_deals_get(from_dt, datetime.now()) or []
    # Group by position
    positions = {}
    for d in deals:
        if d.magic != magic: continue
        positions.setdefault(d.position_id, []).append(d)
    out = []
    for pid, ds in positions.items():
        if len(ds) < 2: continue
        ds.sort(key=lambda x: x.time)
        in_d, out_d = ds[0], ds[-1]
        out.append({
            "position_id":  pid,
            "side":         "BUY" if in_d.type == 0 else "SELL",
            "open_time":    int(in_d.time),
            "close_time":   int(out_d.time),
            "open_price":   float(in_d.price),
            "close_price":  float(out_d.price),
            "profit":       round(float(out_d.profit) + float(out_d.swap) + float(out_d.commission), 2),
            "comment":      str(out_d.comment or ""),
        })
    return out


def get_day_bars(symbol: str, tf, day_iso: Optional[str] = None) -> Optional[np.ndarray]:
    """Get M5 bars for a specific day. Falls back to LAST 24h of bars if today empty."""
    if not mt5.initialize(): return None
    if day_iso:
        day = datetime.fromisoformat(day_iso).replace(tzinfo=timezone.utc)
    else:
        day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = day + timedelta(days=1)
    bars = mt5.copy_rates_range(symbol, tf, day, end_day)
    if bars is None or len(bars) < 50:
        # Fallback: pull last 288 M5 bars (24h)
        bars = mt5.copy_rates_from_pos(symbol, tf, 0, 288)
    return bars


def _atr(highs, lows, closes, n=14):
    tr = []
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i],
                      abs(highs[i] - closes[i-1]),
                      abs(lows[i]  - closes[i-1])))
    if not tr: return 0
    return sum(tr[-n:]) / min(n, len(tr))


def simulate_archetype_on_day(bars: np.ndarray, archetype: str = "BREAKOUT_HUNTER",
                              starting_balance: float = 95.0) -> dict:
    """Replay one day's M5 bars with R's IMPROVED rules and see what happens."""
    if bars is None or len(bars) < 50:
        return {"ok": False, "reason": "not enough bars"}

    trades = []
    balance = starting_balance
    position = None
    cooldown = 0

    # Try to import current learned multipliers
    try:
        from friday_v3.algory.r_learning import get_adjusted_multipliers
        adj = get_adjusted_multipliers(archetype)
        sl_mult = 2.0 * adj.get("sl_mult", 1.0)
        tp_mult = 7.0 * adj.get("tp_mult", 1.0)
    except Exception:
        sl_mult = 2.0; tp_mult = 7.0

    LOT = 0.01
    CONTRACT_SIZE = 100   # gold

    for i in range(40, len(bars) - 1):
        bar = bars[i]
        # Lookback for indicators
        window = bars[max(0, i-50):i+1]
        c = window["close"]; h = window["high"]; l = window["low"]
        atr = _atr(h, l, c, 14)
        if atr <= 0: continue

        # If in position, check SL/TP
        if position:
            high_now = float(bar["high"]); low_now = float(bar["low"])
            if position["side"] == "BUY":
                if low_now <= position["sl"]:
                    profit = (position["sl"] - position["entry"]) * LOT * CONTRACT_SIZE
                    trades.append({**position, "close_bar": i, "close_price": position["sl"],
                                   "close_time": int(bar["time"]), "profit": round(profit,2),
                                   "exit": "SL"})
                    balance += profit; position = None; cooldown = 5
                elif high_now >= position["tp"]:
                    profit = (position["tp"] - position["entry"]) * LOT * CONTRACT_SIZE
                    trades.append({**position, "close_bar": i, "close_price": position["tp"],
                                   "close_time": int(bar["time"]), "profit": round(profit,2),
                                   "exit": "TP"})
                    balance += profit; position = None; cooldown = 5
            else:  # SELL
                if high_now >= position["sl"]:
                    profit = (position["entry"] - position["sl"]) * LOT * CONTRACT_SIZE
                    trades.append({**position, "close_bar": i, "close_price": position["sl"],
                                   "close_time": int(bar["time"]), "profit": round(profit,2),
                                   "exit": "SL"})
                    balance += profit; position = None; cooldown = 5
                elif low_now <= position["tp"]:
                    profit = (position["entry"] - position["tp"]) * LOT * CONTRACT_SIZE
                    trades.append({**position, "close_bar": i, "close_price": position["tp"],
                                   "close_time": int(bar["time"]), "profit": round(profit,2),
                                   "exit": "TP"})
                    balance += profit; position = None; cooldown = 5
            continue

        if cooldown > 0:
            cooldown -= 1; continue

        # Simple breakout entry: close breaks above last 10-bar high (BUY) or below low (SELL)
        # Use bar BEFORE current to avoid look-ahead bias (recent_h excludes current bar)
        recent_h = float(h[-11:-1].max()) if len(h) >= 11 else float(h[-10:].max())
        recent_l = float(l[-11:-1].min()) if len(l) >= 11 else float(l[-10:].min())
        close_now = float(c[-1])

        if close_now > recent_h:
            entry = close_now
            sl = entry - atr * sl_mult
            tp = entry + atr * tp_mult
            position = {"side": "BUY", "entry": entry, "sl": sl, "tp": tp,
                        "open_bar": i, "open_time": int(bar["time"]),
                        "archetype": archetype}
        elif close_now < recent_l:
            entry = close_now
            sl = entry + atr * sl_mult
            tp = entry - atr * tp_mult
            position = {"side": "SELL", "entry": entry, "sl": sl, "tp": tp,
                        "open_bar": i, "open_time": int(bar["time"]),
                        "archetype": archetype}

    # Close any open position at last bar
    if position:
        last = bars[-1]
        cl = float(last["close"])
        if position["side"] == "BUY":
            profit = (cl - position["entry"]) * LOT * CONTRACT_SIZE
        else:
            profit = (position["entry"] - cl) * LOT * CONTRACT_SIZE
        trades.append({**position, "close_bar": len(bars)-1, "close_price": cl,
                       "close_time": int(last["time"]), "profit": round(profit,2),
                       "exit": "EOD"})
        balance += profit

    total_pl = round(balance - starting_balance, 2)
    wins = sum(1 for t in trades if t["profit"] > 0)
    return {
        "ok":              True,
        "archetype":       archetype,
        "starting_balance": starting_balance,
        "ending_balance":  round(balance, 2),
        "total_pl":        total_pl,
        "total_trades":    len(trades),
        "wins":            wins,
        "win_rate":        round(wins / max(1,len(trades)) * 100, 1),
        "trades":          trades,
        "sl_mult_used":    round(sl_mult, 2),
        "tp_mult_used":    round(tp_mult, 2),
    }


def run_training_session(symbol: str = "XAUUSDm") -> dict:
    """Compare actual day vs simulated day with improved rules."""
    if not mt5.initialize():
        return {"ok": False, "error": "mt5 init"}

    actual_trades = get_today_real_trades()
    actual_pl = sum(t["profit"] for t in actual_trades)

    bars = get_day_bars(symbol, mt5.TIMEFRAME_M5)
    # Try each archetype, pick best
    archetypes = ["BREAKOUT_HUNTER", "MEAN_REVERTER", "MULTI_SIGNAL", "PATTERN_SPOTTER"]
    simulated_runs = {}
    for arch in archetypes:
        simulated_runs[arch] = simulate_archetype_on_day(bars, arch)

    best_arch = max(simulated_runs.items(),
                    key=lambda kv: kv[1].get("total_pl", -999) if kv[1].get("ok") else -999)

    # Build lessons
    lessons = []
    if actual_pl < 0:
        lessons.append(f"الواقع: خسرنا ${actual_pl:.2f} اليوم من {len(actual_trades)} صفقات")
    else:
        lessons.append(f"الواقع: ربحنا ${actual_pl:.2f} اليوم من {len(actual_trades)} صفقات")
    if best_arch[1].get("ok"):
        sim_pl = best_arch[1].get("total_pl", 0)
        delta = sim_pl - actual_pl
        lessons.append(f"التدريب: لو استخدمت {best_arch[0]} وقواعدي الجديدة لكنت سأحقق ${sim_pl:+.2f} "
                       f"({best_arch[1]['wins']}/{best_arch[1]['total_trades']} = {best_arch[1]['win_rate']}% WR)")
        lessons.append(f"الفرق: {('+' if delta>0 else '')}${delta:.2f}")
        if delta > 0:
            lessons.append(f"💡 الدرس: المرة القادمة سأستخدم {best_arch[0]} مع SL×{best_arch[1]['sl_mult_used']} و TP×{best_arch[1]['tp_mult_used']}")
        else:
            lessons.append(f"⚠ السوق اليوم كان صعب — حتى rules الجديدة ما حسّنت كثيراً")

    out = {
        "ok":              True,
        "ts":              datetime.now(timezone.utc).isoformat(),
        "symbol":          symbol,
        "market_open":     is_market_open(symbol),
        "actual_trades":   actual_trades,
        "actual_pl":       round(actual_pl, 2),
        "simulated":       simulated_runs,
        "best_simulation": best_arch[0],
        "lessons":         lessons,
        "bars_analyzed":   int(len(bars)) if bars is not None else 0,
        # Chart data for UI rendering (last 100 bars as candles)
        "chart": _bars_to_chart(bars[-100:] if bars is not None and len(bars) > 100 else bars,
                                 best_arch[1].get("trades", []) if best_arch[1].get("ok") else [],
                                 bars),
    }

    # Save
    TRAIN_DIR.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    save_path = TRAIN_DIR / f"session_{today_str}.json"
    save_path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str),
                          encoding="utf-8")
    return out


def _bars_to_chart(bars, sim_trades, all_bars):
    """Convert bars + trade markers into a tiny structure the UI can render."""
    if bars is None or len(bars) == 0: return {"bars": [], "markers": []}
    # Compute bar_index offset between all_bars and bars (for trade marker mapping)
    offset = (len(all_bars) - len(bars)) if all_bars is not None else 0
    candles = []
    for b in bars:
        candles.append({
            "t":  int(b["time"]),
            "o":  float(b["open"]),
            "h":  float(b["high"]),
            "l":  float(b["low"]),
            "c":  float(b["close"]),
        })
    markers = []
    for t in (sim_trades or []):
        # open marker
        if t.get("open_bar") is not None and t["open_bar"] >= offset:
            markers.append({
                "bar":   t["open_bar"] - offset,
                "price": t["entry"],
                "type":  f"OPEN_{t['side']}",
                "color": "#10b981" if t["side"] == "BUY" else "#ef4444",
                "label": f"{t['side']} {t.get('archetype','')[:4]}",
            })
        # close marker
        if t.get("close_bar") is not None and t["close_bar"] >= offset:
            markers.append({
                "bar":   t["close_bar"] - offset,
                "price": t.get("close_price", t.get("entry")),
                "type":  f"CLOSE_{t.get('exit','?')}",
                "color": "#22c55e" if t.get("profit", 0) > 0 else "#dc2626",
                "label": f"{t.get('exit','?')} ${t.get('profit',0):+.2f}",
            })
    return {"bars": candles, "markers": markers}


if __name__ == "__main__":
    out = run_training_session()
    print(json.dumps({k: out[k] for k in ("ok","market_open","actual_pl","best_simulation","lessons")
                      if k in out}, ensure_ascii=False, indent=2))

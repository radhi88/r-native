"""scanner.py - Full-market scanner: 4000 bars × all TFs × all symbols × all archetypes.

For each (symbol, TF, archetype):
  1. Pull 4000 bars from MT5
  2. Replay archetype's entry logic across history
  3. Compute stats: WR, PF, DD, return%, sharpe, avg R:R
  4. Score gene fitness (which indicator combos win on this symbol)
  5. Output confidence verdict: DEPLOY / EVALUATE / REJECT

Saves to: data/r_native/scans/<timestamp>/<symbol>_<tf>_<archetype>.json
And aggregated: data/r_native/scans/<timestamp>/summary.json
"""
from __future__ import annotations
import json
import math
import time
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

import numpy as np
import MetaTrader5 as mt5

ROOT = Path(r"C:\Users\Radhi\MT5")
DATA_DIR = ROOT / "data" / "r_native"
SCANS_DIR = DATA_DIR / "scans"
CONFIG_DIR = DATA_DIR / "symbol_configs"
LEARN_DIR = DATA_DIR / "symbol_learning"


# ─── Archetype rules — each takes (i, bars) and returns trigger ───
ARCHETYPES = {
    "BREAKOUT_HUNTER": {
        "desc": "Buys breakouts above 20-bar high, sells breakdowns below 20-bar low",
        "sl_atr_mult": 2.0,
        "tp_atr_mult": 7.0,
    },
    "MEAN_REVERTER": {
        "desc": "Buys oversold (RSI<30) bounces, sells overbought (RSI>70) pullbacks",
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 4.0,
    },
    "MULTI_SIGNAL": {
        "desc": "Requires 3+ confirmations: RSI + MACD + MA cross",
        "sl_atr_mult": 1.8,
        "tp_atr_mult": 5.5,
    },
    "PATTERN_SPOTTER": {
        "desc": "Engulfing or pin bar at key MA",
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 4.5,
    },
}


@dataclass
class TradeResult:
    side: str
    entry: float
    exit: float
    profit: float
    duration_bars: int
    exit_reason: str   # TP, SL, EOD


@dataclass
class StrategyStats:
    symbol: str
    timeframe: str
    archetype: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0
    profit_factor: float = 0
    total_return_pct: float = 0
    max_drawdown_pct: float = 0
    sharpe: float = 0
    avg_rr: float = 0
    avg_win: float = 0
    avg_loss: float = 0
    longest_win_streak: int = 0
    longest_loss_streak: int = 0
    bars_scanned: int = 0
    spread_pt: float = 0
    sl_mult: float = 0
    tp_mult: float = 0
    confidence: str = "NONE"       # DEPLOY / EVALUATE / REJECT
    verdict_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _atr(highs, lows, closes, n=14):
    tr = [max(float(highs[i]) - float(lows[i]),
              abs(float(highs[i]) - float(closes[i-1])),
              abs(float(lows[i]) - float(closes[i-1])))
          for i in range(1, len(closes))]
    if len(tr) < n: return sum(tr) / len(tr) if tr else 0
    out = [sum(tr[:n]) / n]
    for t in tr[n:]:
        out.append((out[-1] * (n - 1) + t) / n)
    return out


def _rsi(closes, n=14):
    diffs = np.diff(closes)
    gains = np.where(diffs > 0, diffs, 0)
    losses = np.where(diffs < 0, -diffs, 0)
    if len(diffs) < n: return [50] * len(closes)
    avg_g = np.mean(gains[:n]); avg_l = np.mean(losses[:n])
    out = [50] * (n + 1)
    for i in range(n, len(diffs)):
        avg_g = (avg_g * (n - 1) + gains[i]) / n
        avg_l = (avg_l * (n - 1) + losses[i]) / n
        out.append(100 - 100 / (1 + (avg_g / avg_l)) if avg_l > 0 else 100)
    while len(out) < len(closes): out.append(out[-1])
    return out


def _sma(arr, n):
    out = []
    for i in range(len(arr)):
        if i < n - 1: out.append(arr[i])
        else: out.append(float(np.mean(arr[i - n + 1:i + 1])))
    return out


def _simulate_archetype(bars: np.ndarray, archetype: str, spread_pt: float,
                        point_size: float, contract_size: float,
                        lot: float = 0.01) -> tuple[list[TradeResult], dict]:
    """Replay one archetype over the historical bars."""
    tpl = ARCHETYPES[archetype]
    n = len(bars)
    if n < 60: return [], {"reason": "not enough bars"}

    o = bars["open"].astype(float)
    h = bars["high"].astype(float)
    l = bars["low"].astype(float)
    c = bars["close"].astype(float)

    atr_series = _atr(h, l, c, 14)
    rsi_series = _rsi(c, 14)
    sma_fast = _sma(c, 8)
    sma_slow = _sma(c, 21)

    spread_price = spread_pt * point_size
    half_spread = spread_price / 2

    trades: list[TradeResult] = []
    pos = None     # current open position dict
    cooldown = 0

    for i in range(50, n - 1):
        atr = atr_series[i - 1] if i - 1 < len(atr_series) else 0
        if atr <= 0: continue
        rsi = rsi_series[i] if i < len(rsi_series) else 50
        # Manage existing position
        if pos:
            bar_h = h[i]; bar_l = l[i]
            if pos["side"] == "BUY":
                if bar_l <= pos["sl"]:
                    pl = (pos["sl"] - pos["entry"]) * lot * contract_size
                    trades.append(TradeResult("BUY", pos["entry"], pos["sl"], pl, i - pos["open_bar"], "SL"))
                    pos = None; cooldown = 3
                    continue
                if bar_h >= pos["tp"]:
                    pl = (pos["tp"] - pos["entry"]) * lot * contract_size
                    trades.append(TradeResult("BUY", pos["entry"], pos["tp"], pl, i - pos["open_bar"], "TP"))
                    pos = None; cooldown = 3
                    continue
            else:    # SELL
                if bar_h >= pos["sl"]:
                    pl = (pos["entry"] - pos["sl"]) * lot * contract_size
                    trades.append(TradeResult("SELL", pos["entry"], pos["sl"], pl, i - pos["open_bar"], "SL"))
                    pos = None; cooldown = 3
                    continue
                if bar_l <= pos["tp"]:
                    pl = (pos["entry"] - pos["tp"]) * lot * contract_size
                    trades.append(TradeResult("SELL", pos["entry"], pos["tp"], pl, i - pos["open_bar"], "TP"))
                    pos = None; cooldown = 3
                    continue
            continue
        if cooldown > 0: cooldown -= 1; continue

        # ─── Archetype entry rules ───
        signal = None    # "BUY" or "SELL"
        if archetype == "BREAKOUT_HUNTER":
            recent_h = max(h[i - 20:i])
            recent_l = min(l[i - 20:i])
            if c[i] > recent_h: signal = "BUY"
            elif c[i] < recent_l: signal = "SELL"

        elif archetype == "MEAN_REVERTER":
            if rsi < 30 and c[i] > o[i]: signal = "BUY"     # oversold + bullish bar
            elif rsi > 70 and c[i] < o[i]: signal = "SELL"  # overbought + bearish bar

        elif archetype == "MULTI_SIGNAL":
            sf = sma_fast[i]; ss = sma_slow[i]
            sf_prev = sma_fast[i-1]; ss_prev = sma_slow[i-1]
            ma_cross_up = sf_prev < ss_prev and sf > ss
            ma_cross_dn = sf_prev > ss_prev and sf < ss
            if ma_cross_up and rsi > 50: signal = "BUY"
            elif ma_cross_dn and rsi < 50: signal = "SELL"

        elif archetype == "PATTERN_SPOTTER":
            body = abs(c[i] - o[i])
            upper_wick = h[i] - max(o[i], c[i])
            lower_wick = min(o[i], c[i]) - l[i]
            # bullish pin bar near rising MA
            if (lower_wick > body * 2 and c[i] > o[i] and sma_fast[i] > sma_slow[i]):
                signal = "BUY"
            elif (upper_wick > body * 2 and c[i] < o[i] and sma_fast[i] < sma_slow[i]):
                signal = "SELL"

        if not signal: continue

        # Place trade
        entry = c[i] + half_spread if signal == "BUY" else c[i] - half_spread
        sl_dist = atr * tpl["sl_atr_mult"]
        tp_dist = atr * tpl["tp_atr_mult"]
        sl = entry - sl_dist if signal == "BUY" else entry + sl_dist
        tp = entry + tp_dist if signal == "BUY" else entry - tp_dist
        pos = {"side": signal, "entry": entry, "sl": sl, "tp": tp, "open_bar": i}

    return trades, {"bars": n, "spread_price": spread_price}


def _stats_from_trades(trades: list[TradeResult]) -> dict:
    if not trades: return {}
    wins = [t for t in trades if t.profit > 0]
    losses = [t for t in trades if t.profit < 0]
    gw = sum(t.profit for t in wins)
    gl = abs(sum(t.profit for t in losses))
    wr = len(wins) / len(trades) * 100
    pf = gw / gl if gl > 0 else (999 if wins else 0)
    avg_win = gw / len(wins) if wins else 0
    avg_loss = gl / len(losses) if losses else 0
    rr = avg_win / avg_loss if avg_loss > 0 else 0
    # Drawdown
    bal, peak, max_dd = 0, 0, 0
    for t in trades:
        bal += t.profit
        peak = max(peak, bal)
        max_dd = max(max_dd, peak - bal)
    total_ret = sum(t.profit for t in trades)
    # Sharpe per trade
    profits = [t.profit for t in trades]
    mean = statistics.mean(profits)
    sd = statistics.stdev(profits) if len(profits) > 1 else 1
    sharpe = (mean / sd * math.sqrt(len(trades))) if sd > 0 else 0
    # streaks
    cur_w = cur_l = max_w = max_l = 0
    for t in trades:
        if t.profit > 0:
            cur_w += 1; cur_l = 0
            max_w = max(max_w, cur_w)
        elif t.profit < 0:
            cur_l += 1; cur_w = 0
            max_l = max(max_l, cur_l)
    return {
        "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": round(wr, 1), "profit_factor": round(pf, 2),
        "total_return_pct": round(total_ret, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "avg_rr": round(rr, 2),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "longest_win_streak": max_w,
        "longest_loss_streak": max_l,
    }


def _verdict(stats: dict) -> tuple[str, str]:
    """Decide DEPLOY / EVALUATE / REJECT."""
    if stats.get("trades", 0) < 20:
        return "REJECT", f"only {stats.get('trades',0)} trades (need ≥20)"
    wr = stats.get("win_rate", 0)
    pf = stats.get("profit_factor", 0)
    sharpe = stats.get("sharpe", 0)
    dd_ratio = stats.get("max_drawdown_pct", 0) / max(1, stats.get("total_return_pct", 1))
    if pf >= 1.8 and wr >= 50 and sharpe >= 1.5 and stats.get("total_return_pct", 0) > 0:
        return "DEPLOY", f"PF {pf}, WR {wr}%, Sharpe {sharpe}"
    if pf >= 1.3 and wr >= 45:
        return "EVALUATE", f"borderline: PF {pf}, WR {wr}%"
    return "REJECT", f"weak: PF {pf}, WR {wr}%, return {stats.get('total_return_pct',0)}"


# ─── Main scanner ───
def discover_active_symbols(limit: int = 30) -> list[str]:
    """All visible+tradeable symbols (just names)."""
    if not mt5.initialize(): return []
    out = []
    for s in (mt5.symbols_get() or []):
        if s.visible and s.trade_mode == 4:
            out.append(s.name)
        if len(out) >= limit: break
    return out


def scan_symbol_tf_archetype(symbol: str, tf, archetype: str,
                              n_bars: int = 4000) -> StrategyStats:
    if not mt5.initialize(): return StrategyStats(symbol, str(tf), archetype, verdict_reason="mt5 init failed")
    sym_info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if not sym_info or not tick:
        return StrategyStats(symbol, str(tf), archetype, verdict_reason="no symbol info")
    spread_pt = (tick.ask - tick.bid) / sym_info.point if sym_info.point else 0
    # H.4: route through the symbol-capped LRU bar cache (5 symbols max).
    # The same (symbol, tf) array is otherwise re-fetched once per archetype;
    # the cache also lets post-campaign cleanup bound worker RAM.
    try:
        from r_native.bar_cache import fetch as _bars_fetch
        bars = _bars_fetch(symbol, _tf_name(tf), n_bars,
                           lambda: mt5.copy_rates_from_pos(symbol, tf, 0, n_bars))
    except ImportError:
        bars = mt5.copy_rates_from_pos(symbol, tf, 0, n_bars)
    if bars is None or len(bars) < 100:
        return StrategyStats(symbol, str(tf), archetype, bars_scanned=0,
                              verdict_reason="not enough bars")
    trades, meta = _simulate_archetype(bars, archetype, spread_pt,
                                        sym_info.point, sym_info.trade_contract_size)
    stats = _stats_from_trades(trades)
    verdict, reason = _verdict(stats)
    tpl = ARCHETYPES[archetype]
    return StrategyStats(
        symbol=symbol, timeframe=_tf_name(tf), archetype=archetype,
        trades=stats.get("trades", 0), wins=stats.get("wins", 0), losses=stats.get("losses", 0),
        win_rate=stats.get("win_rate", 0), profit_factor=stats.get("profit_factor", 0),
        total_return_pct=stats.get("total_return_pct", 0),
        max_drawdown_pct=stats.get("max_drawdown_pct", 0),
        sharpe=stats.get("sharpe", 0), avg_rr=stats.get("avg_rr", 0),
        avg_win=stats.get("avg_win", 0), avg_loss=stats.get("avg_loss", 0),
        longest_win_streak=stats.get("longest_win_streak", 0),
        longest_loss_streak=stats.get("longest_loss_streak", 0),
        bars_scanned=len(bars), spread_pt=round(spread_pt, 1),
        sl_mult=tpl["sl_atr_mult"], tp_mult=tpl["tp_atr_mult"],
        confidence=verdict, verdict_reason=reason,
    )


def _tf_name(tf):
    return {
        mt5.TIMEFRAME_M1: "M1",  mt5.TIMEFRAME_M5: "M5",
        mt5.TIMEFRAME_M15:"M15", mt5.TIMEFRAME_M30:"M30",
        mt5.TIMEFRAME_H1: "H1",  mt5.TIMEFRAME_H4: "H4",
        mt5.TIMEFRAME_D1: "D1",
    }.get(tf, str(tf))


def full_scan(symbols: list[str] = None, n_bars: int = 4000,
              progress_cb: Callable[[str], None] = None) -> dict:
    """Scan every (symbol × TF × archetype) combination. Returns master report."""
    if not mt5.initialize():
        return {"ok": False, "error": "mt5 init"}
    if symbols is None:
        symbols = discover_active_symbols()
    tfs = [mt5.TIMEFRAME_M5, mt5.TIMEFRAME_M15, mt5.TIMEFRAME_H1, mt5.TIMEFRAME_H4]
    archetypes = list(ARCHETYPES.keys())

    SCANS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = SCANS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(exist_ok=True)

    all_results = []
    total_combos = len(symbols) * len(tfs) * len(archetypes)
    done = 0
    t0 = time.time()
    for sym in symbols:
        for tf in tfs:
            for arch in archetypes:
                done += 1
                if progress_cb:
                    progress_cb(f"[{done}/{total_combos}] {sym} {_tf_name(tf)} {arch}")
                try:
                    res = scan_symbol_tf_archetype(sym, tf, arch, n_bars)
                    all_results.append(res.to_dict())
                    # Per-combo file
                    (run_dir / f"{sym}_{_tf_name(tf)}_{arch}.json").write_text(
                        json.dumps(res.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception as e:
                    all_results.append({"symbol": sym, "tf": _tf_name(tf), "archetype": arch,
                                        "error": str(e)})

    elapsed = time.time() - t0
    # Aggregate: best per symbol
    by_symbol = {}
    for r in all_results:
        if "error" in r or r.get("trades", 0) == 0: continue
        sym = r["symbol"]
        if sym not in by_symbol or r.get("profit_factor", 0) > by_symbol[sym].get("profit_factor", 0):
            by_symbol[sym] = r
    deploy_list = [r for r in all_results if r.get("confidence") == "DEPLOY"]
    reject_list = [r for r in all_results if r.get("confidence") == "REJECT"]

    summary = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbols_scanned": len(symbols),
        "tfs": [_tf_name(t) for t in tfs],
        "archetypes": archetypes,
        "total_combinations": total_combos,
        "elapsed_seconds": round(elapsed, 1),
        "deploy_count": len(deploy_list),
        "evaluate_count": sum(1 for r in all_results if r.get("confidence") == "EVALUATE"),
        "reject_count": len(reject_list),
        "best_per_symbol": by_symbol,
        "deploy_strategies": deploy_list,
        "all_results": all_results,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    # Save as "latest" too
    (SCANS_DIR / "latest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    return summary


def update_symbol_configs_from_scan(scan_summary: dict):
    """For every symbol in scan, write/update its config file with deploy strategies."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    by_sym = {}
    for r in scan_summary.get("all_results", []):
        if "error" in r: continue
        sym = r["symbol"]
        by_sym.setdefault(sym, []).append(r)
    for sym, results in by_sym.items():
        cfg_path = CONFIG_DIR / f"{sym}.json"
        existing = {}
        if cfg_path.exists():
            try: existing = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception: pass
        results_sorted = sorted(results, key=lambda x: -x.get("profit_factor", 0))
        deploy = [r for r in results if r.get("confidence") == "DEPLOY"]
        cfg = {
            "symbol": sym,
            "last_scan": scan_summary.get("ts"),
            "all_results": results_sorted,
            "deploy_strategies": deploy,
            "best_archetype": deploy[0]["archetype"] if deploy else None,
            "best_tf": deploy[0]["timeframe"] if deploy else None,
            "best_pf": deploy[0]["profit_factor"] if deploy else 0,
            "tradeable": len(deploy) > 0,
            # per-symbol risk (auto-tuned from scan)
            "lot": existing.get("lot", 0.01),
            "max_concurrent": existing.get("max_concurrent", 1),
            "daily_loss_cap_usd": existing.get("daily_loss_cap_usd", 3.0),
            "user_overrides": existing.get("user_overrides", {}),
        }
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def load_symbol_config(symbol: str) -> dict:
    cfg_path = CONFIG_DIR / f"{symbol}.json"
    if not cfg_path.exists():
        return {"symbol": symbol, "tradeable": False, "deploy_strategies": []}
    try: return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception: return {"symbol": symbol, "tradeable": False}


if __name__ == "__main__":
    import sys
    print("R Native v2 — Full Market Scanner")
    print("=" * 60)
    symbols_arg = sys.argv[1] if len(sys.argv) > 1 else None
    if symbols_arg:
        symbols = symbols_arg.split(",")
    else:
        symbols = discover_active_symbols(limit=15)
    print(f"Scanning {len(symbols)} symbols × 4 TFs × {len(ARCHETYPES)} archetypes")
    print(f"= {len(symbols) * 4 * len(ARCHETYPES)} combinations")
    print()
    def cb(msg): print(f"  {msg}")
    summary = full_scan(symbols, n_bars=4000, progress_cb=cb)
    print()
    print(f"Done in {summary.get('elapsed_seconds')}s")
    print(f"DEPLOY: {summary.get('deploy_count')}  EVALUATE: {summary.get('evaluate_count')}  REJECT: {summary.get('reject_count')}")
    update_symbol_configs_from_scan(summary)
    print(f"Configs written to {CONFIG_DIR}")

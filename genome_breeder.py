"""genome_breeder.py — J.14 — Manual genome editor with "what-if" backtest.

Lets the user hand-craft a genome (toggle genes, adjust params) and instantly
see how it would have performed on historical data. Educational tool: shows
what each gene does in isolation.

Two entry points:
  - Python API: build_genome() → simulate_on() → returns stats
  - CLI: python -m r_native.genome_breeder edit BTCUSDm M5

Genome JSON schema:
{
  "id":           "MANUAL_<timestamp>",
  "active_genes": [...list of gene names...],
  "params": {
    "sl_atr_mult":  1.5,
    "tp_atr_mult":  2.0,
    "start_hour":   8,
    "end_hour":     20,
    "rsi_period":   14,
    ...
  },
  "flags": { (auto-derived from active_genes) }
}
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


# Canonical gene names by category (from genes.py)
GENE_CATEGORIES = {
    "EXEC": ["exec_market2", "exec_limit", "exec_limit2", "exec_stop", "exec_swing"],
    "BIAS": ["use_bias_adx", "use_bias_chandelier", "use_bias_daily_mid",
             "use_bias_donchian_mid", "use_bias_ema", "use_bias_htf",
             "use_bias_market_struct", "use_bias_momentum", "use_bias_psar",
             "use_bias_rsi", "use_bias_sma", "use_bias_trailing"],
    "SIGNAL": ["use_sig_bb", "use_sig_breakout", "use_sig_cci",
               "use_sig_engulfing", "use_sig_fib", "use_sig_inside_break",
               "use_sig_macd", "use_sig_mom_break", "use_sig_pin_bar",
               "use_sig_rsi", "use_sig_stoch", "use_sig_three_soldiers",
               "use_sig_wick_rejection", "use_sig_williams"],
    "FILTER": ["use_filt_adr_exhaust", "use_filt_adx", "use_filt_bb",
               "use_filt_cci", "use_filt_consec", "use_filt_doji",
               "use_filt_keltner", "use_no_open_friday", "use_filt_receding",
               "use_filt_rsi", "use_filt_sma", "use_filt_volatility"],
    "MGMT": ["use_breakeven", "use_eod_close", "use_friday_close_profit",
             "use_partial_tp", "use_sl_lock", "use_sl_reduce"],
}


def build_genome(active_genes: list, params: dict | None = None) -> dict:
    """Construct a genome dict ready for the simulator."""
    params = params or {}
    # Defaults for missing params (engine needs these)
    defaults = {
        "sl_atr_mult":        1.5,
        "tp_atr_mult":        1.5,
        "start_hour":         0,
        "end_hour":           23,
        "consec_max":         5,
        "friday_close":       19,
        "min_score":          25,
        "rsi_period":         14,
        "rsi_lower":          30,
        "rsi_upper":          70,
        "sma_fast_period":    20,
        "sma_slow_period":    50,
        "atr_period":         14,
        "breakout_lookback":  20,
        "ema_fast":           12,
        "ema_slow":           26,
    }
    merged_params = {**defaults, **params}

    # Build flags dict (every known gene → True/False)
    all_genes = sum(GENE_CATEGORIES.values(), [])
    flags = {g: (g in active_genes) for g in all_genes}

    gid = "MANUAL_" + str(int(time.time()))
    return {
        "id":            gid,
        "active_genes":  sorted(active_genes),
        "params":        merged_params,
        "flags":         flags,
        "generation":    0,
        "method":        "manual_breeder",
        "parent_a":      None,
        "parent_b":      None,
    }


def simulate_on(genome: dict, symbol: str, tf: str, n_bars: int = 4000) -> dict:
    """Run the genome through ga_simulator on real MT5 bars."""
    try:
        import MetaTrader5 as mt5
        from r_native.ga_simulator import simulate_genome
        if not mt5.initialize():
            return {"ok": False, "error": "MT5 init failed"}
        sym_info = mt5.symbol_info(symbol)
        if not sym_info: return {"ok": False, "error": f"no symbol {symbol}"}
        tf_map = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
                  "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
                  "H1": mt5.TIMEFRAME_H1, "H2": mt5.TIMEFRAME_H2,
                  "H4": mt5.TIMEFRAME_H4}
        bars = mt5.copy_rates_from_pos(symbol, tf_map.get(tf, mt5.TIMEFRAME_M5),
                                        0, n_bars)
        if bars is None or len(bars) < 100:
            return {"ok": False, "error": "not enough bars"}
        stats = simulate_genome(genome, bars, sym_info)
        return {"ok": True, "genome": genome, "stats": stats}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def save_to_vault(genome: dict, symbol: str, tf: str, stats: dict) -> dict:
    """Persist a manually-bred genome into the symbol vault."""
    cfg_path = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs") / f"{symbol}.json"
    cfg = {}
    if cfg_path.exists():
        try: cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception: pass
    pf = stats.get("profit_factor", 0)
    slim = {
        "id":              genome["id"],
        "archetype":       "MANUAL_BRED",
        "timeframe":       tf,
        "trades":          stats.get("trades", 0),
        "win_rate":        stats.get("win_rate", 0),
        "profit_factor":   pf,
        "total_return_pct":stats.get("total_return_pct", 0),
        "max_drawdown_pct":stats.get("max_drawdown_pct", 0),
        "sharpe":          stats.get("sharpe", 0),
        "linearity":       stats.get("linearity", 0),
        "confidence":      "DEPLOY" if pf >= 1.5 else "EVALUATE" if pf >= 1.1 else "REJECT",
        "active_genes":    genome.get("active_genes", []),
        "sl_atr_mult":     genome["params"].get("sl_atr_mult"),
        "tp_atr_mult":     genome["params"].get("tp_atr_mult"),
        "start_hour":      genome["params"].get("start_hour"),
        "end_hour":        genome["params"].get("end_hour"),
        "source":          "MANUAL_BREEDER",
        "created_at":      None,
    }
    strats = cfg.setdefault("ga_strategies", [])
    by_id = {s["id"]: s for s in strats}
    by_id[slim["id"]] = slim
    cfg["ga_strategies"] = sorted(by_id.values(), key=lambda x: -(x.get("profit_factor", 0)))
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return {"ok": True, "added_to_vault": symbol, "id": slim["id"]}


def _cli():
    p = argparse.ArgumentParser(prog="r_native.genome_breeder")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list-genes")
    pt = sub.add_parser("test")
    pt.add_argument("symbol")
    pt.add_argument("tf")
    pt.add_argument("--genes", nargs="+", required=True,
                    help="active gene names (e.g. use_sig_breakout use_bias_ema)")
    pt.add_argument("--params", help="JSON params dict")
    pt.add_argument("--save", action="store_true")
    args = p.parse_args()

    if args.cmd == "list-genes":
        for cat, genes in GENE_CATEGORIES.items():
            print(f"\n{cat} ({len(genes)}):")
            for g in genes: print(f"  {g}")
        return

    if args.cmd == "test":
        params = json.loads(args.params) if args.params else {}
        g = build_genome(args.genes, params)
        print(f"Built genome: {g['id']}")
        print(f"  active: {len(g['active_genes'])} genes")
        result = simulate_on(g, args.symbol, args.tf)
        if not result["ok"]:
            print(f"⚠️ {result.get('error')}"); return
        s = result["stats"]
        print(f"\nSTATS:")
        for k in ("trades", "win_rate", "profit_factor", "total_return_pct",
                  "max_drawdown_pct", "sharpe", "linearity"):
            print(f"  {k:25s} {s.get(k)}")
        if args.save:
            r = save_to_vault(g, args.symbol, args.tf, s)
            print(f"\n✓ {r}")


if __name__ == "__main__":
    _cli()

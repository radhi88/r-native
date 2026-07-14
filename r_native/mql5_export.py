"""mql5_export.py — J.1 — Export deployed genome as standalone .mq5 EA.

Takes any genome from a symbol's vault and generates a compileable MQL5
Expert Advisor that the user can attach in MetaTrader 5 directly. No Python,
no R Executor, no daemons — just a regular EA.

Workflow:
  1. python -m r_native.mql5_export 98ED3A BTCUSDm M5
  2. Output: dist/mql5/R_98ED3A.mq5
  3. Copy to MetaTrader 5/MQL5/Experts/
  4. Compile in MetaEditor (or use Algory's compiler path auto-detect)
  5. Attach to BTCUSDm M5 chart
  6. Set ENABLE_TRADING=true input → it trades autonomously

What the EA does:
  - Implements the SAME logic as R's trade_gate for the deployed genome's
    active_genes (RSI/EMA/Breakout/MACD/etc.)
  - Uses the genome's SL/TP multipliers, session window, breakeven setting
  - Logs entries with genome_id in trade comment for tracking
  - Same magic number (20260605) so R Native dashboard still tracks it

Limitations:
  - Only the most common genes are implemented in the template (RSI, EMA,
    breakout, ADX filter, breakeven, Friday close). More complex genes need
    template extension.
  - No multi-symbol scanning — one EA per symbol per chart.
  - No advanced R-Executor features (auto-restart, smart symbol picking).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

TEMPLATE_PATH = Path(__file__).parent / "mql5_templates" / "r_strategy_template.mq5"
SYMBOL_CFG    = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
CAMPAIGN_DIR  = Path(r"C:\Users\Radhi\MT5\data\r_native\campaigns")
OUT_DIR       = Path(r"C:\Users\Radhi\MT5\dist\mql5")

# Algory's recorded compiler path
COMPILER_PATH = Path(r"C:/Program Files/MetaTrader 5 EXNESS/MetaEditor64.exe")

# Default param values (used when genome doesn't specify)
DEFAULT_PARAMS = {
    "rsi_period":        14,
    "ema_fast":          12,
    "ema_slow":          26,
    "atr_period":        14,
    "breakout_lookback": 20,
}


def _load_genome(symbol: str, genome_id: str) -> dict:
    """Find the genome in the symbol's vault. Pull full record from campaign if available."""
    cfg_path = SYMBOL_CFG / f"{symbol}.json"
    if not cfg_path.exists():
        raise FileNotFoundError(f"no vault for {symbol}")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    slim = next((s for s in cfg.get("ga_strategies", []) if s.get("id") == genome_id), None)
    if not slim:
        raise KeyError(f"{genome_id} not in {symbol} vault")
    # Try to enrich with full record from source campaign
    src = (slim.get("source") or "").replace("GA_campaign_", "")
    if src:
        vf = CAMPAIGN_DIR / src / "vault.json"
        if vf.exists():
            vault = json.loads(vf.read_text(encoding="utf-8"))
            full = next((r for r in vault
                         if r.get("genome", {}).get("id") == genome_id), None)
            if full:
                # Merge: slim has aggregate stats, full has params+flags
                merged = dict(slim)
                merged["params"]       = full.get("genome", {}).get("params", {})
                merged["flags"]        = full.get("genome", {}).get("flags", {})
                merged["active_genes"] = full.get("genome", {}).get("active_genes", [])
                merged["stats"]        = full.get("stats", {})
                return merged
    return slim


def _flag(active_genes: list, name: str) -> str:
    return "1" if name in active_genes else "0"


def generate_ea(symbol: str, genome_id: str, tf: str,
                out_path: Path | None = None) -> Path:
    """Generate a standalone .mq5 EA for `genome_id`."""
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"template missing: {TEMPLATE_PATH}")
    genome = _load_genome(symbol, genome_id)
    params = genome.get("params") or {}
    stats  = genome.get("stats")  or {}
    active = genome.get("active_genes") or []

    # Build substitution dict
    subs = {
        "GENOME_ID":         genome_id,
        "SYMBOL":            symbol,
        "TIMEFRAME":         tf,
        "GENERATED_AT":      datetime.now(timezone.utc).isoformat(),
        "PF":                stats.get("profit_factor") or genome.get("profit_factor", 0),
        "WIN_RATE":          stats.get("win_rate") or genome.get("win_rate", 0),
        "TRADES":            stats.get("trades") or genome.get("trades", 0),
        # Genome params
        "SL_ATR_MULT":       float(params.get("sl_atr_mult") or genome.get("sl_atr_mult") or 1.5),
        "TP_ATR_MULT":       float(params.get("tp_atr_mult") or genome.get("tp_atr_mult") or 1.5),
        "START_HOUR":        int(params.get("start_hour") or genome.get("start_hour") or 0),
        "END_HOUR":          int(params.get("end_hour")   or genome.get("end_hour")   or 23),
        "RSI_PERIOD":        int(params.get("rsi_period",        DEFAULT_PARAMS["rsi_period"])),
        "EMA_FAST":          int(params.get("ema_fast",          DEFAULT_PARAMS["ema_fast"])),
        "EMA_SLOW":          int(params.get("ema_slow",          DEFAULT_PARAMS["ema_slow"])),
        "ATR_PERIOD":        int(params.get("atr_period",        DEFAULT_PARAMS["atr_period"])),
        "BREAKOUT_LOOKBACK": int(params.get("breakout_lookback", DEFAULT_PARAMS["breakout_lookback"])),
        # Management
        "USE_BREAKEVEN":     "true"  if "use_breakeven" in active else "false",
        "USE_FRIDAY_CLOSE":  "true"  if "use_friday_close_profit" in active else "false",
        # Gene flags (1/0 for #define)
        "SIG_BREAKOUT":      _flag(active, "use_sig_breakout"),
        "SIG_RSI":           _flag(active, "use_sig_rsi"),
        "SIG_MACD":          _flag(active, "use_sig_macd"),
        "SIG_ENGULFING":     _flag(active, "use_sig_engulfing"),
        "SIG_MOM_BREAK":     _flag(active, "use_sig_mom_break"),
        "BIAS_RSI":          _flag(active, "use_bias_rsi"),
        "BIAS_EMA":          _flag(active, "use_bias_ema"),
        "BIAS_SMA":          _flag(active, "use_bias_sma"),
        "FILT_ADX":          _flag(active, "use_filt_adx"),
        "FILT_CONSEC":       _flag(active, "use_filt_consec"),
    }

    # Render
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered = template
    for k, v in subs.items():
        rendered = rendered.replace(f"{{{{{k}}}}}", str(v))

    # Write
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = out_path or (OUT_DIR / f"R_{genome_id}.mq5")
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


def compile_ea(mq5_path: Path) -> tuple[bool, str]:
    """Invoke MetaEditor to compile the .mq5 → .ex5. Returns (success, log)."""
    if not COMPILER_PATH.exists():
        return False, f"MetaEditor not found at {COMPILER_PATH}"
    log_path = mq5_path.with_suffix(".log")
    try:
        subprocess.run([str(COMPILER_PATH),
                        f"/compile:{mq5_path}",
                        f"/log:{log_path}"],
                       check=False, timeout=60)
        ex5 = mq5_path.with_suffix(".ex5")
        if ex5.exists():
            return True, f"compiled → {ex5}"
        log = log_path.read_text(encoding="utf-16", errors="ignore") \
              if log_path.exists() else "(no log)"
        return False, log[:500]
    except Exception as e:
        return False, str(e)


def install_to_mt5(mq5_path: Path,
                   mt5_experts_dir: Path = Path(
                       r"C:\Program Files\MetaTrader 5 EXNESS\MQL5\Experts")) -> bool:
    """Copy the .mq5 (and .ex5 if compiled) into MT5's Experts folder."""
    if not mt5_experts_dir.exists():
        print(f"MT5 Experts dir not found: {mt5_experts_dir}")
        return False
    shutil.copy(mq5_path, mt5_experts_dir / mq5_path.name)
    ex5 = mq5_path.with_suffix(".ex5")
    if ex5.exists():
        shutil.copy(ex5, mt5_experts_dir / ex5.name)
    return True


# ── CLI ───────────────────────────────────────────────────────────────
def _cli():
    p = argparse.ArgumentParser(prog="r_native.mql5_export")
    p.add_argument("genome_id", help="genome ID to export (e.g. 98ED3A)")
    p.add_argument("symbol",    help="symbol (e.g. BTCUSDm)")
    p.add_argument("tf",        help="timeframe (e.g. M5)")
    p.add_argument("--compile", action="store_true",
                   help="also compile with MetaEditor → .ex5")
    p.add_argument("--install", action="store_true",
                   help="also copy to MT5 Experts dir (implies --compile)")
    args = p.parse_args()

    mq5 = generate_ea(args.symbol, args.genome_id, args.tf)
    print(f"✓ generated → {mq5}")

    if args.compile or args.install:
        ok, log = compile_ea(mq5)
        if ok: print(f"✓ {log}")
        else:  print(f"✗ compile failed: {log[:200]}")
        if args.install and ok:
            if install_to_mt5(mq5):
                print(f"✓ installed to MT5 Experts folder")


if __name__ == "__main__":
    _cli()

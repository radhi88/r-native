"""
algory_loader.py
----------------
Loads Algory strategy JSON files → AlgoryGenome → activates in live registry.

Gives FRIDAY immediate trading capability using Algory's validated strategies
without waiting for campaigns to finish.

Usage (called at startup):
    from mt5_ai.algory_loader import bootstrap_from_algory_vault
    bootstrap_from_algory_vault(integrator)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .algory_dna import AlgoryGenome, EXEC_GENES

log = logging.getLogger("algory_loader")

from .core.project_root import APPDATA_ALGORY as _APPDATA_ALGORY
ALGORY_VAULT = _APPDATA_ALGORY / "Generated_Strategies"

# exec_mode string in JSON → AlgoryGenome boolean fields
EXEC_MODE_MAP: dict[str, str] = {
    "market2": "exec_market2",
    "limit":   "exec_limit",
    "limit2":  "exec_limit2",
    "stop":    "exec_stop",
}


def _map_genome(raw: dict) -> dict:
    """Map Algory strategy JSON genome dict → AlgoryGenome field dict."""
    g = raw.get("genome", raw)  # some JSONs are flat

    kw: dict[str, Any] = {
        "id":         raw.get("id", str(uuid.uuid4())[:12]),
        "symbol":     raw.get("symbol", ""),
        "timeframe":  raw.get("timeframe", "H1"),
        "campaign":   "algory_import",
        "phase":      "imported",
        "created_at": raw.get("created_at", datetime.now(timezone.utc).isoformat()),
        "generation": 0,
        "parent_ids": [],
    }

    # ── Boolean genes (direct copy) ───────────────────────────────────────────
    bool_fields = {
        "use_bias_adx", "use_bias_chandelier", "use_bias_daily_mid",
        "use_bias_donchian_mid", "use_bias_ema", "use_bias_htf",
        "use_bias_market_struct", "use_bias_momentum", "use_bias_psar",
        "use_bias_rsi", "use_bias_sma", "use_bias_trailing",
        "use_sig_bb", "use_sig_breakout", "use_sig_cci", "use_sig_engulfing",
        "use_sig_fib", "use_sig_inside_break", "use_sig_macd", "use_sig_mom_break",
        "use_sig_pin_bar", "use_sig_rsi", "use_sig_stoch", "use_sig_three_soldiers",
        "use_sig_wick_rejection", "use_sig_williams",
        "use_filt_adr_exhaust", "use_filt_adx", "use_filt_bb", "use_filt_cci",
        "use_filt_consec", "use_filt_doji", "use_filt_keltner", "use_filt_receding",
        "use_filt_rsi", "use_filt_sma", "use_filt_volatility",
        "use_breakeven", "use_eod_close", "use_partial_tp", "use_sl_lock", "use_sl_reduce",
    }
    for f in bool_fields:
        if f in g:
            kw[f] = bool(g[f])

    # ── Exec mode: "stop" / "limit" / "limit2" / "market2" → bool flags ──────
    exec_mode = g.get("exec_mode", "")
    for mode_str, field_name in EXEC_MODE_MAP.items():
        kw[field_name] = (exec_mode == mode_str)

    # ── Numeric params (direct mapping where names match) ─────────────────────
    numeric_direct = [
        "start_hour", "end_hour", "friday_close",
        "rsi_period", "cci_period", "cci_limit",
        "bb_period", "bb_std", "sma_slow_period", "sma_fast_period",
        "adx_period", "adx_threshold", "stoch_k_period", "stoch_d_period", "stoch_slowing",
        "ema_period", "atr_ma_period", "trailing_period", "momentum_period",
        "williams_period", "williams_ob", "williams_os",
        "keltner_period", "keltner_mult", "htf_sma_period",
        "psar_step", "psar_max", "chand_mult",
        "consec_count", "wick_ratio", "fib_level", "fib_lookback",
        "breakout_lookback", "pin_bar_body_pct",
        "mom_break_atr", "soldiers_min_body_atr",
        "sweep_lookback_candles", "sweep_period",
        "adr_period", "adr_exhaust_pct",
        "limit_offset_atr", "limit_expiry_bars",
        "limit2_offset_atr", "stop_offset_atr", "stop_expiry_bars",
        "market2_window_bars", "market2_pullback_atr",
        "be_trigger_pct", "pt_trigger_pct", "pt_close_pct",
        "scale_max_trades",
    ]
    for f in numeric_direct:
        if f in g:
            kw[f] = g[f]

    # ── Renamed fields ─────────────────────────────────────────────────────────
    if "sl_mult" in g:
        kw["atr_sl_mult"] = float(g["sl_mult"])
    if "tp_mult" in g:
        kw["tp_max"] = float(g["tp_mult"])

    # ── Performance state from stats block ────────────────────────────────────
    stats = raw.get("stats", {})
    if stats:
        kw["trades"]     = int(stats.get("trades", 0))
        kw["wins"]       = int(round(stats.get("win_rate", 0) / 100.0 * kw["trades"]))
        kw["total_pnl"]  = float(stats.get("return_pct", 0)) * 1000.0  # approx on 100k balance
        kw["max_dd_pct"] = float(stats.get("drawdown_pct", 0))
        win_r = stats.get("win_rate", 50) / 100.0
        avg_w = kw["total_pnl"] * win_r / max(1, kw["wins"]) if kw["wins"] else 0
        avg_l = abs(kw["total_pnl"] * (1 - win_r)) / max(1, kw["trades"] - kw["wins"])
        kw["win_pnl"]  = avg_w * kw["wins"]
        kw["loss_pnl"] = avg_l * max(0, kw["trades"] - kw["wins"])

    # ── Name and advisor note ─────────────────────────────────────────────────
    kw["name"] = raw.get("id", "")
    kw["advisor_note"] = (
        f"Imported from Algory | "
        f"Ret={stats.get('return_pct', 0):.1f}% "
        f"DD={stats.get('drawdown_pct', 0):.1f}% "
        f"PF={stats.get('profit_factor', 0):.2f} "
        f"Tr={stats.get('trades', 0)}"
    )

    return kw


def load_algory_strategy(json_path: Path) -> AlgoryGenome | None:
    """Load a single Algory strategy JSON → AlgoryGenome."""
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        kw  = _map_genome(raw)
        return AlgoryGenome(**{k: v for k, v in kw.items()
                               if k in AlgoryGenome.__dataclass_fields__})
    except Exception as e:
        log.error("Failed to load %s: %s", json_path.name, e)
        return None


def scan_algory_vault(vault_path: Path = ALGORY_VAULT) -> list[Path]:
    """Find all strategy JSON files in Algory's vault."""
    if not vault_path.exists():
        log.warning("Algory vault not found: %s", vault_path)
        return []
    SKIP = {"_vault_index.json", "diagnostics.json", "config.json"}
    paths = [
        p for p in vault_path.rglob("*.json")
        if p.name not in SKIP
        and p.stat().st_size > 10_000  # skip tiny/empty files
    ]
    # Sort by newest first
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def bootstrap_from_algory_vault(integrator: Any, max_per_symbol_tf: int = 1) -> int:
    """
    Load Algory's best validated strategies → activate in integrator registry.

    Called at startup so trading begins immediately without waiting for campaigns.
    Returns number of genomes activated.
    """
    paths = scan_algory_vault()
    if not paths:
        log.warning("No Algory strategy JSONs found in vault")
        return 0

    activated  = 0
    seen: dict[tuple[str, str], int] = {}

    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        sym = raw.get("symbol", "")
        tf  = raw.get("timeframe", "")
        if not sym or not tf:
            continue

        key = (sym, tf)
        if seen.get(key, 0) >= max_per_symbol_tf:
            continue

        # Only load strategies with decent IS performance
        stats = raw.get("stats", {})
        if stats.get("drawdown_pct", 99) > 15:
            continue
        if stats.get("trades", 0) < 40:
            continue
        if stats.get("profit_factor", 0) < 1.2:
            continue

        genome = load_algory_strategy(path)
        if genome is None:
            continue

        # Quality gate — never activate an invalid genome
        try:
            from mt5_ai.core.genome_quality_gate import get_quality_gate as _gqg
            gr = _gqg().check(genome, source=f"algory_loader:{sym}|{tf}")
            if not gr.ok:
                log.warning("Blocked genome %s (%s|%s) [%s]: %s",
                            genome.name, sym, tf, gr.rule, gr.reason)
                continue
        except ImportError:
            pass

        integrator.registry.activate(genome, sym, tf)
        seen[key] = seen.get(key, 0) + 1
        activated += 1
        log.info(
            "Bootstrapped %s %s | id=%s ret=%.1f%% dd=%.1f%% pf=%.2f tr=%d",
            sym, tf, genome.name,
            stats.get("return_pct", 0), stats.get("drawdown_pct", 0),
            stats.get("profit_factor", 0), stats.get("trades", 0),
        )

    if activated:
        integrator.registry.save()
        log.info("Bootstrap complete: %d genome(s) activated", activated)
    return activated

"""strategy_io.py — J.6 — Export/import strategies as portable .r-strategy files.

A .r-strategy file is a signed JSON document containing:
- Genome (params + active_genes + flags)
- Stats (PF, WR, trades, sharpe, DD, etc.)
- Origin (campaign name, date, symbol, TF)
- SHA256 signature for integrity

Use case: share winning genomes between R Native installs, build community libraries,
back up your best strategies independently from the campaign vault.

CLI usage:
    python -m r_native.strategy_io export 98ED3A BTCUSDm M5  → strategies/98ED3A.r-strategy
    python -m r_native.strategy_io import path/to/X.r-strategy --symbol BTCUSDm
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

FORMAT_VERSION = "1.0"
EXPORT_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\exported_strategies")
SYMBOL_CFG_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
CAMPAIGN_DIR   = Path(r"C:\Users\Radhi\MT5\data\r_native\campaigns")


def _sign(payload: dict) -> str:
    """Deterministic SHA256 over the payload (excluding the signature field)."""
    clone = {k: v for k, v in payload.items() if k != "signature"}
    blob = json.dumps(clone, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ── Export ────────────────────────────────────────────────────────────
def export_strategy(genome_id: str, symbol: str, tf: str,
                    out_path: Path | None = None) -> Path:
    """Export a genome from the per-symbol vault. Looks up its full record
    in the source campaign for complete data."""
    # 1) Find slim entry in per-symbol config
    cfg_path = SYMBOL_CFG_DIR / f"{symbol}.json"
    if not cfg_path.exists():
        raise FileNotFoundError(f"no vault for symbol {symbol}")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    slim = next((s for s in cfg.get("ga_strategies", []) if s.get("id") == genome_id), None)
    if not slim:
        raise KeyError(f"genome {genome_id} not in {symbol} vault")

    # 2) Pull full record from source campaign (params + flags + trades + equity)
    src_camp = (slim.get("source") or "").replace("GA_campaign_", "")
    full_genome = None
    full_stats  = None
    if src_camp:
        vault_file = CAMPAIGN_DIR / src_camp / "vault.json"
        if vault_file.exists():
            try:
                vault = json.loads(vault_file.read_text(encoding="utf-8"))
                full = next((r for r in vault
                             if r.get("genome", {}).get("id") == genome_id), None)
                if full:
                    full_genome = full.get("genome")
                    full_stats  = full.get("stats")
            except Exception:
                pass

    # Fall back to slim if full not available
    genome = full_genome or {
        "id": genome_id,
        "active_genes": slim.get("active_genes", []),
        "params": {
            "sl_atr_mult": slim.get("sl_atr_mult"),
            "tp_atr_mult": slim.get("tp_atr_mult"),
            "start_hour":  slim.get("start_hour"),
            "end_hour":    slim.get("end_hour"),
        },
        "flags": {},
    }
    stats = full_stats or {k: slim.get(k) for k in
                            ("trades", "win_rate", "profit_factor",
                             "total_return_pct", "max_drawdown_pct",
                             "sharpe", "linearity")}

    payload = {
        "format_version": FORMAT_VERSION,
        "exported_at":   datetime.now(timezone.utc).isoformat(),
        "exported_by":   "R Native",
        "origin": {
            "symbol":   symbol,
            "timeframe": tf,
            "campaign":  src_camp or "(unknown)",
            "source":    slim.get("source") or "",
        },
        "genome":  genome,
        "stats":   stats,
    }
    payload["signature"] = _sign(payload)

    # Write file
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = out_path or (EXPORT_DIR /
                            f"{genome_id}_{symbol}_{tf}.r-strategy")
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return out_path


# ── Import ────────────────────────────────────────────────────────────
def import_strategy(file_path: str | Path,
                    target_symbol: str | None = None,
                    verify: bool = True) -> dict:
    """Read a .r-strategy file, verify signature, merge into target symbol's vault."""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"{p} not found")
    payload = json.loads(p.read_text(encoding="utf-8"))

    # Signature check
    if verify and payload.get("signature"):
        expected = _sign(payload)
        if expected != payload["signature"]:
            raise ValueError(f"signature mismatch: file may be tampered")

    symbol = target_symbol or payload["origin"]["symbol"]
    tf     = payload["origin"]["timeframe"]
    genome = payload["genome"]
    stats  = payload["stats"]

    # Build the slim entry to add to ga_strategies
    pf = stats.get("profit_factor", 0)
    slim = {
        "id":              genome.get("id"),
        "archetype":       "GA_EVOLVED_IMPORTED",
        "timeframe":       tf,
        "score":           stats.get("score", 0),
        "trades":          stats.get("trades", 0),
        "win_rate":        stats.get("win_rate", 0),
        "profit_factor":   pf,
        "total_return_pct":stats.get("total_return_pct", 0),
        "max_drawdown_pct":stats.get("max_drawdown_pct", 0),
        "sharpe":          stats.get("sharpe", 0),
        "linearity":       stats.get("linearity", 0),
        "confidence":      "DEPLOY" if pf >= 1.5 else "EVALUATE",
        "active_genes":    genome.get("active_genes", []),
        "sl_atr_mult":     (genome.get("params") or {}).get("sl_atr_mult"),
        "tp_atr_mult":     (genome.get("params") or {}).get("tp_atr_mult"),
        "start_hour":      (genome.get("params") or {}).get("start_hour"),
        "end_hour":        (genome.get("params") or {}).get("end_hour"),
        "source":          f"IMPORTED_{p.stem}",
        "created_at":      payload.get("exported_at"),
    }

    # Merge into target symbol's vault
    cfg_path = SYMBOL_CFG_DIR / f"{symbol}.json"
    cfg = {}
    if cfg_path.exists():
        try: cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception: pass
    by_id = {s["id"]: s for s in cfg.get("ga_strategies", []) if s.get("id")}
    by_id[slim["id"]] = slim
    cfg["ga_strategies"] = sorted(by_id.values(), key=lambda x: -(x.get("profit_factor", 0)))
    cfg["symbol"] = symbol
    SYMBOL_CFG_DIR.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    return {
        "ok":          True,
        "imported_id": slim["id"],
        "into_symbol": symbol,
        "total_strats_now": len(cfg["ga_strategies"]),
    }


# ── CLI ───────────────────────────────────────────────────────────────
def _cli():
    p = argparse.ArgumentParser(prog="r_native.strategy_io")
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("export", help="Export a genome to .r-strategy")
    pe.add_argument("genome_id")
    pe.add_argument("symbol")
    pe.add_argument("tf")
    pe.add_argument("--out", help="output path")

    pi = sub.add_parser("import", help="Import a .r-strategy into a symbol vault")
    pi.add_argument("file")
    pi.add_argument("--symbol", help="target symbol (defaults to origin)")
    pi.add_argument("--no-verify", action="store_true")

    args = p.parse_args()
    if args.cmd == "export":
        out = export_strategy(args.genome_id, args.symbol, args.tf,
                              Path(args.out) if args.out else None)
        print(f"✓ exported → {out}")
    elif args.cmd == "import":
        result = import_strategy(args.file, args.symbol,
                                 verify=not args.no_verify)
        print(f"✓ {result}")


if __name__ == "__main__":
    _cli()

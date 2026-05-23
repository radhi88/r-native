"""force_genes.py — Algory-style "force ON" override for management genes.

When user enables a force-gene, every genome in a campaign has that gene
turned on regardless of mutation. Useful for testing: "what if every
strategy had breakeven enabled?"

Stored: data/r_native/force_genes.json
{
  "use_breakeven":            false,
  "use_eod_close":            false,
  "use_friday_close_profit":  false,
  "use_partial_tp":           false,
  "use_sl_lock":              false,
  "use_sl_reduce":            false
}

Applied by genetic_engine after each genome generation but before evaluation.
"""
from __future__ import annotations
import json
from pathlib import Path

CONFIG_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\force_genes.json")

# Only management genes can be forced (signals/biases/filters need to evolve)
FORCEABLE = [
    "use_breakeven",
    "use_eod_close",
    "use_friday_close_profit",
    "use_partial_tp",
    "use_sl_lock",
    "use_sl_reduce",
]

DEFAULTS = {g: False for g in FORCEABLE}


def load() -> dict:
    if not CONFIG_PATH.exists(): return DEFAULTS.copy()
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = DEFAULTS.copy(); cfg.update(loaded); return cfg
    except Exception:
        return DEFAULTS.copy()


def save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def active() -> list[str]:
    """Return list of currently-forced gene names."""
    cfg = load()
    return [g for g, on in cfg.items() if on and g in FORCEABLE]


def apply_to_genome(genome_dict: dict) -> dict:
    """Mutate a genome's flags + active_genes to include forced genes.
    Returns the (mutated) genome."""
    forced = active()
    if not forced: return genome_dict
    flags = genome_dict.setdefault("flags", {})
    ag    = set(genome_dict.get("active_genes", []) or [])
    for g in forced:
        flags[g] = True
        ag.add(g)
    genome_dict["active_genes"] = sorted(ag)
    return genome_dict

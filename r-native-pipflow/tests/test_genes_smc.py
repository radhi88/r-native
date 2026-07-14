"""Tests for the SMC additions in genes.py — new flags, coherence repair,
smc_lean random seeding, group_intensities mutation."""
from __future__ import annotations

import os
import sys
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# Load genes.py as standalone module. We must register it in sys.modules
# BEFORE exec — dataclass uses sys.modules[cls.__module__] internally.
_modname = "genes_under_test"
spec = importlib.util.spec_from_file_location(_modname, os.path.join(REPO, "genes.py"))
g = importlib.util.module_from_spec(spec)
sys.modules[_modname] = g
spec.loader.exec_module(g)


def test_all_genes_count_61():
    assert len(g.ALL_GENES) == 61, f"expected 61 genes, got {len(g.ALL_GENES)}"
    print("OK test_all_genes_count_61")


def test_smc_flags_present():
    expected_smc_signals = {
        "use_sig_smc_ob", "use_sig_smc_fvg", "use_sig_smc_bos",
        "use_sig_smc_choch", "use_sig_smc_liq_sweep", "use_sig_smc_idm",
    }
    assert expected_smc_signals.issubset(g.SIGNAL_GENES)

    expected_smc_filters = {
        "use_filter_smc_fresh_only", "use_filter_smc_htf_alignment",
        "use_filter_smc_idm_required",
    }
    assert expected_smc_filters.issubset(g.FILTER_GENES)

    assert "sl_anchor_smc_ob" in g.SMC_PLACEMENT_GENES
    assert "tp_target_smc_liq" in g.SMC_PLACEMENT_GENES
    print("OK test_smc_flags_present")


def test_smc_cont_params_present():
    for k in ("smc_ob_buffer_atr", "smc_ob_freshness_bars", "smc_htf_lookback_bars"):
        assert k in g.CONT_PARAMS, f"missing cont param {k}"
    print("OK test_smc_cont_params_present")


def test_coherence_repair_pulls_signal_on():
    # Test the repair directly
    flags = {gene: False for gene in g.ALL_GENES}
    flags["sl_anchor_smc_ob"] = True
    g._repair_smc_coherence(flags)
    assert flags["use_sig_smc_ob"] is True, "OB SL anchor must pull signal flag on"

    flags = {gene: False for gene in g.ALL_GENES}
    flags["tp_target_smc_ob"] = True
    g._repair_smc_coherence(flags)
    assert flags["use_sig_smc_ob"] is True

    flags = {gene: False for gene in g.ALL_GENES}
    flags["tp_target_smc_liq"] = True
    g._repair_smc_coherence(flags)
    assert flags["use_sig_smc_liq_sweep"] or flags["use_sig_smc_idm"]
    print("OK test_coherence_repair_pulls_signal_on")


def test_random_smc_lean_increases_smc_density():
    # 200 random genomes — count SMC active flags. smc_lean=+1 should be denser.
    import random as _r
    _r.seed(42)
    base_count = 0; lean_count = 0
    for _ in range(200):
        gm = g.Genome.random(smc_lean=0.0)
        base_count += sum(gm.flags.get(s, False) for s in g.SMC_GENES)
    _r.seed(42)
    for _ in range(200):
        gm = g.Genome.random(smc_lean=1.0)
        lean_count += sum(gm.flags.get(s, False) for s in g.SMC_GENES)
    assert lean_count > base_count * 1.5, \
        f"smc_lean should boost density: base={base_count} lean={lean_count}"
    print(f"OK test_random_smc_lean_increases_smc_density (base={base_count} lean={lean_count})")


def test_mutate_group_intensities():
    import random as _r
    _r.seed(7)
    gm = g.Genome.random()
    # Capture initial SMC flag state
    initial_smc = {s: gm.flags.get(s, False) for s in g.SMC_GENES}
    # Mutate with massive SMC boost
    mutated = gm.mutate(intensity=0.0, group_intensities={
        "use_sig_smc_":   1.0,
        "use_filter_smc_": 1.0,
        "sl_anchor_smc_": 1.0,
        "tp_target_smc_": 1.0,
    })
    final_smc = {s: mutated.flags.get(s, False) for s in g.SMC_GENES}
    # Every SMC flag should have flipped (intensity=1.0)
    flipped = sum(1 for s in g.SMC_GENES if initial_smc[s] != final_smc[s])
    # Some flags may still be False due to coherence repair, so allow ≥ 50%
    assert flipped >= len(g.SMC_GENES) // 2, \
        f"only {flipped}/{len(g.SMC_GENES)} SMC flags flipped"
    print(f"OK test_mutate_group_intensities ({flipped}/{len(g.SMC_GENES)} flipped)")


def test_crossover_preserves_smc_coherence():
    a = g.Genome.random(smc_lean=1.0)
    b = g.Genome.random(smc_lean=1.0)
    child = g.Genome.crossover(a, b, gen=1)
    # If any SMC SL/TP anchor is on, matching signal must be on too
    if child.flags.get("sl_anchor_smc_ob") or child.flags.get("tp_target_smc_ob"):
        assert child.flags.get("use_sig_smc_ob")
    if child.flags.get("tp_target_smc_liq"):
        assert child.flags.get("use_sig_smc_liq_sweep") or child.flags.get("use_sig_smc_idm")
    print("OK test_crossover_preserves_smc_coherence")


def test_genome_id_changes_with_smc_flags():
    # Two genomes differing only in SMC flags should have different IDs
    gm1 = g.Genome(flags={s: False for s in g.ALL_GENES}, params={})
    gm2 = g.Genome(flags={s: (s == "use_sig_smc_ob") for s in g.ALL_GENES}, params={})
    assert gm1.id != gm2.id
    print("OK test_genome_id_changes_with_smc_flags")


if __name__ == "__main__":
    test_all_genes_count_61()
    test_smc_flags_present()
    test_smc_cont_params_present()
    test_coherence_repair_pulls_signal_on()
    test_random_smc_lean_increases_smc_density()
    test_mutate_group_intensities()
    test_crossover_preserves_smc_coherence()
    test_genome_id_changes_with_smc_flags()
    print("\n✓ all genes SMC tests passed")

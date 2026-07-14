"""genes.py - R Native gene system (mirrors Algory's 48-gene catalog, then exceeds it).

A GENOME = full strategy DNA: which indicators are ON + their parameters.
Random genome → backtest → score → genetic operations (cross/mutate/elite/revival).
"""
from __future__ import annotations
import json
import random
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional


# ─────────────────────────────────────────────────────────────────────
# THE 48 GENES (mirror Algory's gene catalog)
# ─────────────────────────────────────────────────────────────────────
EXECUTION_GENES = [
    "exec_market2",      # immediate market with strict offset
    "exec_limit",        # standard limit order
    "exec_limit2",       # limit with sub-bar fill
    "exec_stop",         # stop entry on breakout
]

BIAS_GENES = [
    "use_bias_adx",          "use_bias_chandelier",   "use_bias_daily_mid",
    "use_bias_donchian_mid", "use_bias_ema",          "use_bias_htf",
    "use_bias_market_struct","use_bias_momentum",     "use_bias_psar",
    "use_bias_rsi",          "use_bias_sma",          "use_bias_trailing",
]

SIGNAL_GENES = [
    "use_sig_bb",            "use_sig_breakout",      "use_sig_cci",
    "use_sig_engulfing",     "use_sig_fib",           "use_sig_inside_break",
    "use_sig_macd",          "use_sig_mom_break",     "use_sig_pin_bar",
    "use_sig_rsi",           "use_sig_stoch",         "use_sig_three_soldiers",
    "use_sig_wick_rejection","use_sig_williams",
]

FILTER_GENES = [
    "use_filt_adr_exhaust",  "use_filt_adx",          "use_filt_bb",
    "use_filt_cci",          "use_filt_consec",       "use_filt_doji",
    "use_filt_keltner",      "use_no_open_friday",    "use_filt_receding",
    "use_filt_rsi",          "use_filt_sma",          "use_filt_volatility",
]

EXIT_GENES = [
    "use_breakeven",         "use_eod_close",         "use_friday_close_profit",
    "use_partial_tp",        "use_sl_lock",           "use_sl_reduce",
]

ALL_GENES = EXECUTION_GENES + BIAS_GENES + SIGNAL_GENES + FILTER_GENES + EXIT_GENES
# 4 + 12 + 14 + 12 + 6 = 48 genes


# ─── Continuous parameters (always present, evolved separately) ───
CONT_PARAMS = {
    "sl_atr_mult":   (0.5, 4.0),     # SL = N × ATR
    "tp_atr_mult":   (1.0, 10.0),    # TP = N × ATR (RR ratio)
    "start_hour":    (0,   23),      # session start UTC
    "end_hour":      (0,   23),      # session end UTC
    "friday_close":  (12,  22),      # close-on-Friday hour
    "rsi_period":    (8,   28),
    "rsi_lower":     (15,  35),
    "rsi_upper":     (65,  85),
    "atr_period":    (10,  30),
    "ema_fast":      (5,   25),
    "ema_slow":      (15,  80),
    "breakout_lookback": (10, 50),
    "consec_max":    (1,   5),       # max consecutive losing trades
    "min_score":     (40,  90),      # minimum entry score
    "max_drawdown_stop": (3.0, 15.0),
    "kelly_fraction": (0.05, 0.5),
}


@dataclass
class Genome:
    """A full strategy DNA. Hashable for vault dedup."""
    flags: dict = field(default_factory=dict)        # gene_name → bool
    params: dict = field(default_factory=dict)       # cont_param_name → float
    # Provenance
    generation: int = 0
    parent_a: Optional[str] = None
    parent_b: Optional[str] = None
    method: str = "random"   # random / crossover / mutation / revival / elite

    # ── ID ──
    @property
    def id(self) -> str:
        body = json.dumps({"f": self.flags, "p": self.params}, sort_keys=True)
        return hashlib.md5(body.encode()).hexdigest()[:6].upper()

    # ── Factory: random ──
    @classmethod
    def random(cls, gen: int = 0) -> "Genome":
        # Bias toward FEWER active genes (sparser strategies trade more often)
        flags = {g: random.random() < 0.20 for g in ALL_GENES}
        # Ensure at least one exec mode is on
        if not any(flags[e] for e in EXECUTION_GENES):
            flags[random.choice(EXECUTION_GENES)] = True
        # Ensure at least one signal is on
        if not any(flags[s] for s in SIGNAL_GENES):
            flags[random.choice(SIGNAL_GENES)] = True
        params = {}
        for p, (lo, hi) in CONT_PARAMS.items():
            if isinstance(lo, int):
                params[p] = random.randint(lo, hi)
            else:
                params[p] = round(random.uniform(lo, hi), 3)
        # Ensure end_hour > start_hour
        if params["end_hour"] <= params["start_hour"]:
            params["end_hour"] = min(23, params["start_hour"] + 4)
        # Ensure ema_slow > ema_fast
        if params["ema_slow"] <= params["ema_fast"]:
            params["ema_slow"] = params["ema_fast"] + 5
        return cls(flags=flags, params=params, generation=gen, method="random")

    # ── Genetic operations ──
    @classmethod
    def crossover(cls, a: "Genome", b: "Genome", gen: int) -> "Genome":
        """Uniform crossover: each gene 50/50 from each parent."""
        flags = {g: (a.flags.get(g, False) if random.random() < 0.5 else b.flags.get(g, False))
                 for g in ALL_GENES}
        params = {}
        for p in CONT_PARAMS:
            params[p] = a.params.get(p) if random.random() < 0.5 else b.params.get(p)
        # Repair
        if not any(flags[e] for e in EXECUTION_GENES):
            flags[random.choice(EXECUTION_GENES)] = True
        if not any(flags[s] for s in SIGNAL_GENES):
            flags[random.choice(SIGNAL_GENES)] = True
        if params["end_hour"] <= params["start_hour"]:
            params["end_hour"] = min(23, params["start_hour"] + 4)
        if params["ema_slow"] <= params["ema_fast"]:
            params["ema_slow"] = params["ema_fast"] + 5
        return cls(flags=flags, params=params, generation=gen, method="crossover",
                   parent_a=a.id, parent_b=b.id)

    def mutate(self, intensity: float = 0.10, gen: int = 0) -> "Genome":
        """Bit-flip mutation + small param perturbation."""
        flags = dict(self.flags)
        for g in ALL_GENES:
            if random.random() < intensity:
                flags[g] = not flags[g]
        params = dict(self.params)
        for p, (lo, hi) in CONT_PARAMS.items():
            if random.random() < intensity:
                cur = params.get(p, (lo + hi) / 2)
                if isinstance(lo, int):
                    delta = max(1, int((hi - lo) * 0.1))
                    params[p] = max(lo, min(hi, int(cur + random.randint(-delta, delta))))
                else:
                    delta = (hi - lo) * 0.1
                    params[p] = round(max(lo, min(hi, cur + random.uniform(-delta, delta))), 3)
        # Repair
        if not any(flags[e] for e in EXECUTION_GENES):
            flags[random.choice(EXECUTION_GENES)] = True
        if not any(flags[s] for s in SIGNAL_GENES):
            flags[random.choice(SIGNAL_GENES)] = True
        if params["end_hour"] <= params["start_hour"]:
            params["end_hour"] = min(23, params["start_hour"] + 4)
        if params["ema_slow"] <= params["ema_fast"]:
            params["ema_slow"] = params["ema_fast"] + 5
        return Genome(flags=flags, params=params, generation=gen, method="mutation",
                      parent_a=self.id)

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "generation": self.generation,
            "method":     self.method,
            "parent_a":   self.parent_a,
            "parent_b":   self.parent_b,
            "flags":      self.flags,
            "params":     self.params,
            "active_genes": [g for g, on in self.flags.items() if on],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Genome":
        return cls(flags=d.get("flags", {}), params=d.get("params", {}),
                   generation=d.get("generation", 0), method=d.get("method", "?"),
                   parent_a=d.get("parent_a"), parent_b=d.get("parent_b"))


# ─── Scoring functions ───
def modern_score(stats: dict) -> float:
    """Algory-style 'Modern' score: balances PF, Sharpe, linearity, sample size."""
    if not stats or stats.get("trades", 0) < 10: return 0.0
    pf = stats.get("profit_factor", 0)
    sharpe = stats.get("sharpe", 0)
    linearity = stats.get("linearity", 0.5)
    wr = stats.get("win_rate", 0) / 100
    ret = stats.get("total_return_pct", 0)
    dd = max(0.5, stats.get("max_drawdown_pct", 5))
    trades = stats.get("trades", 0)
    # Sample size confidence: scales 0..1 with trades, plateau at 100
    sample_w = min(1.0, trades / 100)
    # PF component (cap at 5)
    pf_score = min(5, pf) / 5
    sharpe_score = max(0, min(3, sharpe)) / 3
    # Linear-y equity curve is best (low std around fitted line)
    lin_score = max(0, min(1, linearity))
    # Return/DD ratio
    rd_score = max(0, min(5, ret / dd)) / 5
    # Combined
    base = (pf_score * 30 + sharpe_score * 25 + lin_score * 20 + rd_score * 15 + wr * 10)
    return round(base * sample_w, 2)


def algory_purge_check(stats: dict, thresholds: dict = None) -> tuple[bool, str]:
    """Algory's purge criteria — keep if passes, kill if rejected.
    Default thresholds are PRACTICAL (more lenient than Algory's strict defaults
    so we get meaningful vault even on small bar windows / unusual symbols)."""
    th = thresholds or {
        "min_trades":     15,        # was 40 — too strict for short windows
        "max_dd":         15.0,      # was 10 — allow normal drawdown
        "min_pf":         1.1,       # was 1.2 — slight edge counts
        "min_ret":        2.0,       # was 6  — positive return is enough
        "min_linearity":  0.3,       # was 0.7 — drop unrealistic
    }
    if stats.get("trades", 0) < th["min_trades"]:
        return False, f"trades {stats.get('trades',0)} < {th['min_trades']}"
    if stats.get("max_drawdown_pct", 99) > th["max_dd"]:
        return False, f"DD {stats.get('max_drawdown_pct')} > {th['max_dd']}%"
    if stats.get("profit_factor", 0) < th["min_pf"]:
        return False, f"PF {stats.get('profit_factor',0)} < {th['min_pf']}"
    if stats.get("total_return_pct", 0) < th["min_ret"]:
        return False, f"return {stats.get('total_return_pct',0)}% < {th['min_ret']}%"
    if stats.get("linearity", 0) < th["min_linearity"]:
        return False, f"linearity {stats.get('linearity',0)} < {th['min_linearity']}"
    return True, "passed all thresholds"


if __name__ == "__main__":
    print(f"Total genes: {len(ALL_GENES)}")
    print(f"  execution: {len(EXECUTION_GENES)}")
    print(f"  bias:      {len(BIAS_GENES)}")
    print(f"  signal:    {len(SIGNAL_GENES)}")
    print(f"  filter:    {len(FILTER_GENES)}")
    print(f"  exit:      {len(EXIT_GENES)}")
    print(f"Continuous params: {len(CONT_PARAMS)}")
    print()
    g = Genome.random()
    print(f"Random genome {g.id}:")
    print(f"  active genes: {sum(g.flags.values())} / 48")
    print(f"  active: {[k for k,v in g.flags.items() if v][:6]}...")
    print(f"  sl_mult={g.params['sl_atr_mult']}  tp_mult={g.params['tp_atr_mult']}  hours={g.params['start_hour']}-{g.params['end_hour']}")
    print()
    g2 = Genome.random()
    child = Genome.crossover(g, g2, gen=1)
    print(f"Crossover child {child.id} from {g.id} × {g2.id}")
    m = child.mutate(intensity=0.15, gen=2)
    print(f"Mutated {m.id}: gens flipped, {sum(m.flags.values())} active genes")

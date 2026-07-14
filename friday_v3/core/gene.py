"""
gene.py — A single trading "gene" — parameterized aggressive dip-buyer.

Each gene = one strategy variation with specific parameters.
The gene pool tracks performance per gene; winners reproduce, losers die.

Gene DNA (10 evolvable parameters):
  • min_dip_score          — minimum dip quality (30-80)
  • min_drop_atr           — drop must be ≥ N×ATR (0.5-3.0)
  • max_rsi_m1             — only buy if RSI<X (15-45)
  • require_hammer         — bool (must see hammer rejection)
  • require_multi_tf       — bool (M5 must confirm)
  • profit_target_usd      — exit at $X profit (0.05-0.50)
  • sl_atr_mult            — SL = entry - N×ATR (0.5-3.0)
  • max_hold_minutes       — exit if open > N min (2-60)
  • lot_base               — base lot before kelly (0.01-0.05)
  • cooldown_seconds       — wait after a trade (30-600)
"""
from __future__ import annotations
import json
import random
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime


@dataclass
class GeneDNA:
    min_dip_score:       int   = 60
    min_drop_atr:        float = 1.0
    max_rsi_m1:          float = 35.0
    require_hammer:      bool  = False
    require_multi_tf:    bool  = True
    profit_target_usd:   float = 0.15
    sl_atr_mult:         float = 1.5
    max_hold_minutes:    int   = 15
    lot_base:            float = 0.01
    cooldown_seconds:    int   = 90

    def mutate(self, intensity: float = 0.15) -> "GeneDNA":
        """Return a mutated copy. Intensity = max % change."""
        def jitter_f(v, lo, hi, pct=intensity):
            new = v * (1 + random.uniform(-pct, pct))
            return round(max(lo, min(hi, new)), 3)
        def jitter_i(v, lo, hi, pct=intensity):
            return int(max(lo, min(hi, round(v * (1 + random.uniform(-pct, pct))))))
        def flip_maybe(v, p=0.1):
            return (not v) if random.random() < p else v

        return GeneDNA(
            min_dip_score    = jitter_i(self.min_dip_score, 30, 90),
            min_drop_atr     = jitter_f(self.min_drop_atr, 0.5, 3.0),
            max_rsi_m1       = jitter_f(self.max_rsi_m1, 15, 45),
            require_hammer   = flip_maybe(self.require_hammer),
            require_multi_tf = flip_maybe(self.require_multi_tf),
            profit_target_usd= jitter_f(self.profit_target_usd, 0.05, 0.50),
            sl_atr_mult      = jitter_f(self.sl_atr_mult, 0.5, 3.0),
            max_hold_minutes = jitter_i(self.max_hold_minutes, 2, 60),
            lot_base         = round(jitter_f(self.lot_base, 0.01, 0.05), 2),
            cooldown_seconds = jitter_i(self.cooldown_seconds, 30, 600),
        )

    @classmethod
    def random(cls) -> "GeneDNA":
        """Create a totally random gene (for initial pool diversity)."""
        return cls(
            min_dip_score    = random.randint(30, 90),
            min_drop_atr     = round(random.uniform(0.5, 3.0), 2),
            max_rsi_m1       = round(random.uniform(15, 45), 1),
            require_hammer   = random.random() < 0.3,
            require_multi_tf = random.random() < 0.7,
            profit_target_usd= round(random.uniform(0.05, 0.50), 2),
            sl_atr_mult      = round(random.uniform(0.5, 3.0), 2),
            max_hold_minutes = random.randint(2, 60),
            lot_base         = round(random.choice([0.01, 0.02, 0.03]), 2),
            cooldown_seconds = random.randint(30, 600),
        )

    @classmethod
    def crossover(cls, parent1: "GeneDNA", parent2: "GeneDNA") -> "GeneDNA":
        """Sexual reproduction — pick each gene's parameter from one parent at random."""
        d1, d2 = asdict(parent1), asdict(parent2)
        return cls(**{k: (d1[k] if random.random() < 0.5 else d2[k]) for k in d1})


@dataclass
class GeneStats:
    trades:      int = 0
    wins:        int = 0
    losses:      int = 0
    total_pl:    float = 0.0
    avg_win:     float = 0.0
    avg_loss:    float = 0.0
    max_drawdown: float = 0.0
    consecutive_losses: int = 0
    best_pl:     float = 0.0
    worst_pl:    float = 0.0
    last_trade_ts: str = ""
    age_cycles:  int = 0      # how many cycles this gene has survived

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        gains = self.wins * self.avg_win
        losses = self.losses * abs(self.avg_loss)
        return gains / losses if losses > 0 else 0.0

    @property
    def fitness(self) -> float:
        """Composite fitness — combines P/L, win rate, consistency."""
        if self.trades < 5:
            return 0.0          # too early to judge
        # Base: profit factor scaled by trade count
        base = self.profit_factor * min(1.0, self.trades / 20)
        # Penalty for high drawdown
        dd_penalty = max(0, 1 - self.max_drawdown / 10)
        # Bonus for consistent profit
        consistency = 1.0 + (0.2 if self.win_rate > 0.55 else 0)
        return round(base * dd_penalty * consistency, 3)


@dataclass
class Gene:
    id:         str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    generation: int = 1
    parent_ids: list = field(default_factory=list)
    dna:        GeneDNA = field(default_factory=GeneDNA)
    stats:      GeneStats = field(default_factory=GeneStats)
    born_at:    str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_signal_ts: float = 0.0     # epoch — for cooldown

    def can_trade(self, now_epoch: float) -> bool:
        """Cooldown gate."""
        return (now_epoch - self.last_signal_ts) >= self.dna.cooldown_seconds

    def evaluate_dip(self, sig) -> tuple[bool, str]:
        """Given a DipSignal, decide if this gene wants to trade.
        Returns (yes/no, reason)."""
        if sig.score < self.dna.min_dip_score:
            return False, f"score {sig.score} < {self.dna.min_dip_score}"
        if sig.drop_atr < self.dna.min_drop_atr:
            return False, f"drop_atr {sig.drop_atr} < {self.dna.min_drop_atr}"
        if sig.rsi_m1 > self.dna.max_rsi_m1:
            return False, f"rsi {sig.rsi_m1} > {self.dna.max_rsi_m1}"
        if self.dna.require_hammer and not sig.has_hammer:
            return False, "no hammer"
        if self.dna.require_multi_tf and not sig.multi_tf_aligned:
            return False, "no multi-tf"
        return True, "all filters passed"

    def record_trade_result(self, profit: float) -> None:
        """Update stats after a trade closes."""
        s = self.stats
        s.trades += 1
        s.total_pl += profit
        s.last_trade_ts = datetime.utcnow().isoformat()
        if profit > 0:
            s.wins += 1
            s.avg_win = (s.avg_win * (s.wins - 1) + profit) / s.wins
            s.consecutive_losses = 0
            s.best_pl = max(s.best_pl, profit)
        else:
            s.losses += 1
            s.avg_loss = (s.avg_loss * (s.losses - 1) + profit) / s.losses
            s.consecutive_losses += 1
            s.worst_pl = min(s.worst_pl, profit)
        # rough drawdown (cumulative neg P/L distance)
        s.max_drawdown = max(s.max_drawdown, abs(min(0, s.total_pl)))

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "generation":  self.generation,
            "parent_ids":  self.parent_ids,
            "dna":         asdict(self.dna),
            "stats":       asdict(self.stats),
            "born_at":     self.born_at,
            "last_signal_ts": self.last_signal_ts,
            "fitness":     self.stats.fitness,
            "win_rate":    round(self.stats.win_rate, 3),
            "profit_factor": round(self.stats.profit_factor, 2),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Gene":
        g = cls(
            id=d["id"], generation=d["generation"], parent_ids=d["parent_ids"],
            dna=GeneDNA(**d["dna"]), stats=GeneStats(**d["stats"]),
            born_at=d["born_at"],
        )
        g.last_signal_ts = d.get("last_signal_ts", 0.0)
        return g


if __name__ == "__main__":
    # Demo: create gene, mutate it, show DNA
    g = Gene()
    print("Default gene DNA:")
    print(json.dumps(asdict(g.dna), indent=2))

    print("\nMutated child:")
    child_dna = g.dna.mutate(0.2)
    print(json.dumps(asdict(child_dna), indent=2))

    print("\nRandom gene:")
    rand = GeneDNA.random()
    print(json.dumps(asdict(rand), indent=2))

"""genomes/base.py — genome ABC + thesis contract.

Every CLAUDE-* genome inherits from Genome and MUST:
  • have a thesis string (the WHY — judged later vs. actual results)
  • implement propose() that returns Proposal or None
  • declare the symbol(s) it trades and side restrictions

Genomes do NOT send orders directly. They propose. The council decides.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
from r_native_v2.council.types import Proposal


class Genome(ABC):
    name:    str = "BASE"
    thesis:  str = ""
    symbols: tuple = ()
    sides:   tuple = ("BUY", "SELL")
    lot:     float = 0.01

    @abstractmethod
    def propose(self, snapshot, account) -> Optional[Proposal]:
        """Return a Proposal if conditions warrant a trade, else None."""
        ...

    def __repr__(self):
        return f"<Genome {self.name} on {self.symbols} sides={self.sides}>"

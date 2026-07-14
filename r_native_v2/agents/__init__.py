"""agents/__init__.py — V2 background agents.

Three specialist agents serve the council and genome journal:

  live_journal     — writes a narrative story for every closed trade
  council_logger   — aggregates vote tallies + dissent patterns
  thesis_validator — periodically checks genome thesis vs actual results
"""
from .live_journal     import LiveJournal
from .council_logger   import CouncilLogger
from .thesis_validator import ThesisValidator

__all__ = ["LiveJournal", "CouncilLogger", "ThesisValidator"]

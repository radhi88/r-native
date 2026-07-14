"""Strategy DNA helpers.

DNA is config and performance memory only. It never rewrites Python source code.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


class StrategyDNA:
    def __init__(self, genome: dict[str, Any]):
        self.genome = deepcopy(genome)

    def agent_weight(self, source: str, default: float = 1.0) -> float:
        return float(self.genome.get("agent_weights", {}).get(source, default))

    def threshold(self, key: str, default: float) -> float:
        return float(self.genome.get("confidence_thresholds", {}).get(key, default))

    def risk_value(self, key: str, default: float) -> float:
        return float(self.genome.get("risk", {}).get(key, default))

    def symbol_config(self, symbol: str) -> dict[str, Any]:
        return dict(self.genome.get("symbols", {}).get(symbol, {}))

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.genome)


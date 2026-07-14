"""magic_registry.py — Single source of truth for all FRIDAY magic numbers."""
from __future__ import annotations

# ── Registered magic numbers ─────────────────────────────────────────────────
REGISTRY: dict[str, int] = {
    "QADER_REAL_CONTROLLED": 20260514,  # Qader GUI-gated real controlled mode
    "FRIDAY_ALGORY":   20260600,  # algory_runner.py — active live executor
    "FRIDAY_SMC":      20260601,  # future smc_agent
    "FRIDAY_ICT":      20260602,  # future ict_sweep_agent
    "FRIDAY_SCALPER":  20260603,  # future scalper_agent
    "FRIDAY_TOUCH":    20260604,  # future touch_agent
    "FRIDAY_GOVERNOR": 20260605,  # future position_manager
    "FRIDAY_OLLAMA":   20260606,  # future ollama/ai_agent
    "MANUAL_TEST":     20260699,  # reserved for manual/test trades
}

# Legacy magics (inactive executors — kept for learner filtering)
LEGACY_MAGICS: set[int] = {20260504, 20260505, 20260506, 20260507}

# All known FRIDAY magics (used by learner files to filter trade history)
ALL_FRIDAY_MAGICS: set[int] = set(REGISTRY.values()) | LEGACY_MAGICS

# Reverse lookup
_REVERSE = {v: k for k, v in REGISTRY.items()}

def get_magic(strategy_id: str) -> int:
    m = REGISTRY.get(strategy_id)
    if m is None:
        raise KeyError(f"Unknown strategy_id '{strategy_id}' — register it in magic_registry.py")
    return m

def get_strategy(magic: int) -> str:
    return _REVERSE.get(magic, f"UNKNOWN_{magic}")

def is_known(magic: int) -> bool:
    return magic in ALL_FRIDAY_MAGICS

def validate_request(magic: int, source: str) -> None:
    if magic in LEGACY_MAGICS:
        raise ValueError(
            f"ExecutionRequest from '{source}' uses disabled legacy magic {magic}"
        )
    if not is_known(magic):
        raise ValueError(f"ExecutionRequest from '{source}' uses unregistered magic {magic}")

# Convenience constants
QADER_REAL_CONTROLLED_MAGIC = REGISTRY["QADER_REAL_CONTROLLED"]
ALGORY_MAGIC   = REGISTRY["FRIDAY_ALGORY"]
SMC_MAGIC      = REGISTRY["FRIDAY_SMC"]
ICT_MAGIC      = REGISTRY["FRIDAY_ICT"]
SCALPER_MAGIC  = REGISTRY["FRIDAY_SCALPER"]
TOUCH_MAGIC    = REGISTRY["FRIDAY_TOUCH"]
GOVERNOR_MAGIC = REGISTRY["FRIDAY_GOVERNOR"]
OLLAMA_MAGIC   = REGISTRY["FRIDAY_OLLAMA"]

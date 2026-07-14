"""
run_agents.py — FRIDAY Multi-Agent Runner (paper/demo mode only).

Usage:
    .venv\\Scripts\\python.exe scripts\\run_agents.py

The runner:
  1. Connects to MT5 gateway (demo account)
  2. Builds a market_state dict each bar from live MT5 data + signal pipeline
  3. Passes market_state to AgentCoordinator.on_bar() every N seconds
  4. Prints a status summary periodically
"""

import logging
import sys
import time
from pathlib import Path

# ── project path ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mt5_ai.agents import AgentCoordinator
from mt5_ai.config import (
    DEMO_TRADING_ENABLED,
    LIVE_TRADING_ENABLED,
    MT5_SYMBOL,
)
from mt5_ai.execution import DemoMT5Executor, PaperExecutor

# ── safety gate ───────────────────────────────────────────────────────────────
assert not LIVE_TRADING_ENABLED, "Live trading must be disabled — demo/paper only."

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("friday.runner")

BAR_INTERVAL_SEC = 60   # poll every 60 s (≈ M1 bar)
STATUS_EVERY     = 10   # print status every N bars


def build_market_state_paper() -> dict:
    """
    Placeholder: returns a dummy market state for offline/paper testing.
    Replace with real pipeline output (mt5_gateway + market_structure + ai_brain).
    """
    import random
    p = random.uniform(0.30, 0.75)
    return {
        "probability":    p,
        "smc_buy_score":  random.randint(0, 4),
        "smc_sell_score": random.randint(0, 4),
        "bias":           random.choice([-2, -1, 0, 1, 2]),
        "context_score":  random.randint(0, 3),
        "spread_points":  random.uniform(10, 200),
        "atr":            1.5,
        "price":          random.uniform(2300, 2400),
        "ob_buy_level":   0.0,
        "ob_sell_level":  0.0,
        "fvg_low":        0.0,
        "fvg_high":       0.0,
    }


def main():
    log.info("FRIDAY Multi-Agent System starting — PAPER mode")
    log.info("Symbol: %s | Live trading locked: %s", MT5_SYMBOL, not LIVE_TRADING_ENABLED)

    # Use PaperExecutor by default; swap to DemoMT5Executor when MT5 is live
    executor = PaperExecutor()

    coordinator = AgentCoordinator(executor=executor, symbol=MT5_SYMBOL)
    log.info("Agents loaded: %s", [a.name for a in coordinator.agents])

    bar = 0
    try:
        while True:
            bar += 1
            market_state = build_market_state_paper()
            coordinator.on_bar(market_state)

            if bar % STATUS_EVERY == 0:
                status = coordinator.status()
                open_pos = status["open_positions"]
                log.info("── Bar %d ── open positions: %d", bar, len(open_pos))
                for agent_name, summary in status["agent_summaries"].items():
                    if summary.get("trades", 0) > 0:
                        log.info(
                            "  [%s] trades=%d win_rate=%.1f%% pf=%.2f | buy_thr=%.2f sell_thr=%.2f",
                            agent_name,
                            summary["trades"],
                            summary["win_rate"] * 100,
                            summary["profit_factor"],
                            summary["thresholds"]["buy_threshold"],
                            summary["thresholds"]["sell_threshold"],
                        )

            time.sleep(BAR_INTERVAL_SEC)

    except KeyboardInterrupt:
        log.info("Stopped by user.")
        final = coordinator.status()
        log.info("Final status: %s", final)


if __name__ == "__main__":
    main()

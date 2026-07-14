"""r_native.agents — always-on AI advisors that actually do work.

These are NOT cosmetic background processes. Each agent:
  • runs on its own thread with a real interval
  • inspects live state (HoF, executor, market, positions)
  • makes actual decisions: pin/unpin genomes, propose deploys,
    trigger kill_switch, generate audit reports, route by regime
  • all decisions are logged with reasoning + persisted
  • can be paused/resumed individually from the UI

The orchestrator owns all agent lifecycles and exposes a unified
insights stream via brain_server's /api/r/agents/* endpoints.
"""

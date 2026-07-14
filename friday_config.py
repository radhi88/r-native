"""
friday_config.py — Centralized configuration for all FRIDAY components.

Edit this file to tune the entire system. All other modules read from here.
"""
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════
# IDENTITY
# ═══════════════════════════════════════════════════════════════════════════

SYMBOL              = "XAUUSDm"          # main trading symbol
TIMEFRAME_M         = 1                  # M1
MAGIC               = 20260600           # FRIDAY brain's unique tag
OWNER_LOGIN         = 260896436          # MT5 account number (just a safety check)
COMMENT_PREFIX      = "FRIDAY"           # MT5 only allows ASCII in comments

# ═══════════════════════════════════════════════════════════════════════════
# RISK MODEL — tuned for small account (~$50-100)
# Adjust these if balance grows beyond $200
# ═══════════════════════════════════════════════════════════════════════════

# Position sizing
MIN_LOT                  = 0.01
MAX_LOT                  = 0.02          # cap so a single loss can't blow account
MAX_RISK_PCT_PER_TRADE   = 5.0           # % of balance at risk per trade
MAX_TOTAL_RISK_PCT       = 12.0          # cap on combined risk of all open + pending

# Concurrency caps
MAX_ORDERS               = 3             # total pendings + positions
MAX_OPEN_POSITIONS       = 2
COOLDOWN_S               = 30            # seconds between full-cycle orders
SCALP_COOLDOWN_S         = 20            # seconds between scalp orders

# Stop-loss & take-profit constraints
REQUIRE_SL               = True          # every order MUST have SL
MIN_SL_DISTANCE_PT       = 80            # SL must be ≥ 80 points from entry
MAX_SL_DISTANCE_PT       = 800           # SL can't be ≥ 800 points (else risk too big)
MIN_RR_RATIO             = 1.5           # reward / risk minimum
MIN_SPREAD_TO_MOVE_MULT  = 3.0           # TP move ≥ 3 × current spread

# Spread guard
MAX_SPREAD_POINTS        = 600           # don't trade if spread above this
SCALP_MAX_SPREAD         = 450           # scalps need tighter spread

# Pendings lifecycle
PENDING_MAX_AGE_S        = 1800          # cancel pendings older than 30 min
PENDING_FLIP_BIAS_CANCEL = True          # cancel BUY pendings if bias → SELL

# Position management
BREAKEVEN_TRIGGER_R      = 0.8           # move SL to BE when profit ≥ 0.8×R
BREAKEVEN_BUFFER_PCT     = 10            # how far above entry SL settles (% of original risk)
CLOSE_ON_CHOCH_AGAINST   = True          # close if CHoCH flips against position

# Multi-stage trailing SL — tightens as profit grows to lock gains against reversals
# Stage thresholds: profit in multiples of original risk (R)
TRAIL_STAGE1_R           = 1.0          # after BE: start trailing at wide distance
TRAIL_STAGE2_R           = 1.5          # profit ≥ 1.5R → tighten trail
TRAIL_STAGE3_R           = 2.5          # profit ≥ 2.5R → tighten more
TRAIL_STAGE4_R           = 3.5          # profit ≥ 3.5R → lock near TP

# Trail distances: how far behind the peak price the SL sits (in R units)
TRAIL_DIST_STAGE1        = 0.85         # initial trail: 0.85R behind peak
TRAIL_DIST_STAGE2        = 0.55         # 1.5R profit: 0.55R behind peak
TRAIL_DIST_STAGE3        = 0.35         # 2.5R profit: 0.35R behind peak
TRAIL_DIST_STAGE4        = 0.20         # 3.5R profit: 0.20R behind peak (very tight)

TRAIL_MIN_MOVE_PT        = 2.0          # minimum price move (pts) before modifying SL

# ═══════════════════════════════════════════════════════════════════════════
# MOMENTUM / SCALP DETECTOR
# ═══════════════════════════════════════════════════════════════════════════

MOMENTUM_BARS_WINDOW     = 10            # look at last N bars
WHALE_BODY_EXP           = 1.8           # body must be ≥ N× the recent average
WHALE_STREAK             = 2             # min consecutive same-direction bars
WHALE_RANGE_EXP          = 1.2           # range must be ≥ N× the recent average
WHALE_BR_RATIO           = 0.55          # body/range ratio (full-body candles)
SCALP_TRIGGER_SCORE      = 60            # score threshold to enter
SCALP_SL_ATR_MULT        = 0.8
SCALP_TP_ATR_MULT        = 2.0           # R:R 1:2.5 on scalps

# ═══════════════════════════════════════════════════════════════════════════
# FVG (FAIR VALUE GAP) — fast limit entries into imbalance zones
# A 3-candle gap where price must return to "fill" before continuing.
# Entry: LIMIT at 50% of the gap. SL: beyond gap edge. TP: 2R.
# ═══════════════════════════════════════════════════════════════════════════

FVG_ENABLED         = True
FVG_MAX_AGE_BARS    = 8       # ignore FVGs older than this many M1 bars
FVG_MIN_SIZE_PT     = 30      # minimum gap size in points (30pt = $0.30 on gold)
FVG_SL_BUFFER_PT    = 60      # extra buffer beyond FVG edge for SL placement
FVG_TP_RR           = 2.0     # TP at 2R from entry
FVG_MAX_SPREAD_PT   = 420     # max spread to allow FVG entry (tighter than scalp)
FVG_COOLDOWN_S      = 45      # seconds between consecutive FVG limit placements

# ═══════════════════════════════════════════════════════════════════════════
# LLM / AGENTS
# ═══════════════════════════════════════════════════════════════════════════

CYCLE_SECONDS            = 8             # full agent cycle interval
LLM_TIMEOUT_SECONDS      = 45
OLLAMA_URL               = "http://localhost:11434/api/chat"
# All agents on qwen2.5:3b — RTX 5060 Laptop (8GB) can comfortably handle 5 parallel
# requests on the 3b model (each ~1GB context). Inference 3-4× faster than 7b.
FAST_MODEL               = "qwen2.5:3b"
DEEP_MODEL               = "qwen2.5:3b"
CLAUDE_COORDINATOR_MODEL = "claude-sonnet-4-5"
USE_CLAUDE_FOR_COORDINATOR_IF_KEY = True   # auto-enable if ANTHROPIC_API_KEY set

# ═══════════════════════════════════════════════════════════════════════════
# PATHS — usually no need to change
# ═══════════════════════════════════════════════════════════════════════════

ROOT        = Path(r"C:\Users\Radhi\MT5")
MT5_COMMON  = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
VAULT       = ROOT / "plutobrain"
DASHBOARD   = ROOT / "dashboard"
KILL_SWITCH = ROOT / "kill_switch.txt"
BUS_FILE    = ROOT / "friday_bus.json"
LEVELS_FILE = ROOT / "friday_levels.json"
ORDERS_LOG  = ROOT / "friday_orders.csv"
BRAIN_STATE = ROOT / "friday_brain_v2_state.json"
EA_ORDERS   = MT5_COMMON / "friday_brain_orders.json"


def summary() -> str:
    """Return human-readable settings summary."""
    return f"""
═════════════════════════════════════════════════════
  FRIDAY Configuration Summary
═════════════════════════════════════════════════════
  Symbol:       {SYMBOL} M{TIMEFRAME_M}
  Magic:        {MAGIC}
  Account:      {OWNER_LOGIN}

  Risk model:
    Lot:                {MIN_LOT} - {MAX_LOT}
    Max risk/trade:     {MAX_RISK_PCT_PER_TRADE}%
    Max total exposure: {MAX_TOTAL_RISK_PCT}%
    Min R:R:            1:{MIN_RR_RATIO}
    SL range:           {MIN_SL_DISTANCE_PT} - {MAX_SL_DISTANCE_PT} points

  Concurrency:
    Max orders:         {MAX_ORDERS}  (positions + pendings)
    Max positions:      {MAX_OPEN_POSITIONS}
    Order cooldown:     {COOLDOWN_S}s
    Scalp cooldown:     {SCALP_COOLDOWN_S}s

  Spread guards:
    Max spread:         {MAX_SPREAD_POINTS}pt
    Scalp max spread:   {SCALP_MAX_SPREAD}pt
    TP move ≥           {MIN_SPREAD_TO_MOVE_MULT}× spread

  Position management:
    Move to BE at:      {BREAKEVEN_TRIGGER_R}R profit
    Trail distance:     {TRAIL_DISTANCE_R}R
    Close on CHoCH:     {CLOSE_ON_CHOCH_AGAINST}
    Cancel stale at:    {PENDING_MAX_AGE_S}s

  Scalp / momentum:
    Trigger score ≥     {SCALP_TRIGGER_SCORE}
    Whale: body×{WHALE_BODY_EXP} streak≥{WHALE_STREAK} range×{WHALE_RANGE_EXP}

  Cycle:               every {CYCLE_SECONDS}s
  LLM models:          fast={FAST_MODEL}  deep={DEEP_MODEL}
═════════════════════════════════════════════════════
"""


if __name__ == "__main__":
    print(summary())

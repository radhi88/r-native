import os
from pathlib import Path


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PREPARED_DIR = DATA_DIR / "prepared"
MODELS_DIR = PROJECT_ROOT / "models"
CHECKPOINT_DIR = MODELS_DIR / "checkpoints"
LOG_DIR = PROJECT_ROOT / "logs"
REPORT_DIR = PROJECT_ROOT / "reports"
JOURNAL_DIR = DATA_DIR / "journal"

for directory in (
    RAW_DATA_DIR,
    PREPARED_DIR,
    MODELS_DIR,
    CHECKPOINT_DIR,
    LOG_DIR,
    REPORT_DIR,
    JOURNAL_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)


# Data / MT5
MT5_SYMBOL = "XAUUSDm"
MT5_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe"
TIMEFRAME = "M1"
CSV_HISTORY = RAW_DATA_DIR / f"mt5_history_{MT5_SYMBOL}.csv"
TRAINING_DATA_CSV = RAW_DATA_DIR / "training_data.csv"


# Sequence settings
SEQ_LEN = 200
HORIZON = 20
MIN_MOVE_ATR_MULT = 0.5
FEATURE_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "atr",
    "macd",
    "macd_sig",
    "trend",
    "rsi",
    "adx",
    "mfi",
    "voi_pct",
    "spr",
    "dch",
    "demand",
    "supply",
]
FEATURES = len(FEATURE_COLUMNS)


# Model artifacts
MODEL_PATH = MODELS_DIR / "hybrid_model.keras"
SCALER_PATH = MODELS_DIR / "scaler.save"
MODEL_CANDIDATES = [
    MODEL_PATH,
    MODELS_DIR / "hybrid_model.h5",
    MODELS_DIR / "model.keras",
    MODELS_DIR / "model.h5",
    MODELS_DIR / "best_model.keras",
    CHECKPOINT_DIR / "best_model.keras",
]


# Streaming / AI server
ZMQ_BIND = "tcp://127.0.0.1:5555"
SEQ_LEN_EXPECTED = SEQ_LEN


# Incremental learning
BUFFER_PATH = DATA_DIR / "stream_buffer.npy"
NEW_BATCH_X_PATH = PREPARED_DIR / "new_batch_X.npy"
NEW_BATCH_Y_PATH = PREPARED_DIR / "new_batch_y.npy"
INCREMENTAL_BATCH = 256


# Trading controls
DEMO_MODE = True
DEMO_TRADING_ENABLED = True
DEMO_SERVER_KEYWORDS = ("demo", "trial", "practice", "contest")
LIVE_MODE_ALLOWED = True
LIVE_TRADING_ENABLED = True
AUTO_LEARNING_ENABLED = True
AUTO_LEARNING_MODE = "paper"
COOLDOWN_SECONDS = 30
MAX_DAILY_LOSS_USD = 100.0
BUY_THRESHOLD = 0.60
SELL_THRESHOLD = 0.40
DEFAULT_LOT = 0.01
MAX_LOT = 0.05
MAX_DEMO_OPEN_ORDERS = 3
DEFAULT_DEVIATION = 20
DEFAULT_MAGIC = 260426
LIVE_CONFIRM_ENV = "MT5_AI_LIVE_TRADING"
LIVE_CONFIRM_VALUE = "YES_I_ACCEPT_RISK"
MAX_MARKET_SCAN_SYMBOLS = 60
MAX_PAPER_SCAN_ORDERS = 3


# Optional Claude committee. Disabled by default to keep normal runs local and
# avoid paid API calls unless explicitly requested by the operator.
CLAUDE_COMMITTEE_ENABLED = _env_flag("MT5_AI_CLAUDE_COMMITTEE", False)
CLAUDE_COMMITTEE_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
CLAUDE_COMMITTEE_MIN_CONFIDENCE = _env_float("MT5_AI_CLAUDE_MIN_CONFIDENCE", 0.35)
CLAUDE_COMMITTEE_COOLDOWN_BARS = _env_int("MT5_AI_CLAUDE_COOLDOWN_BARS", 5)


# Smart-money / ICT feature controls
SWING_LOOKBACK = 20
LIQUIDITY_LOOKBACK = 40
FVG_MIN_ATR_MULT = 0.20
OB_LOOKBACK = 12

# Estimated bid-ask spread (in points) used as fallback when the data source
# (e.g. an offline CSV) has no real spread column.
# This is an APPROXIMATION — not real market spread.
# XAUUSDm ECN typical spread: 15–30 points. Tune per symbol if needed.
ESTIMATED_SPREAD_POINTS_CSV = 20.0

# Global spread ceiling (points). Overrides per-profile max_spread.
# XAUUSDm can spike to 350-400+ during news. Set to None to use per-profile limits.
MAX_SPREAD_OVERRIDE = 500

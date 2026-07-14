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
MT5_SYMBOL = os.environ.get("FRIDAY_DEFAULT_SYMBOL", "XAUUSDm").strip() or "XAUUSDm"
DEFAULT_SYMBOLS = [
    symbol.strip()
    for symbol in os.environ.get(
        "FRIDAY_DEFAULT_SYMBOLS",
        "XAUUSDm,XAGUSDm,EURUSDm,GBPUSDm,USDJPYm,USDCHFm,USDCADm,AUDUSDm,NZDUSDm,EURJPYm,GBPJPYm,BTCUSDm,ETHUSDm,USOILm,UKOILm",
    ).split(",")
    if symbol.strip()
]
MT5_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe"
TIMEFRAME = "M1"
PARQUET_HISTORY = RAW_DATA_DIR / f"{MT5_SYMBOL}_history.parquet"
CSV_HISTORY = RAW_DATA_DIR / f"mt5_history_{MT5_SYMBOL}.csv"
TRAINING_DATA_CSV = RAW_DATA_DIR / "training_data.csv"


# Sequence settings
SEQ_LEN = 200
HORIZON = 20
MIN_MOVE_ATR_MULT = 0.5
FEATURE_COLUMNS = [
    # ── Base OHLCV + indicators (17) ─────────────────────────────────────────
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
    # ── SMC / market-structure features (14) ─────────────────────────────────
    "bos_up",
    "bos_down",
    "choch_up",
    "choch_down",
    "buy_side_liquidity_sweep",
    "sell_side_liquidity_sweep",
    "bullish_fvg",
    "bearish_fvg",
    "in_bullish_ob",
    "in_bearish_ob",
    "smc_buy_score",
    "smc_sell_score",
    "smc_bias",
    "upper_wick_ratio",
    "lower_wick_ratio",
]
FEATURES = len(FEATURE_COLUMNS)  # 31


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


# ── Per-symbol model artifacts (Phase 3 — subfolder layout, D-04) ───────────
# Layout: models/{SYMBOL}/model.keras + models/{SYMBOL}/scaler.pkl
# This SUPERSEDES the flat models/{SYMBOL}_model.keras naming (D-04a override).
def symbol_model_dir(symbol: str) -> Path:
    return MODELS_DIR / str(symbol).strip()

def symbol_model_path(symbol: str) -> Path:
    return symbol_model_dir(symbol) / "model.keras"

def symbol_scaler_path(symbol: str) -> Path:
    return symbol_model_dir(symbol) / "scaler.pkl"


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
DEMO_TRADING_ENABLED = False
DEMO_SERVER_KEYWORDS = ("demo", "trial", "practice", "contest")
LIVE_MODE_ALLOWED = False
LIVE_TRADING_ENABLED = False
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
DEFAULT_MAGIC = 20260600
LIVE_CONFIRM_ENV = "MT5_AI_LIVE_TRADING"
LIVE_CONFIRM_VALUE = "YES_I_ACCEPT_RISK"
MAX_MARKET_SCAN_SYMBOLS = 60
MAX_PAPER_SCAN_ORDERS = 3


# Daily Pivot Channels confirmation layer
USE_PIVOT_FILTER = _env_flag("USE_PIVOT_FILTER", True)
USE_PIVOT_CONFIDENCE_BOOST = _env_flag("USE_PIVOT_CONFIDENCE_BOOST", True)
USE_MID_PIVOT_LEVELS = _env_flag("USE_MID_PIVOT_LEVELS", True)
PIVOT_CONFIDENCE_BOOST = _env_float("PIVOT_CONFIDENCE_BOOST", 0.15)
PIVOT_BIAS_BOOST = _env_float("PIVOT_BIAS_BOOST", 0.05)
PIVOT_TOUCH_TOLERANCE_POINTS = _env_int("PIVOT_TOUCH_TOLERANCE_POINTS", 200)
PIVOT_PENDING_DISTANCE_POINTS = _env_int("PIVOT_PENDING_DISTANCE_POINTS", 500)

# ── Multi-agent SMC scalping ────────────────────────────────────────────────
# لا قيود على السبريد في أي وكيل — النظام الجديد يتجاهل السبريد تماماً
AGGRESSIVE_SCALPING_IGNORE_SPREAD = True  # ثابت دائماً — لا تعديل
SMC_ENTRY_BUY_PROB   = _env_float("FRIDAY_BUY_PROB",  0.60)   # عتبة الشراء للـEntryAgent
SMC_ENTRY_SELL_PROB  = _env_float("FRIDAY_SELL_PROB", 0.40)   # عتبة البيع
SMC_MIN_SCORE        = _env_int("FRIDAY_MIN_SMC",  2)          # الحد الأدنى لدرجة SMC
MONITOR_BE_ATR_MULT  = _env_float("FRIDAY_BE_ATR",   1.0)     # ATR multiplier للـBreak-Even
MONITOR_TRAIL_MULT   = _env_float("FRIDAY_TRAIL_ATR", 1.2)    # ATR multiplier للـTrailing SL
RISK_MIN_RR          = _env_float("FRIDAY_MIN_RR",   1.5)     # الحد الأدنى لنسبة R:R
RISK_SL_ATR_MULT     = _env_float("FRIDAY_SL_ATR",   0.8)     # ATR multiplier لـSL


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

# MAX_SPREAD_OVERRIDE = None  ← لا حد للسبريد في النظام الجديد
MAX_SPREAD_OVERRIDE = None


# FRIDAY realtime local voice assistant
PROJECT_NAME = os.environ.get("FRIDAY_PROJECT_NAME", "FRIDAY")
OLLAMA_MODEL = os.environ.get("FRIDAY_OLLAMA_MODEL", "qwen2.5:3b-instruct")
WHISPER_MODEL = os.environ.get("FRIDAY_WHISPER_MODEL", "base")
TTS_ENGINE = os.environ.get("FRIDAY_TTS_ENGINE", "edge-tts")
DEFAULT_SYMBOL = os.environ.get("FRIDAY_DEFAULT_SYMBOL", MT5_SYMBOL)
DEFAULT_TIMEFRAME = os.environ.get("FRIDAY_DEFAULT_TIMEFRAME", TIMEFRAME)
AUDIO_DEVICE = os.environ.get("FRIDAY_AUDIO_DEVICE")
VAD_SETTINGS = {
    "backend": os.environ.get("FRIDAY_VAD_BACKEND", "webrtcvad"),
    "sensitivity": _env_float("FRIDAY_VAD_SENSITIVITY", 0.62),
    "silence_timeout_ms": _env_int("FRIDAY_SILENCE_TIMEOUT_MS", 650),
    "audio_chunk_ms": _env_int("FRIDAY_AUDIO_CHUNK_MS", 30),
    "sample_rate": _env_int("FRIDAY_SAMPLE_RATE", 16000),
    "max_record_seconds": _env_float("FRIDAY_MAX_RECORD_SECONDS", 12.0),
}
STREAMING_ENABLED = _env_flag("FRIDAY_STREAMING_ENABLED", True)
VOICE_MODE = _env_flag("FRIDAY_VOICE_MODE", True)
MEMORY_ENABLED = _env_flag("FRIDAY_MEMORY_ENABLED", True)


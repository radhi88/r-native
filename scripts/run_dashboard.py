"""
FRIDAY — مركز العمليات المرئي

يشغّل حلقة التداول في thread خلفي ويعرض لوحة الوكلاء في المقدمة.

التشغيل:
    python scripts/run_dashboard.py
    python scripts/run_dashboard.py --symbol EURUSDm --poll-seconds 15
    python scripts/run_dashboard.py --bars 800 --max-positions 2 --debug
"""

import argparse
import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import joblib

from _bootstrap import bootstrap
bootstrap()

from mt5_ai.agents.dashboard import FridayDashboard
from mt5_ai.agents.orchestrator import FridayOrchestrator
from mt5_ai.config import (
    DEFAULT_LOT,
    FEATURE_COLUMNS,
    LOG_DIR,
    MODEL_CANDIDATES,
    MT5_SYMBOL,
    SCALER_PATH,
    SEQ_LEN,
    MAX_DEMO_OPEN_ORDERS,
)
from mt5_ai.execution import DemoMT5Executor, PaperExecutor
from mt5_ai.mt5_gateway import MT5Gateway

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "friday_dashboard.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("friday.dashboard_runner")


# ── تحميل النموذج والـScaler ──────────────────────────────────────────────────

def _load_model():
    try:
        import tensorflow as tf
    except ImportError:
        log.error("TensorFlow غير مثبّت — pip install tensorflow")
        sys.exit(1)
    for candidate in MODEL_CANDIDATES:
        if Path(candidate).exists():
            log.info("تحميل النموذج: %s", candidate)
            return tf.keras.models.load_model(str(candidate), compile=False)
    log.error("لم يُعثر على نموذج في: %s", [str(c) for c in MODEL_CANDIDATES])
    sys.exit(1)


def _load_scaler():
    if not Path(SCALER_PATH).exists():
        log.error("Scaler غير موجود: %s", SCALER_PATH)
        sys.exit(1)
    return joblib.load(SCALER_PATH)


# ── حلقة التداول (تعمل في thread خلفي) ──────────────────────────────────────

def _trading_loop(
    orchestrator: FridayOrchestrator,
    gateway: MT5Gateway,
    symbol: str,
    poll_seconds: int,
    bars: int,
    debug: bool,
    stop_event: threading.Event,
):
    log.info("حلقة التداول بدأت — %s  poll=%ds  bars=%d", symbol, poll_seconds, bars)
    while not stop_event.is_set():
        try:
            raw_df = gateway.fetch_rates(symbol, "M1", bars)
            orchestrator.on_bar(raw_df)
        except Exception as exc:
            log.error("خطأ في الـbar: %s", exc, exc_info=debug)
        stop_event.wait(poll_seconds)
    log.info("حلقة التداول انتهت.")


# ── الدالة الرئيسية ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="FRIDAY Dashboard — مركز العمليات المرئي"
    )
    parser.add_argument("--symbol",        default=MT5_SYMBOL)
    parser.add_argument("--poll-seconds",  type=int, default=30)
    parser.add_argument("--bars",          type=int, default=600)
    parser.add_argument("--max-positions", type=int, default=MAX_DEMO_OPEN_ORDERS)
    parser.add_argument("--refresh",       type=float, default=2.0,
                        help="ثواني بين تحديثات الشاشة")
    parser.add_argument("--debug",         action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    model  = _load_model()
    scaler = _load_scaler()

    gateway = MT5Gateway()
    gateway.initialize()
    account = gateway.account_snapshot()
    is_demo = gateway.is_demo_account(account)

    executor = DemoMT5Executor(gateway) if is_demo else PaperExecutor()

    orchestrator = FridayOrchestrator(
        executor=executor,
        model=model,
        scaler=scaler,
        symbol=args.symbol,
        feature_columns=FEATURE_COLUMNS,
        seq_len=SEQ_LEN,
        max_positions=args.max_positions,
    )

    # ── شغّل حلقة التداول في الخلفية ────────────────────────────────────────
    stop_event = threading.Event()
    trade_thread = threading.Thread(
        target=_trading_loop,
        args=(orchestrator, gateway, args.symbol,
              args.poll_seconds, args.bars, args.debug, stop_event),
        daemon=True,
        name="friday-trade",
    )
    trade_thread.start()

    # ── شغّل الداشبورد في المقدمة (blocking) ─────────────────────────────────
    dash = FridayDashboard(
        orchestrator=orchestrator,
        gateway=gateway,
        symbol=args.symbol,
    )
    dash.REFRESH = args.refresh

    try:
        dash.run(block=True)
    finally:
        stop_event.set()
        trade_thread.join(timeout=5)
        gateway.shutdown()
        log.info("النظام أُغلق بنظام.")


if __name__ == "__main__":
    main()

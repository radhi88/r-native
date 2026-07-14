"""
FRIDAY — نقطة الدخول الرئيسية للنظام متعدد الوكلاء

الوكلاء:
  MarketAnalystAgent   ← يحلل هيكل السوق (BOS / CHOCH / OB / FVG)
  LiquidityHunterAgent ← يرصد اختراقات السيولة (EQH / EQL sweeps)
  EntryAgent           ← يقرر الدخول بناءً على SMC + نموذج AI
  RiskAgent            ← يضع SL/TP عند مستويات الهيكل
  MonitorAgent         ← يراقب الصفقات المفتوحة (BE / Trailing SL)
  LearningEngine       ← يسجل الأداء ويُكيّف العتبات

لا قيود على السبريد. لا قيود زمنية. لا قيود أخبار.

التشغيل:
    python run_friday.py
    python run_friday.py --poll-seconds 10
    python run_friday.py --bars 800 --max-positions 2
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np

from _bootstrap import bootstrap
bootstrap()

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
from mt5_ai.pivot_engine import PivotEngine


# ── تهيئة السجل ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "friday_run.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("friday.main")


# ── معالج الأحداث ────────────────────────────────────────────────────────────

def event_handler(event: str, data: dict):
    ts = datetime.now().strftime("%H:%M:%S")
    if event == "trade_open":
        side = data.get("action", "?")
        sym  = data.get("symbol", MT5_SYMBOL)
        p    = data.get("price", 0)
        sl   = data.get("sl", 0)
        tp   = data.get("tp", 0)
        lot  = data.get("lot", 0)
        rr   = data.get("rr", "?")
        why  = data.get("reason", "")
        tid  = data.get("trade_id", "")
        sent = data.get("sent", False)
        icon = "🟢" if side == "BUY" else "🔴"
        print(
            f"\n[{ts}] {icon} {side} {sym}  "
            f"@ {p:.2f}  SL={sl:.2f}  TP={tp:.2f}  "
            f"lot={lot}  R:R={rr}  [{why}]  "
            f"id={tid}  sent={sent}"
        )
    elif event == "trade_closed":
        won   = data.get("won", False)
        pnl   = data.get("pnl_points", 0)
        side  = data.get("side", "?")
        entry = data.get("entry", 0)
        exit_ = data.get("exit", 0)
        icon  = "💰" if won else "💸"
        label = "WIN" if won else "LOSS"
        print(
            f"\n[{ts}] {icon} CLOSED {side}  "
            f"entry={entry:.2f} → exit={exit_:.2f}  "
            f"pnl={pnl:+.2f} pts  {label}"
        )
    elif event == "sl_update":
        reason = data.get("reason", "")
        sl_new = data.get("sl", 0)
        tid    = data.get("trade_id", "")
        print(f"[{ts}] ⚙️  SL→{sl_new:.5f}  [{reason}]  {tid}", end="\r")


# ── تحميل النموذج ────────────────────────────────────────────────────────────

def load_model():
    try:
        import tensorflow as tf
    except ImportError:
        log.error("TensorFlow غير مثبّت — شغّل: pip install tensorflow")
        sys.exit(1)

    for candidate in MODEL_CANDIDATES:
        if Path(candidate).exists():
            log.info("تحميل النموذج من: %s", candidate)
            return tf.keras.models.load_model(str(candidate), compile=False)

    log.error("لم يُعثر على ملف نموذج في: %s", [str(c) for c in MODEL_CANDIDATES])
    sys.exit(1)


def load_scaler():
    if not Path(SCALER_PATH).exists():
        log.error("ملف الـScaler غير موجود: %s", SCALER_PATH)
        sys.exit(1)
    return joblib.load(SCALER_PATH)


# ── الدالة الرئيسية ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FRIDAY SMC Multi-Agent Scalping")
    parser.add_argument("--symbol",        default=MT5_SYMBOL, help="رمز التداول")
    parser.add_argument("--poll-seconds",  type=int,   default=30,  help="الفترة بين الـbars")
    parser.add_argument("--bars",          type=int,   default=600, help="عدد الشمعات المجلوبة")
    parser.add_argument("--max-positions", type=int,   default=MAX_DEMO_OPEN_ORDERS)
    parser.add_argument("--debug",         action="store_true", help="تسجيل تفصيلي")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    print("\n" + "═" * 65)
    print("  FRIDAY — نظام سكالبينج SMC متعدد الوكلاء")
    print("  لا حدود للسبريد · لا قيود زمنية · لا فلاتر أخبار")
    print("═" * 65)

    model  = load_model()
    scaler = load_scaler()

    gateway = MT5Gateway()
    gateway.initialize()
    account = gateway.account_snapshot()
    is_demo = gateway.is_demo_account(account)
    symbol_info = gateway.symbol_snapshot(args.symbol)
    point_size = float(symbol_info.get("point") or 0.01)
    pivot_engine = PivotEngine(gateway, args.symbol, point_size=point_size)

    print(f"\n  حساب : {account.get('login')}")
    print(f"  سيرفر: {account.get('server')}")
    print(f"  رصيد : {account.get('balance')} {account.get('currency', 'USD')}")
    print(f"  نوع  : {'DEMO ✅' if is_demo else 'LIVE — تنفيذ Paper فقط'}")
    print(f"  رمز  : {args.symbol}")
    print(f"  تردد : {args.poll_seconds}s  |  شمعات: {args.bars}")
    print("─" * 65 + "\n")

    executor = DemoMT5Executor(gateway) if is_demo else PaperExecutor()

    orchestrator = FridayOrchestrator(
        executor=executor,
        model=model,
        scaler=scaler,
        symbol=args.symbol,
        feature_columns=FEATURE_COLUMNS,
        seq_len=SEQ_LEN,
        max_positions=args.max_positions,
        event_cb=event_handler,
        pivot_engine=pivot_engine,
    )

    stats    = {"bars": 0, "trades": 0, "wins": 0, "losses": 0, "errors": 0}
    log_file = LOG_DIR / "friday_trades.jsonl"

    log.info("النظام جاهز — يبدأ التشغيل...")

    try:
        while True:
            ts = datetime.now().strftime("%H:%M:%S")
            try:
                raw_df = gateway.fetch_rates(args.symbol, "M1", args.bars)
                result = orchestrator.on_bar(raw_df)
                stats["bars"] += 1

                action = result.get("action", "HOLD")
                if action in {"BUY", "SELL"}:
                    stats["trades"] += 1
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")

                prob     = result.get("prob",     0.0)
                smc_b    = result.get("smc_buy",  0)
                smc_s    = result.get("smc_sell", 0)
                pos_cnt  = result.get("open_pos", 0)
                price    = result.get("price",    0.0)
                ssl_a    = "SSL✓" if result.get("ssl_active") else "   "
                bsl_a    = "BSL✓" if result.get("bsl_active") else "   "
                bos_u    = "BOS↑" if result.get("bos_up")    else "    "
                bos_d    = "BOS↓" if result.get("bos_down")  else "    "

                line = (
                    f"[{ts}] {action:5s}  {price:>9.2f}  "
                    f"prob={prob:.3f}  "
                    f"SMC={smc_b}/{smc_s}  "
                    f"{ssl_a} {bsl_a}  "
                    f"{bos_u}{bos_d}  "
                    f"pos={pos_cnt}  bars={stats['bars']:>4d}  "
                    f"trades={stats['trades']}"
                )
                print(line, end="\r", flush=True)

            except Exception as exc:
                stats["errors"] += 1
                log.error("خطأ في الـbar: %s", exc, exc_info=args.debug)

            time.sleep(args.poll_seconds)

    except KeyboardInterrupt:
        print(f"\n\n{'─'*65}")
        print(f"  تم الإيقاف بواسطة المستخدم")
        print(f"  إجمالي bars  : {stats['bars']}")
        print(f"  إجمالي صفقات : {stats['trades']}")
        print(f"  أخطاء        : {stats['errors']}")

        final = orchestrator.status()
        print(f"  صفقات مفتوحة : {len(final['open_positions'])}")
        lrn   = final.get("learning", {})
        if lrn.get("trades"):
            wr = lrn.get("win_rate", 0)
            pf = lrn.get("profit_factor", 0)
            print(f"  معدل الربح   : {wr:.1%}  PF={pf:.2f}  ({lrn['trades']} صفقة)")
        print("─" * 65)

    finally:
        gateway.shutdown()


if __name__ == "__main__":
    main()

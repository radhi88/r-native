"""
قادر GADER — نقطة التشغيل الوحيدة
══════════════════════════════════════════════════════════

يدمج في ملف واحد:
  • GaderDashboard  — شاشة pixel art مع شخصيات متحركة
  • Multi-Symbol    — يكتشف جميع رموز MT5 تلقائياً
  • Cross-Market    — انحياز النفط بناءً على حركة الذهب
  • PositionSyncer  — يتعلم من تدخلاتك اليدوية
  • LocalMind       — تحكم صوتي/نصي (حالة/صفقات/أوقف)

التشغيل:
    python scripts/run_gader.py
    python scripts/run_gader.py --symbol XAUUSDm   # رمز واحد فقط
    python scripts/run_gader.py --max-symbols 5    # أول 5 رموز
    python scripts/run_gader.py --manage-only      # مراقبة بدون صفقات جديدة
    python scripts/run_gader.py --no-dash          # نص فقط بدون واجهة
"""

import argparse
import logging
import os
import sys
import threading
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

# ── مسارات المشروع ────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

import joblib
import numpy as np
from sklearn.preprocessing import StandardScaler

import tensorflow as tf
tf.get_logger().setLevel("ERROR")

from _bootstrap import bootstrap
bootstrap()

from mt5_ai.agents.dashboard_pixel import GaderDashboard, event_bus
from mt5_ai.agents.orchestrator    import FridayOrchestrator
from mt5_ai.config import (
    DATA_DIR, FEATURE_COLUMNS, LOG_DIR, MODEL_PATH, MODELS_DIR,
    MT5_SYMBOL, SCALER_PATH, SEQ_LEN,
)
from mt5_ai.cross_market      import gold_to_energy_bias
from mt5_ai.execution         import DemoMT5Executor
from mt5_ai.human_learner     import HumanBehaviorLearner
from mt5_ai.market_structure  import add_market_structure
from mt5_ai.mt5_gateway       import MT5Gateway
from mt5_ai.orchestrator_adapter import OrchestratorAdapter
from mt5_ai.local_mind        import LocalMind
from mt5_ai.position_sync     import PositionSyncer
from mt5_ai.ai_watchdog       import AIWatchdog
from mt5_ai.ollama_ceo        import OllamaCEO
from mt5_ai.smart_algorithm_pro import SmartAlgorithmPro, SECTION_10_CHECKLIST

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "gader.log", encoding="utf-8")],
)
log = logging.getLogger("gader")


# ── Paper Executor (لا يرسل أوامر حقيقية) ────────────────────────────────────

class _PaperExec:
    mode = "paper"

    @staticmethod
    def _stamp():
        return datetime.now(timezone.utc).isoformat()

    def execute(self, symbol, side, price, lot=0.01, sl=None, tp=None):
        return {"sent": True, "mode": "paper", "action": "OPEN",
                "symbol": symbol, "side": side, "lot": float(lot),
                "requested_price": float(price), "sl": sl, "tp": tp}

    def execute_pending(self, symbol, side, limit_price, lot=0.01, sl=None, tp=None):
        return {"sent": True, "mode": "paper_pending", "action": "PENDING",
                "symbol": symbol, "side": side, "lot": float(lot),
                "limit_price": float(limit_price), "sl": sl, "tp": tp}


# ── تحميل النموذج ─────────────────────────────────────────────────────────────

def _load_model():
    path = MODEL_PATH if MODEL_PATH.exists() else MODELS_DIR / "best_model.keras"
    if not path.exists():
        log.error("لم يُعثر على ملف النموذج: %s", path)
        sys.exit(1)
    log.info("تحميل النموذج: %s", path.name)
    return tf.keras.models.load_model(str(path), compile=False)


def _fit_scaler(enriched_df, fallback_scaler):
    available = [c for c in FEATURE_COLUMNS if c in enriched_df.columns]
    data      = enriched_df[available].dropna().to_numpy(dtype=np.float32)
    sc        = StandardScaler()
    if len(data) >= 10:
        sc.fit(data)
    else:
        sc = fallback_scaler
    return sc


# ── Event callback يُرسل الأحداث إلى event_bus ───────────────────────────────

def _make_event_cb(symbol: str, no_dash: bool):
    def on_event(event: str, data: dict):
        ts = datetime.now().strftime("%H:%M:%S")

        if not no_dash:
            # الأحداث تُرسل تلقائياً من GaderDashboard._translate_event
            # هذا الـ callback يطبع على الـlog فقط
            pass

        if event == "trade_open":
            side  = data.get("action", "?")
            otype = data.get("order_type", "MARKET")
            sl    = data.get("sl", 0)
            tp    = data.get("tp", 0)
            rr    = data.get("rr", "?")
            tid   = data.get("trade_id", "")
            icon  = "🟡" if otype in ("BUY_LIMIT", "SELL_LIMIT") else ("🟢" if "BUY" in side else "🔴")
            log.info("[%s] %s %s %s  SL=%.5f  TP=%.5f  R:R=%s  [%s]",
                     ts, icon, symbol, side, sl, tp, rr, tid)

        elif event == "trade_closed":
            won  = data.get("won", False)
            pnl  = data.get("pnl_points", 0)
            side = data.get("side", "?")
            icon = "💰" if won else "💸"
            log.info("[%s] %s CLOSED %s %s  pnl=%+.5f  %s",
                     ts, icon, symbol, side, pnl, "WIN" if won else "LOSS")

        elif event == "sl_update":
            if data.get("modify_sent") is False:
                log.warning("[%s] ⚠️ %s SL rejected  kept=%.5f",
                            ts, symbol, data.get("sl", 0))

    return on_event


# ── حلقة تداول لرمز واحد (تعمل في thread) ────────────────────────────────────

_GLOBAL_MAX_OPEN = 4   # حد أقصى لمجموع المراكز المفتوحة عبر كل الرموز
_GLOBAL_TRADE_LOCK = threading.Lock()


def _symbol_loop(
    symbol: str,
    orch: FridayOrchestrator,
    gw: MT5Gateway,
    pos_syncer: "PositionSyncer | None",
    execution_mode: str,
    bars: int,
    poll: int,
    gold_df_ref: list,   # [0] = آخر gold_df
    smart_analyzer: "SmartAlgorithmPro | None",
    stop_event: threading.Event,
    trade_log: list,
    all_orchs: "dict",   # لحساب إجمالي المراكز
):
    while not stop_event.is_set():
        try:
            # on_bar may open a position. Keep the global cap race-free across
            # symbol threads so a burst cannot exceed _GLOBAL_MAX_OPEN.
            result = None
            with _GLOBAL_TRADE_LOCK:
                total_open = sum(o.monitor.count() for o in all_orchs.values())
                if total_open >= _GLOBAL_MAX_OPEN and orch.monitor.count() == 0:
                    result = {"action": "HOLD", "price": 0, "atr": 0}
                else:
                    df = gw.fetch_rates(symbol, "M1", bars)
                    smart_ctx = {}
                    if smart_analyzer is not None:
                        frames = {"M1": df}
                        for tf in ("M5", "M15", "M30", "H1", "H4"):
                            try:
                                frames[tf] = gw.fetch_rates(symbol, tf, min(max(bars, 120), 320))
                            except Exception:
                                pass
                        try:
                            smart_ctx = smart_analyzer.analyze(
                                symbol=symbol,
                                frames=frames,
                                tick=gw.symbol_snapshot(symbol),
                                learning_summary=orch.learning.summary("smc", symbol, lookback=30),
                            )
                        except Exception as exc:
                            smart_ctx = {
                                "active": False,
                                "signal": "HOLD",
                                "reason": f"smart_pro_error:{exc}",
                            }
                    external_context = {
                        "cross_market": gold_to_energy_bias(symbol, gold_df_ref[0]),
                        "smart_pro": smart_ctx,
                    }
                    result = orch.on_bar(df, external_context=external_context)

            # مزامنة مع MT5 للكشف عن التدخلات اليدوية
            if execution_mode == "demo" and orch.monitor.count() > 0:
                price  = result.get("price", 0)
                atr    = result.get("atr", 0) or 1.0
                events = pos_syncer.sync(orch, current_price=price, atr=atr) if pos_syncer else []
                for ev in events:
                    ts_ev = datetime.now().strftime("%H:%M:%S")
                    if ev["type"] == "manual_close":
                        pnl  = ev.get("pnl_points", 0)
                        conf = orch.confidence.status()
                        log.info("[%s] 🧑 MANUAL CLOSE %s pnl=%+.5f → conf=%.2f",
                                 ts_ev, symbol, pnl, conf["confidence"])
                    elif ev["type"] == "manual_sl_move":
                        log.info("[%s] 🧑 MANUAL SL %s  %.5f→%.5f",
                                 ts_ev, symbol, ev["old_sl"], ev["new_sl"])

            action = result.get("action", "HOLD")
            if action != "HOLD":
                trade_log.append({"symbol": symbol, "time": datetime.now().isoformat(),
                                  **result})

        except Exception as exc:
            log.error("[%s] خطأ: %s", symbol, exc, exc_info=False)

        stop_event.wait(poll)


# ── حلقة تيك سريعة (1 ثانية) لتحريك SL بشكل فوري ───────────────────────────

def _fast_tick_loop(
    orchestrators: "dict[str, FridayOrchestrator]",
    gw: "MT5Gateway",
    stop_event: threading.Event,
    interval: float = 1.0,
):
    """
    تُشغَّل كل ثانية وتحدّث SL/BE لجميع الصفقات المفتوحة.
    لا تفتح صفقات جديدة — تراقب وتتحرك فقط.
    """
    while not stop_event.is_set():
        for sym, orch in list(orchestrators.items()):
            if orch.monitor.count() == 0:
                continue
            try:
                tick  = gw.symbol_snapshot(sym)
                price = float(tick.get("bid", 0) or tick.get("last", 0))
                if price <= 0:
                    continue
                atr  = orch._last_status.get("atr", 0) or 1.0
                closed = orch.monitor.update(price, atr)
                for trade in closed:
                    try:
                        orch._record_closed(trade, orch._last_status)
                    except Exception:
                        pass
            except Exception:
                pass
        stop_event.wait(interval)


# ── الدالة الرئيسية ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="قادر GADER — مركز العمليات الموحّد")
    parser.add_argument("--symbol",       default="",          help="رمز واحد (اتركه فارغاً لكل الرموز)")
    parser.add_argument("--max-symbols",  type=int, default=12)
    parser.add_argument("--global-max-open", type=int, default=4, help="حد أقصى للمراكز المفتوحة عبر كل الرموز")
    parser.add_argument("--bars",         type=int, default=600)
    parser.add_argument("--poll",         type=int, default=15,  help="ثواني بين كل جولة")
    parser.add_argument("--refresh",      type=float, default=2.0, help="ثواني بين تحديثات الشاشة")
    parser.add_argument("--mode",         choices=["auto","paper","demo"], default="auto")
    parser.add_argument("--manage-only",  action="store_true",  help="مراقبة بدون صفقات جديدة")
    parser.add_argument("--no-dash",      action="store_true",  help="تشغيل بدون واجهة pixel art")
    parser.add_argument("--runtime-seconds", type=int, default=0, help="إيقاف تلقائي بعد N ثانية للاختبار")
    parser.add_argument("--ollama-model", default=os.environ.get("OLLAMA_MODEL", "qwen2.5:3b-instruct"))
    parser.add_argument("--ollama-host",  default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
    parser.add_argument("--ceo-interval", type=int, default=60, help="ثواني بين دورات OllamaCEO")
    parser.add_argument("--watchdog-interval", type=int, default=120, help="ثواني بين فحوصات AIWatchdog")
    parser.add_argument("--no-ollama",    action="store_true", help="تعطيل مستشار Ollama")
    parser.add_argument("--no-watchdog",  action="store_true", help="تعطيل AIWatchdog")
    parser.add_argument("--no-smart-pro", action="store_true", help="تعطيل Smart Algorithm Pro multi-timeframe filter")
    parser.add_argument("--smart-min-power", type=float, default=66.0, help="أدنى Power%% للسماح بالدخول")
    parser.add_argument("--smart-max-spread", type=float, default=45.0, help="أقصى spread points في فلتر Smart Pro")
    parser.add_argument("--visible-only", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--debug",        action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    global _GLOBAL_MAX_OPEN
    _GLOBAL_MAX_OPEN = max(1, args.global_max_open)

    # ── تحميل النموذج والـ Scaler ───────────────────────────────────────────
    model         = _load_model()
    fallback_sc   = joblib.load(SCALER_PATH)

    # ── MT5 ────────────────────────────────────────────────────────────────
    gw  = MT5Gateway()
    gw.initialize()
    acc     = gw.account_snapshot()
    is_demo = gw.is_demo_account(acc)
    print(f"\n[GADER] {acc.get('login')} @ {acc.get('server')}"
          f"  balance=${acc.get('balance',0):.2f}"
          f"  {'DEMO' if is_demo else 'LIVE'}")

    if args.mode == "demo" and not is_demo:
        print("[ERR] طلبت --mode demo لكن الحساب ليس ديمو. إيقاف.")
        gw.shutdown()
        sys.exit(1)

    if args.mode == "paper" or (args.mode == "auto" and not is_demo):
        execution_mode = "paper"
        executor       = _PaperExec()
        print("[SAFE] Paper mode — لا أوامر حقيقية")
    else:
        execution_mode = "demo"
        executor       = DemoMT5Executor(gw)
        print("[SAFE] Demo MT5 mode")

    # ── اكتشاف الرموز ──────────────────────────────────────────────────────
    BARS        = max(SEQ_LEN + 50, args.bars)
    MAX_SYMBOLS = max(1, args.max_symbols)
    POLL        = max(1, args.poll)

    # رموز BTC cross والرموز الغريبة محظورة — النموذج لم يُدرَّب عليها
    _HARD_BLACKLIST = {
        "BTCAUDm", "BTCCNHm", "BTCTHBm", "BTCXAGm", "BTCXAUm",
        "BTCZARm", "BTCJPYm",  # BTC crosses (نقاط ضخمة، خسائر كبيرة)
        "CHFZARm", "AUDZARm", "DKKZARm",  # ZAR crosses (WR منخفض تاريخياً)
        "EURHKDm", "DKKJPYm", "DKKPLNm", "DKKSGDm",  # DKK exotics
    }

    if args.symbol:
        target_symbols = [args.symbol]
    else:
        print(f"\n[SCAN] اكتشاف رموز MT5...")
        all_sym_info = gw.symbols(visible_only=args.visible_only, tradable_only=True, limit=300)
        # أولوية للرموز المهمة — بدون الرموز المحظورة
        _PRIO = [MT5_SYMBOL, "XAUUSDm", "USOILm", "UKOILm", "XNGUSDm", "EURUSDm", "GBPUSDm",
                 "BTCUSDm", "ETHUSDm"]
        prio   = [s["symbol"] for s in all_sym_info
                  if s["symbol"] in _PRIO and s["symbol"] not in _HARD_BLACKLIST]
        rest   = [s["symbol"] for s in all_sym_info
                  if s["symbol"] not in _PRIO and s["symbol"] not in _HARD_BLACKLIST]
        target_symbols = (prio + rest)[:MAX_SYMBOLS]
        print(f"[SCAN] {len(target_symbols)} رمز مرشح (تجاهل {len(_HARD_BLACKLIST)} محظور)")

    # ── بناء الـ Orchestrators ──────────────────────────────────────────────
    orchestrators: dict[str, FridayOrchestrator] = {}
    print("\n[BUILD] بناء الـ Orchestrators...")

    for sym in target_symbols:
        try:
            df_init = gw.fetch_rates(sym, "M1", BARS)
            if len(df_init) < SEQ_LEN + 50:
                continue
            enriched_init = add_market_structure(df_init)
            sc = _fit_scaler(enriched_init, fallback_sc)

            orch = FridayOrchestrator(
                executor        = executor,
                model           = model,
                scaler          = sc,
                symbol          = sym,
                feature_columns = FEATURE_COLUMNS,
                seq_len         = SEQ_LEN,
                max_positions   = 1,
                event_cb        = _make_event_cb(sym, no_dash=args.no_dash),
                entries_enabled = not args.manage_only,
            )
            try:
                orch.wick.scan_history(enriched_init, lookback=500)
            except Exception:
                pass
            orchestrators[sym] = orch
            print(f"  ✓ {sym}", end="  ", flush=True)
        except Exception:
            pass

    print(f"\n\n[BUILD] {len(orchestrators)} رمز جاهز")
    if not orchestrators:
        print("[ERR] لا يوجد أي رمز. تحقق من اتصال MT5.")
        gw.shutdown()
        sys.exit(1)

    # ── الرمز الأساسي ──────────────────────────────────────────────────────
    primary_sym  = MT5_SYMBOL if MT5_SYMBOL in orchestrators else next(iter(orchestrators))
    primary_orch = orchestrators[primary_sym]

    # ── HumanBehaviorLearner مشترك ─────────────────────────────────────────
    shared_human = HumanBehaviorLearner()
    pos_syncer   = PositionSyncer(gw=gw, human_learner=shared_human)
    for orch in orchestrators.values():
        orch.human              = shared_human
        orch.monitor.human_learner = shared_human

    if execution_mode == "demo":
        imported = sum(pos_syncer.import_open_positions(o) for o in orchestrators.values())
        if imported:
            print(f"[SYNC] استُورد {imported} صفقة مفتوحة من MT5")

    smart_analyzer = None
    if args.no_smart_pro:
        print("[SMART] Smart Algorithm Pro معطّل بطلب التشغيل")
    else:
        smart_analyzer = SmartAlgorithmPro(
            min_power=args.smart_min_power,
            max_spread_points=args.smart_max_spread,
        )
        print(
            f"[SMART] Smart Algorithm Pro ON — 6TF M1→H4  checklist={len(SECTION_10_CHECKLIST)}"
            f"  min_power={args.smart_min_power:.1f}"
        )

    # ── LocalMind ──────────────────────────────────────────────────────────
    orch_adapter = OrchestratorAdapter(primary_orch)
    mind         = LocalMind(orchestrator=orch_adapter)
    print(f"[MIND] LocalMind جاهز ({primary_sym}) — اكتب: حالة / صفقات / تعلم / أوقف\n")

    def _mind_loop():
        for line in sys.stdin:
            text = line.strip()
            if not text:
                continue
            try:
                resp = mind.chat(text)
                print(f"\n[قادر] {resp.get('answer','')}\n", flush=True)
            except Exception as exc:
                print(f"\n[MIND ERR] {exc}\n", flush=True)
            if orch_adapter.should_stop():
                break

    if args.no_dash:
        threading.Thread(target=_mind_loop, daemon=True, name="gader-mind").start()

    # ── متغيرات مشتركة بين الـ threads ────────────────────────────────────
    stop_event   = threading.Event()
    trade_log: list[dict] = []
    gold_df_ref: list     = [None]   # [0] = آخر gold_df

    # ── thread لتحديث gold_df كل جولة ─────────────────────────────────────
    def _gold_updater():
        while not stop_event.is_set():
            try:
                gold_df_ref[0] = gw.fetch_rates(MT5_SYMBOL, "M1", BARS)
            except Exception:
                pass
            stop_event.wait(POLL)

    threading.Thread(target=_gold_updater, daemon=True, name="gold-updater").start()

    # ── threads لكل رمز ────────────────────────────────────────────────────
    sym_threads: list[threading.Thread] = []
    for sym, orch in orchestrators.items():
        t = threading.Thread(
            target   = _symbol_loop,
            args     = (sym, orch, gw, pos_syncer, execution_mode,
                        BARS, POLL, gold_df_ref, smart_analyzer,
                        stop_event, trade_log, orchestrators),
            daemon   = True,
            name     = f"gader-{sym}",
        )
        t.start()
        sym_threads.append(t)

    # ── Fast Tick Loop (1 ثانية) ───────────────────────────────────────────────
    tick_thread = threading.Thread(
        target   = _fast_tick_loop,
        args     = (orchestrators, gw, stop_event, 1.0),
        daemon   = True,
        name     = "gader-tick",
    )
    tick_thread.start()
    print("[TICK] Fast tick loop بدأ (1s interval)")

    # ── AIWatchdog ─────────────────────────────────────────────────────────
    watchdog = None
    api_key  = os.environ.get("ANTHROPIC_API_KEY", "")
    if args.no_watchdog:
        print("[WATCH] AIWatchdog معطّل بطلب التشغيل")
    else:
        watchdog = AIWatchdog(
            orchestrators,
            check_interval=max(15, args.watchdog_interval),
            api_key=api_key,
        )
        watchdog.start()
        print("[WATCH] AIWatchdog بدأ (Claude API" + (" متاح)" if api_key else " غير مضبوط — قواعد داخلية فقط)"))

    # ── OllamaCEO ─────────────────────────────────────────────────────────
    ceo = None
    if args.no_ollama:
        print("[CEO] OllamaCEO معطّل بطلب التشغيل")
    else:
        ceo = OllamaCEO(
            orchestrators = orchestrators,
            interval      = max(15, args.ceo_interval),
            model         = args.ollama_model,
            host          = args.ollama_host,
            event_bus     = event_bus,
        )
        ceo.start()
        print(f"[CEO] OllamaCEO بدأ (model={args.ollama_model}  host={ceo.host})")

    print(f"[START] Smart Algorithm Pro / GADER — {len(orchestrators)} رمز  poll={POLL}s  bars={BARS}")
    if args.manage_only:
        print("        ManageOnly=ON — مراقبة بدون صفقات جديدة")
    if args.runtime_seconds > 0:
        print(f"        Runtime={args.runtime_seconds}s — إيقاف تلقائي للاختبار")

    # ── حارس رصيد الجلسة ───────────────────────────────────────────────────
    session_balance   = acc.get("balance", 0) or 0.0
    _DRAWDOWN_LIMIT   = 0.08   # 8% نزول equity/balance من بداية الجلسة يوقف الدخولات
    _balance_halted   = False
    _started_at       = time.monotonic()

    def _runtime_expired() -> bool:
        return args.runtime_seconds > 0 and (time.monotonic() - _started_at) >= args.runtime_seconds

    def _check_balance_guard():
        nonlocal _balance_halted
        if _balance_halted:
            return
        try:
            snap = gw.account_snapshot()
            cur_balance = snap.get("balance", session_balance) or session_balance
            cur_equity  = snap.get("equity", cur_balance) or cur_balance
            balance_dd = (session_balance - cur_balance) / session_balance if session_balance > 0 else 0
            equity_dd  = (session_balance - cur_equity) / session_balance if session_balance > 0 else 0
            drawdown = max(balance_dd, equity_dd)
            if drawdown >= _DRAWDOWN_LIMIT:
                for o in orchestrators.values():
                    o.entries_enabled = False
                _balance_halted = True
                log.warning(
                    "[GUARD] equity/balance نزل %.1f%% (start=%.2f balance=%.2f equity=%.2f) → إيقاف جميع الدخولات",
                    drawdown * 100, session_balance, cur_balance, cur_equity,
                )
                print(f"\n[GUARD] ⛔ نزول رصيد {drawdown*100:.1f}% — الدخولات موقوفة لحماية الحساب")
        except Exception:
            pass

    # ── تشغيل الداشبورد أو الـ text loop ──────────────────────────────────
    if args.no_dash:
        # وضع النص: طباعة حالة كل جولة
        try:
            while True:
                if orch_adapter.should_stop() or _runtime_expired():
                    break
                _check_balance_guard()
                wait_for = POLL
                if args.runtime_seconds > 0:
                    remaining = args.runtime_seconds - (time.monotonic() - _started_at)
                    if remaining <= 0:
                        break
                    wait_for = max(0.5, min(POLL, remaining))
                time.sleep(wait_for)
                if _runtime_expired():
                    break
                ts     = datetime.now().strftime("%H:%M:%S")
                n_open = sum(o.monitor.count() for o in orchestrators.values())
                guard_icon = "⛔" if _balance_halted else ""
                print(
                    f"\r[{ts}] رموز={len(orchestrators)}"
                    f"  مفتوحة={n_open}"
                    f"  صفقات={len(trade_log)}{guard_icon}",
                    end="", flush=True,
                )
        except KeyboardInterrupt:
            pass

    else:
        # وضع الداشبورد
        dash = GaderDashboard(
            orchestrator = primary_orch,
            gateway      = gw,
            symbol       = primary_sym,
            all_orchs    = orchestrators,
            ceo          = ceo,
        )
        dash.REFRESH = args.refresh

        # أضف LocalMind thread مربوط بالـ event bus
        threading.Thread(target=_mind_loop, daemon=True, name="gader-mind").start()

        try:
            dash.run(block=True)
        except Exception as exc:
            log.error("Dashboard error: %s", exc, exc_info=True)

    # ── إيقاف ──────────────────────────────────────────────────────────────
    print(f"\n\n{'='*60}")
    stop_event.set()
    if ceo:
        ceo.stop()
    if watchdog:
        watchdog.stop()
    for t in sym_threads:
        t.join(timeout=3)

    closed = [e for e in trade_log if e.get("action") not in ("HOLD", None)]
    print(f"[END] رموز={len(orchestrators)}  إجمالي إشارات={len(closed)}")

    active = [(sym, orch) for sym, orch in orchestrators.items()
              if orch.status().get("trades_opened", 0) > 0]
    if active:
        print("\nملخص الرموز النشطة:")
        for sym, orch in active:
            st  = orch.status()
            lrn = st.get("learning", {})
            print(f"  {sym:<14} صفقات={st['trades_opened']}"
                  f"  WR={lrn.get('win_rate', 0):.0%}"
                  f"  مفتوحة={len(st['open_positions'])}")

    gw.shutdown()
    print("=" * 60)


if __name__ == "__main__":
    main()


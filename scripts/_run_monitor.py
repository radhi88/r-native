"""
FRIDAY Multi-Symbol — يكتشف جميع رموز MT5 تلقائياً ويتداولها بالتوازي.

كل رمز:
  - orchestrator مستقل بوكلاء SMC خاصة به
  - scaler مُحسَّب لحظياً من بيانات الرمز (لا يعتمد على scaler الذهب)
  - LearningEngine يتعلم نمط كل رمز على حدة
  - حد أقصى صفقة واحدة مفتوحة لكل رمز
"""
import argparse
import sys, warnings, time, json, threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
warnings.filterwarnings('ignore')

import joblib
import numpy as np
from sklearn.preprocessing import StandardScaler

import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ.setdefault('TF_ENABLE_ONEDNN_OPTS', '0')
import tensorflow as tf
tf.get_logger().setLevel('ERROR')

from mt5_ai.config import (
    FEATURE_COLUMNS, MODEL_PATH, MODELS_DIR,
    MT5_SYMBOL, SCALER_PATH, SEQ_LEN,
)
from mt5_ai.agents.orchestrator import FridayOrchestrator
from mt5_ai.execution import DemoMT5Executor
from mt5_ai.mt5_gateway import MT5Gateway
from mt5_ai.orchestrator_adapter import OrchestratorAdapter
from mt5_ai.local_mind import LocalMind
from mt5_ai.market_structure import add_market_structure
from mt5_ai.human_learner import HumanBehaviorLearner
from mt5_ai.position_sync import PositionSyncer
from mt5_ai.cross_market import gold_to_energy_bias

class MonitorPaperExecutor:
    """Paper executor shape expected by FridayOrchestrator.

    It never calls MT5 order_send. It only reports accepted virtual orders so the
    MonitorAgent can track SL/TP, learning, confidence, and reward/punishment.
    """

    mode = "paper"

    @staticmethod
    def _stamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def execute(self, symbol, side, price, lot=0.01, sl=None, tp=None):
        return {
            "timestamp": self._stamp(),
            "sent": True,
            "mode": "paper",
            "action": "OPEN",
            "symbol": symbol,
            "side": side,
            "lot": float(lot),
            "requested_price": float(price),
            "sl": sl,
            "tp": tp,
            "reason": "paper_monitor_trade_logged",
        }

    def execute_pending(self, symbol, side, limit_price, lot=0.01, sl=None, tp=None):
        return {
            "timestamp": self._stamp(),
            "sent": True,
            "mode": "paper_pending",
            "action": "PENDING",
            "symbol": symbol,
            "side": side,
            "lot": float(lot),
            "limit_price": float(limit_price),
            "sl": sl,
            "tp": tp,
            "reason": "paper_monitor_pending_logged",
        }


def parse_args():
    parser = argparse.ArgumentParser(description="Run FRIDAY multi-symbol monitor.")
    parser.add_argument("--mode", choices=["auto", "paper", "demo"], default="auto")
    parser.add_argument("--bars", type=int, default=600)
    parser.add_argument("--max-symbols", type=int, default=60)
    parser.add_argument("--poll", type=int, default=15)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--manage-only", action="store_true",
                        help="Manage existing MT5 demo positions without opening new entries.")
    parser.add_argument("--visible-only", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


args = parse_args()

# ── تحميل النموذج ─────────────────────────────────────────────────────────────
model_path = MODEL_PATH if MODEL_PATH.exists() else MODELS_DIR / 'best_model.keras'
print(f"[LOAD] model  : {model_path.name}")
model = tf.keras.models.load_model(str(model_path), compile=False)

print(f"[LOAD] scaler : {Path(SCALER_PATH).name}")
_gold_scaler = joblib.load(SCALER_PATH)   # احتياطي فقط

# ── MT5 ───────────────────────────────────────────────────────────────────────
gw = MT5Gateway()
gw.initialize()
acc = gw.account_snapshot()
is_demo = gw.is_demo_account(acc)
print(f"[MT5]  {acc.get('login')} @ {acc.get('server')}  "
      f"balance=${acc.get('balance'):.2f}  {'DEMO' if is_demo else 'LIVE'}")

if args.mode == "demo" and not is_demo:
    print("[ERR] طلبت --mode demo لكن الحساب المتصل ليس ديمو. التشغيل متوقف.")
    gw.shutdown()
    sys.exit(1)

if args.mode == "paper" or (args.mode == "auto" and not is_demo):
    execution_mode = "paper"
    executor = MonitorPaperExecutor()
    print("[SAFE] Execution mode: PAPER — لا يتم إرسال أي أوامر إلى MT5")
else:
    execution_mode = "demo"
    executor = DemoMT5Executor(gw)
    print("[SAFE] Execution mode: DEMO MT5 — الحساب ديمو فقط")

# ── Runtime Scaler (لكل رمز على حدة) ─────────────────────────────────────────

def fit_scaler(enriched_df: Any) -> StandardScaler:
    """
    يُحسب StandardScaler من بيانات الرمز الحالية.
    كل رمز له نطاق سعري مختلف (ذهب≠يورو≠نفط)، لذلك لا يصح استخدام scaler واحد.
    """
    available = [c for c in FEATURE_COLUMNS if c in enriched_df.columns]
    data = enriched_df[available].dropna().to_numpy(dtype=np.float32)
    sc = StandardScaler()
    if len(data) >= 10:
        sc.fit(data)
    else:
        sc = _gold_scaler   # fallback إذا البيانات ناقصة
    return sc

# ── سجل الصفقات المشترك ───────────────────────────────────────────────────────
trade_log: list[dict] = []

# ── مولّد event callback لكل رمز ─────────────────────────────────────────────

def make_event_cb(symbol: str):
    def on_event(event: str, data: dict):
        ts = datetime.now().strftime('%H:%M:%S')

        if event == 'trade_open':
            side  = data.get('action', '?')
            otype = data.get('order_type', 'MARKET')
            lp    = data.get('limit_price')
            p     = data.get('price', 0)
            sl    = data.get('sl', 0)
            tp    = data.get('tp', 0)
            lot   = data.get('lot', 0)
            rr    = data.get('rr', '?')
            why   = data.get('reason', '')
            tid   = data.get('trade_id', '')
            pending  = otype in ('BUY_LIMIT', 'SELL_LIMIT')
            icon     = '🟡' if pending else ('🟢' if 'BUY' in side else '🔴')
            label    = f"PENDING {otype}" if pending else f"MARKET {side}"
            entry_ln = f"  Limit : {lp:.5f}\n" if pending else f"  Entry : {p:.5f}\n"
            sl_pts   = abs(p - sl) if sl else 0
            tp_pts   = abs(tp - p) if tp else 0
            print(
                f"\n{'='*62}\n"
                f"[{ts}] {icon} {label}  {symbol}\n"
                f"{entry_ln}"
                f"  SL    : {sl:.5f}  ({sl_pts:.5f} pts)\n"
                f"  TP    : {tp:.5f}  ({tp_pts:.5f} pts)\n"
                f"  R:R   : {rr}  Lot: {lot}\n"
                f"  Reason: {why}  [{tid}]\n"
                f"{'='*62}",
                flush=True,
            )
            trade_log.append({'event': 'open', 'symbol': symbol, 'time': ts, **data})

        elif event == 'trade_closed':
            won   = data.get('won', False)
            pnl   = data.get('pnl_points', 0)
            side  = data.get('side', '?')
            entry = data.get('entry', 0)
            exit_ = data.get('exit', 0)
            icon  = '💰' if won else '💸'
            print(
                f"\n{'='*62}\n"
                f"[{ts}] {icon} CLOSED  {symbol}  {side}\n"
                f"  Entry → Exit : {entry:.5f} → {exit_:.5f}\n"
                f"  PnL pts      : {pnl:+.5f}\n"
                f"  Result       : {'WIN ✅' if won else 'LOSS ❌'}\n"
                f"{'='*62}",
                flush=True,
            )
            trade_log.append({'event': 'closed', 'symbol': symbol, 'time': ts, **data})

        elif event == 'sl_update':
            reason = data.get('reason', '')
            sl_new = data.get('sl', 0)
            tid    = data.get('trade_id', '')
            if data.get('modify_sent') is False:
                print(
                    f"[{ts}] ⚠️  {symbol}  SL update rejected by MT5"
                    f"  kept SL={sl_new:.5f}  [{tid}]",
                    flush=True,
                )
                return
            peak   = data.get('peak')
            peak_s = f"  Peak={peak:.5f}" if peak else ""
            print(
                f"[{ts}] ⚙️  {symbol}  {reason.upper()} → SL={sl_new:.5f}{peak_s}  [{tid}]",
                flush=True,
            )

        elif event == 'prediction_hit':
            side   = data.get('side', '?')
            target = data.get('target', 0)
            price  = data.get('price', 0)
            print(
                f"[{ts}] 🎯 {symbol}  TOUCH HIT  {side} level={target:.5f}"
                f"  price={price:.5f}  confidence+",
                flush=True,
            )

        elif event == 'prediction_miss':
            side   = data.get('side', '?')
            target = data.get('target', 0)
            print(
                f"[{ts}] ⏳ {symbol}  TOUCH MISS  {side} level={target:.5f}",
                flush=True,
            )
    return on_event

# ── اكتشاف الرموز وبناء الـOrchestrators ─────────────────────────────────────
BARS        = max(SEQ_LEN + 50, int(args.bars))
MAX_SYMBOLS = max(1, int(args.max_symbols))
POLL        = max(1, int(args.poll))    # ثانية بين كل جولة

print(f"\n[SCAN] اكتشاف رموز MT5 المتاحة...")
all_sym_info = gw.symbols(visible_only=args.visible_only, tradable_only=True, limit=300)
print(f"[SCAN] {len(all_sym_info)} رمز مرشح\n")

# ── أولوية الرموز المهمة — تُضاف دائماً في المقدمة قبل الحد ──────────────────
_PRIORITY_SYMBOLS = [
    MT5_SYMBOL, "XAUUSDm",
    "USOILm", "UKOILm", "XNGUSDm",
    "EURUSDm", "GBPUSDm",
]
_priority_infos = [s for s in all_sym_info if s["symbol"] in _PRIORITY_SYMBOLS]
_rest_infos     = [s for s in all_sym_info if s["symbol"] not in _PRIORITY_SYMBOLS]
all_sym_info    = _priority_infos + _rest_infos

orchestrators: dict[str, FridayOrchestrator] = {}

for sym_info in all_sym_info:
    if len(orchestrators) >= MAX_SYMBOLS:
        break

    sym = sym_info["symbol"]
    try:
        df_init      = gw.fetch_rates(sym, 'M1', BARS)
        if len(df_init) < SEQ_LEN + 50:
            continue                            # بيانات غير كافية
        enriched_init = add_market_structure(df_init)
        sc = fit_scaler(enriched_init)

        orch = FridayOrchestrator(
            executor=executor,
            model=model,
            scaler=sc,
            symbol=sym,
            feature_columns=FEATURE_COLUMNS,
            seq_len=SEQ_LEN,
            max_positions=1,                    # صفقة واحدة لكل رمز
            event_cb=make_event_cb(sym),
            entries_enabled=not args.manage_only,
        )
        orchestrators[sym] = orch
        # مسح تاريخي للذيول — يبني قاعدة معرفة مبدئية من أول 500 شمعة
        try:
            orch.wick.scan_history(enriched_init, lookback=500)
        except Exception:
            pass
        print(f"  ✓ {sym}", end="  ", flush=True)

    except Exception:
        pass   # تجاهل الرموز التي تفشل في التهيئة

print(f"\n\n[BUILD] {len(orchestrators)} رمز جاهز\n")
if not orchestrators:
    print("[ERR] لم يتم بناء أي Orchestrator. تحقق من اتصال MT5 وعدد الشموع المتاحة.")
    gw.shutdown()
    sys.exit(1)

# ── LocalMind مربوط بالرمز الرئيسي ───────────────────────────────────────────
primary_orch    = orchestrators.get(MT5_SYMBOL) or next(iter(orchestrators.values()))
orch_adapter    = OrchestratorAdapter(primary_orch) if primary_orch else None
mind            = LocalMind(orchestrator=orch_adapter)

mind_label = f"مربوط بـ{primary_orch.symbol}" if primary_orch else "بدون Orchestrator"
print(f"[MIND] LocalMind جاهز ({mind_label}) — اكتب أمراً وأضغط Enter.")
print(f"       (حالة / صفقات / تعلم / أوقف)\n")


def _mind_input_loop():
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            resp   = mind.chat(text)
            answer = resp.get("answer", "")
            print(f"\n[FRIDAY] {answer}\n", flush=True)
        except Exception as exc:
            print(f"\n[MIND ERR] {exc}\n", flush=True)
        if orch_adapter and orch_adapter.should_stop():
            break


threading.Thread(target=_mind_input_loop, daemon=True, name="friday-mind").start()

# ── PositionSyncer — يكتشف تدخلات المتداول اليدوية ──────────────────────────
_shared_human  = HumanBehaviorLearner()
_pos_syncer    = PositionSyncer(gw=gw, human_learner=_shared_human)

# اربط نفس المتعلم بكل orchestrator (تعلّم مشترك عبر الرموز)
for _orch in orchestrators.values():
    _orch.human = _shared_human
    _orch.monitor.human_learner = _shared_human

if execution_mode == "demo":
    imported_positions = 0
    for _orch in orchestrators.values():
        imported_positions += _pos_syncer.import_open_positions(_orch)
    if imported_positions:
        print(f"[SYNC] تم استيراد {imported_positions} صفقة مفتوحة من MT5 إلى ذاكرة المراقبة")

# ── حلقة المراقبة متعددة الرموز ─────────────────────────────────────────────
print(f"[START] FRIDAY Multi-Symbol Scalping")
print(f"        رموز={len(orchestrators)}  Poll={POLL}s  Bars={BARS}  MaxPos=1/رمز")
if args.manage_only:
    print("        ManageOnly=ON  لا توجد صفقات جديدة، مراقبة وإدارة فقط")
print(f"        اضغط Ctrl+C للإيقاف\n")

bars_run  = 0
sym_list  = list(orchestrators.keys())

try:
    while True:
        if orch_adapter and orch_adapter.should_stop():
            print("\n[MIND] إيقاف مطلوب من LocalMind.")
            break

        bars_run += 1
        total_open = total_active = total_errors = total_perf_paused = 0
        gold_df = None
        try:
            gold_df = gw.fetch_rates(MT5_SYMBOL, 'M1', BARS)
        except Exception:
            gold_df = None

        for sym in sym_list:
            orch = orchestrators[sym]
            try:
                df = gw.fetch_rates(sym, 'M1', BARS)

                # تحديث الـscaler كل 20 جولة
                if bars_run % 20 == 0:
                    enriched_refresh = add_market_structure(df)
                    orch.scaler = fit_scaler(enriched_refresh)

                external_context = {
                    "cross_market": gold_to_energy_bias(sym, gold_df),
                }
                result = orch.on_bar(df, external_context=external_context)

                # ── مزامنة مع MT5 لاكتشاف التدخلات اليدوية ─────────────
                # تعمل فقط في demo، لأن وضع paper لا يرسل أوامر إلى MT5.
                if execution_mode == "demo" and orch.monitor.count() > 0:
                    price = result.get('price', 0)
                    atr   = result.get('atr', 0) or 1.0
                    events = _pos_syncer.sync(orch, current_price=price, atr=atr)
                    for ev in events:
                        ts_ev = datetime.now().strftime('%H:%M:%S')
                        if ev['type'] == 'manual_close':
                            pnl  = ev.get('pnl_points', 0)
                            icon = '🧑💰' if pnl > 0 else '🧑💸'
                            conf = orch.confidence.status()
                            print(
                                f"\n[{ts_ev}] {icon} MANUAL CLOSE  {sym}  {ev['side']}"
                                f"  pnl={pnl:+.5f}"
                                f"  → confidence={conf['confidence']:.2f}"
                                f"  lot×{conf['lot_mult']:.2f}"
                                f"  extra_pos={conf['extra_pos']}\n",
                                flush=True,
                            )
                        elif ev['type'] == 'manual_sl_move':
                            print(
                                f"\n[{ts_ev}] 🧑⚙️  MANUAL SL  {sym}  {ev['side']}"
                                f"  {ev['old_sl']:.5f} → {ev['new_sl']:.5f}"
                                f"  (تعلّم المسافة)\n",
                                flush=True,
                            )

                action = result.get('action', 'HOLD')
                reason = str(result.get('reason', ''))
                pos    = result.get('open_pos', 0)
                total_open   += pos
                total_active += int(action != 'HOLD')
                total_perf_paused += int(reason.startswith('symbol_paused_recent_perf'))

            except Exception:
                total_errors += 1

        ts   = datetime.now().strftime('%H:%M:%S')
        wins = sum(1 for t in trade_log if t.get('event') == 'closed' and t.get('won'))
        loss = sum(1 for t in trade_log if t.get('event') == 'closed' and not t.get('won'))

        status_line = (
            f"[{ts}] bar={bars_run}  رموز={len(sym_list)}"
            f"  مفتوحة={total_open}  إشارات={total_active}"
            + (f"  حماية_أداء={total_perf_paused}" if total_perf_paused else "")
            + f"  W={wins} L={loss}"
            + (f"  err={total_errors}" if total_errors else "")
        )
        print(status_line, end='\r', flush=True)

        if args.once:
            print()
            break

        time.sleep(POLL)

except KeyboardInterrupt:
    pass

finally:
    print(f"\n\n{'='*62}")
    print(f"إجمالي جولات : {bars_run}")
    print(f"رموز نشطة    : {len(sym_list)}")

    closed = [t for t in trade_log if t.get('event') == 'closed']
    if closed:
        wins      = sum(1 for t in closed if t.get('won'))
        total_pnl = sum(t.get('pnl_points', 0) for t in closed)
        print(f"\nنتائج كل الصفقات المغلقة ({len(closed)}):")
        print(f"  ربح / خسارة : {wins} / {len(closed) - wins}")
        print(f"  WR           : {wins/len(closed):.1%}")
        print(f"  PnL إجمالي  : {total_pnl:+.4f} نقطة")
    else:
        print("لا توجد صفقات مغلقة بعد")

    # ملخص لكل رمز تعلّم أو فتح صفقات
    active_syms = [
        (sym, orch) for sym, orch in orchestrators.items()
        if orch.status().get('trades_opened', 0) > 0
        or len(orch.status().get('open_positions', {})) > 0
    ]
    if active_syms:
        print(f"\nملخص الرموز النشطة:")
        for sym, orch in active_syms:
            st  = orch.status()
            lrn = st.get('learning', {})
            print(
                f"  {sym:<14} صفقات={st['trades_opened']}"
                f"  WR={lrn.get('win_rate', 0):.0%}"
                f"  مفتوحة={len(st['open_positions'])}"
            )

    gw.shutdown()
    print('='*62)

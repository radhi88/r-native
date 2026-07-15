"""fabio_orb.py — 🎯 نموذج Fabio Valentini (IVB / FaberVaale ORB) — تطبيقٌ أمينٌ على MT5.

المصدر: تقرير التحقّق المستقلّ «The Institutional Protocol» (Matteo Conti، 823 صفقة NQ،
فوز 58٪، PF 1.28 بعد الكلفة، P(EV≤0)=0.001). الاستراتيجية:

  • نطاق الافتتاح (ORB): 08:30→09:00 بتوقيت نيويورك (30د)، أعلى/أدنى شمعات M5.
  • الدخول: طويلٌ فقط — عند إغلاق شمعة M5 فوق قمّة النطاق، بعد انتهاء جلسة النطاق،
    ضمن نافذة التداول حتى 14:00 نيويورك (كما في البارامترات المُختبرة). مرّةً واحدة لليوم.
  • فلتر الدلتا: BarDelta = Upticks−Downticks ≥ عتبة (تقريبيّ على CFD عبر copy_ticks؛
    اختياريّ عبر use_bar_delta، ولا يحجب إن غابت بيانات التيك — صدقٌ لا تزييف).
  • الوقف = أدنى النطاق. الهدف = الدخول + 1R×(الدخول−أدنى النطاق) [TP_RR=1.0].
  • تسييلٌ إجباريّ عند 14:00 نيويورك. مركزٌ واحد، لوت ثابت.

الرمز: USTECm (نظير ناسداك-100 لعقد NQ) — رمزك الوحيد المُثبت +EV. قابلٌ للضبط.

جدرانٌ صارمة: ديمو فقط (Trial/Demo) · مفتاحا القتل · enabled/execute من الإعداد كلّ دورة
(execute=false افتراضياً: يبني النطاق ويسجّل الإشارة بلا تنفيذٍ حتى تفعّله). magic 20260716.
يُحكَم تلقائياً بواسطة edge_governor (لو نزف صافيه ⇒ enabled=false). Windowless:
  pythonw fabio_orb.py
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")            # يتعامل مع التوقيت الصيفيّ تلقائياً
except Exception:                                 # احتياط: EST ثابت إن غاب zoneinfo
    NY = timezone(timedelta(hours=-5))
UTC = timezone.utc

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
CFG_F = RN / "fabio_orb_config.json"
STATUS_F = RN / "fabio_orb_status.json"
STATE_F = RN / "fabio_orb_state.json"
KILL1 = RN / "kill_switch.txt"
KILL2 = MT5DIR / "kill_switch.txt"
MAGIC = 20260716
COMMENT = "fabio-orb"
POLL_S = 15

for p in (str(MT5DIR), str(MT5DIR / "r_native_v2")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _log(msg):
    print(f"[{datetime.now(UTC):%H:%M:%S}] {msg}", flush=True)


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except Exception:
        return d


def _save(p, obj):
    try:
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(str(p) + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception as e:
        _log(f"save fail {p}: {e}")


def _cfg():
    """الإعداد — يُكتب بالافتراضات عند الغياب فقط (فيثبت enabled=false الذي يكتبه الحاكم)."""
    d = {"enabled": True, "execute": False, "symbol": "USTECm",
         "orb_start_h_ny": 8, "orb_start_m_ny": 30, "orb_dur_min": 30,
         "trade_end_h_ny": 14, "trade_end_m_ny": 0, "tp_rr": 1.0,
         "lot": 0.01, "max_spread_pts": 9.0,
         "use_bar_delta": True, "delta_threshold": 200,
         "_note": "🎯 نموذج Fabio ORB (magic 20260716). execute=false ⇒ إشارةٌ فقط بلا "
                  "تنفيذ (آمن). فعّل execute=true للتداول المحكوم على الديمو. الرمز USTECm = "
                  "نظير NQ. الدلتا تقريبيّة على CFD (copy_ticks) — لا تحجب إن غابت."}
    got = _load(CFG_F)
    if isinstance(got, dict):
        d.update(got)
    else:
        _save(CFG_F, d)
    return d


def _is_demo(mt5):
    a = mt5.account_info()
    if not a:
        return False
    if a.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
        return True
    srv = (a.server or "").lower()
    return ("trial" in srv or "demo" in srv) and "real" not in srv


def _killed():
    return KILL1.exists() or KILL2.exists()


def _ny_window_utc(cfg, now_ny):
    """يعيد (orb_start, orb_end, trade_end) بتوقيت UTC ليوم now_ny."""
    o0 = now_ny.replace(hour=int(cfg["orb_start_h_ny"]), minute=int(cfg["orb_start_m_ny"]),
                        second=0, microsecond=0)
    o1 = o0 + timedelta(minutes=int(cfg["orb_dur_min"]))
    te = now_ny.replace(hour=int(cfg["trade_end_h_ny"]), minute=int(cfg["trade_end_m_ny"]),
                        second=0, microsecond=0)
    return o0.astimezone(UTC), o1.astimezone(UTC), te.astimezone(UTC)


def _opening_range(mt5, sym, o0_utc, o1_utc):
    """أعلى/أدنى شمعات M5 داخل [o0, o1). يعيد (hi, lo) أو (None, None)."""
    r = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M5, o0_utc, o1_utc)
    if r is None or len(r) < 1:
        return None, None
    hi = max(float(x["high"]) for x in r)
    lo = min(float(x["low"]) for x in r)
    return hi, lo


def _bar_delta(mt5, sym, t_from_utc, t_to_utc):
    """تقريبٌ لـ BarDelta = Upticks−Downticks عبر تصنيف التيكات بحركة آخر سعر.
    يعيد None إن غابت بيانات التيك (⇒ لا نحجب)."""
    try:
        ticks = mt5.copy_ticks_range(sym, t_from_utc, t_to_utc, mt5.COPY_TICKS_ALL)
    except Exception:
        return None
    if ticks is None or len(ticks) < 2:
        return None
    up = dn = 0
    prev = None
    for tk in ticks:
        last = float(tk["last"]) or float(tk["bid"])   # CFD قد يكون last=0 ⇒ استخدم bid
        if prev is not None:
            if last > prev:
                up += 1
            elif last < prev:
                dn += 1
        prev = last
    return up - dn


def _spread_pts(tick):
    try:
        return round(float(tick.ask) - float(tick.bid), 2)
    except Exception:
        return 999.0


def _enter_long(mt5, sym, info, entry_px, orb_lo, cfg):
    """أمر سوقٍ طويل: SL=أدنى النطاق، TP=دخول+1R×(دخول−أدنى)."""
    tick = mt5.symbol_info_tick(sym)
    if not tick:
        return False
    price = float(tick.ask)
    risk = price - float(orb_lo)
    if risk <= 0:
        _log("SL فوق الدخول — تخطّي"); return False
    tp = price + float(cfg["tp_rr"]) * risk
    d = info.digits
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(cfg["lot"]),
           "type": mt5.ORDER_TYPE_BUY, "price": round(price, d),
           "sl": round(float(orb_lo), d), "tp": round(tp, d),
           "deviation": 50, "magic": MAGIC, "comment": COMMENT,
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    ok = bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)
    _log(f"{'✅' if ok else '❌'} BUY {sym} @{req['price']} SL={req['sl']} TP={req['tp']} "
         f"ret={getattr(r, 'retcode', '?')}")
    return ok


def _flat_eod(mt5, sym):
    for p in (mt5.positions_get(symbol=sym) or []):
        if p.magic != MAGIC:
            continue
        t = mt5.symbol_info_tick(sym)
        mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "position": p.ticket, "symbol": sym,
                        "volume": p.volume, "type": mt5.ORDER_TYPE_SELL,
                        "price": t.bid if t else 0.0, "deviation": 50, "magic": MAGIC,
                        "comment": "fabio-eod", "type_filling": mt5.ORDER_FILLING_IOC})
        _log(f"🕒 EOD تسييل {sym} pos={p.ticket}")


def _has_pos(mt5, sym):
    return any(p.magic == MAGIC for p in (mt5.positions_get(symbol=sym) or []))


def main():
    from engine_lock import claim
    claim("fabio_orb")
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        _log("mt5 init failed"); return 1
    _log(f"نموذج Fabio ORB حيّ · magic {MAGIC}")
    st = _load(STATE_F, {}) or {}
    st.setdefault("done", {})            # "date" -> True (دخولٌ واحدٌ لليوم)

    while True:
        note = ""
        try:
            cfg = _cfg()
            sym = str(cfg["symbol"])
            enabled = bool(cfg.get("enabled", True))
            execute = bool(cfg.get("execute", False))
            if not enabled:
                note = "disabled"
            elif _killed():
                note = "kill_switch"
            elif not _is_demo(mt5):
                note = "not_demo"
            else:
                mt5.symbol_select(sym, True)
                info = mt5.symbol_info(sym)
                tick = mt5.symbol_info_tick(sym)
                now_ny = datetime.now(NY)
                today = now_ny.strftime("%Y-%m-%d")
                if not info or not tick:
                    note = "no_symbol"
                else:
                    o0, o1, te = _ny_window_utc(cfg, now_ny)
                    now_utc = datetime.now(UTC)
                    have_pos = _has_pos(mt5, sym)

                    # نهاية الجلسة (14:00 نيويورك) ⇒ سيّل أيّ مركز
                    if now_utc >= te:
                        if have_pos:
                            _flat_eod(mt5, sym)
                        note = "session_over"
                    elif now_utc < o1:
                        note = "orb_forming" if now_utc >= o0 else "before_open"
                    elif have_pos:
                        note = "in_position"
                    elif st["done"].get(today):
                        note = "done_today"
                    else:
                        hi, lo = _opening_range(mt5, sym, o0, o1)
                        if hi is None or (hi - lo) <= 0:
                            note = "no_range"
                        else:
                            # آخر شمعة M5 مُغلقة
                            bars = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 3)
                            if bars is None or len(bars) < 2:
                                note = "no_bars"
                            else:
                                last = bars[-2]         # المُغلقة (‑1 قيد التكوّن)
                                close = float(last["close"])
                                spread = _spread_pts(tick)
                                if close <= hi:
                                    note = f"watch hi={hi:.1f} close={close:.1f}"
                                elif spread > float(cfg["max_spread_pts"]):
                                    note = f"spread_veto {spread}"
                                else:
                                    # فلتر الدلتا (تقريبيّ، لا يحجب إن غاب)
                                    delta_ok = True
                                    if cfg.get("use_bar_delta", True):
                                        bt = datetime.fromtimestamp(int(last["time"]), UTC)
                                        bd = _bar_delta(mt5, sym, bt, bt + timedelta(minutes=5))
                                        if bd is not None:
                                            delta_ok = bd >= int(cfg["delta_threshold"])
                                            note = f"break close={close:.1f} delta={bd} ok={delta_ok}"
                                        else:
                                            note = f"break close={close:.1f} delta=NA(pass)"
                                    else:
                                        note = f"break close={close:.1f} delta=off"
                                    if delta_ok:
                                        if execute:
                                            if _enter_long(mt5, sym, info, close, lo, cfg):
                                                st["done"][today] = True
                                                _save(STATE_F, st)
                                        else:
                                            note += " | execute=false (إشارةٌ فقط)"
                    # نظافة مفاتيح الأيام
                    st["done"] = {k: v for k, v in st["done"].items() if k == today}
        except Exception as e:
            note = f"err {e}"
            _log(note)
        _save(STATUS_F, {"ts": time.time(), "iso": datetime.now(UTC).isoformat(),
                         "magic": MAGIC, "symbol": str(_load(CFG_F, {}).get("symbol", "USTECm")),
                         "note": note})
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())

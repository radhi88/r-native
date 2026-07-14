"""
mt5_client.py — غلاف رقيق حول حزمة MetaTrader5 الرسمية (ويندوز فقط).
لو MT5 مفتوح ومسجّل دخول، يكفي تتركه يلتصق بالترمينال الشغّال (بدون باسورد في .env).

تحصين FRIDAY (أُضيف عند الاستلام):
  • التنفيذ **ديمو-فقط** — يُكشف الديمو عبر اسم الخادم (Trial/Demo)؛ Exness Trial يُبلّغ
    trade_mode=0 (REAL) فلا نعتمد عليه (درس المشروع).
  • التنفيذ يحترم kill_switch.txt — لو مُفعّل لا يفتح صفقة.
"""
import os
import threading
import time as _time
from datetime import datetime, timezone
from pathlib import Path
import MetaTrader5 as mt5

MT5_ROOT = Path(r"C:\Users\Radhi\MT5")
KILL = MT5_ROOT / "kill_switch.txt"

TF_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

_connected = False
_connect_lock = threading.Lock()
_bg_started = False

# 🛡️ درس عطل 2026-06-28: mt5.initialize() يحجب ~60ث لو الطرفية مخنوقة. نُجريه **في خيط خلفيّ فقط**
# (لا في startup ولا في نقاط النهاية) كي لا يُعلّق uvicorn ولا يتكدّس. النقاط تقرأ علامة الاتصال فقط.


def connect():
    """محاولة اتصال واحدة (قد تحجب على initialize). تُستدعى من خيط الخلفية فقط — لا من النقاط."""
    global _connected
    with _connect_lock:
        if _connected:
            return True, "متصل"
        login = int(os.getenv("MT5_LOGIN", "0") or 0)
        password = os.getenv("MT5_PASSWORD", "")
        server = os.getenv("MT5_SERVER", "")
        path = os.getenv("MT5_PATH", "") or None
        kwargs = {}
        if path:
            kwargs["path"] = path
        if not mt5.initialize(**kwargs):
            return False, f"initialize فشل: {mt5.last_error()}"
        if login and password and server:
            if not mt5.login(login, password=password, server=server):
                err = mt5.last_error()
                mt5.shutdown()
                return False, f"login فشل: {err}"
        _connected = True
        return True, "متصل بالترمينال"


def _bg_loop():
    while True:
        if not _connected:
            try:
                connect()
            except Exception:
                pass
        _time.sleep(30)               # محاولة كل 30ث — لا إغراق للطرفية


def start_background_connect():
    """يبدأ خيط اتصال خلفيّ (غير حاجب). يُستدعى مرّة من startup."""
    global _bg_started
    if _bg_started:
        return
    _bg_started = True
    threading.Thread(target=_bg_loop, daemon=True).start()


def ensure():
    """غير حاجب: يُرجع حالة الاتصال فقط (لا يستدعي initialize أبداً)."""
    return _connected, ("متصل" if _connected else "MT5 يتصل…")


def is_connected():
    return _connected


def is_demo():
    """ديمو؟ يُكشف عبر اسم الخادم (Trial/Demo) — لا عبر trade_mode (Exness Trial يكذب)."""
    info = mt5.account_info()
    if info is None:
        return False
    srv = (info.server or "").lower()
    return ("trial" in srv) or ("demo" in srv)


def account():
    info = mt5.account_info()
    if info is None:
        return None
    return {
        "login": info.login, "balance": info.balance, "equity": info.equity,
        "currency": info.currency, "leverage": info.leverage,
        "profit": info.profit, "server": info.server, "demo": is_demo(),
    }


def list_symbols(only_watch=None):
    syms = mt5.symbols_get()
    names = [s.name for s in syms] if syms else []
    if only_watch:
        wanted = set(only_watch)
        names = [n for n in names if n in wanted]
    return names


def tick(symbol):
    mt5.symbol_select(symbol, True)
    t = mt5.symbol_info_tick(symbol)
    if t is None:
        return None
    info = mt5.symbol_info(symbol)
    spread = round((t.ask - t.bid) / (info.point or 1)) if info else None
    return {
        "symbol": symbol, "bid": t.bid, "ask": t.ask, "last": t.last or t.bid,
        "spread": spread,
        "time": datetime.fromtimestamp(t.time, tz=timezone.utc).isoformat(),
    }


def rates(symbol, tf, count=250):
    if tf not in TF_MAP:
        return []
    mt5.symbol_select(symbol, True)
    raw = mt5.copy_rates_from_pos(symbol, TF_MAP[tf], 0, count)
    if raw is None:
        return []
    return [{
        "time": int(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
        "low": float(r["low"]), "close": float(r["close"]), "volume": int(r["tick_volume"]),
    } for r in raw]


def market_order(symbol, side, volume, sl=None, tp=None, deviation=20):
    """تنفيذ أمر سوق. يجرّب أنماط التعبئة المختلفة حسب ما يقبله البروكر.
    🛡️ تحصين FRIDAY: ديمو-فقط + احترام kill_switch."""
    if KILL.exists():
        return {"error": "🛑 kill_switch مُفعّل — التنفيذ متوقّف"}
    if not is_demo():
        return {"error": "🛑 محظور: ليس حساب ديمو. التنفيذ من الجسر مسموح على الديمو فقط."}

    mt5.symbol_select(symbol, True)
    info = mt5.symbol_info(symbol)
    t = mt5.symbol_info_tick(symbol)
    if info is None or t is None:
        return {"error": f"رمز غير متاح: {symbol}"}

    otype = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    price = t.ask if side == "BUY" else t.bid
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(volume),
        "type": otype, "price": price, "deviation": deviation,
        "magic": 555000, "comment": "RConfirm", "type_time": mt5.ORDER_TIME_GTC,
    }
    if sl:
        req["sl"] = float(sl)
    if tp:
        req["tp"] = float(tp)

    for fill in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
        req["type_filling"] = fill
        r = mt5.order_send(req)
        if r is None:
            return {"error": f"order_send=None: {mt5.last_error()}"}
        if r.retcode == mt5.TRADE_RETCODE_DONE:
            return {"ok": True, "order": r.order, "deal": r.deal,
                    "price": r.price, "volume": r.volume}
        if r.retcode in (mt5.TRADE_RETCODE_INVALID_FILL,):
            continue  # جرّب نمط تعبئة آخر
        return {"error": f"retcode={r.retcode} {r.comment}"}
    return {"error": "كل أنماط التعبئة مرفوضة من البروكر"}


_PENDING_TYPES = {"BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT, "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
                  "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP, "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP}
_ONAME = {v: k for k, v in _PENDING_TYPES.items()}


def pending_order(symbol, otype, price, volume, sl=None, tp=None):
    """أمر محدّد (limit/stop) عند سعر معيّن. ديمو-فقط + يحترم kill_switch."""
    if KILL.exists():
        return {"error": "🛑 kill_switch مُفعّل"}
    if not is_demo():
        return {"error": "🛑 ديمو فقط"}
    t = _PENDING_TYPES.get(str(otype).upper())
    if t is None:
        return {"error": "نوع غير صحيح (BUY_LIMIT/SELL_LIMIT/BUY_STOP/SELL_STOP)"}
    mt5.symbol_select(symbol, True)
    info = mt5.symbol_info(symbol)
    if info is None:
        return {"error": f"رمز غير متاح: {symbol}"}
    req = {"action": mt5.TRADE_ACTION_PENDING, "symbol": symbol, "volume": float(volume),
           "type": t, "price": round(float(price), info.digits), "deviation": 50,
           "magic": 555000, "comment": "RConfirm-pend", "type_time": mt5.ORDER_TIME_GTC}
    if sl:
        req["sl"] = round(float(sl), info.digits)
    if tp:
        req["tp"] = round(float(tp), info.digits)
    for fill in (mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK):
        req["type_filling"] = fill
        r = mt5.order_send(req)
        if r is None:
            return {"error": f"order_send=None: {mt5.last_error()}"}
        if r.retcode == mt5.TRADE_RETCODE_DONE:
            return {"ok": True, "order": r.order, "type": str(otype).upper(), "price": req["price"]}
        if r.retcode == mt5.TRADE_RETCODE_INVALID_FILL:
            continue
        return {"error": f"retcode={r.retcode} {r.comment}"}
    return {"error": "كل أنماط التعبئة مرفوضة"}


def pendings():
    """الأوامر المحدّدة المعلّقة (كلها) + المسافة للسعر الحاليّ (هل سيلامسها؟)."""
    out = []
    for o in (mt5.orders_get() or []):
        tk = mt5.symbol_info_tick(o.symbol)
        cur = ((tk.bid + tk.ask) / 2.0) if tk else None
        info = mt5.symbol_info(o.symbol)
        atr = None
        try:
            import numpy as np
            r = mt5.copy_rates_from_pos(o.symbol, mt5.TIMEFRAME_M5, 0, 15)
            if r is not None and len(r) > 1:
                h, l, c = r["high"], r["low"], r["close"]
                tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
                atr = float(tr.mean())
        except Exception:
            pass
        dist = abs(cur - o.price_open) if cur is not None else None
        out.append({"ticket": o.ticket, "symbol": o.symbol, "type": _ONAME.get(o.type, str(o.type)),
                    "price": o.price_open, "volume": o.volume_current, "cur": round(cur, 5) if cur else None,
                    "dist": round(dist, 5) if dist is not None else None,
                    "dist_atr": round(dist / atr, 2) if (dist is not None and atr) else None,
                    "mine": o.magic == 555000})
    return out


def cancel_pending(ticket):
    """إلغاء أمر محدّد معلّق."""
    r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": int(ticket)})
    if r is None:
        return {"error": f"None: {mt5.last_error()}"}
    return {"ok": r.retcode == mt5.TRADE_RETCODE_DONE, "retcode": r.retcode}


def order_check(symbol, side, volume):
    """تحقّق من صحّة الطلب دون تنفيذ (للاختبار الآمن)."""
    mt5.symbol_select(symbol, True)
    t = mt5.symbol_info_tick(symbol)
    if t is None:
        return {"error": f"رمز غير متاح: {symbol}"}
    otype = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    price = t.ask if side == "BUY" else t.bid
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(volume),
           "type": otype, "price": price, "deviation": 20, "magic": 555000,
           "comment": "RConfirm-check", "type_time": mt5.ORDER_TIME_GTC,
           "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_check(req)
    if r is None:
        return {"error": f"order_check=None: {mt5.last_error()}"}
    return {"retcode": r.retcode, "comment": r.comment, "balance": r.balance,
            "margin": r.margin, "margin_free": r.margin_free, "demo": is_demo()}


def shutdown():
    global _connected
    mt5.shutdown()
    _connected = False

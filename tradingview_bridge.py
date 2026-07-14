# -*- coding: utf-8 -*-
"""tradingview_bridge.py — 🌉 جسر TradingView → MT5 (طلب المستخدم: الشارت على TradingView، التنفيذ على ميتا).

الآليّة المعتمدة عالميّاً (لا قراءة شارت — TradingView لا تتيحها): تنبيه TradingView (Webhook) يرسل JSON
إلى نقطة عندنا، فننفّذ على MT5. أنت تضبط التنبيه على شارتك؛ نحن ننفّذ بأمان.

🔒 أمانٌ صارم (نقطة عامّة تُنفّذ صفقات = سطح خطر): (1) سرٌّ إجباريّ في كل طلب، (2) ديمو فقط،
(3) kill_switch، (4) execute=false افتراضيّاً (يسجّل فقط حتى تُفعّله بنفسك)، (5) قائمة رموز بيضاء
اختياريّة، (6) لوت محدود. ماجيك خاصّ 20260710. كل طلب يُسجَّل.

⚖️ الصدق: هذا يوصّل شارتك كمصدر إشارة + ميتا كمنفّذ — لكنّ مؤشّرات TradingView هي نفسها التي قِستُ
أنّها بلا حافّة OOS. الجسر لا يخلق حافّة؛ ينفّذ استراتيجيّتك. إن كان لشارتك حافّة، يقيسها التشريح.

التنفيذ عبر إنترنت: TradingView يحتاج URL عامّاً — استخدم نفق Cloudflare (tools/cloudflared.exe).
Run: pythonw tradingview_bridge.py     ·     يستمع POST على :8025/tv
"""
from __future__ import annotations
import sys, os, json, time, secrets, threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
LOG = RN / "tradingview_bridge.out.log"
JL = RN / "tradingview_bridge.jsonl"
STATUS_F = RN / "tradingview_bridge_status.json"
CFG_F = RN / "tradingview_bridge_config.json"
PORT = 8025
MAGIC = 20260710

try:
    RN.mkdir(parents=True, exist_ok=True)
    _lf = open(LOG, "a", buffering=1, encoding="utf-8"); sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass
if str(MT5DIR) not in sys.path:
    sys.path.insert(0, str(MT5DIR))

import MetaTrader5 as mt5

_mt5_lock = threading.Lock()


def _cfg():
    d = {"enabled": True, "execute": False, "secret": "", "default_lot": 0.01,
         "max_lot": 0.10, "allowed_symbols": [], "stop_pips": 0, "tp_pips": 0}
    try:
        d.update(json.load(open(CFG_F, encoding="utf-8")))
    except Exception:
        pass
    # توليد سرٍّ قويّ عند أوّل تشغيل + كتابته للإعداد (تضعه أنت في تنبيه TradingView)
    if not d.get("secret"):
        d["secret"] = secrets.token_urlsafe(24)
        try:
            json.dump(d, open(CFG_F, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except Exception:
            pass
        print(f"🔑 سرٌّ جديد وُلِّد وحُفِظ في {CFG_F.name}: {d['secret']}", flush=True)
    return d


def _is_demo():
    try:
        a = mt5.account_info(); s = (a.server or "").lower() if a else ""
        return ("demo" in s) or ("trial" in s)
    except Exception:
        return False


def _killed():
    return (RN / "kill_switch.txt").exists() or (MT5DIR / "kill_switch.txt").exists()


def _log(rec):
    try:
        with open(JL, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _execute(action, symbol, lot, sl_pips, tp_pips, cfg):
    """ينفّذ على MT5 (ديمو، ماجيك 20260710). يرجع (ok, msg)."""
    with _mt5_lock:
        if not (mt5.initialize() or mt5.initialize()):
            return (False, "mt5 init فشل")
        try:
            if not _is_demo():
                return (False, "ليس ديمو — رُفض (حماية)")
            si = mt5.symbol_info(symbol)
            if si is None:
                mt5.symbol_select(symbol, True); si = mt5.symbol_info(symbol)
            if si is None:
                return (False, f"رمز غير معروف: {symbol}")
            t = mt5.symbol_info_tick(symbol)
            if not t:
                return (False, "لا سعر")
            act = str(action).lower()
            if act in ("close", "flat", "exit"):
                closed = 0
                for p in (mt5.positions_get(symbol=symbol) or []):
                    if p.magic != MAGIC:
                        continue
                    ct = mt5.symbol_info_tick(symbol)
                    price = ct.bid if p.type == 0 else ct.ask
                    r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
                                        "volume": float(p.volume), "position": p.ticket,
                                        "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
                                        "price": float(price), "deviation": 40, "magic": MAGIC,
                                        "comment": "tv-close", "type_filling": mt5.ORDER_FILLING_IOC})
                    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                        closed += 1
                return (True, f"أُغلق {closed} مركز {symbol}")
            is_buy = act in ("buy", "long")
            if not (is_buy or act in ("sell", "short")):
                return (False, f"إجراء غير معروف: {action}")
            lot = max(float(si.volume_min or 0.01), min(float(cfg.get("max_lot", 0.10)), float(lot)))
            price = t.ask if is_buy else t.bid
            pt = si.point or 0.0001
            sl = tp = 0.0
            if sl_pips and sl_pips > 0:
                sl = price - sl_pips * 10 * pt if is_buy else price + sl_pips * 10 * pt
            if tp_pips and tp_pips > 0:
                tp = price + tp_pips * 10 * pt if is_buy else price - tp_pips * 10 * pt
            req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(round(lot, 2)),
                   "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL, "price": float(price),
                   "deviation": 40, "magic": MAGIC, "comment": "tv-bridge",
                   "type_filling": mt5.ORDER_FILLING_IOC}
            if sl:
                req["sl"] = float(round(sl, si.digits))
            if tp:
                req["tp"] = float(round(tp, si.digits))
            r = mt5.order_send(req)
            ok = bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)
            return (ok, f"{'نُفّذ' if ok else 'فشل'} {act} {lot} {symbol} @ {price} (rc={getattr(r,'retcode','?')})")
        finally:
            mt5.shutdown()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # لا ضجيج

    def _reply(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        # فحص صحّة بسيط (لا سرّ، لا تنفيذ)
        self._reply(200, {"ok": True, "service": "tradingview_bridge", "hint": "POST /tv with JSON {secret,action,symbol,...}"})

    def do_POST(self):
        cfg = _cfg()
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:
            return self._reply(400, {"ok": False, "err": "json غير صالح"})
        # 🔒 سرّ إجباريّ
        if str(payload.get("secret", "")) != str(cfg.get("secret", "")):
            _log({"ts": time.time(), "iso": time.strftime("%H:%M:%S"), "rejected": "bad_secret", "ip": self.client_address[0]})
            return self._reply(403, {"ok": False, "err": "سرّ خاطئ"})
        if not cfg.get("enabled", True) or _killed():
            return self._reply(200, {"ok": False, "err": "معطّل أو kill_switch"})
        action = payload.get("action") or payload.get("side") or payload.get("signal")
        symbol = payload.get("symbol") or payload.get("ticker") or ""
        symbol = str(symbol).replace("XAUUSD", "XAUUSDm") if symbol and not symbol.endswith("m") and symbol.isalpha() else symbol
        lot = payload.get("lot", cfg.get("default_lot", 0.01))
        aw = cfg.get("allowed_symbols") or []
        if aw and symbol not in aw:
            _log({"ts": time.time(), "rejected": "symbol_not_allowed", "symbol": symbol})
            return self._reply(200, {"ok": False, "err": f"رمز غير مسموح: {symbol}"})
        rec = {"ts": time.time(), "iso": time.strftime("%H:%M:%S"), "action": action, "symbol": symbol,
               "lot": lot, "execute": bool(cfg.get("execute"))}
        if not cfg.get("execute", False):
            rec["result"] = "log_only (execute=false)"
            _log(rec); print(f"📩 تنبيه (تسجيل فقط): {action} {symbol} {lot}", flush=True)
            return self._reply(200, {"ok": True, "mode": "log_only", "note": "فعّل execute=true للتنفيذ الفعليّ"})
        ok, msg = _execute(action, symbol, lot, payload.get("sl_pips", cfg.get("stop_pips", 0)),
                           payload.get("tp_pips", cfg.get("tp_pips", 0)), cfg)
        rec["result"] = msg; rec["ok"] = ok; _log(rec)
        print(f"{'⚡' if ok else '⏭️'} {msg}", flush=True)
        return self._reply(200, {"ok": ok, "msg": msg})


def _status_loop():
    while True:
        try:
            cfg = _cfg()
            json.dump({"ts": time.time(), "iso": time.strftime("%H:%M:%S"), "engine": "جسر TradingView",
                       "port": PORT, "enabled": cfg.get("enabled"), "execute": cfg.get("execute"),
                       "has_secret": bool(cfg.get("secret")), "magic": MAGIC},
                      open(STATUS_F, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
        time.sleep(30)


def main():
    cfg = _cfg()
    print(f"🌉 جسر TradingView بدأ على :{PORT}/tv — enabled={cfg.get('enabled')} execute={cfg.get('execute')} "
          f"(execute=false ⇒ تسجيل فقط). السرّ في {CFG_F.name}", flush=True)
    threading.Thread(target=_status_loop, daemon=True).start()
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), _Handler)  # 0.0.0.0 ليصله النفق
    except OSError:
        print(f"المنفذ {PORT} مشغول — نسخة أخرى تعمل، خروج.", flush=True); return
    srv.serve_forever()


if __name__ == "__main__":
    main()

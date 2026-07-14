"""
server.py — الجسر + يخدم تطبيق الجوال نفسه.
شغّله، وافتح من جوالك على نفس الواي فاي:  http://<آي-بي-الجهاز>:8000/

  GET  /               واجهة الجوال
  GET  /health         فحص الحالة (+ ديمو؟)
  GET  /account        معلومات الحساب
  GET  /symbols        الرموز
  GET  /scan           مسح (مع watchlist اختياري) — مُثرى بقناعة FRIDAY الحقيقية
  GET  /candles        شموع للشارت
  POST /confirm        تأكيد كلود
  POST /order_check    تحقّق من أمر دون تنفيذ (آمن)
  POST /order          تنفيذ صفقة سوق (ديمو-فقط + يحترم kill_switch + توكن اختياريّ)
  WS   /stream         بثّ أسعار لحظي

تشغيل:  uvicorn server:app --host 0.0.0.0 --port 8000

تحصين FRIDAY (أُضيف عند الاستلام):
  • /order و /order_check ديمو-فقط + يحترمان kill_switch (في mt5_client).
  • /order يقبل توكناً اختيارياً: لو RB_ORDER_TOKEN مضبوط في البيئة، الطلب بلا توكن صحيح يُرفض
    (يمنع أيّ جهاز على الشبكة من فتح صفقات).
  • /scan يُرفق قناعة FRIDAY الحقيقية (deep_conviction) لكل رمز بجانب ثقة EMA الحتميّة.
"""
import os
import sys
import asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

load_dotenv()
import mt5_client as mt5c
import scanner
import claude_confirm

# قناعة FRIDAY الحقيقية (فيتو Bonferroni/تكلفة) — best-effort من جذر المشروع
sys.path.insert(0, r"C:\Users\Radhi\MT5")
try:
    import deep_conviction as dc
except Exception:
    dc = None
try:
    import analysis as smc_analysis      # SMC لحظيّ (BOS/OB/CHoCH/FVG/سيولة) + ربط عقل المشروع
except Exception:
    smc_analysis = None

DEFAULT_TFS = ["M1", "M5", "M15", "H1", "H4"]   # M1 مُضاف — تحليل لحظيّ
HERE = os.path.dirname(os.path.abspath(__file__))
RB_ORDER_TOKEN = os.getenv("RB_ORDER_TOKEN", "")        # لو مضبوط، يُطلب توكن لتنفيذ الأوامر


def watch_symbols():
    raw = os.getenv("SCAN_SYMBOLS", "XAUUSDm,EURUSD,GBPUSD,USDJPY")
    return [s.strip() for s in raw.split(",") if s.strip()]


app = FastAPI(title="R Bridge")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    mt5c.start_background_connect()        # غير حاجب — uvicorn يربط فوراً ويخدم؛ MT5 يتصل بالخلفية
    print("[MT5] background connect started")


@app.on_event("shutdown")
def stop():
    mt5c.shutdown()


@app.get("/")
def index():
    # بلا تخزين — الجوال يجلب أحدث نسخة دائماً (حلّ مشكلة الصفحة المخزّنة القديمة)
    return FileResponse(os.path.join(HERE, "index.html"),
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate",
                                 "Pragma": "no-cache", "Expires": "0"})


@app.get("/health")
def health():
    ok, msg = mt5c.ensure()
    return {"ok": ok, "mt5": msg, "demo": mt5c.is_demo() if ok else None,
            "order_token_required": bool(RB_ORDER_TOKEN)}


@app.get("/account")
def get_account():
    mt5c.ensure()
    return mt5c.account() or {"error": "لا يوجد حساب متصل"}


@app.get("/symbols")
def get_symbols():
    mt5c.ensure()
    return {"symbols": mt5c.list_symbols(only_watch=watch_symbols())}


def _friday_conviction(sym, direction):
    """قناعة FRIDAY الحقيقية للرمز/الاتجاه (mult, tier, ok). محايد لو غير متاح."""
    if dc is None or direction not in ("BUY", "SELL"):
        return None
    try:
        mult, tier, ok = dc.conviction(sym, direction)
        return {"mult": round(float(mult), 2), "tier": tier, "veto": (not ok)}
    except Exception:
        return None


@app.get("/scan")
def get_scan(tfs: str = "", symbols: str = ""):
    mt5c.ensure()
    tf_list = [t.strip() for t in tfs.split(",") if t.strip()] or DEFAULT_TFS
    syms = [s.strip() for s in symbols.split(",") if s.strip()] or watch_symbols()
    rows = scanner.scan_all(syms, tf_list)
    for r in rows:                                       # أرفِق قناعة FRIDAY + ملخّص SMC على M1
        fc = _friday_conviction(r.get("symbol"), r.get("direction"))
        if fc:
            r["friday"] = fc
        if smc_analysis is not None:
            s = smc_analysis.smc(r.get("symbol"), "M1")
            r["m1"] = {k: s.get(k) for k in ("trend", "bos", "choch", "ob", "fvg", "sweep", "momentum") if s.get(k)}
            p = smc_analysis.position(r.get("symbol"))
            if p:
                r["position"] = p
    return {"tfs": tf_list, "rows": rows,
            "note": "الثقة = ترتيب EMA حتميّ للعرض (~50% بعد التكلفة، ليست حافّة). 'friday'=قناعة المشروع، 'm1'=SMC لحظيّ، 'position'=مركز مفتوح."}


@app.get("/analyze")
def get_analyze(symbol: str, tfs: str = ""):
    """تحليل احترافيّ كامل لرمز: SMC لكل فريم (M1+) + عقل المشروع المنفّذ + المركز المفتوح."""
    mt5c.ensure()
    if not symbol:
        return {"error": "symbol مطلوب"}
    if smc_analysis is None:
        return {"error": "وحدة التحليل غير متاحة"}
    tf_list = [t.strip() for t in tfs.split(",") if t.strip()] or ["M1", "M5", "M15", "H1"]
    return smc_analysis.analyze(symbol, tf_list)


@app.get("/candles")
def get_candles(symbol: str, tf: str = "H1", count: int = 200):
    mt5c.ensure()
    candles = mt5c.rates(symbol, tf, count)
    overlay = {}
    if smc_analysis is not None:                          # طبقات SMC للرسم فوق الشموع
        try:
            s = smc_analysis.smc(symbol, tf)
            f = smc_analysis.friday(symbol) or {}
            def _lvl(x):                                   # nearest_above/below = [نوع, سعر] → السعر
                if isinstance(x, (list, tuple)) and len(x) > 1 and isinstance(x[1], (int, float)):
                    return x[1]
                return x if isinstance(x, (int, float)) else None
            overlay = {"ob_zone": s.get("ob_zone"), "fvg_zone": s.get("fvg_zone"),
                       "trend": s.get("trend"), "bos": s.get("bos"), "choch": s.get("choch"),
                       "sr": [_lvl(f.get("nearest_above")), _lvl(f.get("nearest_below"))]}
            pl = smc_analysis.setup(symbol, tf)            # خطّة الإعداد لرسمها على الشارت
            if pl.get("valid"):
                overlay["plan"] = {"direction": pl["direction"], "entry": pl["entry"], "stop": pl["stop"],
                                   "targets": pl["targets"], "golden_zone": pl["golden_zone"]}
        except Exception:
            pass
    return {"symbol": symbol, "tf": tf, "candles": candles, "overlay": overlay}


@app.post("/confirm")
def post_confirm(payload: dict):
    # التوكن مرفوع عن التأكيد (قراءة فقط)؛ يبقى على /order (التنفيذ) لحماية الصفقات.
    mt5c.ensure()
    symbol = payload.get("symbol")
    tf_list = payload.get("tfs") or DEFAULT_TFS
    if not symbol:
        return {"error": "symbol مطلوب"}
    return claude_confirm.confirm(symbol, tf_list)


@app.post("/order_check")
def post_order_check(payload: dict):
    mt5c.ensure()
    symbol = payload.get("symbol"); side = payload.get("side"); volume = payload.get("volume")
    if not symbol or side not in ("BUY", "SELL") or not volume:
        return {"error": "symbol/side/volume مطلوبة"}
    return mt5c.order_check(symbol, side, float(volume))


@app.post("/order")
def post_order(payload: dict):
    mt5c.ensure()
    if RB_ORDER_TOKEN and payload.get("token") != RB_ORDER_TOKEN:
        return {"error": "🛑 توكن غير صحيح — التنفيذ مرفوض"}
    symbol = payload.get("symbol")
    side = payload.get("side")
    volume = payload.get("volume")
    if not symbol or side not in ("BUY", "SELL") or not volume:
        return {"error": "symbol/side/volume مطلوبة"}
    return mt5c.market_order(symbol, side, float(volume),
                             payload.get("sl"), payload.get("tp"))


@app.get("/pendings")
def get_pendings():
    mt5c.ensure()
    return {"pendings": mt5c.pendings()}


@app.post("/pending")
def post_pending(payload: dict):
    mt5c.ensure()
    if RB_ORDER_TOKEN and payload.get("token") != RB_ORDER_TOKEN:
        return {"error": "🛑 توكن غير صحيح — الأمر مرفوض"}
    symbol = payload.get("symbol"); otype = payload.get("otype"); price = payload.get("price")
    volume = payload.get("volume")
    if not symbol or not otype or not price or not volume:
        return {"error": "symbol/otype/price/volume مطلوبة"}
    return mt5c.pending_order(symbol, otype, float(price), float(volume),
                              payload.get("sl"), payload.get("tp"))


@app.post("/pending_cancel")
def post_pending_cancel(payload: dict):
    mt5c.ensure()
    if RB_ORDER_TOKEN and payload.get("token") != RB_ORDER_TOKEN:
        return {"error": "🛑 توكن غير صحيح"}
    if not payload.get("ticket"):
        return {"error": "ticket مطلوب"}
    return mt5c.cancel_pending(payload["ticket"])


@app.websocket("/stream")
async def stream(ws: WebSocket):
    await ws.accept()
    symbols = watch_symbols()
    try:
        try:
            init = await asyncio.wait_for(ws.receive_json(), timeout=2)
            if isinstance(init, dict) and init.get("symbols"):
                symbols = init["symbols"]
        except Exception:
            pass

        while True:
            mt5c.ensure()
            ticks = [mt5c.tick(s) for s in symbols]
            await ws.send_json({"ticks": [t for t in ticks if t]})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return

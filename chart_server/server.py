# -*- coding: utf-8 -*-
"""chart_server/server.py — لوحة الشارت الحيّة (طلب المستخدم: الشارت الاحترافيّ كصفحةٍ تتحدّث لحظياً
لا صورةً لمرّة واحدة). FastAPI على المنفذ 8016. يقرأ شموع MT5 ويرسم المستويات الهندسيّة من level_map
(قمّة/قاع الأمس، البايفوت، فيبوناتشي، جان/مربّع التسعة، نجمة داوود، الفراكتلات، VWAP/POC) + مناطق
الالتقاء، ويرجعها JSON ⇒ ترسمها index.html على كانفاس شموعٍ احترافيّ، يُحدَّث كلّ 10ث.

نافذة-آمن (pythonw بلا stdout): نعيد توجيه stdout/stderr لملفّ سجلّ **قبل** uvicorn.
نسخة-مفردة: engine_lock.claim('chart_server') (منفذ القفل 8746).
تشغيل (نافذة): pythonw.exe chart_server\\server.py   |   أو: python -m uvicorn chart_server.server:app --port 8016
"""
from __future__ import annotations
import sys, os
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
LOG = MT5DIR / "data" / "chart_server.log"

# نافذة-آمن: أعِد توجيه stdout/stderr لملفّ سجلّ قبل أيّ طباعة/uvicorn (pythonw بلا stdout ⇒ تعطّل)
try:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    _lf = open(LOG, "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf
    sys.stderr = _lf
except Exception:
    pass

# اجعل جذر المشروع على المسار كي نستورد level_map / engine_lock / momentum_harvester
if str(MT5DIR) not in sys.path:
    sys.path.insert(0, str(MT5DIR))

import json
import threading
import datetime as _dt
import urllib.request as _urlreq

import MetaTrader5 as mt5
from fastapi import FastAPI, Query, Body
from fastapi.responses import JSONResponse, HTMLResponse, Response

import level_map

# «Index Chart» الحيّ للذهب وسلّته (وحدة منفصلة لإبقاء هذا الملفّ رشيقاً)
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import index_chart as _index_chart
except Exception:
    _index_chart = None
try:
    import pulse_chart as _pulse_chart      # 🫀 نبض السوق (كل العملات — قراءة ملفّات فقط)
except Exception:
    _pulse_chart = None
try:
    import pro_chart as _pro_chart          # 🎛️ قمرة الشارتات الاحترافيّة (Index + D1/H4/H1 + SMC/POC)
except Exception:
    _pro_chart = None

# اتّجاه D1: أعد استخدام momentum_harvester._trend إن أمكن، وإلّا احسب اتّجاه D1 بسيط محلياً
try:
    from momentum_harvester import _trend as _mh_trend  # type: ignore
except Exception:
    _mh_trend = None

# ── واجهات قراءة-فقط لتحويل الشارت من زينةٍ لقمرةِ قيادة (cockpit) ──
# كلٌّ ملفوف بـ try/except عند الاستعمال؛ غيابُ أيّ وحدةٍ لا يكسر النقطة النهائيّة.
try:
    import chart_read as _chart_read            # ~35 مؤشّراً حيّاً (votes/net/dir/confluence)
except Exception:
    _chart_read = None
try:
    import deep_conviction as _deep_conviction   # رؤية العقل/الجين (mult, tier, ok)
except Exception:
    _deep_conviction = None
try:
    import engine_gov as _engine_gov             # حوكمة المايسترو (paused/mults)
except Exception:
    _engine_gov = None

# خريطة المجيك ⇒ اسم المحرّك (لرسم خطوط دخولنا مُعنونةً على الشارت)
_MAGIC_NAME = {
    20260608: "multi_trader", 20260618: "army_warroom", 20260628: "gold_scalper",
    20260612: "tournament", 20260616: "orb", 20260629: "pipflow_core",
    20260630: "momentum_harvester", 20260605: "brain_server", 20260614: "news_gene",
    20260617: "legacy_20260617",
}

HERE = Path(__file__).resolve().parent
INDEX = HERE / "index.html"

# خرائط الفريمات الزمنيّة المدعومة
_TF = {
    "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

app = FastAPI(title="FRIDAY Chart Server")

_ready = False
_lock = threading.Lock()      # MT5 ليس thread-safe — نحرس كلّ النداءات


def _mt5():
    global _ready
    if not _ready:
        _ready = bool(mt5.initialize())
    return _ready


def _simple_trend(sym):
    """اتّجاه D1 بسيط (بديل عند تعذّر استيراد momentum_harvester): إغلاق اليوم مقابل متوسّط 20-يوم."""
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 22)
    if r is None or len(r) < 21:
        return 0
    c = r["close"]
    sma = sum(float(c[-i]) for i in range(1, 21)) / 20.0
    price = float(c[-1])
    if price > sma:
        return 1
    if price < sma:
        return -1
    return 0


def _trend(sym):
    if _mh_trend is not None:
        try:
            d = _mh_trend(sym)
            if d:                      # 0 = حياديّ ⇒ اسقط لاتّجاه D1 البسيط لرسم الفيبو/جان
                return d
        except Exception:
            pass
    return _simple_trend(sym) or 1


def _vwap_poc(sym, tf):
    """VWAP (السعر النموذجيّ مرجّحٌ بالحجم) + POC (نقطة التحكّم: السعر الأكثر تداولاً عبر حجم-بالسعر).
    حجم MT5 tick_volume تقريبيّ لكنّه يكفي للسياق."""
    r = mt5.copy_rates_from_pos(sym, tf, 0, 200)
    if r is None or len(r) < 5:
        return {}
    out = {}
    tp = [(float(x["high"]) + float(x["low"]) + float(x["close"])) / 3.0 for x in r]
    vol = [float(x["tick_volume"]) or 1.0 for x in r]
    tv = sum(vol)
    if tv > 0:
        out["VWAP"] = sum(tp[i] * vol[i] for i in range(len(r))) / tv
    # POC: نقسم المدى لـ50 حزمة ونجمع الحجم في كلّ حزمة، الأعلى = POC
    lo = min(float(x["low"]) for x in r)
    hi = max(float(x["high"]) for x in r)
    if hi > lo:
        nb = 50
        bw = (hi - lo) / nb
        buckets = [0.0] * nb
        for i, x in enumerate(r):
            mid = (float(x["high"]) + float(x["low"])) / 2.0
            b = min(nb - 1, max(0, int((mid - lo) / bw)))
            buckets[b] += vol[i]
        bi = max(range(nb), key=lambda k: buckets[k])
        out["POC"] = lo + (bi + 0.5) * bw
    return out


# ── إثراءات قمرة القيادة (cockpit) — كلٌّ معزولٌ، يُرجِع null/[] عند الفشل، لا يكسر أبداً ──

def _enrich_live(sym, dig):
    """لقطة السوق الحيّة: السعر الوسطيّ + bid/ask + السبريد + الطابع الزمنيّ."""
    try:
        tk = mt5.symbol_info_tick(sym)
        if not tk or not tk.bid or not tk.ask:
            return None
        return {
            "price": round((tk.ask + tk.bid) / 2.0, dig),
            "bid": round(float(tk.bid), dig),
            "ask": round(float(tk.ask), dig),
            "spread": round(float(tk.ask - tk.bid), dig),
            "ts": int(getattr(tk, "time", 0)) or None,
        }
    except Exception as e:
        print(f"[chart] live({sym}) failed: {e}", flush=True)
        return None


def _enrich_indicators(sym, tf_name):
    """مؤشّراتنا الـ~35 حيّةً عبر chart_read.read_local: {dir, confluence, net, votes}."""
    if _chart_read is None:
        return None
    try:
        d = _chart_read.read_local(mt5, sym, tf_name.upper())
        if not d:
            return None
        return {
            "dir": d.get("dir"),
            "confluence": d.get("confluence"),
            "net": d.get("net"),
            "regime": d.get("regime"),
            "votes": d.get("votes") or {},
        }
    except Exception as e:
        print(f"[chart] indicators({sym}) failed: {e}", flush=True)
        return None


def _enrich_signal(sym, direction, proj, zones):
    """إشارة التداول: زخم TSM البطيء + الهدف التالي + أقوى منطقة التقاء."""
    out = {"tsm_trend": None, "next_target": None, "top_confluence": None}
    try:
        out["tsm_trend"] = _trend(sym)
    except Exception as e:
        print(f"[chart] tsm_trend({sym}) failed: {e}", flush=True)
    try:
        nxt = proj.get("next") if proj else None
        if nxt:
            out["next_target"] = {"label": nxt[0], "v": nxt[1]}
    except Exception as e:
        print(f"[chart] next_target({sym}) failed: {e}", flush=True)
    try:
        if zones:
            z = zones[0]   # confluence_zones مرتّبة بالقوّة تنازليّاً
            out["top_confluence"] = {
                "center": z.get("center"), "strength": z.get("strength"),
                "labels": z.get("labels", []),
            }
    except Exception as e:
        print(f"[chart] top_confluence({sym}) failed: {e}", flush=True)
    return out


def _enrich_conviction(sym):
    """رؤية العقل العميق/الجين: قناعة الشراء والبيع (tier + ok + mult)."""
    if _deep_conviction is None:
        return None
    out = {}
    for side in ("BUY", "SELL"):
        try:
            mult, tier, ok = _deep_conviction.conviction(sym, side)
            out[side.lower()] = {"mult": round(float(mult), 3), "tier": tier, "ok": bool(ok)}
        except Exception as e:
            print(f"[chart] conviction({sym},{side}) failed: {e}", flush=True)
            out[side.lower()] = None
    return out


def _enrich_positions(sym, dig):
    """صفقاتنا المفتوحة على هذا الرمز (لرسم خطوط دخولنا): مجمّعة بالمجيك/الاتجاه."""
    try:
        pos = mt5.positions_get(symbol=sym)
        if not pos:
            return []
        # تجميع بالمجيك+الاتجاه ⇒ متوسّط دخولٍ مرجّحٌ باللوت + صافي عائم
        agg = {}
        for p in pos:
            try:
                magic = int(getattr(p, "magic", 0))
                side = "BUY" if int(getattr(p, "type", 0)) == 0 else "SELL"
                lots = float(getattr(p, "volume", 0.0))
                entry = float(getattr(p, "price_open", 0.0))
                net = float(getattr(p, "profit", 0.0)) + float(getattr(p, "swap", 0.0))
                key = (magic, side)
                a = agg.setdefault(key, {"lots": 0.0, "wsum": 0.0, "net": 0.0})
                a["lots"] += lots
                a["wsum"] += entry * lots
                a["net"] += net
            except Exception:
                continue
        out = []
        for (magic, side), a in agg.items():
            lots = a["lots"]
            avg = (a["wsum"] / lots) if lots > 0 else 0.0
            out.append({
                "magic": magic,
                "engine": _MAGIC_NAME.get(magic, "manual" if magic == 0 else f"magic_{magic}"),
                "side": side,
                "avg_entry": round(avg, dig),
                "lots": round(lots, 2),
                "net": round(a["net"], 2),
            })
        out.sort(key=lambda r: (-abs(r["net"])))
        return out
    except Exception as e:
        print(f"[chart] positions({sym}) failed: {e}", flush=True)
        return []


def _enrich_governance():
    """حوكمة المايسترو: المجيكات المُقالة (لا تفتح صفقاتٍ جديدة) + ملاحظة."""
    if _engine_gov is None:
        return None
    try:
        paused = sorted(int(m) for m in _engine_gov._C.get("paused", set())) \
            if isinstance(getattr(_engine_gov, "_C", None), dict) else []
        # أجبر التحديث ثمّ اقرأ المجموعة المُحدّثة
        try:
            _engine_gov._refresh()
            paused = sorted(int(m) for m in _engine_gov._C.get("paused", set()))
        except Exception:
            pass
        return {
            "paused": paused,
            "paused_named": [{"magic": m, "engine": _MAGIC_NAME.get(m, f"magic_{m}")} for m in paused],
            "note": "المجيكات المُقالة تدير القائم فقط — لا تفتح جديداً (نزّاف كارثيّ).",
        }
    except Exception as e:
        print(f"[chart] governance failed: {e}", flush=True)
        return None


def _chart_payload(sym, tf_name):
    """منطق /chart: شموع + مستويات + التقاء + سعر + اتّجاه. قراءة-فقط."""
    if not _mt5():
        return {"error": "mt5_init_failed", "symbol": sym}
    tf = _TF.get(tf_name.upper(), mt5.TIMEFRAME_H1)
    info = mt5.symbol_info(sym)
    if info is None:
        # حاول إظهار الرمز في مراقب السوق
        mt5.symbol_select(sym, True)
        info = mt5.symbol_info(sym)
    if info is None:
        return {"error": "unknown_symbol", "symbol": sym}
    dig = info.digits

    rates = mt5.copy_rates_from_pos(sym, tf, 0, 160)
    candles = []
    if rates is not None:
        for x in rates:
            candles.append({
                "t": int(x["time"]),
                "o": round(float(x["open"]), dig),
                "h": round(float(x["high"]), dig),
                "l": round(float(x["low"]), dig),
                "c": round(float(x["close"]), dig),
            })

    direction = _trend(sym)
    proj = None
    levels = []
    try:
        proj = level_map.project(sym, direction)
    except Exception as e:
        proj = None
        print(f"[chart] project({sym}) failed: {e}", flush=True)
    if proj and proj.get("all"):
        for lbl, v in proj["all"].items():
            if v:
                levels.append({"label": lbl, "v": round(float(v), dig)})

    # VWAP + POC (مصدران لا يأتيان من level_map.project)
    try:
        vp = _vwap_poc(sym, tf)
        for lbl, v in vp.items():
            levels.append({"label": lbl, "v": round(float(v), dig)})
    except Exception as e:
        print(f"[chart] vwap_poc({sym}) failed: {e}", flush=True)

    confluence = []
    zones = []
    try:
        zones = level_map.confluence_zones(sym) or []
        for z in zones:
            confluence.append({
                "center": z["center"], "lo": z["lo"], "hi": z["hi"],
                "strength": z["strength"], "n": z["n"],
                "labels": z["labels"],
            })
    except Exception as e:
        print(f"[chart] confluence({sym}) failed: {e}", flush=True)

    tk = mt5.symbol_info_tick(sym)
    price = round((tk.ask + tk.bid) / 2.0, dig) if tk else (proj["price"] if proj else None)

    out = {
        "symbol": sym, "tf": tf_name.upper(), "digits": dig,
        "price": price, "trend": direction,
        "candles": candles, "levels": levels, "confluence": confluence,
        "ts": _dt.datetime.utcnow().isoformat() + "Z",
    }

    # ── الإثراءات (cockpit) — كلٌّ معزولٌ، يُرجِع null/[] عند الفشل، لا يكسر الشموع أبداً ──
    try:
        out["live"] = _enrich_live(sym, dig)
    except Exception as e:
        out["live"] = None; print(f"[chart] live wrap failed: {e}", flush=True)
    try:
        out["indicators"] = _enrich_indicators(sym, tf_name)
    except Exception as e:
        out["indicators"] = None; print(f"[chart] indicators wrap failed: {e}", flush=True)
    try:
        out["signal"] = _enrich_signal(sym, direction, proj, zones)
    except Exception as e:
        out["signal"] = None; print(f"[chart] signal wrap failed: {e}", flush=True)
    try:
        out["conviction"] = _enrich_conviction(sym)
    except Exception as e:
        out["conviction"] = None; print(f"[chart] conviction wrap failed: {e}", flush=True)
    try:
        out["positions"] = _enrich_positions(sym, dig)
    except Exception as e:
        out["positions"] = []; print(f"[chart] positions wrap failed: {e}", flush=True)
    try:
        out["governance"] = _enrich_governance()
    except Exception as e:
        out["governance"] = None; print(f"[chart] governance wrap failed: {e}", flush=True)

    return out


def _symbol_list():
    """قائمة الرموز القابلة للتداول (المرئيّة في مراقب السوق أولاً، الذهب أوّلاً)."""
    if not _mt5():
        return ["XAUUSDm"]
    syms = mt5.symbols_get() or []
    names = [s.name for s in syms if getattr(s, "visible", True)]
    if not names:
        names = [s.name for s in syms]
    # الذهب أوّلاً (XAUUSD تحديداً ثمّ بقيّة أزواج الذهب)، ثمّ BTC/ETH، ثمّ الباقي أبجدياً
    def _key(n):
        u = n.upper()
        if u.startswith("XAUUSD"):
            return (0, u)
        if "XAU" in u:
            return (1, u)
        if "BTCUSD" in u:
            return (2, u)
        if "ETHUSD" in u:
            return (3, u)
        if "BTC" in u:
            return (4, u)
        return (5, u)
    names = sorted(set(names), key=_key)
    return names[:120]


@app.get("/symbols")
def symbols():
    with _lock:
        try:
            return JSONResponse({"symbols": _symbol_list()})
        except Exception as e:
            return JSONResponse({"symbols": ["XAUUSDm"], "error": str(e)})


@app.get("/chart")
def chart(sym: str = Query("XAUUSDm"), tf: str = Query("H1")):
    with _lock:
        try:
            return JSONResponse(_chart_payload(sym, tf))
        except Exception as e:
            return JSONResponse({"error": str(e), "symbol": sym}, status_code=200)


# ── 📺 لوحة تزامن وكيل اليوتيوب ↔ القناة (طلب المستخدم: «ورني كيف يشوف اليوتيوب ويدخل معه») ──
_RN_YT = MT5DIR / "data" / "r_native"

_YT_HTML = """<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>تزامن اليوتيوب ↔ القناة</title>
<style>
 body{margin:0;background:#0b0f17;color:#e6edf3;font-family:'Segoe UI',Tahoma,sans-serif;padding:14px}
 h1{font-size:18px;margin:0 0 12px;display:flex;gap:10px;align-items:center}
 .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;max-width:780px}
 .card{background:#131a26;border:1px solid #233044;border-radius:14px;padding:16px}
 .lbl{color:#8b97a8;font-size:13px;margin-bottom:8px}
 .badge{font-size:34px;font-weight:800;letter-spacing:1px}
 .buy{color:#34d399}.sell{color:#f87171}.muted{color:#8b97a8}
 .bar{height:10px;background:#233044;border-radius:6px;overflow:hidden;margin:10px 0 6px}
 .bar>i{display:block;height:100%;border-radius:6px;transition:width .4s}
 .status{max-width:780px;margin:12px 0;padding:14px 16px;border-radius:12px;background:#0e1622;border:1px solid #233044;font-size:16px;font-weight:600}
 .how{max-width:780px;background:#0e1622;border:1px dashed #2b3a52;border-radius:12px;padding:12px 16px;color:#b9c4d4;font-size:13px;line-height:1.8;margin-bottom:12px}
 .feed{max-width:780px;background:#0b1019;border:1px solid #233044;border-radius:12px;padding:10px 14px;font-family:Consolas,monospace;font-size:12.5px;color:#9fb0c4;max-height:240px;overflow:auto;direction:ltr;text-align:left}
 .feed div{padding:3px 0;border-bottom:1px solid #161e2b}
 .live{color:#34d399;font-size:12px}
</style></head><body>
<h1>📺 تزامن وكيل اليوتيوب ↔ القناة (الذهب) <span class="live" id="live">● حيّ</span></h1>
<div class="grid">
 <div class="card"><div class="lbl">📡 القناة تقول الآن (Current Position)</div>
  <div class="badge muted" id="ch">—</div>
  <div class="bar"><i id="agbar" style="width:0%;background:#8b97a8"></i></div>
  <div class="muted" id="agtxt">اتّفاق —/10</div>
  <div class="muted" id="trend" style="margin-top:6px"></div></div>
 <div class="card"><div class="lbl">🤖 الوكيل</div>
  <div class="badge muted" id="ag">—</div>
  <div id="poslist" style="font-size:13px;margin-top:8px" class="muted"></div></div>
</div>
<div class="status" id="st">…</div>
<div class="how"><b>كيف يدخل مع القناة:</b> يقرأ اللوحة بصرياً كل ~20ث. حين تصبح <b>Current Position</b> قويّة
 (اتّفاق <b>≥7 من 10</b> مؤطّرات) ⇒ يدخل <b>سوقاً فورياً</b> بنفس اتجاه القناة (لوت ثابت) بأهدافٍ متدرّجة عند
 مستويات السيولة. أقلّ من 7 ⇒ ينتظر. لو عكست القناة ⇒ يُغلق ويعكس معها.</div>
<div class="lbl" style="max-width:780px">🔎 ما يراه الوكيل لحظياً (آخر القراءات — تتحدّث كل ~20ث):</div>
<div class="feed" id="feed"></div>
<script>
async function tick(){
 try{
  const d=await (await fetch('/youtube/data')).json(); const s=d.status||{};
  const ch=document.getElementById('ch'), dir=s.channel_says;
  ch.textContent=dir?(dir==='buy'?'BUY ▲':'SELL ▼'):'—';
  ch.className='badge '+(dir==='buy'?'buy':dir==='sell'?'sell':'muted');
  const ag=s.agree||0,tot=s.total||10,need=(d.cfg&&d.cfg.min_mtf_agree)||7;
  const bar=document.getElementById('agbar'); bar.style.width=Math.round(ag/tot*100)+'%';
  bar.style.background=(ag>=need)?'#34d399':'#eab308';
  document.getElementById('agtxt').textContent='اتّفاق '+ag+'/'+tot+(s.strong?' — قويّة ✓':' — ضعيفة');
  document.getElementById('trend').textContent='ترند: '+(s.trend||'—');
  const agent=document.getElementById('ag'), inT=s.agent_in_trade;
  agent.textContent=inT?(inT==='buy'?'في شراء ▲':'في بيع ▼'):'ينتظر ⏳';
  agent.className='badge '+(inT==='buy'?'buy':inT==='sell'?'sell':'muted');
  const pl=(d.positions||[]).map(p=>'<div>'+(p.dir==='buy'?'شراء':'بيع')+' '+p.lot+' لوت @ '+p.open+' · عائم $'+p.pnl+'</div>').join('');
  document.getElementById('poslist').innerHTML=pl||'<span class=muted>لا صفقة مفتوحة</span>';
  document.getElementById('st').textContent=s.status||'…';
  document.getElementById('feed').innerHTML=(d.recent||[]).slice().reverse().map(l=>'<div>'+l.replace(/</g,'&lt;')+'</div>').join('');
  document.getElementById('live').textContent='● حيّ '+new Date().toLocaleTimeString();
 }catch(e){document.getElementById('live').textContent='● انقطاع';}
}
tick(); setInterval(tick,3000);
</script></body></html>"""


@app.get("/youtube/data")
def youtube_data():
    out = {"status": None, "positions": [], "recent": [], "cfg": {}}
    try:
        out["status"] = json.loads((_RN_YT / "youtube_live_status.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        c = json.loads((MT5DIR / "youtube_analyst_config.json").read_text(encoding="utf-8"))
        out["cfg"] = {"mode": c.get("mode"), "min_mtf_agree": c.get("min_mtf_agree"),
                      "fixed_lot": c.get("fixed_lot"), "symbol": c.get("stream_symbol")}
    except Exception:
        pass
    try:
        with _lock:
            poss = mt5.positions_get() or []
        for p in poss:
            if p.magic == 20260631:
                out["positions"].append({"dir": "buy" if p.type == 0 else "sell", "lot": p.volume,
                                         "open": p.price_open, "sl": p.sl, "tp": p.tp, "pnl": round(p.profit, 2)})
    except Exception:
        pass
    try:
        lines = (_RN_YT / "youtube_analyst.log").read_text(encoding="utf-8", errors="ignore").splitlines()
        out["recent"] = [l for l in lines if any(k in l for k in ("👁️", "✅", "🔄", "🎯", "🔒"))][-9:]
    except Exception:
        pass
    return JSONResponse(out)


@app.get("/youtube")
def youtube_page():
    return HTMLResponse(_YT_HTML)


# ── 🤖 محلّل Fable: تقرير + زرّ حلّل الآن + اسأل الشارت ──
_AN_REPORT = MT5DIR / "data" / "r_native" / "llm_analyst_report.json"
_AN_FLAG = MT5DIR / "data" / "r_native" / "llm_analyst_request.flag"
_AN_CLAUDE = r"C:\Users\Radhi\.local\bin\claude.exe"
_AN_ASK_LOCK = threading.Lock()          # سؤالٌ واحد متزامن (حماية التوكنز عبر النفق العامّ)
_AN_ASK_TIMES: list = []                 # سقف 20 سؤالاً/ساعة


@app.get("/analyst/data")
def analyst_data():
    try:
        return JSONResponse(json.loads(_AN_REPORT.read_text(encoding="utf-8")))
    except Exception:
        return JSONResponse({"error": "لا تقرير بعد — المحلّل يعمل أو لم يبدأ"})


@app.post("/council/refresh")
def council_refresh():
    try:
        (MT5DIR / "data" / "r_native" / "ai_council_request.flag").write_text(
            str(_dt.datetime.now()), encoding="utf-8")
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/analyst/refresh")
def analyst_refresh():
    try:
        _AN_FLAG.write_text(str(_dt.datetime.now()), encoding="utf-8")
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/analyst/ask")
def analyst_ask(payload: dict = Body(...)):
    q = str((payload or {}).get("q") or "").strip()[:500]
    if not q:
        return JSONResponse({"error": "سؤالٌ فارغ"})
    import time as _t
    now = _t.time()
    _AN_ASK_TIMES[:] = [t for t in _AN_ASK_TIMES if now - t < 3600]
    if len(_AN_ASK_TIMES) >= 20:
        return JSONResponse({"error": "بلغنا سقف الأسئلة (20/ساعة) — لحماية التوكنز"})
    if not _AN_ASK_LOCK.acquire(blocking=False):
        return JSONResponse({"error": "سؤالٌ آخر قيد المعالجة — لحظة"})
    try:
        _AN_ASK_TIMES.append(now)
        ctx = []
        for f, tag in ((MT5DIR / "data/r_native/quant_desk.json", "مكتب الحسابات"),
                       (_AN_REPORT, "آخر تقرير")):
            try:
                raw = f.read_text(encoding="utf-8")
                ctx.append(f"[{tag}] {raw[:2600]}")
            except Exception:
                pass
        try:
            mp = json.loads((MT5DIR / "data/r_native/market_pulse.json").read_text(encoding="utf-8"))
            g = (mp.get("symbols") or {}).get("XAUUSDm") or {}
            g.pop("candles_m5", None); g.pop("spark", None)
            ctx.append("[نبض الذهب] " + json.dumps(g, ensure_ascii=False)[:2200])
        except Exception:
            pass
        prompt = ("أنت محلّل أسواقٍ محترف على منصّة FRIDAY. أجب بالعربيّة بإيجازٍ ودقّة (<=150 كلمة) "
                  "اعتماداً على السياق الحيّ أدناه فقط — لا تختلق أرقاماً، وإن سُئلت عن توقّعٍ فأطّر سيناريوهات "
                  "بشروط إبطالٍ ولا تدّعِ يقيناً.\n\n=== السياق الحيّ ===\n" + "\n".join(ctx) +
                  f"\n\n=== سؤال المتداول ===\n{q}")
        import subprocess as _sp
        r = _sp.run([_AN_CLAUDE, "-p", prompt, "--model", "claude-fable-5",
                     "--output-format", "text"],
                    capture_output=True, text=True, timeout=90, encoding="utf-8", errors="ignore",
                    creationflags=0x08000000)   # CREATE_NO_WINDOW: لا وميض نوافذ
        ans = (r.stdout or "").strip()
        if not ans:
            return JSONResponse({"error": f"لا إجابة (rc={r.returncode})"})
        return JSONResponse({"answer": ans[:4000]})
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"})
    finally:
        _AN_ASK_LOCK.release()


@app.get("/timer")
def news_timer():
    """⏰ مؤقّت عدٍّ تنازليّ عملاق لأقرب خبر (طلب المستخدم قبل NFP)."""
    return HTMLResponse("""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>⏰ عدّاد الخبر</title>
<style>body{margin:0;background:radial-gradient(800px 500px at 50% 30%,#1a2030,#0b0e13);color:#e6e9ef;
font-family:'Segoe UI',Tahoma;display:flex;flex-direction:column;align-items:center;justify-content:center;
min-height:100vh;text-align:center}
#title{font-size:clamp(16px,3vw,28px);color:#9aa3b2;margin-bottom:8px}
#clock{font-size:clamp(60px,16vw,200px);font-weight:800;font-variant-numeric:tabular-nums;
color:#f5c518;text-shadow:0 0 40px rgba(245,197,24,.35);direction:ltr}
#clock.hot{color:#ff5c5c;text-shadow:0 0 60px rgba(255,92,92,.6);animation:p .8s infinite}
@keyframes p{50%{opacity:.55}}
#sub{font-size:clamp(12px,2vw,18px);color:#9aa3b2;margin-top:10px}
#events{margin-top:24px;font-size:clamp(11px,1.6vw,15px);color:#7a8090;line-height:2}</style></head><body>
<div id="title">—</div><div id="clock">--:--:--</div><div id="sub"></div><div id="events"></div>
<script>
let EV=[];
async function load(){try{const r=await fetch('/pro/data?sym=XAUUSDm');const d=await r.json();
EV=(d.news_events||[]).filter(e=>e.epoch*1000>Date.now()-60000).sort((a,b)=>a.epoch-b.epoch);
document.getElementById('events').innerHTML=EV.slice(0,5).map(e=>{
 const t=new Date(e.epoch*1000);return (e.impact==='High'?'🔴':'🟠')+' '+e.title+' — '+t.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})}).join('<br>');
}catch(e){}}
function tick(){if(!EV.length){document.getElementById('title').textContent='لا أخبار قادمة';return}
const e=EV[0],s=Math.max(0,Math.floor(e.epoch-Date.now()/1000));
const h=String(Math.floor(s/3600)).padStart(2,'0'),m=String(Math.floor(s%3600/60)).padStart(2,'0'),x=String(s%60).padStart(2,'0');
const c=document.getElementById('clock');c.textContent=h+':'+m+':'+x;c.className=s<600?'hot':'';
document.getElementById('title').textContent=(e.impact==='High'?'🔴 ':'🟠 ')+e.title;
document.getElementById('sub').textContent='الساعة '+new Date(e.epoch*1000).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})+' بتوقيتك · الآن '+new Date().toLocaleTimeString('en-GB');
if(s===0){EV.shift()}}
load();setInterval(load,30000);setInterval(tick,250);
</script></body></html>""")


@app.get("/pro/data")
def pro_data(sym: str = Query("XAUUSDm")):
    if not _pro_chart:
        return JSONResponse({"error": "pro_chart غير متوفّر"})
    with _lock:
        return JSONResponse(_pro_chart.get_pro_data(sym))


@app.get("/pro")
def pro_page():
    if not _pro_chart:
        return HTMLResponse("<h1>pro_chart غير متوفّر</h1>", status_code=500)
    return HTMLResponse(_pro_chart.PRO_HTML)


# ── 📱 /live — نبض حيّ لحظيّ للجوّال: إجماع الـ90 وكيلاً + الصفقات + الحساب (طلب المستخدم) ──
@app.get("/live/data")
def live_data():
    rn = MT5DIR / "data" / "r_native"
    out = {"ts": _dt.datetime.now().strftime("%H:%M:%S")}
    try:
        c = json.loads((rn / "agent_council.json").read_text(encoding="utf-8"))
        syms = c.get("symbols") or {}
        rows = []
        for s, o in syms.items():
            if not isinstance(o, dict):
                continue
            rows.append({"sym": s, "verdict": o.get("verdict"), "dir": o.get("dir"),
                         "pct": o.get("agreement_pct"), "n": o.get("n_voted"),
                         "buy": o.get("votes_buy"), "sell": o.get("votes_sell"),
                         "gene": str(o.get("gene", ""))[:8], "why": (o.get("top_reasons") or [])[:2]})
        rows.sort(key=lambda r: -(r["pct"] or 0))
        out["council"] = rows
        out["council_age"] = round(_dt.datetime.now().timestamp() - float(c.get("ts", 0)), 0)
    except Exception as e:
        out["council"] = []; out["council_err"] = str(e)
    try:
        st = json.loads((rn / "brain_trader_status.json").read_text(encoding="utf-8"))
        out["exec"] = {"positions": st.get("positions"), "frozen": st.get("frozen"),
                       "pnl_today": st.get("pnl_today"), "risk_pct": st.get("risk_pct"),
                       "satisfaction": st.get("satisfaction"), "floating": st.get("floating")}
    except Exception:
        out["exec"] = {}
    try:
        # 🏆 سبورة المكتب (desk_scoreboard.py يكتبها كل 30ث) — قراءة فاشلة بهدوء ⇒ {}
        b = json.loads((rn / "desk_scoreboard.json").read_text(encoding="utf-8-sig"))
        if not isinstance(b, dict):
            b = {}
        out["board"] = {"updated": b.get("updated"), "magics": b.get("magics") or [],
                        "winners": b.get("winners") or [], "retired": b.get("retired") or []}
    except Exception:
        out["board"] = {}
    try:
        # 🧠 العقل الجماعيّ (fleet_mind.json) — حالة الأسطول + ميزانيّة المخاطرة للجوّال
        fm = json.loads((rn / "fleet_mind.json").read_text(encoding="utf-8-sig"))
        out["fleet"] = {"state": fm.get("fleet_state"), "budget": fm.get("budget_factor"),
                        "fleet_daily": fm.get("fleet_daily")} if isinstance(fm, dict) else {}
    except Exception:
        out["fleet"] = {}
    with _lock:
        try:
            if mt5.terminal_info() is None:
                mt5.initialize()
            a = mt5.account_info()
            if a:
                out["account"] = {"equity": round(a.equity, 2), "balance": round(a.balance, 2),
                                  "margin_level": round(a.margin_level or 0, 0), "server": a.server}
            pos = [p for p in (mt5.positions_get() or []) if p.magic in (20260703, 20260704)]
            prows = []
            for p in pos:
                tk = mt5.symbol_info_tick(p.symbol)
                info = mt5.symbol_info(p.symbol)
                dig = int(info.digits) if info else 2
                cur = float(tk.bid if p.type == 0 else tk.ask) if tk else float(p.price_open)
                prows.append({"sym": p.symbol, "dir": "شراء" if p.type == 0 else "بيع",
                              "lot": p.volume, "pnl": round(p.profit, 2),
                              "mom": "mom" in (p.comment or ""),
                              "entry": round(float(p.price_open), dig), "cur": round(cur, dig),
                              "tp": round(float(p.tp), dig) if p.tp else None,
                              "sl": round(float(p.sl), dig) if p.sl else None, "dig": dig,
                              "to_tp": round(abs(float(p.tp) - cur), dig) if p.tp else None,
                              "to_sl": round(abs(cur - float(p.sl)), dig) if p.sl else None,
                              "secured": p.profit >= 0.30})       # 🌾 أمين الأرباح يتتبّعه
            out["positions"] = prows
        except Exception as e:
            out["account_err"] = str(e)
    return JSONResponse(out)


@app.get("/live")
def live_page():
    return HTMLResponse(_LIVE_HTML)


_LIVE_HTML = """<!doctype html><html lang=ar dir=rtl><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>FRIDAY — حيّ</title>
<style>
*{box-sizing:border-box;margin:0;-webkit-tap-highlight-color:transparent}
body{background:#0b0d12;color:#e6e9ef;font:14px/1.5 system-ui,-apple-system,sans-serif;padding:10px;padding-bottom:40px}
.hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.eq{font-size:26px;font-weight:800}.sub{font-size:12px;color:#7a828f}
.card{background:#12151c;border:1px solid #232833;border-radius:12px;padding:10px;margin-bottom:10px}
.h2{font-size:13px;color:#9aa3b2;margin-bottom:8px;display:flex;justify-content:space-between}
.up{color:#3ddc84}.dn{color:#ff5c6c}.dim{color:#7a828f}.gold{color:#f5c518}
.row{display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid #1c202a;font-size:13px}
.row:first-child{border-top:0}
.sym{width:74px;font-weight:700}.bar{flex:1;height:20px;background:#1a1e27;border-radius:5px;position:relative;overflow:hidden}
.fill{position:absolute;top:0;bottom:0;border-radius:5px;opacity:.85}
.pct{width:44px;text-align:left;direction:ltr;font-weight:700}
.tradeable{box-shadow:0 0 0 1px #3ddc84 inset}
.pos{display:flex;justify-content:space-between;padding:5px 0;border-top:1px solid #1c202a;font-size:13px}
.chip{font-size:10px;padding:1px 7px;border-radius:20px;background:#1c2430;color:#9aa3b2}
.gene{font-size:9px;color:#5a6270;direction:ltr}
</style></head><body>
<div class=hdr><div><div class=eq id=eq>—</div><div class=sub id=acc>يحمّل…</div></div>
<div style=text-align:left><div class=sub id=clk>—</div><div class=sub id=exec>—</div></div></div>
<div class=card><div class=h2><span>🧠 العقل الجماعيّ</span><span class=sub id=fmstate></span></div><div id=fleetline class=dim>—</div></div>
<div class=card><div class=h2><span>🏆 السبورة</span><span class=sub id=bage></span></div><div id=board class=dim>—</div></div>
<div class=card><div class=h2><span>🏛️ إجماع الـ90 وكيلاً — لحظيّ</span><span class=sub id=cage></span></div><div id=council></div></div>
<div class=card><div class=h2><span>🌍 الصفقات المفتوحة</span><span class=sub id=posn></span></div><div id=positions class=dim>—</div></div>
<div class=sub style=text-align:center>🟢 إطار أخضر = إجماع ≥75% (يُتداوَل) · يحدّث كل ثانيتين</div>
<script>
const $=id=>document.getElementById(id);
async function tick(){
 try{const d=await(await fetch('/live/data',{cache:'no-store'})).json();
 $('clk').textContent='⏱️ '+d.ts;
 const a=d.account||{};
 $('eq').textContent='$'+(a.equity??'—');
 $('acc').textContent=(a.server||'')+' · رصيد $'+(a.balance??'—')+' · هامش '+(a.margin_level??'—')+'%';
 const e=d.exec||{};
 const fl=e.floating||0, fc=fl>=0?'up':'dn';
 $('exec').innerHTML=(e.frozen?'🧊 مجمّد ':'🟢 نشط ')+' · مخاطرة '+(e.risk_pct??'—')+'% · رضا '+(e.satisfaction??0)+'%';
 // 🧠 العقل الجماعيّ (fleet_mind عبر نفس النبضة)
 const F=d.fleet||{};
 if(F.state){const stAr={healthy:'صحّيّ 🟢',mild_drawdown:'تراجع خفيف 🟡',deep_drawdown:'تراجع عميق 🔴',unknown:'—'}[F.state]||F.state;
  const fc=F.state==='healthy'?'up':(F.state==='deep_drawdown'?'dn':'');
  $('fmstate').innerHTML='ميزانيّة '+Number(F.budget||0).toFixed(2);
  $('fleetline').innerHTML='<span class="'+fc+'">'+stAr+'</span> · صافي الأسطول اليوم <span class="'+((F.fleet_daily||0)>=0?'up':'dn')+'">'+Number(F.fleet_daily||0).toFixed(2)+'</span>';
 } else { $('fleetline').textContent='لا بيانات العقل بعد…'; }
 // 🏆 السبورة (رابح/متقاعد/مراقَب — من desk_scoreboard عبر نفس النبضة)
 const B=d.board||{}, M=B.magics||[];
 $('bage').textContent=B.updated?('عمر '+Math.max(0,Math.round(Date.now()/1000-B.updated))+'ث'):'';
 if(M.length){let bh='';
  for(const m of M){
   const em=m.status==='winner'?'🟢':(m.status==='retired'?'🔴':'🟡');
   const nt=Number(m.net_today||0), nc=nt>=0?'up':'dn';
   const po=m.payoff, pc=(po==null)?'dim':(po>=1?'up':(po>=0.5?'':'dn'));
   const pt=(po==null)?((m.avg_loss===0||m.avg_loss==null)&&m.avg_win?'∞':'—'):po.toFixed(2);
   bh+='<div class=pos><span>'+em+' '+(m.name||m.magic)+
       (m.n_open?' <span class=chip>'+m.n_open+' مفتوح</span>':'')+'</span>'+
       '<span><span class="'+pc+'" style=font-size:11px title=العائد>ع'+pt+'</span> '+
       '<span class=dim style=font-size:11px>'+(m.wr_today==null?'—':m.wr_today+'%')+'</span> '+
       '<span class='+nc+'>'+(nt>=0?'+':'')+nt.toFixed(2)+'</span></span></div>';
  }
  $('board').innerHTML=bh;
 } else $('board').innerHTML='<span class=dim>لا سبورة بعد…</span>';
 // المجلس
 const C=d.council||[]; $('cage').textContent='عمر '+(d.council_age??'?')+'ث';
 let h='';
 for(const r of C){
  const col=r.dir>0?'#3ddc84':(r.dir<0?'#ff5c6c':'#7a828f');
  const trad=(r.pct>=75)?' tradeable':'';
  h+='<div class="row'+trad+'"><span class=sym style=color:'+col+'>'+r.sym.replace('m','')+'</span>'+
     '<span class=bar><span class=fill style="'+(r.dir>0?'right:0':'left:0')+';width:'+(r.pct||0)+'%;background:'+col+'"></span></span>'+
     '<span class=pct style=color:'+col+'>'+(r.pct||0)+'%</span></div>';
 }
 $('council').innerHTML=h||'<div class=dim>يحمّل…</div>';
 // الصفقات
 const P=d.positions||[]; $('posn').textContent=P.length+' مركز';
 if(P.length){let ph='';let tot=0;
  for(const p of P){tot+=p.pnl;const c=p.pnl>=0?'up':'dn';
   ph+='<div style="padding:7px 0;border-top:1px solid #1c202a">'+
       '<div class=pos style=border-top:0;padding:0><span>'+(p.mom?'🏇 ':'')+p.sym.replace('m','')+' '+p.dir+' '+p.lot+
       (p.secured?' <span class=chip style=background:#1a3a24;color:#3ddc84>🌾 مؤمَّن</span>':'')+'</span>'+
       '<span class='+c+'>'+(p.pnl>=0?'+':'')+p.pnl.toFixed(2)+'</span></div>'+
       '<div class=gene style="direction:rtl;margin-top:2px;font-size:10px">'+
       '🎯 هدف '+(p.tp??'—')+' (بُعد '+(p.to_tp??'—')+') · 🛑 وقف '+(p.sl??'—')+' (بُعد '+(p.to_sl??'—')+')'+
       (p.mom?' · 🏇 تريلينغ':'')+'</div></div>';}
  ph+='<div class=pos style=border-top:1px solid #2a3240;margin-top:4px><b>الإجماليّ</b><b class='+(tot>=0?'up':'dn')+'>'+(tot>=0?'+':'')+tot.toFixed(2)+'</b></div>';
  $('positions').innerHTML=ph;
 } else $('positions').innerHTML='<span class=dim>لا صفقات مفتوحة — ينتظر إجماعاً ≥75%</span>';
 }catch(e){$('clk').textContent='⚠️ '+e}
}
tick();setInterval(tick,2000);
</script></body></html>"""


# ── 🕸️ وسيطان (proxy) لخريطة العقل :8012 كي تُعرض عبر :8016 (صديقة للنفق، same-origin) ──
def _proxy_get(url, timeout=5.0):
    """يجلب نصّ استجابة GET من url — (نصّ, content-type) أو (None, None) عند أيّ فشل."""
    try:
        with _urlreq.urlopen(url, timeout=timeout) as r:
            ctype = r.headers.get("Content-Type") or ""
            return r.read().decode("utf-8", "replace"), ctype
    except Exception as e:
        print(f"[chart] brain proxy({url}) failed: {e}", flush=True)
        return None, None


@app.get("/pro/graph")
def pro_graph():
    """يُرجِع خريطة العقل JSON من http://127.0.0.1:8012/graph.json (تحويل مباشر) —
    الفشل ⇒ {"nodes":[],"edges":[]} لا استثناء."""
    body, _ = _proxy_get("http://127.0.0.1:8012/graph.json", timeout=5.0)
    if body is None:
        return JSONResponse({"nodes": [], "edges": []})
    return Response(content=body, media_type="application/json")


@app.get("/pro/graphmap")
def pro_graphmap():
    """يُرجِع صفحة الخريطة الحيّة (D3) من http://127.0.0.1:8012/ كي تُعرض داخل iframe القمرة
    (same-origin عبر النفق). الفشل ⇒ بديلٌ HTML بسيط لا استثناء."""
    body, _ = _proxy_get("http://127.0.0.1:8012/", timeout=5.0)
    if body is None:
        return HTMLResponse("<h1 style='font-family:sans-serif;color:#8b97a8'>خريطة العقل :8012 غير متاحة</h1>")
    return HTMLResponse(body)


@app.get("/pulse/data")
def pulse_data():
    if not _pulse_chart:
        return JSONResponse({"error": "pulse_chart غير متوفّر"})
    return JSONResponse(_pulse_chart.get_pulse_data())


@app.get("/pulse")
def pulse_page():
    if not _pulse_chart:
        return HTMLResponse("<h1>pulse_chart غير متوفّر</h1>", status_code=500)
    return HTMLResponse(_pulse_chart.PULSE_HTML)


@app.get("/index/data")
def index_data():
    if not _index_chart:
        return JSONResponse({"error": "index_chart غير متوفّر"})
    with _lock:
        return JSONResponse(_index_chart.get_index_data())


@app.get("/index")
def index_chart_page():
    if not _index_chart:
        return HTMLResponse("<h1>index_chart غير متوفّر</h1>", status_code=500)
    return HTMLResponse(_index_chart.INDEX_HTML)


@app.get("/")
def index():
    try:
        return HTMLResponse(INDEX.read_text(encoding="utf-8"))
    except Exception as e:
        return HTMLResponse(f"<h1>chart_server</h1><pre>index.html missing: {e}</pre>", status_code=500)


def main():
    # نسخة-مفردة (يحرّر تلقائياً عند موت العملية)
    try:
        import engine_lock
        engine_lock.claim("chart_server")
    except SystemExit:
        raise
    except Exception as e:
        print(f"[chart_server] engine_lock unavailable: {e}", flush=True)
    print(f"[chart_server] starting on :8016 (log {LOG})", flush=True)
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8016, log_level="warning")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""gateway.py — بوّابة R Trader الموحّدة على :8020.

reverse-proxy بسيط (urllib، مهلة 15ث) يجمع الأنظمة الثلاثة خلف منفذ واحد:
  /pro /live /chart /symbols /youtube /analyst /timer /council /index ⇒ :8016 (chart_server)
  /graph.json /node /gaps /map                                        ⇒ :8012 (system_graph)
  /api                                                                 ⇒ :8770 (خلفية FRIDAY)
"/" = صدفة R Trader (تبويبات iframe) — تأتي من r_trader.ui (يكتبها وكيل آخر).
⚖️ الصدق: واجهة توحيد وقراءة فقط — لا مسار أوامر جديداً هنا.
"""
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# جذر MT5 على المسار حتى يعمل `python r_trader/gateway.py` مباشرةً
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import psutil  # مطابقة سطر الأوامر للحياة + القتل
except Exception:  # pragma: no cover
    psutil = None

# 🔒 قفل نسخة-مفردة (نسخة أخرى تعمل ⇒ خروج هادئ من engine_lock نفسه)
try:
    import engine_lock
    engine_lock.claim("r_trader_gateway")
except SystemExit:
    raise
except Exception:
    pass  # غياب engine_lock لا يمنع البوّابة (بيئة اختبار)

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse

_FALLBACK_HTML = """<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8">
<title>R Trader</title><style>body{background:#0b0d12;color:#e8e8e8;font-family:Tahoma,Arial,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{background:#12151c;border:1px solid #f5c518;border-radius:12px;padding:32px 48px;text-align:center}
h1{color:#f5c518;margin:0 0 8px}</style></head><body><div class="card">
<h1>R Trader <small>v1</small></h1><p>الصدفة الكاملة غير متاحة بعد (r_trader/ui.py) — البوّابة تعمل والتمرير سليم.</p>
</div></body></html>"""

try:
    from r_trader.ui import SHELL_HTML  # يكتبها الوكيل B — استيراد دفاعيّ
except Exception:
    SHELL_HTML = _FALLBACK_HTML

app = FastAPI(title="R Trader", version="1.0", docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1024)

# ─── جدول التوجيه بالبادئات ───────────────────────────────────────────────
_CHART_BASE = "http://127.0.0.1:8016"
_GRAPH_BASE = "http://127.0.0.1:8012"
_API_BASE = "http://127.0.0.1:8770"

_CHART_PREFIXES = ("/pro", "/live", "/chart", "/symbols", "/youtube",
                   "/analyst", "/timer", "/council", "/index")
_GRAPH_PREFIXES = ("/graph.json", "/node", "/gaps")

_ERR_502 = """<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8">
<style>body{{background:#0b0d12;color:#e8e8e8;font-family:Tahoma,Arial,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{background:#12151c;border:1px solid #6b2d2d;border-radius:12px;padding:28px 44px;text-align:center}}
h2{{color:#f5c518;margin:0 0 8px}}</style></head><body><div class="card">
<h2>⚠️ الخدمة الخلفية غير متاحة</h2><p>تعذّر الوصول إلى <code>{upstream}</code> — تأكّد أن الخدمة تعمل ثم حاول مجدّداً.</p>
</div></body></html>"""


def _resolve(path: str):
    """يحوّل مسار الطلب إلى (قاعدة الخادم الخلفي، المسار المُمرَّر) أو None."""
    for p in _CHART_PREFIXES:
        if path.startswith(p):
            return _CHART_BASE, path
    if path in ("/map", "/map/"):
        return _GRAPH_BASE, "/"          # /map يقدّم جذر :8012
    if path.startswith("/map/"):
        return _GRAPH_BASE, path[len("/map"):]
    if path.startswith("/map"):
        return _GRAPH_BASE, path
    for p in _GRAPH_PREFIXES:
        if path.startswith(p):
            return _GRAPH_BASE, path
    if path.startswith("/api"):
        return _API_BASE, path
    return None


def _fetch(url: str, method: str, body, content_type):
    """جلب متزامن عبر urllib (يُنفَّذ في threadpool حتى لا يجمّد حلقة الأحداث)."""
    req = urllib.request.Request(url, data=body if method == "POST" else None, method=method)
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return (resp.getcode() or 200,
                    resp.headers.get("Content-Type") or "application/octet-stream",
                    resp.read())
    except urllib.error.HTTPError as e:      # خطأ من الخادم الخلفي نفسه — مرّره كما هو
        return (e.code,
                e.headers.get("Content-Type") or "text/plain; charset=utf-8",
                e.read())


async def _proxy(url: str, request: Request) -> Response:
    """يحافظ على method/query/body/content-type. فشل الاتصال ⇒ 502 برسالة عربية."""
    body = await request.body() if request.method == "POST" else None
    try:
        status, ctype, content = await run_in_threadpool(
            _fetch, url, request.method, body, request.headers.get("content-type"))
        return Response(content=content, status_code=status, media_type=ctype)
    except Exception:
        upstream = url.split("/", 3)
        upstream = "/".join(upstream[:3]) if len(upstream) >= 3 else url
        return HTMLResponse(_ERR_502.format(upstream=upstream), status_code=502)


@app.get("/")
async def root() -> HTMLResponse:
    """صدفة R Trader — من r_trader.ui إن وُجدت، وإلا الصفحة البديلة."""
    return HTMLResponse(SHELL_HTML)


# ═══════════════════════════════════════════════════════════════════════════
# 🎛️ لوحة تحكّم المحرّكات (تحكّم تشغيليّ فقط — لا مسار أوامر تداول جديد)
# ⚖️ الصدق: start/stop/restart لعمليّات الطاقم فقط عبر قائمة بيضاء صارمة. ديمو.
# ═══════════════════════════════════════════════════════════════════════════
from fastapi.responses import JSONResponse  # noqa: E402  (استيراد محليّ للقسم)

_RN_DIR = _ROOT / "data" / "r_native"
_TOKEN_PATH = _RN_DIR / "rt_token.txt"

# 🐍 مُشغّل بايثون بلا نافذة (نفس منطق الوصيّ): venv pythonw إن وُجد، وإلا pythonw في PATH
_PYW = str(_ROOT / ".venv" / "Scripts" / "pythonw.exe")
if not os.path.exists(_PYW):
    _PYW = "pythonw"
_CREATE_NO_WINDOW = 0x08000000

# الطاقم النشط: اسم منطقيّ → (needle لمطابقة سطر الأوامر، args، cwd).
# needle هو ما يميّز العمليّة في cmdline (اسم السكربت). القائمة = قائمة بيضاء صارمة.
_CREW = {
    "unified_brain":       ("unified_brain.py",      ["unified_brain.py"],      str(_ROOT)),
    "brain_trader":        ("brain_trader.py",       ["brain_trader.py"],       str(_ROOT)),
    "agent_council":       ("agent_council.py",      ["agent_council.py"],      str(_ROOT)),
    "market_pulse":        ("market_pulse.py",       ["market_pulse.py"],       str(_ROOT)),
    "quant_desk":          ("quant_desk.py",         ["quant_desk.py"],         str(_ROOT)),
    "radhi_mimic":         ("radhi_mimic.py",        ["radhi_mimic.py"],        str(_ROOT)),
    "profit_harvester":    ("profit_harvester.py",   ["profit_harvester.py"],   str(_ROOT)),
    "news_alarm":          ("news_alarm.py",         ["news_alarm.py"],         str(_ROOT)),
    "order_janitor":       ("order_janitor.py",      ["order_janitor.py"],      str(_ROOT)),
    "real_lock":           ("real_lock.py",          ["real_lock.py"],          str(_ROOT)),
    "master_floor":        ("master_floor.py",       ["master_floor.py"],       str(_ROOT)),
    "peak_watch":          ("peak_watch.py",         ["peak_watch.py"],         str(_ROOT)),
    "gold_level_sentinel": ("gold_level_sentinel.py", ["gold_level_sentinel.py"], str(_ROOT)),
    "self_evolver":        ("self_evolver.py",       ["self_evolver.py"],       str(_ROOT)),
    "brain_watch":         ("brain_watch.py",        ["brain_watch.py"],        str(_ROOT)),
    "watchdog_guard":      ("watchdog_guard.py",     ["watchdog_guard.py"],     str(_ROOT)),
}
# قائمة بيضاء صارمة للأفعال — أيّ اسم خارج المفاتيح يُرفض بـ403.
_CREW_ALLOWED = frozenset(_CREW.keys())
_ACTIONS = frozenset({"start", "stop", "restart"})


def _get_token() -> str:
    """يقرأ توكن التحكّم أو يولّده (os.urandom hex، ثابت بعد أوّل توليد). يُخزّن ليقرأه UI."""
    try:
        tok = _TOKEN_PATH.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    except Exception:
        pass
    tok = os.urandom(24).hex()
    try:
        _RN_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _TOKEN_PATH.with_suffix(".txt.tmp")
        tmp.write_text(tok, encoding="utf-8")
        os.replace(tmp, _TOKEN_PATH)
    except Exception:
        pass
    return tok


def _token_ok(request: Request) -> bool:
    """تحقّق التوكن عبر رأس X-RT-Token أو ?token= — مقارنة ثابتة الزمن."""
    import hmac
    supplied = request.headers.get("x-rt-token") or request.query_params.get("token") or ""
    if not supplied:
        return False
    return hmac.compare_digest(supplied, _get_token())


def _is_localhost(request: Request) -> bool:
    """أهو الطلب من 127.0.0.1 مباشرةً (لا عبر النفق)؟ — لحماية تسريب التوكن."""
    client = request.client
    host = client.host if client else ""
    return host in ("127.0.0.1", "::1", "localhost")


def _crew_alive() -> dict:
    """اسم منطقيّ → عدد عمليّات بايثون الحيّة التي يطابق سطر أوامرها needle (عدا هذا الماسح)."""
    counts = {name: 0 for name in _CREW}
    if psutil is None:
        return counts
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if "python" not in (p.info["name"] or "").lower():
                continue
            cl = " ".join(p.info.get("cmdline") or [])
            if "shell-snapshot" in cl:
                continue
            for name, (needle, _args, _cwd) in _CREW.items():
                if needle in cl:
                    counts[name] += 1
        except Exception:
            pass
    return counts


def _kill_crew(needle: str) -> int:
    """يقتل كل عمليّات بايثون التي يطابق سطر أوامرها needle. يرجع العدد المقتول."""
    n = 0
    if psutil is None:
        return n
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if "python" not in (p.info["name"] or "").lower():
                continue
            cl = " ".join(p.info.get("cmdline") or [])
            if "shell-snapshot" in cl:
                continue
            if needle in cl:
                p.kill()
                n += 1
        except Exception:
            pass
    return n


def _start_crew(name: str, force: bool = False) -> dict:
    """يُطلق سكربت المحرّك بلا نافذة (CREATE_NO_WINDOW). يحترم القفل: لا يُطلق نسخةً إن كانت حيّة
    (إلا عند restart حيث force=True — العمليّة القديمة قُتلت للتوّ فقد تبدو حيّةً لحظياً)."""
    needle, args, cwd = _CREW[name]
    if not force and _crew_alive().get(name, 0) > 0:
        return {"ok": True, "already": True, "note": "نسخة تعمل — القفل يمنع التكرار"}
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        subprocess.Popen([_PYW] + args, cwd=cwd, env=env,
                         creationflags=_CREATE_NO_WINDOW)
        return {"ok": True, "started": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/rt/token")
async def rt_token(request: Request) -> JSONResponse:
    """يرجع توكن التحكّم — فقط لطلبات localhost (كي لا يتسرّب عبر النفق)."""
    if not _is_localhost(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return JSONResponse({"token": _get_token()})


@app.get("/rt/engines")
async def rt_engines() -> JSONResponse:
    """قائمة محرّكات الطاقم النشط + هل كلٌّ حيّ (قراءة فقط)."""
    counts = await run_in_threadpool(_crew_alive)
    engines = [
        {"name": name, "script": _CREW[name][0],
         "alive": counts.get(name, 0) > 0, "procs": counts.get(name, 0)}
        for name in _CREW
    ]
    return JSONResponse({
        "engines": engines,
        "n_alive": sum(1 for e in engines if e["alive"]),
        "n_total": len(engines),
    })


@app.post("/rt/engines/{name}/{action}")
async def rt_engine_action(name: str, action: str, request: Request) -> JSONResponse:
    """تحكّم تشغيليّ (start|stop|restart) لعمليّة محرّك من الطاقم فقط. محميّ بتوكن + قائمة بيضاء."""
    if not _token_ok(request):
        return JSONResponse({"error": "unauthorized", "detail": "توكن غير صحيح"}, status_code=401)
    if name not in _CREW_ALLOWED:
        return JSONResponse({"error": "forbidden", "detail": "اسم خارج الطاقم المسموح"}, status_code=403)
    if action not in _ACTIONS:
        return JSONResponse({"error": "bad_action", "detail": "الفعل ∈ start|stop|restart"}, status_code=400)

    needle = _CREW[name][0]
    if action == "stop":
        killed = await run_in_threadpool(_kill_crew, needle)
        return JSONResponse({"ok": True, "name": name, "action": action, "killed": killed})
    if action == "start":
        res = await run_in_threadpool(_start_crew, name)
        return JSONResponse({"name": name, "action": action, **res})
    # restart = stop ثمّ start (force: العمليّة قُتلت للتوّ — تجاوز فحص الحياة اللحظيّ)
    killed = await run_in_threadpool(_kill_crew, needle)
    res = await run_in_threadpool(_start_crew, name, True)
    return JSONResponse({"name": name, "action": action, "killed": killed, **res})


# ═══════════════════════════════════════════════════════════════════════════
# 📊 قراءة فقط: لوحة نتائج الديسك + بيانات الصفحة الرئيسة (لا مسار أوامر جديد)
# ═══════════════════════════════════════════════════════════════════════════
_SCOREBOARD_PATH = _ROOT / "data" / "r_native" / "desk_scoreboard.json"
_SCOREBOARD_STALE = {"magics": [], "winners": [], "retired": [],
                     "today_trades": [], "account": {}, "stale": True}


def _read_scoreboard() -> dict:
    """يقرأ desk_scoreboard.json (utf-8-sig آمن). فشل/غياب/تلف ⇒ هيكل stale (لا 500)."""
    import json
    try:
        raw = _SCOREBOARD_PATH.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return dict(_SCOREBOARD_STALE)


@app.get("/rt/scoreboard")
async def rt_scoreboard() -> JSONResponse:
    """لوحة نتائج الديسك (قراءة فقط) — فشل-ناعم: أبداً 500، بل هيكل stale بحالة 200."""
    data = await run_in_threadpool(_read_scoreboard)
    return JSONResponse(data)


@app.get("/rt/home")
async def rt_home() -> JSONResponse:
    """منحنى الأسهم + صفقات اليوم من r_trader.home_extra (استيراد دفاعيّ، قراءة فقط)."""
    try:
        from r_trader.home_extra import equity_curve, todays_trades
    except Exception:
        return JSONResponse({"equity_curve": [], "today_trades": []})
    equity = await run_in_threadpool(equity_curve)
    trades = await run_in_threadpool(todays_trades)
    return JSONResponse({"equity_curve": equity, "today_trades": trades})


# ─── 🖐️🚀 بطاقة الانطلاقة: حالة حرس اليد (قراءة فقط، فشل-ناعم) ─────────────
_HAND_GUARD_PATH = _ROOT / "data" / "r_native" / "hand_guard_status.json"


def _read_hand_guard() -> dict:
    """يقرأ hand_guard_status.json (utf-8-sig آمن). فشل/غياب/تلف ⇒ {"stale": true} بحالة 200 (لا 500)."""
    import json
    try:
        data = json.loads(_HAND_GUARD_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"stale": True}


@app.get("/rt/launch")
async def rt_launch() -> JSONResponse:
    """🚀 بطاقة الانطلاقة (حرس اليد 🖐️): الحقوق مقابل البداية + القمّة + شريط اليد اليوميّ.
    قراءة فقط — فشل-ناعم: أبداً 500، بل {"stale": true} بحالة 200."""
    data = await run_in_threadpool(_read_hand_guard)
    return JSONResponse(data)


# ─── 🧠 العقل الجماعيّ: لقطة fleet_mind (قراءة فقط، فشل-ناعم) ───────────────
_FLEET_MIND_PATH = _ROOT / "data" / "r_native" / "fleet_mind.json"


def _read_fleet_mind() -> dict:
    """يقرأ fleet_mind.json (utf-8-sig آمن). فشل/غياب ⇒ {"stale": true} بحالة 200 (لا 500)."""
    import json
    try:
        data = json.loads(_FLEET_MIND_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"stale": True}


@app.get("/rt/fleet")
async def rt_fleet() -> JSONResponse:
    """🧠 العقل الجماعيّ: حالة الأسطول + ميزانيّة المخاطرة + مضاعِف كل محرّك (يديرون بعضهم).
    قراءة فقط — فشل-ناعم 200."""
    return JSONResponse(await run_in_threadpool(_read_fleet_mind))


# ─── 🩺 فحص صحّة البوّابة (قراءة فقط، فشل-ناعم — أبداً 500) ────────────────
_UPSTREAMS = {"chart_8016": _CHART_BASE, "graph_8012": _GRAPH_BASE, "friday_8770": _API_BASE}


def _upstream_alive(base: str) -> bool:
    """أيّ ردّ HTTP (حتى 404/405) = حيّ؛ فشل الاتصال فقط = ميّت."""
    try:
        req = urllib.request.Request(base + "/", method="HEAD")
        with urllib.request.urlopen(req, timeout=2):
            return True
    except urllib.error.HTTPError:
        return True  # ردّ HTTP من الخادم (404/405/…) ⇒ الخدمة حيّة
    except Exception:
        return False


def _health_snapshot() -> dict:
    import time
    from datetime import datetime
    ups = {}
    for name, base in _UPSTREAMS.items():
        try:
            ups[name] = _upstream_alive(base)
        except Exception:
            ups[name] = False
    try:
        age = round(time.time() - _SCOREBOARD_PATH.stat().st_mtime, 1)
    except Exception:
        age = None
    return {"gateway": True, "upstreams": ups,
            "scoreboard_age_s": age,
            "iso": datetime.now().strftime("%H:%M:%S")}


@app.get("/rt/health")
async def rt_health() -> JSONResponse:
    """صحّة البوّابة + حياة الخوادم الخلفيّة + عمر لوحة النتائج. فشل-ناعم دائماً."""
    try:
        data = await run_in_threadpool(_health_snapshot)
    except Exception:
        data = {"gateway": True, "upstreams": {}, "scoreboard_age_s": None, "iso": ""}
    return JSONResponse(data)


# ─── 🧠 مخ الشركة: رسم خزنة plutobrain الحيّ (قراءة فقط، فشل-ناعم) ─────────
_BRAIN_TTL = 60.0                              # مسح الخزنة رخيص لكن لا داعي لكلّ تحديث
_BRAIN_CACHE = {"html": "", "ts": 0.0}

_BRAIN_ERR = """<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8">
<title>مخ الشركة</title><style>body{background:#07080c;color:#e8e8e8;font-family:Tahoma,Arial,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{background:#12151c;border:1px solid #6b2d2d;border-radius:12px;padding:28px 44px;text-align:center}
h2{color:#f5c518;margin:0 0 8px}</style></head><body><div class="card">
<h2>🧠 مخ الشركة غير متاح</h2><p>تعذّر بناء الرسم — تأكّد من وجود خزنة plutobrain ثم حدّث الصفحة.</p>
</div></body></html>"""


def _brain_html() -> str:
    """يبني صفحة الرسم عبر r_trader.brain_graph مع كاش 60ث. أيّ خلل ⇒ صفحة الخطأ."""
    import time
    now = time.time()
    if _BRAIN_CACHE["html"] and (now - _BRAIN_CACHE["ts"]) < _BRAIN_TTL:
        return _BRAIN_CACHE["html"]
    from r_trader import brain_graph          # استيراد دفاعيّ (داخل try للنداء)
    html = brain_graph.render_html()
    _BRAIN_CACHE["html"] = html
    _BRAIN_CACHE["ts"] = now
    return html


@app.get("/rt/brain")
async def rt_brain() -> HTMLResponse:
    """رسم «مخ الشركة» الحيّ (خزنة Obsidian). فشل-ناعم: أبداً 500 — بطاقة خطأ عربية 200."""
    try:
        html = await run_in_threadpool(_brain_html)
        return HTMLResponse(html)
    except Exception:
        return HTMLResponse(_BRAIN_ERR, status_code=200)


# ─── 🚌 ناقل الرسائل الحيّ + المتعلّم-الفوقيّ (تبادل معلومات حقيقيّ + قياس ذاتيّ صادق) ─
# ⚖️ الصدق: هذه نوافذ قراءة فقط على ملفّات تكتبها المحرّكات من أحداث حقيقيّة. إن غاب
#   الملفّ أو تلف ⇒ نرجع هيكلاً فارغاً بحالة 200 (لا اختلاق، لا 500). السوق غير متنبّأ
#   به بهذه النماذج (قياس أصيل)؛ لذا لا نزيّن رقماً ولا نصنع «تعلّماً» لم يحدث فعلاً.
_BUS_PATH = _ROOT / "data" / "r_native" / "brain_bus.json"
_META_PROGRESS_PATH = _ROOT / "data" / "r_native" / "meta_learner_progress.json"
_META_BELIEFS_PATH = _ROOT / "data" / "r_native" / "meta_beliefs.json"


def _read_json_soft(path: Path):
    """يقرأ JSON بأمان (utf-8-sig). غياب/تلف ⇒ None (لا يرمي أبداً)."""
    import json
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data
    except Exception:
        return None


def _bus_text(m: dict) -> str:
    """يشتقّ نصّاً مقروءاً مختصراً من payload الحقيقيّ للرسالة (لا اختلاق — فقط ما كتبه الناقل).
    brain_bus يكتب payload مُهيكلاً (side/pct/net/score/…) لا حقل text؛ نصهره سطراً عربيّاً مقروءاً."""
    p = m.get("payload")
    if not isinstance(p, dict):
        return ""
    sym = str(m.get("sym") or "")
    bits = []
    side = p.get("side")
    if side in ("buy", "sell"):
        bits.append("شراء" if side == "buy" else "بيع")
    for k, lbl in (("pct", "توافق"), ("score", "درجة"), ("conv", "قناعة"),
                   ("mult", "×"), ("net", "صافي"), ("pnl", "ربح"),
                   ("lot", "لوت"), ("confluence", "التقاء"), ("level", "مستوى")):
        v = p.get(k)
        if v is not None and v != "":
            bits.append(f"{lbl} {v}")
    core = " · ".join(bits)
    if sym and core:
        return f"{sym} · {core}"
    return sym or core


def _read_bus() -> dict:
    """آخر الرسائل بين المحرّكات كما كتبتها هي (حقيقيّة). brain_bus يكتب المفتاح "recent"
    (وقد يكتب غيره "messages")؛ نقبل كليهما. غياب/تلف ⇒ {"messages": [], "stale": true} 200.
    نشتقّ text من payload الحقيقيّ للعرض — بلا تلفيق (فقط صهر ما كُتب فعلاً)."""
    data = _read_json_soft(_BUS_PATH)
    msgs = None
    if isinstance(data, dict):
        for key in ("recent", "messages"):
            m = data.get(key)
            if isinstance(m, list):
                msgs = m
                break
    elif isinstance(data, list):
        msgs = data
    if msgs is None:
        return {"messages": [], "stale": True}
    # نمرّر آخر 40 فقط (العميل يعرض ~12) ونحافظ على الحقول المعروفة كما هي — بلا تلفيق
    out = []
    for m in msgs[-40:]:
        if isinstance(m, dict):
            out.append({"frm": m.get("frm") or m.get("from") or "",
                        "to": m.get("to") or "",
                        "kind": m.get("kind") or "",
                        "text": m.get("text") or m.get("msg") or _bus_text(m),
                        "ts": m.get("ts")})
    return {"messages": out, "n": len(out)}


@app.get("/rt/bus")
async def rt_bus() -> JSONResponse:
    """🚌 ناقل الرسائل الحيّ بين المحرّكات (قراءة فقط، رسائل حقيقيّة من أحداث حقيقيّة).
    فشل-ناعم: أبداً 500 — {"messages": [], "stale": true} بحالة 200 عند الغياب."""
    return JSONResponse(await run_in_threadpool(_read_bus))


def _read_meta() -> dict:
    """قياس المتعلّم-الفوقيّ خارج-العيّنة (صادق حتى لو مسطّحاً/سالباً). الشكل المتوقَّع في
      meta_learner_progress.json: {"verdict","brier","edge_t","n", …} ويُدمَج meta_beliefs.json.
    غياب/تلف ⇒ {"verdict": "no_data", "stale": true} — لا نخترع «حافّة» ولا «تقدّماً»."""
    prog = _read_json_soft(_META_PROGRESS_PATH)
    beliefs = _read_json_soft(_META_BELIEFS_PATH)
    if not isinstance(prog, dict):
        prog = {}
    out = dict(prog)
    if isinstance(beliefs, dict):
        # لا ندهس أرقام التقدّم الحقيقيّة؛ نضيف المعتقدات كقسم مستقلّ فقط
        out.setdefault("beliefs", beliefs)
    if not out:
        return {"verdict": "no_data", "stale": True}
    out.setdefault("verdict", "no_data")
    return out


@app.get("/rt/meta")
async def rt_meta() -> JSONResponse:
    """🧠 قياس المتعلّم-الفوقيّ خارج-العيّنة (Brier + دلالة t للحافّة) — صادق دائماً:
    إن كان لا-حافّة يُظهرها كما هي. فشل-ناعم: أبداً 500 — {"verdict":"no_data"} 200."""
    return JSONResponse(await run_in_threadpool(_read_meta))


# ─── 🔭 حسّ السوق + الثقة الذاتيّة (قراءة فقط، فشل-ناعم — يتنفّس بها الرسم) ──────────
_SENSE_PATH = _ROOT / "data" / "r_native" / "market_sense.json"
_CONFIDENCE_PATH = _ROOT / "data" / "r_native" / "confidence.json"


def _read_sense() -> dict:
    """يدمج market_sense.json + confidence.json (كلاهما اختياريّ) في لقطةٍ واحدة تُغذّي «تنفّس»
    العقد بثقتها الحيّة. ⚖️ الصدق: كلاهما قد يغيب ⇒ نرجع أقساماً فارغة بحالة 200 (لا اختلاق، لا 500).
    الثقة ليست وعداً بربح — هي *اعتقادٌ ذاتيّ* يُعرَض شفّافاً ويُقاس صدقه في المتعلّم-الفوقيّ."""
    sense = _read_json_soft(_SENSE_PATH)
    raw_conf = _read_json_soft(_CONFIDENCE_PATH)
    # نطبّع الثقة إلى {مفتاح(str): float∈[0..1]} مقبولاً شكلين: {"engines":{k:{confidence}}} أو {k:num}
    conf = {}
    src = None
    if isinstance(raw_conf, dict):
        src = raw_conf.get("engines") if isinstance(raw_conf.get("engines"), dict) else raw_conf
    if isinstance(src, dict):
        for k, v in src.items():
            c = None
            if isinstance(v, (int, float)):
                c = float(v)
            elif isinstance(v, dict):
                for ck in ("confidence", "conf", "self_confidence", "belief"):
                    if isinstance(v.get(ck), (int, float)):
                        c = float(v[ck]); break
            if c is not None:
                conf[str(k)] = max(0.0, min(1.0, c))
    out = {
        "sense": sense if isinstance(sense, dict) else {},
        "confidence": conf,
        "has_sense": isinstance(sense, dict) and bool(sense),
        "has_confidence": bool(conf),
    }
    if not out["has_sense"] and not out["has_confidence"]:
        out["stale"] = True
    return out


@app.get("/rt/sense")
async def rt_sense() -> JSONResponse:
    """🔭 حسّ السوق + الثقة الذاتيّة للمحرّكات (قراءة فقط) — تتنفّس بها عُقد الرسم.
    فشل-ناعم: أبداً 500 — أقسامٌ فارغة/{"stale":true} بحالة 200 عند غياب الملفّات."""
    return JSONResponse(await run_in_threadpool(_read_sense))


# ─── 🖐️⛏️ معدِّن اليد: لماذا تربح يدُك (OOS)، مقيسٌ لحظة الدخول (قراءة فقط، صادق) ─────────
_HAND_EDGE_PATH = _ROOT / "data" / "r_native" / "hand_edge.json"


def _read_hand() -> dict:
    """يفكّ لماذا تربح يد المستخدم من بصمة اللحظة المخزّنة (hand_miner). صادقٌ دائماً: يُظهر أنّ
    اليد تربح بالتكرار لا بالمال (فوزٌ عالٍ/صافٍ سالب) ويكشف الرافعات الصامدة خارج-العيّنة فقط
    (حجم/فريم-أعلى/ليل). غياب/تلف ⇒ {"ok": false, "stale": true} 200 — لا اختلاق حافّة."""
    d = _read_json_soft(_HAND_EDGE_PATH)
    if not isinstance(d, dict) or not d:
        return {"ok": False, "stale": True, "reason": "no_hand_edge_yet"}
    return d


@app.get("/rt/hand")
async def rt_hand() -> JSONResponse:
    """🖐️⛏️ لماذا تربح يدُك — تحليلٌ صادق خارج-العيّنة لبصمة كل صفقة يدوية لحظة الدخول.
    فشل-ناعم: أبداً 500 — {"ok":false,"stale":true} 200 عند غياب hand_edge.json."""
    return JSONResponse(await run_in_threadpool(_read_hand))


# ─── 🧩 المُعالِج الذاتيّ لتعارض القرارات (conflict_resolver) — حالة الحلّ الحيّة (قراءة فقط) ─────
_COHERENCE_PATH = _ROOT / "data" / "r_native" / "conflict_resolver_status.json"


def _read_coherence() -> dict:
    """حالة المُعالِج الذاتيّ: التعارضات المكتشفة + المُنِعة (vetoed) + المُعالَجة الآن (resolved_now).
    فشل-ناعم: غياب/تلف ⇒ {"active": false} 200 (المُعالِج غير مُشغَّل بعد — لا اختلاق)."""
    d = _read_json_soft(_COHERENCE_PATH)
    if not isinstance(d, dict) or not d:
        return {"active": False}
    d.setdefault("active", True)
    return d


@app.get("/rt/coherence")
async def rt_coherence() -> JSONResponse:
    """🧩 حالة المُعالِج الذاتيّ لتعارض القرارات (يحلّ لا يُنبّه فقط) — قراءة فقط، فشل-ناعم 200."""
    return JSONResponse(await run_in_threadpool(_read_coherence))


@app.api_route("/{full_path:path}", methods=["GET", "POST"])
async def gateway(full_path: str, request: Request) -> Response:
    path = "/" + full_path
    resolved = _resolve(path)
    if resolved is None:
        return HTMLResponse(
            """<div dir="rtl" style="font-family:Tahoma;padding:24px">المسار غير معروف في بوّابة R Trader.</div>""",
            status_code=404)
    base, target_path = resolved
    url = base + target_path
    if request.url.query:
        url += "?" + request.url.query
    return await _proxy(url, request)


if __name__ == "__main__":
    # 🪟 pythonw.exe بلا وحدة تحكّم ⇒ sys.stdout/stderr = None، وإعداد تسجيل uvicorn
    # يتعطّل عند الكتابة على تيّار معدوم فتموت العمليّة صامتةً. نوجّه الإخراج إلى ملفّ
    # سجلّ عند غيابه كي تعمل «pythonw r_trader/gateway.py» بلا نافذة كما هو موثّق.
    if sys.stdout is None or sys.stderr is None:
        try:
            _log = _RN_DIR / "r_trader_gateway.out.log"
            _RN_DIR.mkdir(parents=True, exist_ok=True)
            _fh = open(_log, "a", encoding="utf-8", buffering=1)
            if sys.stdout is None:
                sys.stdout = _fh
            if sys.stderr is None:
                sys.stderr = _fh
        except Exception:
            pass
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8020, log_level="warning")

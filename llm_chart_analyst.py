# -*- coding: utf-8 -*-
"""
llm_chart_analyst.py — «محلّل Fable» أقوى محلّل شارت لدينا (قراءة فقط — لا يتداول أبداً)
================================================================================
حلقة دائمة (~20 ثانية):
  1) حارس الأخبار: يجلب تقويم ForexFactory كلّ news_refresh_min ويُرشّح أحداث الذهب/الدولار.
  2) كلّ interval_min (أو عند ملف الطلب llm_analyst_request.flag من زرّ "حلّل الآن")
     يبني حزمة سياقٍ مضغوطة من ملفّاتنا الحيّة ثم يستدعي Claude CLI (claude-fable-5)
     ليكتب قراءةً مهنيّة عربيّة بسيناريوهات إن/فإن + شروط الإبطال + سطر الصدق.
  3) يكتب data/r_native/llm_analyst_report.json ذرّيّاً للوحة.
قانون الصدق: تأطيرٌ للقراءة من أرقامنا الحيّة فقط — لا يقين تنبّئيّ (قياسنا ~50% خارج العيّنة).
لا مسارات أوامر MT5 إطلاقاً في هذا الملف.
"""

import os
import sys

# ── أوّلاً: تحويل المخرجات إلى ملف سجلّ (آمنٌ للتشغيل بلا نافذة pythonw) ──
BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data", "r_native")
os.makedirs(DATA, exist_ok=True)
_LOG_PATH = os.path.join(DATA, "llm_analyst.out.log")
try:
    _log_f = open(_LOG_PATH, "a", encoding="utf-8", errors="replace", buffering=1)
    sys.stdout = _log_f
    sys.stderr = _log_f
except Exception:
    pass

# ── بعد التحويل: بقيّة الاستيرادات ──
import json
import time
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone

# ── قفل النسخة الواحدة (singleton) ──
try:
    import engine_lock
    engine_lock.claim("llm_chart_analyst")
except SystemExit:
    raise
except Exception as _e:
    print(f"[warn] engine_lock غير متاح: {_e}", flush=True)

CLAUDE = r"C:\Users\Radhi\.local\bin\claude.exe"      # مسار CLI المصادَق عليه (الملفّ الفعليّ .exe)
CFG_PATH = os.path.join(DATA, "llm_analyst_config.json")
REPORT_PATH = os.path.join(DATA, "llm_analyst_report.json")
NEWS_PATH = os.path.join(DATA, "news_calendar.json")
FLAG_PATH = os.path.join(DATA, "llm_analyst_request.flag")

QUANT_PATH = os.path.join(DATA, "quant_desk.json")
PULSE_PATH = os.path.join(DATA, "market_pulse.json")
YT_PATH = os.path.join(DATA, "youtube_live_status.json")
SENT_PATH = os.path.join(DATA, "gold_sentinel_status.json")

NEWS_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CREATE_NO_WINDOW = 0x08000000  # كي لا تظهر نافذة كونسول عند استدعاء CLI


def log(msg):
    """سجلّ بطابع زمنيّ — لا يفشل أبداً."""
    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)
    except Exception:
        pass


def atomic_write(path, obj):
    """كتابة ذرّيّة: tmp ثم os.replace (لا ملفّات نصف مكتوبة)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_json(path, max_age_s=None):
    """قراءة JSON بأمان؛ يعيد None عند الفشل أو التقادم الشديد."""
    try:
        if not os.path.exists(path):
            return None
        if max_age_s is not None and (time.time() - os.path.getmtime(path)) > max_age_s:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_config():
    """تحميل الإعدادات مع القيم الافتراضيّة (setdefault) وحفظها إن تغيّرت."""
    cfg = read_json(CFG_PATH) or {}
    defaults = {"enabled": True, "interval_min": 20,
                "model": "claude-fable-5", "news_refresh_min": 60}
    changed = False
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k] = v
            changed = True
    if changed:
        try:
            atomic_write(CFG_PATH, cfg)
        except Exception:
            pass
    return cfg


# ════════════════════════ 1) حارس الأخبار ════════════════════════

def fetch_news():
    """يجلب تقويم الأسبوع ويُرشّح: USD/ALL أو ذكر الذهب، تأثير High/Medium، خلال 36 ساعة."""
    req = urllib.request.Request(NEWS_URL, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FRIDAY-analyst/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = json.loads(r.read().decode("utf-8", errors="replace"))
    now = datetime.now(timezone.utc)
    out = []
    for ev in raw if isinstance(raw, list) else []:
        try:
            cur = str(ev.get("country", "")).upper()
            title = str(ev.get("title", ""))
            impact = str(ev.get("impact", ""))
            if impact not in ("High", "Medium"):
                continue
            if cur not in ("USD", "ALL") and "gold" not in title.lower():
                continue
            dt = datetime.fromisoformat(str(ev.get("date", "")).replace("Z", "+00:00"))
            hours_to = (dt - now).total_seconds() / 3600.0
            if not (-1.0 <= hours_to <= 36.0):
                continue
            out.append({"title": title, "currency": cur, "impact": impact,
                        "date": ev.get("date"), "hours_to": round(hours_to, 1),
                        "forecast": ev.get("forecast", ""), "previous": ev.get("previous", "")})
        except Exception:
            continue
    out.sort(key=lambda e: e["hours_to"])
    return out


def refresh_news_if_due(state, cfg):
    """يحدّث كاش الأخبار عند استحقاقه؛ عند الفشل يُبقي الكاش القديم."""
    due = (time.time() - state.get("last_news", 0)) >= cfg["news_refresh_min"] * 60
    if not due and os.path.exists(NEWS_PATH):
        return
    try:
        events = fetch_news()
        atomic_write(NEWS_PATH, {"ts": time.time(),
                                 "iso": datetime.now().isoformat(timespec="seconds"),
                                 "events": events})
        state["last_news"] = time.time()
        log(f"news: {len(events)} حدثاً مرشّحاً (36 ساعة القادمة)")
    except Exception as e:
        state["last_news"] = time.time()  # لا نُعاود القصف كلّ 20 ثانية
        log(f"news fetch فشل — نُبقي الكاش: {e}")


def load_news_events():
    """أحداث الأخبار من الكاش مع إعادة حساب hours_to لحظيّاً."""
    cache = read_json(NEWS_PATH) or {}
    events = cache.get("events", [])
    now = datetime.now(timezone.utc)
    fresh = []
    for ev in events:
        try:
            dt = datetime.fromisoformat(str(ev.get("date", "")).replace("Z", "+00:00"))
            h = (dt - now).total_seconds() / 3600.0
            if h < -1.0:
                continue
            ev = dict(ev)
            ev["hours_to"] = round(h, 1)
            fresh.append(ev)
        except Exception:
            continue
    fresh.sort(key=lambda e: e["hours_to"])
    return fresh


# ════════════════════════ 2) حزمة السياق ════════════════════════

def _fmt(v, nd=2):
    try:
        return f"{float(v):.{nd}f}"
    except Exception:
        return "؟"


def build_context_pack(news_events):
    """يبني حزمة سياقٍ مضغوطة (~4-6 آلاف حرف) من الملفّات الحيّة."""
    lines = []
    quant = read_json(QUANT_PATH, max_age_s=6 * 3600)
    pulse = read_json(PULSE_PATH, max_age_s=3 * 3600)
    yt = read_json(YT_PATH, max_age_s=3 * 3600)
    sent = read_json(SENT_PATH, max_age_s=6 * 3600)

    # ── الذهب من نبض السوق ──
    gold = None
    if pulse and isinstance(pulse.get("symbols"), dict):
        gold = pulse["symbols"].get("XAUUSDm") or pulse["symbols"].get("XAUUSD")
    if gold:
        lines.append(f"سعر الذهب الآن: {_fmt(gold.get('price'))}")
        lines.append(f"قراءة النبض: {gold.get('read','—')} | نقاط {_fmt(gold.get('score'),1)}/100")
        pm1, pm5 = gold.get("pattern_m1") or {}, gold.get("pattern_m5") or {}
        if pm1.get("name") or pm5.get("name"):
            lines.append(f"شموع: M1={pm1.get('name') or '—'} (قوّة {pm1.get('strength',0)}) | M5={pm5.get('name') or '—'}")
        mom = gold.get("momentum") or {}
        lines.append(f"زخم: Stoch {_fmt(mom.get('stoch_k'),1)}/{_fmt(mom.get('stoch_d'),1)} | RSI9 {_fmt(mom.get('rsi9'),1)} | ميل M1={mom.get('trend_m1')} M5={mom.get('trend_m5')}")
        st = gold.get("structure") or {}
        lines.append(f"بنية: قمّة أرجوحة {_fmt(st.get('swing_high'))} / قاع {_fmt(st.get('swing_low'))}")
        vol = gold.get("volatility") or {}
        lines.append(f"تذبذب: ATR14(M5) {_fmt(vol.get('atr14_m5'))} | سبريد {_fmt(vol.get('spread'))} ({_fmt(vol.get('spread_atr_pct'),1)}% من ATR)")
        smc = gold.get("smc") or {}
        bos = (smc.get("bos") or [])[-1:]
        cho = (smc.get("choch") or [])[-1:]
        if bos:
            lines.append(f"SMC آخر BOS: اتّجاه {bos[0].get('dir')} عند {_fmt(bos[0].get('price'))}")
        if cho:
            lines.append(f"SMC آخر CHoCH: اتّجاه {cho[0].get('dir')} عند {_fmt(cho[0].get('price'))}")
        obs = smc.get("ob") or []
        fvgs = smc.get("fvg") or []
        live_ob = [o for o in obs if not o.get("mitigated")]
        live_fvg = [f for f in fvgs if not f.get("filled")]
        lines.append(f"SMC: OB حيّة {len(live_ob)}/{len(obs)} | FVG غير مملوءة {len(live_fvg)}/{len(fvgs)} | POC {_fmt(smc.get('poc'))}")
        sw = (smc.get("sweeps") or [])[-1:]
        if sw:
            lines.append(f"آخر اصطياد سيولة: جهة {sw[0].get('side')} عند {_fmt(sw[0].get('price'))}")
        lp = (smc.get("liq_pools") or [])[-2:]
        for p in lp:
            lines.append(f"بِركة سيولة: {p.get('side')} عند {_fmt(p.get('price'))} (لمسات {p.get('count')})")
        if smc.get("summary"):
            lines.append(f"ملخّص SMC: {smc['summary']}")

    # ── مكتب الكمّ ──
    if quant:
        g = quant.get("gold") or {}
        lines.append(f"مكتب الكمّ: مركّب {_fmt(g.get('composite'),1)}/100 — {g.get('verdict','—')} | POC(H1) {_fmt(g.get('poc_h1'))}")
        fac = g.get("factors") or {}
        top = sorted(fac.items(), key=lambda kv: -abs((kv[1] or {}).get("contrib", 0)))[:3]
        if top:
            lines.append("أعلى العوامل: " + " | ".join(
                f"{k}={_fmt((v or {}).get('contrib'),1)}" for k, v in top))
        reg = quant.get("regime") or {}
        lines.append(f"النظام: مخاطرة {_fmt(reg.get('risk_onoff'),2)} | ضغط الدولار {_fmt(reg.get('dollar_pressure'),2)} | تقلّب الذهب: {reg.get('gold_vol_state','—')} (بالمئين {_fmt(reg.get('gold_vol_pctile'),0)}) | جلسة: {reg.get('session','—')}")
        groups = ((quant.get("pnl") or {}).get("groups")) or {}
        if groups:
            lines.append("أرباح اليوم بالمجموعات: " + " | ".join(
                f"{k}: {_fmt((v or {}).get('realized'),1)}$" for k, v in list(groups.items())[:6]))

    # ── حارس الذهب (سياق مستويات إضافيّ) ──
    if sent:
        lines.append(f"حارس الذهب: EMA50 {_fmt(sent.get('ema50'))} / EMA200 {_fmt(sent.get('ema200'))} | ATR {_fmt(sent.get('atr'))} | اتّجاه {sent.get('trend','—')} | سلّة: {sent.get('basket','—')}")

    # ── 🌍 خريطة العملات كاملة (كل الرموز لا الذهب فقط — طلب المستخدم) ──
    if pulse and isinstance(pulse.get("symbols"), dict):
        allsyms = [(s, d) for s, d in pulse["symbols"].items()
                   if s not in ("XAUUSDm", "XAUUSD") and isinstance(d, dict)]
        allsyms.sort(key=lambda sd: -abs(float(sd[1].get("score", 50) or 50) - 50))
        lines.append("— خريطة كل العملات (نقاط النبض 0-100، >50 صاعد) —")
        for s, d in allsyms:
            smc_t = ((d.get("smc") or {}).get("trend"))
            lines.append(f"{s}: {_fmt(d.get('score'),0)} | ترند SMC {smc_t if smc_t is not None else '—'} | {str(d.get('read') or '—')[:60]}")

    # ── خطّة قناة اليوتيوب ──
    if yt and isinstance(yt.get("plan"), dict):
        p = yt["plan"]
        tps = ", ".join(_fmt(t) for t in (p.get("tps") or [])[:3])
        lines.append(f"خطّة القناة: {p.get('direction','—')} دخول {_fmt(p.get('entry'))} وقف {_fmt(p.get('sl'))} أهداف [{tps}] | إجماع {yt.get('agree')}/{yt.get('total')} | اتّجاهها: {yt.get('trend','—')}")

    # ── الأخبار القادمة (أقرب 3) ──
    if news_events:
        for ev in news_events[:3]:
            lines.append(f"خبر قادم: {ev['title']} ({ev['currency']}, {ev['impact']}) بعد {ev['hours_to']} ساعة | توقّع {ev.get('forecast') or '—'} سابق {ev.get('previous') or '—'}")
    else:
        lines.append("لا أخبار USD مؤثّرة خلال 36 ساعة (بحسب الكاش).")

    pack = "\n".join(lines)
    return pack[:6000]  # قصٌّ آمن


# ════════════════════════ 3) استدعاء النموذج ════════════════════════

PROMPT_HEAD = (
    "أنت محلّل أسواقٍ محترف يعمل لمكتب تداولٍ خاصّ — تُغطّي كلّ العملات والمعادن والمؤشّرات، لا الذهب فقط. "
    "أمامك سياقٌ حيٌّ من أنظمتنا (نبض 17 رمزاً، مكتب الكمّ، SMC، خطّة قناة يوتيوب، تقويم الأخبار). "
    "اكتب قراءةً مهنيّة موجزة (<=430 كلمة) بأقسام: "
    "📖 القصّة الآن (الذهب + السوق العامّ)، "
    "🌍 خريطة العملات: أقوى 3 فرصٍ عبر كلّ الرموز (من خريطة النقاط — سمِّ الرمز والاتّجاه والسبب بأرقامه)، "
    "🎯 مستويات القرار (أرقام دقيقة من السياق)، "
    "⚖️ سيناريو صاعد (إن/فإن + ما يُبطله)، "
    "⚖️ سيناريو هابط (إن/فإن + ما يُبطله)، "
    "📰 مخاطر الأخبار القادمة، "
    "🧭 خلاصة سطرٍ واحد. "
    "اعتمد فقط على الأرقام المعطاة؛ لا تختلق مستويات؛ "
    "اختم بسطر الصدق: هذا تأطيرٌ للقراءة لا تنبّؤ مثبت.\n\n=== السياق الحيّ ===\n"
)


def call_claude(prompt, model):
    """استدعاء Claude CLI بلا صدفة (list-args)؛ يعيد النصّ أو None عند الفشل."""
    exe = CLAUDE if os.path.exists(CLAUDE) else (shutil.which("claude") or "claude")
    try:
        t0 = time.time()
        r = subprocess.run(
            [exe, "-p", prompt, "--model", model, "--output-format", "text"],
            capture_output=True, timeout=120, creationflags=CREATE_NO_WINDOW,
            encoding="utf-8", errors="replace")
        secs = round(time.time() - t0, 1)
        text = (r.stdout or "").strip()
        if r.returncode != 0 or not text:
            log(f"claude CLI فشل rc={r.returncode} stderr={(r.stderr or '')[:300]}")
            return None, secs
        return text, secs
    except subprocess.TimeoutExpired:
        log("claude CLI تجاوز المهلة (120 ثانية)")
        return None, 120.0
    except Exception as e:
        log(f"claude CLI خطأ: {e}")
        return None, 0.0


def run_analysis(cfg, trigger):
    """يبني السياق، يستدعي النموذج، يكتب التقرير ذرّيّاً. يعيد True عند النجاح."""
    news = load_news_events()
    pack = build_context_pack(news)
    if len(pack) < 80:
        log("سياقٌ فارغ تقريباً — تخطّي هذه الدورة")
        return False
    report, secs = call_claude(PROMPT_HEAD + pack, cfg["model"])
    if not report:
        log("لا تقرير جديد — نُبقي السابق")
        return False
    atomic_write(REPORT_PATH, {
        "ts": time.time(),
        "iso": datetime.now().isoformat(timespec="seconds"),
        "model": cfg["model"],
        "report": report,
        "news": news[:8],
        "gen_seconds": secs,
        "trigger": trigger,
    })
    log(f"تقرير جديد ({trigger}) — {len(report)} حرفاً في {secs} ثانية")
    return True


# ════════════════════════ الحلقة الرئيسة ════════════════════════

def main():
    log("=== محلّل Fable انطلق (قراءة فقط — لا تداول) ===")
    state = {"last_news": 0.0, "last_run": 0.0}
    # عند الإقلاع: لا نُعيد التوليد فوراً إن كان التقرير السابق حديثاً
    prev = read_json(REPORT_PATH)
    if prev and isinstance(prev.get("ts"), (int, float)):
        state["last_run"] = float(prev["ts"])

    while True:
        try:
            cfg = load_config()
            if not cfg.get("enabled", True):
                time.sleep(20)
                continue

            refresh_news_if_due(state, cfg)

            manual = os.path.exists(FLAG_PATH)
            if manual:
                try:
                    os.remove(FLAG_PATH)  # زرّ "حلّل الآن" من اللوحة
                except Exception:
                    pass
            interval_due = (time.time() - state["last_run"]) >= cfg["interval_min"] * 60

            if manual or interval_due:
                trigger = "manual" if manual else "interval"
                ok = run_analysis(cfg, trigger)
                # حتى عند الفشل ننتظر دقيقتين قبل إعادة المحاولة (لا قصف للـCLI)
                state["last_run"] = time.time() if ok else (
                    time.time() - cfg["interval_min"] * 60 + 120)
        except Exception as e:
            log(f"خطأ في الحلقة (نستمرّ): {e}")
        time.sleep(20)


if __name__ == "__main__":
    main()

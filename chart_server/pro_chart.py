# -*- coding: utf-8 -*-
"""chart_server/pro_chart.py — «Pro Chart» كوكبيت احترافي متعدّد الفريمات (D1/H4/H1).

النصف البياني: get_pro_data(sym) ⇒ JSON جاهز — شموع + SMC (smc_engine) + POC/HVN +
EMA50/EMA200 + VWAP + مستويات الفترات + حمولة الـIndex Chart مضمّنة للوحة المؤشّر.

قراءة-فقط من MT5 (نفس اتصال خادم chart_server — يُستدعى تحت قفل داخل المعالج).
⚖️ صدق المشروع: SMC/POC/المستويات = سياقٌ بصريّ للعين البشريّة فقط (قيست ~50% OOS
كتنبّؤ) — لا تُربط أبداً بأيّ مسار أوامر أوتوماتيكيّ. NO order_send هنا.

محاذاة المؤشّرات: compute_smc يُحسب على كامل السحب (شموع مغلقة فقط، بلا الشمعة
المتكوّنة) بينما نُصدّر آخر N شمعة — لذلك نعيد "candles_first_idx" لكلّ فريم:
local_idx_في_الرسم = smc_idx − candles_first_idx (هذا الخطأ لدغ بناء pulse سابقاً).

النقطتان: get_pro_data(sym) ⇒ dict · PRO_HTML ⇒ الصفحة (يكتبها وكيل الواجهة)."""
from __future__ import annotations

import datetime as _dt
import json as _json
import math as _math
import os as _os
import sys as _sys

import numpy as np
import MetaTrader5 as mt5

# جذر المشروع (smc_engine/level_map) + مجلّد chart_server (index_chart) على المسار
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import smc_engine  # محرّك SMC النقيّ (حساب فقط، بدون MT5)

# ملفّ مكتب الحسابات (quant_desk daemon) — قراءة ملفّ خالصة، بلا أيّ نداء MT5 إضافيّ
_DESK_PATH = _os.path.join(_ROOT, "data", "r_native", "quant_desk.json")


def _read_council():
    """🏛️ مجلس العقول المحليّ — قراءة ملفٍّ خالصة، None لو غاب."""
    try:
        with open(_os.path.join(_ROOT, "data", "r_native", "ai_council.json"), encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return None


def _read_desk():
    """يقرأ data/r_native/quant_desk.json — None لو غاب/تعطّل (الواجهة تتجاهله برشاقة)."""
    try:
        with open(_DESK_PATH, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return None


def _desk_for_symbol(sym):
    """🌍 مركّب المكتب + نسبة معرفتنا للرمز المختار (من quant_desk.symbols/knowledge) — يجعل بطاقة
    المكتب تعمل لكلّ عملة لا الذهب فقط. الذهب يحتفظ بتفصيله الكامل عبر desk.gold."""
    try:
        d = _read_desk() or {}
        comp = (d.get("symbols") or {}).get(sym)
        kn = (d.get("knowledge") or {}).get(sym)
        if comp is None and kn is None:
            return None
        return {"sym": sym, "composite": (comp or {}).get("composite"),
                "read": (comp or {}).get("read"), "knowledge": kn,
                "is_gold": sym == "XAUUSDm"}
    except Exception:
        return None


# ملفّا العقل العميق + خريطة العقل (قراءة ملفّ خالصة، بلا أيّ نداء MT5)
_DEEP_DOSSIER_PATH = _os.path.join(_ROOT, "data", "r_native", "deep_dossier.json")
_GRAPH_BRAIN_PATH = _os.path.join(_ROOT, "data", "r_native", "graph_brain.json")
_UNIFIED_BRAIN_PATH = _os.path.join(_ROOT, "data", "r_native", "unified_brain.json")


def _unified_for(sym):
    """🧠 المخ الواحد للرمز: حكمٌ مصهورٌ من كل العيون + قائمة أفضل الفرص. dict أو None."""
    try:
        with open(_UNIFIED_BRAIN_PATH, "r", encoding="utf-8") as f:
            u = _json.load(f)
        s = (u.get("symbols") or {}).get(sym)
        if not isinstance(s, dict):
            return None
        return {"sym": sym, **s, "top": u.get("top") or [],
                "evolver": u.get("evolver") or {}, "iso": u.get("iso")}
    except Exception:
        return None


def _deep_brain_for(sym):
    """🧠 قراءة العقل العميق للرمز من data/r_native/deep_dossier.json — dict أو None.
    أولاً high_conf_now[sym]، وإلا نبحث في أيّ حقل رمزٍ مطابق؛ null لو غاب. دفاعيّ تماماً:
    أيّ خطأ ⇒ None (لا يكسر الحمولة)."""
    try:
        with open(_DEEP_DOSSIER_PATH, "r", encoding="utf-8") as f:
            d = _json.load(f)
        if not isinstance(d, dict):
            return None
        updated = d.get("updated")
        rec = (d.get("high_conf_now") or {}).get(sym)
        if not isinstance(rec, dict):
            # وإلا ابحث في أيّ حقلٍ علويّ قاموسٍ يحمل الرمز مفتاحاً
            rec = None
            for v in d.values():
                if isinstance(v, dict) and isinstance(v.get(sym), dict):
                    rec = v.get(sym)
                    break
        if not isinstance(rec, dict):
            return None
        return {"sym": sym, "bias": rec.get("bias"), "call": rec.get("call"),
                "score": rec.get("score"), "align": rec.get("align"),
                "session": rec.get("session"), "with_htf": rec.get("with_htf"),
                "updated": updated}
    except Exception:
        return None


def _brain_meta():
    """🕸️ ملخّص خريطة العقل من data/r_native/graph_brain.json — dict أو None. دفاعيّ:
    {n_nodes, n_edges, kinds, hubs:[{name,deg}]×5, updated}؛ أيّ خطأ ⇒ None."""
    try:
        with open(_GRAPH_BRAIN_PATH, "r", encoding="utf-8") as f:
            g = _json.load(f)
        if not isinstance(g, dict):
            return None
        hubs = []
        for h in (g.get("hubs") or [])[:5]:
            if isinstance(h, dict):
                hubs.append({"name": h.get("name"), "deg": h.get("deg")})
        return {"n_nodes": g.get("n_nodes"), "n_edges": g.get("n_edges"),
                "kinds": g.get("kinds"), "hubs": hubs,
                "updated": g.get("updated") or g.get("iso")}
    except Exception:
        return None


# ─────────── ترقية MAX: صفقات اليوم + منحنى الرصيد + الجلسات + الأخبار + الخلاصات ───────────
# خريطة الماجيك → مجموعة عربيّة (0 = يدويّ يُعرض ولا يُلمس) · الخارجيّة تُستبعد كليّاً
_MAGIC_GROUPS = {20260631: "يوتيوب", 20260701: "حارس", 20260608: "multi",
                 20260618: "warroom", 20260614: "news", 0: "يدويّ"}
_EXTERNAL_MAGICS = {2447, 20250418, 20250421, 20250422, 20250618}   # EA المستخدم — لا تُعرض

# ملفّا الأخبار والخلاصات (قراءة ملفّ خالصة، بلا MT5)
_NEWS_EVENTS_PATH = _os.path.join(_ROOT, "data", "r_native", "news_events.json")
_FEED_FILES = [("sentinel", _os.path.join(_ROOT, "data", "r_native", "gold_sentinel_feed.jsonl")),
               ("pulse",    _os.path.join(_ROOT, "data", "r_native", "market_pulse_feed.jsonl")),
               ("desk",     _os.path.join(_ROOT, "data", "r_native", "quant_desk_feed.jsonl")),
               ("news",     _os.path.join(_ROOT, "data", "r_native", "news_alarm_feed.jsonl"))]

# جلسات السوق بساعات UTC (آسيا 00-07 · لندن 07-12 · نيويورك 12-21)
_SESSION_DEFS = [("آسيا", 0, 7), ("لندن", 7, 12), ("نيويورك", 12, 21)]


def _deal_rows():
    """صفقات اليوم من MT5 (منتصف الليل المحلّي ← الآن، بهامش ساعتين لفارق الخادم)."""
    now = _dt.datetime.now()
    frm = now.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(frm, now + _dt.timedelta(hours=2))
    if not deals:
        return []
    return sorted(deals, key=lambda d: int(d.time))


def _trades_today(deals, sym):
    """صفقاتُنا اليوم على الرمز الحاليّ: [{t,price,dir,kind,magic_group,pnl}] أحدث 60."""
    out = []
    for d in deals:
        try:
            if d.symbol != sym or int(d.magic) in _EXTERNAL_MAGICS:
                continue
            if d.type == mt5.DEAL_TYPE_BUY:
                dr = 1
            elif d.type == mt5.DEAL_TYPE_SELL:
                dr = -1
            else:
                continue                                    # إيداعات/تصحيحات — ليست صفقات
            kind = "in" if d.entry == mt5.DEAL_ENTRY_IN else "out"
            grp = _MAGIC_GROUPS.get(int(d.magic), "آخر")
            out.append({"t": int(d.time), "price": float(d.price), "dir": dr,
                        "kind": kind, "magic_group": grp,
                        "pnl": round(float(d.profit or 0.0), 2)})
        except Exception:
            continue
    return out[-60:]                                        # أحدث 60 فقط


def _equity_curve(deals):
    """مسار الرصيد المحقَّق اليوم: بداية = الرصيد − مجموع ربح اليوم، خطوة لكلّ إغلاق."""
    acct = mt5.account_info()
    if acct is None:
        return []
    closes = []
    for d in deals:
        try:
            if d.type not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                continue
            if d.entry == mt5.DEAL_ENTRY_IN:
                continue                                    # الدخول لا يُحقّق ربحاً
            pnl = float(d.profit or 0.0) + float(d.commission or 0.0) + float(d.swap or 0.0)
            closes.append((int(d.time), pnl))
        except Exception:
            continue
    eq = float(acct.balance) - sum(p for _, p in closes)    # رصيد بداية اليوم (محقَّق)
    curve = [[int(closes[0][0]) - 1 if closes else int(_dt.datetime.now().timestamp()), round(eq, 2)]]
    for t, pnl in closes:
        eq += pnl
        curve.append([t, round(eq, 2)])
    curve.append([int(_dt.datetime.now().timestamp()), round(float(acct.equity), 2)])
    return curve[-200:]                                     # أقصى 200 نقطة


def _sessions_for(tfs):
    """جلسات آسيا/لندن/نيويورك (ساعات UTC) لأيّام نافذة H1/M4 المُصدَّرة."""
    blk = tfs.get("H1") or tfs.get("M4")
    if not blk or not blk.get("candles"):
        return []
    t0, t1 = int(blk["candles"][0][0]), int(blk["candles"][-1][0])
    day = (t0 // 86400) * 86400                             # منتصف ليل UTC لليوم الأوّل
    out = []
    while day <= t1 and len(out) < 90:
        for name, h0, h1 in _SESSION_DEFS:
            out.append({"name": name, "start_epoch": day + h0 * 3600,
                        "end_epoch": day + h1 * 3600})
        day += 86400
    return out


def _news_events():
    """أحداث الأخبار بحقب مطلقة من data/r_native/news_events.json — [] لو غاب.
    news_alarm.py يكتب {"updated","count","events":[...]} — نستخرج القائمة (كان
    isinstance(list) يُعيد [] دائماً لأنّ الملفّ dict — أُصلح)."""
    try:
        with open(_NEWS_EVENTS_PATH, "r", encoding="utf-8") as f:
            ev = _json.load(f)
        if isinstance(ev, dict):
            ev = ev.get("events", [])
        return ev if isinstance(ev, list) else []
    except Exception:
        return []


def _feed_ts(o):
    """حقبة السطر: ts/epoch/t رقميّ، أو time/iso نصّيّ ISO — 0 لو تعذّر."""
    for k in ("ts", "epoch", "t", "time"):
        v = o.get(k)
        if isinstance(v, (int, float)) and v > 1e9:
            return float(v)
        if isinstance(v, str):
            try:
                return _dt.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
    return 0.0


def _feed_text(o):
    """نصّ السطر: أوّل حقلٍ نصّيّ معروف، وإلا تركيبٌ من أوائل الحقول القصيرة."""
    for k in ("text", "msg", "message", "title", "summary", "note", "event",
              "alert", "action", "signal", "verdict"):
        v = o.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:160]
    parts = []
    for k, v in o.items():
        if k in ("ts", "time", "iso", "epoch", "t") or isinstance(v, (dict, list)):
            continue
        parts.append(f"{k}:{v}")
        if len(parts) >= 4:
            break
    return " · ".join(parts)[:160]


def _tail_jsonl(path, n=12):
    """آخر n أسطر JSON صالحة من ملفّ jsonl (قراءة ذيل 64KB فقط — الملفّات قد تكبر)."""
    rows = []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 65536))
            raw = f.read().decode("utf-8", "replace")
        for line in raw.strip().splitlines()[-(n + 4):]:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                o = _json.loads(line)
                if isinstance(o, dict):
                    rows.append(o)
            except Exception:
                continue
    except Exception:
        return []
    return rows[-n:]


def _feeds_merged(n=12):
    """دمج آخر أسطر الخلاصات الأربع {src,ts,iso,text} — الأحدث أوّلاً، أقصى n."""
    merged = []
    for src, path in _FEED_FILES:
        for o in _tail_jsonl(path, n):
            ts = _feed_ts(o)
            iso = o.get("iso") if isinstance(o.get("iso"), str) else None
            if not iso and ts > 0:
                try:
                    # ISO كامل — الواجهة تقتطع [11:19] لعرض HH:MM:SS (صيغة قصيرة كانت تُمحى)
                    iso = _dt.datetime.fromtimestamp(ts).isoformat()
                except Exception:
                    iso = ""
            merged.append({"src": src, "ts": ts, "iso": iso or "",
                           "text": _feed_text(o)})
    merged.sort(key=lambda x: x["ts"], reverse=True)
    return merged[:n]


# الرموز المدعومة — أيّ رمز آخر أو مجهول ⇒ الافتراضيّ XAUUSDm
SYMBOLS = ["XAUUSDm", "XAGUSDm", "EURUSDm", "GBPUSDm", "USDJPYm",
           "AUDUSDm", "USDCHFm", "USDCADm", "NZDUSDm", "EURJPYm", "GBPJPYm",
           "BTCUSDm", "ETHUSDm", "USOILm", "US30m", "US500m", "DXYm"]   # 🌍 كل عملات النبض (17)
DEFAULT_SYM = "XAUUSDm"

# (اسم, فريم MT5, عدد السحب, عدد التصدير) — السحب أكبر ليستقرّ EMA200
_TFS = [("D1", mt5.TIMEFRAME_D1, 200, 90),
        ("H4", mt5.TIMEFRAME_H4, 220, 120),
        ("H1", mt5.TIMEFRAME_H1, 260, 160),
        ("M4", mt5.TIMEFRAME_M4, 320, 120)]   # ⚡ الدقيقة-4: لوحة التوقيت السريع (طلب المستخدم)

HONESTY = ("⚖️ SMC/POC/المستويات سياقٌ بصريّ للقراءة اليدويّة فقط — "
           "قِيست في هذا المشروع ~50% OOS كتنبّؤ (لا أفضليّة). ليست إشارة تداول.")


def _ema(a, p):
    """متوسّط أُسّيّ بسيط — مصفوفة بطول السلسلة (سببيّ)."""
    a = np.asarray(a, dtype=np.float64)
    k = 2.0 / (p + 1.0)
    e = np.empty(len(a))
    e[0] = a[0]
    for i in range(1, len(a)):
        e[i] = a[i] * k + e[i - 1] * (1.0 - k)
    return e


def _vwap(h, l, c, v):
    """VWAP تراكميّ على النافذة المُصدَّرة: Σ(سعر نموذجيّ×حجم)/Σ(حجم) — None لو الحجم كلّه صفر."""
    h = np.asarray(h, float); l = np.asarray(l, float)
    c = np.asarray(c, float); v = np.asarray(v, float)
    tv = float(v.sum())
    if tv <= 0:
        return None
    typ = (h + l + c) / 3.0
    return float((typ * v).sum() / tv)


def _round_levels(price, digits):
    """أرقامٌ مستديرة قريبة من السعر (خطوتان: ×5 و×10 من رتبة السعر)."""
    out = []
    if not price or price <= 0:
        return out
    mag = _math.floor(_math.log10(price))
    base = 10.0 ** (mag - 2)                      # ذهب 3345⇒10 · يورو 1.08⇒0.01 · BTC⇒1000
    seen = set()
    for step in (base * 5.0, base * 10.0):
        for p in (_math.floor(price / step) * step, _math.ceil(price / step) * step):
            key = round(p, digits)
            if key > 0 and key not in seen:
                seen.add(key)
                out.append({"price": float(key), "name": "رقم مستدير", "cls": "round"})
    return out


def _period_levels(sym, digits, price):
    """مستويات الفترات: قمّة/قاع اليوم والأمس (D1) + هذا الأسبوع (W1) + أرقام مستديرة."""
    out = []
    try:
        d1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 2)
        if d1 is not None and len(d1) >= 1:
            labs = [("اليوم", "day"), ("الأمس", "prev")]
            for j, (lab, cls) in enumerate(labs):
                idx = len(d1) - 1 - j
                if idx < 0:
                    continue
                out.append({"price": round(float(d1[idx]["high"]), digits),
                            "name": f"قمّة {lab}", "cls": cls})
                out.append({"price": round(float(d1[idx]["low"]), digits),
                            "name": f"قاع {lab}", "cls": cls})
    except Exception:
        pass
    try:
        w1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_W1, 0, 1)
        if w1 is not None and len(w1) >= 1:
            out.append({"price": round(float(w1[-1]["high"]), digits),
                        "name": "قمّة الأسبوع", "cls": "week"})
            out.append({"price": round(float(w1[-1]["low"]), digits),
                        "name": "قاع الأسبوع", "cls": "week"})
    except Exception:
        pass
    out.extend(_round_levels(price, digits))
    # إزالة التكرار السعريّ (الأولويّة لمستويات الفترات على الأرقام المستديرة)
    dedup, seen = [], set()
    for lv in out:
        key = round(lv["price"], digits)
        if key in seen:
            continue
        seen.add(key)
        lv["price"] = float(key)
        dedup.append(lv)
    # مناطق التقاء level_map (اختياريّ — يتجاهل بصمت لو غاب)
    try:
        import level_map
        for z in (level_map.confluence_zones(sym) or [])[:4]:
            p = z.get("price") if isinstance(z, dict) else getattr(z, "price", None)
            nm = z.get("name", "") if isinstance(z, dict) else getattr(z, "name", "")
            if p:
                dedup.append({"price": round(float(p), digits),
                              "name": ("التقاء " + str(nm))[:20], "cls": "conf"})
    except Exception:
        pass
    return sorted(dedup, key=lambda x: x["price"])


def _auto_plan(o, h, l, c, smc, digits, win_start=0):
    """🧭 خطّة تداول آليّة لكلّ فريم (على غرار مؤشّرات TradingView الشاملة):
    دخول/وقف بنيويّ/وقف متحرّك/TP1-2-3 مع «لصق ذكيّ» بالمستويات + Premium/Discount.
    دالّة نقيّة على الشموع المغلقة نفسها التي حُسب عليها SMC — بلا أيّ MT5.
    ⚖️ قانون الصدق: تأطيرٌ بصريّ فقط (~50% OOS) — لا تُربط أبداً بمسار أوامر."""
    if not isinstance(smc, dict):
        return None
    d = int(smc.get("trend") or 0)
    if d not in (1, -1):
        return None                                        # بلا ترند بنيويّ ⇒ بلا خطّة
    h = np.asarray(h, float); l = np.asarray(l, float); c = np.asarray(c, float)
    n = len(c)
    if n < 30:
        return None
    entry = float(c[-1])                                   # الدخول = آخر إغلاق
    atr = float(smc_engine._atr(h, l, c)[-1])              # ATR14 (نفس حساب المحرّك)
    if atr <= 0:
        return None

    # القمم/القيعان الفراكتاليّة (k=2) — مؤكّدة بالبناء (تحتاج k شموع بعدها)
    sw = smc_engine.swings(h, l, k=2)
    pools = smc.get("liq_pools") or []

    # ── الوقف البنيويّ: آخر قاع مؤكّد + أدنى بركة سيولة تحت السعر (للشراء) — معكوس للبيع.
    # مرشّح بنيويّ أبعد من 3.8×ATR = «لا بنية» (البركة قد تبعد 20×ATR في الترند ⇒ قمامة)
    band = 3.8 * atr
    cands = []
    if d == 1:
        lows = [p for _, p in sw["lows"] if entry - band <= p < entry]
        if lows:
            cands.append(lows[-1])
        plows = [pp["price"] for pp in pools
                 if pp.get("side") == "low" and entry - band <= float(pp.get("price", 0)) < entry]
        if plows:
            cands.append(min(plows))
        sl = (min(cands) - 0.15 * atr) if cands else (entry - 1.3 * atr)
        r = entry - sl
    else:
        highs = [p for _, p in sw["highs"] if entry < p <= entry + band]
        if highs:
            cands.append(highs[-1])
        phighs = [pp["price"] for pp in pools
                  if pp.get("side") == "high" and entry < float(pp.get("price", 0)) <= entry + band]
        if phighs:
            cands.append(max(phighs))
        sl = (max(cands) + 0.15 * atr) if cands else (entry + 1.3 * atr)
        r = sl - entry
    if r <= 0 or r > 4.0 * atr:
        return None                                        # خطّة مشوّهة ⇒ ارفض

    # ── الأهداف 1R/2R/3R مع «لصق ذكيّ»: أقرب مستوى معنويّ ضمن 0.3R من الهدف الخام
    marks = []
    if isinstance(smc.get("poc"), (int, float)):
        marks.append(float(smc["poc"]))
    for x in (smc.get("hvn") or []):
        if isinstance(x, (int, float)):
            marks.append(float(x))
    marks += [float(pp["price"]) for pp in pools if isinstance(pp.get("price"), (int, float))]
    marks += [p for _, p in sw["highs"]] + [p for _, p in sw["lows"]]
    tps = []
    for j in (1, 2, 3):
        raw = entry + d * j * r
        near = [m for m in marks if abs(m - raw) <= 0.3 * r]
        tp = min(near, key=lambda m: abs(m - raw)) if near else raw
        # حفظ الرتابة: كلّ هدف يتقدّم على سابقه وعلى الدخول، وإلا نعود للخام
        if d * (tp - entry) <= 0 or (tps and d * (tp - tps[-1]) <= 0):
            tp = raw
        tps.append(tp)

    # ── الوقف المتحرّك: آخر قاع (شراء) / آخر قمّة (بيع) — ما يستعمله المتتبّع اليدويّ الآن
    if d == 1:
        trailing = sw["lows"][-1][1] if sw["lows"] else sl
    else:
        trailing = sw["highs"][-1][1] if sw["highs"] else sl

    # ── Premium/Discount من قمّة/قاع النافذة المرئيّة: الثلث الأعلى غالٍ، الأدنى رخيص
    ws = max(0, min(int(win_start), n - 2))
    hi = float(np.max(h[ws:])); lo = float(np.min(l[ws:]))
    rng = hi - lo
    if rng <= 0:
        return None
    pd = {"hi": hi, "p_line": lo + rng * (2.0 / 3.0),
          "e_line": lo + rng * 0.5, "d_line": lo + rng * (1.0 / 3.0), "lo": lo}

    def _rd(x):
        return round(float(x), digits)

    return {"dir": d, "entry": _rd(entry), "sl": _rd(sl), "trailing": _rd(trailing),
            "tps": [_rd(t) for t in tps], "r": _rd(r),
            "pd": {k: _rd(v) for k, v in pd.items()},
            "note": "خطّة آليّة — تأطيرٌ لا توصية مثبتة"}


def _tf_block(sym, tf_mt5, pull, show, digits, levels, want_vwap):
    """كتلة فريمٍ واحد: شموع آخر show + SMC (شموع مغلقة) + POC/HVN + EMA + VWAP.
    ملاحظة المحاذاة: مؤشّرات SMC مفهرسة على كامل السحب ⇒ نعيد candles_first_idx."""
    try:
        mt5.symbol_select(sym, True)
    except Exception:
        pass
    r = mt5.copy_rates_from_pos(sym, tf_mt5, 0, pull)
    if r is None or len(r) < 30:
        return None
    n = len(r)
    show = min(show, n)
    first = n - show                                       # الإزاحة العالميّة للمُصدَّر
    o = np.asarray(r["open"], float); h = np.asarray(r["high"], float)
    l = np.asarray(r["low"], float); c = np.asarray(r["close"], float)
    v = np.asarray(r["tick_volume"], float); t = r["time"]

    # SMC على الشموع المغلقة فقط (نستبعد الشمعة المتكوّنة الأخيرة)
    try:
        smc = smc_engine.compute_smc(o[:-1], h[:-1], l[:-1], c[:-1], v[:-1])
    except Exception as e:
        smc = {"error": f"{type(e).__name__}: {e}"}

    # بروفايل الحجم على النافذة المُصدَّرة نفسها (ما تراه العين)
    try:
        poc_price, hvn = smc_engine.poc(h[first:], l[first:], c[first:], v[first:])
        poc_price = round(float(poc_price), digits)
        hvn = [round(float(x), digits) for x in hvn]
    except Exception:
        poc_price, hvn = None, []

    e50 = _ema(c, 50)
    e200 = _ema(c, 200) if n >= 200 else _ema(c, min(200, max(2, n - 1)))
    vw = _vwap(h[first:], l[first:], c[first:], v[first:]) if want_vwap else None

    # خطّة آليّة (H1/M4 فقط — إبقاء D1/H4 نظيفتين) على نفس الشموع المغلقة كما SMC
    plan = None
    if tf_mt5 in (mt5.TIMEFRAME_H1, mt5.TIMEFRAME_M4):
        try:
            plan = _auto_plan(o[:-1], h[:-1], l[:-1], c[:-1], smc, digits,
                              win_start=first)
        except Exception:
            plan = None

    candles = [[int(t[i]), round(float(o[i]), digits), round(float(h[i]), digits),
                round(float(l[i]), digits), round(float(c[i]), digits),
                float(v[i])] for i in range(first, n)]
    return {
        "candles": candles,
        "plan": plan,
        "candles_first_idx": int(first),                   # smc_idx − هذا = فهرس الرسم
        "smc": smc,
        "poc": poc_price,
        "hvn": hvn,
        "ema50": [round(float(x), digits) for x in e50[first:]],
        "ema200": [round(float(x), digits) for x in e200[first:]],
        "levels": levels,
        "vwap": (round(float(vw), digits) if vw is not None else None),
    }


def _mtf_panel(sym):
    """🦅 لوحة MTF (طلب المستخدم 2026-07-03 «سوّ اللوحة وركّز على التقلب»): انحياز 7 فريمات +
    قياس تقلب كوانتي حقيقي (σ×√T محقق + percentile تاريخي + عنقدة GARCH-lite) يعمل **فلتراً** للأنماط —
    درس فيديو الكوانت: النظام (منخفض/متوسط/عالٍ) يقرر أي استراتيجية تُسمح، لا العكس."""
    import math
    TFs = [("M1", mt5.TIMEFRAME_M1), ("M5", mt5.TIMEFRAME_M5), ("M15", mt5.TIMEFRAME_M15),
           ("M30", mt5.TIMEFRAME_M30), ("H1", mt5.TIMEFRAME_H1), ("H4", mt5.TIMEFRAME_H4),
           ("D1", mt5.TIMEFRAME_D1)]

    def _ema_last(c, n, cut=0):
        seq = c[:-cut] if cut else c
        if len(seq) < n:
            return None
        k = 2.0 / (n + 1); e = sum(seq[:n]) / float(n)
        for v in seq[n:]:
            e += k * (v - e)
        return e

    def _bias(tf):
        r = mt5.copy_rates_from_pos(sym, tf, 1, 130)
        if r is None or len(r) < 60:
            return 0
        c = [float(x) for x in r["close"]]
        e, ep = _ema_last(c, 50), _ema_last(c, 50, cut=3)
        if e is None or ep is None:
            return 0
        return 1 if (e > ep and c[-1] > e) else (-1 if (e < ep and c[-1] < e) else 0)

    biases = {n: _bias(tf) for n, tf in TFs}
    vote = sum(biases.values())
    position = "شراء" if vote >= 3 else ("بيع" if vote <= -3 else "حياد")

    # ── 🔬 قلب اللوحة: التقلب الكوانتي ──
    vol = {"realized_daily_pct": None, "pctile_30d": None, "clustering": "غير معروف",
           "regime": "غير معروف", "filter": "—"}
    r5 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 1, 289)
    if r5 is not None and len(r5) > 100:
        c = [float(x) for x in r5["close"]]
        rets = [math.log(c[i] / c[i - 1]) for i in range(1, len(c)) if c[i - 1] > 0]
        m = sum(rets) / len(rets)
        sd = (sum((x - m) ** 2 for x in rets) / max(1, len(rets) - 1)) ** 0.5
        vol["realized_daily_pct"] = round(sd * math.sqrt(288) * 100.0, 2)   # σ×√T ليوم كامل
    rh = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 1, 760)
    if rh is not None and len(rh) > 80:
        h = rh["high"]; l = rh["low"]; cc = rh["close"]
        trs = [max(float(h[i] - l[i]), abs(float(h[i] - cc[i - 1])), abs(float(l[i] - cc[i - 1])))
               for i in range(1, len(rh))]
        atrs = [sum(trs[i - 14:i]) / 14.0 for i in range(14, len(trs))]
        now_a = atrs[-1]
        pct = 100.0 * sum(1 for a in atrs if a < now_a) / len(atrs)
        vol["pctile_30d"] = round(pct, 1)
        vol["regime"] = "منخفض 😴" if pct < 30 else ("متوسط ⚖️" if pct <= 70 else "عالٍ 🌋")
        prev24 = sum(atrs[-48:-24]) / 24.0 if len(atrs) >= 48 else now_a
        last24 = sum(atrs[-24:]) / 24.0
        vol["clustering"] = ("متصاعدة 📈 (عنقدة GARCH: العاصف يجرّ عاصفاً)" if last24 > prev24 * 1.15
                             else ("متراجعة 📉" if last24 < prev24 * 0.87 else "مستقرة ➖"))
        vol["filter"] = ("قنص فقط · أهداف صغيرة (لا وقود للموجات)" if pct < 30 else
                         ("كل الأنماط مسموحة" if pct <= 70 else
                          "موجات فقط · حجم أدنى · حذر الفجوات مضاعف"))
    # حالة السوق + المؤسسات + الجلسة + ضغط الترند
    trending = abs(biases["M5"] + biases["M15"] + biases["M30"]) >= 2 and biases["H1"] != 0
    inst = "خامل"
    if rh is not None and len(rh) > 100:
        tv = [float(x) for x in rh["tick_volume"][-100:]]
        mu = sum(tv) / len(tv)
        sd2 = (sum((x - mu) ** 2 for x in tv) / 99.0) ** 0.5
        if sd2 > 0 and (tv[-1] - mu) / sd2 > 1.5:
            inst = "نشط 🏦 (حجم H1 فوق 1.5σ)"
    hr = _dt.datetime.utcnow().hour
    session = "طوكيو" if hr < 7 else ("لندن" if hr < 13 else ("نيويورك" if hr < 21 else "آسيا المتأخرة"))
    tp = biases["H4"] + biases["D1"]
    pressure = "صاعد قويّ" if tp == 2 else ("صاعد" if tp == 1 else
               ("هابط قويّ" if tp == -2 else ("هابط" if tp == -1 else "متعادل")))

    # ── 🕯️ عين تشريح الشموع — نفس معادلات radhi_mimic._candle_read حرفياً (شفافية «كيف يراها النظام») ──
    candles = None
    r1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, 20)
    if r1 is not None and len(r1) >= 14:
        bodies = [float(x["close"] - x["open"]) for x in r1]
        rngs = [max(float(x["high"] - x["low"]), 1e-9) for x in r1]
        upw = [float(x["high"]) - max(float(x["close"]), float(x["open"])) for x in r1]
        dnw = [min(float(x["close"]), float(x["open"])) - float(x["low"]) for x in r1]
        trs = [max(rngs[i], abs(float(r1[i]["high"] - r1[i - 1]["close"])),
                   abs(float(r1[i]["low"] - r1[i - 1]["close"]))) for i in range(1, len(r1))]
        a1 = sum(trs[-14:]) / 14.0 if len(trs) >= 14 else 0.5
        bias = 0; notes = []
        if all(b > 0 for b in bodies[-3:]):
            bias += 1; notes.append("3 خضر متتالية ⇒ +1 للشراء")
        elif all(b < 0 for b in bodies[-3:]):
            bias -= 1; notes.append("3 حمر متتالية ⇒ +1 للبيع")
        if any(dnw[i] >= 0.6 * rngs[i] and rngs[i] >= 0.6 * a1 for i in (-1, -2)):
            bias += 1; notes.append("ذيل رفض سفليّ (≥60% من المدى) ⇒ +1 للشراء")
        if any(upw[i] >= 0.6 * rngs[i] and rngs[i] >= 0.6 * a1 for i in (-1, -2)):
            bias -= 1; notes.append("ذيل رفض علويّ ⇒ +1 للبيع")
        if abs(bodies[-1]) > abs(bodies[-2]) and bodies[-1] * bodies[-2] < 0:
            bias += 1 if bodies[-1] > 0 else -1; notes.append("ابتلاع " + ("صاعد" if bodies[-1] > 0 else "هابط"))
        if rngs[-2] > 2 * a1 and (abs(bodies[-1]) < 0.25 * rngs[-1] or bodies[-1] * bodies[-2] < 0):
            bias += -1 if bodies[-2] > 0 else 1; notes.append("إنهاك بعد شمعة عملاقة (>2×ATR ثم دوجي/معاكسة)")
        if all(abs(b) < 0.35 * a1 for b in bodies[-5:]):
            notes.append("تجمّع انضغاطيّ (5 أجسام <0.35×ATR) — انفجار قريب")
        bias = max(-2, min(2, bias))
        rows = []
        for i in range(-5, 0):
            rows.append({"t": _dt.datetime.fromtimestamp(int(r1[i]["time"])).strftime("%H:%M"),
                         "لون": "أخضر" if bodies[i] > 0 else ("أحمر" if bodies[i] < 0 else "دوجي"),
                         "جسم$": round(bodies[i], 2), "مدى$": round(rngs[i], 2),
                         "ذيل_علوي%": round(100 * upw[i] / rngs[i]), "ذيل_سفلي%": round(100 * dnw[i] / rngs[i]),
                         "مدى/ATR": round(rngs[i] / a1, 2)})
        verdict = ("🟢 الشموع تدفع شراءً" if bias >= 1 else
                   ("🔴 الشموع تدفع بيعاً" if bias <= -1 else "⚪ حيادية"))
        candles = {"bias": bias, "verdict": verdict, "notes": notes or ["لا أنماط بارزة"],
                   "atr_m1": round(a1, 2), "rows": rows}
    return {"biases": biases, "vote": vote, "position": position,
            "market_state": ("ترند 🔥" if trending else "عرضيّ 💤"),
            "vol": vol, "institutional": inst, "session": session, "trend_pressure": pressure,
            "candles": candles}


def get_pro_data(sym: str = DEFAULT_SYM):
    """حمولة الكوكبيت الاحترافيّ متعدّد الفريمات — dict جاهز لـ JSON (أو {"error": ...})."""
    try:
        if mt5.terminal_info() is None:        # غير متّصل ⇒ هيّئ (idempotent — نفس عمليّة الخادم)
            mt5.initialize()
        # ── تحقّق الرمز: مدعوم + معروف لدى الوسيط، وإلا الافتراضيّ ──
        sym = str(sym or DEFAULT_SYM).strip()
        if sym not in SYMBOLS:
            sym = DEFAULT_SYM
        info = mt5.symbol_info(sym)
        if info is None:
            sym = DEFAULT_SYM
            info = mt5.symbol_info(sym)
        if info is None:
            return {"error": f"لا معلومات رمز من MT5 ({sym})"}
        digits = int(info.digits or 2)

        tick = mt5.symbol_info_tick(sym)
        price = float(tick.bid) if tick and tick.bid else float(info.bid or 0.0)

        levels = _period_levels(sym, digits, price)

        tfs = {}
        for name, tf_mt5, pull, show in _TFS:
            blk = _tf_block(sym, tf_mt5, pull, show, digits, levels,
                            want_vwap=(name in ("H1", "H4", "M4")))
            if blk is not None:
                tfs[name] = blk
        if not tfs:
            return {"error": f"لا شموع من MT5 للرمز {sym}"}

        # لوحة الـIndex Chart (سلّة الذهب المُعاد تأسيسها) — اختياريّة
        try:
            import index_chart
            index_payload = index_chart.get_index_data()
        except Exception:
            index_payload = None

        # ── ترقية MAX (كلّ مفتاح يتدهور إلى فارغ باستقلال — نفس اتصال MT5 تحت قفل النادي) ──
        try:
            deals = _deal_rows()
        except Exception:
            deals = []
        try:
            trades = _trades_today(deals, sym)
        except Exception:
            trades = []
        try:
            equity_curve = _equity_curve(deals)
        except Exception:
            equity_curve = []
        try:
            sessions = _sessions_for(tfs)
        except Exception:
            sessions = []
        try:
            news_events = _news_events()
        except Exception:
            news_events = []
        try:
            feeds = _feeds_merged(12)
        except Exception:
            feeds = []

        try:
            mtf = _mtf_panel(sym)
        except Exception:
            mtf = None
        return {
            "sym": sym,
            "digits": digits,
            "point": float(info.point or 0.0),
            "price": round(price, digits),
            "updated": _dt.datetime.now().strftime("%H:%M:%S"),
            "symbols": SYMBOLS,
            "mtf": mtf,
            "tfs": tfs,
            "index": index_payload,
            "desk": _read_desk(),
            "desk_sym": _desk_for_symbol(sym),        # 🌍 مركّب المكتب + معرفتنا للرمز المختار (لا الذهب فقط)
            "unified": _unified_for(sym),             # 🧠 المخ الواحد: حكمٌ مصهور من كل العيون + أفضل الفرص
            "deep_brain": _deep_brain_for(sym),       # 🧠 العقل العميق للرمز (high_conf_now) — null لو غاب
            "brain_meta": _brain_meta(),              # 🕸️ ملخّص خريطة العقل الحيّة — null لو غاب
            "council": _read_council(),
            "trades": trades,
            "equity_curve": equity_curve,
            "sessions": sessions,
            "news_events": news_events,
            "feeds": feeds,
            "honesty": HONESTY,
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# صفحة الكوكبيت الكاملة (Arabic RTL · زجاج داكن) — من وكيل الواجهة في pro_chart_html.py
from pro_chart_html import PRO_HTML  # noqa: E402

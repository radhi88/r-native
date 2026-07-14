# -*- coding: utf-8 -*-
"""news_alarm.py — منبّه أخبار دقيق (T-10min ألطف + T-60s حاد) + جسر تقويم لتسليح news_gene.

المهام (حلقة كل 5 ثوانٍ، بلا MT5، بلا تداول):
  1) يجلب تقويم ForexFactory كل ساعة (UA + مهلة 20ث؛ عند الفشل يُبقي الكاش القديم).
  2) يحدّث data/r_native/news_events.json: الأحداث القادمة (48 ساعة، عملة USD/ALL،
     أثر High+Medium) بطوابع زمنية مطلقة {title,currency,impact,epoch,iso_local,minutes_to}.
  3) إنذاران لكل حدث (مرّة واحدة، منع تكرار بالعنوان+epoch):
       • T-10min (ألطف)  ← kind:"T-10min"
       • T-60s  (حاد)    ← kind:"T-60"
     يُلحقان في data/r_native/news_alarm_feed.jsonl — يرحَّلان لهاتف المستخدم عبر Monitor.
  4) حالة كل دورة → data/r_native/news_alarm_status.json {next_event,minutes_to,armed_count,updated}.
  5) جسر news_gene: يكتب friday_v3/data/news_calendar.json بالصيغة الدقيقة التي يقرؤها
     news_engine.load_calendar():  {"fetched_at": iso, "events":[{title,country,impact,date}]}
     مع date بصيغة ISO (كاتبٌ آخر كان يتركه "07-01-2026"+"1:00pm" غير قابل للتحليل ⇒
     news_gene كان أعمى عن الأحداث). هذا الجسر يجعله يتسلّح تلقائياً للأحداث عالية الأثر.

آمن بلا نافذة (pythonw)، نسخة مفردة (engine_lock)، كتابة ذرّية (tmp+os.replace).
Run:  pythonw news_alarm.py
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
LOG = RN / "news_alarm.out.log"

if str(MT5DIR) not in sys.path:
    sys.path.insert(0, str(MT5DIR))

import urllib.request


def _daemon_setup() -> None:
    """يُستدعى فقط عند التشغيل كسكربت (لا عند الاستيراد للاختبار):
    1) نافذة-آمن: أعِد توجيه stdout/stderr أوّلاً قبل أيّ شيء (pythonw بلا stdout ⇒ تعطّل).
    2) قفل النسخة المفردة (يخرج بهدوء لو نسخة أخرى حيّة)."""
    try:
        RN.mkdir(parents=True, exist_ok=True)
        _lf = open(LOG, "a", buffering=1, encoding="utf-8")
        sys.stdout = _lf; sys.stderr = _lf
    except Exception:
        pass
    try:
        import engine_lock
        engine_lock.claim("news_alarm")
    except SystemExit:
        raise
    except Exception as _e:
        print(f"[ALARM] engine_lock غير متاح ({_e}) — متابعة بلا قفل", flush=True)

EVENTS_F = RN / "news_events.json"            # الأحداث القادمة بطوابع مطلقة
FEED_F   = RN / "news_alarm_feed.jsonl"       # الإنذارات (يرحَّل للهاتف عبر Monitor)
STATUS_F = RN / "news_alarm_status.json"      # الحالة كل دورة
SEEN_F   = RN / "news_alarm_seen.json"        # منع تكرار الإنذارات (يبقى عبر إعادة التشغيل)
GENE_CAL = MT5DIR / "friday_v3" / "data" / "news_calendar.json"  # ما يقرؤه news_gene (عبر news_engine)

FF_URL   = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
UA       = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FRIDAY-news-alarm/1.0"
LOOP_S   = 5
FETCH_S  = 3600          # إعادة الجلب كل ساعة
RETRY_S  = 300           # عند فشل الجلب: أعد المحاولة بعد 5 دقائق (لا تدقّ المصدر)
HORIZON  = 48 * 3600     # أفق 48 ساعة
CURRENCIES = {"USD", "ALL"}
IMPACTS    = {"high", "medium"}


def _atomic(path: Path, obj) -> None:
    """كتابة ذرّية: tmp ثم os.replace — لا يقرأ أحدٌ ملفاً نصفَ مكتوب."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _append_jsonl(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _load(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _epoch(s) -> float | None:
    """ISO (مع إزاحة منطقة) → epoch مطلق. أيّ صيغة أخرى ⇒ None."""
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def fetch_calendar() -> list | None:
    """جلب تقويم ForexFactory الأسبوعي. عند الفشل ⇒ None (الكاش القديم يبقى)."""
    try:
        req = urllib.request.Request(FF_URL, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = json.loads(r.read().decode("utf-8", "replace"))
        if isinstance(raw, list) and raw:
            return raw
    except Exception as e:
        print(f"[ALARM] فشل جلب التقويم: {e}", flush=True)
    return None


def bridge_gene(raw: list) -> None:
    """جسر news_gene: اكتب التقويم الكامل (كل العملات/الآثار) بصيغة news_engine الدقيقة —
    date تبقى ISO الخام من المصدر (قابلة لـ _parse_ts) وmtime طازج ⇒ load_calendar يستخدمه
    وnews_gene يتسلّح تلقائياً على كل حدث High قادم. لا نقصّه على USD لأن calendar_veto
    (فيتو كل العملات) يقرأ نفس الملف."""
    try:
        evs = [{"title": e.get("title"), "country": e.get("country"),
                "impact": e.get("impact"), "date": e.get("date")}
               for e in raw if e.get("title") and _epoch(e.get("date"))]
        _atomic(GENE_CAL, {"fetched_at": datetime.now(timezone.utc).isoformat(),
                           "events": evs,
                           "_writer": "news_alarm.py (جسر بصيغة ISO — لا تُعِد صيغة date غير ISO)"})
        print(f"[ALARM] 🪜 جسر news_gene: {len(evs)} حدثاً بصيغة ISO → {GENE_CAL.name}", flush=True)
    except Exception as e:
        print(f"[ALARM] فشل جسر news_gene: {e}", flush=True)


def build_events(raw: list, now: float) -> list[dict]:
    """رشّح: 48 ساعة قادمة، USD/ALL، High+Medium — بطوابع مطلقة."""
    out = []
    for e in raw or []:
        ccy = str(e.get("country") or "").upper()
        imp = str(e.get("impact") or "").lower()
        if ccy not in CURRENCIES or imp not in IMPACTS:
            continue
        ep = _epoch(e.get("date"))
        if ep is None or not (now - 60 <= ep <= now + HORIZON):
            continue
        out.append({"title": str(e.get("title") or "؟"),
                    "currency": ccy,
                    "impact": str(e.get("impact")),
                    "epoch": round(ep, 0),
                    "iso_local": datetime.fromtimestamp(ep).astimezone().isoformat()})
    out.sort(key=lambda x: x["epoch"])
    return out


def main() -> int:
    print(f"[ALARM] منبّه الأخبار حيّ · حلقة {LOOP_S}ث · جلب كل {FETCH_S//60} دقيقة", flush=True)
    seen: dict = _load(SEEN_F, {}) or {}
    # عند الإقلاع: استرجع الأحداث السابقة (epochs مطلقة ⇒ صالحة بعد إعادة التشغيل حتى بلا شبكة)
    events: list = (_load(EVENTS_F, {}) or {}).get("events", [])
    next_fetch = 0.0
    while True:
        try:
            now = time.time()
            iso_now = datetime.now(timezone.utc).isoformat()
            # ── 1) إعادة الجلب كل ساعة (فشل ⇒ كاش قديم يبقى + محاولة بعد 5 دقائق) ──
            if now >= next_fetch:
                raw = fetch_calendar()
                if raw:
                    next_fetch = now + FETCH_S
                    bridge_gene(raw)                      # جسر news_gene (الصيغة الدقيقة)
                    events = build_events(raw, now)
                else:
                    next_fetch = now + RETRY_S
            # ── 2) صيانة القائمة + إعادة حساب minutes_to عند الكتابة (لا قيمة قديمة) ──
            events = [e for e in events if e["epoch"] >= now - 60]
            view = [dict(e, minutes_to=round((e["epoch"] - now) / 60.0, 1)) for e in events]
            _atomic(EVENTS_F, {"updated": iso_now, "count": len(view), "events": view})
            # ── 3) الإنذارات: T-10min (ألطف) ثم T-60s (حاد) — مرّة لكل حدث ──
            fired = False
            for ev in events:
                dt = ev["epoch"] - now
                for kind, win in (("T-10min", 600), ("T-60", 60)):
                    if 0 < dt <= win:
                        key = f"{kind}|{ev['title']}|{int(ev['epoch'])}"
                        if key in seen:
                            continue
                        seen[key] = now
                        fired = True
                        _append_jsonl(FEED_F, {
                            "ts": round(now, 1), "iso": iso_now, "kind": kind,
                            "title": ev["title"], "impact": ev["impact"],
                            "currency": ev["currency"],
                            "minutes_to": 1 if kind == "T-60" else round(dt / 60.0, 1)})
                        print(f"[ALARM] 🔔 {kind} — {ev['title']} ({ev['impact']}/{ev['currency']})", flush=True)
            if fired:
                # قلّم القديم (>3 أيام) واحفظ منع التكرار
                seen = {k: v for k, v in seen.items() if now - v < 3 * 86400}
                _atomic(SEEN_F, seen)
            # ── 4) الحالة كل دورة ──
            upcoming = [e for e in view if e["epoch"] > now]
            nxt = upcoming[0] if upcoming else None
            _atomic(STATUS_F, {"next_event": nxt,
                               "minutes_to": (nxt or {}).get("minutes_to"),
                               "armed_count": len(upcoming),
                               "updated": iso_now})
        except Exception as e:
            print(f"[ALARM] err {e}", flush=True)
        time.sleep(LOOP_S)


if __name__ == "__main__":
    _daemon_setup()          # إعادة التوجيه أوّلاً ثم القفل — الاستيرادُ للاختبار لا يفعلهما
    raise SystemExit(main())

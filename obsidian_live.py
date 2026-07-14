"""obsidian_live.py — يحدّث system_map/LIVE STATUS.md بأرقام النظام الحيّة كل 10ث.

Obsidian (vault = C:\\Users\\Radhi\\MT5) يعيد تحميل الملف تلقائيًّا → ترى الحالة تتحدّث،
والـGraph View يُظهر تفاعل المكوّنات. تشغيل:  python obsidian_live.py
"""
import json, time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(r"C:\Users\Radhi\MT5")
D = ROOT / "r_native_v2" / "data"
OUT = ROOT / "system_map" / "LIVE STATUS.md"
GENE = D / "specialist" / "XAUUSDm" / "memory.json"
SDK = D / "sdk_decision.json"
GOLDOUT = D / "gold_live.out"


def _load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return {}


def build():
    now = datetime.now(timezone.utc)
    h = now.hour
    night = h >= 22 or h < 8
    g = _load(GENE); best = g.get("best", {}) or {}
    sd = _load(SDK)
    # MT5 الحيّ
    eq = bal = ml = None; p99 = p0 = 0; f99 = f0 = 0.0
    ind = {}
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
        a = mt5.account_info()
        if a: eq, bal, ml = round(a.equity, 2), round(a.balance, 2), (round(a.margin_level, 0) if a.margin_level else None)
        for p in (mt5.positions_get() or []):
            if p.magic == 99791: p99 += 1; f99 += p.profit
            elif p.magic == 0: p0 += 1; f0 += p.profit
        import chart_read as cr
        cd = cr.read_local(mt5, "XAUUSDm", "M15") or {}
        ind = {"dir": cd.get("dir"), "conf": cd.get("confluence"), "regime": cd.get("regime"), "votes": cd.get("votes", {})}
        r = mt5.copy_rates_from_pos("XAUUSDm", mt5.TIMEFRAME_M15, 0, 120)
        if r is not None and len(r) > 40:
            import live_quant as lq
            cl = [float(x["close"]) for x in r]
            ind["er"] = round(lq.efficiency_ratio(cl, len(cl) - 1, 20), 3)
    except Exception as e:
        ind["err"] = str(e)[:80]
    try:
        last = [l for l in GOLDOUT.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()][-1]
    except Exception:
        last = "—"
    dirtxt = {1: "🟢 BUY", -1: "🔴 SELL"}.get(ind.get("dir"), "🟡 NEUTRAL")
    votes = "  ".join(f"{k}{'▲' if v>0 else '▼' if v<0 else '•'}" for k, v in (ind.get("votes") or {}).items())
    md = f"""---
tags: [live, status]
---
# 📡 LIVE STATUS — {now.strftime('%Y-%m-%d %H:%M:%S')} UTC

> يتحدّث كل 10ث · جزء من [[FRIDAY System]]

## 💰 الحساب
| الإكويتي | الرصيد | مستوى الهامش |
|---|---|---|
| **${eq}** | ${bal} | {ml}% |

## ⚙️ [[gold_live]]
- صفقات البوت (99791): **{p99}** · عائم **${round(f99,2)}**
- آخر إجراء: `{last.replace('[GOLD-LIVE]','▶')}`
- [[night-discipline]]: {'🌙 ليل — لا دخول' if night else '☀️ نهار — يتداول'} (UTC {h:02d}:00)

## 🔪 يدوي (magic 0)
- صفقات: **{p0}** · عائم **${round(f0,2)}**  {'⚠️ راقب الحجم!' if p0 else ''}

## 🧬 [[gene]]
- الجيل **{g.get('generation','—')}** · {g.get('state','')} · PF {best.get('score','—')}
- نصف1 {(best.get('h1',{}) or {}).get('pf','—')} · نصف2 {(best.get('h2',{}) or {}).get('pf','—')}

## 🤖 [[friday_decision]]
- **{sd.get('bias','—')}** ثقة {sd.get('confidence','—')} · {sd.get('regime','')} · محرّك {sd.get('engine','')}

## 📊 المؤشرات اللحظيّة ([[chart_read]] · [[live_quant]])
- القرار: **{dirtxt}** · قناعة {ind.get('conf','—')} · ريجيم {ind.get('regime','—')}
- كفاءة ER: **{ind.get('er','—')}** {'(عرضي 🔴)' if (ind.get('er') or 1)<0.30 else '(ترند 🟢)'}
- أصوات: {votes or '—'}

---
*مصدر البيانات: ملفات النظام الحيّة · [[dashboards]]*
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(md, encoding="utf-8")


def main():
    print("obsidian_live → يحدّث system_map/LIVE STATUS.md كل 10ث (Ctrl-C يوقف)", flush=True)
    while True:
        try:
            build()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ حُدّث", flush=True)
        except Exception as e:
            print(f"خطأ: {e}", flush=True)
        time.sleep(10)


if __name__ == "__main__":
    main()

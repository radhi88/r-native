"""friday_autopilot.py — لوحة واحدة: "اشتغل، احمِ، وورّني ربحي". يجمع كل المُثبت في نظرة واحدة.

ليس آلة طبع نقود (لا توجد) — بل طيّار آلي صادق:
  • يتأكّد أن محرّكات الربح المُثبتة + الحرّاس + حلقات التعلّم كلها حيّة (عبر watchdog).
  • يحسب ربحك الحقيقي مقسوماً بالمصدر: بوتاتنا (مُثبتة) · يدويك (magic-0) · إكسبيرتك · أداة غامضة.
  • يقيس أمان الحساب (هامش/سحب) ويرفع علَماً: OK / WARN / CRITICAL.
  • يكتب autopilot_status.json + يطبع ملخّصاً بلمحة. أنت ترتاح وتقرأ سطراً واحداً.

الربح يأتي من البوتات المُثبتة + الانضباط — لا من التنبؤ. هذا ما يربح، لا ما يَعِد.
Run: python friday_autopilot.py --once   |   pythonw friday_autopilot.py  (loop, watchdog)
"""
from __future__ import annotations
import json, os, subprocess, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import MetaTrader5 as mt5

RN = Path(r"C:\Users\Radhi\MT5\data\r_native")
STATUS = RN / "autopilot_status.json"
CYCLE_S = 300
MT5DIR = r"C:\Users\Radhi\MT5"
PYW = MT5DIR + r"\.venv\Scripts\pythonw.exe"
_FLAGS = 0x00000008 | 0x00000200          # DETACHED | NEW_PROCESS_GROUP — windowless


def _ensure_watchdog():
    """مَن يحرس الحارس؟ هذا. autopilot يُطلَق detached فيبقى حيّاً حتى لو مات الحارس —
    فيعيد تشغيله. حلّ تبادلي: الحارس يحرس autopilot، وautopilot يحرس الحارس → لا نقطة
    فشل وحيدة داخل الجلسة (الحارس مات بصمت 41 ساعة 2026-06-18 وأظلم النظام كلّه)."""
    try:
        import psutil
        for p in psutil.process_iter(["cmdline"]):
            cl = " ".join(p.info.get("cmdline") or [])
            if "watchdog_guard" in cl and "shell-snapshot" not in cl and "keepalive" not in cl:
                return                       # الحارس حيّ
        pyw = PYW if os.path.exists(PYW) else "pythonw"
        subprocess.Popen([pyw, "watchdog_guard.py"], cwd=MT5DIR, creationflags=_FLAGS)
        print("[AUTOPILOT] ⚠️ الحارس كان ميتاً — أعدت تشغيله", flush=True)
    except Exception as e:
        print("[AUTOPILOT] ensure_watchdog err", e, flush=True)

BOT_MAGICS = {20260608, 20260612, 20260613, 20260611, 20260614, 20260616,
              99782, 99779, 99791, 20260605, 3627, 20260617, 20260618}  # محرّكاتنا (+ spike_rider 20260617)
USER_EA = {20250421, 20250422}                          # إكسبيرت QuantumShark تبعه


def _src(magic):
    if magic in BOT_MAGICS: return "bots"
    if magic == 0: return "manual_magic0"
    if magic in USER_EA: return "user_ea"
    return "other"


def snapshot():
    out = {"iso": datetime.now(timezone.utc).isoformat(), "ts": time.time()}
    if not (mt5.initialize() or mt5.initialize()):
        out["error"] = "mt5 init failed"; return out
    a = mt5.account_info(); now = datetime.now(timezone.utc)
    eq = a.equity; bal = a.balance
    ml = (eq / a.margin * 100) if a.margin > 0 else 9999
    pos = mt5.positions_get() or []
    # realized P&L by source: today + 7d
    def by_src(hours):
        d = mt5.history_deals_get(int(time.time() - hours * 3600), int(time.time())) or []
        agg = {}
        for x in d:
            if x.entry == 1:
                agg[_src(x.magic)] = agg.get(_src(x.magic), 0.0) + x.profit + x.commission + x.swap
        return {k: round(v, 1) for k, v in agg.items()}
    today = by_src(24); week = by_src(24 * 7)
    float_total = round(sum(p.profit for p in pos), 1)
    naked_manual = sum(1 for p in pos if p.magic == 0 and p.sl == 0)
    mt5.shutdown()

    # engines
    try:
        w = json.loads((RN / "watchdog_status.json").read_text(encoding="utf-8"))
        eng = {"alive": w.get("n_alive"), "total": w.get("n_total"),
               "age_s": round(time.time() - w.get("ts", 0))}
    except Exception:
        eng = {"alive": None, "total": None, "age_s": None}
    # discipline score
    try:
        g = json.loads((RN / "edge_guard.json").read_text(encoding="utf-8"))
        disc = g.get("discipline_score")
    except Exception:
        disc = None

    # safety flag
    flag = "OK"; reasons = []
    if ml < 150: flag = "CRITICAL"; reasons.append(f"هامش {ml:.0f}% قرب الخطر")
    elif ml < 300: flag = "WARN"; reasons.append(f"هامش {ml:.0f}% منخفض")
    dd = (bal - eq) / bal * 100 if bal > 0 else 0
    if dd > 20: flag = "CRITICAL"; reasons.append(f"سحب عائم {dd:.0f}%")
    elif dd > 10 and flag == "OK": flag = "WARN"; reasons.append(f"سحب عائم {dd:.0f}%")
    if naked_manual > 0 and flag == "OK": flag = "WARN"; reasons.append(f"{naked_manual} يدوي عارٍ")
    if eng.get("alive") is not None and eng["total"] and eng["alive"] < eng["total"] - 1:
        reasons.append(f"محرّكات ناقصة {eng['alive']}/{eng['total']}")

    out.update({
        "equity": round(eq, 2), "balance": round(bal, 2), "margin_level": round(ml, 0),
        "float": float_total, "open_positions": len(pos), "naked_manual": naked_manual,
        "realized_today": today, "realized_7d": week,
        "engines": eng, "discipline_score": disc,
        "safety_flag": flag, "safety_reasons": reasons,
    })
    return out


def _print(s):
    if "error" in s:
        print("[AUTOPILOT] خطأ:", s["error"]); return
    flagemoji = {"OK": "✅", "WARN": "⚠️", "CRITICAL": "🚨"}.get(s["safety_flag"], "")
    print("=" * 56)
    print(f"  FRIDAY الطيّار الآلي  ·  {s['iso'][:16]}  {flagemoji} {s['safety_flag']}")
    print("=" * 56)
    print(f"  الحقوق ${s['equity']:.0f} · الرصيد ${s['balance']:.0f} · هامش {s['margin_level']:.0f}% · عائم ${s['float']:+.0f}")
    bt = s['realized_today'].get('bots', 0); bw = s['realized_7d'].get('bots', 0)
    m0t = s['realized_today'].get('manual_magic0', 0); m0w = s['realized_7d'].get('manual_magic0', 0)
    print(f"  ربح محقّق اليوم:  بوتاتنا ${bt:+.0f} · يدويك/الأداة ${m0t:+.0f}")
    print(f"  ربح محقّق 7 أيام: بوتاتنا ${bw:+.0f} · يدويك/الأداة ${m0w:+.0f}")
    print(f"  محرّكات حيّة: {s['engines']['alive']}/{s['engines']['total']} · انضباطك: {s['discipline_score']}/100")
    if s["safety_reasons"]:
        print(f"  {flagemoji} تنبيه: " + " · ".join(s["safety_reasons"]))
    print("=" * 56)


def main():
    once = "--once" in sys.argv
    while True:
        if not once:
            _ensure_watchdog()            # حارس متبادل: لو مات الحارس أعِده
        s = snapshot()
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATUS.with_suffix(".json.tmp"); tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, STATUS)
        _print(s)
        if once:
            return s
        time.sleep(CYCLE_S)


if __name__ == "__main__":
    main()

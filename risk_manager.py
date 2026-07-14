"""risk_manager.py — FULL ISO-31000/ICA risk-management cycle as a LIVE engine, mapped from the
user's course slides (خطوات عملية إدارة المخاطر):

  1. Establish context  (تأسيس سياق العمل)   → account, session, regime, upcoming events
  2. Identify the risk  (تحديد المخاطر)      → 10 live risk detectors across the whole system
  3. Analyze the risk   (تحليل المخاطر)      → probability × impact per risk
  4. Assess/prioritize  (تقدير الأولويات)    → score → LOW/MED/HIGH/CRITICAL, sorted
  5. Treat risk         (التعامل مع المخاطر) → maps each risk to its REAL mitigation in the system
                                               (+ risk-aware lot scaling the trader obeys)
  + Monitoring & review (المراقبة والمراجعة)  → 60s loop, writes risk_register.json
  + Communication       (التواصل)            → dashboard risk command-center reads the register

Read-only on the market (no order_send). Windowless.  Run:  pythonw risk_manager.py
"""
from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
V2 = MT5DIR / "r_native_v2" / "data"
OUT = RN / "risk_register.json"
CHECK_S = 60
DAILY_KILL_PCT = 15.0
MAGICS_BOT = {20260608, 99782, 99791, 20260600, 20260605}


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _lv(score):
    return "CRITICAL" if score >= 16 else "HIGH" if score >= 9 else "MED" if score >= 4 else "LOW"


def cycle(mt5):
    now = time.time()
    acct = mt5.account_info()
    ti = mt5.terminal_info()
    pos = mt5.positions_get() or []
    # ── 1. CONTEXT ──────────────────────────────────────────────────────────
    try:
        import sys
        if str(MT5DIR / "r_native_v2") not in sys.path:
            sys.path.insert(0, str(MT5DIR / "r_native_v2"))
        from indicators import session as S
        sess = S.classify().name
    except Exception:
        sess = "?"
    news = _load(RN / "agents" / "news_signals.json", {}) or {}
    events = news.get("active_events", []) or []
    wd = _load(RN / "watchdog_status.json", {}) or {}
    ctx = {"equity": round(acct.equity, 2) if acct else 0,
           "balance": round(acct.balance, 2) if acct else 0,
           "session": sess, "open_positions": len(pos),
           "engines": f"{wd.get('n_alive', '?')}/{wd.get('n_total', '?')}"}

    # daily realized P&L (all bots)
    day0 = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    deals = [d for d in (mt5.history_deals_get(int(day0), int(now)) or []) if d.entry == 1]
    day_net = sum(d.profit + d.commission + d.swap for d in deals)
    eq = acct.equity if acct else 1.0

    # peak equity for drawdown — LOGIN-AWARE: a NEW account (login changed) must not inherit the
    # old account's peak (it froze risk at CRITICAL forever after the user opened a fresh demo).
    pk = _load(RN / "peak_equity.json", {}) or {}
    login = int(getattr(acct, "login", 0) or 0)
    if int(pk.get("login", 0) or 0) != login:
        peak = eq                                   # fresh account → fresh peak
    else:
        peak = max(float(pk.get("peak", eq) or eq), eq)
    try:
        (RN / "peak_equity.json").write_text(
            json.dumps({"peak": peak, "login": login, "ts": now}), encoding="utf-8")
    except Exception:
        pass
    dd_pct = (peak - eq) / peak * 100 if peak > 0 else 0

    # ── 2+3. IDENTIFY + ANALYZE (probability 1-5 × impact 1-5) ─────────────
    risks = []

    def R(rid, name, prob, impact, why, treat, treated):
        risks.append({"id": rid, "name": name, "prob": prob, "impact": impact,
                      "score": prob * impact, "level": _lv(prob * impact),
                      "why": why, "treatment": treat, "treated": treated})

    naked = [p for p in pos if not p.sl]
    naked_big = [p for p in naked if p.volume >= 0.1]
    R("R1", "صفقات بلا وقف خسارة", 5 if naked_big else (3 if naked else 1), 5 if naked_big else 3,
      f"{len(naked)} صفقة عارية" + (f" (منها {len(naked_big)} كبيرة!)" if naked_big else ""),
      "الحاجز الحقيقيّ = master_floor (50% كارثة) + حارس الهامش — لا وقف لكل صفقة (أسلوب المستخدم)",
      len(naked) == 0)

    dl_ratio = abs(min(0.0, day_net)) / max(1.0, eq) * 100
    R("R2", "اقتراب القتل اليومي", min(5, int(dl_ratio / 3) + 1), 4,
      f"خسارة اليوم {day_net:+.2f}$ = {dl_ratio:.1f}% من الحقوق (القتل عند {DAILY_KILL_PCT}%)",
      "DAILY_KILL في multi_trader يوقف الدخول عند 15%", dl_ratio < DAILY_KILL_PCT)

    R("R3", "السحب من القمة (Drawdown)", min(5, int(dd_pct / 8) + 1), 4,
      f"الحقوق {eq:.0f}$ تحت القمة {peak:.0f}$ بـ {dd_pct:.1f}%",
      "تقليص اللوت تلقائياً عند CRITICAL + بنح الرموز النازفة (−$8)", dd_pct < 25)

    by_sym = {}
    for p in pos:
        by_sym[p.symbol] = by_sym.get(p.symbol, 0) + 1
    conc = max(by_sym.values()) if by_sym else 0
    R("R4", "تركّز المراكز في رمز واحد", min(5, conc), 3,
      f"أقصى تكدّس: {conc} مراكز في رمز واحد" if conc else "لا تكدّس",
      "MAX_STACK_PER_SYM=4 + نفس الاتجاه فقط", conc <= 4)

    soon = [e for e in events if abs(float(e.get("minutes_to_event", 999))) <= 30]
    R("R5", "خبر عالي الأثر وشيك", 5 if soon else 1, 4,
      ("؛ ".join(f"{e.get('title','?')} بعد {e.get('minutes_to_event','?')}د" for e in soon[:2]) or "لا أحداث ±30د"),
      "فيتو التقويم يمنع الدخول ±15-20د + قراءات كلود تنتهي قبل الحدث", True)

    dead = [k for k, c in (wd.get("alive", {}) or {}).items() if c == 0]
    R("R6", "محرّكات ميتة", min(5, len(dead) + 1) if dead else 1, 3,
      f"ميّت: {dead}" if dead else "كل المحرّكات حيّة",
      "watchdog_guard يُحيي أي محرّك خلال 60 ثانية", len(dead) <= 1)

    R("R7", "التداول الآلي معطّل", 5 if (ti and not ti.trade_allowed) else 1, 5,
      "AutoTrading OFF في المنصّة!" if (ti and not ti.trade_allowed) else "مفعّل 🟢",
      "لا حماية ولا تداول بدونه — تنبيه فوري للمستخدم (زر Algo Trading)", bool(ti and ti.trade_allowed))

    margin_pct = (acct.margin / eq * 100) if (acct and eq > 0 and acct.margin) else 0
    R("R14", "استخدام الهامش", min(5, int(margin_pct / 15) + 1), 4,
      f"الهامش المستخدم {margin_pct:.1f}% من الحقوق",
      "أحجام مخاطرة-ثابتة (0.3%) + سقف لوت يتدرّج مع الحقوق", margin_pct < 40)

    hr_trades = len([d for d in deals if d.time >= now - 3600])
    R("R9", "إفراط تداول (رشّاش بلا حافة)", min(5, int(hr_trades / 15) + 1), 3,
      f"{hr_trades} صفقة مغلقة آخر ساعة",
      "بوّابة LLM analyst (يتداول المُجاز فقط) + تبريد لكل رمز", hr_trades < 30)

    bench = _load(V2 / "multi_cooldown.json", {}) or {}
    R("R10", "تداول رموز بلا حافة مثبتة", 1, 3,
      "النشر مقصور على المتخصّصين العابرين لاختبار 50k+سبريد حقيقي",
      "بوّابة OOS الصارمة + فلتر السيولة + التوجيه بالجلسات", True)

    # R12 — صحة MT5/الاتصال (من خطة ICA المتكاملة): منصة ميتة = نظام أعمى
    gold_tick = mt5.symbol_info_tick("XAUUSDm")
    tick_age = (now - gold_tick.time) if gold_tick else 9999
    mt5_ok = bool(ti) and gold_tick is not None
    R("R12", "صحة منصة MT5", 1 if (mt5_ok and tick_age < 300) else 5, 5,
      f"اتصال {'سليم' if mt5_ok else 'مفقود!'} · آخر تيك ذهب قبل {int(tick_age)}ث",
      "فحص كل 60ث + الحارس يحيي live_terminal + تنبيه فوري", mt5_ok and tick_age < 300)

    # R13 — موثوقية البيانات: ملفات القرار الحيوية يجب أن تكون طازجة
    stale = []
    for f, ttl in (("market_directive.json", 300), ("agents/news_signals.json", 600),
                   ("mode_weights.json", 3600), ("watchdog_status.json", 180)):
        d = _load(RN / f, {}) or {}
        ts_ = float(d.get("ts", 0) or (_load(RN / f, {}) or {}).get("_ts", 0) or 0)
        if now - ts_ > ttl:
            stale.append(f.split("/")[-1].replace(".json", ""))
    R("R13", "موثوقية بيانات القرار", min(5, 1 + len(stale)), 3,
      f"ملفات متقادمة: {stale}" if stale else "كل ملفات القرار طازجة",
      "كل قارئ يتجاهل الملف المتقادم (fail-safe) + الحارس يحيي الكاتب", len(stale) <= 1)

    # R8-حوكمة — نزيف الـEAs القديمة/اليدوي خارج الحكم (يُقاس من صفقات اليوم الفعلية)
    GOVERNED = {20260608, 20260611, 20260612, 20260613, 20260614, 99782}
    ungov = sum(d.profit + d.commission + d.swap for d in deals
                if d.magic not in GOVERNED)
    R("R8", "نزيف خارج الحوكمة (EAs قديمة/يدوي)", min(5, 1 + int(abs(min(0, ungov)) / max(1, eq * 0.02))), 4,
      f"صافي غير المحكوم اليوم: ${ungov:+.2f}",
      "مفصول في لوحة الحقيقة · العزل الفعلي (إزالة EA من الشارت) قرار المستخدم", ungov > -eq * 0.05)

    # R11 — الفجوة المغلقة: سقف الكتلة المترابطة (أصول تتحرك معاً = خطر واحد متنكّر)
    CLUSTERS = {"آسيا": {"USDJPYm", "JP225m", "EURJPYm", "GBPJPYm"},
                "ذهب": {"XAUUSDm", "XAUGBPm", "XAGUSDm"},
                "تك أمريكي": {"NVDAm", "TSLAm", "GOOGLm", "ORCLm", "IBMm", "MSFTm", "LLYm"}}
    cl_counts = {k: sum(1 for p in pos if p.symbol in s) for k, s in CLUSTERS.items()}
    worst_cl = max(cl_counts, key=cl_counts.get) if cl_counts else "—"
    maxcl = cl_counts.get(worst_cl, 0)
    R("R11", "تركّز كتلة مترابطة", min(5, max(1, maxcl - 2)), 3,
      f"أكبر كتلة: {worst_cl} = {maxcl} مراكز تتحرك معاً",
      "lot_mult يخنق تلقائياً عند التضخم + تكديس معطل وقت الخطر", maxcl <= 6)

    # ── 4. PRIORITIZE ────────────────────────────────────────────────────────
    risks.sort(key=lambda r: -r["score"])
    total = sum(r["score"] for r in risks)
    worst = risks[0] if risks else None
    overall = _lv(worst["score"]) if worst else "LOW"
    risk_pct = min(100, int(total / 2.5))

    # ── 5. TREAT (risk-aware sizing the trader obeys) ───────────────────────
    lot_mult = 0.4 if overall == "CRITICAL" else 0.7 if overall == "HIGH" else 1.0
    # 🚨 EMERGENCY PLAN (خطة الطوارئ من الخطة المتكاملة): محفّزات → وضع الحماية
    engines_down = sum(1 for c in (wd.get("alive", {}) or {}).values() if c == 0)
    emergency = ((peak > 0 and eq < 0.5 * peak and eq > 0)
                 or (ti and not ti.trade_allowed)
                 or engines_down >= 3)
    if emergency:
        overall = "EMERGENCY"
        lot_mult = 0.1                       # وضع الحماية: لوت 10% فقط + المنفّذون يوقفون الدخول
        try:
            (RN / "EMERGENCY_LOG.jsonl").open("a", encoding="utf-8").write(
                json.dumps({"ts": now, "eq": eq, "peak": peak,
                            "autotrading": bool(ti and ti.trade_allowed),
                            "engines_down": engines_down}, ensure_ascii=False) + "\n")
        except Exception:
            pass

    out = {"ts": now, "iso": datetime.now(timezone.utc).isoformat(),
           "context": ctx, "day_net": round(day_net, 2), "dd_pct": round(dd_pct, 1),
           "risks": risks, "overall": overall, "risk_pct": risk_pct,
           "lot_mult": lot_mult,
           "cycle": ["تأسيس السياق ✓", "تحديد المخاطر ✓", "تحليل (احتمال×أثر) ✓",
                     "ترتيب الأولويات ✓", "المعالجة ✓", "مراقبة كل 60ث ✓", "تواصل عبر اللوحة ✓"]}
    out["emergency"] = emergency
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, OUT)
    # context_dna.json — تأسيس السياق (ICA خطوة 1) بصيغة الخطة المتكاملة + عدّاد أجيال
    try:
        prev_g = int((_load(RN / "context_dna.json", {}) or {}).get("generation", 0))
        mw = (_load(RN / "mode_weights.json", {}) or {}).get("modes", {})
        ctx_dna = {
            "timestamp": out["iso"], "generation": prev_g + 1,
            "market_context": {"session": sess,
                               "spread_status": "ok" if not [r for r in risks if r["id"] == "R3" and r["level"] in ("HIGH", "CRITICAL")] else "wide"},
            "portfolio_context": {"equity": eq, "peak": round(peak, 2),
                                  "drawdown_pct": round(dd_pct, 1),
                                  "daily_pnl": round(day_net, 2),
                                  "open_positions": len(pos)},
            "strategy_context": {"active_modes": [m for m, v in mw.items() if not v.get("disabled")],
                                 "disabled_modes": [m for m, v in mw.items() if v.get("disabled")]},
            "external_context": {"risk_level": overall, "lot_mult": lot_mult},
            "system_context": {"engines": ctx.get("engines"),
                               "mt5_status": "OK" if (ti and ti.trade_allowed) else "BLOCKED",
                               "emergency": emergency},
        }
        tmp2 = (RN / "context_dna.json").with_suffix(".json.tmp")
        tmp2.write_text(json.dumps(ctx_dna, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp2, RN / "context_dna.json")
    except Exception:
        pass
    return out


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    print("[RISK] ICA cycle live — identify→analyze→prioritize→treat→monitor", flush=True)
    while True:
        try:
            o = cycle(mt5)
            top = o["risks"][0]
            print(f"[RISK] {o['overall']} ({o['risk_pct']}%) · أعلى خطر: {top['name']} ({top['level']}) · lot×{o['lot_mult']}", flush=True)
        except Exception as e:
            print(f"[RISK] err {e}", flush=True)
        time.sleep(CHECK_S)


if __name__ == "__main__":
    raise SystemExit(main())

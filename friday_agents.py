#!/usr/bin/env python3
"""
FRIDAY Multi-Agent Swarm — 6 متخصصين + منسق رئيسي
كل وكيل يملك خبرة كلود في مجاله، يعمل بدون API tokens
يكتب حالته كل 5 ثواني إلى friday_agents.json
"""

import threading, time, json, math, random, os
from datetime import datetime
from pathlib import Path

# ── مسارات الملفات ───────────────────────────────────────
MT5_DIR = Path(os.path.expanduser(
    r"~\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
))
AGENTS_FILE  = MT5_DIR / "friday_agents.json"
STATUS_FILE  = MT5_DIR / "ea_realtime_status.json"
DNA_FILE     = MT5_DIR / "gold_dna_memory.csv"
BRAIN_LOG    = MT5_DIR / "friday_brain_log.json"

# ── كود EA المُنتج — يُحدّث بعد كل تجربة ──────────────
EA_CODE_FILE = Path(r"C:\Users\Radhi\MT5") / "friday_best_ea_code.json"

def ts():
    return datetime.now().strftime("%H:%M:%S")

def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except:
        return {}

def read_status():
    data = read_json(STATUS_FILE)
    if data:
        return data
    # fallback — try bar history
    for alt in ["ea_bar_history.json", "friday_realtime_bar.json"]:
        d = read_json(MT5_DIR / alt)
        if d:
            return d
    return {}

def read_dna_records():
    try:
        lines = DNA_FILE.read_text(encoding="utf-8").strip().split("\n")
        records = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) >= 6:
                try:
                    records.append({
                        "gen":     int(parts[0]),
                        "gap":     float(parts[1]),
                        "tp":      float(parts[2]),
                        "sl":      float(parts[3]),
                        "pf":      float(parts[4]),
                        "fitness": float(parts[5]),
                    })
                except:
                    pass
        return records
    except:
        return []

def append_brain(agent_name, thought, decision):
    try:
        log = read_json(BRAIN_LOG) if BRAIN_LOG.exists() else []
        if not isinstance(log, list):
            log = []
        log.append({
            "timestamp": ts(),
            "source": agent_name,
            "thought": thought,
            "decision": decision,
        })
        BRAIN_LOG.write_text(
            json.dumps(log[-200:], ensure_ascii=False),
            encoding="utf-8"
        )
    except:
        pass


# ════════════════════════════════════════════════════════
#  Base Agent
# ════════════════════════════════════════════════════════
class Agent:
    def __init__(self, name, role, emoji, interval=20):
        self.name     = name
        self.role     = role
        self.emoji    = emoji
        self.interval = interval
        self.score    = 0
        self.decisions_count = 0
        self.running  = True
        self._lock    = threading.Lock()
        self._state   = {
            "name": name, "role": role, "emoji": emoji,
            "status": "تهيؤ", "thought": "أبدأ...",
            "decision": "—", "confidence": 0, "score": 0,
            "params": {}, "last_update": ts(),
            "decisions_count": 0,
            "recent_decisions": [],
        }
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def get_state(self):
        with self._lock:
            return dict(self._state)

    def _update(self, **kw):
        with self._lock:
            self._state.update(kw)
            self._state["last_update"] = ts()

    def _loop(self):
        time.sleep(random.uniform(1, 6))
        while self.running:
            try:
                market = read_status()
                result = self.think(market)
                self.decisions_count += 1
                recent = self._state["recent_decisions"][-9:] + [{
                    "t": ts(),
                    "d": result.get("decision", "—"),
                    "c": result.get("confidence", 50),
                }]
                self._update(
                    status="نشط",
                    thought=result.get("thought", ""),
                    decision=result.get("decision", "—"),
                    confidence=result.get("confidence", 50),
                    params=result.get("params", {}),
                    score=self.score,
                    decisions_count=self.decisions_count,
                    recent_decisions=recent,
                )
                if result.get("log", True):
                    append_brain(
                        self.role,
                        result.get("thought", ""),
                        result.get("decision", "—"),
                    )
            except Exception as e:
                self._update(status=f"خطأ: {str(e)[:40]}")
            time.sleep(self.interval)

    def think(self, market) -> dict:
        raise NotImplementedError

    def reward(self, pts):
        self.score += pts

    def start(self):
        self._thread.start()
        return self


# ════════════════════════════════════════════════════════
#  وكيل 1 — محلل الفجوة  📐
# ════════════════════════════════════════════════════════
class GapAnalyst(Agent):
    def __init__(self):
        super().__init__("gap_analyst", "محلل الفجوة", "📐", interval=22)

    def think(self, market):
        cur        = market.get("current", market)
        gap        = float(cur.get("dna_gap", 500) or 500)
        spread     = float(cur.get("spread_points", 30) or 30)
        atr        = float(cur.get("atr_points", 150) or 150)
        loss_streak= int(cur.get("loss_streak", 0) or 0)
        win_streak = int(cur.get("win_streak", 0) or 0)
        agm        = cur.get("agm", {}) or {}

        ideal_min = max(spread * 3.2, 120)
        ideal_max = atr * 0.85

        if agm.get("locked"):
            best_gap = agm.get("best_gap", gap)
            thought  = (f"AGM قفل الفجوة على {best_gap}pt بعد اختبار 3 مرشحين. "
                        f"الفجوة المثالية المحسوبة [{ideal_min:.0f}–{ideal_max:.0f}]pt. "
                        f"{'متوافق ✓' if ideal_min <= best_gap <= ideal_max else 'خارج النطاق ⚠️'}.")
            decision = f"AGM مقفل: {best_gap}pt"
            confidence = 88
            params = {}
            self.reward(3)
        elif gap < ideal_min:
            new_gap  = int(ideal_min * 1.15)
            thought  = (f"الفجوة {gap:.0f}pt أصغر من الحد الأدنى الآمن {ideal_min:.0f}pt "
                        f"(سبريد×3.2). يسبب ضربات ستوب متكررة. أوصي برفعها إلى {new_gap}pt.")
            decision = f"رفع الفجوة → {new_gap}pt"
            confidence = 84
            params = {"gap": new_gap}
            self.reward(5)
        elif gap > ideal_max and atr > 80:
            new_gap  = int(ideal_max * 0.82)
            thought  = (f"الفجوة {gap:.0f}pt أكبر من ATR×0.85={ideal_max:.0f}pt. "
                        f"يُفوّت حركات. خفّض إلى {new_gap}pt.")
            decision = f"تخفيض الفجوة → {new_gap}pt"
            confidence = 76
            params = {"gap": new_gap}
            self.reward(3)
        elif loss_streak >= 3:
            new_gap  = int(min(gap + 180, 1500))
            thought  = (f"سلسلة خسائر {loss_streak}. السوق عشوائي. "
                        f"أُوسّع الفجوة مؤقتاً {gap:.0f}→{new_gap}pt.")
            decision = f"توسيع دفاعي → {new_gap}pt"
            confidence = 79
            params = {"gap": new_gap}
            self.reward(2)
        elif win_streak >= 4:
            thought  = (f"سلسلة مكاسب {win_streak} متتالية. الفجوة {gap:.0f}pt تعمل بامتياز. "
                        f"لا تغيير. ATR={atr:.0f} سبريد={spread:.0f}.")
            decision = "الفجوة مثالية ✓"
            confidence = 90
            params = {}
            self.reward(4)
        else:
            thought  = (f"الفجوة {gap:.0f}pt ضمن النطاق [{ideal_min:.0f}–{ideal_max:.0f}]pt. "
                        f"ATR={atr:.0f} سبريد={spread:.0f}. مستقرة.")
            decision = "الفجوة مستقرة"
            confidence = 67
            params = {}

        return {"thought": thought, "decision": decision,
                "confidence": confidence, "params": params}


# ════════════════════════════════════════════════════════
#  وكيل 2 — قارئ السوق  📊
# ════════════════════════════════════════════════════════
class MarketReader(Agent):
    def __init__(self):
        super().__init__("market_reader", "قارئ السوق", "📊", interval=18)
        self._last_mode = -1

    def think(self, market):
        cur     = market.get("current", market)
        candles = market.get("candles", [])

        rsi    = float(cur.get("rsi", 50) or 50)
        atr    = float(cur.get("atr_points", 150) or 150)
        spread = float(cur.get("spread_points", 30) or 30)
        mode   = int(cur.get("market_mode", 0) or 0)
        mode_s = "سوينق 📈" if mode == 1 else "سكالبينج ⚡"

        # trend from last 5 candles
        closes = [float(c.get("close", 0)) for c in candles[-5:] if c.get("close")]
        if len(closes) >= 3:
            trend = "صاعد ↑" if closes[-1] > closes[0] else "هابط ↓"
            momentum = abs(closes[-1] - closes[0])
        else:
            trend, momentum = "محايد", 0

        mode_changed = mode != self._last_mode and self._last_mode != -1
        self._last_mode = mode

        if spread > 85:
            thought  = (f"⛔ سبريد {spread:.0f}pt — خطر! السبريد يأكل الأرباح. "
                        f"أُوصي بتوقف التداول حتى ينخفض تحت 60pt.")
            decision = "توقف — سبريد خطير"
            confidence = 93
            self.reward(-3)
        elif rsi > 73:
            thought  = (f"تشبع شرائي RSI={rsi:.0f}. الاتجاه {trend} وضع {mode_s}. "
                        f"احتمال تصحيح. انتظر قبل شراء.")
            decision = "حذر شراء — RSI مرتفع"
            confidence = 82
        elif rsi < 27:
            thought  = (f"تشبع بيعي RSI={rsi:.0f}. الاتجاه {trend}. "
                        f"فرصة شراء محتملة عند تأكيد الانعكاس.")
            decision = "مراقبة فرصة شراء"
            confidence = 79
        elif mode_changed:
            thought  = (f"⚡ تغير الوضع! الآن {mode_s}. "
                        f"{'ضَع أهدافاً أبعد '+str(int(atr*3))+'pt' if mode==1 else 'أسرع خروج '+str(int(atr*1.2))+'pt'}.")
            decision = f"تكيّف مع {mode_s}"
            confidence = 85
            self.reward(5)
        elif mode == 1:
            thought  = (f"سوينق نشط. ATR={atr:.0f}pt. هدف مقترح {atr*2.8:.0f}pt، ستوب {atr*1.6:.0f}pt. "
                        f"الاتجاه {trend}.")
            decision = f"سوينق: TP {atr*2.8:.0f}pt"
            confidence = 75
        else:
            thought  = (f"سوق طبيعي. RSI={rsi:.0f} ATR={atr:.0f}pt سبريد={spread:.0f}pt. "
                        f"اتجاه {trend} زخم={momentum:.1f}.")
            decision = "السوق متوازن ✓"
            confidence = 68

        return {"thought": thought, "decision": decision,
                "confidence": confidence, "params": {"rsi": rsi, "atr": atr}}


# ════════════════════════════════════════════════════════
#  وكيل 3 — حارس المخاطر  🛡️
# ════════════════════════════════════════════════════════
class RiskGuardian(Agent):
    def __init__(self):
        super().__init__("risk_guardian", "حارس المخاطر", "🛡️", interval=20)

    def think(self, market):
        cur     = market.get("current", market)
        metrics = market.get("metrics", {})

        loss_streak = int(cur.get("loss_streak", 0) or 0)
        pf          = float(metrics.get("profit_factor",
                            cur.get("profit_factor", 1.0)) or 1.0)
        dd          = float(metrics.get("max_drawdown_pct", 0) or 0)
        tp          = float(cur.get("dna_tp", 2.0) or 2.0)
        sl          = float(cur.get("dna_sl", 8.0) or 8.0)
        balance     = float(cur.get("balance", 0) or 0)
        equity      = float(cur.get("equity", balance) or balance)
        live_dd     = ((balance - equity) / balance * 100) if balance > 0 else 0

        if dd > 22 or live_dd > 18:
            worst = max(dd, live_dd)
            thought  = (f"🚨 انهيار {worst:.1f}%! حد الخطر تجاوز. "
                        f"SL الحالي {sl:.1f}$ يجب تقليصه. إيقاف فوري مطلوب.")
            decision = "⛔ إيقاف فوري — انهيار حاد"
            confidence = 97
            params = {"sl": max(tp+1, sl*0.65), "cooldown_minutes": 60}
            self.reward(-15)
        elif loss_streak >= 5:
            thought  = (f"سلسلة {loss_streak} خسائر متتالية. PF={pf:.2f}. "
                        f"النظام في أزمة. أرفع الراحة وأُقلّص الخطر.")
            decision = f"راحة إجبارية 45min — {loss_streak} خسائر"
            confidence = 90
            params = {"sl": max(tp+1.5, sl-1.0), "cooldown_minutes": 45}
            self.reward(-8)
        elif pf < 0.75 and dd > 12:
            thought  = (f"PF={pf:.2f} ضعيف مع سحب {dd:.1f}%. النظام يخسر أكثر مما يربح. "
                        f"أُعيد معايرة SL/TP.")
            decision = "تقليص مخاطر — PF حرج"
            confidence = 84
            params = {"sl": max(tp+1, sl-0.5)}
            self.reward(-4)
        elif sl <= tp * 1.15:
            thought  = (f"⚠️ SL={sl:.1f}$ أصغر من TP×1.15={tp*1.15:.1f}$! قاعدة أساسية مكسورة. "
                        f"يجب SL > TP دائماً.")
            decision = f"إصلاح SL → {tp*2:.1f}$"
            confidence = 98
            params = {"sl": tp * 2.0}
            self.reward(-2)
        elif pf > 1.9 and loss_streak == 0 and dd < 8:
            thought  = (f"✅ أداء استثنائي! PF={pf:.2f} DD={dd:.1f}% صفر خسائر متتالية. "
                        f"يمكن رفع TP تدريجياً.")
            decision = f"رفع TP → {min(tp+0.5, 8.0):.1f}$"
            confidence = 86
            params = {"tp": min(tp + 0.5, 8.0)}
            self.reward(10)
        else:
            thought  = (f"المخاطر ضمن الحدود. PF={pf:.2f} DD={dd:.1f}% "
                        f"SL/TP={sl:.1f}/{tp:.1f}$ خسائر={loss_streak}.")
            decision = "المخاطر متوازنة ✓"
            confidence = 74
            params = {}
            self.reward(2)

        return {"thought": thought, "decision": decision,
                "confidence": confidence, "params": params}


# ════════════════════════════════════════════════════════
#  وكيل 4 — مطور الجينات  🧬
# ════════════════════════════════════════════════════════
class DNADeveloper(Agent):
    def __init__(self):
        super().__init__("dna_developer", "مطور الجينات", "🧬", interval=35)
        self.best_fitness   = 0.0
        self.tested_combos  = []

    def think(self, market):
        records = read_dna_records()
        cur     = market.get("current", market)
        metrics = market.get("metrics", {})

        pf     = float(metrics.get("profit_factor", 1.0) or 1.0)
        trades = int(metrics.get("total_trades", 0) or 0)
        dd     = float(metrics.get("max_drawdown_pct", 0) or 0)
        gap    = float(cur.get("dna_gap", 500) or 500)
        tp     = float(cur.get("dna_tp", 2.0) or 2.0)
        sl     = float(cur.get("dna_sl", 8.0) or 8.0)

        fitness = pf * math.sqrt(max(trades, 1)) * (1.0 - dd / 100.0)

        if fitness > self.best_fitness:
            self.best_fitness = fitness
            self.reward(8)
            # سجّل أفضل كومبو
            self.tested_combos.append({
                "gap": gap, "tp": tp, "sl": sl,
                "fitness": round(fitness, 3),
                "pf": round(pf, 2),
                "t": ts(),
            })
            self.tested_combos = sorted(
                self.tested_combos, key=lambda x: x["fitness"], reverse=True
            )[:10]

        gen_count = len(records)

        if gen_count == 0:
            thought  = "لا يوجد DNA محفوظ بعد. أنتظر أول بيانات لبدء التعلم."
            decision = "انتظار بيانات أولى"
            confidence = 35
        elif gen_count < 5:
            thought  = (f"جمعت {gen_count} جيل. أحتاج 10+ للمقارنة الدقيقة. "
                        f"الفتنس الحالي={fitness:.2f}.")
            decision = f"تجميع بيانات {gen_count}/10"
            confidence = 52
        else:
            best = max(records, key=lambda r: r["fitness"])
            top3 = sorted(records, key=lambda r: r["fitness"], reverse=True)[:3]
            top3_str = " | ".join(
                f"G{r['gen']} Gap={r['gap']:.0f} PF={r['pf']:.2f}" for r in top3
            )
            if fitness >= best["fitness"] * 0.92:
                thought  = (f"✅ DNA حالي ممتاز (Fitness={fitness:.2f} vs Best={best['fitness']:.2f}). "
                            f"أفضل 3: {top3_str}.")
                decision = f"DNA مثالي Gen={gen_count}"
                confidence = 85
                self.reward(5)
            else:
                diff = best["fitness"] - fitness
                thought  = (f"DNA الحالي (Fitness={fitness:.2f}) أقل من الأفضل بـ {diff:.2f}. "
                            f"أُوصي بإعدادات Gen{best['gen']}: Gap={best['gap']:.0f} TP={best['tp']:.2f}$.")
                decision = f"ارجع لـ Gen{best['gen']} — Fitness أعلى"
                confidence = 78

        params = {
            "fitness": round(fitness, 2),
            "generations": gen_count,
            "best_fitness": round(self.best_fitness, 2),
            "best_combos": self.tested_combos[:3],
        }
        return {"thought": thought, "decision": decision,
                "confidence": confidence, "params": params}


# ════════════════════════════════════════════════════════
#  وكيل 5 — مبتكر الاستراتيجيات  🔬
# ════════════════════════════════════════════════════════
class StrategyInventor(Agent):
    def __init__(self):
        super().__init__("strategy_inventor", "مبتكر الاستراتيجيات", "🔬", interval=38)
        self.inventions  = []
        self.last_mode   = -1
        self.trial_count = 0

    def _invent(self, atr, spread, pf, mode):
        pool = [
            {
                "name": "فجوة ATR الديناميكية",
                "desc": f"فجوة={atr*0.55:.0f}pt عند ATR منخفض، {atr*1.25:.0f}pt عند مرتفع",
                "code_hint": "gap = base_atr * (0.55 if atr_ratio < 1.0 else 1.25)",
            },
            {
                "name": "فلتر السبريد الذكي",
                "desc": f"توقف عند سبريد>{spread*2.2:.0f}pt، استأنف عند<{spread*0.8:.0f}pt",
                "code_hint": f"if spread > {spread*2.2:.0f}: skip_entry()",
            },
            {
                "name": "التوقف التكيفي",
                "desc": f"بعد 3 خسائر → راحة 30min ثم فجوة +{atr*0.45:.0f}pt",
                "code_hint": "if loss_streak >= 3: cooldown=1800; gap += atr*0.45",
            },
            {
                "name": "الاستهداف المتدرج",
                "desc": f"TP1={atr:.0f}pt (50%) + TP2={atr*2:.0f}pt (30%) + TP3={atr*4:.0f}pt (20%)",
                "code_hint": "partial_close([0.5, 0.3, 0.2], [atr, atr*2, atr*4])",
            },
            {
                "name": "عكس الاتجاه المفاجئ",
                "desc": f"عند RSI>74 أو <26 → عكس اتجاه الدخول مؤقتاً",
                "code_hint": "if rsi > 74: direction = -direction",
            },
            {
                "name": "نظام المكافأة التراكمية",
                "desc": f"بعد 5 مكاسب → رفع حجم اللوت ×1.15، بعد 3 خسائر → تصفير",
                "code_hint": "lot_factor = 1.15 ** win_streak if win_streak>0 else 1.0",
            },
        ]
        return random.choice(pool)

    def think(self, market):
        cur     = market.get("current", market)
        metrics = market.get("metrics", {})

        mode        = int(cur.get("market_mode", 0) or 0)
        pf          = float(metrics.get("profit_factor", 1.0) or 1.0)
        loss_streak = int(cur.get("loss_streak", 0) or 0)
        atr         = float(cur.get("atr_points", 150) or 150)
        spread      = float(cur.get("spread_points", 30) or 30)

        mode_changed = (mode != self.last_mode and self.last_mode != -1)
        self.last_mode = mode
        self.trial_count += 1

        if loss_streak >= 4 or pf < 0.65:
            inv = self._invent(atr, spread, pf, mode)
            self.inventions.append({"t": ts(), **inv, "trigger": "performance"})
            thought  = (f"أداء ضعيف (PF={pf:.2f} خسائر={loss_streak}). "
                        f"أبتكر: [{inv['name']}] — {inv['desc']}")
            decision = f"اختبر: {inv['name']}"
            confidence = 73
            self.reward(5)
        elif mode_changed:
            inv = self._invent(atr, spread, pf, mode)
            self.inventions.append({"t": ts(), **inv, "trigger": "mode_change"})
            thought  = (f"تغيّر الوضع → {'سوينق' if mode==1 else 'سكالبينج'}. "
                        f"استراتيجية مقترحة: [{inv['name']}] — {inv['desc']}")
            decision = f"تكيّف: {inv['name']}"
            confidence = 78
        elif self.trial_count % 8 == 0:
            inv = self._invent(atr, spread, pf, mode)
            self.inventions.append({"t": ts(), **inv, "trigger": "periodic"})
            thought  = (f"مراجعة دورية (جلسة #{self.trial_count}). "
                        f"فكرة جديدة: [{inv['name']}] — {inv['desc']}")
            decision = f"فكرة: {inv['name']}"
            confidence = 62
        else:
            thought  = (f"PF={pf:.2f} ATR={atr:.0f}pt. أراقب وأجمع بيانات. "
                        f"لديّ {len(self.inventions)} ابتكار مسجّل.")
            decision = "مراقبة مستمرة"
            confidence = 58

        return {
            "thought": thought, "decision": decision, "confidence": confidence,
            "params": {
                "inventions_count": len(self.inventions),
                "latest_invention": self.inventions[-1] if self.inventions else None,
            },
        }


# ════════════════════════════════════════════════════════
#  وكيل 6 — محلل الكود  💻
# ════════════════════════════════════════════════════════
class CodeAnalyst(Agent):
    """يُنتج أفضل كود EA بناءً على البيانات الحية ويحفظه"""

    TEMPLATE = """// ══════════════════════════════════════════════════════
// FRIDAY GOLD EA — نسخة مُنتجة بالذكاء الجماعي للوكلاء
// التاريخ: {date}  |  Fitness: {fitness}  |  PF: {pf}
// ══════════════════════════════════════════════════════
input int    ExtraTightGapPoints   = {gap};      // نقاط الفجوة (مُحسَّن)
input double BasketTakeProfitMoney = {tp};       // هدف السلة $
input double BasketStopLossMoney   = {sl};       // ستوب السلة $
input int    CooldownMinutes       = {cooldown}; // راحة بعد الخسارة

// ── استراتيجية AGM ──────────────────────────────────
// يختبر 3 فجوات (×0.75 / ×1.0 / ×1.6 من DNA)
// يختار الأفضل بناءً على: PnL - hits×0.08
// يقفل بعد 60 بار ويُعيد الاختبار تلقائياً

// ── وضع السوق ────────────────────────────────────────
// SCALP: ATR14 ≤ ATR60×1.4 → فجوة أصغر، TP={tp_scalp:.1f}$
// SWING: ATR14 > ATR60×1.4 → فجوة أكبر، TP={tp_swing:.1f}$

// ── FastProfitLock ───────────────────────────────────
// عند أي ربح: حرّك SL إلى BreakEven فوراً
// SWING: اضبط TP على ATR×3

// ── إشارة الوكلاء ────────────────────────────────────
// RSI_threshold_buy  = 27   (تشبع بيعي)
// RSI_threshold_sell = 73   (تشبع شرائي)
// Spread_max         = {spread_max:.0f} pts
// ATR_factor_sl      = 1.3
// ATR_factor_tp1     = 1.2
// ATR_factor_tp2     = 2.8
// ATR_factor_tp3     = 5.0
"""

    def __init__(self):
        super().__init__("code_analyst", "محلل الكود", "💻", interval=45)
        self.best_code = None
        self.best_fitness = 0.0
        self.versions = []

    def think(self, market):
        cur     = market.get("current", market)
        metrics = market.get("metrics", {})
        records = read_dna_records()

        pf      = float(metrics.get("profit_factor", 1.0) or 1.0)
        trades  = int(metrics.get("total_trades", 0) or 0)
        dd      = float(metrics.get("max_drawdown_pct", 0) or 0)
        gap     = float(cur.get("dna_gap", 500) or 500)
        tp      = float(cur.get("dna_tp", 2.0) or 2.0)
        sl      = float(cur.get("dna_sl", 8.0) or 8.0)
        atr     = float(cur.get("atr_points", 150) or 150)
        spread  = float(cur.get("spread_points", 30) or 30)

        fitness = pf * math.sqrt(max(trades, 1)) * (1.0 - dd / 100.0)

        # merge best DNA record params if available
        if records:
            best_rec = max(records, key=lambda r: r["fitness"])
            if best_rec["fitness"] > fitness:
                gap = best_rec["gap"]
                tp  = best_rec["tp"]
                sl  = best_rec["sl"]
                fitness = best_rec["fitness"]

        code = self.TEMPLATE.format(
            date=datetime.now().strftime("%Y-%m-%d %H:%M"),
            fitness=round(fitness, 3),
            pf=round(pf, 2),
            gap=int(gap),
            tp=round(tp, 2),
            sl=round(sl, 2),
            cooldown=15,
            tp_scalp=round(tp, 2),
            tp_swing=round(tp * 2.5, 2),
            spread_max=round(spread * 2, 0),
        )

        if fitness > self.best_fitness:
            self.best_fitness = fitness
            self.best_code = code
            self.versions.append({
                "t": ts(), "fitness": round(fitness, 3),
                "gap": int(gap), "tp": round(tp, 2), "sl": round(sl, 2),
                "pf": round(pf, 2), "trades": trades,
            })
            self.versions = self.versions[-20:]
            self.reward(8)
            try:
                EA_CODE_FILE.write_text(
                    json.dumps({
                        "code": code,
                        "params": {"gap": int(gap), "tp": round(tp, 2),
                                   "sl": round(sl, 2), "fitness": round(fitness, 3)},
                        "versions": self.versions[-5:],
                        "updated": ts(),
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
            except:
                pass

        thought  = (f"أُنتجت نسخة كود بـ Fitness={fitness:.2f} PF={pf:.2f} "
                    f"Gap={gap:.0f} TP={tp:.2f}$. "
                    f"{'🏆 أفضل نسخة حتى الآن!' if fitness >= self.best_fitness else f'الأفضل={self.best_fitness:.2f}'}")
        decision = f"كود Gen#{len(self.versions)} — Fitness={fitness:.2f}"
        confidence = min(int(60 + fitness * 5), 92)

        return {
            "thought": thought, "decision": decision, "confidence": confidence,
            "params": {
                "fitness": round(fitness, 3),
                "versions_count": len(self.versions),
                "best_params": {"gap": int(gap), "tp": round(tp, 2), "sl": round(sl, 2)},
                "code_preview": code[:300],
            },
        }


# ════════════════════════════════════════════════════════
#  المنسق الرئيسي  🤖
# ════════════════════════════════════════════════════════
class Coordinator(Agent):
    def __init__(self, specialists):
        super().__init__("coordinator", "المنسق الرئيسي", "🤖", interval=28)
        self.specialists = specialists
        self.consensus_log = []

    def think(self, market):
        states = [a.get_state() for a in self.specialists]

        # جمع آراء الوكلاء وترجيحها
        all_params = {}
        total_conf = sum(s.get("confidence", 50) for s in states)
        insights   = []
        alerts     = []

        for s in states:
            c = s.get("confidence", 50)
            p = s.get("params", {}) or {}
            d = s.get("decision", "—")
            insights.append(f"{s['emoji']} {s['role']}: {d} ({c}%)")
            if c >= 85:
                alerts.append(f"{s['emoji']} {d}")
            for k, v in p.items():
                if isinstance(v, (int, float)) and k in ("gap", "tp", "sl"):
                    if k not in all_params:
                        all_params[k] = {"wsum": 0.0, "w": 0.0}
                    all_params[k]["wsum"] += v * c
                    all_params[k]["w"]    += c

        # متوسط مرجّح للمعاملات
        final_params = {}
        for k, d in all_params.items():
            if d["w"] > 0:
                final_params[k] = round(d["wsum"] / d["w"], 2)

        avg_conf = total_conf / max(len(states), 1)
        n_alert  = len(alerts)

        if n_alert >= 3:
            thought  = (f"🚨 إجماع حرج! {n_alert} وكلاء ≥85% ثقة: "
                        f"{' | '.join(alerts)}. "
                        f"المعاملات المقترحة: {final_params}.")
            decision = f"إجماع حرج — {n_alert} وكلاء متفقون"
            confidence = min(int(avg_conf * 1.15), 96)
            self.reward(8)
        elif n_alert >= 1:
            thought  = (f"تنبيه من {n_alert} وكيل حرج: {' | '.join(alerts)}. "
                        f"ثقة متوسطة {avg_conf:.0f}%. معاملات مقترحة: {final_params}.")
            decision = f"تنبيه — {n_alert} وكيل حرج"
            confidence = int(avg_conf * 1.08)
        else:
            thought  = (f"جمعت آراء {len(states)} وكلاء. ثقة متوسطة {avg_conf:.0f}%. "
                        f"لا تنبيهات حرجة. النظام مستقر.")
            decision = "الوكلاء متوافقون ✓"
            confidence = int(avg_conf)

        entry = {
            "t": ts(), "decision": decision,
            "confidence": confidence, "params": final_params,
        }
        self.consensus_log.append(entry)
        self.consensus_log = self.consensus_log[-30:]

        return {
            "thought": thought, "decision": decision,
            "confidence": confidence, "params": final_params,
            "insights": insights,
            "alerts": alerts,
            "consensus_log": self.consensus_log[-5:],
            "log": True,
        }


# ════════════════════════════════════════════════════════
#  Swarm Manager
# ════════════════════════════════════════════════════════
class Swarm:
    def __init__(self):
        self.specialists = [
            GapAnalyst(),
            MarketReader(),
            RiskGuardian(),
            DNADeveloper(),
            StrategyInventor(),
            CodeAnalyst(),
        ]
        self.coordinator = Coordinator(self.specialists)
        self.all_agents  = self.specialists + [self.coordinator]

    def start(self):
        for a in self.all_agents:
            a.start()
        print(f"[SWARM] {len(self.all_agents)} وكيل تم تشغيلهم")
        for a in self.all_agents:
            print(f"  {a.emoji} {a.role} — كل {a.interval}s")

    def snapshot(self):
        coord = self.coordinator.get_state()
        return {
            "timestamp":   ts(),
            "agents":      [a.get_state() for a in self.specialists],
            "coordinator": coord,
            "total_score": sum(a.score for a in self.all_agents),
            "alerts":      coord.get("params", {}).get("alerts", []),
        }

    def run(self):
        self.start()
        print(f"[SWARM] يكتب إلى {AGENTS_FILE}")
        while True:
            try:
                snap = self.snapshot()
                AGENTS_FILE.write_text(
                    json.dumps(snap, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
            except Exception as e:
                print(f"[SWARM] خطأ كتابة: {e}")
            time.sleep(5)


if __name__ == "__main__":
    print("=" * 55)
    print("  FRIDAY Agent Swarm — 6 متخصصين + منسق رئيسي")
    print("  كل وكيل يعمل باستمرار ويطوّر نفسه ذاتياً")
    print("=" * 55)
    Swarm().run()

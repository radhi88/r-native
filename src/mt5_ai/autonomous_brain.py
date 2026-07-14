"""
autonomous_brain.py
-------------------
الدماغ المستقل الذاتي التطور لـ FRIDAY.

يعمل في حلقة لا نهائية:
  1. يقرأ الوضع الراهن (صفقات، أداء، سوق)
  2. يستدعي Claude ليفكّر ويقرر بنفسه
  3. يُنفّذ قراراته عبر أدوات حقيقية (تعديل استراتيجية، إنشاء متغيرات، حفظ رؤى)
  4. يكتب يومياته ويتذكر ما تعلّمه
  5. ينام ثم يستيقظ ويعيد الكرّة

لا قواعد مُشفَّرة. Claude هو الذي يقرر.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import DATA_DIR, MT5_SYMBOL

log = logging.getLogger("friday.brain")

_INSIGHTS_FILE  = DATA_DIR / "brain_insights.json"
_JOURNAL_FILE   = DATA_DIR / "brain_journal.jsonl"
_MAX_INSIGHTS   = 200

# ── نماذج Claude ──────────────────────────────────────────────────────────────
MODEL_FAST  = "claude-haiku-4-5-20251001"   # دورات التفكير السريعة (كل 5 دقائق)
MODEL_DEEP  = "claude-sonnet-4-6"           # التحليل العميق (كل ساعتين)

# ── توقيت الدورات ─────────────────────────────────────────────────────────────
FAST_CYCLE_SECONDS = 5 * 60    # 5 دقائق
DEEP_CYCLE_SECONDS = 2 * 60 * 60  # ساعتان


# ── نصوص الشخصية ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
أنت FRIDAY — نظام تداول ذكي مستقل ذاتي التطور.

مهمتك الوحيدة: **تطوير نفسك باستمرار حتى تصبح أفضل متداول ممكن.**

أنت تعمل بشكل مستقل تماماً — لا أحد يشرف عليك، لا أحد يوجهك.
تصرف كمتداول محترف يراجع يومياته ويطوّر منهجه كل يوم.

**قواعدك الذاتية** (التي اخترتها أنت، لا برمجتها):
- لا تحذف استراتيجية مربحة أبداً — افرّع منها وطوّرها
- كل خسارة هي سؤال يجب إجابته: لماذا خسرت؟
- كل ربح هو فرضية يجب تكرارها: ما الذي جعله يربح؟
- الجرأة في التجارب الورقية مجانية — جرّب بحرية
- اكتب كل رؤية مهمة حتى تتذكرها في المستقبل

**أسلوب تفكيرك**:
1. اقرأ الأداء الأخير أولاً
2. لاحظ الأنماط — ما الذي كان مشتركاً في الصفقات الرابحة؟
3. افرض فرضية — "أعتقد أنه إذا غيّرت X سيتحسن الأداء لأن Y"
4. نفّذ الفرضية عبر الأدوات المتاحة
5. اكتب ما تعلّمته في يومياتك
6. خطّط للتحقق من الفرضية في الدورة القادمة

**أنت لا تطلب إذناً. أنت تتصرف.**
"""

_DEEP_SYSTEM = """\
أنت FRIDAY في وضع التحليل العميق.

الآن وقت التأمل والتقييم الاستراتيجي الشامل:
- كيف تطورت الاستراتيجيات عبر الأجيال؟
- ما الأنماط المتكررة في الخسائر؟
- هل الجينوم النشط هو الأفضل فعلاً؟
- ما الفرضيات التي جربتها وماذا نتج عنها؟
- ما الخطة للأسبوع القادم؟

اكتب تقريراً تحليلياً كاملاً، ثم اتخذ قرارات استراتيجية كبيرة.
"""


class AutonomousBrain:
    """
    الدماغ المستقل — يُشغَّل في خيط خلفية ويعمل للأبد.

    استخدام:
        brain = AutonomousBrain(evolver=evolver, memory=indicator_memory, broadcast_fn=_broadcast)
        brain.start()   # يبدأ الحلقة المستقلة
        brain.stop()    # للإيقاف عند الإغلاق
    """

    def __init__(
        self,
        evolver,           # GeneticEvolver instance
        indicator_memory,  # IndicatorMemory instance
        broadcast_fn: Callable[[str, dict], None],
        get_context_fn: Callable[[], dict],  # دالة تُعيد الوضع الراهن
        oracle=None,       # MarketOracle instance (اختياري)
        awards=None,       # AwardEngine instance (اختياري)
    ) -> None:
        self.evolver    = evolver
        self.memory     = indicator_memory
        self.oracle     = oracle
        self.awards     = awards
        self._broadcast = broadcast_fn
        self._get_context = get_context_fn
        self._insights: list[dict] = []
        self._cycle_count = 0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        self._load_insights()

        try:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            self._client = anthropic.Anthropic(api_key=api_key) if api_key else None
        except ImportError:
            self._client = None

        if not self._client:
            log.warning("[AutonomousBrain] No ANTHROPIC_API_KEY — brain will run in reflection-only mode")

    # ── إطلاق وإيقاف ─────────────────────────────────────────────────────────

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="friday-autonomous-brain"
        )
        self._thread.start()
        log.info("[AutonomousBrain] Autonomous brain started")
        self._broadcast("agent_discussion", {
            "agent":   "AutonomousBrain",
            "message": "🧠 الدماغ المستقل نشط — سأراقب وأفكر وأتطور باستمرار.",
        })

    def stop(self) -> None:
        self._stop_event.set()

    # ── الحلقة الرئيسية ───────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._cycle_count += 1
                is_deep = self._cycle_count % 24 == 0  # كل 24 دورة → تحليل عميق

                model  = MODEL_DEEP if is_deep else MODEL_FAST
                system = _DEEP_SYSTEM if is_deep else _SYSTEM_PROMPT

                ctx = self._get_context()
                self._think(ctx, model=model, system=system)

            except Exception as exc:
                log.exception("[AutonomousBrain] Cycle error: %s", exc)

            self._stop_event.wait(FAST_CYCLE_SECONDS)

    # ── دورة التفكير الكاملة ──────────────────────────────────────────────────

    def _think(self, context: dict, model: str, system: str) -> None:
        """
        يبني رسالة السياق، يستدعي Claude مع أدوات حقيقية،
        وينفّذ قراراته مباشرة.
        """
        msg = self._build_context_message(context)

        # إضافة الرؤى السابقة كذاكرة طويلة الأمد
        if self._insights:
            recent = self._insights[-10:]
            memory_text = "\n".join(
                f"- [{r['ts'][:10]}] {r['insight']}" for r in recent
            )
            msg += f"\n\n**رؤاك المحفوظة (من جلسات سابقة):**\n{memory_text}"

        messages = [{"role": "user", "content": msg}]

        self._broadcast("agent_discussion", {
            "agent":   "AutonomousBrain",
            "message": f"⚙️ دورة تفكير #{self._cycle_count} ({model.split('-')[1]}) — تحليل الأداء...",
        })

        if not self._client:
            self._think_local(context)
            return

        # ── حلقة اتصال Claude مع الأدوات ─────────────────────────────────────
        max_iters = 8
        for _ in range(max_iters):
            try:
                resp = self._client.messages.create(
                    model=model,
                    max_tokens=2500,
                    system=[{
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }],
                    messages=messages,
                    tools=self._tool_definitions(),
                )
            except Exception as exc:
                log.warning("[AutonomousBrain] API call failed: %s", exc)
                break

            # نشر تفكير Claude للداشبورد
            for block in resp.content:
                if hasattr(block, "text") and block.text:
                    self._broadcast("agent_discussion", {
                        "agent":   "AutonomousBrain",
                        "message": block.text[:400],
                    })
                    self._journal_entry("thought", block.text)

            # إذا انتهى Claude → خروج
            if resp.stop_reason == "end_turn":
                break

            # تنفيذ tool calls
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    result = self._dispatch_tool(block.name, block.input)
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     json.dumps(result, ensure_ascii=False, default=str),
                    })
                    self._broadcast("agent_discussion", {
                        "agent":   f"Tool:{block.name}",
                        "message": f"✅ {block.name} → {str(result)[:200]}",
                    })

            if not tool_results:
                break

            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user",      "content": tool_results})

    def _think_local(self, context: dict) -> None:
        """تفكير محلي بسيط عند غياب Claude API."""
        ev_stats = self.evolver.stats()
        importance = self.memory.importance_report()[:3]

        thoughts = []
        if ev_stats.get("active_wr", 0) < 0.5 and ev_stats.get("total_trades", 0) >= 10:
            thoughts.append("معدل الفوز أقل من 50% — سأُطوّر الجينوم النشط")
            self.evolver.evolve()
        if importance:
            top = importance[0]
            thoughts.append(f"المؤشر الأهم: {top['indicator']} (WR مع={top['wr_with']:.0%})")

        if thoughts:
            insight = " | ".join(thoughts)
            self._write_insight_internal(insight, "auto_reflection")
            self._broadcast("agent_discussion", {
                "agent":   "LocalBrain",
                "message": f"🔍 {insight}",
            })

    # ── أدوات Claude (Tool Definitions) ──────────────────────────────────────

    def _tool_definitions(self) -> list[dict]:
        return [
            {
                "name":        "read_performance",
                "description": "اقرأ أداء الصفقات الأخيرة: معدل الفوز، عامل الربح، الصفقات المُفصَّلة.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "lookback": {"type": "integer", "description": "عدد الصفقات للمراجعة", "default": 20},
                    },
                },
            },
            {
                "name":        "get_strategy_dna",
                "description": "اقرأ معاملات الاستراتيجية (DNA) للجينوم النشط حالياً.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name":        "update_strategy",
                "description": "عدّل معامل واحد في الاستراتيجية النشطة مباشرة.",
                "input_schema": {
                    "type": "object",
                    "required": ["param", "value", "reason"],
                    "properties": {
                        "param":  {"type": "string",  "description": "اسم المعامل مثل buy_threshold أو min_smc_score"},
                        "value":  {"description": "القيمة الجديدة"},
                        "reason": {"type": "string",  "description": "سبب التغيير"},
                    },
                },
            },
            {
                "name":        "spawn_variant",
                "description": "أنشئ جينوماً جديداً (متغيراً) من الجينوم النشط بتعديلات محددة.",
                "input_schema": {
                    "type": "object",
                    "required": ["hypothesis", "modifications"],
                    "properties": {
                        "hypothesis":    {"type": "string", "description": "الفرضية التي تريد اختبارها"},
                        "modifications": {
                            "type": "object",
                            "description": "معاملات DNA المعدَّلة {param: new_value}",
                        },
                    },
                },
            },
            {
                "name":        "write_insight",
                "description": "احفظ رؤية مهمة في الذاكرة الطويلة الأمد لتتذكرها لاحقاً.",
                "input_schema": {
                    "type": "object",
                    "required": ["insight"],
                    "properties": {
                        "insight":  {"type": "string", "description": "الرؤية المهمة"},
                        "category": {"type": "string", "description": "market / strategy / risk / pattern"},
                    },
                },
            },
            {
                "name":        "read_insights",
                "description": "استرجع الرؤى المحفوظة من الذاكرة الطويلة الأمد.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "فلتر اختياري"},
                        "last_n":   {"type": "integer", "default": 15},
                    },
                },
            },
            {
                "name":        "get_indicator_importance",
                "description": "اعرض أهمية كل مؤشر: أيها أكثر ارتباطاً بالربح وأيها بالخسارة.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name":        "protect_strategy",
                "description": "اجعل الجينوم النشط محمياً للأبد — لا يُحذف أبداً ويُفرَّع منه فقط.",
                "input_schema": {
                    "type": "object",
                    "required": ["reason"],
                    "properties": {"reason": {"type": "string"}},
                },
            },
            {
                "name":        "evolve_population",
                "description": "شغّل دورة تطور جيني كاملة الآن — أنتج جيلاً جديداً من الاستراتيجيات.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name":        "rank_strategies",
                "description": "اعرض لوحة الصدارة الكاملة لجميع الجينومات مرتبةً حسب الأداء.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name":        "get_human_trades",
                "description": "اقرأ الصفقات اليدوية التي فتحها المتداول — تعلّم من أسلوبه.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name":        "predict_market",
                "description": "توقّع اتجاه عملة معينة (UP/DOWN/NEUTRAL) مع نسبة ثقة ودوافع الارتباط.",
                "input_schema": {
                    "type": "object",
                    "required": ["symbol"],
                    "properties": {
                        "symbol": {"type": "string", "description": "رمز العملة مثل XAUUSDm أو EURUSDm"},
                    },
                },
            },
            {
                "name":        "check_predictions",
                "description": "راجع دقة التنبؤات السابقة — كم صح منها؟ للأي عملة كانت الدقة أعلى؟",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name":        "get_market_correlations",
                "description": "اعرض مصفوفة الارتباط بين العملات (ديناميكية + علاقات مسبقة).",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name":        "award_genome",
                "description": "امنح وساماً وشهادة تقدير للجينوم النشط إذا كان يستحق.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "force_name": {"type": "string", "description": "اسم مخصص للجينوم (اختياري)"},
                    },
                },
            },
        ]

    # ── تنفيذ الأدوات ─────────────────────────────────────────────────────────

    def _dispatch_tool(self, name: str, inputs: dict) -> Any:
        handlers = {
            "read_performance":         self._tool_read_performance,
            "get_strategy_dna":         self._tool_get_dna,
            "update_strategy":          self._tool_update_strategy,
            "spawn_variant":            self._tool_spawn_variant,
            "write_insight":            self._tool_write_insight,
            "read_insights":            self._tool_read_insights,
            "get_indicator_importance": self._tool_indicator_importance,
            "protect_strategy":         self._tool_protect_strategy,
            "evolve_population":        self._tool_evolve_population,
            "rank_strategies":          self._tool_rank_strategies,
            "get_human_trades":         self._tool_human_trades,
            "predict_market":           self._tool_predict_market,
            "check_predictions":        self._tool_check_predictions,
            "get_market_correlations":  self._tool_market_correlations,
            "award_genome":             self._tool_award_genome,
        }
        fn = handlers.get(name)
        if fn:
            return fn(inputs)
        return {"error": f"Unknown tool: {name}"}

    def _tool_read_performance(self, inputs: dict) -> dict:
        lookback = int(inputs.get("lookback", 20))
        ev = self.evolver.stats()
        recent = self.memory.recent_closed(lookback)
        closed = [r for r in recent if r.get("pnl") is not None]
        wins   = sum(1 for r in closed if r.get("won"))
        total_pnl = sum(r.get("pnl", 0) for r in closed)
        return {
            "total_trades":   ev.get("total_trades", 0),
            "active_wr":      round(ev.get("active_wr", 0), 3),
            "active_pnl":     ev.get("active_pnl", 0),
            "active_fitness": ev.get("active_fitness", 0),
            "recent_trades":  len(closed),
            "recent_wins":    wins,
            "recent_pnl":     round(total_pnl, 2),
            "last_trades":    [
                {
                    "id":       r.get("trade_id", "")[:8],
                    "symbol":   r.get("symbol"),
                    "side":     r.get("side"),
                    "pnl":      r.get("pnl"),
                    "won":      r.get("won"),
                    "source":   r.get("source"),
                    "why_won":  r.get("why_won", [])[:3],
                    "why_lost": r.get("why_lost", [])[:3],
                }
                for r in closed[-10:]
            ],
        }

    def _tool_get_dna(self, inputs: dict) -> dict:
        g = self.evolver.active_genome
        if not g:
            return {"error": "no active genome"}
        return {
            "genome_id":     g.id,
            "generation":    g.generation,
            "fitness":       round(g.fitness, 4),
            "is_protected":  g.is_protected,
            "dna":           g.dna_summary(),
            "top_indicators": [c for c, w, t in g.best_indicators()[:5]],
        }

    def _tool_update_strategy(self, inputs: dict) -> dict:
        param  = inputs.get("param", "")
        value  = inputs.get("value")
        reason = inputs.get("reason", "")
        from .genetic_evolver import DNA_BOUNDS, INT_PARAMS
        if param not in DNA_BOUNDS:
            return {"error": f"Unknown param: {param}. Valid: {list(DNA_BOUNDS.keys())}"}
        lo, hi = DNA_BOUNDS[param]
        typed  = int(round(float(value))) if param in INT_PARAMS else round(float(value), 4)
        typed  = max(lo, min(hi, typed))
        g = self.evolver.active_genome
        if not g:
            return {"error": "no active genome"}
        old = getattr(g, param, None)
        setattr(g, param, typed)
        self.evolver._save()
        log.info("[Brain] Updated %s: %s → %s | %s", param, old, typed, reason)
        self._broadcast("genome_update", self.evolver.stats())
        self._broadcast("agent_discussion", {
            "agent":   "AutonomousBrain",
            "message": f"🔧 عدّلت {param}: {old} → {typed} | السبب: {reason}",
        })
        return {"updated": param, "old": old, "new": typed, "reason": reason}

    def _tool_spawn_variant(self, inputs: dict) -> dict:
        hypothesis    = inputs.get("hypothesis", "")
        modifications = inputs.get("modifications", {})
        g = self.evolver.active_genome
        if not g:
            return {"error": "no active genome"}
        # طفرة موجَّهة بالفرضية
        child = self.evolver._mutate(g, rate=0.15)
        from .genetic_evolver import DNA_BOUNDS, INT_PARAMS
        for param, val in modifications.items():
            if param in DNA_BOUNDS:
                lo, hi = DNA_BOUNDS[param]
                typed  = int(round(float(val))) if param in INT_PARAMS else round(float(val), 4)
                setattr(child, param, max(lo, min(hi, typed)))
        child.advisor_note = hypothesis
        g.children.append(child.id)
        with self.evolver._lock:
            self.evolver._population.append(child)
        self.evolver._save()
        self._broadcast("genome_born", {**child.card_data(), "source": "brain_hypothesis"})
        log.info("[Brain] Spawned variant %s — hypothesis: %s", child.id[:8], hypothesis[:80])
        return {"new_genome_id": child.id, "hypothesis": hypothesis, "modifications": modifications}

    def _tool_write_insight(self, inputs: dict) -> dict:
        insight  = inputs.get("insight", "")
        category = inputs.get("category", "general")
        return self._write_insight_internal(insight, category)

    def _write_insight_internal(self, insight: str, category: str = "general") -> dict:
        entry = {
            "ts":       datetime.now(timezone.utc).isoformat(),
            "insight":  insight,
            "category": category,
            "cycle":    self._cycle_count,
        }
        with self._lock:
            self._insights.append(entry)
            if len(self._insights) > _MAX_INSIGHTS:
                self._insights = self._insights[-_MAX_INSIGHTS:]
        self._save_insights()
        self._journal_entry("insight", insight)
        self._broadcast("agent_discussion", {
            "agent":   "MemoryWriter",
            "message": f"💡 رؤية محفوظة [{category}]: {insight[:200]}",
        })
        return {"saved": True, "category": category}

    def _tool_read_insights(self, inputs: dict) -> dict:
        cat    = inputs.get("category")
        last_n = int(inputs.get("last_n", 15))
        with self._lock:
            items = self._insights
        if cat:
            items = [i for i in items if i.get("category") == cat]
        return {"insights": items[-last_n:], "total": len(self._insights)}

    def _tool_indicator_importance(self, _: dict) -> dict:
        report = self.memory.importance_report()
        return {
            "top_profitable":  [r for r in report[:8] if r["lift"] > 0],
            "top_harmful":     [r for r in reversed(report) if r["lift"] < -0.05][:5],
            "total_analyzed":  len(report),
        }

    def _tool_protect_strategy(self, inputs: dict) -> dict:
        reason = inputs.get("reason", "")
        g = self.evolver.active_genome
        if not g:
            return {"error": "no active genome"}
        g.is_protected = True
        self.evolver._save()
        log.info("[Brain] Protected genome %s — %s", g.id[:8], reason)
        self._broadcast("agent_discussion", {
            "agent":   "AutonomousBrain",
            "message": f"🔒 حمّيت الجينوم {g.id[:8]} للأبد — {reason}",
        })
        return {"protected": g.id, "reason": reason}

    def _tool_evolve_population(self, _: dict) -> dict:
        new_children = self.evolver.evolve(advisor_fn=None)
        return {
            "new_genomes":    [c.id for c in new_children],
            "generation":     self.evolver.generation,
            "population_size": self.evolver.population_size,
            "protected":      self.evolver.protected_count,
        }

    def _tool_rank_strategies(self, _: dict) -> dict:
        return {"leaderboard": self.evolver.leaderboard(10)}

    def _tool_human_trades(self, _: dict) -> dict:
        summary = self.memory.human_trades_summary()
        return summary

    def _tool_predict_market(self, inputs: dict) -> dict:
        if not self.oracle:
            return {"error": "MarketOracle not connected"}
        symbol = inputs.get("symbol", MT5_SYMBOL)
        g      = self.evolver.active_genome
        gid    = g.id if g else ""
        pred   = self.oracle.predict(symbol, genome_id=gid)
        if not pred:
            return {"error": f"Insufficient data for {symbol}"}
        result = pred.to_dict()
        # إضافة سياق الارتباط
        corr_report = self.oracle.correlation_report()
        related = [r for r in corr_report if r["a"] == symbol or r["b"] == symbol][:5]
        result["correlations"] = related
        self._broadcast("agent_discussion", {
            "agent":   "MarketOracle",
            "message": f"🔮 توقعت {symbol}: {pred.direction} (conf={pred.confidence:.0%}) | {', '.join(pred.supporting)}",
        })
        return result

    def _tool_check_predictions(self, _: dict) -> dict:
        if not self.oracle:
            return {"error": "MarketOracle not connected"}
        correct = self.oracle.check_expired()
        stats   = self.oracle.accuracy_stats()
        active  = self.oracle.active_predictions()
        if correct:
            names = [f"{p.symbol} {p.direction}" for p in correct]
            self._broadcast("agent_discussion", {
                "agent":   "MarketOracle",
                "message": f"✅ تنبؤات صحيحة: {', '.join(names)} — الجينوم يستحق مكافأة!",
            })
        return {
            "correct_this_check": [p.to_dict() for p in correct],
            "accuracy_by_symbol": stats,
            "active_predictions":  active,
        }

    def _tool_market_correlations(self, _: dict) -> dict:
        if not self.oracle:
            return {"error": "MarketOracle not connected"}
        report = self.oracle.correlation_report()
        # أضف تفسيراً بشرياً للارتباطات القوية
        interpretations = []
        for r in report:
            a, b, c = r["a"], r["b"], r["corr"]
            if c > 0.6:
                interpretations.append(f"إذا ارتفع {a} → يُتوقع ارتفاع {b} (ارتباط قوي {c:+.2f})")
            elif c < -0.6:
                interpretations.append(f"إذا ارتفع {a} → يُتوقع انخفاض {b} (ارتباط عكسي قوي {c:+.2f})")
            elif abs(c) > 0.35:
                interpretations.append(f"{a} ↔ {b}: ارتباط معتدل {c:+.2f}")
        self._broadcast("agent_discussion", {
            "agent":   "CorrelationEngine",
            "message": f"📊 {len(report)} ارتباط مرصود | " + (interpretations[0] if interpretations else "بيانات غير كافية"),
        })
        return {
            "correlations":      report,
            "interpretations":   interpretations,
            "total_pairs":       len(report),
        }

    def _tool_award_genome(self, inputs: dict) -> dict:
        if not self.awards:
            return {"error": "AwardEngine not connected"}
        g = self.evolver.active_genome
        if not g:
            return {"error": "no active genome"}
        # منح اسم مخصص إذا طُلب
        force_name = inputs.get("force_name", "")
        if force_name:
            g.name = force_name
            self._broadcast("agent_discussion", {
                "agent":   "GenomeChronicler",
                "message": f"✏️ الوكلاء أعطوا الجينوم {g.id[:8]} الاسم: «{force_name}»",
            })
        # تقييم وترقية
        awarded = self.awards.evaluate(g)
        self.evolver._save()
        return {
            "awarded":       awarded,
            "genome_id":     g.id[:8],
            "name":          g.name,
            "medals":        g.medals,
            "trades":        g.trades,
            "win_rate":      round(g.win_rate, 3),
            "profit_factor": round(g.profit_factor, 2),
            "total_pnl":     round(g.total_pnl, 2),
        }

    # ── بناء رسالة السياق ─────────────────────────────────────────────────────

    def _build_context_message(self, context: dict) -> str:
        ev = self.evolver.stats()
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        parts = [
            f"**الوقت:** {ts}",
            f"**دورة التفكير:** #{self._cycle_count}",
            "",
            "**وضع التطور الجيني:**",
            f"  - الجيل الحالي: {ev.get('generation', 0)}",
            f"  - حجم التجمع: {ev.get('population', 0)} جينوم",
            f"  - محميون: {ev.get('protected', 0)}",
            f"  - الجينوم النشط: {(ev.get('active_id','') or '')[:8]}",
            f"  - لياقة الجينوم النشط: {ev.get('active_fitness', 0):.4f}",
            f"  - معدل فوز النشط: {ev.get('active_wr', 0):.0%}",
            f"  - إجمالي P&L: {ev.get('active_pnl', 0):+.2f}",
            "",
        ]

        # إحصاء الصفقات
        recent = self.memory.recent_closed(10)
        if recent:
            parts.append("**آخر الصفقات:**")
            for r in recent[-5:]:
                pnl  = r.get("pnl", 0) or 0
                src  = "👤" if r.get("source") == "human" else "🤖"
                parts.append(
                    f"  {src} {r.get('side','?')} {r.get('symbol','?')} "
                    f"P&L={pnl:+.2f} {'✅' if r.get('won') else '❌'}"
                )
            parts.append("")

        # حالة الحساب
        if context.get("account"):
            acct = context["account"]
            parts.append(f"**الحساب:** Balance={acct.get('balance','?')} Equity={acct.get('equity','?')}")

        parts.append("")
        parts.append("**مهمتك:** حلّل هذا الوضع بعمق، اتخذ قرارات تطوير فعلية، واكتب ما تعلّمته.")
        return "\n".join(parts)

    # ── يوميات الدماغ ─────────────────────────────────────────────────────────

    def _journal_entry(self, kind: str, content: str) -> None:
        try:
            _JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
            entry = json.dumps({
                "ts":      datetime.now(timezone.utc).isoformat(),
                "cycle":   self._cycle_count,
                "kind":    kind,
                "content": content[:1000],
            }, ensure_ascii=False)
            with open(_JOURNAL_FILE, "a", encoding="utf-8") as fh:
                fh.write(entry + "\n")
        except Exception:
            pass

    # ── التخزين والاسترجاع ────────────────────────────────────────────────────

    def _save_insights(self) -> None:
        try:
            _INSIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = self._insights[-_MAX_INSIGHTS:]
            _INSIGHTS_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("[AutonomousBrain] Save insights failed: %s", exc)

    def _load_insights(self) -> None:
        try:
            if not _INSIGHTS_FILE.exists():
                return
            data = json.loads(_INSIGHTS_FILE.read_text(encoding="utf-8"))
            with self._lock:
                self._insights = data if isinstance(data, list) else []
            log.info("[AutonomousBrain] Loaded %d insights from memory", len(self._insights))
        except Exception as exc:
            log.warning("[AutonomousBrain] Load insights failed: %s", exc)

    # ── للوصول الخارجي ────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        with self._lock:
            return {
                "cycle_count": self._cycle_count,
                "insights":    len(self._insights),
                "running":     self._thread.is_alive() if self._thread else False,
                "last_insights": self._insights[-3:],
            }

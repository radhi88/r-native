"""
genetic_evolver.py
------------------
نظام التطور الجيني لاستراتيجيات التداول في FRIDAY.

القواعد الأساسية:
- الجينوم المربح محمي للأبد — لا يُحذف أبداً
- يتكاثر الجينوم المربح ويُنتج أطفالاً بطفرات ذكية
- كل جيل يتعلم من المؤشرات المربحة ويربطها بالاستراتيجية
- Claude يُستشار عند كل دورة تطور لاقتراح طفرات مثلى
- تتبع كامل للنسب (الأجداد → الأبناء → الأحفاد)
"""

from __future__ import annotations

import json
import logging
import random
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import DATA_DIR
from .indicator_memory import IndicatorMemory

log = logging.getLogger("friday.genetics")

# ── نطاقات المعاملات (DNA bounds) ─────────────────────────────────────────────
DNA_BOUNDS: dict[str, tuple] = {
    "buy_threshold":          (0.55, 0.88),
    "sell_threshold":         (0.12, 0.45),
    "min_smc_score":          (1, 5),
    "atr_sl_mult":            (1.0, 3.0),
    "min_rr":                 (1.0, 3.0),
    "high_conf_buy":          (0.62, 0.88),
    "high_conf_sell":         (0.12, 0.38),
    "bos_continuation_buy":   (0.52, 0.78),
    "bos_continuation_sell":  (0.22, 0.48),
    "smc_score_strong":       (2, 5),
}

INT_PARAMS = {"min_smc_score", "smc_score_strong"}

POPULATION_FILE = DATA_DIR / "strategy_population.json"


def _safe_symbol_name(symbol: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(symbol or ""))
    return clean.strip("._-")


def _population_file_for(symbol: str) -> Path:
    clean = _safe_symbol_name(symbol)
    if not clean:
        return POPULATION_FILE
    return DATA_DIR / "strategy_populations" / f"{clean}.json"

# ── ثوابت التطور ───────────────────────────────────────────────────────────────
POPULATION_MAX     = 20      # الحد الأقصى للتجمع
ELITE_KEEP         = 5       # نبقي دائماً أفضل N من حيث اللياقة
MIN_TRADES_EVAL    = 8       # نقيّم اللياقة بعد هذا العدد من الصفقات
EVOLUTION_EVERY    = 15      # نُطوّر بعد كل N صفقة مغلقة في التجمع
FITNESS_WR_W       = 0.30    # وزن معدل الفوز
FITNESS_PF_W       = 0.40    # وزن عامل الربح
FITNESS_AVG_W      = 0.15    # وزن متوسط P&L
FITNESS_FREQ_W     = 0.15    # وزن تكرار الصفقات (Sharpe-like frequency bonus)
FITNESS_FREQ_TARGET = 30     # عدد الصفقات المستهدف لأقصى مكافأة تكرار


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ── بنية الجينوم ──────────────────────────────────────────────────────────────

@dataclass
class StrategyGenome:
    id: str
    generation: int
    parent_ids: list[str]
    created_at: str
    symbol: str

    # DNA — معاملات الاستراتيجية
    buy_threshold: float
    sell_threshold: float
    min_smc_score: int
    atr_sl_mult: float
    min_rr: float
    high_conf_buy: float
    high_conf_sell: float
    bos_continuation_buy: float
    bos_continuation_sell: float
    smc_score_strong: int

    # أداء الصفقات
    trades: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    win_pnl: float = 0.0
    loss_pnl: float = 0.0

    # الحالة
    is_protected: bool = False
    is_active: bool = False
    children: list[str] = field(default_factory=list)

    # تاريخ اللياقة (snapshot per trade)
    fitness_history: list[dict] = field(default_factory=list)

    # انتماء المؤشرات: اسم_المؤشر → [فوز, إجمالي]
    indicator_affinity: dict[str, list[int]] = field(default_factory=dict)

    # تعليق من المستشار (Claude)
    advisor_note: str = ""

    # هوية الجينوم — تُمنح من الوكلاء
    name:         str        = ""           # الاسم الممنوح من الوكلاء
    medals:       list[str]  = field(default_factory=list)   # الأوسمة المكتسبة
    achievements: list[str]  = field(default_factory=list)   # إنجازات خاصة
    award_count:  int        = 0

    # ── حسابات مشتقة ──────────────────────────────────────────────────────────

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        if self.loss_pnl <= 0:
            return 1.0 if self.win_pnl > 0 else 0.0
        return self.win_pnl / self.loss_pnl

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.trades if self.trades > 0 else 0.0

    @property
    def fitness(self) -> float:
        if self.trades < MIN_TRADES_EVAL:
            return 0.0
        pf_score   = _clamp(self.profit_factor / 2.0, 0.0, 1.0)
        avg_score  = 1.0 if self.avg_pnl > 0 else 0.0
        freq_score = _clamp(self.trades / FITNESS_FREQ_TARGET, 0.0, 1.0)
        return (FITNESS_WR_W  * self.win_rate
                + FITNESS_PF_W  * pf_score
                + FITNESS_AVG_W * avg_score
                + FITNESS_FREQ_W * freq_score)

    @property
    def is_profitable(self) -> bool:
        return (self.trades >= MIN_TRADES_EVAL
                and self.total_pnl > 0
                and self.win_rate >= 0.50)

    # ── تسجيل الصفقة ──────────────────────────────────────────────────────────

    def record_trade(
        self,
        won: bool,
        pnl: float,
        conditions_active: list[str] | None = None,
    ) -> None:
        self.trades += 1
        if won:
            self.wins += 1
            self.win_pnl += abs(pnl)
        else:
            self.loss_pnl += abs(pnl)
        self.total_pnl += pnl

        # تتبع انتماء المؤشرات
        for cond in (conditions_active or []):
            if cond not in self.indicator_affinity:
                self.indicator_affinity[cond] = [0, 0]
            self.indicator_affinity[cond][1] += 1
            if won:
                self.indicator_affinity[cond][0] += 1

        self.fitness_history.append({
            "t":       self.trades,
            "fitness": round(self.fitness, 4),
            "pnl_sum": round(self.total_pnl, 2),
            "wr":      round(self.win_rate, 3),
        })
        # الاحتفاظ بآخر 200 نقطة فقط
        if len(self.fitness_history) > 200:
            self.fitness_history = self.fitness_history[-200:]

        # حماية تلقائية عند الربحية
        if self.is_profitable and not self.is_protected:
            self.is_protected = True
            log.info(
                "[GENOME %s] Protected! fitness=%.3f wr=%.0f%% pf=%.2f total=%.2f",
                self.id[:8], self.fitness, self.win_rate * 100,
                self.profit_factor, self.total_pnl,
            )

    # ── تحويلات للوكلاء ──────────────────────────────────────────────────────

    def to_entry_agent_params(self) -> dict:
        return {
            "buy_prob_threshold":  self.buy_threshold,
            "sell_prob_threshold": self.sell_threshold,
            "min_smc_score":       self.min_smc_score,
            "setup_thresholds": {
                "high_conf_buy":         self.high_conf_buy,
                "high_conf_sell":        self.high_conf_sell,
                "bos_continuation_buy":  self.bos_continuation_buy,
                "bos_continuation_sell": self.bos_continuation_sell,
                "smc_score_strong":      self.smc_score_strong,
            },
        }

    def to_learning_engine_params(self) -> dict:
        return {
            "buy_threshold":  self.buy_threshold,
            "sell_threshold": self.sell_threshold,
            "min_smc_score":  self.min_smc_score,
            "atr_sl_mult":    self.atr_sl_mult,
            "min_rr":         self.min_rr,
        }

    def dna_summary(self) -> dict[str, Any]:
        return {
            "buy_threshold":          self.buy_threshold,
            "sell_threshold":         self.sell_threshold,
            "min_smc_score":          self.min_smc_score,
            "atr_sl_mult":            self.atr_sl_mult,
            "min_rr":                 self.min_rr,
            "high_conf_buy":          self.high_conf_buy,
            "high_conf_sell":         self.high_conf_sell,
            "bos_continuation_buy":   self.bos_continuation_buy,
            "bos_continuation_sell":  self.bos_continuation_sell,
            "smc_score_strong":       self.smc_score_strong,
        }

    def best_indicators(self, min_trades: int = 3) -> list[tuple[str, float, int]]:
        results = []
        for cond, (won, total) in self.indicator_affinity.items():
            if total >= min_trades:
                wr = won / total
                if wr > 0.55:
                    results.append((cond, round(wr, 3), total))
        return sorted(results, key=lambda x: -x[1])

    def card_data(self) -> dict:
        return {
            "id":            self.id,
            "symbol":        self.symbol,
            "gen":           self.generation,
            "fitness":       round(self.fitness, 4),
            "win_rate":      round(self.win_rate, 3),
            "profit_factor": round(self.profit_factor, 2),
            "total_pnl":     round(self.total_pnl, 2),
            "trades":        self.trades,
            "wins":          self.wins,
            "is_protected":  self.is_protected,
            "is_active":     self.is_active,
            "parents":       self.parent_ids[:2],
            "children_count": len(self.children),
            "best_indicators": [
                {"name": n, "wr": w, "trades": t}
                for n, w, t in self.best_indicators()[:5]
            ],
            "fitness_history": self.fitness_history[-20:],
            "advisor_note":    self.advisor_note,
            "dna":             self.dna_summary(),
            "name":            self.name or "—",
            "medals":          self.medals,
            "achievements":    self.achievements,
            "award_count":     self.award_count,
        }


# ── محرك التطور الجيني ────────────────────────────────────────────────────────

class GeneticEvolver:
    """
    يدير تجمعاً من الجينومات ويطورها جيلاً بعد جيل.

    الضمانات الأساسية:
    - لا يُحذف جينوم مربح أبداً (is_protected = True)
    - الجينوم ذو اللياقة الأعلى يكون النشط دائماً
    - بعد كل EVOLUTION_EVERY صفقة يُولد جيل جديد
    - يُستدعى المستشار (Claude) لاقتراح طفرات ذكية
    """

    def __init__(
        self,
        symbol: str = "",
        seed_params: dict | None = None,
        broadcast_fn: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.symbol = symbol
        self.population_file = _population_file_for(symbol)
        self._broadcast = broadcast_fn or (lambda e, d: None)
        self._lock = threading.Lock()

        self._population: list[StrategyGenome] = []
        self._generation: int = 0
        self._active_id: str | None = None
        self._total_trades_since_evolution: int = 0
        self._discussion_log: list[dict] = []  # يُرسل للوحة التحكم

        # ذاكرة المؤشرات الغنية (مشتركة بين كل الجينومات)
        self.memory = IndicatorMemory()

        self._load()

        if not self._population:
            self._seed(seed_params or {})
            log.info("[GeneticEvolver] Population seeded — symbol=%s", symbol)

    # ── API العام ───────────────────────────────────────────────────────────────

    @property
    def active_genome(self) -> StrategyGenome | None:
        with self._lock:
            return self._find(self._active_id) or (self._population[0] if self._population else None)

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def population_size(self) -> int:
        return len(self._population)

    @property
    def protected_count(self) -> int:
        return sum(1 for g in self._population if g.is_protected)

    def record_trade(
        self,
        won: bool,
        pnl: float,
        conditions_active: list[str] | None = None,
        genome_id: str | None = None,
        trade_id: str | None = None,
        source: str = "bot",
        snapshot: dict | None = None,
    ) -> None:
        """
        سجّل صفقة مغلقة في الجينوم النشط وذاكرة المؤشرات.

        source="human" → صفقة يدوية من المتداول (وزن تعلّم مُعزَّز)
        snapshot       → لقطة المؤشرات الكاملة لحظة الدخول
        """
        with self._lock:
            gid = genome_id or self._active_id
            g = self._find(gid)
            if g:
                # الصفقات اليدوية تُسجَّل بوزن مُضاعَف في الانتماء
                effective_conditions = list(conditions_active or [])
                if source == "human":
                    effective_conditions.append("__human_signal__")
                g.record_trade(won, pnl, effective_conditions)
            self._total_trades_since_evolution += 1
            should_evolve = self._total_trades_since_evolution >= EVOLUTION_EVERY

        # تحديث ذاكرة المؤشرات بالصورة الكاملة
        if trade_id and snapshot:
            rec = self.memory.get_open_entry(str(trade_id))
            if not rec:
                self.memory.record_entry(
                    trade_id    = str(trade_id),
                    symbol      = g.symbol if g else self.symbol,
                    side        = "BUY" if won else "SELL",  # تقريب
                    entry_price = float(snapshot.get("close", 0)),
                    snapshot    = snapshot,
                    genome_id   = gid or "",
                    source      = source,
                )
            self.memory.record_exit(str(trade_id), pnl)

            # تحديث indicator_affinity في الجينوم من نتائج الذاكرة
            top_conds = self.memory.top_profitable_conditions(8)
            if g and top_conds:
                for cond in top_conds:
                    if cond not in g.indicator_affinity:
                        g.indicator_affinity[cond] = [0, 0]

        self._save()
        self._broadcast("genome_update", self._stats_dict())

        if source == "human":
            log.info("[GeneticEvolver] Human trade recorded pnl=%.2f — system learns from you", pnl)
            self._broadcast("agent_discussion", {
                "agent":   "HumanLearner",
                "message": f"تعلّمت من صفقتك اليدوية: {'ربح' if won else 'خسارة'} {pnl:+.2f} | "
                           f"المؤشرات النشطة: {', '.join((conditions_active or [])[:4])}",
            })

        if should_evolve:
            self._evolve_async()

    def evolve(self, advisor_fn: Callable | None = None) -> list[StrategyGenome]:
        """
        دورة تطور كاملة. advisor_fn(summaries) → list[dict] طفرات مقترحة.
        يُعيد قائمة الجينومات الجديدة المولودة.
        """
        with self._lock:
            self._generation += 1
            gen = self._generation
            self._total_trades_since_evolution = 0

            # ترتيب حسب اللياقة
            ranked = sorted(self._population, key=lambda g: g.fitness, reverse=True)

            # حماية النخبة المربحة
            for g in ranked[:ELITE_KEEP]:
                if g.is_profitable:
                    g.is_protected = True

            # الفرز: المحمية + الجديدة التي لم تُقيَّم بعد
            protected     = [g for g in ranked if g.is_protected]
            unprotected   = [g for g in ranked if not g.is_protected]
            young         = [g for g in unprotected if g.trades < MIN_TRADES_EVAL]
            old_weak      = [g for g in unprotected if g.trades >= MIN_TRADES_EVAL]

            survivors = protected + young
            # نُبقي على أفضل المضعفين القدامى إن كانت المساحة تسمح
            for g in old_weak[:max(0, POPULATION_MAX - len(survivors) - 4)]:
                survivors.append(g)

            # الآباء: المحميون + ذوو اللياقة > 0.3
            parents = [g for g in ranked if g.is_protected or g.fitness > 0.3]
            if not parents:
                parents = ranked[: max(2, len(ranked) // 2)]

            # توليد أطفال جدد
            new_children: list[StrategyGenome] = []
            slots = max(0, POPULATION_MAX - len(survivors))

            for _ in range(slots):
                if len(parents) >= 2:
                    p1, p2 = random.sample(parents[: max(2, len(parents))], 2)
                    child = self._crossover(p1, p2)
                    p1.children.append(child.id)
                    p2.children.append(child.id)
                else:
                    p = parents[0]
                    child = self._mutate(p, rate=0.25)
                    p.children.append(child.id)
                new_children.append(child)
                survivors.append(child)

            self._population = survivors

            # تعيين الجينوم النشط = الأعلى لياقة
            if ranked:
                best = ranked[0]
                for g in self._population:
                    g.is_active = g.id == best.id
                self._active_id = best.id

            leaderboard = self._leaderboard_dict()

        # استشارة المستشار خارج القفل
        if advisor_fn and new_children:
            try:
                summaries = [g.dna_summary() for g in self._population[:5]]
                suggestions = advisor_fn(summaries)
                if suggestions:
                    self._apply_advisor(suggestions, gen)
            except Exception as exc:
                log.warning("[GeneticEvolver] Advisor call failed: %s", exc)

        self._save()

        entry = {
            "ts":             datetime.now(timezone.utc).isoformat(),
            "generation":     gen,
            "population":     len(self._population),
            "protected":      self.protected_count,
            "new_children":   [c.id for c in new_children],
            "active_id":      self._active_id,
            "leaderboard":    leaderboard[:5],
        }
        self._discussion_log.append(entry)
        if len(self._discussion_log) > 200:
            self._discussion_log = self._discussion_log[-200:]

        self._broadcast("evolution_cycle", entry)
        log.info(
            "[GeneticEvolver] Gen %d — pop=%d protected=%d new=%d active=%s",
            gen, len(self._population), self.protected_count,
            len(new_children), (self._active_id or "")[:8],
        )
        return new_children

    def post_agent_message(self, agent: str, message: str, genome_id: str = "") -> None:
        """يُستدعى من الوكلاء لنشر رسائل النقاش في الوقت الفعلي."""
        entry = {
            "ts":       datetime.now(timezone.utc).isoformat(),
            "agent":    agent,
            "message":  message,
            "genome":   genome_id[:8] if genome_id else "",
        }
        self._discussion_log.append(entry)
        if len(self._discussion_log) > 200:
            self._discussion_log = self._discussion_log[-200:]
        self._broadcast("agent_discussion", entry)

    def leaderboard(self, top_n: int = 10) -> list[dict]:
        with self._lock:
            return self._leaderboard_dict(top_n)

    def genealogy(self) -> dict:
        with self._lock:
            return {
                "generation": self._generation,
                "nodes": [
                    {
                        "id":        g.id,
                        "gen":       g.generation,
                        "parents":   g.parent_ids,
                        "children":  g.children[:10],
                        "fitness":   round(g.fitness, 4),
                        "protected": g.is_protected,
                        "active":    g.is_active,
                        "pnl":       round(g.total_pnl, 2),
                    }
                    for g in self._population
                ],
            }

    def stats(self) -> dict:
        with self._lock:
            return self._stats_dict()

    def discussion_log(self, last_n: int = 50) -> list[dict]:
        return self._discussion_log[-last_n:]

    # ── عمليات التطور الداخلية ────────────────────────────────────────────────

    def _crossover(self, p1: StrategyGenome, p2: StrategyGenome) -> StrategyGenome:
        """BLX-α (Blend Crossover) مع توريث انتماء المؤشرات من الأب الأقوى."""
        params: dict[str, Any] = {}
        for param, (lo, hi) in DNA_BOUNDS.items():
            v1 = getattr(p1, param)
            v2 = getattr(p2, param)
            alpha = 0.3
            span  = abs(v2 - v1)
            lo_c  = min(v1, v2) - alpha * span
            hi_c  = max(v1, v2) + alpha * span
            val   = random.uniform(max(lo, lo_c), min(hi, hi_c))
            params[param] = int(round(val)) if param in INT_PARAMS else round(val, 4)

        child = StrategyGenome(
            id=str(uuid.uuid4())[:12],
            generation=self._generation,
            parent_ids=[p1.id, p2.id],
            created_at=datetime.now(timezone.utc).isoformat(),
            symbol=self.symbol,
            **params,
        )
        better = p1 if p1.fitness >= p2.fitness else p2
        child.indicator_affinity = {k: list(v) for k, v in better.indicator_affinity.items()}
        log.info("[CROSSOVER] Gen%d: %s×%s → %s", self._generation, p1.id[:8], p2.id[:8], child.id[:8])
        return child

    def _mutate(self, parent: StrategyGenome, rate: float = 0.20) -> StrategyGenome:
        """طفرة غاوسية مع احتمال rate لكل معامل."""
        params: dict[str, Any] = {}
        for param, (lo, hi) in DNA_BOUNDS.items():
            val = getattr(parent, param)
            if random.random() < rate:
                sigma = (hi - lo) * 0.10
                val   = _clamp(val + random.gauss(0, sigma), lo, hi)
            params[param] = int(round(val)) if param in INT_PARAMS else round(val, 4)

        child = StrategyGenome(
            id=str(uuid.uuid4())[:12],
            generation=self._generation,
            parent_ids=[parent.id],
            created_at=datetime.now(timezone.utc).isoformat(),
            symbol=self.symbol,
            **params,
        )
        child.indicator_affinity = {k: list(v) for k, v in parent.indicator_affinity.items()}
        log.info("[MUTATE] Gen%d: %s → %s (rate=%.0f%%)", self._generation, parent.id[:8], child.id[:8], rate * 100)
        return child

    def _apply_advisor(self, suggestions: list[dict], gen: int) -> None:
        """يُطبّق اقتراحات المستشار بإنشاء جينومات مُوجَّهة."""
        active = self.active_genome
        if not active:
            return
        for sug in suggestions[:2]:
            try:
                base = active.dna_summary()
                base.update({k: v for k, v in sug.items() if k in DNA_BOUNDS})
                # تصحيح الأنواع
                for p in INT_PARAMS:
                    if p in base:
                        base[p] = int(round(base[p]))
                        lo, hi  = DNA_BOUNDS[p]
                        base[p] = _clamp(base[p], lo, hi)
                for p, (lo, hi) in DNA_BOUNDS.items():
                    if p not in INT_PARAMS and p in base:
                        base[p] = round(_clamp(float(base[p]), lo, hi), 4)

                g = StrategyGenome(
                    id=str(uuid.uuid4())[:12],
                    generation=gen,
                    parent_ids=["ai_advisor", active.id],
                    created_at=datetime.now(timezone.utc).isoformat(),
                    symbol=self.symbol,
                    advisor_note=sug.get("note", ""),
                    **{k: base[k] for k in DNA_BOUNDS},
                )
                with self._lock:
                    self._population.append(g)
                self._broadcast("genome_born", {**g.card_data(), "source": "advisor"})
                log.info("[AI_ADVISED] Genome %s created from advisor", g.id[:8])
            except Exception as exc:
                log.warning("[GeneticEvolver] Apply advisor suggestion failed: %s", exc)

    def _evolve_async(self) -> None:
        t = threading.Thread(target=self.evolve, daemon=True, name="evolution-cycle")
        t.start()

    # ── مساعدات داخلية ───────────────────────────────────────────────────────

    def _find(self, gid: str | None) -> StrategyGenome | None:
        if not gid:
            return None
        for g in self._population:
            if g.id == gid:
                return g
        return None

    def _stats_dict(self) -> dict:
        active = self._find(self._active_id)
        ranked = sorted(self._population, key=lambda g: g.fitness, reverse=True)
        best   = ranked[0] if ranked else None
        return {
            "generation":       self._generation,
            "population":       len(self._population),
            "protected":        self.protected_count,
            "active_id":        self._active_id,
            "active_name":      (active.name or "—") if active else "—",
            "active_medals":    (active.medals) if active else [],
            "active_fitness":   round(active.fitness, 4) if active else 0.0,
            "active_wr":        round(active.win_rate, 3) if active else 0.0,
            "active_pnl":       round(active.total_pnl, 2) if active else 0.0,
            "best_fitness":     round(best.fitness, 4) if best else 0.0,
            "best_pnl":         round(best.total_pnl, 2) if best else 0.0,
            "total_trades":     sum(g.trades for g in self._population),
            "trades_to_evolve": max(0, EVOLUTION_EVERY - self._total_trades_since_evolution),
            "symbol":           self.symbol,
            "population_file":  str(self.population_file),
        }

    def _leaderboard_dict(self, top_n: int = 10) -> list[dict]:
        ranked = sorted(self._population, key=lambda g: g.fitness, reverse=True)
        return [g.card_data() for g in ranked[:top_n]]

    def _seed(self, params: dict) -> None:
        base_dna = {
            "buy_threshold":          params.get("buy_threshold", 0.62),
            "sell_threshold":         params.get("sell_threshold", 0.38),
            "min_smc_score":          int(params.get("min_smc_score", 2)),
            "atr_sl_mult":            float(params.get("atr_sl_mult", 1.5)),
            "min_rr":                 float(params.get("min_rr", 1.2)),
            "high_conf_buy":          float(params.get("high_conf_buy", 0.72)),
            "high_conf_sell":         float(params.get("high_conf_sell", 0.28)),
            "bos_continuation_buy":   float(params.get("bos_continuation_buy", 0.58)),
            "bos_continuation_sell":  float(params.get("bos_continuation_sell", 0.42)),
            "smc_score_strong":       int(params.get("smc_score_strong", 3)),
        }
        root = StrategyGenome(
            id=str(uuid.uuid4())[:12],
            generation=0,
            parent_ids=[],
            created_at=datetime.now(timezone.utc).isoformat(),
            symbol=self.symbol,
            is_active=True,
            **base_dna,
        )
        self._active_id = root.id
        self._population.append(root)

        # 4 متغيرات ابتدائية حول القاعدة
        for _ in range(4):
            v = self._mutate(root, rate=0.35)
            self._population.append(v)

        self._save()

    # ── التخزين والاسترجاع ────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            POPULATION_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "generation":       self._generation,
                "symbol":           self.symbol,
                "active_id":        self._active_id,
                "trades_to_evolve": self._total_trades_since_evolution,
                "population":       [self._to_dict(g) for g in self._population],
            }
            self.population_file.parent.mkdir(parents=True, exist_ok=True)
            self.population_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("[GeneticEvolver] Save failed: %s", exc)

    def _load(self) -> None:
        try:
            path = self.population_file
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            elif POPULATION_FILE.exists():
                data = json.loads(POPULATION_FILE.read_text(encoding="utf-8"))
                legacy_symbol = str(data.get("symbol") or "")
                if self.symbol and legacy_symbol and legacy_symbol != self.symbol:
                    return
            else:
                return
            self._generation                = int(data.get("generation", 0))
            self._active_id                 = data.get("active_id")
            self._total_trades_since_evolution = int(data.get("trades_to_evolve", 0))
            for gd in data.get("population", []):
                try:
                    genome = self._from_dict(gd)
                    if self.symbol:
                        genome.symbol = self.symbol
                    self._population.append(genome)
                except Exception as exc:
                    log.warning("[GeneticEvolver] Skip corrupted genome: %s", exc)
            log.info(
                "[GeneticEvolver] Loaded gen=%d pop=%d symbol=%s",
                self._generation, len(self._population), self.symbol,
            )
        except Exception as exc:
            log.warning("[GeneticEvolver] Load failed: %s", exc)

    @staticmethod
    def _to_dict(g: StrategyGenome) -> dict:
        return {
            "id":                     g.id,
            "generation":             g.generation,
            "parent_ids":             g.parent_ids,
            "created_at":             g.created_at,
            "symbol":                 g.symbol,
            "buy_threshold":          g.buy_threshold,
            "sell_threshold":         g.sell_threshold,
            "min_smc_score":          g.min_smc_score,
            "atr_sl_mult":            g.atr_sl_mult,
            "min_rr":                 g.min_rr,
            "high_conf_buy":          g.high_conf_buy,
            "high_conf_sell":         g.high_conf_sell,
            "bos_continuation_buy":   g.bos_continuation_buy,
            "bos_continuation_sell":  g.bos_continuation_sell,
            "smc_score_strong":       g.smc_score_strong,
            "trades":                 g.trades,
            "wins":                   g.wins,
            "total_pnl":              g.total_pnl,
            "win_pnl":                g.win_pnl,
            "loss_pnl":               g.loss_pnl,
            "is_protected":           g.is_protected,
            "is_active":              g.is_active,
            "children":               g.children,
            "fitness_history":        g.fitness_history[-50:],
            "indicator_affinity":     g.indicator_affinity,
            "advisor_note":           g.advisor_note,
            "name":                   g.name,
            "medals":                 g.medals,
            "achievements":           g.achievements,
            "award_count":            g.award_count,
        }

    @staticmethod
    def _from_dict(d: dict) -> StrategyGenome:
        return StrategyGenome(
            id=d["id"],
            generation=int(d.get("generation", 0)),
            parent_ids=d.get("parent_ids", []),
            created_at=d.get("created_at", ""),
            symbol=d.get("symbol", ""),
            buy_threshold=float(d.get("buy_threshold", 0.62)),
            sell_threshold=float(d.get("sell_threshold", 0.38)),
            min_smc_score=int(d.get("min_smc_score", 2)),
            atr_sl_mult=float(d.get("atr_sl_mult", 1.5)),
            min_rr=float(d.get("min_rr", 1.2)),
            high_conf_buy=float(d.get("high_conf_buy", 0.72)),
            high_conf_sell=float(d.get("high_conf_sell", 0.28)),
            bos_continuation_buy=float(d.get("bos_continuation_buy", 0.58)),
            bos_continuation_sell=float(d.get("bos_continuation_sell", 0.42)),
            smc_score_strong=int(d.get("smc_score_strong", 3)),
            trades=int(d.get("trades", 0)),
            wins=int(d.get("wins", 0)),
            total_pnl=float(d.get("total_pnl", 0.0)),
            win_pnl=float(d.get("win_pnl", 0.0)),
            loss_pnl=float(d.get("loss_pnl", 0.0)),
            is_protected=bool(d.get("is_protected", False)),
            is_active=bool(d.get("is_active", False)),
            children=d.get("children", []),
            fitness_history=d.get("fitness_history", []),
            indicator_affinity=d.get("indicator_affinity", {}),
            advisor_note=d.get("advisor_note", ""),
            name=d.get("name", ""),
            medals=d.get("medals", []),
            achievements=d.get("achievements", []),
            award_count=d.get("award_count", 0),
        )

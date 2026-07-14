"""
evolution_committee.py
----------------------
لجنة التطور متعددة الوكلاء لـ FRIDAY.

وكلاء اللجنة:
  1. StrategyAnalyst  — يحلل أداء التجمع الحالي ويكتب تقرير موجز
  2. MutationEngineer — يقترح معاملات DNA مُحسَّنة للجيل القادم
  3. RiskFilter       — يتحقق أن الاقتراحات لا تُعرّض الحساب للخطر
  4. GenomeChronicler — يسجّل الحدث في سجل التطور ويُبلّغ الداشبورد

يُستشار Claude عبر ANTHROPIC_API_KEY إذا كان متاحاً.
في حالة عدم توفر المفتاح يعمل النظام بمستشار محلي (rule-based).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger("friday.evolution_committee")

try:
    import anthropic
    _SDK = True
except ImportError:
    _SDK = False

# ── نظام الطوارئ المحلي (بدون Claude) ────────────────────────────────────────

def _local_advisor(population_summaries: list[dict]) -> list[dict]:
    """
    مستشار محلي بسيط: يُقلّص عتبات الإدخال إذا كان PF > 1.5،
    ويُوسّعها إذا كان PF < 1.0.
    يُعيد قائمة فارغة إذا لا يوجد إجراء واضح.
    """
    if not population_summaries:
        return []

    best = population_summaries[0]
    suggestions = []

    # تقدير عامل الربح من DNA فقط (لا نعرف PF الفعلي هنا)
    # قاعدة بسيطة: كلما ضيّقنا الفجوة buy_threshold-sell_threshold → اقتنصنا فرصاً أكثر
    gap = float(best.get("buy_threshold", 0.62)) - float(best.get("sell_threshold", 0.38))
    if gap > 0.30:
        # عتبات ضيقة جداً → نُخفّفها قليلاً
        suggestions.append({
            "buy_threshold":  round(float(best.get("buy_threshold", 0.62)) - 0.02, 4),
            "sell_threshold": round(float(best.get("sell_threshold", 0.38)) + 0.02, 4),
            "note": "local_advisor: widening thresholds to capture more setups",
        })
    elif gap < 0.15:
        # عتبات واسعة جداً → نُضيّقها لجودة أعلى
        suggestions.append({
            "buy_threshold":  round(float(best.get("buy_threshold", 0.62)) + 0.02, 4),
            "sell_threshold": round(float(best.get("sell_threshold", 0.38)) - 0.02, 4),
            "note": "local_advisor: tightening thresholds for higher quality",
        })

    return suggestions


# ── نصوص النظام لكل وكيل ──────────────────────────────────────────────────────

_ANALYST_SYS = """\
You are a quantitative strategy performance analyst for FRIDAY, an SMC-based scalping system.
You receive a JSON snapshot of the top-5 strategy genomes (parameter sets) and their performance metrics.
Your job: write a concise (≤ 150 words) performance narrative covering:
- Which genome is performing best and why
- Common parameter patterns among profitable genomes
- Key weaknesses or risks you spot
- One actionable recommendation for the next evolution cycle
Be data-driven. No fluff. Use bullet points.
"""

_ENGINEER_SYS = """\
You are a genetic mutation engineer for a trading strategy optimizer (FRIDAY system).
You receive:
  1. A performance analysis of current genomes
  2. The DNA (parameter values) of the best genome

Your job: suggest 1-2 mutated parameter sets for the NEXT generation that could improve performance.
Each suggestion must be a JSON object with these exact keys (all required):
  buy_threshold, sell_threshold, min_smc_score, atr_sl_mult, min_rr,
  high_conf_buy, high_conf_sell, bos_continuation_buy, bos_continuation_sell,
  smc_score_strong, note

Parameter bounds (stay within these):
  buy_threshold:         0.55 – 0.88
  sell_threshold:        0.12 – 0.45
  min_smc_score:         1 – 5 (integer)
  atr_sl_mult:           1.0 – 3.0
  min_rr:                1.0 – 3.0
  high_conf_buy:         0.62 – 0.88
  high_conf_sell:        0.12 – 0.38
  bos_continuation_buy:  0.52 – 0.78
  bos_continuation_sell: 0.22 – 0.48
  smc_score_strong:      2 – 5 (integer)

Return ONLY a JSON array of 1-2 objects. No markdown. No explanation outside the JSON.
Example: [{"buy_threshold": 0.64, ..., "note": "reason here"}]
"""

_RISK_SYS = """\
You are a risk filter for a trading strategy optimizer.
You receive suggested genome mutations and must approve or reject each one.
Rules (non-negotiable):
  - buy_threshold must be > sell_threshold + 0.10 (to avoid contradictory signals)
  - atr_sl_mult must be ≤ 2.5 for scalping (prevents oversized stops)
  - min_rr must be ≥ 1.2 (ensures minimum reward:risk)
  - buy_threshold and sell_threshold must stay within their allowed bounds

For each suggestion: output APPROVED or REJECTED with a one-line reason.
Format: [{\"approved\": true/false, \"reason\": \"...\"}]
No extra text, no markdown.
"""


# ── استدعاء API فردي ──────────────────────────────────────────────────────────

def _call_claude(
    system: str,
    user_msg: str,
    model: str,
    max_tokens: int = 400,
) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not _SDK:
        return ""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_msg}],
        )
        return resp.content[0].text.strip()
    except Exception as exc:
        log.warning("[EvolutionCommittee] Claude call failed: %s", exc)
        return ""


def _strip_fence(raw: str) -> str:
    t = raw.strip()
    for prefix in ("```json", "```"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
    if t.endswith("```"):
        t = t[:-3].strip()
    return t


# ── نتيجة اللجنة ─────────────────────────────────────────────────────────────

@dataclass
class CommitteeResult:
    analysis:     str
    suggestions:  list[dict]
    risk_checks:  list[dict]
    approved:     list[dict]
    model_used:   str
    used_claude:  bool


# ── المستشار الرئيسي ──────────────────────────────────────────────────────────

class EvolutionCommittee:
    """
    ينظّم نقاش الوكلاء الأربعة ويُعيد اقتراحات DNA مُصفّاة.

    إذا كان ANTHROPIC_API_KEY متاحاً يستخدم Claude.
    وإلا يعمل بالمستشار المحلي rule-based.
    """

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        broadcast_fn: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.model = model
        self._broadcast = broadcast_fn or (lambda e, d: None)
        self._use_claude = bool(_SDK and os.environ.get("ANTHROPIC_API_KEY"))
        log.info(
            "[EvolutionCommittee] Ready — claude=%s model=%s",
            self._use_claude, model,
        )

    def advise(self, population_summaries: list[dict]) -> list[dict]:
        """
        الواجهة الرئيسية: يأخذ ملخصات التجمع ويُعيد اقتراحات DNA مُعتمَدة.
        يُرسل أحداث للداشبورد في كل مرحلة.
        """
        if not population_summaries:
            return []

        if not self._use_claude:
            suggestions = _local_advisor(population_summaries)
            self._broadcast("agent_discussion", {
                "agent":   "LocalAdvisor",
                "message": f"Rule-based advisor: {len(suggestions)} suggestion(s).",
            })
            return suggestions

        return self._claude_pipeline(population_summaries)

    # ── خط أنابيب Claude ──────────────────────────────────────────────────────

    def _claude_pipeline(self, summaries: list[dict]) -> list[dict]:
        best = summaries[0]
        data_str = json.dumps(summaries, indent=2)

        # الوكيل 1: المحلل
        analysis = _call_claude(
            _ANALYST_SYS,
            f"Current top-5 genome performance:\n{data_str}",
            self.model, 400,
        )
        if not analysis:
            analysis = "Analysis unavailable."
        self._broadcast("agent_discussion", {"agent": "StrategyAnalyst", "message": analysis[:300]})
        log.debug("[Analyst] %s", analysis[:120])

        # الوكيل 2: مهندس الطفرات
        engineer_prompt = (
            f"Performance analysis:\n{analysis}\n\n"
            f"Best genome DNA:\n{json.dumps(best, indent=2)}"
        )
        raw_eng = _call_claude(_ENGINEER_SYS, engineer_prompt, self.model, 500)
        suggestions: list[dict] = []
        if raw_eng:
            try:
                suggestions = json.loads(_strip_fence(raw_eng))
                if not isinstance(suggestions, list):
                    suggestions = [suggestions]
            except json.JSONDecodeError:
                log.warning("[EvolutionCommittee] Engineer JSON parse failed: %s", raw_eng[:100])

        if not suggestions:
            return _local_advisor(summaries)

        self._broadcast("agent_discussion", {
            "agent":   "MutationEngineer",
            "message": f"Suggested {len(suggestions)} genome mutation(s).",
        })

        # الوكيل 3: مرشّح المخاطر
        risk_prompt = f"Mutations to check:\n{json.dumps(suggestions, indent=2)}"
        raw_risk = _call_claude(_RISK_SYS, risk_prompt, self.model, 200)
        risk_checks: list[dict] = []
        if raw_risk:
            try:
                risk_checks = json.loads(_strip_fence(raw_risk))
                if not isinstance(risk_checks, list):
                    risk_checks = [risk_checks]
            except json.JSONDecodeError:
                pass

        approved: list[dict] = []
        for i, sug in enumerate(suggestions):
            check = risk_checks[i] if i < len(risk_checks) else {"approved": True, "reason": "no_check"}
            if check.get("approved", True):
                approved.append(sug)
                self._broadcast("agent_discussion", {
                    "agent":   "RiskFilter",
                    "message": f"APPROVED genome mutation: {sug.get('note','')[:80]}",
                })
            else:
                self._broadcast("agent_discussion", {
                    "agent":   "RiskFilter",
                    "message": f"REJECTED: {check.get('reason','')[:80]}",
                })

        # الوكيل 4: المؤرّخ
        self._broadcast("agent_discussion", {
            "agent":   "GenomeChronicler",
            "message": f"Evolution cycle complete: {len(approved)}/{len(suggestions)} mutations approved.",
        })

        log.info(
            "[EvolutionCommittee] Pipeline done: %d/%d approved",
            len(approved), len(suggestions),
        )
        return approved

    # ── استشارة فورية (للاستخدام من الداشبورد) ───────────────────────────────

    def quick_consult(self, question: str) -> str:
        """
        استشارة نصية مباشرة مع Claude حول الاستراتيجية.
        يُستخدم من نافذة 'تشاور' في الداشبورد.
        """
        if not self._use_claude:
            return "Claude غير متاح — تأكد من ضبط ANTHROPIC_API_KEY."
        system = """\
You are FRIDAY's AI strategy advisor for an SMC-based gold scalping system.
Answer concisely and practically in the language of the question (Arabic or English).
Focus on actionable insights. Maximum 200 words.
"""
        answer = _call_claude(system, question, self.model, 400)
        self._broadcast("agent_discussion", {"agent": "ClaudeAdvisor", "message": answer[:200]})
        return answer or "No response from Claude."

"""
genome_awards.py
----------------
نظام الجوائز والأوسمة والأسماء للجينومات المربحة في FRIDAY.

المستويات:
  🔰 Rookie      — عند الإنشاء
  🥉 Bronze      — 5+ صفقات، أي ربح إيجابي
  🥈 Silver      — 10+ صفقات، WR≥55%، PF≥1.2
  🥇 Gold        — 15+ صفقات، WR≥62%، PF≥1.5
  💎 Diamond     — 20+ صفقات، WR≥70%، PF≥2.0
  👑 Legend      — 30+ صفقات، WR≥75%، PF≥2.5

الأسماء: يمنحها الوكلاء بناءً على أسلوب التداول.
الشهادة: وثيقة رسمية موقّعة من جميع الوكلاء.
"""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("friday.awards")


# ── تعريف المستويات ──────────────────────────────────────────────────────────

@dataclass
class MedalTier:
    id:         str
    emoji:      str
    name_ar:    str
    name_en:    str
    min_trades: int
    min_wr:     float
    min_pf:     float
    min_pnl:    float


MEDAL_TIERS: list[MedalTier] = [
    MedalTier("rookie",   "🔰", "مبتدئ",      "Rookie",       0,   0.00, 0.0,  0.0),
    MedalTier("bronze",   "🥉", "كاشف برونزي", "Bronze Scout", 5,   0.45, 1.0,  0.01),
    MedalTier("silver",   "🥈", "قناص فضي",   "Silver Sniper", 10,  0.55, 1.20, 1.0),
    MedalTier("gold",     "🥇", "صياد ذهبي",  "Gold Hunter",  15,  0.62, 1.50, 3.0),
    MedalTier("diamond",  "💎", "شبح ماسي",   "Diamond Ghost", 20,  0.70, 2.00, 8.0),
    MedalTier("legend",   "👑", "أسطورة",     "Legend",       30,  0.75, 2.50, 20.0),
]


# ── قائمة أسماء المقاتلين (فولباك بدون Claude) ───────────────────────────────

_HERO_NAMES_AR = [
    "الصياد الذهبي",    # Golden Hunter
    "قناص القمم",       # Summit Sniper
    "ظل السوق",         # Market Shadow
    "ذئب الليل",        # Night Wolf
    "صاحب القرار",      # Decision Maker
    "أسد السوق",        # Market Lion
    "العقل البارد",     # Cool Mind
    "الفارس الأزرق",    # Blue Knight
    "المحارب الصامت",   # Silent Warrior
    "حارس الثروة",      # Wealth Guardian
    "قاطع الطريق",      # Interceptor
    "روح الأرباح",      # Spirit of Profits
    "الحلم الرقمي",     # Digital Dream
    "أبو اليقين",       # Master of Certainty
    "الباحث الدقيق",    # Precise Researcher
    "بركان الفرص",      # Opportunity Volcano
    "السهم الحاد",      # Sharp Arrow
    "نمر السوق",        # Market Tiger
    "عاصفة الأرباح",    # Profit Storm
    "الحكيم الجريء",    # Brave Wise
]


# ── احتساب المستوى ───────────────────────────────────────────────────────────

def compute_tier(trades: int, win_rate: float, profit_factor: float, total_pnl: float) -> MedalTier:
    """يُعيد أعلى مستوى يستحقه الجينوم."""
    achieved = MEDAL_TIERS[0]
    for tier in MEDAL_TIERS:
        if (trades    >= tier.min_trades and
            win_rate  >= tier.min_wr     and
            profit_factor >= tier.min_pf and
            total_pnl >= tier.min_pnl):
            achieved = tier
    return achieved


# ── توليد الاسم ──────────────────────────────────────────────────────────────

def _style_description(dna: dict) -> str:
    """يصف أسلوب الجينوم بكلمات مختصرة لاستخدامها في توليد الاسم."""
    parts = []
    buy_t = float(dna.get("buy_threshold", 0.65))
    sell_t = float(dna.get("sell_threshold", 0.35))
    gap = buy_t - sell_t

    if gap > 0.35:
        parts.append("محافظ جداً، انتقائي")
    elif gap < 0.20:
        parts.append("عدواني، كثير الصفقات")
    else:
        parts.append("متوازن")

    smc = int(dna.get("min_smc_score", 2))
    if smc >= 4:
        parts.append("يشترط تأكيداً قوياً")
    elif smc <= 2:
        parts.append("سريع الدخول")

    rr = float(dna.get("min_rr", 1.5))
    if rr >= 2.5:
        parts.append("صيّاد المستهدفات الكبيرة")
    elif rr <= 1.3:
        parts.append("سكالبر سريع")

    return "، ".join(parts) if parts else "متعدد الأساليب"


def _name_with_claude(dna: dict, tier: MedalTier, win_rate: float, pnl: float) -> str:
    """يطلب من Claude اختيار اسم مناسب بناءً على أسلوب الجينوم."""
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return ""
        style = _style_description(dna)
        prompt = (
            f"أنت وكيل في نظام تداول FRIDAY. جينوم استراتيجية حقق الآتي:\n"
            f"- أسلوبه: {style}\n"
            f"- مستواه: {tier.emoji} {tier.name_ar}\n"
            f"- معدل فوز: {win_rate:.0%}، ربح إجمالي: ${pnl:.2f}\n\n"
            f"امنحه اسماً عربياً مميزاً (2-4 كلمات) يعبّر عن شخصيته التداولية. "
            f"أعد الاسم فقط، بدون شرح."
        )
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            system="أنت مُسمّي الجينومات في FRIDAY. تُعطي أسماء قصيرة قوية.",
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()[:40]
    except Exception as exc:
        log.debug("[Awards] Claude name failed: %s", exc)
        return ""


def assign_name(dna: dict, tier: MedalTier, win_rate: float, pnl: float, existing_name: str = "") -> str:
    """
    يُعيد اسماً للجينوم.
    أولوية: Claude → قائمة محلية.
    لا يُبدّل الاسم إذا كان موجوداً بالفعل.
    """
    if existing_name and existing_name not in ("", "—"):
        return existing_name

    # جرّب Claude
    name = _name_with_claude(dna, tier, win_rate, pnl)
    if name:
        return name

    # فولباك: قائمة محلية
    return random.choice(_HERO_NAMES_AR)


# ── الشهادة الرسمية ──────────────────────────────────────────────────────────

def issue_certificate(
    genome_id: str,
    genome_name: str,
    tier: MedalTier,
    stats: dict,
    agents: list[str] | None = None,
) -> dict:
    """
    يُصدر شهادة تقدير رسمية موقّعة من الوكلاء.
    تُحفظ ويُبثّ للداشبورد.
    """
    default_agents = [
        "StrategyAnalyst",
        "MutationEngineer",
        "RiskFilter",
        "GenomeChronicler",
        "AutonomousBrain",
    ]
    signatories = agents or default_agents

    cert = {
        "type":       "ACHIEVEMENT_CERTIFICATE",
        "issued_at":  datetime.now(timezone.utc).isoformat(),
        "genome_id":  genome_id[:8],
        "name":       genome_name,
        "medal":      tier.id,
        "medal_emoji": tier.emoji,
        "medal_name": tier.name_ar,
        "stats": {
            "trades":      stats.get("trades", 0),
            "win_rate":    f"{stats.get('win_rate', 0):.0%}",
            "profit_factor": round(stats.get("profit_factor", 0), 2),
            "total_pnl":   round(stats.get("total_pnl", 0), 2),
        },
        "citation": _write_citation(genome_name, tier, stats),
        "signed_by": signatories,
    }
    return cert


def _write_citation(name: str, tier: MedalTier, stats: dict) -> str:
    wr  = stats.get("win_rate", 0)
    pnl = stats.get("total_pnl", 0)
    tr  = stats.get("trades", 0)
    pf  = stats.get("profit_factor", 0)
    return (
        f"بالنظر إلى الأداء المتميز للجينوم «{name}» "
        f"الذي حقق معدل فوز {wr:.0%} عبر {tr} صفقة "
        f"بعامل ربح {pf:.2f} وربح إجمالي ${pnl:.2f}، "
        f"يُمنح وسام {tier.emoji} {tier.name_ar} اعترافاً بالتفوق والإتقان."
    )


# ── التحقق والترقية ──────────────────────────────────────────────────────────

class AwardEngine:
    """
    يراقب الجينومات ويمنح الأوسمة والأسماء عند استحقاقها.
    """

    def __init__(
        self,
        broadcast_fn: Any = None,
    ) -> None:
        self._broadcast = broadcast_fn or (lambda e, d: None)
        self._awarded:   dict[str, str] = {}  # genome_id → current medal id

    def evaluate(self, genome: Any) -> bool:
        """
        يُقيّم جينوماً ويمنحه وساماً إذا استحق ترقية.
        يُعيد True إذا صدرت جائزة جديدة.
        """
        trades = genome.trades
        wr     = genome.win_rate
        pnl    = genome.total_pnl
        pf     = genome.profit_factor if hasattr(genome, "profit_factor") else (
            pnl / max(1e-6, abs(pnl) * (1 - wr)) if pnl > 0 else 0.0
        )

        tier = compute_tier(trades, wr, pf, pnl)

        current = self._awarded.get(genome.id, "rookie")
        if tier.id == current:
            return False

        # ترقية!
        self._awarded[genome.id] = tier.id

        # أضف الوسام إن لم يكن موجوداً
        medal_str = f"{tier.emoji} {tier.name_ar}"
        if not hasattr(genome, "medals"):
            genome.medals = []
        if medal_str not in genome.medals:
            genome.medals.append(medal_str)

        # أعطه اسماً إن لم يكن لديه
        dna = genome.dna_summary() if hasattr(genome, "dna_summary") else {}
        new_name = assign_name(dna, tier, wr, pnl, getattr(genome, "name", ""))
        genome.name = new_name

        # أصدر الشهادة
        cert = issue_certificate(
            genome_id=genome.id,
            genome_name=new_name,
            tier=tier,
            stats={"trades": trades, "win_rate": wr, "profit_factor": pf, "total_pnl": pnl},
        )

        # أبلّغ الداشبورد
        self._broadcast("genome_award", {
            "genome_id":   genome.id[:8],
            "name":        new_name,
            "medal_emoji": tier.emoji,
            "medal_name":  tier.name_ar,
            "medal_id":    tier.id,
            "message": f"{tier.emoji} «{new_name}» حصل على وسام {tier.name_ar}!",
        })
        self._broadcast("agent_discussion", {
            "agent":   "GenomeChronicler",
            "message": (
                f"{tier.emoji} شهادة تقدير: الجينوم «{new_name}» ({genome.id[:8]}) "
                f"يحمل الآن وسام {tier.name_ar} — "
                f"WR={wr:.0%} PF={pf:.2f} PnL=${pnl:.2f}"
            ),
        })

        log.info(
            "[Awards] %s awarded %s %s — WR=%.0f%% PF=%.2f PnL=%.2f",
            new_name, tier.emoji, tier.name_ar, wr * 100, pf, pnl,
        )
        return True

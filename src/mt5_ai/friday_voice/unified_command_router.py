"""Shared lightweight routing helpers for FRIDAY voice, desktop, and Qader."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


ARABIC_RE = re.compile(r"[\u0600-\u06ff]")


@dataclass(slots=True)
class UnifiedRoute:
    text: str
    normalized: str
    language: str
    domain: str
    handled: bool = False
    intent: str = "chat"
    requires_confirmation: bool = False
    message: str = ""
    tool_context: dict[str, Any] = field(default_factory=dict)


def normalize_user_text(text: str) -> str:
    value = (text or "").strip()
    value = value.replace("ـ", "")
    value = re.sub(r"\s+", " ", value)
    replacements = {
        "داشبورت": "داشبورد",
        "الشارت": "شارت",
        "الشارط": "شارت",
        "فرايدي": "friday",
        "كادر": "قادر",
        "غادر": "قادر",
    }
    lowered = value.lower()
    for src, dst in replacements.items():
        lowered = lowered.replace(src, dst)
    return lowered.strip()


def detect_language(text: str) -> str:
    return "ar" if ARABIC_RE.search(text or "") else "en"


def classify_domain(text: str) -> str:
    normalized = normalize_user_text(text)
    if any(x in normalized for x in ["قادر", "qader", "demo", "ديمو", "صفقة", "xau", "ذهب"]):
        return "qader"
    if any(x in normalized for x in ["friday", "jarvis", "الصوت", "افتح", "شغل", "سكرين", "شارت"]):
        return "device"
    if any(x in normalized for x in ["status", "health", "الحالة", "الخدمات", "الوضع"]):
        return "status"
    if any(x in normalized for x in ["market", "analysis", "حلل", "السوق"]):
        return "market"
    return "chat"


def route_text(text: str) -> UnifiedRoute:
    normalized = normalize_user_text(text)
    return UnifiedRoute(
        text=text or "",
        normalized=normalized,
        language=detect_language(normalized),
        domain=classify_domain(normalized),
    )

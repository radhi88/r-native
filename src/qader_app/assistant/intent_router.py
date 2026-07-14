"""Text intent routing for Qader assistant commands."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Intent:
    name: str
    permission: str | None = None
    dangerous: bool = False
    requires_confirmation: bool = False
    args: dict = field(default_factory=dict)


class IntentRouter:
    DANGEROUS = {
        "enable_demo",
        "change_risk",
        "modify_genome",
        "long_session",
        "package_update",
    }

    def route(self, text: str) -> Intent:
        raw = (text or "").strip()
        t = raw.lower()
        if not t:
            return Intent("empty")
        if any(word in t for word in ["stop all", "emergency", "إيقاف", "وقف كل", "اوقف"]):
            return Intent("emergency_stop")
        if "live" in t or "حقيقي" in t:
            return Intent("live_trading_request", "can_place_live_orders", True, True)
        if "demo" in t or "ديمو" in t:
            return Intent("enable_demo", "can_run_demo_controlled", True, True)
        if "dry-run" in t or "dry run" in t or "محاكاة" in t:
            return Intent("switch_mode", "can_run_dry_run", args={"mode": "dry_run_simulation"})
        if "strategy dna" in t or "genome" in t or "جينوم" in t or "dna" in t:
            return Intent("modify_genome", "can_modify_strategy_dna", True, True)
        if "risk" in t or "مخاطر" in t:
            return Intent("change_risk", "can_modify_strategy_dna", True, True)
        if "package" in t or "exe" in t or "build" in t:
            return Intent("package_update", "can_apply_code_updates", True, True)
        if "signal" in t or "إشارة" in t or "اشارات" in t:
            return Intent("show_signals", "can_scan_market")
        if "scan" in t or "gold" in t or "xau" in t or "ذهب" in t or "حلل" in t:
            symbol = "XAUUSDm" if any(x in t for x in ["gold", "xau", "ذهب"]) else ""
            return Intent("scan_market", "can_scan_market", args={"symbol": symbol})
        if "tone" in t or "أسلوب" in t or "direct" in t or "مختصر" in t:
            return Intent("update_tone", "can_save_memory", args={"text": raw})
        if "save" in t or "default" in t or "احفظ" in t:
            return Intent("save_preference", "can_save_memory", args={"text": raw})
        if "explain" in t or "اشرح" in t:
            return Intent("explain_last_decision")
        return Intent("chat", args={"text": raw})


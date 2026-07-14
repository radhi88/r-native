"""Qader assistant identity and safe command handling."""
from __future__ import annotations

from qader_app.assistant.intent_router import Intent, IntentRouter
from qader_app.assistant.memory import QaderMemory
from qader_app.assistant.permissions_guard import PermissionsGuard
from qader_app.storage.audit_log import log_action
from qader_app.storage.profile_store import ProfileStore
from qader_app.storage.settings_store import SettingsStore
from mt5_ai.friday_voice.unified_command_router import normalize_user_text, route_text


INTRO_AR = (
    "أنا قادر، مساعدك الذكي لتحليل السوق وإدارة مشروع MT5. "
    "أقدر أراقب السوق، أحلل الإشارات، أتعلم من النتائج، وأضبط إعداداتي حسب الصلاحيات التي تمنحني إياها. "
    "قبل أن أبدأ، سألتزم فقط بما تسمح لي به."
)
INTRO_EN = (
    "I am Qader, your intelligent assistant for market analysis and MT5 workflow control. "
    "I can monitor the market, analyze signals, learn from results, and adjust my settings based on the permissions you grant me. "
    "I will only act within your approved permissions."
)


class QaderBrain:
    def __init__(
        self,
        guard: PermissionsGuard | None = None,
        memory: QaderMemory | None = None,
        router: IntentRouter | None = None,
    ):
        self.guard = guard or PermissionsGuard()
        self.memory = memory or QaderMemory()
        self.router = router or IntentRouter()
        self.profile_store = ProfileStore()
        self.settings_store = SettingsStore()
        self.pending_confirmation: Intent | None = None

    def introduction(self) -> str:
        language = self.profile_store.load().get("language", "bilingual")
        if language == "Arabic":
            return INTRO_AR
        if language == "English":
            return INTRO_EN
        return f"{INTRO_AR}\n\n{INTRO_EN}"

    def handle_text(self, text: str, confirmed: bool = False) -> dict:
        unified = route_text(text)
        intent = self.router.route(unified.normalized)
        if intent.name == "empty":
            return {"ok": False, "message": "No command received.", "intent": intent.name}

        if intent.name == "live_trading_request":
            message = "Real trading requires manual confirmation from the permissions screen."
            log_action(intent.name, intent.permission, False, "manual_permissions_screen_required", "qader_brain")
            return {"ok": False, "message": message, "intent": intent.name, "requires_confirmation": True}

        if confirmed and self.pending_confirmation:
            intent = self.pending_confirmation
            self.pending_confirmation = None

        if intent.requires_confirmation and not confirmed:
            self.pending_confirmation = intent
            message = f"Command `{intent.name}` requires confirmation before Qader can continue."
            log_action(intent.name, intent.permission, False, "confirmation_required", "qader_brain")
            return {"ok": False, "message": message, "intent": intent.name, "requires_confirmation": True}

        if intent.permission:
            perm = self.guard.check(intent.permission, intent.name, "qader_brain")
            if not perm.allowed:
                return {"ok": False, "message": perm.reason, "intent": intent.name, "permission": intent.permission}

        result = self._execute_safe_intent(intent)
        result.setdefault("domain", unified.domain)
        result.setdefault("language", unified.language)
        result.setdefault("normalized_text", normalize_user_text(text))
        return result

    def _execute_safe_intent(self, intent: Intent) -> dict:
        if intent.name == "live_trading_request":
            return {"ok": False, "message": "Real trading requires manual confirmation from the permissions screen.", "intent": intent.name}
        if intent.name == "emergency_stop":
            log_action("emergency_stop_requested", None, True, "user_requested_stop", "qader_brain")
            return {"ok": True, "message": "Emergency stop requested. Scanner, runner, and voice tasks should stop.", "intent": intent.name}
        if intent.name == "switch_mode":
            self.settings_store.save({"mode": intent.args.get("mode", "dry_run_simulation")})
            return {"ok": True, "message": "Mode updated to dry-run simulation.", "intent": intent.name}
        if intent.name == "scan_market":
            symbol = intent.args.get("symbol") or "selected symbols"
            return {"ok": True, "message": f"Ready to scan {symbol}.", "intent": intent.name, "args": intent.args}
        if intent.name == "show_signals":
            return {"ok": True, "message": "Open the scanner panel to view current SignalArbiter outputs.", "intent": intent.name}
        if intent.name == "modify_genome":
            return {"ok": True, "message": "Qader can propose DNA changes; source code will not be modified.", "intent": intent.name}
        if intent.name == "update_tone":
            self.memory.remember_preference("tone_instruction", intent.args.get("text", ""))
            return {"ok": True, "message": "Tone preference saved.", "intent": intent.name}
        if intent.name == "save_preference":
            self.memory.remember_preference("last_saved_instruction", intent.args.get("text", ""))
            return {"ok": True, "message": "Preference saved locally.", "intent": intent.name}
        if intent.name == "explain_last_decision":
            last = self.memory.load().get("last_decision")
            return {"ok": True, "message": str(last or "No previous decision is stored yet."), "intent": intent.name}
        if intent.name == "package_update":
            return {"ok": True, "message": "Packaging updates can be prepared, but require explicit review before running a build.", "intent": intent.name}
        log_action(intent.name, intent.permission, True, "handled_as_chat", "qader_brain")
        return {"ok": True, "message": "I can help with market scanning, dry-run analysis, permissions, memory, and strategy DNA.", "intent": intent.name}

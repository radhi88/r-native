from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .config import log_event
from .device_tools import DeviceTools
from .gateway_client import GatewayClient
from .memory import FridayMemory
from .mt5_tools import MT5Tools
from .unified_command_router import normalize_user_text, route_text


@dataclass(slots=True)
class CommandResult:
    category: str
    user_text: str
    tool_name: str | None = None
    tool_context: dict[str, Any] = field(default_factory=dict)
    direct_response: str | None = None


class CommandRouter:
    CATEGORIES = {
        "CHAT",
        "MARKET_ANALYSIS",
        "SYSTEM_COMMAND",
        "FILE_COMMAND",
        "STATUS",
        "AUTOMATION",
        "MEMORY_QUERY",
        "DEVICE_CONTROL",
        "mt5_query",    # D-01: price, positions, balance from MT5Tools directly
        "agent_query",  # D-01: dispatch jobs and pending patches from Gateway
        "control",      # D-01: stop/start/launch/send commands
    }

    _DEVICE_TRIGGERS = [
        "افتح", "فتح", "اشغل", "شغّل",
        "ارفع الصوت", "خفض الصوت", "اخفض الصوت", "زيد الصوت", "قلل الصوت",
        "الصوت", "سكرين شوت", "صورة الشاشة", "التقط الشاشة",
        "معلومات الجهاز", "حالة الجهاز", "كم رام",
        "فرايدي", "chrome", "edge", "notepad", "calc", "explorer",
        "كروم", "ايدج", "مفكرة", "حاسبة", "داشبورد", "الداشبورد", "داشبورت", "الداشبورت",
        "لوحة التحكم", "الشات", "الوكلاء",
        # Multi-monitor
        "وش تشوف", "وريني", "شوف الشاشة", "الشاشتين", "كل الشاشات",
    ]

    def __init__(self, mt5_tools: MT5Tools, memory: FridayMemory):
        self.mt5_tools = mt5_tools
        self.memory = memory
        self.device = DeviceTools()
        self.gateway = GatewayClient()
        self.tools = {
            "mt5.market_snapshot": self.mt5_tools.market_snapshot,
            "mt5.system_status": self.mt5_tools.system_status,
            "mt5.feature_council": self.mt5_tools.feature_council,
            "mt5.qader_state": self.mt5_tools.get_qader_state,
            "memory.search": self.memory.search,
        }

    @staticmethod
    def _detect_mt5_sub(text: str) -> str:
        """Determine which MT5 data sub-type the text requests."""
        t = text.lower()
        if any(x in t for x in ["رصيد", "الرصيد", "balance", "equity", "بلانس", "ايكويتي", "رأس المال"]):
            return "balance"
        if any(x in t for x in ["صفقات", "مراكز", "المركز", "positions", "profit", "الربح", "الخسارة"]):
            return "positions"
        # Default: price/tick query
        return "price"

    def classify(self, text: str) -> str:
        route = route_text(text)
        t = route.normalized

        # control MUST come before DEVICE_CONTROL — full phrases "شغل الداشبورد"/"وقف الاوتوبايلوت"
        # would otherwise be grabbed by the bare "داشبورد" device trigger (D-02).
        if any(x in t for x in [
            "وقف الاوتوبايلوت", "stop autopilot",
            "شغل الداشبورد", "launch dashboard",
            "ارسل مهمة", "send task",
        ]):
            return "control"

        # mt5_query MUST come before DEVICE_CONTROL and MARKET_ANALYSIS — price/positions/balance
        # keywords moved here (D-02). "صفقات"/"مراكز"/"سعر"/"رصيد" no longer fall into MARKET_ANALYSIS.
        if any(x in t for x in [
            "سعر", "بكم", "gold price", "bid", "ask", "بيد", "اسك",
            "صفقات", "مراكز", "المركز", "positions", "profit", "الربح", "الخسارة",
            "رصيد", "الرصيد", "balance", "equity", "بلانس", "ايكويتي", "رأس المال",
        ]):
            return "mt5_query"

        # agent_query: dispatch jobs and patches (D-02)
        if any(x in t for x in [
            "مهام", "jobs", "باتشات", "patches", "وكلاء", "agents",
            "آخر مهمة", "last job",
        ]):
            return "agent_query"

        if any(x in t for x in self._DEVICE_TRIGGERS):
            return "DEVICE_CONTROL"

        if any(x in t for x in [
            "status", "state", "health", "الحالة", "الوضع", "شغال", "الستاك",
            "كيف الستاك", "الخدمات", "الخدمه", "هل الخدمات", "فرايدي شغال",
        ]):
            return "STATUS"

        # MARKET_ANALYSIS: general market/analysis queries — price/positions/balance removed (mt5_query)
        if any(x in t for x in [
            "xau", "gold", "market", "analysis", "analyze",
            "حلل", "السوق", "ذهب", "الأمر المعلق",
            "اشرح السوق", "شو السوق", "وش السوق",
        ]):
            return "MARKET_ANALYSIS"

        if any(x in t for x in ["remember", "memory", "ذاكرة", "تذكر", "وش قلت", "ما تذكر", "اللي قلت"]):
            return "MEMORY_QUERY"

        if any(x in t for x in ["file", "folder", "ملف", "مجلد"]):
            return "FILE_COMMAND"

        if any(x in t for x in [
            "restart", "start", "stop", "run",
            "شغل", "وقف", "اعد تشغيل", "أوقف", "ابدأ",
            "اقفل فرايدي", "شغل فرايدي",
        ]):
            return "SYSTEM_COMMAND"

        if any(x in t for x in ["remind", "schedule", "monitor", "ذكرني", "راقب", "تابع"]):
            return "AUTOMATION"

        return "CHAT"

    def route(self, text: str) -> CommandResult:
        text = normalize_user_text(text)
        category = self.classify(text)
        log_event("ROUTER", f"{category}: {text[:120]}")

        if category == "DEVICE_CONTROL":
            return self._handle_device(text)

        if category == "STATUS":
            return CommandResult(
                category=category,
                user_text=text,
                tool_name="mt5.system_status",
                tool_context={
                    "system_status": self.mt5_tools.system_status(),
                    "qader_state": self.mt5_tools.get_qader_state(),
                },
            )

        if category == "MARKET_ANALYSIS":
            snapshot = self.mt5_tools.market_snapshot()
            qader = self.mt5_tools.get_qader_state()
            self.memory.remember_analysis({"symbol": snapshot.get("symbol"), "snapshot": snapshot})
            return CommandResult(
                category=category,
                user_text=text,
                tool_name="mt5.market_snapshot",
                tool_context={"market_snapshot": snapshot, "qader_state": qader},
            )

        if category == "MEMORY_QUERY":
            hits = self.memory.search(text)
            return CommandResult(
                category=category,
                user_text=text,
                tool_name="memory.search",
                tool_context={"memory_hits": hits},
            )

        if category == "SYSTEM_COMMAND":
            return CommandResult(
                category=category,
                user_text=text,
                tool_name=None,
                tool_context={"available_tools": sorted(self.tools)},
                direct_response=None,
            )

        if category == "FILE_COMMAND":
            return CommandResult(
                category=category,
                user_text=text,
                tool_context={"note": "File operations are routed for explanation only in voice mode."},
            )

        if category == "AUTOMATION":
            return CommandResult(
                category=category,
                user_text=text,
                tool_context={"note": "Voice automation intent detected. Create automations from Codex chat, not from always-listening mode."},
            )

        if category == "mt5_query":
            sub = self._detect_mt5_sub(text)
            if sub == "price":
                data = self.mt5_tools.tick()
                if not data.get("ok", True):
                    return CommandResult(
                        category=category, user_text=text,
                        direct_response="MT5 مش متصل",
                    )
                return CommandResult(
                    category=category, user_text=text,
                    tool_context={"mt5": data},
                )
            elif sub == "positions":
                positions = self.mt5_tools.positions()
                account = self.mt5_tools.account_snapshot()
                if not account.get("ok", True):
                    return CommandResult(
                        category=category, user_text=text,
                        direct_response="MT5 مش متصل",
                    )
                return CommandResult(
                    category=category, user_text=text,
                    tool_context={"mt5": {"positions": positions, "account": account}},
                )
            else:  # balance
                data = self.mt5_tools.account_snapshot()
                if not data.get("ok", True):
                    return CommandResult(
                        category=category, user_text=text,
                        direct_response="MT5 مش متصل",
                    )
                return CommandResult(
                    category=category, user_text=text,
                    tool_context={"mt5": data},
                )

        if category == "agent_query":
            jobs = self.gateway.get_jobs(limit=3)
            patches = self.gateway.get_patches(status="pending", limit=10)
            if jobs.get("error") == "gateway_unreachable":
                return CommandResult(
                    category=category, user_text=text,
                    direct_response="ما قدرت أوصل للبوابة",
                )
            return CommandResult(
                category=category, user_text=text,
                tool_context={"jobs": jobs, "patches": patches},
            )

        if category == "control":
            t_lower = text.strip().lower()

            # "ارسل مهمة" — send agent task (D-06)
            for trigger in ["ارسل مهمة", "send task"]:
                if trigger in t_lower:
                    task_text = t_lower.split(trigger, 1)[-1].strip()
                    if not task_text:
                        return CommandResult(
                            category=category, user_text=text,
                            direct_response="قل لي وش المهمة",
                        )
                    result = self.gateway.dispatch_task(task_text)
                    if result.get("error") == "gateway_unreachable":
                        return CommandResult(
                            category=category, user_text=text,
                            direct_response="ما قدرت أوصل للبوابة",
                        )
                    return CommandResult(
                        category=category, user_text=text,
                        direct_response="تم ارسال المهمة",
                    )

            # "وقف الاوتوبايلوت" / "stop autopilot" — write mode=stop to state file (D-05)
            if any(x in t_lower for x in ["وقف الاوتوبايلوت", "stop autopilot"]):
                result = self.gateway.control_autopilot("stop")
                if not result.get("ok"):
                    return CommandResult(
                        category=category, user_text=text,
                        direct_response="ما قدرت أوقف الاوتوبايلوت",
                    )
                return CommandResult(
                    category=category, user_text=text,
                    direct_response="تم إيقاف الاوتوبايلوت",
                )

            # "شغل الداشبورد" / "launch dashboard" — launch if not running (D-05)
            if any(x in t_lower for x in ["شغل الداشبورد", "launch dashboard"]):
                result = self.gateway.launch_dashboard()
                if result.get("status") == "already_running":
                    return CommandResult(
                        category=category, user_text=text,
                        direct_response="الداشبورد شغال بالفعل",
                    )
                if not result.get("ok"):
                    return CommandResult(
                        category=category, user_text=text,
                        direct_response="ما قدرت أشغل الداشبورد",
                    )
                return CommandResult(
                    category=category, user_text=text,
                    direct_response="تم تشغيل الداشبورد",
                )

            # Fallback control
            return CommandResult(category=category, user_text=text)

        return CommandResult(category="CHAT", user_text=text)

    # ── Device control dispatch ───────────────────────────────────────────────

    def _handle_device(self, text: str) -> CommandResult:
        t = text.strip().lower()

        if any(x in t for x in ["سكرين شوت", "صورة الشاشة", "screenshot", "التقط الشاشة", "التقط"]):
            # Multi-monitor or single
            if any(x in t for x in ["كل الشاشات", "جميع الشاشات", "الشاشتين", "all screens", "all monitors"]):
                result = self.device.screenshot_all_monitors()
                count = result.get("count", 0)
                msg = f"تم التقاط {count} شاشة" if result.get("ok") else "ما قدرت التقط الشاشات"
            else:
                result = self.device.screenshot()
                msg = "تم التقاط صورة الشاشة" if result.get("ok") else "ما قدرت التقط الشاشة"
            return CommandResult(category="DEVICE_CONTROL", user_text=text, direct_response=msg)

        if any(x in t for x in ["معلومات الجهاز", "حالة الجهاز", "كم رام", "cpu", "ذاكرة الجهاز"]):
            return self._handle_sysinfo(text)

        if any(x in t for x in ["صوت", "الصوت", "volume"]):
            return self._handle_volume(text, t)

        if "فرايدي" in t:
            return self._handle_friday(text, t)

        app_key = self.device.resolve_app_name(text)
        if app_key:
            result = self.device.open_app(app_key)
            if result.get("ok"):
                msg = f"تم فتح {app_key}"
            else:
                msg = f"ما قدرت افتح {app_key}"
            return CommandResult(category="DEVICE_CONTROL", user_text=text, direct_response=msg)

        return CommandResult(category="DEVICE_CONTROL", user_text=text)

    def _handle_sysinfo(self, text: str) -> CommandResult:
        info = self.device.system_info()
        if info.get("ok"):
            msg = (
                f"المعالج {info.get('cpu_pct')}%، "
                f"الرام {info.get('ram_used_gb')} من {info.get('ram_total_gb')} جيجا، "
                f"الديسك متبقي {info.get('disk_free_gb')} جيجا"
            )
        else:
            msg = "ما قدرت أجيب معلومات الجهاز"
        return CommandResult(category="DEVICE_CONTROL", user_text=text, direct_response=msg)

    def _handle_volume(self, text: str, t: str) -> CommandResult:
        if any(x in t for x in ["ارفع", "زيد", "اكثر", "كبّر", "كبر"]):
            cur = self.device.get_volume().get("volume", 50)
            new_level = min(100, cur + 20)
            self.device.set_volume(new_level)
            msg = f"تم رفع الصوت إلى {new_level}%"
        elif any(x in t for x in ["خفض", "اخفض", "قلل", "اقل", "صغّر", "صغر"]):
            cur = self.device.get_volume().get("volume", 50)
            new_level = max(0, cur - 20)
            self.device.set_volume(new_level)
            msg = f"تم تخفيض الصوت إلى {new_level}%"
        elif any(x in t for x in ["كم", "إيش", "وش", "شو", "مستوى"]):
            result = self.device.get_volume()
            vol = result.get("volume")
            msg = f"مستوى الصوت الحالي {vol}%" if vol is not None else "ما قدرت أقرأ الصوت"
        else:
            match = re.search(r"(\d+)", text)
            if match:
                level = max(0, min(100, int(match.group(1))))
                self.device.set_volume(level)
                msg = f"تم ضبط الصوت على {level}%"
            else:
                result = self.device.get_volume()
                vol = result.get("volume")
                msg = f"مستوى الصوت {vol}%" if vol is not None else "ما عرفت وش تقصد بالصوت"
        return CommandResult(category="DEVICE_CONTROL", user_text=text, direct_response=msg)

    def _handle_friday(self, text: str, t: str) -> CommandResult:
        if any(x in t for x in ["اعد تشغيل", "ريستارت", "restart"]):
            self.device.friday_restart()
            msg = "تم إعادة تشغيل فرايدي"
        elif any(x in t for x in ["وقف", "اوقف", "إيقاف", "stop", "اقفل"]):
            self.device.friday_stop_all()
            msg = "تم إيقاف جميع خدمات فرايدي"
        elif any(x in t for x in ["شغل", "ابدأ", "شغّل", "start", "تشغيل"]):
            self.device.friday_start()
            msg = "تم تشغيل فرايدي"
        else:
            result = self.device.friday_processes()
            count = result.get("count", 0)
            msg = f"فرايدي يشغّل {count} عملية الآن"
        return CommandResult(category="DEVICE_CONTROL", user_text=text, direct_response=msg)

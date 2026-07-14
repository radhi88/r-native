"""
OrchestratorAdapter — يربط FridayOrchestrator بواجهة LocalMind.

يوفر الأوامر النصية التالية:
  حالة / status          → ملخص النظام والصفقات
  صفقات / positions      → الصفقات المفتوحة الآن
  تعلم / learning        → إحصائيات التعلم
  أوقف / stop            → يضع علامة إيقاف (on_bar يقرأها)
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agents.orchestrator import FridayOrchestrator


class OrchestratorAdapter:
    """غلاف خفيف حول FridayOrchestrator لاستخدامه مع LocalMind."""

    def __init__(self, orchestrator: "FridayOrchestrator"):
        self.orch    = orchestrator
        self._stop   = False

    # ── واجهة LocalMind ──────────────────────────────────────────────────────────

    def status(self) -> dict:
        st = self.orch.status()
        return {
            "symbol":        self.orch.symbol,
            "bars":          st.get("bars_processed", 0),
            "trades_opened": st.get("trades_opened", 0),
            "open_count":    len(st.get("open_positions", {})),
            "open_positions": st.get("open_positions", {}),
            "learning":      st.get("learning", {}),
            "stop_requested": self._stop,
        }

    def positions(self) -> dict:
        return self.orch.monitor.open_positions()

    def learning_summary(self) -> dict:
        return self.orch.learning.summary("smc", self.orch.symbol)

    def request_stop(self) -> str:
        self._stop = True
        return "طلب الإيقاف مُسجَّل — سيتوقف النظام بعد اكتمال الـbar الحالي."

    def should_stop(self) -> bool:
        return self._stop

    def clear_stop(self):
        self._stop = False

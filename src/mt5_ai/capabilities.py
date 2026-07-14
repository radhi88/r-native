import json
import platform
from dataclasses import dataclass
from pathlib import Path

from .config import PROJECT_ROOT
from .neural_memory import NeuralMemory


@dataclass
class CapabilityDecision:
    allowed: bool
    reason: str
    requires_confirmation: bool = False


class CapabilityBroker:
    """Central permission gate for FRIDAY tools.

    The assistant can be broad, but never raw and blind. All tool actions pass
    through this broker and are logged into local memory.
    """

    def __init__(self, memory=None, project_root=None):
        self.memory = memory or NeuralMemory()
        self.project_root = Path(project_root or PROJECT_ROOT).resolve()

    def decide(self, capability, action, payload=None):
        payload = payload or {}
        if capability == "project_files":
            return self._project_file_decision(action, payload)
        if capability == "system":
            return self._system_decision(action, payload)
        if capability == "mt5":
            return self._mt5_decision(action, payload)
        if capability == "memory":
            return CapabilityDecision(True, "local_memory_allowed")
        return CapabilityDecision(False, f"unknown_capability:{capability}")

    def record(self, capability, action, payload, decision):
        self.memory.record_tool_event(
            capability=capability,
            action=action,
            payload=json.dumps(payload or {}, ensure_ascii=True),
            allowed=decision.allowed,
            reason=decision.reason,
        )

    def authorize(self, capability, action, payload=None):
        decision = self.decide(capability, action, payload)
        self.record(capability, action, payload or {}, decision)
        return decision

    def _project_file_decision(self, action, payload):
        path = payload.get("path")
        if action in {"read", "list", "search"}:
            if not path:
                return CapabilityDecision(True, "project_file_read_default")
            resolved = Path(path).expanduser().resolve()
            if str(resolved).startswith(str(self.project_root)):
                return CapabilityDecision(True, "project_file_read_allowed")
            return CapabilityDecision(
                False,
                "outside_project_requires_explicit_tool",
                requires_confirmation=True,
            )
        if action in {"write", "move", "delete"}:
            return CapabilityDecision(
                False,
                f"{action}_requires_action_time_confirmation",
                requires_confirmation=True,
            )
        return CapabilityDecision(False, f"unsupported_file_action:{action}")

    def _system_decision(self, action, payload):
        if action in {"hardware_status", "process_status", "environment_status"}:
            return CapabilityDecision(True, "safe_system_read_allowed")
        if action in {"run_command", "install_software", "change_settings"}:
            return CapabilityDecision(
                False,
                f"{action}_requires_action_time_confirmation",
                requires_confirmation=True,
            )
        return CapabilityDecision(False, f"unsupported_system_action:{action}")

    def _mt5_decision(self, action, payload):
        if action in {"read_rates", "analyze", "paper_trade", "demo_trade"}:
            return CapabilityDecision(True, f"{action}_allowed")
        if action == "live_trade":
            return CapabilityDecision(
                False,
                "live_trading_permanently_disabled",
                requires_confirmation=False,
            )
        return CapabilityDecision(False, f"unsupported_mt5_action:{action}")

    def system_snapshot(self):
        decision = self.authorize("system", "environment_status", {})
        return {
            "allowed": decision.allowed,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "project_root": str(self.project_root),
            "live_trading": "permanently_disabled",
        }

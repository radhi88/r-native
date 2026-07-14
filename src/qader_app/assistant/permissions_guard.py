"""Permission checks for every Qader capability."""
from __future__ import annotations

from dataclasses import dataclass

from qader_app.storage.audit_log import log_action
from qader_app.storage.settings_store import LOCKED_PERMISSIONS, PermissionsStore


@dataclass(slots=True)
class PermissionResult:
    allowed: bool
    permission: str
    reason: str


class PermissionsGuard:
    def __init__(self, store: PermissionsStore | None = None):
        self.store = store or PermissionsStore()

    def check(self, permission: str, action: str, module: str = "permissions") -> PermissionResult:
        permissions = self.store.load()
        if permission in LOCKED_PERMISSIONS and permission == "can_place_live_orders":
            lockdown_exit = permissions.get("_real_lockdown_exit_code", 1)
            allowed = (
                bool(permissions.get("can_place_live_orders"))
                and bool(permissions.get("_real_controlled_mode_unlocked"))
                and bool(permissions.get("_real_unlock_phrase_confirmed"))
                and int(1 if lockdown_exit is None else lockdown_exit) == 0
            )
            reason = "allowed" if allowed else LOCKED_PERMISSIONS[permission]
        elif permission in LOCKED_PERMISSIONS:
            reason = LOCKED_PERMISSIONS[permission]
            allowed = False
        else:
            allowed = bool(permissions.get(permission, False))
            reason = "allowed" if allowed else f"Permission `{permission}` is not granted."
        log_action(action, permission, allowed, reason, module, result="allowed" if allowed else "denied")
        return PermissionResult(allowed=allowed, permission=permission, reason=reason)

    def require(self, permission: str, action: str, module: str = "permissions") -> None:
        result = self.check(permission, action, module)
        if not result.allowed:
            raise PermissionError(result.reason)

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Iterable


TRUE_VALUES = {"1", "true", "yes", "on", "full", "allow"}

MARK_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(os.getenv("JARVIS_PROJECT_ROOT", str(MARK_ROOT))).resolve()
PROFILE = (os.getenv("JARVIS_PERMISSION_PROFILE", "guarded") or "guarded").strip().lower()

SECRET_FILE_NAMES = {
    ".env",
    "api_keys.json",
    "credentials.json",
    "secrets.json",
    "service_account.json",
    "token.json",
    "tokens.json",
}

SECRET_NAME_TOKENS = (
    "apikey",
    "api_key",
    "secret",
    "credential",
    "password",
    "private_key",
    "token",
)

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    ".jarvis_backups",
    ".jarvis_agents",
}

BLOCKED_COMMAND_WORDS = {
    "rm",
    "rmdir",
    "del",
    "erase",
    "format",
    "shutdown",
    "restart",
    "reboot",
    "curl",
    "wget",
    "bitsadmin",
    "certutil",
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
}


def _env_enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in TRUE_VALUES


def _existing(paths: Iterable[Path]) -> list[Path]:
    results: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except Exception:
            continue
        if resolved.exists() and resolved not in results:
            results.append(resolved)
    return results


def user_space_roots() -> list[Path]:
    home = Path.home()
    return _existing(
        [
            home / "Desktop",
            home / "Downloads",
            home / "Documents",
            home / "Pictures",
            home / "Music",
            home / "Videos",
        ]
    )


def safe_roots() -> list[Path]:
    base = [MARK_ROOT, PROJECT_ROOT]
    if PROFILE in {"guarded", "developer"}:
        base.extend(user_space_roots())
    elif PROFILE in {"full", "autonomous"}:
        base.extend([Path.home(), *user_space_roots()])
    return _existing(base)


def _blocked_system_roots() -> list[Path]:
    if platform.system() != "Windows":
        return _existing([Path("/bin"), Path("/etc"), Path("/usr"), Path("/var")])
    return _existing(
        [
            Path(os.environ.get("WINDIR", r"C:\Windows")),
            Path(r"C:\Program Files"),
            Path(r"C:\Program Files (x86)"),
            Path.home() / "AppData",
        ]
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _has_skipped_part(path: Path) -> bool:
    return any(part.lower() in SKIP_DIR_NAMES for part in path.parts)


def is_secret_path(path: Path) -> bool:
    name = path.name.lower()
    if name in SECRET_FILE_NAMES:
        return True
    return any(token in name for token in SECRET_NAME_TOKENS)


def is_protected_path(path: Path) -> bool:
    try:
        resolved = path.expanduser().resolve()
    except Exception:
        resolved = path

    if _has_skipped_part(resolved):
        return True
    if is_secret_path(resolved) and not _env_enabled("JARVIS_ALLOW_SECRET_ACCESS"):
        return True
    if not _env_enabled("JARVIS_ALLOW_SYSTEM_ROOTS"):
        if any(_inside(resolved, root) or resolved == root for root in _blocked_system_roots()):
            return True
    return False


def is_path_allowed(path: Path, operation: str = "read") -> tuple[bool, str]:
    try:
        resolved = path.expanduser().resolve()
    except Exception as exc:
        return False, f"path_resolve_failed:{exc}"

    if is_protected_path(resolved):
        return False, "protected_or_secret_path"

    roots = safe_roots()
    if not roots:
        return False, "no_safe_roots_configured"

    if not any(_inside(resolved, root) or resolved == root for root in roots):
        return False, "outside_safe_roots"

    op = (operation or "read").lower()
    if op in {"delete", "move", "rename", "destructive"} and not _env_enabled("JARVIS_ALLOW_DESTRUCTIVE"):
        return False, "destructive_operations_disabled"

    return True, "ok"


def is_command_allowed(command: list[str]) -> tuple[bool, str]:
    if not command:
        return False, "empty_command"
    joined = " ".join(str(x) for x in command).lower()
    executable_names: list[str] = []
    for part in command:
        raw = str(part).strip().strip('"').strip("'")
        if not raw:
            continue
        lowered = raw.lower()
        executable_names.append(lowered)
        try:
            executable_names.append(Path(raw).name.lower())
        except Exception:
            pass
    for name in executable_names:
        if name in BLOCKED_COMMAND_WORDS:
            return False, f"blocked_command:{name}"
    for word in BLOCKED_COMMAND_WORDS:
        if f" {word} " in f" {joined} ":
            return False, f"blocked_command:{word}"
    return True, "ok"


def build_runtime_snapshot() -> dict:
    roots = safe_roots()
    return {
        "profile": PROFILE,
        "project_root": str(PROJECT_ROOT),
        "mark_root": str(MARK_ROOT),
        "safe_roots": [str(path) for path in roots],
        "destructive_allowed": _env_enabled("JARVIS_ALLOW_DESTRUCTIVE"),
        "secret_access_allowed": _env_enabled("JARVIS_ALLOW_SECRET_ACCESS"),
        "system_roots_allowed": _env_enabled("JARVIS_ALLOW_SYSTEM_ROOTS"),
        "capabilities": {
            "local_ollama_brain": True,
            "project_agents": _env_enabled("JARVIS_PROJECT_AGENT_ENABLED", True),
            "file_read_write": True,
            "computer_control": True,
            "browser_control": True,
            "friday_tools": True,
            "vision": True,
            "memory": True,
        },
        "guards": {
            "safe_roots_enforced": PROFILE not in {"off", "unsafe"},
            "secret_files_blocked": not _env_enabled("JARVIS_ALLOW_SECRET_ACCESS"),
            "system_roots_blocked": not _env_enabled("JARVIS_ALLOW_SYSTEM_ROOTS"),
            "destructive_ops_blocked": not _env_enabled("JARVIS_ALLOW_DESTRUCTIVE"),
            "blocked_command_words": sorted(BLOCKED_COMMAND_WORDS),
        },
    }


def format_runtime_snapshot(detail: bool = False) -> str:
    snap = build_runtime_snapshot()
    caps = snap["capabilities"]
    guards = snap["guards"]
    enabled = [name for name, ok in caps.items() if ok]
    lines = [
        "حالة قدرات JARVIS:",
        f"- Permission profile: {snap['profile']}",
        f"- Project root: {snap['project_root']}",
        f"- Active capabilities: {', '.join(enabled)}",
        (
            "- Safety: "
            f"secrets_blocked={guards['secret_files_blocked']}, "
            f"system_roots_blocked={guards['system_roots_blocked']}, "
            f"destructive_ops_blocked={guards['destructive_ops_blocked']}"
        ),
    ]
    if detail:
        lines.append("- Safe roots:")
        lines.extend(f"  * {root}" for root in snap["safe_roots"])
        lines.append("- Blocked command words:")
        lines.append("  * " + ", ".join(guards["blocked_command_words"]))
    return "\n".join(lines)

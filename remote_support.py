"""remote_support.py — FRIDAY-branded Support Session bridge.

When the user clicks 🆘 Request Support, this module:
  1. Lazily installs the remote-control engine (one UAC prompt, first run only)
  2. Generates a fresh 8-digit access code each session
  3. Surfaces a Support ID + Access Code in OUR own dialog
  4. Logs every session to data/r_native/support_sessions.jsonl

The user never sees the underlying transport (RustDesk). All labels say
"FRIDAY Support" / "Support ID" / "Access Code" — the executable runs hidden
in the system tray, no popups, no third-party branding visible.

Public API:
  ensure_installed()                      → bool        (idempotent service install)
  get_support_id()                        → str|None
  rotate_access_code()                    → str|None    (fresh random 6-8 digit code)
  start_session(parent_widget=None)       → bool        (the full UX flow)
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

PROJECT_ROOT  = Path(r"C:\Users\Radhi\MT5")
VENDOR_BIN    = PROJECT_ROOT / "vendor" / "rustdesk" / "rustdesk.exe"
SESSION_LOG   = PROJECT_ROOT / "data" / "r_native" / "support_sessions.jsonl"

# Engine resolution — installed copy is preferred (has all DLLs and the
# service hook); the bundled vendor binary is only the bootstrap installer
# and CANNOT serve queries like --get-id on its own (missing plugin dlls).
_INSTALLED_CANDIDATES = [
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "RustDesk" / "rustdesk.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "RustDesk" / "rustdesk.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "RustDesk" / "rustdesk.exe",
]
# Vendor is the seed binary used to run --silent-install once; never queried.
_BOOTSTRAP_BIN = VENDOR_BIN
_ENGINE_CANDIDATES = _INSTALLED_CANDIDATES + [_BOOTSTRAP_BIN]


def _bootstrap_path() -> Optional[Path]:
    """Returns the binary we use to perform the one-time --silent-install."""
    if _BOOTSTRAP_BIN.exists(): return _BOOTSTRAP_BIN
    # Fall back to any installed copy if the bundled one is missing
    for p in _INSTALLED_CANDIDATES:
        if p.exists(): return p
    return None

# Detached process flag on Windows
_DETACHED = 0x00000008
_CREATE_NO_WINDOW = 0x08000000


def _engine_path() -> Optional[Path]:
    for p in _ENGINE_CANDIDATES:
        if p.exists() and p.is_file(): return p
    sys_path = shutil.which("rustdesk")
    return Path(sys_path) if sys_path else None


def _log(action: str, **extra) -> None:
    try:
        SESSION_LOG.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": datetime.now(timezone.utc).isoformat(),
               "action": action, **extra}
        with SESSION_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception: pass


# ───────────────────────────────────────────────────────────────────────
# Engine queries (hidden / no UAC)
# ───────────────────────────────────────────────────────────────────────

def get_support_id() -> Optional[str]:
    """Return the machine's permanent Support ID, or None on failure."""
    exe = _engine_path()
    if not exe: return None
    try:
        r = subprocess.run([str(exe), "--get-id"],
                           capture_output=True, text=True, timeout=5,
                           creationflags=_CREATE_NO_WINDOW)
        out = (r.stdout or "").strip()
        # Strip non-digits (some builds prefix with whitespace/labels)
        return "".join(c for c in out if c.isdigit()) or None
    except Exception:
        return None


def _format_id(raw_id: str) -> str:
    """453410628  →  453 410 628 (3-digit grouping, easier to read aloud)."""
    if not raw_id: return raw_id
    parts = [raw_id[i:i + 3] for i in range(0, len(raw_id), 3)]
    return " ".join(parts)


def _generate_access_code(n_digits: int = 8) -> str:
    """Cryptographically-random N-digit numeric code."""
    return "".join(secrets.choice(string.digits) for _ in range(n_digits))


# ───────────────────────────────────────────────────────────────────────
# Engine install (one-time UAC) + password rotation
# ───────────────────────────────────────────────────────────────────────

def _is_service_installed() -> bool:
    """Service mode = elevated permissions retained = we can call --password
    silently. Detect by checking the service registry entry."""
    try:
        r = subprocess.run(["sc.exe", "query", "RustDesk"],
                           capture_output=True, text=True, timeout=5,
                           creationflags=_CREATE_NO_WINDOW)
        return "RUNNING" in (r.stdout or "") or "STOPPED" in (r.stdout or "")
    except Exception:
        return False


def ensure_installed() -> bool:
    """Idempotent. Installs the engine as a Windows service on first call.
    Triggers ONE UAC prompt — branded as 'FRIDAY Support Engine'. Subsequent
    sessions don't prompt."""
    if _is_service_installed():
        return True
    exe = _bootstrap_path()
    if not exe: return False
    try:
        # ShellExecute "runas" triggers the UAC consent prompt
        import ctypes
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", str(exe), "--silent-install", None, 0)  # 0 = SW_HIDE
        # ShellExecute returns >32 on success
        if ret <= 32:
            _log("install_cancelled", code=int(ret))
            return False
        # Service install is async — poll for up to 8s
        for _ in range(16):
            time.sleep(0.5)
            if _is_service_installed():
                _log("install_complete")
                return True
        return False
    except Exception as e:
        _log("install_error", error=str(e))
        return False


def rotate_access_code() -> Optional[str]:
    """Generate a fresh access code and push it to the engine.
    Requires the engine to be running as service (silent — no UAC)."""
    exe = _engine_path()
    if not exe: return None
    code = _generate_access_code(8)
    try:
        # When service is installed, --password runs without UAC
        subprocess.run([str(exe), "--password", code],
                       capture_output=True, text=True, timeout=8,
                       creationflags=_CREATE_NO_WINDOW)
        _log("access_code_rotated")
        return code
    except Exception as e:
        _log("rotate_error", error=str(e))
        return None


# ───────────────────────────────────────────────────────────────────────
# UX — FRIDAY-branded dialog (no RustDesk references)
# ───────────────────────────────────────────────────────────────────────

def _show_support_dialog(parent_widget, support_id: str,
                          access_code: str) -> bool:
    """Modal dialog showing credentials. Returns True if user kept it open
    (session active), False if cancelled before sharing."""
    try:
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                         QLabel, QPushButton, QFrame,
                                         QApplication)
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QClipboard, QFont
    except Exception:
        # Headless mode — just print
        print(f"\nFRIDAY Support Session\n  Support ID:  {support_id}\n"
              f"  Access Code: {access_code}\n")
        return True

    dlg = QDialog(parent_widget)
    dlg.setWindowTitle("FRIDAY Support Session")
    dlg.setModal(True)
    dlg.setMinimumWidth(540)
    v = QVBoxLayout(dlg); v.setContentsMargins(24, 24, 24, 20); v.setSpacing(14)

    # Header
    title = QLabel("FRIDAY Support Session — Active")
    title.setStyleSheet("font-size: 17px; font-weight: 700; color: #f5a524;")
    v.addWidget(title)

    body = QLabel(
        "Your support session is ready. Share the credentials below with "
        "your FRIDAY support technician — they'll connect to your system "
        "to assist you. You can end the session at any time by clicking "
        "End Session below.")
    body.setWordWrap(True)
    body.setStyleSheet("color: #cccccc; font-size: 12px;")
    v.addWidget(body)

    # Credentials card
    card = QFrame()
    card.setStyleSheet(
        "background:#13131a; border:1px solid #2d2d3a; border-radius:8px; "
        "padding:16px;")
    cv = QVBoxLayout(card); cv.setContentsMargins(16, 14, 16, 14); cv.setSpacing(10)

    mono = QFont("Consolas", 22, QFont.Bold)

    sid_lbl = QLabel("SUPPORT ID")
    sid_lbl.setStyleSheet("color:#888; font-size:11px; letter-spacing:1px;")
    sid_val = QLabel(_format_id(support_id))
    sid_val.setFont(mono)
    sid_val.setStyleSheet("color:#ffffff; padding:4px 0;")
    sid_val.setCursor(Qt.IBeamCursor)
    sid_val.setTextInteractionFlags(Qt.TextSelectableByMouse)
    btn_copy_id = QPushButton("Copy")
    btn_copy_id.setFixedWidth(70)
    btn_copy_id.clicked.connect(
        lambda: QApplication.clipboard().setText(support_id))

    code_lbl = QLabel("ACCESS CODE  (changes each session)")
    code_lbl.setStyleSheet("color:#888; font-size:11px; letter-spacing:1px;")
    code_val = QLabel(access_code)
    code_val.setFont(mono)
    code_val.setStyleSheet("color:#f5a524; padding:4px 0;")
    code_val.setCursor(Qt.IBeamCursor)
    code_val.setTextInteractionFlags(Qt.TextSelectableByMouse)
    btn_copy_code = QPushButton("Copy")
    btn_copy_code.setFixedWidth(70)
    btn_copy_code.clicked.connect(
        lambda: QApplication.clipboard().setText(access_code))

    row1 = QHBoxLayout(); row1.addWidget(sid_val, 1); row1.addWidget(btn_copy_id)
    row2 = QHBoxLayout(); row2.addWidget(code_val, 1); row2.addWidget(btn_copy_code)

    cv.addWidget(sid_lbl); cv.addLayout(row1)
    cv.addSpacing(4)
    cv.addWidget(code_lbl); cv.addLayout(row2)
    v.addWidget(card)

    # Status pill
    status = QLabel("● Awaiting support technician — keep this window open")
    status.setStyleSheet("color:#55aa55; font-size:11px; padding-top:4px;")
    v.addWidget(status)

    # Footer
    foot_row = QHBoxLayout()
    btn_end = QPushButton("End Session")
    btn_end.setStyleSheet(
        "background:#c44e52; color:#ffffff; font-weight:700; "
        "padding:8px 18px; border-radius:4px;")
    foot_row.addStretch()
    foot_row.addWidget(btn_end)
    v.addLayout(foot_row)

    btn_end.clicked.connect(dlg.accept)

    _log("session_dialog_shown", support_id=support_id)
    dlg.exec()
    _log("session_dialog_closed")
    return True


def start_session(parent_widget=None) -> bool:
    """Full support-session flow. Returns True if credentials were shown
    to the user, False on any failure."""
    exe = _engine_path()
    if not exe:
        _show_engine_missing(parent_widget)
        return False

    # 1. Install engine as service if not already (one-time UAC)
    if not ensure_installed():
        _show_install_failed(parent_widget)
        return False

    # 2. Look up the permanent ID
    support_id = get_support_id()
    if not support_id:
        # Engine might still be initializing — wait briefly and retry once
        time.sleep(2)
        support_id = get_support_id()
    if not support_id:
        _show_engine_missing(parent_widget, msg="Engine couldn't generate Support ID")
        return False

    # 3. Rotate access code for this session
    access_code = rotate_access_code()
    if not access_code:
        _show_engine_missing(parent_widget,
                              msg="Engine couldn't set access code")
        return False

    # 4. Show our dialog
    _log("session_started", support_id=support_id)
    return _show_support_dialog(parent_widget, support_id, access_code)


def _show_engine_missing(parent, msg: str = "Support engine isn't available") -> None:
    try:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(parent, "Support Session",
                            f"{msg}.\n\nPlease contact FRIDAY support directly.")
    except Exception:
        print(f"[support] {msg}")


def _show_install_failed(parent) -> None:
    try:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            parent, "Support Session",
            "Remote support needs a one-time permission to install the "
            "session engine. Please approve the system prompt when it "
            "appears, then click 🆘 Request Support again.")
    except Exception:
        print("[support] install consent required — re-click 🆘 after approving UAC")


# ───────────────────────────────────────────────────────────────────────
# Back-compat shims (the older API some callers use)
# ───────────────────────────────────────────────────────────────────────

def is_available() -> bool: return _engine_path() is not None


def installation_path() -> Optional[Path]: return _engine_path()


def read_local_id_password() -> Tuple[Optional[str], Optional[str]]:
    """Legacy alias kept for back-compat with old app.py callers."""
    return get_support_id(), None


def cli_smoke_test() -> None:
    p = _engine_path()
    print(f"engine_path           : {p}")
    print(f"service_installed     : {_is_service_installed()}")
    sid = get_support_id()
    print(f"support_id (live)     : {sid}  (formatted: {_format_id(sid) if sid else '-'})")
    print(f"session_log           : {SESSION_LOG}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="r_native.remote_support")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--start", action="store_true",
                    help="full headless test of the session flow")
    ap.add_argument("--rotate", action="store_true",
                    help="just rotate the access code and print it")
    args = ap.parse_args()

    if args.start:
        ok = start_session(parent_widget=None)
        raise SystemExit(0 if ok else 1)
    if args.rotate:
        code = rotate_access_code()
        print(code or "rotate failed")
        raise SystemExit(0 if code else 1)
    cli_smoke_test()

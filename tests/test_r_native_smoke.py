"""tests/test_r_native_smoke.py — GUI smoke tests for r_native (offscreen Qt).

Real verification, not theater:
  1. ast.parse every .py under r_native/ — catches syntax errors before launch.
  2. Construct the three GUI classes offscreen — catches import errors,
     bad signal wiring, and constructor crashes.
  3. Run SonCockpit.refresh() twice — once hidden (early-exit path) and once
     shown (full path reading the LIVE r_native_v2/data JSON files).

Read-only: never writes to any live data file, never spawns the gateway.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

# ── environment MUST be set before any PySide6 import ────────────────────────
os.environ["QT_QPA_PLATFORM"] = "offscreen"

MT5_ROOT = Path(r"C:\Users\Radhi\MT5")
if str(MT5_ROOT) not in sys.path:
    sys.path.insert(0, str(MT5_ROOT))

import pytest

R_NATIVE = MT5_ROOT / "r_native"


# ──────────────────────────────────────────────────────────────────────────────
# 1. Syntax sweep: every .py in r_native must ast.parse
# ──────────────────────────────────────────────────────────────────────────────
def _all_py_files() -> list[Path]:
    return sorted(p for p in R_NATIVE.rglob("*.py")
                  if "__pycache__" not in p.parts)


def test_r_native_files_exist():
    files = _all_py_files()
    assert len(files) > 10, f"expected many .py files under {R_NATIVE}, got {len(files)}"


def test_ast_parse_all_r_native():
    offenders: list[str] = []
    for f in _all_py_files():
        try:
            ast.parse(f.read_text(encoding="utf-8", errors="replace"), filename=str(f))
        except SyntaxError as e:
            offenders.append(f"{f.name}:{e.lineno}: {e.msg}")
    assert not offenders, "syntax errors in r_native:\n" + "\n".join(offenders)


# ──────────────────────────────────────────────────────────────────────────────
# 2/3. Offscreen construction + real refresh
# ──────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtCore import Qt, QCoreApplication
    from PySide6.QtWidgets import QApplication
    # QtWebEngine (used by RTraderTab) needs this set BEFORE the app exists.
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def test_son_cockpit_constructs(qapp):
    from r_native.son_cockpit import SonCockpit
    w = SonCockpit(parent=None)
    assert w is not None
    w.deleteLater()
    qapp.processEvents()


def test_command_palette_constructs(qapp):
    from r_native.command_palette import CommandPalette
    w = CommandPalette(parent=None, commands=[("x", lambda: None)])
    # the palette pre-populates its list from commands on construction
    assert w.listw.count() == 1
    w.deleteLater()
    qapp.processEvents()


def test_rtrader_tab_constructs(qapp):
    from r_native.rtrader_tab import RTraderTab
    w = RTraderTab(parent=None)
    # health ping is async QNetworkAccessManager — must not have blocked or raised
    assert w.health_lbl is not None
    w.deleteLater()
    qapp.processEvents()


def test_son_cockpit_refresh_hidden_and_shown(qapp):
    """refresh() early-exits while hidden; after show() it must run the FULL
    path against the live r_native_v2/data files without raising."""
    from PySide6.QtTest import QTest
    from r_native.son_cockpit import SonCockpit

    w = SonCockpit(parent=None)
    try:
        # hidden path — isVisible() False → early return, must not raise
        assert not w.isVisible()
        w.refresh()

        # shown path — one real refresh against live data files
        w.show()
        QTest.qWait(50)          # let show/polish events settle
        assert w.isVisible()
        w.refresh()
        QTest.qWait(400)         # singleShot(300, refresh) from ctor also fires
        # after a real refresh the account strip is populated (not the "…" stub)
        assert w.acct_lbl.text() != "…"
    finally:
        w._timer.stop()
        w.close()
        w.deleteLater()
        qapp.processEvents()

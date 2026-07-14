# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import threading
from datetime import datetime


def _log(ui, message: str) -> None:
    try:
        ui.write_log(message)
    except Exception:
        print(message)


def _qt_imports():
    candidates = (
        ("PyQt6.QtWidgets", "PyQt6.QtCore", "PyQt6.QtGui"),
        ("PySide6.QtWidgets", "PySide6.QtCore", "PySide6.QtGui"),
        ("PyQt5.QtWidgets", "PyQt5.QtCore", "PyQt5.QtGui"),
        ("PySide2.QtWidgets", "PySide2.QtCore", "PySide2.QtGui"),
    )

    for widgets_mod, core_mod, gui_mod in candidates:
        try:
            widgets = __import__(widgets_mod, fromlist=["*"])
            core = __import__(core_mod, fromlist=["*"])
            gui = __import__(gui_mod, fromlist=["*"])
            return widgets, core, gui
        except Exception:
            continue

    return None, None, None


def _qt_flag(core, name: str):
    qt = core.Qt

    try:
        return getattr(qt.WindowType, name)
    except Exception:
        pass

    try:
        return getattr(qt, name)
    except Exception:
        return 0


def _safe_callback(ui, callback_name: str) -> None:
    callback = getattr(ui, callback_name, None)

    if not callable(callback):
        _log(ui, f"ERR: callback not ready: {callback_name}")
        return

    try:
        callback()
    except Exception as exc:
        _log(ui, f"ERR: callback failed {callback_name}: {exc}")


def _find_main_window(ui, widgets):
    QWidget = getattr(widgets, "QWidget", None)

    if QWidget is None:
        return None

    for candidate in (getattr(ui, "root", None), ui):
        try:
            if isinstance(candidate, QWidget):
                return candidate
        except Exception:
            pass

    try:
        app = widgets.QApplication.instance()
        if app is not None:
            win = app.activeWindow()
            if win is not None:
                return win

            wins = app.topLevelWidgets()
            if wins:
                return wins[0]
    except Exception:
        pass

    return None


def _position_dock(ui, dock, widgets):
    """
    Stable one-time dock position.
    No auto-follow, no movement loop.
    """
    try:
        app = widgets.QApplication.instance()
        dock_w = dock.width() or 430

        if app is not None and app.primaryScreen() is not None:
            geo = app.primaryScreen().availableGeometry()
            x = geo.x() + geo.width() - dock_w - 35
            y = geo.y() + 90
            dock.move(max(20, x), max(40, y))
            return

        dock.move(930, 90)
    except Exception:
        try:
            dock.move(930, 90)
        except Exception:
            pass


def apply_qader_visual_upgrade(ui) -> None:
    """
    Guaranteed visible Qader control dock.

    Important:
    - Does not touch Gemini Live microphone.
    - Does not touch _listen_live_audio.
    - Does not touch _send_live_text.
    - Adds real clickable buttons in a floating always-on-top dock.
    """
    if getattr(ui, "_qader_visual_upgrade_applied", False):
        return

    setattr(ui, "_qader_visual_upgrade_applied", True)

    widgets, core, _gui = _qt_imports()

    if widgets is None or core is None:
        _log(ui, "ERR: Qader visual dock failed: Qt bindings not found.")
        return

    QApplication = widgets.QApplication
    QWidget = widgets.QWidget
    QLabel = widgets.QLabel
    QPushButton = widgets.QPushButton
    QVBoxLayout = widgets.QVBoxLayout
    QHBoxLayout = widgets.QHBoxLayout
    QFrame = widgets.QFrame

    app = QApplication.instance()

    if app is None:
        _log(ui, "ERR: Qader visual dock failed: QApplication not ready.")
        return

    dock = QWidget()
    dock.setWindowTitle("Qader Screen Control")

    flags = (
        _qt_flag(core, "Tool")
        | _qt_flag(core, "WindowStaysOnTopHint")
    )

    try:
        dock.setWindowFlags(flags)
    except Exception:
        pass

    dock.setFixedSize(430, 500)

    dock.setStyleSheet("""
    QWidget {
        background-color: #02070b;
        color: #b9fbff;
        font-family: Consolas, 'Segoe UI', Arial;
        font-size: 11px;
    }

    QFrame#MainCard {
        background-color: #061621;
        border: 1px solid #00d9ff;
        border-radius: 18px;
    }

    QLabel#Title {
        color: #00eaff;
        font-size: 17px;
        font-weight: 900;
        padding-bottom: 2px;
    }

    QLabel#Subtitle {
        color: #8defff;
        font-size: 11px;
    }

    QLabel#Status {
        color: #00ff99;
        font-size: 12px;
        font-weight: 800;
        border: 1px solid rgba(0, 255, 153, 120);
        border-radius: 10px;
        padding: 8px;
        background-color: #03130d;
    }

    QLabel#Result {
        color: #d5fdff;
        font-size: 11px;
        border: 1px solid rgba(0, 217, 255, 120);
        border-radius: 12px;
        padding: 9px;
        background-color: #02111a;
    }

    QPushButton {
        background-color: #042536;
        color: #d8fdff;
        border: 1px solid #00a6c8;
        border-radius: 11px;
        padding: 10px;
        font-weight: 800;
        min-height: 34px;
    }

    QPushButton:hover {
        background-color: #073d55;
        border: 1px solid #24e6ff;
    }

    QPushButton:pressed {
        background-color: #010d13;
    }

    QPushButton#Primary {
        background-color: #00d9ff;
        color: #001014;
        border: 1px solid #8cf8ff;
    }

    QPushButton#Danger {
        background-color: #341016;
        color: #ffd5d5;
        border: 1px solid #ff6666;
    }

    QPushButton#Gold {
        background-color: #302306;
        color: #ffe7a0;
        border: 1px solid #ffc24d;
    }
    """)

    outer = QVBoxLayout(dock)
    outer.setContentsMargins(10, 10, 10, 10)

    card = QFrame()
    card.setObjectName("MainCard")

    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)

    title = QLabel("QADER CONTROL DOCK")
    title.setObjectName("Title")
    layout.addWidget(title)

    subtitle = QLabel("Gemini Live Mic: unchanged  |  Screen tools: ready")
    subtitle.setObjectName("Subtitle")
    layout.addWidget(subtitle)

    status = QLabel("SCREEN CONTEXT: OFF")
    status.setObjectName("Status")
    ui._qader_dock_status_label = status
    layout.addWidget(status)

    row1 = QHBoxLayout()

    analyze = QPushButton("ANALYZE SCREEN")
    analyze.setObjectName("Primary")

    share = QPushButton("SHARE SCREEN")

    row1.addWidget(analyze)
    row1.addWidget(share)
    layout.addLayout(row1)

    row2 = QHBoxLayout()

    stop = QPushButton("STOP SHARE")
    stop.setObjectName("Danger")

    runtime = QPushButton("RUNTIME")
    runtime.setObjectName("Gold")

    row2.addWidget(stop)
    row2.addWidget(runtime)
    layout.addLayout(row2)

    result = QLabel("Last result: waiting.")
    result.setObjectName("Result")
    result.setWordWrap(True)
    result.setMinimumHeight(90)
    ui._qader_dock_result_label = result
    layout.addWidget(result)

    hint = QLabel("Tip: click Analyze Screen, then ask Qader about what is visible.")
    hint.setObjectName("Subtitle")
    hint.setWordWrap(True)
    layout.addWidget(hint)

    outer.addWidget(card)

    analyze.clicked.connect(lambda: _safe_callback(ui, "on_qader_visual_analyze"))
    share.clicked.connect(lambda: _safe_callback(ui, "on_qader_visual_share"))
    stop.clicked.connect(lambda: _safe_callback(ui, "on_qader_visual_stop"))
    runtime.clicked.connect(lambda: _safe_callback(ui, "on_qader_visual_status"))

    ui._qader_visual_dock = dock

    _position_dock(ui, dock, widgets)

    dock.show()
    dock.raise_()
    # Dock position timer disabled: keep the control dock fixed and stable.


    _log(ui, "SYS: Qader visual upgrade applied.")
    _log(ui, "SYS: Floating Qader Control Dock visible.")
    _log(ui, "SYS: Screen command buttons ready.")


def bind_qader_visual_callbacks(ui, jarvis) -> None:
    """
    Bind floating dock buttons to JARVIS tools.
    This does not modify voice or microphone logic.
    """
    if getattr(ui, "_qader_visual_callbacks_bound", False):
        return

    setattr(ui, "_qader_visual_callbacks_bound", True)

    widgets, core, _gui = _qt_imports()
    ui._qader_visual_share = False

    def set_status(text: str) -> None:
        ui._qader_visual_status = text

        label = getattr(ui, "_qader_dock_status_label", None)
        if label is not None:
            try:
                label.setText(text)
            except Exception:
                pass

    def set_result(text: str) -> None:
        if len(text) > 420:
            text = text[:420] + "..."

        label = getattr(ui, "_qader_dock_result_label", None)
        if label is not None:
            try:
                label.setText(text)
            except Exception:
                pass

    def run_tool(tool_name: str, args: dict, speak: bool = False) -> None:
        async def runner():
            try:
                if not hasattr(jarvis, "_execute_tool"):
                    raise RuntimeError("jarvis._execute_tool is not available")

                result = await jarvis._execute_tool(tool_name, args)

                if isinstance(result, dict):
                    raw = (
                        result.get("result")
                        or result.get("response")
                        or result.get("message")
                        or str(result)
                    )
                else:
                    raw = str(result)

                raw = str(raw or "").strip()

                if not raw:
                    raw = "No result returned."

                stamp = datetime.now().strftime("%H:%M:%S")
                final = f"{stamp} — {raw}"

                set_result(final)
                _log(ui, f"SCREEN_RESULT: {raw[:1500]}")

                if speak:
                    try:
                        jarvis.speak(raw[:260])
                    except Exception:
                        pass

            except Exception as exc:
                msg = f"Screen failed: {exc}"
                set_result(msg)
                _log(ui, f"ERR: {msg}")

        loop = getattr(jarvis, "_loop", None)

        try:
            running = loop is not None and loop.is_running()
        except Exception:
            running = False

        if running:
            asyncio.run_coroutine_threadsafe(runner(), loop)
        else:
            threading.Thread(target=lambda: asyncio.run(runner()), daemon=True).start()

    def analyze_once():
        set_status("SCREEN CONTEXT: ANALYZING")
        set_result("Analyzing current screen...")
        _log(ui, "SYS: Analyze Screen clicked.")

        run_tool(
            "screen_process",
            {
                "angle": "screen",
                "text": (
                    "Analyze the current desktop screen. Describe visible windows, errors, "
                    "important UI state, and the next useful action. Keep it concise."
                ),
            },
            speak=False,
        )

    def share_tick():
        if not bool(getattr(ui, "_qader_visual_share", False)):
            return

        run_tool(
            "screen_process",
            {
                "angle": "screen",
                "text": (
                    "Refresh current screen context. Mention only important changes, "
                    "errors, confirmations, or next action."
                ),
            },
            speak=False,
        )

    def share_on():
        ui._qader_visual_share = True
        set_status("SCREEN CONTEXT: LIVE / 5S")
        set_result("Screen sharing enabled.")
        _log(ui, "SYS: Screen sharing enabled.")

        if core is not None:
            try:
                timer = getattr(ui, "_qader_visual_share_timer", None)

                if timer is None:
                    dock = getattr(ui, "_qader_visual_dock", None)
                    timer = core.QTimer(dock)
                    timer.setInterval(5000)
                    timer.timeout.connect(share_tick)
                    ui._qader_visual_share_timer = timer

                timer.start()
            except Exception as exc:
                _log(ui, f"ERR: share timer failed: {exc}")

        analyze_once()

    def share_stop():
        ui._qader_visual_share = False
        set_status("SCREEN CONTEXT: OFF")
        set_result("Screen sharing stopped.")
        _log(ui, "SYS: Screen sharing stopped.")

        timer = getattr(ui, "_qader_visual_share_timer", None)

        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass

    def runtime_status():
        set_status("RUNTIME STATUS REQUESTED")
        set_result("Checking runtime status...")
        _log(ui, "SYS: Runtime Status clicked.")

        run_tool(
            "runtime_status",
            {"detail": True},
            speak=False,
        )

    ui.on_qader_visual_analyze = analyze_once
    ui.on_qader_visual_share = share_on
    ui.on_qader_visual_stop = share_stop
    ui.on_qader_visual_status = runtime_status

    _log(ui, "SYS: Qader visual callbacks bound.")
    _log(ui, "SYS: Gemini Live microphone logic unchanged.")


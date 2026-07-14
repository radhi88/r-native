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
        ("PyQt6", "PyQt6.QtWidgets", "PyQt6.QtCore", "PyQt6.QtGui"),
        ("PySide6", "PySide6.QtWidgets", "PySide6.QtCore", "PySide6.QtGui"),
        ("PyQt5", "PyQt5.QtWidgets", "PyQt5.QtCore", "PyQt5.QtGui"),
        ("PySide2", "PySide2.QtWidgets", "PySide2.QtCore", "PySide2.QtGui"),
    )

    for _name, widgets_mod, core_mod, gui_mod in candidates:
        try:
            widgets = __import__(widgets_mod, fromlist=["*"])
            core = __import__(core_mod, fromlist=["*"])
            gui = __import__(gui_mod, fromlist=["*"])
            return widgets, core, gui
        except Exception:
            continue

    return None, None, None


def _parent_widget(ui, widgets):
    QWidget = getattr(widgets, "QWidget", None)

    if QWidget is None:
        return None

    try:
        if isinstance(ui, QWidget):
            return ui
    except Exception:
        pass

    try:
        root = getattr(ui, "root", None)
        if isinstance(root, QWidget):
            return root
    except Exception:
        pass

    return None


def _set_label(ui, attr: str, text: str) -> None:
    label = getattr(ui, attr, None)
    if label is None:
        return

    try:
        label.setText(text)
    except Exception:
        pass


def _safe_callback(ui, name: str) -> None:
    cb = getattr(ui, name, None)

    if not callable(cb):
        _log(ui, f"ERR: UI callback not ready: {name}")
        return

    try:
        cb()
    except Exception as exc:
        _log(ui, f"ERR: UI callback failed {name}: {exc}")


def apply_qader_ui_upgrade(ui) -> None:
    """
    Add an upgraded right-side command panel.
    This function is UI-only. It does not touch voice, mic, Gemini Live, or Ollama routing.
    """
    if getattr(ui, "_qader_ui_upgrade_applied", False):
        return

    setattr(ui, "_qader_ui_upgrade_applied", True)

    widgets, core, _gui = _qt_imports()

    if widgets is None or core is None:
        _log(ui, "SYS: UI upgrade skipped: Qt binding not found.")
        return

    parent = _parent_widget(ui, widgets)

    try:
        if hasattr(ui, "setWindowTitle"):
            ui.setWindowTitle("Qader — AI Command Center")
        elif hasattr(ui, "root") and hasattr(ui.root, "setWindowTitle"):
            ui.root.setWindowTitle("Qader — AI Command Center")
    except Exception:
        pass

    stylesheet = """
    QWidget {
        background-color: #02070b;
        color: #8ff7ff;
        font-family: Consolas, 'Segoe UI', Arial;
    }

    QFrame#QaderControlPanel {
        background-color: rgba(2, 18, 28, 235);
        border: 1px solid #00d9ff;
        border-radius: 16px;
    }

    QLabel#PanelTitle {
        color: #00eaff;
        font-size: 15px;
        font-weight: 800;
        letter-spacing: 1px;
    }

    QLabel#PanelSubtle {
        color: #8defff;
        font-size: 11px;
    }

    QLabel#PanelResult {
        color: #b7fbff;
        font-size: 11px;
        padding: 7px;
        border: 1px solid rgba(0, 217, 255, 90);
        border-radius: 10px;
        background-color: rgba(0, 16, 24, 170);
    }

    QPushButton {
        background-color: #042536;
        color: #c9fbff;
        border: 1px solid #00a6c8;
        border-radius: 10px;
        padding: 8px 10px;
        font-weight: 700;
    }

    QPushButton:hover {
        background-color: #073d55;
        border: 1px solid #24e6ff;
    }

    QPushButton:pressed {
        background-color: #02141f;
    }

    QPushButton#PrimaryButton {
        color: #001014;
        background-color: #00d9ff;
        border: 1px solid #7ef8ff;
    }

    QPushButton#DangerButton {
        color: #ffd1d1;
        border: 1px solid #ff6b6b;
        background-color: #321116;
    }
    """

    try:
        target = parent or getattr(ui, "root", None) or ui
        if hasattr(target, "setStyleSheet"):
            old = target.styleSheet() if hasattr(target, "styleSheet") else ""
            if "QaderControlPanel" not in old:
                target.setStyleSheet(old + "\n" + stylesheet)
    except Exception as exc:
        _log(ui, f"ERR: stylesheet upgrade skipped: {exc}")

    if parent is None:
        _log(ui, "SYS: UI upgraded without floating panel: parent widget not detected.")
        return

    QFrame = widgets.QFrame
    QLabel = widgets.QLabel
    QPushButton = widgets.QPushButton
    QVBoxLayout = widgets.QVBoxLayout
    QHBoxLayout = widgets.QHBoxLayout

    panel = QFrame(parent)
    panel.setObjectName("QaderControlPanel")
    panel.setMinimumWidth(315)
    panel.setMaximumWidth(370)

    layout = QVBoxLayout(panel)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(9)

    title = QLabel("QADER CONTROL CENTER")
    title.setObjectName("PanelTitle")
    layout.addWidget(title)

    subtitle = QLabel("Voice: Gemini Live  |  Actions: Local Tools")
    subtitle.setObjectName("PanelSubtle")
    layout.addWidget(subtitle)

    screen_status = QLabel("SCREEN CONTEXT: OFF")
    screen_status.setObjectName("PanelSubtle")
    ui._qader_screen_status_label = screen_status
    layout.addWidget(screen_status)

    model_status = QLabel("Vision: LLaVA / screen_process")
    model_status.setObjectName("PanelSubtle")
    layout.addWidget(model_status)

    row1 = QHBoxLayout()

    analyze_btn = QPushButton("Analyze Screen")
    analyze_btn.setObjectName("PrimaryButton")

    share_btn = QPushButton("Share Screen")

    row1.addWidget(analyze_btn)
    row1.addWidget(share_btn)
    layout.addLayout(row1)

    row2 = QHBoxLayout()

    stop_btn = QPushButton("Stop Sharing")
    stop_btn.setObjectName("DangerButton")

    status_btn = QPushButton("Runtime Status")

    row2.addWidget(stop_btn)
    row2.addWidget(status_btn)
    layout.addLayout(row2)

    result = QLabel("Last screen analysis: waiting.")
    result.setObjectName("PanelResult")
    result.setWordWrap(True)
    ui._qader_screen_result_label = result
    layout.addWidget(result)

    layout.addStretch(1)

    def position_panel():
        try:
            width = parent.width()
            height = parent.height()

            panel_width = min(360, max(315, int(width * 0.25)))
            panel_height = 270

            x = max(12, width - panel_width - 18)
            y = max(80, int(height * 0.14))

            panel.setGeometry(x, y, panel_width, panel_height)
            panel.raise_()
            panel.show()
        except Exception:
            pass

    analyze_btn.clicked.connect(lambda: _safe_callback(ui, "on_screen_analyze"))
    share_btn.clicked.connect(lambda: _safe_callback(ui, "on_screen_share_toggle"))
    stop_btn.clicked.connect(lambda: _safe_callback(ui, "on_screen_share_stop"))
    status_btn.clicked.connect(lambda: _safe_callback(ui, "on_runtime_status_request"))

    try:
        timer = core.QTimer(parent)
        timer.setInterval(5000)
        timer.timeout.connect(lambda: _safe_callback(ui, "on_screen_share_tick"))
        ui._qader_screen_timer = timer
    except Exception:
        ui._qader_screen_timer = None

    try:
        position_timer = core.QTimer(parent)
        position_timer.setInterval(1000)
        position_timer.timeout.connect(position_panel)
        position_timer.start()
        ui._qader_panel_position_timer = position_timer
    except Exception:
        pass

    position_panel()

    _log(ui, "SYS: UI upgraded.")
    _log(ui, "SYS: Screen controls ready.")


def bind_qader_callbacks(ui, jarvis) -> None:
    """
    Bind screen buttons to existing JARVIS tool execution.
    This does not modify Gemini Live microphone logic.
    """
    if getattr(ui, "_qader_callbacks_bound", False):
        return

    setattr(ui, "_qader_callbacks_bound", True)

    ui._qader_screen_share_enabled = False
    ui._qader_screen_interval_seconds = 5
    ui._qader_screen_last_at = None

    def update_status(text: str) -> None:
        _set_label(ui, "_qader_screen_status_label", text)

    def update_result(text: str) -> None:
        if len(text) > 320:
            text = text[:320] + "..."
        _set_label(ui, "_qader_screen_result_label", text)

    def run_tool_async(tool_name: str, args: dict, speak: bool = False) -> None:
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

                timestamp = datetime.now().strftime("%H:%M:%S")
                ui._qader_screen_last_at = timestamp

                update_result(f"{timestamp} — {raw}")
                _log(ui, f"SCREEN_RESULT: {raw[:1200]}")

                if speak:
                    try:
                        jarvis.speak(raw[:260])
                    except Exception:
                        pass

            except Exception as exc:
                update_result(f"Screen analysis failed: {exc}")
                _log(ui, f"ERR: Screen analysis failed: {exc}")

        loop = getattr(jarvis, "_loop", None)

        try:
            is_running = loop is not None and loop.is_running()
        except Exception:
            is_running = False

        if is_running:
            asyncio.run_coroutine_threadsafe(runner(), loop)
        else:
            threading.Thread(target=lambda: asyncio.run(runner()), daemon=True).start()

    def on_screen_analyze():
        _log(ui, "SYS: Analyze Screen requested from UI.")
        update_status("SCREEN CONTEXT: ON-DEMAND")

        run_tool_async(
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

    def on_screen_share_toggle():
        current = bool(getattr(ui, "_qader_screen_share_enabled", False))
        ui._qader_screen_share_enabled = not current

        if ui._qader_screen_share_enabled:
            _log(ui, "SYS: Screen context sharing enabled.")
            update_status("SCREEN CONTEXT: ON — interval 5s")

            timer = getattr(ui, "_qader_screen_timer", None)

            if timer is not None:
                try:
                    timer.start(int(getattr(ui, "_qader_screen_interval_seconds", 5)) * 1000)
                except Exception:
                    pass

            on_screen_analyze()
        else:
            on_screen_share_stop()

    def on_screen_share_stop():
        ui._qader_screen_share_enabled = False

        timer = getattr(ui, "_qader_screen_timer", None)

        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass

        update_status("SCREEN CONTEXT: OFF")
        _log(ui, "SYS: Screen context sharing stopped.")

    def on_screen_share_tick():
        if not bool(getattr(ui, "_qader_screen_share_enabled", False)):
            return

        run_tool_async(
            "screen_process",
            {
                "angle": "screen",
                "text": (
                    "Refresh current screen context. Summarize only important changes, "
                    "errors, confirmations, or next action."
                ),
            },
            speak=False,
        )

    def on_runtime_status_request():
        _log(ui, "SYS: Runtime status requested from UI.")

        run_tool_async(
            "runtime_status",
            {"detail": True},
            speak=False,
        )

    ui.on_screen_analyze = on_screen_analyze
    ui.on_screen_share_toggle = on_screen_share_toggle
    ui.on_screen_share_stop = on_screen_share_stop
    ui.on_screen_share_tick = on_screen_share_tick
    ui.on_runtime_status_request = on_runtime_status_request

    _log(ui, "SYS: Screen callbacks bound.")
    _log(ui, "SYS: Gemini Live microphone logic unchanged.")

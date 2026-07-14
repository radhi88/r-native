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


def _selected_source_id(ui) -> str:
    combo = getattr(ui, "_qader_source_combo", None)

    if combo is None:
        return "desktop:all"

    try:
        value = combo.currentData()
        if value:
            return str(value)
    except Exception:
        pass

    try:
        text = combo.currentText()
        mapping = getattr(ui, "_qader_source_map", {})
        return str(mapping.get(text, "desktop:all"))
    except Exception:
        return "desktop:all"


def _populate_sources(ui) -> None:
    combo = getattr(ui, "_qader_source_combo", None)

    if combo is None:
        return

    try:
        from qader_screen_share_controller import sources_as_tuples

        items = sources_as_tuples()

        combo.blockSignals(True)
        combo.clear()

        ui._qader_source_map = {}

        if not items:
            combo.addItem("No sources found", "desktop:all")
            ui._qader_source_map["No sources found"] = "desktop:all"
        else:
            for source_id, label in items:
                combo.addItem(label, source_id)
                ui._qader_source_map[label] = source_id

        combo.blockSignals(False)

        _log(ui, f"SYS: Screen sources refreshed: {len(items)}")

    except Exception as exc:
        try:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(f"Source refresh failed: {exc}", "desktop:all")
            combo.blockSignals(False)
        except Exception:
            pass

        _log(ui, f"ERR: Screen source refresh failed: {exc}")


def apply_qader_visual_upgrade(ui) -> None:
    """
    Teams-like screen picker dock.

    This creates a real visible floating dock with:
    - source picker
    - refresh sources
    - analyze selected source
    - share selected source
    - stop share
    - runtime status

    It does NOT change voice or microphone behavior.
    """
    if getattr(ui, "_qader_visual_upgrade_applied", False):
        return

    setattr(ui, "_qader_visual_upgrade_applied", True)

    widgets, core, _gui = _qt_imports()

    if widgets is None or core is None:
        _log(ui, "ERR: Qader screen picker failed: Qt bindings not found.")
        return

    QApplication = widgets.QApplication
    QWidget = widgets.QWidget
    QLabel = widgets.QLabel
    QPushButton = widgets.QPushButton
    QVBoxLayout = widgets.QVBoxLayout
    QHBoxLayout = widgets.QHBoxLayout
    QFrame = widgets.QFrame
    QComboBox = widgets.QComboBox

    app = QApplication.instance()

    if app is None:
        _log(ui, "ERR: Qader screen picker failed: QApplication not ready.")
        return

    dock = QWidget()
    dock.setWindowTitle("Qader — Share Screen")

    flags = _qt_flag(core, "Tool") | _qt_flag(core, "WindowStaysOnTopHint")

    try:
        dock.setWindowFlags(flags)
    except Exception:
        pass

    dock.setFixedSize(520, 520)

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
        font-size: 18px;
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

    QComboBox {
        background-color: #031925;
        color: #e2feff;
        border: 1px solid #00a6c8;
        border-radius: 10px;
        padding: 8px;
        min-height: 34px;
    }

    QComboBox QAbstractItemView {
        background-color: #031925;
        color: #e2feff;
        selection-background-color: #005c74;
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

    title = QLabel("QADER SCREEN SHARE")
    title.setObjectName("Title")
    layout.addWidget(title)

    subtitle = QLabel("Choose what to share like Teams: desktop, monitor, or window.")
    subtitle.setObjectName("Subtitle")
    subtitle.setWordWrap(True)
    layout.addWidget(subtitle)

    status = QLabel("SCREEN CONTEXT: OFF")
    status.setObjectName("Status")
    ui._qader_dock_status_label = status
    layout.addWidget(status)

    source_label = QLabel("Share source")
    source_label.setObjectName("Subtitle")
    layout.addWidget(source_label)

    combo = QComboBox()
    ui._qader_source_combo = combo
    layout.addWidget(combo)

    row_refresh = QHBoxLayout()

    refresh = QPushButton("REFRESH SOURCES")
    refresh.setObjectName("Gold")

    runtime = QPushButton("RUNTIME")
    runtime.setObjectName("Gold")

    row_refresh.addWidget(refresh)
    row_refresh.addWidget(runtime)
    layout.addLayout(row_refresh)

    row1 = QHBoxLayout()

    analyze = QPushButton("ANALYZE SELECTED")
    analyze.setObjectName("Primary")

    share = QPushButton("SHARE SELECTED")

    row1.addWidget(analyze)
    row1.addWidget(share)
    layout.addLayout(row1)

    row2 = QHBoxLayout()

    stop = QPushButton("STOP SHARE")
    stop.setObjectName("Danger")

    hide = QPushButton("HIDE DOCK")

    row2.addWidget(stop)
    row2.addWidget(hide)
    layout.addLayout(row2)

    result = QLabel("Last result: waiting.")
    result.setObjectName("Result")
    result.setWordWrap(True)
    result.setMinimumHeight(125)
    ui._qader_dock_result_label = result
    layout.addWidget(result)

    hint = QLabel("If a window is hidden behind another window, choose its monitor instead.")
    hint.setObjectName("Subtitle")
    hint.setWordWrap(True)
    layout.addWidget(hint)

    outer.addWidget(card)

    analyze.clicked.connect(lambda: _safe_callback(ui, "on_qader_visual_analyze"))
    share.clicked.connect(lambda: _safe_callback(ui, "on_qader_visual_share"))
    stop.clicked.connect(lambda: _safe_callback(ui, "on_qader_visual_stop"))
    runtime.clicked.connect(lambda: _safe_callback(ui, "on_qader_visual_status"))
    refresh.clicked.connect(lambda: _populate_sources(ui))
    hide.clicked.connect(lambda: dock.hide())

    ui._qader_visual_dock = dock

    _populate_sources(ui)

    try:
        screen = app.primaryScreen()

        if screen is not None:
            geo = screen.availableGeometry()
            dock.move(geo.x() + geo.width() - 550, geo.y() + 80)
        else:
            dock.move(840, 80)
    except Exception:
        dock.move(840, 80)

    dock.show()
    dock.raise_()

    _log(ui, "SYS: Qader visual upgrade applied.")
    _log(ui, "SYS: Teams-like screen picker dock visible.")
    _log(ui, "SYS: Screen source selection ready.")


def bind_qader_visual_callbacks(ui, jarvis) -> None:
    """
    Bind picker dock actions.
    This does not modify Gemini Live microphone logic.
    """
    if getattr(ui, "_qader_visual_callbacks_bound", False):
        return

    setattr(ui, "_qader_visual_callbacks_bound", True)

    widgets, core, _gui = _qt_imports()
    ui._qader_visual_share = False

    def set_status(text: str) -> None:
        label = getattr(ui, "_qader_dock_status_label", None)

        if label is not None:
            try:
                label.setText(text)
            except Exception:
                pass

    def set_result(text: str) -> None:
        if len(text) > 680:
            text = text[:680] + "..."

        label = getattr(ui, "_qader_dock_result_label", None)

        if label is not None:
            try:
                label.setText(text)
            except Exception:
                pass

    def run_selected_analysis(prompt: str, *, speak: bool = False) -> None:
        source_id = _selected_source_id(ui)

        async def runner():
            try:
                from qader_screen_share_controller import analyze_source

                result = await asyncio.to_thread(analyze_source, source_id, prompt)

                stamp = datetime.now().strftime("%H:%M:%S")
                final = f"{stamp} — {result}"

                set_result(final)
                _log(ui, f"SCREEN_RESULT: {result[:1800]}")

                if speak:
                    try:
                        jarvis.speak(result[:260])
                    except Exception:
                        pass

            except Exception as exc:
                msg = f"Screen analysis failed: {exc}"
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

    def run_tool(tool_name: str, args: dict) -> None:
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

                stamp = datetime.now().strftime("%H:%M:%S")
                set_result(f"{stamp} — {raw}")
                _log(ui, f"TOOL_RESULT: {raw[:1500]}")

            except Exception as exc:
                msg = f"Tool failed: {exc}"
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
        set_status("SCREEN CONTEXT: ANALYZING SELECTED")
        set_result("Analyzing selected source...")
        _log(ui, f"SYS: Analyze selected source: {_selected_source_id(ui)}")

        run_selected_analysis(
            "Analyze the selected shared screen/window. Describe visible windows, errors, important UI state, and next useful action. Keep it concise.",
            speak=False,
        )

    def share_tick():
        if not bool(getattr(ui, "_qader_visual_share", False)):
            return

        run_selected_analysis(
            "Refresh the selected shared source. Mention only important changes, errors, confirmations, or next action.",
            speak=False,
        )

    def share_on():
        ui._qader_visual_share = True
        selected = _selected_source_id(ui)

        set_status(f"SCREEN CONTEXT: SHARED — {selected}")
        set_result("Screen is shared. Waiting for your instruction.")
        _log(ui, f"SYS: Share selected source enabled without auto-analysis: {selected}")

        # مثل Teams: مجرد تأكيد صوتي بدون تحليل كتابي تلقائي.
        try:
            jarvis.speak("إيه، أنا أشوف الشاشة الآن. وش تبي أسوي فيها؟")
        except Exception as exc:
            _log(ui, f"ERR: share voice acknowledgement failed: {exc}")

        # لا نشغل تحليل تلقائي ولا مؤقت 5 ثواني.
        # التحليل يصير فقط عند الضغط على ANALYZE SELECTED أو عند طلب المستخدم.
        timer = getattr(ui, "_qader_visual_share_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass

    def share_stop():
        ui._qader_visual_share = False
        set_status("SCREEN CONTEXT: OFF")
        set_result("Screen sharing stopped.")
        _log(ui, "SYS: Selected source sharing stopped.")

        timer = getattr(ui, "_qader_visual_share_timer", None)

        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass

        try:
            jarvis.speak("تم إيقاف مشاركة الشاشة.")
        except Exception:
            pass

    def runtime_status():
        set_status("RUNTIME STATUS REQUESTED")
        set_result("Checking runtime status...")
        _log(ui, "SYS: Runtime Status clicked.")

        run_tool(
            "runtime_status",
            {"detail": True},
        )

    ui.on_qader_visual_analyze = analyze_once
    ui.on_qader_visual_share = share_on
    ui.on_qader_visual_stop = share_stop
    ui.on_qader_visual_status = runtime_status

    _log(ui, "SYS: Qader visual callbacks bound.")
    _log(ui, "SYS: Gemini Live microphone logic unchanged.")


"""r_app.py - R Factory Desktop App (minimal working version)."""
import os, sys, time, subprocess, socket
from pathlib import Path

APP_DIR = Path(__file__).parent
PROJECT_ROOT = APP_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


class BackgroundServices:
    def __init__(self):
        self.procs = {}
        self.tmp = Path(os.environ.get("LOCALAPPDATA", "/tmp")) / "R_Factory"
        self.tmp.mkdir(parents=True, exist_ok=True)

    def _port_open(self, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.3)
        try: return s.connect_ex(("127.0.0.1", port)) == 0
        finally: s.close()

    def start(self, live=False, bypass=True):
        env = dict(os.environ)
        if bypass:
            env["R_BYPASS_SESSION"] = "1"
            env["R_BYPASS_WEEKEND"] = "1"
            env["R_BYPASS_FRIDAY"] = "1"
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        if not self._port_open(5055):
            log = open(self.tmp / "brain.log", "ab")
            self.procs["brain"] = subprocess.Popen(
                [sys.executable, "brain_server.py"],
                stdout=log, stderr=log, env=env, creationflags=flags)
            for _ in range(30):
                if self._port_open(5055): break
                time.sleep(0.4)
        log = open(self.tmp / "watcher.log", "ab")
        self.procs["watcher"] = subprocess.Popen(
            [sys.executable, "-u", "-m", "friday_v3.algory.algory_watcher", "--interval", "30"],
            stdout=log, stderr=log, env=env, creationflags=flags)
        cmd = [sys.executable, "-u", "-m", "friday_v3.algory.r_executor",
               "--no-brain-json", "--interval", "8"]
        if live: cmd.append("--live")
        log = open(self.tmp / "exec.log", "ab")
        self.procs["executor"] = subprocess.Popen(
            cmd, stdout=log, stderr=log, env=env, creationflags=flags)

    def stop_all(self):
        for p in list(self.procs.values()):
            try:
                if p.poll() is None: p.terminate()
            except Exception: pass
        time.sleep(1)
        for p in list(self.procs.values()):
            try:
                if p.poll() is None: p.kill()
            except Exception: pass
        self.procs.clear()

    def status(self):
        return {
            "brain": self._port_open(5055),
            "watcher": "watcher" in self.procs and self.procs["watcher"].poll() is None,
            "executor": "executor" in self.procs and self.procs["executor"].poll() is None,
        }


def main():
    from PySide6.QtWidgets import (QApplication, QMainWindow, QSystemTrayIcon, QMenu,
                                   QLabel, QMessageBox, QStyle)
    from PySide6.QtCore import QUrl, Qt, QTimer
    from PySide6.QtGui import QIcon, QAction, QPalette, QColor
    from PySide6.QtWebEngineWidgets import QWebEngineView

    app = QApplication(sys.argv)
    app.setApplicationName("R Factory")
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(6, 4, 24))
    pal.setColor(QPalette.WindowText, QColor(241, 245, 249))
    pal.setColor(QPalette.Base, QColor(13, 8, 36))
    pal.setColor(QPalette.Button, QColor(28, 17, 66))
    pal.setColor(QPalette.ButtonText, QColor(251, 191, 36))
    pal.setColor(QPalette.Highlight, QColor(139, 92, 246))
    pal.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(pal)

    logo = PROJECT_ROOT / "friday_v3" / "algory" / "r_logo.svg"
    icon = QIcon(str(logo)) if logo.exists() else app.style().standardIcon(QStyle.SP_ComputerIcon)
    app.setWindowIcon(icon)

    bg = BackgroundServices()
    bg.start(live=False, bypass=True)

    win = QMainWindow()
    win.setWindowTitle("R FACTORY - Genetic Trading System")
    win.resize(1500, 900)
    win.setWindowIcon(icon)

    toolbar = win.addToolBar("Main")
    toolbar.setMovable(False)
    toolbar.setStyleSheet(
        "QToolBar { background: #0d0824; border: none; padding: 4px; spacing: 8px; }"
        "QToolButton { color: #fbbf24; padding: 6px 14px; font-weight: bold; }"
        "QToolButton:hover { background: #2d1b69; border-radius: 4px; }"
    )

    web = QWebEngineView()

    def add_btn(name, fn):
        a = QAction(name, win); a.triggered.connect(fn); toolbar.addAction(a); return a

    add_btn("R Factory", lambda: web.setUrl(QUrl("http://127.0.0.1:5055/r/")))
    add_btn("Pro View", lambda: web.setUrl(QUrl("http://127.0.0.1:5055/")))
    add_btn("Reload", lambda: web.reload())
    toolbar.addSeparator()

    mode_label = QLabel("  PAPER  ")
    mode_label.setStyleSheet("color: #fbbf24; font-weight: bold; padding: 0 10px;")
    toolbar.addWidget(mode_label)

    def go_live():
        r = QMessageBox.warning(win, "Switch to LIVE",
            "Real orders will be sent.\nmagic 20260605 lot 0.01 daily-cap $10.\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes: return
        bg.stop_all(); time.sleep(1); bg.start(live=True, bypass=True)
        mode_label.setText("  LIVE  ")
        mode_label.setStyleSheet("color: #ef4444; font-weight: bold; padding: 0 10px;")

    def stop_trading():
        if "executor" in bg.procs:
            try: bg.procs["executor"].terminate()
            except Exception: pass
        mode_label.setText("  STOPPED  ")
        mode_label.setStyleSheet("color: #94a3b8; font-weight: bold; padding: 0 10px;")

    add_btn("Go LIVE", go_live)
    add_btn("Stop", stop_trading)
    toolbar.addSeparator()
    add_btn("Logs", lambda: subprocess.Popen(["explorer", str(bg.tmp)]))
    add_btn("Open in Browser",
            lambda: subprocess.Popen(["cmd", "/c", "start", "http://127.0.0.1:5055/r/"], shell=True))

    # Load main UI after small delay (lets brain_server initialize)
    QTimer.singleShot(2000, lambda: web.setUrl(QUrl("http://127.0.0.1:5055/r/")))
    win.setCentralWidget(web)

    # Status bar
    statusbar = win.statusBar()
    status_label = QLabel("Initializing...")
    statusbar.addWidget(status_label)
    statusbar.setStyleSheet("background: #0d0824; color: #94a3b8;")

    def update_status():
        s = bg.status()
        parts = []
        for k, v in s.items():
            ico = "OK" if v else "OFF"
            color = "#10b981" if v else "#ef4444"
            parts.append(f"<span style='color:{color}'>[{ico}] {k}</span>")
        status_label.setText("  ".join(parts) + "  |  R Factory v1.0  |  port 5055")
    update_status()
    status_timer = QTimer(); status_timer.timeout.connect(update_status); status_timer.start(3000)

    # System tray
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("R Factory")
    tray_menu = QMenu()
    show_act = QAction("Show R Factory", app)
    show_act.triggered.connect(lambda: (win.show(), win.raise_(), win.activateWindow()))
    quit_act = QAction("Quit (stop all)", app)
    def real_quit():
        bg.stop_all()
        tray.hide()
        app.quit()
    quit_act.triggered.connect(real_quit)
    tray_menu.addAction(show_act)
    tray_menu.addSeparator()
    tray_menu.addAction(quit_act)
    tray.setContextMenu(tray_menu)
    tray.activated.connect(lambda r: (win.show(), win.raise_()) if r == QSystemTrayIcon.Trigger else None)
    tray.show()

    # Close to tray
    orig_close = win.closeEvent
    def close_to_tray(ev):
        ev.ignore()
        win.hide()
        tray.showMessage("R Factory", "Still running in tray - keeps trading.",
                         QSystemTrayIcon.Information, 2500)
    win.closeEvent = close_to_tray

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

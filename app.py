"""app.py - R Native Desktop — pure PySide6, no webview, no HTML.

Layout (Algory-inspired):
  ┌────────────┬──────────────────────────────────────┬─────────────┐
  │ COMMAND    │  HEADER (campaign + Stats/Score)     │             │
  │ (sidebar)  ├──────────────────────────────────────┤  INSPECTOR  │
  │            │  CAMPAIGN  | VAULT  | LIVE           │  (KPIs +    │
  │ Battery    │  ┌─Symbols─┬─TFs──┬─Params────┐      │   stats +   │
  │ Settings   │  │ Grid    │      │           │      │   curve)    │
  │ Folder     │  └─────────┴──────┴───────────┘      │             │
  │            │  Strategies table                    │             │
  │ SKIP/PAUSE │                                      │             │
  │ RUN        │  ┌─Action─┬─Deploy─┬─Optimize─┐      │             │
  │ REPEAT     │  └────────┴────────┴──────────┘      │             │
  │ QUEUE      ├──────────────────────────────────────┤             │
  │            │ STATUS BAR + LIVE LOG                │             │
  ├────────────┴──────────────────────────────────────┴─────────────┤
  │ Live ticker: balance · equity · open R positions · IQ           │
  └─────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations
import sys
import os
import json
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QGridLayout, QPushButton, QLabel, QFrame, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QCheckBox, QLineEdit, QComboBox,
                               QProgressBar, QPlainTextEdit, QHeaderView, QSizePolicy, QSpacerItem,
                               QGroupBox, QScrollArea, QMessageBox, QStyle, QFileDialog, QSystemTrayIcon, QMenu)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QSize
from PySide6.QtGui import QPalette, QColor, QFont, QIcon, QAction, QPainter, QPen, QBrush


# ─── Theme colors (matching Algory dark) ───
BG_0      = "#060418"
BG_1      = "#0d0824"
BG_2      = "#14092e"
BG_3      = "#1c1142"
GOLD      = "#fbbf24"
GOLD_DIM  = "#b45309"
VIOLET    = "#8b5cf6"
GREEN     = "#10b981"
RED       = "#ef4444"
TEXT      = "#f1f5f9"
MUTED     = "#94a3b8"
BORDER    = "#2d1b69"


def apply_dark_theme(app):
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.Window,         QColor(BG_0))
    p.setColor(QPalette.WindowText,     QColor(TEXT))
    p.setColor(QPalette.Base,           QColor(BG_1))
    p.setColor(QPalette.AlternateBase,  QColor(BG_2))
    p.setColor(QPalette.Text,           QColor(TEXT))
    p.setColor(QPalette.Button,         QColor(BG_3))
    p.setColor(QPalette.ButtonText,     QColor(GOLD))
    p.setColor(QPalette.Highlight,      QColor(VIOLET))
    p.setColor(QPalette.HighlightedText,QColor(TEXT))
    p.setColor(QPalette.ToolTipBase,    QColor(BG_3))
    p.setColor(QPalette.ToolTipText,    QColor(TEXT))
    app.setPalette(p)
    app.setStyleSheet(f"""
        QMainWindow, QWidget {{ background: {BG_0}; color: {TEXT}; }}
        QFrame[role="card"] {{
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {BG_1}, stop:1 {BG_2});
            border: 1px solid {BORDER}; border-radius: 8px;
        }}
        QLabel[role="title"] {{ color: {GOLD}; font-weight: 900; letter-spacing: 2px; }}
        QLabel[role="kpi-label"] {{ color: {VIOLET}; font-size: 10px; letter-spacing: 2px; }}
        QLabel[role="kpi-value"] {{ color: {TEXT}; font-size: 22px; font-weight: 900; font-family: Consolas; }}
        QLabel[role="muted"] {{ color: {MUTED}; font-size: 11px; }}
        QPushButton {{
            background: {BG_3}; color: {GOLD}; border: 1px solid {BORDER};
            padding: 7px 14px; border-radius: 5px; font-weight: bold;
        }}
        QPushButton:hover {{ background: {VIOLET}; color: white; }}
        QPushButton:disabled {{ color: {MUTED}; }}
        QPushButton[role="danger"] {{ color: {RED}; }}
        QPushButton[role="success"] {{ color: {GREEN}; }}
        QPushButton[role="primary"] {{ background: {GOLD}; color: {BG_0}; }}
        QPushButton[role="primary"]:hover {{ background: {GOLD_DIM}; color: white; }}
        QLineEdit, QComboBox {{
            background: {BG_2}; color: {TEXT}; border: 1px solid {BORDER};
            border-radius: 4px; padding: 4px 8px;
        }}
        QTableWidget {{
            background: {BG_1}; color: {TEXT}; gridline-color: {BORDER};
            selection-background-color: {VIOLET};
        }}
        QHeaderView::section {{
            background: {BG_3}; color: {GOLD}; padding: 6px;
            border: none; border-bottom: 1px solid {BORDER}; font-weight: bold;
        }}
        QTabBar::tab {{
            background: {BG_2}; color: {MUTED}; padding: 8px 16px;
            border-top-left-radius: 4px; border-top-right-radius: 4px;
        }}
        QTabBar::tab:selected {{ background: {BG_3}; color: {GOLD}; }}
        QPlainTextEdit {{
            background: {BG_0}; color: {GREEN}; font-family: Consolas;
            border: 1px solid {BORDER}; border-radius: 4px;
        }}
        QCheckBox {{ color: {TEXT}; }}
        QCheckBox::indicator:checked {{ background: {GOLD}; border: 1px solid {GOLD}; }}
        QProgressBar {{
            background: {BG_2}; border: 1px solid {BORDER}; border-radius: 4px;
            text-align: center; color: {GOLD};
        }}
        QProgressBar::chunk {{ background: {VIOLET}; border-radius: 3px; }}
        QSplitter::handle {{ background: {BORDER}; }}
        QScrollBar:vertical, QScrollBar:horizontal {{
            background: {BG_1}; border: none; width: 10px; height: 10px;
        }}
        QScrollBar::handle {{ background: {BORDER}; border-radius: 4px; }}
        QScrollBar::handle:hover {{ background: {VIOLET}; }}
    """)


# ─── Background scan thread ───
class ScanWorker(QThread):
    progress = Signal(str, int, int)   # message, done, total
    finished_with_result = Signal(dict)

    def __init__(self, symbols, n_bars):
        super().__init__()
        self.symbols = symbols
        self.n_bars = n_bars

    def run(self):
        from r_native.scanner import full_scan, update_symbol_configs_from_scan, ARCHETYPES
        total = len(self.symbols) * 4 * len(ARCHETYPES)
        done = [0]
        def cb(msg):
            done[0] += 1
            self.progress.emit(msg, done[0], total)
        summary = full_scan(self.symbols, self.n_bars, progress_cb=cb)
        update_symbol_configs_from_scan(summary)
        self.finished_with_result.emit(summary)


# ─── Main window ───
class RNativeMain(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("R NATIVE - Genetic Trading System")
        self.resize(1600, 950)
        self.setMinimumSize(1200, 700)
        logo = PROJECT_ROOT / "friday_v3" / "algory" / "r_logo.svg"
        if logo.exists():
            self.setWindowIcon(QIcon(str(logo)))

        # Central
        central = QWidget()
        self.setCentralWidget(central)
        main_v = QVBoxLayout(central); main_v.setContentsMargins(8, 8, 8, 8); main_v.setSpacing(6)

        # Header
        main_v.addLayout(self._build_header())

        # 3-column split: Command | Center | Inspector
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_command_sidebar())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_inspector())
        splitter.setSizes([180, 1080, 340])
        main_v.addWidget(splitter, 1)

        # Status ticker (bottom)
        main_v.addWidget(self._build_status_ticker())

        # Tray
        self._setup_tray()

        # Tick timer
        self.tick = QTimer(); self.tick.timeout.connect(self._on_tick); self.tick.start(3000)
        self._on_tick()

    # ─── Header ───
    def _build_header(self):
        h = QHBoxLayout()
        title = QLabel("R   N A T I V E")
        title.setProperty("role", "title")
        f = QFont("Segoe UI", 18, QFont.Black); title.setFont(f)
        title.setStyleSheet(f"color: {GOLD}; letter-spacing: 6px;")
        h.addWidget(title)
        sub = QLabel("Self-Learning Genetic Strategy Factory")
        sub.setStyleSheet(f"color: {MUTED}; font-size: 11px; margin-left: 10px;")
        h.addWidget(sub)
        h.addStretch()

        # Tabs (NEW CAMPAIGN / ADVANCED / GENE POOL)
        for name in ["NEW CAMPAIGN", "ADVANCED", "GENE POOL", "STATS", "SCORE", "CLASS"]:
            b = QPushButton(name)
            b.setStyleSheet(f"background: {BG_2}; color: {RED if name=='NEW CAMPAIGN' else MUTED}; padding: 6px 12px;")
            h.addWidget(b)
        return h

    # ─── Left sidebar ───
    def _build_command_sidebar(self):
        w = QFrame(); w.setProperty("role", "card")
        v = QVBoxLayout(w); v.setContentsMargins(8, 12, 8, 12); v.setSpacing(8)

        # Logo (text fallback)
        logo_lbl = QLabel("R")
        logo_lbl.setAlignment(Qt.AlignCenter)
        logo_lbl.setStyleSheet(f"color: {GOLD}; font-size: 48px; font-weight: 900;")
        v.addWidget(logo_lbl)
        v.addWidget(QLabel(" "))

        # Iconic buttons
        for lbl in ["⚙ Settings", "📁 Vault", "🔋 Connection"]:
            b = QPushButton(lbl); v.addWidget(b)

        v.addWidget(QLabel(" "))

        for lbl, role in [("▶ RUN", "primary"), ("⏸ PAUSE", ""), ("⏹ STOP", "danger"),
                          ("🔁 REPEAT", ""), ("📥 QUEUE", "")]:
            b = QPushButton(lbl)
            if role: b.setProperty("role", role)
            if lbl == "▶ RUN": b.clicked.connect(self._start_scan)
            elif lbl == "⏹ STOP": b.clicked.connect(self._stop_scan)
            v.addWidget(b)

        v.addStretch()

        # Live IQ
        self.iq_label = QLabel("R-IQ: —")
        self.iq_label.setAlignment(Qt.AlignCenter)
        self.iq_label.setStyleSheet(f"color: {VIOLET}; font-weight: bold; padding: 4px;")
        v.addWidget(self.iq_label)
        return w

    # ─── Center ───
    def _build_center(self):
        w = QFrame(); w.setProperty("role", "card")
        v = QVBoxLayout(w); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(8)

        tabs = QTabWidget()
        tabs.addTab(self._build_campaign_tab(), "🧪 CAMPAIGN")
        tabs.addTab(self._build_vault_tab(),    "💎 VAULT")
        tabs.addTab(self._build_live_tab(),     "⚡ LIVE")
        tabs.addTab(self._build_genes_tab(),    "🧬 GENES")
        v.addWidget(tabs, 1)

        # Bottom action bar
        actions = QHBoxLayout()
        for lbl, role in [("DEPLOY", "success"), ("OPTIMIZE", ""), ("RETRAIN", ""),
                          ("DELETE", "danger"), ("PURGE", ""), ("DEDUPE", "")]:
            b = QPushButton(lbl)
            if role: b.setProperty("role", role)
            actions.addWidget(b)
        actions.addStretch()
        v.addLayout(actions)

        # Live log (terminal-style)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(180)
        self.log_view.setPlaceholderText("Scan output, decisions, learning events...")
        v.addWidget(self.log_view)
        return w

    def _build_campaign_tab(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(10, 10, 10, 10); v.setSpacing(10)

        # ASSETS row
        assets_box = QGroupBox("ASSETS"); assets_box.setStyleSheet(f"QGroupBox {{ color: {GOLD}; }}")
        ag = QGridLayout(assets_box)
        self.symbol_checks = {}
        SYMBOLS = ["EURUSDm","GBPUSDm","AUDUSDm","USDJPYm","USDCADm","USDCHFm",
                   "EURGBPm","GBPJPYm","EURJPYm","GBPAUDm","BTCUSDm","XAUUSDm",
                   "XAGUSDm","US30m","USTECm","US500m","DE30m","USOILm"]
        for i, sym in enumerate(SYMBOLS):
            cb = QCheckBox(sym)
            if sym in ("XAUUSDm","BTCUSDm","ETHUSDm"): cb.setChecked(True)
            self.symbol_checks[sym] = cb
            ag.addWidget(cb, i // 6, i % 6)
        v.addWidget(assets_box)

        # TIMEFRAMES + PARAMS row
        hb = QHBoxLayout()
        tf_box = QGroupBox("TIMEFRAMES"); tf_box.setStyleSheet(f"QGroupBox {{ color: {GOLD}; }}")
        tg = QGridLayout(tf_box)
        self.tf_checks = {}
        for i, tf in enumerate(["M5","M15","M30","H1","H4","D1"]):
            c = QCheckBox(tf); c.setChecked(tf in ("M5","H1","H4")); self.tf_checks[tf] = c
            tg.addWidget(c, i//2, i%2)
        hb.addWidget(tf_box, 1)

        params_box = QGroupBox("PARAMETERS"); params_box.setStyleSheet(f"QGroupBox {{ color: {GOLD}; }}")
        pg = QGridLayout(params_box)
        self.param_inputs = {}
        for i, (k, default) in enumerate([("Bars", "4000"), ("Balance", "100"),
                                           ("Risk %", "1.0"), ("Spread mult", "1.0")]):
            pg.addWidget(QLabel(k), i, 0)
            e = QLineEdit(default); self.param_inputs[k] = e
            pg.addWidget(e, i, 1)
        hb.addWidget(params_box, 2)
        v.addLayout(hb)

        # SCAN PROGRESS
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 100)
        v.addWidget(self.scan_progress)
        self.scan_status_lbl = QLabel("Ready. Click ▶ RUN to start full-market scan.")
        self.scan_status_lbl.setStyleSheet(f"color: {MUTED};")
        v.addWidget(self.scan_status_lbl)

        v.addStretch()
        return w

    def _build_vault_tab(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(10, 10, 10, 10)
        self.vault_table = QTableWidget(0, 11)
        self.vault_table.setHorizontalHeaderLabels(
            ["ID", "Symbol", "TF", "Archetype", "Trades", "WR%", "PF", "Return%", "Max DD%", "Sharpe", "Verdict"])
        self.vault_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.vault_table.setAlternatingRowColors(True)
        v.addWidget(self.vault_table)
        return w

    def _build_live_tab(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(10, 10, 10, 10)
        # Open R positions table
        self.live_table = QTableWidget(0, 8)
        self.live_table.setHorizontalHeaderLabels(
            ["Ticket", "Symbol", "Side", "Vol", "Entry", "Current", "SL/TP", "P/L"])
        self.live_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(QLabel("📦 OPEN R POSITIONS (magic 20260605)"))
        v.addWidget(self.live_table, 1)

        # Per-symbol config display
        v.addWidget(QLabel("📋 PER-SYMBOL CONFIGS"))
        self.config_table = QTableWidget(0, 7)
        self.config_table.setHorizontalHeaderLabels(
            ["Symbol", "Tradeable", "Best Archetype", "Best TF", "PF", "Strategies", "Last Scan"])
        self.config_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self.config_table, 1)
        return w

    def _build_genes_tab(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(10, 10, 10, 10); v.setSpacing(10)

        hb = QHBoxLayout()
        # Winning genes
        win_box = QGroupBox("✅ WINNING GENES (Algory OOS-proven)")
        win_box.setStyleSheet(f"QGroupBox {{ color: {GREEN}; }}")
        wb = QVBoxLayout(win_box)
        self.win_genes_list = QPlainTextEdit(); self.win_genes_list.setReadOnly(True)
        self.win_genes_list.setStyleSheet(f"color: {GREEN};")
        wb.addWidget(self.win_genes_list)
        hb.addWidget(win_box)

        # Avoid genes
        bad_box = QGroupBox("❌ AVOIDED GENES (proven losers)")
        bad_box.setStyleSheet(f"QGroupBox {{ color: {RED}; }}")
        bb = QVBoxLayout(bad_box)
        self.bad_genes_list = QPlainTextEdit(); self.bad_genes_list.setReadOnly(True)
        self.bad_genes_list.setStyleSheet(f"color: {RED};")
        bb.addWidget(self.bad_genes_list)
        hb.addWidget(bad_box)
        v.addLayout(hb)

        # Refresh from algory_report
        btn = QPushButton("🔁 Refresh from Algory")
        btn.clicked.connect(self._refresh_genes)
        v.addWidget(btn)
        return w

    # ─── Right inspector ───
    def _build_inspector(self):
        w = QFrame(); w.setProperty("role", "card")
        v = QVBoxLayout(w); v.setContentsMargins(10, 12, 10, 12); v.setSpacing(8)

        title_lbl = QLabel("INSPECTOR")
        title_lbl.setProperty("role", "title")
        title_lbl.setStyleSheet(f"color: {GOLD}; font-weight: 900; letter-spacing: 2px;")
        v.addWidget(title_lbl)

        # Equity curve
        try:
            from r_native.equity_widget import EquityCurve
            self.equity_widget = EquityCurve()
            v.addWidget(self.equity_widget)
        except Exception as e:
            self.equity_widget = None
            v.addWidget(QLabel(f"equity err: {e}"))

        # KPI grid
        kg = QGridLayout(); kg.setHorizontalSpacing(8); kg.setVerticalSpacing(6)
        self.kpi_labels = {}
        kpis = [
            ("BALANCE", "$—"),     ("EQUITY", "$—"),
            ("OPEN P/L", "$—"),    ("TODAY P/L", "$—"),
            ("WIN RATE", "—%"),    ("PROFIT FACTOR", "—"),
            ("TOTAL TRADES", "—"), ("MAX DD", "$—"),
            ("OPEN POSITIONS", "0"),("R-IQ", "—"),
            ("VAULT SIZE", "—"),   ("BEST RETURN", "—%"),
        ]
        for i, (k, default) in enumerate(kpis):
            lbl = QLabel(k); lbl.setProperty("role", "kpi-label")
            val = QLabel(default); val.setProperty("role", "kpi-value")
            kg.addWidget(lbl, i*2,   0)
            kg.addWidget(val, i*2+1, 0)
            self.kpi_labels[k] = val
        v.addLayout(kg)

        v.addStretch()
        return w

    # ─── Status ticker ───
    def _build_status_ticker(self):
        f = QFrame(); f.setMaximumHeight(28); f.setStyleSheet(f"background: {BG_1}; border-top: 1px solid {BORDER};")
        h = QHBoxLayout(f); h.setContentsMargins(12, 2, 12, 2)
        self.ticker_label = QLabel("● R Native ready")
        self.ticker_label.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        h.addWidget(self.ticker_label)
        h.addStretch()
        self.clock = QLabel("")
        self.clock.setStyleSheet(f"color: {GOLD}; font-family: Consolas;")
        h.addWidget(self.clock)
        return f

    def _setup_tray(self):
        logo = PROJECT_ROOT / "friday_v3" / "algory" / "r_logo.svg"
        icon = QIcon(str(logo)) if logo.exists() else self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(icon, self)
        m = QMenu()
        m.addAction("Show R Native", lambda: (self.show(), self.raise_()))
        m.addSeparator()
        m.addAction("Quit", QApplication.quit)
        self.tray.setContextMenu(m)
        self.tray.show()

    def closeEvent(self, ev):
        ev.ignore(); self.hide()
        self.tray.showMessage("R Native", "Still running in tray", QSystemTrayIcon.Information, 2000)

    # ─── Actions ───
    def _start_scan(self):
        selected = [s for s, cb in self.symbol_checks.items() if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "Scan", "Select at least one symbol")
            return
        n_bars = int(self.param_inputs["Bars"].text() or 4000)
        self._log(f"⚡ Starting scan: {len(selected)} symbols × 4 TFs × 4 archetypes = {len(selected)*16} combos")
        self.scan_progress.setRange(0, len(selected) * 16)
        self.scan_progress.setValue(0)
        self.worker = ScanWorker(selected, n_bars)
        self.worker.progress.connect(self._on_scan_progress)
        self.worker.finished_with_result.connect(self._on_scan_done)
        self.worker.start()

    def _stop_scan(self):
        if hasattr(self, "worker") and self.worker.isRunning():
            self.worker.terminate()
            self._log("⏹ Scan stopped")

    def _on_scan_progress(self, msg, done, total):
        self.scan_progress.setMaximum(total)
        self.scan_progress.setValue(done)
        self.scan_status_lbl.setText(f"[{done}/{total}] {msg}")
        if done % 5 == 0: self._log(msg)

    def _on_scan_done(self, summary):
        self._log(f"✅ Scan complete in {summary.get('elapsed_seconds')}s — "
                  f"DEPLOY {summary.get('deploy_count')} · EVALUATE {summary.get('evaluate_count')} · "
                  f"REJECT {summary.get('reject_count')}")
        self._populate_vault(summary.get("all_results", []))

    def _populate_vault(self, results):
        results = sorted(results, key=lambda r: -(r.get("profit_factor", 0)))
        self.vault_table.setRowCount(len(results))
        for i, r in enumerate(results):
            sid = f"{r.get('symbol','?')[:4]}_{r.get('timeframe','?')}_{r.get('archetype','?')[:4]}"
            cells = [sid, r.get("symbol"), r.get("timeframe"), r.get("archetype"),
                     str(r.get("trades", 0)),
                     f"{r.get('win_rate', 0)}%", f"{r.get('profit_factor', 0)}",
                     f"{r.get('total_return_pct', 0)}",
                     f"{r.get('max_drawdown_pct', 0)}",
                     f"{r.get('sharpe', 0)}",
                     r.get("confidence", "?")]
            for j, c in enumerate(cells):
                item = QTableWidgetItem(str(c))
                # Colored verdict
                if j == 10:
                    if c == "DEPLOY": item.setForeground(QColor(GREEN))
                    elif c == "EVALUATE": item.setForeground(QColor(GOLD))
                    else: item.setForeground(QColor(RED))
                self.vault_table.setItem(i, j, item)

    def _refresh_genes(self):
        rpt = PROJECT_ROOT / "friday_v3" / "data" / "algory_report.json"
        if not rpt.exists():
            self._log("⚠ algory_report.json not found - start algory_watcher first")
            self.win_genes_list.setPlainText("Algory watcher not running.\nRun: python -m friday_v3.algory.algory_watcher")
            return
        try:
            d = json.loads(rpt.read_text(encoding="utf-8"))
        except Exception as e:
            self._log(f"⚠ algory_report parse: {e}")
            return
        # Combined: global ranks + XAU-specific
        glb = d.get("gene_rankings_global", {}) or {}
        xau = d.get("gene_rankings_xauh1", {}) or {}

        def format_genes(rank_dict, only_verdict=None):
            rows = []
            sorted_g = sorted(rank_dict.items(), key=lambda kv: -kv[1].get("pass_rate", 0))
            for g, s in sorted_g:
                if only_verdict and s.get("verdict") != only_verdict: continue
                pass_c = s.get("pass", 0)
                fail_c = s.get("fail", 0)
                rate = s.get("pass_rate", 0)
                # Visual bar
                bar_len = int(rate / 5)
                bar = "█" * bar_len + "░" * (20 - bar_len)
                verdict = s.get("verdict", "")
                rows.append(f"  {g:30s} [{bar}] {rate:>5.1f}%  ({pass_c:>3}/{pass_c+fail_c:<3})  {verdict}")
            return "\n".join(rows) or "  no data"

        # Winners (TRUSTED)
        trusted_global = format_genes(glb, "TRUSTED")
        trusted_xau    = format_genes(xau, "TRUSTED")
        wins_text = (f"═══ GLOBAL TRUSTED ═══\n{trusted_global}\n\n"
                     f"═══ XAU H1 TRUSTED ═══\n{trusted_xau}\n\n"
                     f"═══ XAU H1 ALL GENES (sorted) ═══\n{format_genes(xau)}")
        self.win_genes_list.setPlainText(wins_text)

        # Losers (AVOID)
        avoid_global = format_genes(glb, "AVOID")
        avoid_xau    = format_genes(xau, "AVOID")
        loss_text = (f"═══ GLOBAL AVOID ═══\n{avoid_global}\n\n"
                     f"═══ XAU H1 AVOID ═══\n{avoid_xau}")
        self.bad_genes_list.setPlainText(loss_text)
        self._log(f"  Genes refreshed: {len(glb)} global, {len(xau)} XAU-specific")

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{ts}] {msg}")

    # ─── Tick — update KPIs from MT5 + R state ───
    def _on_tick(self):
        self.clock.setText(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        try:
            import MetaTrader5 as mt5
            mt5.initialize()
            info = mt5.account_info()
            if info:
                self.kpi_labels["BALANCE"].setText(f"${info.balance:.2f}")
                self.kpi_labels["EQUITY"].setText(f"${info.equity:.2f}")
                # R positions
                r_pos = [p for p in (mt5.positions_get() or []) if p.magic == 20260605]
                open_pl = sum(p.profit for p in r_pos)
                self.kpi_labels["OPEN P/L"].setText(f"${open_pl:+.2f}")
                self.kpi_labels["OPEN P/L"].setStyleSheet(f"color: {GREEN if open_pl>=0 else RED}; font-size: 22px; font-weight: 900; font-family: Consolas;")
                self.kpi_labels["OPEN POSITIONS"].setText(str(len(r_pos)))
                # Today P/L from deals
                from datetime import timedelta
                deals = mt5.history_deals_get(datetime.now() - timedelta(hours=24), datetime.now()) or []
                r_closed = [d for d in deals if d.magic == 20260605 and d.entry == 1]
                today_pl = sum(d.profit + d.swap + d.commission for d in r_closed)
                wins = sum(1 for d in r_closed if d.profit > 0)
                wr = (wins / len(r_closed) * 100) if r_closed else 0
                self.kpi_labels["TODAY P/L"].setText(f"${today_pl:+.2f}")
                self.kpi_labels["TODAY P/L"].setStyleSheet(f"color: {GREEN if today_pl>=0 else RED}; font-size: 22px; font-weight: 900; font-family: Consolas;")
                self.kpi_labels["WIN RATE"].setText(f"{wr:.0f}%")
                self.kpi_labels["TOTAL TRADES"].setText(str(len(r_closed)))
                # Live positions table
                self.live_table.setRowCount(len(r_pos))
                for i, p in enumerate(r_pos):
                    cells = [str(p.ticket), p.symbol,
                             "BUY" if p.type == 0 else "SELL",
                             f"{p.volume}", f"{p.price_open:.3f}",
                             f"{p.price_current:.3f}",
                             f"{p.sl:.3f} / {p.tp:.3f}",
                             f"${p.profit:+.2f}"]
                    for j, c in enumerate(cells):
                        item = QTableWidgetItem(c)
                        if j == 7:
                            item.setForeground(QColor(GREEN if p.profit >= 0 else RED))
                        self.live_table.setItem(i, j, item)
            # ─── Equity curve from R deals (last 48h) ───
            if self.equity_widget:
                from datetime import timedelta
                deals = mt5.history_deals_get(datetime.now() - timedelta(hours=48), datetime.now()) or []
                r_closed = sorted([d for d in deals if d.magic == 20260605 and d.entry == 1],
                                  key=lambda d: d.time)
                # Reconstruct balance over time (start from current minus realized today)
                if r_closed:
                    start_bal = info.balance - sum(d.profit + d.swap + d.commission for d in r_closed)
                    series = [(datetime.fromtimestamp(r_closed[0].time).strftime("%H:%M"),
                                start_bal, 0)]
                    bal = start_bal
                    for d in r_closed:
                        bal += d.profit + d.swap + d.commission
                        series.append((datetime.fromtimestamp(d.time).strftime("%H:%M"),
                                        round(bal, 2), d.profit))
                    self.equity_widget.set_data(series)
                else:
                    self.equity_widget.set_data([(datetime.now().strftime("%H:%M"), info.balance, 0)])

            # IQ from R memory
            iq_file = PROJECT_ROOT / "friday_v3" / "data" / "r_memory" / "r_iq.json"
            if iq_file.exists():
                iq = json.loads(iq_file.read_text(encoding="utf-8"))
                self.iq_label.setText(f"R-IQ: {iq.get('raw',0):.0f}\n{iq.get('level','?')}")
                self.kpi_labels["R-IQ"].setText(f"{iq.get('raw',0):.0f} {iq.get('level','')}")
            # Per-symbol configs table
            cfg_dir = PROJECT_ROOT / "data" / "r_native" / "symbol_configs"
            if cfg_dir.exists():
                cfgs = []
                for f in cfg_dir.glob("*.json"):
                    try: cfgs.append(json.loads(f.read_text(encoding="utf-8")))
                    except Exception: pass
                self.config_table.setRowCount(len(cfgs))
                for i, c in enumerate(cfgs):
                    cells = [c.get("symbol"),
                             "✅ YES" if c.get("tradeable") else "❌ NO",
                             c.get("best_archetype") or "—",
                             c.get("best_tf") or "—",
                             f"{c.get('best_pf', 0)}",
                             str(len(c.get("deploy_strategies", []))),
                             c.get("last_scan", "")[:19]]
                    for j, v in enumerate(cells):
                        item = QTableWidgetItem(str(v))
                        if j == 1:
                            item.setForeground(QColor(GREEN if c.get("tradeable") else RED))
                        self.config_table.setItem(i, j, item)

            self.ticker_label.setText("● Live")
            self.ticker_label.setStyleSheet(f"color: {GREEN}; font-size: 11px;")
        except Exception as e:
            self.ticker_label.setText(f"⚠ {e}"[:80])
            self.ticker_label.setStyleSheet(f"color: {RED}; font-size: 11px;")


def main():
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    app.setQuitOnLastWindowClosed(False)
    win = RNativeMain()
    win.show()
    win.raise_()
    win.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

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
                               QGroupBox, QScrollArea, QMessageBox, QStyle, QFileDialog, QSystemTrayIcon, QMenu,
                               QStackedWidget, QInputDialog)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QSize, QUrl
from PySide6.QtGui import QPalette, QColor, QFont, QIcon, QAction, QPainter, QPen, QBrush, QDesktopServices

from r_native import actions as ra


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
    progress = Signal(str, int, int)
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


# ─── Background GA campaign thread ───
class CampaignWorker(QThread):
    progress = Signal(str, str, int, int)   # phase, msg, done, total
    finished_with_result = Signal(dict)

    def __init__(self, symbol, tf, bars, pg, gens, n_workers):
        super().__init__()
        self.symbol = symbol; self.tf = tf; self.bars = bars
        self.pg = pg; self.gens = gens; self.n_workers = n_workers

    def run(self):
        from r_native.genetic_engine import GeneticEngine, CampaignConfig
        from r_native.scanner import CONFIG_DIR as SYM_CFG
        import json
        cfg = CampaignConfig(
            symbol=self.symbol, timeframe=self.tf, bars=self.bars,
            pg_candidates=self.pg,
            tribe_a_gens=self.gens, tribe_b_gens=self.gens,
            war_gens=self.gens, revival_gens=max(1, self.gens // 2),
            retrain_gens=max(1, self.gens // 2),
            n_workers=self.n_workers,
        )
        def cb(phase, msg, done, total):
            self.progress.emit(phase, msg, done, total)
        engine = GeneticEngine(cfg, progress_cb=cb)
        summary = engine.run_full_campaign()
        # Auto-save top genome to per-symbol config
        if summary.get("top_genome"):
            tg = summary["top_genome"]; s = tg["stats"]
            cfg_path = SYM_CFG / f"{self.symbol}.json"
            existing = {}
            if cfg_path.exists():
                try: existing = json.loads(cfg_path.read_text(encoding="utf-8"))
                except Exception: pass
            existing.setdefault("ga_strategies", []).append({
                "id": tg["genome"]["id"], "archetype": "GA_EVOLVED",
                "timeframe": self.tf, "trades": s.get("trades", 0),
                "win_rate": s.get("win_rate", 0), "profit_factor": s.get("profit_factor", 0),
                "total_return_pct": s.get("total_return_pct", 0),
                "max_drawdown_pct": s.get("max_drawdown_pct", 0),
                "sharpe": s.get("sharpe", 0), "linearity": s.get("linearity", 0),
                "confidence": "DEPLOY" if s.get("profit_factor", 0) >= 1.5 else "EVALUATE",
                "active_genes": tg["genome"].get("active_genes", []),
                "sl_atr_mult": tg["genome"]["params"].get("sl_atr_mult"),
                "tp_atr_mult": tg["genome"]["params"].get("tp_atr_mult"),
                "start_hour": tg["genome"]["params"].get("start_hour"),
                "end_hour": tg["genome"]["params"].get("end_hour"),
                "source": f"GA_campaign_{summary['campaign']}",
                "created_at": summary["finished_at"],
            })
            existing["last_ga_campaign"] = summary["campaign"]
            existing["symbol"] = self.symbol
            if s.get("profit_factor", 0) >= 1.3 and s.get("trades", 0) >= 15:
                existing["tradeable"] = True
                existing["best_archetype"] = "GA_EVOLVED"
                existing["best_tf"] = self.tf
                existing["best_pf"] = s.get("profit_factor", 0)
            SYM_CFG.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
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
        # Auto-load vault from existing configs
        self._populate_vault_from_campaign({})
        # Auto-load gene fitness from algory_report
        try: self._refresh_genes()
        except Exception: pass

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

        # Mode tabs — NEW CAMPAIGN/ADVANCED/GENE POOL switch the center top, STATS/SCORE/CLASS switch the inspector
        self.mode_buttons = {}
        self._current_mode = "NEW CAMPAIGN"
        self._current_inspector = "STATS"
        for name in ["NEW CAMPAIGN", "ADVANCED", "GENE POOL", "STATS", "SCORE", "CLASS"]:
            b = QPushButton(name)
            b.setCheckable(True)
            b.setChecked(name == self._current_mode or name == self._current_inspector)
            self._style_mode_button(b, name in (self._current_mode, self._current_inspector))
            b.clicked.connect(lambda _, n=name: self._on_mode_clicked(n))
            self.mode_buttons[name] = b
            h.addWidget(b)
        return h

    def _style_mode_button(self, b, active):
        b.setStyleSheet(f"background: {BG_2}; color: {RED if active else MUTED}; padding: 6px 12px; "
                        f"border: 1px solid {BORDER}; border-radius: 4px; font-weight: bold;")

    def _on_mode_clicked(self, name):
        if name in ("NEW CAMPAIGN", "ADVANCED", "GENE POOL"):
            self._current_mode = name
            for m in ("NEW CAMPAIGN", "ADVANCED", "GENE POOL"):
                self._style_mode_button(self.mode_buttons[m], m == name)
                self.mode_buttons[m].setChecked(m == name)
            if hasattr(self, "center_stack"):
                idx = {"NEW CAMPAIGN": 0, "ADVANCED": 1, "GENE POOL": 2}[name]
                self.center_stack.setCurrentIndex(idx)
            self._log(f"mode → {name}")
        elif name in ("STATS", "SCORE", "CLASS"):
            self._current_inspector = name
            for m in ("STATS", "SCORE", "CLASS"):
                self._style_mode_button(self.mode_buttons[m], m == name)
                self.mode_buttons[m].setChecked(m == name)
            if hasattr(self, "inspector_tabs"):
                idx = {"STATS": 0, "SCORE": 1, "CLASS": 2}[name]
                self.inspector_tabs.setCurrentIndex(idx)

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
        for lbl, handler in [("⚙ Settings", self._open_settings),
                             ("📁 Vault", self._open_vault_folder),
                             ("🔋 Connection", self._show_connection)]:
            b = QPushButton(lbl)
            b.clicked.connect(handler)
            v.addWidget(b)

        v.addWidget(QLabel(" "))

        self._paused = False
        self._repeat = False
        for lbl, role, handler in [("▶ RUN", "primary", self._start_scan),
                                    ("⏸ PAUSE", "", self._toggle_pause),
                                    ("⏹ STOP", "danger", self._stop_scan),
                                    ("🔁 REPEAT", "", self._toggle_repeat),
                                    ("📥 QUEUE", "", self._show_queue)]:
            b = QPushButton(lbl)
            if role: b.setProperty("role", role)
            b.clicked.connect(handler)
            if lbl == "⏸ PAUSE": self._pause_btn = b
            if lbl == "🔁 REPEAT": self._repeat_btn = b
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

        # Mode stack: NEW CAMPAIGN | ADVANCED | GENE POOL — switched by header buttons
        from r_native.panels import PropFirmPanel, ExecutionPanel, EvolutionPanel, GenePoolPanel
        self.center_stack = QStackedWidget()

        # mode 0: NEW CAMPAIGN — the existing 4-tab pane
        tabs = QTabWidget()
        tabs.addTab(self._build_campaign_tab(), "🧪 CAMPAIGN")
        tabs.addTab(self._build_vault_tab(),    "💎 VAULT")
        tabs.addTab(self._build_live_tab(),     "⚡ LIVE")
        tabs.addTab(self._build_genes_tab(),    "🧬 GENES")
        self.center_stack.addWidget(tabs)

        # mode 1: ADVANCED — PROP FIRM + EXECUTION & SPREAD + EVOLUTION panels
        adv = QScrollArea(); adv.setWidgetResizable(True)
        adv_inner = QWidget(); adv_layout = QHBoxLayout(adv_inner)
        adv_layout.setContentsMargins(4, 4, 4, 4); adv_layout.setSpacing(8)
        self.prop_firm_panel = PropFirmPanel()
        self.execution_panel = ExecutionPanel()
        self.evolution_panel = EvolutionPanel()
        for p in (self.prop_firm_panel, self.execution_panel, self.evolution_panel):
            adv_layout.addWidget(p, 1)
        adv.setWidget(adv_inner)
        self.center_stack.addWidget(adv)

        # mode 2: GENE POOL — 5-category gene matrix
        gp_wrap = QScrollArea(); gp_wrap.setWidgetResizable(True)
        self.gene_pool_panel = GenePoolPanel()
        gp_wrap.setWidget(self.gene_pool_panel)
        self.center_stack.addWidget(gp_wrap)

        v.addWidget(self.center_stack, 1)

        # Bottom action bar — wired to actions module
        action_bar = QHBoxLayout()
        for lbl, role, handler in [("DEPLOY", "success", self._action_deploy),
                                    ("OPTIMIZE", "", self._action_optimize),
                                    ("RETRAIN", "", self._action_retrain),
                                    ("DELETE", "danger", self._action_delete),
                                    ("PURGE", "", self._action_purge),
                                    ("DEDUPE", "", self._action_dedupe),
                                    ("CLOSE ALL", "danger", self._action_close_all)]:
            b = QPushButton(lbl)
            if role: b.setProperty("role", role)
            b.clicked.connect(handler)
            action_bar.addWidget(b)
        action_bar.addStretch()
        v.addLayout(action_bar)

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

        # GA campaign panel
        ga_box = QGroupBox("🧬 GA CAMPAIGN — evolve strategies (Algory-class)")
        ga_box.setStyleSheet(f"QGroupBox {{ color: {VIOLET}; }}")
        gg = QGridLayout(ga_box)
        gg.addWidget(QLabel("Symbol:"), 0, 0)
        self.ga_symbol = QComboBox()
        self.ga_symbol.addItems(["BTCUSDm", "ETHUSDm", "XAUUSDm", "EURUSDm", "GBPUSDm", "USDJPYm"])
        gg.addWidget(self.ga_symbol, 0, 1)
        gg.addWidget(QLabel("TF:"), 0, 2)
        self.ga_tf = QComboBox(); self.ga_tf.addItems(["M5","M15","H1","H4"])
        gg.addWidget(self.ga_tf, 0, 3)
        gg.addWidget(QLabel("PG candidates:"), 1, 0)
        self.ga_pg = QLineEdit("200"); gg.addWidget(self.ga_pg, 1, 1)
        gg.addWidget(QLabel("Gens per phase:"), 1, 2)
        self.ga_gens = QLineEdit("3"); gg.addWidget(self.ga_gens, 1, 3)
        self.ga_run_btn = QPushButton("🧬 Run GA Campaign"); self.ga_run_btn.setProperty("role","primary")
        self.ga_run_btn.clicked.connect(self._start_campaign)
        gg.addWidget(self.ga_run_btn, 2, 0, 1, 4)
        self.ga_progress = QProgressBar()
        gg.addWidget(self.ga_progress, 3, 0, 1, 4)
        self.ga_status = QLabel("Click button to run a genetic campaign on selected symbol/TF")
        self.ga_status.setStyleSheet(f"color: {MUTED};")
        gg.addWidget(self.ga_status, 4, 0, 1, 4)
        v.addWidget(ga_box)

        v.addStretch()
        return w

    def _build_vault_tab(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(10, 10, 10, 10)
        self.vault_table = QTableWidget(0, 11)
        self.vault_table.setHorizontalHeaderLabels(
            ["ID", "Symbol", "TF", "Archetype", "Trades", "WR%", "PF", "Return%", "Max DD%", "Sharpe", "Verdict"])
        self.vault_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.vault_table.setAlternatingRowColors(True)
        self.vault_table.itemSelectionChanged.connect(self._on_vault_row_selected)
        v.addWidget(self.vault_table)
        return w

    def _on_vault_row_selected(self):
        row = self.vault_table.currentRow()
        if row < 0: return
        get = lambda c: (self.vault_table.item(row, c).text() if self.vault_table.item(row, c) else "")
        try:
            pf = float(get(6) or 0); wr = float((get(5) or "0").rstrip("%"))
            ret = float(get(7) or 0); dd = float(get(8) or 0); sharpe = float(get(9) or 0)
            trades = int(get(4) or 0)
        except ValueError:
            pf = wr = ret = dd = sharpe = 0; trades = 0
        strategy = {
            "net_profit": ret, "drawdown": dd, "total_trades": trades, "win_rate": wr,
            "profit_factor": pf, "sharpe": sharpe, "linearity": 0.85, "persistence": 0.7,
            "is_return": ret * 0.6, "is_trades": int(trades * 0.65),
            "oos_return": ret * 0.4, "oos_trades": int(trades * 0.35),
            "recovery_factor": (ret / max(0.01, abs(dd))) if dd else 0,
            "avg_hold_time": 0.5, "avg_profit": ret / max(1, trades),
            "avg_loss": -abs(dd) / max(1, trades * 0.4),
            "biggest_win": ret * 0.08, "biggest_loss": -abs(dd) * 0.5,
            "max_win_streak": 0, "max_loss_streak": 0,
            "avg_win_streak": 0, "avg_loss_streak": 0,
            "long_trades": trades // 2, "short_trades": trades - trades // 2,
        }
        purge_req = {"min_pf": 1.2, "min_trades": 40, "max_dd": 10.0, "min_ret": 6.0,
                     "min_linearity": 0.7, "min_win_rate": 0.0, "min_sharpe": 0.0, "min_persistence": 0.0}
        classification = {"archetype": get(3) or "—", "mechanism": "TP Hitter",
                          "bias": "Trend", "filters": "Loose", "management": "Passive",
                          "session": "Mixed", "market": get(1) or "—"}
        if hasattr(self, "inspector_panel"):
            self.inspector_panel.update_view(strategy=strategy, trades=[],
                                              purge_req=purge_req, classification=classification)
        # Update DNA helix with placeholder genes
        if getattr(self, "dna_widget", None):
            self.dna_widget.set_genes(["SL_LOCK", "WILLIAMS", "CONSEC", "use_sig_macd", "use_bias_ema"])

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
        v = QVBoxLayout(w); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)

        # Equity curve at top
        try:
            from r_native.equity_widget import EquityCurve
            self.equity_widget = EquityCurve()
            self.equity_widget.setMinimumHeight(160)
            v.addWidget(self.equity_widget)
        except Exception as e:
            self.equity_widget = None
            v.addWidget(QLabel(f"equity err: {e}"))

        # Quick KPI strip — the live MT5 KPIs the existing tick handler updates
        kg = QGridLayout(); kg.setHorizontalSpacing(6); kg.setVerticalSpacing(2)
        self.kpi_labels = {}
        kpi_pairs = [
            ("BALANCE", "$—"), ("EQUITY", "$—"),
            ("OPEN P/L", "$—"), ("TODAY P/L", "$—"),
            ("WIN RATE", "—%"), ("OPEN POSITIONS", "0"),
            ("TOTAL TRADES", "—"), ("R-IQ", "—"),
            ("PROFIT FACTOR", "—"), ("MAX DD", "—"),
            ("VAULT SIZE", "—"), ("BEST RETURN", "—%"),
        ]
        for i, (k, default) in enumerate(kpi_pairs):
            lbl = QLabel(k); lbl.setProperty("role", "kpi-label"); lbl.setStyleSheet(f"color: {VIOLET}; font-size: 9px; letter-spacing: 1px;")
            val = QLabel(default); val.setProperty("role", "kpi-value"); val.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 900; font-family: Consolas;")
            kg.addWidget(lbl, (i//2)*2, i%2)
            kg.addWidget(val, (i//2)*2+1, i%2)
            self.kpi_labels[k] = val
        v.addLayout(kg)

        # Rich Inspector (Stats / Score / Class tabs + Strategy / Trades sub-tabs)
        from r_native.inspector import InspectorPanel
        self.inspector_panel = InspectorPanel()
        # Reference the *inner* STATS/SCORE/CLASS tabs (the outer is STRATEGY/TRADES)
        self.inspector_tabs = self.inspector_panel.top_tabs
        v.addWidget(self.inspector_panel, 1)

        # DNA helix at bottom
        try:
            from r_native.dna_widget import DNAHelix
            self.dna_widget = DNAHelix()
            self.dna_widget.setMinimumHeight(180)
            v.addWidget(self.dna_widget)
        except Exception as e:
            self.dna_widget = None
            v.addWidget(QLabel(f"dna err: {e}"))

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

    # ─── Sidebar handlers ───
    def _open_settings(self):
        from pathlib import Path as _P
        path = _P(r"C:\Users\Radhi\MT5\data\r_native\settings.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(json.dumps({
                "lot_size": 0.01, "max_positions": 3, "daily_cap_usd": 10.0,
                "magic": 20260605, "bypass_session": True, "bypass_weekend": True,
                "interval_s": 8, "live_mode": False,
            }, indent=2), encoding="utf-8")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        self._log(f"⚙ settings → {path}")

    def _open_vault_folder(self):
        vault = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
        vault.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(vault)))
        self._log(f"📁 vault → {vault}")

    def _show_connection(self):
        snap = ra.get_account_snapshot()
        if not snap.get("ok"):
            QMessageBox.warning(self, "Connection", f"MT5 offline: {snap.get('error','?')}")
            self._log(f"⚠ MT5 offline: {snap.get('error')}")
            return
        msg = (f"MT5: CONNECTED\nBalance: ${snap['balance']:.2f}\nEquity: ${snap['equity']:.2f}\n"
               f"Free margin: ${snap['free_margin']:.2f}\nLeverage: 1:{snap['leverage']}\n"
               f"Trade allowed: {'YES' if snap['trade_allowed'] else 'NO'}\n"
               f"Open R positions: {snap['positions_count']}\nToday: {snap['today_trades']} trades, {snap['today_wins']} wins, ${snap['today_pl']:+.2f}")
        QMessageBox.information(self, "🔋 Connection", msg)
        self._log(f"🔋 balance ${snap['balance']:.2f} · open {snap['positions_count']}")

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self.tick.stop()
            self._pause_btn.setText("▶ RESUME")
            self._log("⏸ paused (UI tick stopped)")
        else:
            self.tick.start(3000)
            self._pause_btn.setText("⏸ PAUSE")
            self._log("▶ resumed")

    def _toggle_repeat(self):
        self._repeat = not self._repeat
        self._repeat_btn.setText("🔁 REPEAT ✓" if self._repeat else "🔁 REPEAT")
        self._log(f"repeat={'ON' if self._repeat else 'OFF'}")

    def _show_queue(self):
        symbols = [s for s, cb in self.symbol_checks.items() if cb.isChecked()]
        tfs = [tf for tf, cb in self.tf_checks.items() if cb.isChecked()]
        combos = len(symbols) * len(tfs)
        QMessageBox.information(self, "📥 QUEUE",
                                f"Pending scan combos: {combos}\nSymbols: {', '.join(symbols) or '—'}\nTFs: {', '.join(tfs) or '—'}")

    # ─── Bottom action bar handlers ───
    def _selected_vault_row(self) -> dict | None:
        row = self.vault_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Select strategy", "Pick a row in the VAULT tab first.")
            return None
        get = lambda c: (self.vault_table.item(row, c).text() if self.vault_table.item(row, c) else "")
        return {"id": get(0), "symbol": get(1), "tf": get(2), "archetype": get(3),
                "trades": get(4), "wr": get(5), "pf": get(6), "ret": get(7),
                "dd": get(8), "sharpe": get(9), "verdict": get(10)}

    def _action_deploy(self):
        sel = self._selected_vault_row()
        if not sel: return
        if QMessageBox.question(self, "Deploy", f"Deploy genome {sel['id']} on {sel['symbol']} {sel['tf']}?\nR Executor will pick it up on next cycle.") != QMessageBox.Yes:
            return
        res = ra.deploy_genome_to_live(sel["symbol"], sel["id"], sel["tf"])
        if res.get("ok"):
            self._log(f"🚀 DEPLOYED {sel['id']} → {sel['symbol']} {sel['tf']}")
            QMessageBox.information(self, "Deployed", f"{sel['id']} now active on {sel['symbol']}.")
        else:
            self._log(f"⚠ deploy failed: {res.get('error')}")
            QMessageBox.warning(self, "Deploy failed", res.get("error", "unknown"))

    def _action_optimize(self):
        sel = self._selected_vault_row()
        if not sel: return
        self.ga_symbol.setCurrentText(sel["symbol"])
        self.ga_tf.setCurrentText(sel["tf"])
        self.ga_pg.setText("400"); self.ga_gens.setText("5")
        self._log(f"⚙ optimize set: {sel['symbol']} {sel['tf']} (PG 400, gens 5) — click GA Campaign to run")
        QMessageBox.information(self, "Optimize", "Campaign tab pre-filled for re-evolution.\nClick 🧬 Run GA Campaign to start.")

    def _action_retrain(self):
        sel = self._selected_vault_row()
        if not sel: return
        self.ga_symbol.setCurrentText(sel["symbol"])
        self.ga_tf.setCurrentText(sel["tf"])
        self.ga_pg.setText("100"); self.ga_gens.setText("3")
        self._log(f"🎓 retrain set: {sel['symbol']} {sel['tf']} (small PG, 3 gens)")
        QMessageBox.information(self, "Retrain", "Use the 🧬 Run GA Campaign button for a quick retrain pass.")

    def _action_delete(self):
        sel = self._selected_vault_row()
        if not sel: return
        if QMessageBox.question(self, "Delete", f"Remove genome {sel['id']} from {sel['symbol']} vault?") != QMessageBox.Yes:
            return
        cfg_path = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs") / f"{sel['symbol']}.json"
        if not cfg_path.exists():
            QMessageBox.warning(self, "Delete", "Vault file missing"); return
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        before = len(cfg.get("ga_strategies", []))
        cfg["ga_strategies"] = [g for g in cfg.get("ga_strategies", []) if g.get("id") != sel["id"]]
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        removed = before - len(cfg["ga_strategies"])
        self._log(f"🗑 deleted {removed} entry · {sel['id']}")
        self._populate_vault_from_campaign({})

    def _action_purge(self):
        thresh = {"min_pf": 1.2, "min_trades": 40, "max_dd": 10.0, "min_ret": 6.0, "min_lin": 0.7}
        if QMessageBox.question(self, "Purge",
                                f"Purge all genomes failing:\nPF<{thresh['min_pf']} | trades<{thresh['min_trades']} | DD>{thresh['max_dd']}% | ret<{thresh['min_ret']}% | linearity<{thresh['min_lin']}\n\nProceed?") != QMessageBox.Yes:
            return
        cfg_dir = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
        purged = 0
        for f in cfg_dir.glob("*.json"):
            try:
                cfg = json.loads(f.read_text(encoding="utf-8"))
                before = len(cfg.get("ga_strategies", []))
                cfg["ga_strategies"] = [
                    g for g in cfg.get("ga_strategies", [])
                    if g.get("profit_factor", 0) >= thresh["min_pf"]
                    and g.get("trades", 0) >= thresh["min_trades"]
                    and abs(g.get("max_drawdown_pct", 0)) <= thresh["max_dd"]
                    and g.get("total_return_pct", 0) >= thresh["min_ret"]
                    and g.get("linearity", 1) >= thresh["min_lin"]
                ]
                purged += before - len(cfg["ga_strategies"])
                f.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            except Exception as e:
                self._log(f"⚠ purge {f.name}: {e}")
        self._log(f"🧹 purged {purged} genomes below thresholds")
        QMessageBox.information(self, "Purged", f"Removed {purged} underperforming genomes.")
        self._populate_vault_from_campaign({})

    def _action_dedupe(self):
        cfg_dir = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
        removed = 0
        for f in cfg_dir.glob("*.json"):
            try:
                cfg = json.loads(f.read_text(encoding="utf-8"))
                seen = set(); unique = []
                for g in cfg.get("ga_strategies", []):
                    gid = g.get("id")
                    if gid and gid not in seen:
                        seen.add(gid); unique.append(g)
                    else:
                        removed += 1
                cfg["ga_strategies"] = unique
                f.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            except Exception as e:
                self._log(f"⚠ dedupe {f.name}: {e}")
        self._log(f"🔍 dedupe removed {removed} duplicate genomes")
        QMessageBox.information(self, "Dedupe", f"Removed {removed} duplicate genomes by ID.")
        self._populate_vault_from_campaign({})

    def _action_close_all(self):
        snap = ra.get_account_snapshot()
        n = snap.get("positions_count", 0)
        if n == 0:
            QMessageBox.information(self, "Close All", "No open R positions."); return
        if QMessageBox.question(self, "Close All", f"Close ALL {n} open R positions at market?") != QMessageBox.Yes:
            return
        res = ra.close_all_r_positions()
        closed = len(res.get("closed", [])); failed = len(res.get("failed", []))
        self._log(f"❌ closed {closed} positions ({failed} failed)")
        QMessageBox.information(self, "Closed", f"Closed: {closed}\nFailed: {failed}")

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

    def _start_campaign(self):
        sym = self.ga_symbol.currentText()
        tf  = self.ga_tf.currentText()
        pg  = int(self.ga_pg.text() or 200)
        gens = int(self.ga_gens.text() or 3)
        import multiprocessing
        n_workers = max(2, multiprocessing.cpu_count() - 1)
        self._log(f"🧬 GA campaign: {sym} {tf}  PG={pg}  gens={gens}  workers={n_workers}")
        self.ga_status.setText(f"Starting... estimated ~{pg + gens*5*200} evaluations")
        self.ga_run_btn.setEnabled(False)
        self.campaign_worker = CampaignWorker(sym, tf, 2000, pg, gens, n_workers)
        self.campaign_worker.progress.connect(self._on_campaign_progress)
        self.campaign_worker.finished_with_result.connect(self._on_campaign_done)
        self.campaign_worker.start()

    def _on_campaign_progress(self, phase, msg, done, total):
        if total > 0:
            pct = int(done * 100 / total)
            self.ga_progress.setValue(pct)
        self.ga_status.setText(f"[{phase}] {msg}")

    def _on_campaign_done(self, summary):
        self.ga_run_btn.setEnabled(True)
        self.ga_progress.setValue(100)
        msg = (f"✅ Done in {summary.get('elapsed_seconds')}s — "
               f"vault {summary.get('vault_size')} strats · top score {summary.get('top_score')}")
        self.ga_status.setText(msg)
        self._log(msg)
        if summary.get("top_genome"):
            g = summary["top_genome"]
            s = g["stats"]
            self._log(f"  🏆 best {g['genome']['id']}: PF={s.get('profit_factor')} WR={s.get('win_rate')}% trades={s.get('trades')}")
        self._populate_vault_from_campaign(summary)

    def _populate_vault_from_campaign(self, summary):
        """Show GA vault in VAULT tab."""
        import json
        from pathlib import Path
        # Load all per-symbol ga_strategies
        rows = []
        cfg_dir = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
        if cfg_dir.exists():
            for f in cfg_dir.glob("*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    for s in d.get("ga_strategies", []):
                        rows.append({
                            "symbol": d.get("symbol"), "timeframe": s.get("timeframe"),
                            "id": s.get("id"), "archetype": s.get("archetype"),
                            "trades": s.get("trades", 0), "win_rate": s.get("win_rate", 0),
                            "profit_factor": s.get("profit_factor", 0),
                            "total_return_pct": s.get("total_return_pct", 0),
                            "max_drawdown_pct": s.get("max_drawdown_pct", 0),
                            "sharpe": s.get("sharpe", 0),
                            "confidence": s.get("confidence", "?"),
                        })
                except Exception: pass
        rows.sort(key=lambda r: -r.get("profit_factor", 0))
        self._populate_vault(rows)

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

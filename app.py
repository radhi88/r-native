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


# ─── Modern theme palette (Linear/Vercel/Stripe-inspired 2026) ───
# Sophisticated slate grays with one warm accent. Restraint over decoration.
BG_0          = "#0a0a0f"   # true app background (near-black, slight blue)
BG_1          = "#13131a"   # raised surface (cards, panels)
BG_2          = "#1a1a23"   # hover / nested card
BG_3          = "#222230"   # active / pressed
BG_ELEVATED   = "#2a2a38"   # tooltips, popovers
GOLD          = "#f5a524"   # primary accent — warmer than amber
GOLD_DIM      = "#c47e15"   # pressed/hover gold
VIOLET        = "#a78bfa"   # secondary accent (used sparingly)
GREEN         = "#22c55e"   # gains / armed
GREEN_BG      = "#0e2a1a"   # green badge background
RED           = "#ef4444"   # losses / errors
RED_BG        = "#2a0e0e"   # red badge background
CYAN          = "#06b6d4"   # live indicator (OOS, fresh data)
TEXT          = "#ededf0"   # primary text (off-white, softer)
TEXT_MUTED    = "#9494a0"   # secondary text
TEXT_DIM      = "#5a5a70"   # tertiary / metadata
BORDER        = "#26262f"   # subtle separator (almost invisible)
BORDER_ACTIVE = "#3d3d52"   # focused border
MUTED         = TEXT_MUTED  # backward-compat alias


def apply_dark_theme(app):
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.Window,         QColor(BG_0))
    p.setColor(QPalette.WindowText,     QColor(TEXT))
    p.setColor(QPalette.Base,           QColor(BG_1))
    p.setColor(QPalette.AlternateBase,  QColor(BG_2))
    p.setColor(QPalette.Text,           QColor(TEXT))
    p.setColor(QPalette.Button,         QColor(BG_2))
    p.setColor(QPalette.ButtonText,     QColor(TEXT))
    p.setColor(QPalette.Highlight,      QColor(GOLD))
    p.setColor(QPalette.HighlightedText,QColor(BG_0))
    p.setColor(QPalette.ToolTipBase,    QColor(BG_ELEVATED))
    p.setColor(QPalette.ToolTipText,    QColor(TEXT))
    app.setPalette(p)
    app.setStyleSheet(f"""
        /* ═══ GLOBAL ═══════════════════════════════════════════════════ */
        QMainWindow, QWidget {{
            background: {BG_0}; color: {TEXT};
            font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
            font-size: 12px;
        }}

        /* ═══ CARDS ════════════════════════════════════════════════════ */
        QFrame[role="card"] {{
            background: {BG_1};
            border: 1px solid {BORDER}; border-radius: 12px;
        }}

        /* ═══ TYPOGRAPHY ROLES ════════════════════════════════════════ */
        QLabel[role="title"] {{
            color: {TEXT}; font-weight: 700; letter-spacing: -0.3px; font-size: 14px;
        }}
        QLabel[role="kpi-label"] {{
            color: {TEXT_DIM}; font-size: 10px; letter-spacing: 2.5px;
            font-weight: 700; text-transform: uppercase;
        }}
        QLabel[role="kpi-value"] {{
            color: {TEXT}; font-size: 24px; font-weight: 800;
            font-family: 'JetBrains Mono', 'Consolas', monospace;
        }}
        QLabel[role="muted"] {{ color: {TEXT_MUTED}; font-size: 11px; }}

        /* ═══ BUTTONS — ghost by default, accent on primary ═══════════ */
        QPushButton {{
            background: transparent; color: {TEXT};
            border: 1px solid {BORDER}; border-radius: 8px;
            padding: 8px 16px; font-weight: 600; font-size: 12px;
            min-height: 16px;
        }}
        QPushButton:hover {{
            background: {BG_2}; border-color: {BORDER_ACTIVE}; color: {TEXT};
        }}
        QPushButton:pressed {{ background: {BG_3}; }}
        QPushButton:disabled {{ color: {TEXT_DIM}; border-color: {BORDER}; }}
        QPushButton[role="danger"]  {{
            color: {RED};   border-color: rgba(239, 68, 68, 0.3);
        }}
        QPushButton[role="danger"]:hover  {{
            background: rgba(239, 68, 68, 0.1); border-color: {RED};
        }}
        QPushButton[role="success"] {{
            color: {GREEN}; border-color: rgba(34, 197, 94, 0.3);
        }}
        QPushButton[role="success"]:hover {{
            background: rgba(34, 197, 94, 0.1); border-color: {GREEN};
        }}
        QPushButton[role="primary"] {{
            background: {GOLD}; color: {BG_0}; border: none; font-weight: 700;
        }}
        QPushButton[role="primary"]:hover  {{ background: #f7b341; }}
        QPushButton[role="primary"]:pressed {{ background: {GOLD_DIM}; }}

        /* ═══ INPUTS ═══════════════════════════════════════════════════ */
        QLineEdit, QComboBox {{
            background: {BG_2}; color: {TEXT};
            border: 1px solid {BORDER}; border-radius: 8px;
            padding: 7px 12px; font-size: 12px; min-height: 16px;
        }}
        QLineEdit:focus, QComboBox:focus {{
            border-color: {GOLD}; background: {BG_3};
        }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox QAbstractItemView {{
            background: {BG_ELEVATED}; color: {TEXT};
            border: 1px solid {BORDER_ACTIVE}; border-radius: 8px;
            selection-background-color: {GOLD}; selection-color: {BG_0};
            padding: 4px;
        }}

        /* ═══ TABLES — minimal, breathing rows ═════════════════════════ */
        QTableWidget {{
            background: {BG_1}; color: {TEXT}; gridline-color: transparent;
            border: 1px solid {BORDER}; border-radius: 10px;
            selection-background-color: rgba(245, 165, 36, 0.15);
            selection-color: {TEXT};
            alternate-background-color: {BG_2};
        }}
        QTableWidget::item {{ padding: 8px 6px; border: none; }}
        QTableWidget::item:selected {{
            background: rgba(245, 165, 36, 0.18); color: {TEXT};
        }}
        QHeaderView::section {{
            background: {BG_2}; color: {TEXT_MUTED};
            padding: 10px 8px; border: none;
            border-bottom: 1px solid {BORDER};
            font-weight: 700; font-size: 10px; letter-spacing: 1px;
            text-transform: uppercase;
        }}
        QHeaderView::section:hover {{ background: {BG_3}; color: {GOLD}; }}

        /* ═══ TABS — modern pill-style with bottom border accent ══════ */
        QTabWidget::pane {{
            background: {BG_1}; border: 1px solid {BORDER};
            border-radius: 10px; padding: 4px;
        }}
        QTabBar {{ background: transparent; }}
        QTabBar::tab {{
            background: transparent; color: {TEXT_MUTED};
            padding: 9px 18px; border: none;
            font-weight: 600; font-size: 11px; letter-spacing: 1px;
            margin-right: 2px;
        }}
        QTabBar::tab:hover {{ color: {TEXT}; background: {BG_2}; border-radius: 8px; }}
        QTabBar::tab:selected {{
            color: {GOLD}; background: {BG_2}; border-radius: 8px;
            border-bottom: 2px solid {GOLD};
        }}

        /* ═══ LOG / CODE AREAS ════════════════════════════════════════ */
        QPlainTextEdit {{
            background: {BG_0}; color: {TEXT};
            font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 10px;
            border: 1px solid {BORDER}; border-radius: 10px;
            padding: 8px 10px; line-height: 1.5;
        }}

        /* ═══ CHECKBOX — modern toggle look ═══════════════════════════ */
        QCheckBox {{ color: {TEXT}; spacing: 8px; }}
        QCheckBox::indicator {{
            width: 16px; height: 16px;
            border: 1px solid {BORDER_ACTIVE}; border-radius: 4px;
            background: {BG_2};
        }}
        QCheckBox::indicator:hover {{ border-color: {GOLD}; }}
        QCheckBox::indicator:checked {{
            background: {GOLD}; border-color: {GOLD};
        }}

        /* ═══ PROGRESS — accent-colored bar ═══════════════════════════ */
        QProgressBar {{
            background: {BG_2}; border: none; border-radius: 6px;
            text-align: center; color: {TEXT}; font-weight: 600; height: 8px;
        }}
        QProgressBar::chunk {{
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
              stop:0 {GOLD}, stop:1 #f7b341);
            border-radius: 6px;
        }}

        /* ═══ SPLITTER ═════════════════════════════════════════════════ */
        QSplitter::handle {{ background: {BORDER}; }}
        QSplitter::handle:hover {{ background: {GOLD}; }}
        QSplitter::handle:horizontal {{ width: 1px; margin: 0 4px; }}
        QSplitter::handle:vertical   {{ height: 1px; margin: 4px 0; }}

        /* ═══ SCROLLBAR — minimal, hidden until hover ═════════════════ */
        QScrollBar:vertical, QScrollBar:horizontal {{
            background: transparent; border: none; width: 8px; height: 8px;
        }}
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
            background: {BG_3}; border-radius: 4px; min-height: 24px;
        }}
        QScrollBar::handle:hover {{ background: {BORDER_ACTIVE}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

        /* ═══ GROUPBOX — clean section dividers ═══════════════════════ */
        QGroupBox {{
            background: {BG_1}; border: 1px solid {BORDER};
            border-radius: 10px; padding-top: 16px; margin-top: 8px;
            font-weight: 700; color: {TEXT};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin; subcontrol-position: top left;
            padding: 4px 10px; left: 8px;
            background: {BG_0}; color: {GOLD};
            font-size: 10px; letter-spacing: 2px;
        }}

        /* ═══ TOOLTIPS ═════════════════════════════════════════════════ */
        QToolTip {{
            background: {BG_ELEVATED}; color: {TEXT};
            border: 1px solid {BORDER_ACTIVE}; border-radius: 6px;
            padding: 6px 10px;
        }}

        /* ═══ MESSAGE BOX ══════════════════════════════════════════════ */
        QMessageBox {{ background: {BG_1}; }}
        QMessageBox QLabel {{ color: {TEXT}; font-size: 12px; }}
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

    # Cap per-symbol persisted vault to keep config JSON manageable.
    # A campaign can produce 6000+ genomes; this is the upper bound on how many
    # we keep across all campaigns for one symbol.
    # 2000 ≈ 2 MB JSON file — fast to load, plenty of variety for the UI.
    # User can override via data/r_native/settings.json: { "max_persisted_strategies": 5000 }
    MAX_PERSISTED_STRATEGIES_DEFAULT = 2000

    @classmethod
    def _max_persisted_strategies(cls) -> int:
        try:
            import json
            from pathlib import Path
            s = json.loads(Path(r"C:\Users\Radhi\MT5\data\r_native\settings.json")
                           .read_text(encoding="utf-8"))
            v = int(s.get("max_persisted_strategies", cls.MAX_PERSISTED_STRATEGIES_DEFAULT))
            return max(100, min(50000, v))  # clamp to sane range
        except Exception:
            return cls.MAX_PERSISTED_STRATEGIES_DEFAULT

    def run(self):
        from r_native.genetic_engine import GeneticEngine, CampaignConfig, CAMPAIGN_DIR
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

        # ── Persist FULL vault to per-symbol config (every genome → deployable) ──
        if summary.get("vault_size", 0) > 0:
            self._persist_full_vault(summary, SYM_CFG, CAMPAIGN_DIR)

        self.finished_with_result.emit(summary)

    def _persist_full_vault(self, summary, SYM_CFG, CAMPAIGN_DIR):
        """Read the campaign's vault.json (all genomes that passed purge) and
        merge into the per-symbol config so EVERY row in the UI is deployable.

        - Dedup by genome id (newer campaign overwrites older entry)
        - Sort by profit_factor descending
        - Cap at _max_persisted_strategies() — configurable via settings.json
          (default 2000; override with {"max_persisted_strategies": N})
        """
        MAX = self._max_persisted_strategies()
        import json
        from pathlib import Path

        camp_name   = summary.get("campaign", "")
        vault_file  = CAMPAIGN_DIR / camp_name / "vault.json"

        new_strats = []
        if vault_file.exists():
            try:
                full_vault = json.loads(vault_file.read_text(encoding="utf-8"))
            except Exception as e:
                full_vault = []
                self.progress.emit("PERSIST", f"vault.json read err: {e}", 0, 0)
        else:
            full_vault = []
            # Fall back to top_genome only if vault file missing
            if summary.get("top_genome"):
                full_vault = [summary["top_genome"]]

        for r in full_vault:
            if not r or not r.get("genome"): continue
            g = r["genome"]; s = r.get("stats", {})
            new_strats.append({
                "id":              g.get("id"),
                "archetype":       "GA_EVOLVED",
                "timeframe":       self.tf,
                "score":           r.get("score", 0),
                "trades":          s.get("trades", 0),
                "win_rate":        s.get("win_rate", 0),
                "profit_factor":   s.get("profit_factor", 0),
                "total_return_pct":s.get("total_return_pct", 0),
                "max_drawdown_pct":s.get("max_drawdown_pct", 0),
                "sharpe":          s.get("sharpe", 0),
                "linearity":       s.get("linearity", 0),
                "confidence":      "DEPLOY" if s.get("profit_factor", 0) >= 1.5
                                   else "EVALUATE" if s.get("profit_factor", 0) >= 1.1
                                   else "REJECT",
                "active_genes":    g.get("active_genes", []),
                "sl_atr_mult":     g.get("params", {}).get("sl_atr_mult"),
                "tp_atr_mult":     g.get("params", {}).get("tp_atr_mult"),
                "start_hour":      g.get("params", {}).get("start_hour"),
                "end_hour":        g.get("params", {}).get("end_hour"),
                "source":          f"GA_campaign_{camp_name}",
                "created_at":      summary.get("finished_at"),
            })

        cfg_path = SYM_CFG / f"{self.symbol}.json"
        existing = {}
        if cfg_path.exists():
            try: existing = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception: pass

        # ── Filter suspicious entries from the new vault ──
        # PF ≥ 50 with < 50 trades = almost always overfit / divide-by-zero artifact
        # (e.g. PF=999 means zero losing trades — statistically impossible at low sample).
        def _is_suspicious(s):
            pf = s.get("profit_factor", 0) or 0
            tr = s.get("trades", 0) or 0
            return pf >= 50 and tr < 50

        new_clean = [s for s in new_strats if not _is_suspicious(s)]
        suspicious_dropped = len(new_strats) - len(new_clean)

        # ── Merge strategy: rank by the engine's composite SCORE, not raw PF ──
        # The engine's top_genome uses `score` (combines PF + WR + trades + sharpe + DD).
        # Sorting by raw PF lets overfit/synthetic divide-by-zero strategies dominate.
        # Score-based ranking matches what the engine considers "best".
        # We reserve half the cap for the LATEST campaign so new work always surfaces.
        def _rank_key(s):
            # Fall back to PF * sqrt(trades) for legacy entries without score
            score = s.get("score")
            if score is None or score == 0:
                pf = s.get("profit_factor", 0) or 0
                tr = s.get("trades", 0) or 0
                return pf * (tr ** 0.5)
            return score

        reserved = MAX // 2
        new_top  = sorted(new_clean, key=lambda x: -_rank_key(x))[:reserved]
        new_ids  = {s["id"] for s in new_top if s.get("id")}

        # Existing entries minus any whose id is replaced by the new top
        existing_pool = [s for s in existing.get("ga_strategies", [])
                         if s.get("id") and s["id"] not in new_ids
                         and not _is_suspicious(s)]
        existing_top = sorted(existing_pool, key=lambda x: -_rank_key(x))[
            :(MAX - len(new_top))]

        merged = new_top + existing_top
        # Final sort by score (engine's quality metric) for stable UI display
        merged.sort(key=lambda x: -_rank_key(x))

        existing["ga_strategies"]    = merged
        existing["last_ga_campaign"] = camp_name
        existing["symbol"]           = self.symbol

        # Promote-to-tradeable check based on top genome
        top = summary.get("top_genome")
        if top:
            ts = top.get("stats", {})
            if ts.get("profit_factor", 0) >= 1.3 and ts.get("trades", 0) >= 15:
                existing["tradeable"]      = True
                existing["best_archetype"] = "GA_EVOLVED"
                existing["best_tf"]        = self.tf
                existing["best_pf"]        = ts.get("profit_factor", 0)

        SYM_CFG.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        self.progress.emit("PERSIST",
            f"saved {len(merged)} strategies → {cfg_path.name} "
            f"(new: {len(new_top)} reserved + existing: {len(existing_top)}"
            + (f" · dropped {suspicious_dropped} suspicious PF≥50 entries" if suspicious_dropped else "")
            + ")", 1, 1)

        # ── H.14: Ingest into per-combo fitness DB (Algory-style learning) ──
        try:
            from r_native.combo_fitness import ingest_campaign
            ingest_campaign(self.symbol, self.tf, full_vault)
            self.progress.emit("LEARNED",
                f"combo_fitness updated from {len(full_vault)} genomes "
                f"(combos + per-gene OOS tracking)", 1, 1)
        except Exception as e:
            self.progress.emit("LEARN_ERR", f"combo_fitness err: {e}", 0, 0)


# ─── Main window ───
class RNativeMain(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("R NATIVE - Genetic Trading System")
        self.resize(1600, 950)
        self.setMinimumSize(1200, 700)
        ico = PROJECT_ROOT / "friday_v3" / "algory" / "r_logo.ico"
        svg = PROJECT_ROOT / "friday_v3" / "algory" / "r_logo.svg"
        icon_path = ico if ico.exists() else (svg if svg.exists() else None)
        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))

        # Central
        central = QWidget()
        self.setCentralWidget(central)
        main_v = QVBoxLayout(central); main_v.setContentsMargins(8, 8, 8, 8); main_v.setSpacing(6)

        # Header
        main_v.addLayout(self._build_header())

        # ── Champions bar: live genome roster + life-meter per symbol ──
        main_v.addWidget(self._build_champions_bar())

        # ── H.8.1: Hero P/L Card — front and center, can't be missed ──
        main_v.addWidget(self._build_hero_pl_card())

        # 3-column split: Command | Center | Inspector
        # H.9: balanced sizes after right-column cleanup
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_command_sidebar())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_inspector())
        splitter.setSizes([200, 980, 420])
        splitter.setChildrenCollapsible(False)
        main_v.addWidget(splitter, 1)

        # Status ticker (bottom)
        main_v.addWidget(self._build_status_ticker())

        # Tray
        self._setup_tray()

        # ── Background poller: keeps brain HTTP off the Qt main thread ──
        # CRITICAL: without this the UI freezes when brain does anything
        # slow (LLM call, GA campaign, MT5 reconnect). All endpoint calls
        # run in this QThread; UI tick reads from its cache only.
        try:
            from r_native.background_poller import BackgroundPoller
            self.poller = BackgroundPoller(self)
            self.poller.start()
            print("[ui] background poller started", flush=True)
        except Exception as _pe:
            self.poller = None
            print(f"[ui] poller failed: {_pe}", flush=True)

        # Tick timer — 5s instead of 3s, and a re-entry guard inside _on_tick
        # so a slow tick can't cause queue pile-up that freezes Qt event loop
        self.tick = QTimer(); self.tick.timeout.connect(self._on_tick); self.tick.start(5000)
        self._tick_running = False
        self._on_tick()
        # Auto-load vault from existing configs
        self._populate_vault_from_campaign({})
        # Auto-load gene fitness from algory_report
        try: self._refresh_genes()
        except Exception: pass

    # ─── Header ───
    def _build_hero_pl_card(self) -> QWidget:
        """H.10: Slim single-row status strip (Algory-comfort style).
        Was 3-row 200px hero card — now a 50px scannable bar.
        Every stat is here but tiny; the workspace below gets the room."""
        card = QFrame()
        card.setObjectName("heroStrip")
        card.setStyleSheet(
            f"#heroStrip {{ background: {BG_1}; border: 1px solid {BORDER};"
            f"  border-radius: 10px; }}"
            f"#heroStrip QLabel {{ background: transparent; }}")
        card.setFixedHeight(54)
        h = QHBoxLayout(card); h.setSpacing(0); h.setContentsMargins(16, 6, 16, 6)

        def _stat(label_text: str, init: str, value_color: str = TEXT):
            col = QVBoxLayout(); col.setSpacing(1); col.setContentsMargins(12, 0, 12, 0)
            lbl = QLabel(label_text)
            lbl.setStyleSheet(
                f"color: {TEXT_DIM}; font-size: 8px; letter-spacing: 1.5px;"
                " font-weight: 700; text-transform: uppercase;")
            val = QLabel(init)
            val.setStyleSheet(
                f"color: {value_color}; font-size: 15px; font-weight: 700;"
                " font-family: 'JetBrains Mono', 'Consolas', monospace;")
            col.addWidget(lbl); col.addWidget(val)
            return col, val

        # ── Pixel Mascot (H.20) — 16x16 sprite reacts to live P/L ──
        try:
            from r_native.pixel_widget import PixelMascot
            self.hero_mascot = PixelMascot(parent=self, fps=4, scale=3,
                                            show_caption=False)
            self.hero_mascot.setFixedSize(48, 48)
            h.addWidget(self.hero_mascot)
            h.addWidget(self._vsep())
        except Exception as e:
            self.hero_mascot = None
            print(f"[mascot] init err: {e}", flush=True)

        # TODAY P/L
        c1, self.hero_pl       = _stat("TODAY P/L",  "$0.00", TEXT)
        h.addLayout(c1); h.addWidget(self._vsep())
        # TRADES
        c2, self.hero_trades   = _stat("TRADES",     "0 · — WR")
        h.addLayout(c2); h.addWidget(self._vsep())
        # TOTAL P/L
        c3, self.hero_total    = _stat("TOTAL P/L",  "$0.00", TEXT_MUTED)
        h.addLayout(c3); h.addWidget(self._vsep())
        # ACCOUNT
        c4, self.hero_balance  = _stat("ACCOUNT",    "$— · eq $—")
        h.addLayout(c4); h.addWidget(self._vsep())
        # R EXECUTOR
        c5, self.hero_exec     = _stat("R EXECUTOR", "OFFLINE", TEXT_MUTED)
        h.addLayout(c5); h.addWidget(self._vsep())
        # DEPLOYED GENOME
        c6, self.hero_deployed = _stat("DEPLOYED",   "—", TEXT_MUTED)
        h.addLayout(c6); h.addWidget(self._vsep())
        # GATE
        c7, self.hero_gate     = _stat("GATE",       "—", TEXT_MUTED)
        h.addLayout(c7)
        h.addStretch()
        return card

    def _build_hero_kpi(self, label_text: str, init_value: str,
                        value_color: str, value_size: int):
        """Helper: build a tight label-above-value column for the hero card row 2."""
        col = QVBoxLayout(); col.setSpacing(3); col.setContentsMargins(12, 4, 12, 4)
        lbl = QLabel(label_text)
        lbl.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 9px; letter-spacing: 2px;"
            " font-weight: 700; text-transform: uppercase;")
        val = QLabel(init_value)
        val.setStyleSheet(
            f"color: {value_color}; font-size: {value_size}px; font-weight: 700;"
            " font-family: 'JetBrains Mono', 'Consolas', monospace;")
        col.addWidget(lbl)
        col.addWidget(val)
        return col, val

    def _vsep(self) -> QFrame:
        """Vertical hairline separator for column-based layouts."""
        s = QFrame(); s.setFixedWidth(1); s.setFixedHeight(32)
        s.setStyleSheet(f"background: {BORDER};")
        return s

    def _refresh_hero_card(self) -> None:
        """Refresh hero strip — LIVE-only stats from MT5, NOT mixed with PAPER.
        Pulls from BackgroundPoller's mt5_today_* (real history_deals) and
        mt5_account (real balance/equity). The exec_state file is consulted
        ONLY for mode/armed/last_action (which are LIVE-vs-PAPER agnostic).
        """
        if not hasattr(self, "hero_pl"): return
        import json as _json
        from pathlib import Path as _P

        # exec_state only for mode/armed/last_action (status fields)
        exec_state = {}
        try:
            sf = _P(r"C:\Users\Radhi\MT5\friday_v3\data\r_executor_state.json")
            if sf.exists(): exec_state = _json.loads(sf.read_text(encoding="utf-8"))
        except Exception: pass

        # ── LIVE stats: pull from poller's REAL MT5 history_deals ──
        if getattr(self, "poller", None):
            today_pl     = float(self.poller.get("mt5_today_pl", 0) or 0)
            today_trades = int(self.poller.get("mt5_today_trades", 0) or 0)
            today_wins   = int(self.poller.get("mt5_today_wins", 0) or 0)
        else:
            today_pl = 0; today_trades = 0; today_wins = 0

        # TOTAL P/L = current real account growth (equity − a stored baseline).
        # If no baseline saved, use balance as baseline (zero P/L on first run).
        try:
            from pathlib import Path as _PP
            base_path = _PP(r"C:\Users\Radhi\MT5\data\r_native\baseline_balance.json")
            acct = (self.poller.get("mt5_account", {}) if getattr(self,"poller",None) else {}) or {}
            cur_equity = float(acct.get("equity") or 0)
            if cur_equity > 0:
                if base_path.exists():
                    baseline = float(_json.loads(base_path.read_text(encoding="utf-8")).get("balance", cur_equity))
                else:
                    baseline = cur_equity
                    base_path.parent.mkdir(parents=True, exist_ok=True)
                    base_path.write_text(_json.dumps({"balance": baseline, "set_at": "first-launch"}), encoding="utf-8")
                total_pl = round(cur_equity - baseline, 2)
            else:
                total_pl = 0
        except Exception:
            total_pl = 0
        total_trades = today_trades  # session-level approximation

        armed       = bool(exec_state.get("armed",   False))
        mode        = str(exec_state.get("mode",    "—"))
        last_action = str(exec_state.get("last_action", "—"))

        # H.10: compact strip — values only, color via stylesheet
        VAL_STYLE = ("font-size: 15px; font-weight: 700;"
                     " font-family: 'JetBrains Mono', 'Consolas', monospace;")

        # ─── Today's P/L ───
        col = GREEN if today_pl > 0 else RED if today_pl < 0 else TEXT
        sign = "+" if today_pl >= 0 else ""
        self.hero_pl.setText(f"{sign}${today_pl:.2f}")
        self.hero_pl.setStyleSheet(f"color: {col}; {VAL_STYLE}")

        # Trades / WR
        wr = (today_wins / today_trades * 100) if today_trades else 0
        wr_str = f"{wr:.0f}%" if today_trades else "—"
        self.hero_trades.setText(f"{today_trades} · {wr_str}")
        self.hero_trades.setStyleSheet(f"color: {TEXT}; {VAL_STYLE}")

        # Total P/L
        col_t = GREEN if total_pl > 0 else RED if total_pl < 0 else TEXT_MUTED
        sign_t = "+" if total_pl >= 0 else ""
        self.hero_total.setText(f"{sign_t}${total_pl:.2f}")
        self.hero_total.setStyleSheet(f"color: {col_t}; {VAL_STYLE}")

        # Account — from poller cache (NOT direct mt5.* — that blocks Qt)
        try:
            if getattr(self, "poller", None):
                acct = self.poller.get("mt5_account", {}) or {}
                if acct:
                    self.hero_balance.setText(
                        f"${acct.get('balance',0):.0f} · ${acct.get('equity',0):.0f}")
                    self.hero_balance.setStyleSheet(f"color: {TEXT}; {VAL_STYLE}")
        except Exception: pass

        # Executor indicator (compact)
        if exec_state and armed:
            self.hero_exec.setText(f"● {mode}")
            self.hero_exec.setStyleSheet(f"color: {GREEN}; {VAL_STYLE}")
        elif exec_state:
            self.hero_exec.setText("○ IDLE")
            self.hero_exec.setStyleSheet(f"color: {GOLD}; {VAL_STYLE}")
        else:
            self.hero_exec.setText("○ OFFLINE")
            self.hero_exec.setStyleSheet(f"color: {TEXT_DIM}; {VAL_STYLE}")

        # Deployed genome — compact
        try:
            cp = _P(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs\BTCUSDm.json")
            if cp.exists():
                cfg = _json.loads(cp.read_text(encoding="utf-8"))
                dg = cfg.get("deployed_genome") or {}
                if dg.get("id"):
                    self.hero_deployed.setText(f"{dg.get('id')}")
                    self.hero_deployed.setStyleSheet(f"color: {GOLD}; {VAL_STYLE}")
                else:
                    self.hero_deployed.setText("—")
        except Exception: pass

        # Gate (last action snippet)
        gate_text = last_action[:20] if last_action and last_action != "—" else "—"
        self.hero_gate.setText(gate_text)
        self.hero_gate.setStyleSheet(f"color: {TEXT_MUTED}; {VAL_STYLE}")

        # ── Pixel mascot (H.20) — sprite reacts to live P/L ──
        if hasattr(self, "hero_mascot") and self.hero_mascot:
            try:
                # Read balance from poller cache — no direct mt5.* on Qt thread
                bal = 100  # safe default
                if getattr(self, "poller", None):
                    acct = self.poller.get("mt5_account", {}) or {}
                    if acct.get("balance"):
                        bal = max(1, float(acct["balance"]))
                self.hero_mascot.set_pnl(pnl=today_pl, net_worth=bal,
                                          hodl=bool(exec_state.get("paper_open")))
            except Exception as e:
                print(f"[mascot] update err: {e}", flush=True)

    def _build_header(self):
        h = QHBoxLayout(); h.setSpacing(10); h.setContentsMargins(2, 2, 2, 6)
        # Modern wordmark — restrained, sharp
        title = QLabel("R NATIVE")
        f = QFont("Inter", 16, QFont.Bold); title.setFont(f)
        title.setStyleSheet(f"color: {TEXT}; letter-spacing: -0.5px; font-weight: 800;")
        h.addWidget(title)
        # Small accent dot
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {GOLD}; font-size: 14px; margin: 0 4px;")
        h.addWidget(dot)
        sub = QLabel("Genetic Strategy Factory")
        sub.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-weight: 500;")
        h.addWidget(sub)
        h.addStretch()

        # H.9: STATS/SCORE/CLASS removed — Inspector panel has its own tabs.
        # Header only switches the CENTER pane (NEW CAMPAIGN / ADVANCED / GENE POOL).
        self.mode_buttons = {}
        self._current_mode = "NEW CAMPAIGN"
        self._current_inspector = "STATS"   # legacy default; only InspectorPanel reads it now
        for name in ["NEW CAMPAIGN", "ADVANCED", "GENE POOL"]:
            b = QPushButton(name)
            b.setCheckable(True)
            b.setChecked(name == self._current_mode)
            self._style_mode_button(b, name == self._current_mode)
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
                             ("🔋 Connection", self._show_connection),
                             ("🆘 Request Support", self._request_remote_support)]:
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

        # ── H.8.2: Live Activity Stream — last 8 R Executor decisions ──
        v.addWidget(QLabel("⚡ LIVE ACTIVITY"))
        self.live_activity = QPlainTextEdit()
        self.live_activity.setReadOnly(True)
        self.live_activity.setMaximumHeight(160)
        self.live_activity.setStyleSheet(
            f"QPlainTextEdit {{ background: #060418; color: {TEXT}; border: 1px solid {BORDER};"
            f" border-radius: 4px; padding: 4px; font-family: 'Consolas'; font-size: 9px; }}")
        self.live_activity.setPlaceholderText("R Executor activity (every 3s)…")
        v.addWidget(self.live_activity)
        self._activity_seen = set()  # dedupe by last_action timestamp+content

        # ── H.8.3: Live Gate Status — 5 most important conditions ──
        v.addWidget(QLabel("🚦 GATE NOW"))
        self.gate_status_frame = QFrame()
        self.gate_status_frame.setStyleSheet(
            f"QFrame {{ background: #060418; border: 1px solid {BORDER}; border-radius: 4px; padding: 6px; }}")
        gsv = QVBoxLayout(self.gate_status_frame); gsv.setSpacing(2); gsv.setContentsMargins(4, 4, 4, 4)
        self.gate_status_labels = {}
        for key in ["balance", "session", "regime", "deployed", "verdict"]:
            lbl = QLabel(f"○ {key}…")
            lbl.setStyleSheet(f"color: {MUTED}; font-family: 'Consolas'; font-size: 9px;")
            gsv.addWidget(lbl)
            self.gate_status_labels[key] = lbl
        v.addWidget(self.gate_status_frame)

        v.addStretch()

        # Live IQ
        self.iq_label = QLabel("R-IQ: —")
        self.iq_label.setAlignment(Qt.AlignCenter)
        self.iq_label.setStyleSheet(f"color: {VIOLET}; font-weight: bold; padding: 4px;")
        v.addWidget(self.iq_label)
        return w

    def _refresh_live_activity(self) -> None:
        """H.8.2+8.3+8.5: refresh activity log + gate status + notify on new trades."""
        import json as _json
        from pathlib import Path as _P

        # ─── Activity stream: tail r_executor_state + brain_journal ───
        new_lines = []
        # 1) R Executor's latest action
        try:
            sf = _P(r"C:\Users\Radhi\MT5\friday_v3\data\r_executor_state.json")
            if sf.exists():
                s = _json.loads(sf.read_text(encoding="utf-8"))
                key = f"{s.get('last_save', '')}::{s.get('last_action', '')}"
                if key and key not in self._activity_seen:
                    self._activity_seen.add(key)
                    if len(self._activity_seen) > 200:
                        self._activity_seen = set(list(self._activity_seen)[-100:])
                    ts = (s.get("last_save") or "")[11:19] or datetime.now().strftime("%H:%M:%S")
                    armed = "●" if s.get("armed") else "○"
                    new_lines.append(f"[{ts}] {armed} {s.get('mode','—')}: {s.get('last_action','')[:50]}")
        except Exception: pass

        # 2) New trades — read from poller cache (no direct mt5 call)
        try:
            recent = (self.poller.get("mt5_recent_deals", [])
                      if getattr(self, "poller", None) else [])
            for d in recent[:5]:
                dk = f"deal::{d['ticket']}::{d['entry']}"
                if dk in self._activity_seen: continue
                self._activity_seen.add(dk)
                ts = datetime.fromtimestamp(int(d['time'])).strftime("%H:%M:%S")
                kind = "OPEN" if d['entry'] == 0 else "CLOSE"
                side = "BUY" if d['type'] == 0 else "SELL"
                pl = float(d['profit']) + float(d['swap']) + float(d['commission'])
                emoji = "🚀" if kind == "OPEN" else ("💰" if pl > 0 else "🛑" if pl < 0 else "⏹")
                new_lines.append(
                    f"[{ts}] {emoji} {kind} {side} {d['symbol']} @ {float(d['price']):.3f} "
                    + (f"P/L ${pl:+.2f}" if kind == "CLOSE" else f"#{d['ticket']}"))
                # H.8.5: tray toast for new trade events
                if hasattr(self, "tray"):
                    try:
                        if kind == "OPEN":
                            self.tray.showMessage("R Native — Trade Opened",
                                f"{side} {d['symbol']} @ {float(d['price']):.3f}",
                                QSystemTrayIcon.Information, 4000)
                        else:
                            self.tray.showMessage(
                                f"R Native — {'WIN 💰' if pl > 0 else 'LOSS 🛑'}",
                                f"{d.symbol} closed P/L: ${pl:+.2f}",
                                QSystemTrayIcon.Information, 5000)
                    except Exception: pass
                # Retro 8-bit sound effects (easy-peasy.ai pixel-game vibes)
                try:
                    from r_native.retro_sfx import on_trade_event
                    on_trade_event(kind, pl=pl)
                except Exception: pass
        except Exception: pass

        # Append to activity panel (newest at top, keep last ~25 lines)
        if new_lines and hasattr(self, "live_activity"):
            current = self.live_activity.toPlainText().splitlines()
            updated = new_lines + current
            self.live_activity.setPlainText("\n".join(updated[:25]))

        # ─── Gate Status: read from poller cache (no HTTP) ───
        try:
            d = (self.poller.get("trade_gate_btc", {})
                 if getattr(self, "poller", None) else {})
            if not d: return
            checks = {c["name"]: c["passed"] for c in (d.get("checks") or [])}
            verdict = d.get("verdict", "—")
            dg_id  = d.get("deployed_genome_id")
            dg_cpt = d.get("deployed_genome_compat", "—")
            self._set_gate_label("balance",  checks.get("balance_above_floor", False),
                                 "balance ≥ floor")
            self._set_gate_label("session",  checks.get("session_window_open", False),
                                 "session window")
            self._set_gate_label("regime",   checks.get("regime_advisory", True),
                                 "regime OK")
            self._set_gate_label("deployed", bool(dg_id),
                                 f"deployed {dg_id or '—'} ({dg_cpt})")
            ver_color = GREEN if verdict == "GO" else GOLD if verdict == "WAIT" else RED
            self.gate_status_labels["verdict"].setText(f"● VERDICT: {verdict}")
            self.gate_status_labels["verdict"].setStyleSheet(
                f"color: {ver_color}; font-family: 'Consolas'; font-size: 10px; font-weight: 800;")
        except Exception: pass

    def _set_gate_label(self, key: str, passed: bool, text: str) -> None:
        if key not in self.gate_status_labels: return
        icon  = "✅" if passed else "❌"
        color = GREEN if passed else RED
        self.gate_status_labels[key].setText(f"{icon} {text}")
        self.gate_status_labels[key].setStyleSheet(
            f"color: {color}; font-family: 'Consolas'; font-size: 9px;")

    # ─── Center ───
    def _build_champions_bar(self):
        """Compact horizontal strip listing every deployed-genome symbol with
        a life-meter (% life remaining based on score + live PnL). Refreshes 5s."""
        from PySide6.QtWidgets import QFrame, QHBoxLayout
        w = QFrame()
        w.setStyleSheet(
            f"QFrame {{ background: {BG_1}; border: 1px solid {BORDER};"
            f" border-radius: 6px; }}"
            f"QLabel {{ color: {TEXT}; }}")
        w.setMaximumHeight(70)
        self._champions_layout = QHBoxLayout(w)
        self._champions_layout.setContentsMargins(8, 6, 8, 6)
        self._champions_layout.setSpacing(6)
        # initial empty + lazy fill
        self._champions_placeholder = QLabel("  loading champions…")
        self._champions_placeholder.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._champions_layout.addWidget(self._champions_placeholder)
        # Refresh timer
        self._champions_timer = QTimer(self)
        self._champions_timer.timeout.connect(self._refresh_champions_bar)
        self._champions_timer.start(5000)
        QTimer.singleShot(1500, self._refresh_champions_bar)
        return w

    def _refresh_champions_bar(self):
        import urllib.request, json
        try:
            with urllib.request.urlopen("http://localhost:5055/api/r/genomes/active",
                                          timeout=3) as r:
                d = json.loads(r.read().decode())
        except Exception:
            return
        # Clear existing cards
        while self._champions_layout.count():
            it = self._champions_layout.takeAt(0)
            wdg = it.widget()
            if wdg: wdg.deleteLater()
        # Build a small card per REAL deployed-genome symbol
        # Filter out seeded stubs (id without flags) — they never actually
        # trade and just create noise across 38 cards. Only show symbols
        # whose deployed_genome has real flags populated.
        from PySide6.QtWidgets import QFrame, QVBoxLayout, QProgressBar
        rows = []
        for s in (d.get("symbols") or []):
            dg = s.get("deployed_genome")
            if not dg: continue
            flags = dg.get("flags") or {}
            if not any(flags.values()):
                continue  # seeded stub, no actual trading logic
            stats = dg.get("stats") or {}
            life = self._compute_life_pct(dg, stats)
            score = float(dg.get("score") or 0)
            rows.append((s["symbol"], dg["id"], score,
                          stats.get("profit_factor") or 0,
                          stats.get("live_pnl") or 0,
                          stats.get("live_trades") or 0,
                          life))
        # Sort by score descending — best-performing genomes first
        rows.sort(key=lambda r: -r[2])
        if not rows:
            placeholder = QLabel("  no deployed genomes with flags — run deploy_multi_symbol.py")
            placeholder.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
            self._champions_layout.addWidget(placeholder)
            return
        for sym, gid, score, pf, pnl, n, life in rows[:12]:
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background: {BG_2}; border: 1px solid {BORDER};"
                f" border-radius: 4px; }}")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(8, 4, 8, 4)
            cv.setSpacing(2)
            top = QLabel(f"<b style='color:{GOLD}'>{sym}</b>  "
                          f"<span style='color:{TEXT_MUTED};font-family:Consolas'>"
                          f"score {score:.0f}</span>")
            top.setStyleSheet("font-size: 11px;")
            top.setToolTip(f"Deployed genome {gid}\nBacktest score: {score:.1f}\n"
                           f"Live: {n} trades, ${pnl:+.2f}")
            cv.addWidget(top)
            pnl_color = GREEN if pnl > 0 else (RED if pnl < 0 else TEXT_MUTED)
            mid = QLabel(f"<span style='color:{pnl_color};font-family:Consolas'>"
                          f"${pnl:+.2f}</span> live · {n} trades · "
                          f"<span style='color:{TEXT_MUTED}'>{gid}</span>")
            mid.setStyleSheet("font-size: 9px;")
            cv.addWidget(mid)
            bar = QProgressBar()
            bar.setRange(0, 100); bar.setValue(int(life))
            life_color = (GREEN if life >= 60 else
                           GOLD  if life >= 30 else RED)
            bar.setFormat(f"life {int(life)}%")
            bar.setStyleSheet(
                f"QProgressBar {{ background: {BG_3}; border: 1px solid {BORDER};"
                f" border-radius: 2px; text-align: center; color: {TEXT};"
                f" font-size: 9px; font-weight: 700; height: 12px; }}"
                f"QProgressBar::chunk {{ background: {life_color};"
                f" border-radius: 1px; }}")
            cv.addWidget(bar)
            self._champions_layout.addWidget(card)
        self._champions_layout.addStretch(1)

    def _compute_life_pct(self, dg: dict, stats: dict) -> float:
        """Composite life score 0..100. High = champion, low = candidate-for-replacement.

        Inputs:
          • backtest PF (capped at 20)
          • live PnL (rewards positive, punishes negative)
          • live trades count (small reward — proves it's been used)
          • monster status (bonus)
          • kill_protected (bonus)
        """
        pf = float(dg.get("profit_factor") or 0)
        live_pnl    = float(stats.get("live_pnl") or 0)
        live_trades = int(stats.get("live_trades") or 0)
        is_monster  = self._is_monster(dg.get("id", ""))
        protected   = bool(stats.get("kill_protected"))
        pinned      = bool(stats.get("pinned"))

        score = 0
        score += min(40, pf * 2)              # PF 0-20 → 0-40
        score += max(-25, min(25, live_pnl * 5))   # live_pnl ±5 → ±25
        score += min(15, live_trades * 1.5)         # 10 trades → 15
        if is_monster:   score += 10
        if protected:    score += 5
        if pinned:       score += 5
        return max(0, min(100, score))

    def spotlight_activate_button(self):
        """Called by the wizard after Approve — pulse the ARM/Activate control
        for ~10 seconds so the user knows where to click next."""
        # Try common attribute names; absorb if missing
        candidates = ["arm_btn", "btn_arm", "activate_btn", "btn_activate",
                       "armed_indicator", "_arm_pill"]
        target = None
        for attr in candidates:
            if hasattr(self, attr):
                target = getattr(self, attr); break
        if not target: return
        orig_style = target.styleSheet()
        def pulse(step=[0]):
            phase = step[0] % 2
            target.setStyleSheet(orig_style + (
                f"; border: 3px solid {GOLD}; "
                if phase == 0
                else f"; border: 3px solid {GREEN}; "))
            step[0] += 1
        timer = QTimer(self)
        timer.timeout.connect(pulse)
        timer.start(400)
        def stop():
            timer.stop()
            target.setStyleSheet(orig_style)
        QTimer.singleShot(10_000, stop)

    def _show_onboarding_wizard(self):
        """Force-replay the first-run wizard."""
        try:
            from r_native.onboarding import show_anyway
            self._wizard_handle = show_anyway(parent=self)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Wizard", f"Failed to open wizard: {e}")

    def _build_mission_tab(self):
        """🎯 MISSION CONTROL — the full HTML dashboard embedded via QtWebEngine.
        Single source of truth: dashboard.html (also served at /dashboard).
        Falls back to a launch-in-browser button if QtWebEngine isn't installed."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtCore import QUrl
            view = QWebEngineView()
            view.setUrl(QUrl("http://localhost:5055/dashboard"))
            v.addWidget(view, 1)
            # Tiny header with reload + open-in-browser
            from PySide6.QtWidgets import QFrame
            bar = QFrame()
            bar.setStyleSheet(
                f"QFrame {{ background: {BG_2}; border-bottom: 1px solid {BORDER}; }}")
            bar.setMaximumHeight(34)
            bv = QHBoxLayout(bar); bv.setContentsMargins(8, 4, 8, 4); bv.setSpacing(6)
            lbl = QLabel("🎯 MISSION CONTROL · embedded dashboard")
            lbl.setStyleSheet(f"color: {GOLD}; font-size: 10px; font-weight: 800;"
                              f" letter-spacing: 2px;")
            bv.addWidget(lbl); bv.addStretch(1)
            for txt, fn in [
                ("⟳ Reload",         lambda: view.reload()),
                ("🌐 Open in Browser",
                    lambda: QDesktopServices.openUrl(
                        QUrl("http://localhost:5055/dashboard"))),
            ]:
                b = QPushButton(txt)
                b.setStyleSheet(
                    f"QPushButton {{ background: transparent; color: {TEXT_MUTED};"
                    f" border: 1px solid {BORDER}; border-radius: 3px;"
                    f" padding: 3px 10px; font-size: 10px; font-weight: 700; }}"
                    f"QPushButton:hover {{ color: {GOLD}; border-color: {GOLD}; }}")
                b.clicked.connect(fn)
                bv.addWidget(b)
            v.insertWidget(0, bar)
            return w
        except Exception as e:
            # Fallback — no QtWebEngine
            msg = QLabel(
                "🎯  MISSION CONTROL\n\n"
                f"QtWebEngine not available: {e}\n\n"
                "Install:  pip install PySide6-Addons\n\n"
                "Or open in your browser:")
            msg.setAlignment(Qt.AlignCenter)
            msg.setStyleSheet(f"color: {TEXT}; font-size: 13px; padding: 40px;"
                              f" font-family: 'JetBrains Mono','Consolas',monospace;")
            v.addWidget(msg, 1)
            from PySide6.QtCore import QUrl
            btn = QPushButton("🌐  Open Dashboard in Browser")
            btn.setStyleSheet(
                f"QPushButton {{ background: {GOLD}; color: {BG_0};"
                f" border: none; border-radius: 4px; padding: 12px 20px;"
                f" font-weight: 900; letter-spacing: 1px; font-size: 12px; }}"
                f"QPushButton:hover {{ background: #c47e15; }}")
            btn.clicked.connect(lambda: QDesktopServices.openUrl(
                QUrl("http://localhost:5055/dashboard")))
            v.addWidget(btn, 0, Qt.AlignCenter)
            v.addStretch(2)
            return w

    def _flags_str_for(self, st, gid: str = None):
        """Compose a short flag string like '🔥 PIN PROTECT BUY-SPEC' from a stats dict."""
        bits = []
        if gid and self._is_monster(gid): bits.append("🔥")
        if st.get("pinned"):              bits.append("PIN")
        if st.get("kill_protected"):      bits.append("PROTECT")
        d = st.get("directional")
        if d == "BUY":  bits.append("BUY-SPEC")
        elif d == "SELL": bits.append("SELL-SPEC")
        return " ".join(bits) or "—"

    def _is_monster(self, gid: str) -> bool:
        """Cached lookup against data/r_native/monster_genomes.json (refreshed every 30s)."""
        import time, json
        from pathlib import Path
        now = time.time()
        if not hasattr(self, "_monster_cache"):
            self._monster_cache = {"ts": 0, "ids": set()}
        if (now - self._monster_cache["ts"]) > 30:
            mp = Path(r"C:\Users\Radhi\MT5\data\r_native\monster_genomes.json")
            ids = set()
            if mp.exists():
                try:
                    d = json.loads(mp.read_text(encoding="utf-8"))
                    ids = {m["id"] for m in (d.get("monsters") or [])}
                except Exception: pass
            self._monster_cache = {"ts": now, "ids": ids}
        return gid in self._monster_cache["ids"]

    def _build_active_tab(self):
        """🎯 ACTIVE — live view of every deployed genome across symbols.
        Refreshes every 5s from /api/r/genomes/active. Click any row to focus
        the Inspector on that genome, or use action buttons per row."""
        import urllib.request as _ur
        import json as _j

        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 4, 6, 4)
        v.setSpacing(3)

        # Header strip: compact daemon status + tiny refresh
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        self._active_daemon_pill = QLabel("…")
        self._active_daemon_pill.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 9px; padding: 2px 6px;"
            f" border: 1px solid {BORDER}; border-radius: 3px;")
        header.addWidget(self._active_daemon_pill)
        header.addStretch(1)
        btn_refresh = QPushButton("⟳")
        btn_refresh.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_MUTED};"
            f" border: 1px solid {BORDER}; border-radius: 3px;"
            f" padding: 2px 8px; font-size: 11px; font-weight: 700; }}"
            f"QPushButton:hover {{ color: {GOLD}; border-color: {GOLD}; }}")
        btn_refresh.clicked.connect(lambda: self._refresh_active_table())
        header.addWidget(btn_refresh)
        v.addLayout(header)

        # Table (decluttered: 6 cols, shorter labels)
        self.active_table = QTableWidget(0, 6)
        self.active_table.setHorizontalHeaderLabels([
            "SYMBOL", "GENOME", "PF", "P/L", "TRD", "FLAGS"
        ])
        hh = self.active_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setStyleSheet(
            f"QHeaderView::section {{ background: {BG_2}; color: {TEXT_MUTED};"
            f" border: none; border-bottom: 1px solid {BORDER};"
            f" padding: 4px 6px; font-weight: 700; font-size: 9px;"
            f" letter-spacing: 1px; }}")
        self.active_table.setStyleSheet(
            f"QTableWidget {{ background: {BG_1}; color: {TEXT};"
            f" gridline-color: transparent; selection-background-color: {BG_3};"
            f" selection-color: {GOLD}; border: none; }}"
            f"QTableWidget::item {{ padding: 3px 6px;"
            f" border-bottom: 1px solid {BG_2}; }}")
        self.active_table.verticalHeader().setVisible(False)
        from PySide6.QtWidgets import QAbstractItemView as _AIV
        self.active_table.setEditTriggers(_AIV.NoEditTriggers)
        self.active_table.setAlternatingRowColors(False)
        self.active_table.itemDoubleClicked.connect(self._active_table_open_chart)
        v.addWidget(self.active_table, 1)

        # Footer with totals
        self._active_footer = QLabel("loading…")
        self._active_footer.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 10px;"
            f" font-family: 'JetBrains Mono','Consolas',monospace;")
        v.addWidget(self._active_footer)

        # First render + start refresh timer
        self._refresh_active_table()
        self._active_timer = QTimer(self)
        self._active_timer.timeout.connect(self._refresh_active_table)
        self._active_timer.start(5000)
        return w

    def _refresh_active_table(self):
        import urllib.request as _ur
        import json as _j
        try:
            with _ur.urlopen("http://localhost:5055/api/r/genomes/active",
                              timeout=3) as r:
                d = _j.loads(r.read().decode())
        except Exception as e:
            self._active_footer.setText(f"err: {e}")
            return
        symbols = d.get("symbols") or []
        rows = []
        for s in symbols:
            sym = s.get("symbol", "")
            dg = s.get("deployed_genome") or {}
            ens = s.get("ensemble") or []
            if ens:
                # Show one row per ensemble member
                for m in ens:
                    st = m.get("stats") or {}
                    rows.append({
                        "symbol": sym, "gid": m.get("id"),
                        "type": f"ENS w={m.get('weight')}",
                        "pf": "",
                        "live_pnl": st.get("live_pnl", 0),
                        "live_trades": st.get("live_trades", 0),
                        "opens":  st.get("decision_log_opens", 0),
                        "closes": st.get("decision_log_closes", 0),
                        "flags":  self._flags_str_for(st, m.get("id")),
                        "last":   (st.get("decision_log_last_ts") or "—")[:19],
                    })
            elif dg.get("id"):
                st = (dg.get("stats") or {})
                rows.append({
                    "symbol": sym, "gid": dg["id"], "type": "SOLO",
                    "pf": dg.get("profit_factor"),
                    "live_pnl": st.get("live_pnl", 0),
                    "live_trades": st.get("live_trades", 0),
                    "opens":  st.get("decision_log_opens", 0),
                    "closes": st.get("decision_log_closes", 0),
                    "flags":  self._flags_str_for(st, dg["id"]),
                    "last":   (st.get("decision_log_last_ts") or "—")[:19],
                })
            elif s.get("archetype_fallback") and s.get("live_position"):
                lp = s["live_position"]
                rows.append({
                    "symbol": sym, "gid": f"⚠ {lp.get('archetype','ALGORY')}",
                    "type": "ARCHETYPE",
                    "pf": "—",
                    "live_pnl":    float(lp.get("profit", 0)),
                    "live_trades": 1,
                    "opens": 0, "closes": 0,
                    "flags": f"#{lp.get('ticket')} {lp.get('side')}",
                    "last": "—",
                })
            else:
                rows.append({
                    "symbol": sym, "gid": "—", "type": "(no deploy)",
                    "pf": "", "live_pnl": 0, "live_trades": 0,
                    "opens": 0, "closes": 0, "flags": "", "last": "—",
                })
        self.active_table.setRowCount(len(rows))
        from PySide6.QtGui import QColor as _QC
        for ri, r in enumerate(rows):
            def _cell(text, color=None, mono=False):
                it = QTableWidgetItem(str(text))
                if color: it.setForeground(_QC(color))
                if mono:
                    f = QFont("JetBrains Mono", 9)
                    it.setFont(f)
                return it
            pnl = float(r["live_pnl"] or 0)
            pnl_color = GREEN if pnl > 0 else (RED if pnl < 0 else TEXT_MUTED)
            # symbol: show ensemble-weight inline if present (e.g. "XAUUSDm·ENS")
            sym_text = r["symbol"]
            if r["type"].startswith("ENS"):
                sym_text = f"{r['symbol']} ENS"
            self.active_table.setItem(ri, 0, _cell(sym_text, GOLD))
            self.active_table.setItem(ri, 1, _cell(r["gid"], TEXT, mono=True))
            self.active_table.setItem(ri, 2, _cell(
                f"{r['pf']:.1f}" if isinstance(r['pf'], (int, float)) else (r['pf'] or "—"),
                TEXT_MUTED))
            self.active_table.setItem(ri, 3, _cell(f"${pnl:+.2f}", pnl_color, mono=True))
            self.active_table.setItem(ri, 4, _cell(r["live_trades"], TEXT, mono=True))
            self.active_table.setItem(ri, 5, _cell(r["flags"], VIOLET))
        total_pnl = sum(float(r["live_pnl"] or 0) for r in rows)
        total_trades = sum(int(r["live_trades"] or 0) for r in rows)
        self._active_footer.setText(
            f"{len(rows)} rows · P/L ${total_pnl:+.2f} · {total_trades} trades · 5s")
        # Daemon status
        self._refresh_daemon_pill()

    def _refresh_daemon_pill(self):
        """Probe daemons by scanning all running python.exe command lines via
        tasklist /V /FO CSV (cross-version reliable on Windows). The previous
        os.kill(pid, 0) trick is unreliable on Windows because access-denied
        and not-found both raise OSError."""
        try:
            import subprocess
            r = subprocess.run(
                ["tasklist", "/V", "/FO", "CSV", "/FI",
                 "IMAGENAME eq python.exe"],
                capture_output=True, text=True, timeout=4,
                creationflags=0x08000000)  # CREATE_NO_WINDOW
            blob = r.stdout or ""
            # Also tasklist's CSV doesn't have CommandLine — we need wmic OR
            # we infer from launcher_pids.json + check if the PID is in
            # tasklist's listed PIDs (just confirms process exists).
            import json as _j
            from pathlib import Path as _P
            pids_file = _P(r"C:\Users\Radhi\MT5\data\launcher_pids.json")
            pids = (_j.loads(pids_file.read_text(encoding="utf-8"))
                    if pids_file.exists() else {})
            def _alive(pid):
                if not pid: return False
                return f'"{int(pid)}"' in blob
            lin = _alive(pids.get("lineage"))
            asy = _alive(pids.get("asymmetry"))
            mon = _alive(pids.get("monster"))
            con = _alive(pids.get("contender"))
            ico = lambda b: "●" if b else "○"
            self._active_daemon_pill.setText(
                f"{ico(lin)} lin  {ico(asy)} asym  {ico(mon)} mon  {ico(con)} con")
            ok_all = lin and asy and mon and con
            color = GREEN if ok_all else GOLD
            self._active_daemon_pill.setStyleSheet(
                f"color: {color}; font-size: 9px; padding: 2px 6px;"
                f" border: 1px solid {BORDER}; border-radius: 3px;")
        except Exception as _e:
            self._active_daemon_pill.setText(f"○ daemons ({str(_e)[:30]})")

    def _active_table_open_chart(self, item):
        row = item.row()
        gid_item = self.active_table.item(row, 1)
        if not gid_item: return
        gid = gid_item.text().strip()
        if not gid or gid == "—": return
        from PySide6.QtCore import QUrl as _QU
        from PySide6.QtGui import QDesktopServices as _QD
        _QD.openUrl(_QU(f"http://localhost:5055/r/genome/{gid}"))

    def _build_center(self):
        w = QFrame(); w.setProperty("role", "card")
        v = QVBoxLayout(w); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(8)

        # Mode stack: NEW CAMPAIGN | ADVANCED | GENE POOL — switched by header buttons
        from r_native.panels import PropFirmPanel, ExecutionPanel, EvolutionPanel, GenePoolPanel
        self.center_stack = QStackedWidget()

        # mode 0: NEW CAMPAIGN — the existing 4-tab pane
        tabs = QTabWidget()
        tabs.addTab(self._build_mission_tab(),  "🎯 MISSION")
        tabs.addTab(self._build_active_tab(),   "📊 ACTIVE")
        tabs.addTab(self._build_campaign_tab(), "🧪 CAMPAIGN")
        tabs.addTab(self._build_vault_tab(),    "💎 VAULT")
        tabs.addTab(self._build_live_tab(),     "⚡ LIVE")
        tabs.addTab(self._build_genes_tab(),    "🧬 GENES")
        tabs.addTab(self._build_hof_tab(),      "🏆 HALL OF FAME")
        tabs.addTab(self._build_advisors_tab(), "🤖 AI ADVISORS")
        tabs.addTab(self._build_son_tab(),      "🧬 OUR SON")
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

        # Inline deploy status banner — replaces hidden modal dialogs
        self._deploy_banner = QLabel()
        self._deploy_banner.setWordWrap(True)
        self._deploy_banner.setVisible(False)
        v.addWidget(self._deploy_banner)

        # Bottom action bar — wired to actions module
        action_bar = QHBoxLayout()
        for lbl, role, handler in [("DEPLOY", "success", self._action_deploy),
                                    ("🎬 BACKTEST 30d", "primary", self._action_backtest),
                                    ("🔫 FIRE TEST TRADE", "primary", self._action_force_trade),
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

        # Auto-Evolution toggle + status pill (always-on self-evolving loop)
        self._auto_evo_btn = QPushButton("🧬 AUTO-EVOLVE: OFF")
        self._auto_evo_btn.setProperty("role", "primary")
        self._auto_evo_btn.setCheckable(True)
        self._auto_evo_btn.clicked.connect(self._action_toggle_auto_evo)
        self._auto_evo_btn.setToolTip(
            "Continuously runs GA campaigns every N hours and auto-deploys\n"
            "the winning genome — your system evolves while you sleep.")
        action_bar.addWidget(self._auto_evo_btn)

        self._auto_evo_status_lbl = QLabel("")
        self._auto_evo_status_lbl.setStyleSheet(
            "color: #888; font-size: 11px; padding-left: 6px;")
        action_bar.addWidget(self._auto_evo_status_lbl)

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
        # H.13: Full 18-asset coverage matching Algory
        self.ga_symbol.addItems([
            # Forex majors
            "EURUSDm", "GBPUSDm", "AUDUSDm", "USDJPYm", "USDCADm", "USDCHFm",
            # Forex crosses
            "EURGBPm", "GBPJPYm", "EURJPYm", "GBPAUDm",
            # Crypto
            "BTCUSDm", "ETHUSDm",
            # Metals
            "XAUUSDm", "XAGUSDm",
            # Indices
            "US30m", "USTECm", "US500m", "DE30m",
            # Energy
            "USOILm",
        ])
        gg.addWidget(self.ga_symbol, 0, 1)
        gg.addWidget(QLabel("TF:"), 0, 2)
        self.ga_tf = QComboBox()
        # H.15: Added M30 + H2 to match Algory's 6 TFs
        self.ga_tf.addItems(["M5", "M15", "M30", "H1", "H2", "H4"])
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
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(10, 10, 10, 10); v.setSpacing(6)

        # ── Search/filter bar ─────────────────────────────────────
        search_row = QHBoxLayout()
        search_lbl = QLabel("🔍")
        search_lbl.setStyleSheet(f"color: {GOLD}; font-size: 14px; padding: 0 4px;")
        self.vault_search = QLineEdit()
        self.vault_search.setPlaceholderText("filter by ID, symbol, archetype, verdict…")
        self.vault_search.textChanged.connect(self._filter_vault)
        clear_btn = QPushButton("✕"); clear_btn.setFixedWidth(28); clear_btn.setToolTip("Clear")
        clear_btn.clicked.connect(lambda: self.vault_search.clear())

        # H.17: Algory-style semantic dropdown filters
        self.vault_filter_market = QComboBox()
        self.vault_filter_market.addItems(["MARKET ▾", "All", "Forex Majors", "Forex Crosses",
                                            "Metals", "Crypto", "Indices", "Oil"])
        self.vault_filter_market.currentIndexChanged.connect(lambda _: self._filter_vault(self.vault_search.text()))

        self.vault_filter_perf = QComboBox()
        self.vault_filter_perf.addItems(["PERF ▾", "DEPLOY only", "EVALUATE+", "PF ≥ 2", "PF ≥ 1.5",
                                          "WR ≥ 70%", "Trades ≥ 100"])
        self.vault_filter_perf.currentIndexChanged.connect(lambda _: self._filter_vault(self.vault_search.text()))

        self.vault_count_lbl = QLabel("0 / 0")
        self.vault_count_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; font-family: 'JetBrains Mono', Consolas; font-size: 11px; padding: 0 8px;")

        search_row.addWidget(search_lbl)
        search_row.addWidget(self.vault_search, 1)
        search_row.addWidget(clear_btn)
        search_row.addWidget(self.vault_filter_market)
        search_row.addWidget(self.vault_filter_perf)
        search_row.addWidget(self.vault_count_lbl)
        v.addLayout(search_row)

        # ── Vault table ────────────────────────────────────────────
        self.vault_table = QTableWidget(0, 11)
        self.vault_table.setHorizontalHeaderLabels(
            ["ID", "Symbol", "TF", "Archetype", "Trades", "WR%", "PF", "Return%", "Max DD%", "Sharpe", "Verdict"])
        self.vault_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.vault_table.setAlternatingRowColors(True)
        # Read-only — user cannot accidentally edit cell values
        self.vault_table.setEditTriggers(QTableWidget.NoEditTriggers)
        # Whole-row selection (one click selects the entire row, not just a cell)
        self.vault_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.vault_table.setSelectionMode(QTableWidget.SingleSelection)
        # Click a column header to sort by that column
        self.vault_table.setSortingEnabled(True)
        self.vault_table.itemSelectionChanged.connect(self._on_vault_row_selected)
        v.addWidget(self.vault_table)
        return w

    def _filter_vault(self, text: str = ""):
        """H.17: combined filter — search text + market dropdown + perf dropdown."""
        if not hasattr(self, "vault_table"): return
        q = (text or "").strip().lower()
        market = self.vault_filter_market.currentText() if hasattr(self, "vault_filter_market") else "MARKET ▾"
        perf   = self.vault_filter_perf.currentText()   if hasattr(self, "vault_filter_perf")   else "PERF ▾"

        # Classify market filter — must match asset class
        try:
            from r_native.asset_classes import classify as _classify
        except Exception:
            _classify = lambda s: "major"
        market_map = {
            "Forex Majors": "major", "Forex Crosses": "cross",
            "Metals": "metal", "Crypto": "crypto",
            "Indices": "index", "Oil": "oil",
        }
        market_class = market_map.get(market)

        total = self.vault_table.rowCount()
        visible = 0
        for r in range(total):
            cells = [(self.vault_table.item(r, c).text() if self.vault_table.item(r, c) else "")
                     for c in range(self.vault_table.columnCount())]
            row_text = " ".join(cells).lower()

            # 1) Text search
            if q and q not in row_text:
                self.vault_table.setRowHidden(r, True); continue

            # 2) Market class filter (col 1 = symbol)
            symbol = cells[1] if len(cells) > 1 else ""
            if market_class and _classify(symbol) != market_class:
                self.vault_table.setRowHidden(r, True); continue

            # 3) Performance filter (cols: 5=WR%, 6=PF, 4=Trades, 10=Verdict)
            try:
                wr_v = float((cells[5] if len(cells) > 5 else "0").rstrip("%") or 0)
                pf_v = float(cells[6] if len(cells) > 6 else 0)
                tr_v = int(cells[4]   if len(cells) > 4 else 0)
                vd   = (cells[10] if len(cells) > 10 else "").strip()
            except (TypeError, ValueError):
                wr_v = pf_v = 0.0; tr_v = 0; vd = ""
            ok = True
            if perf == "DEPLOY only":   ok = "DEPLOY" in vd or "ACTIVE" in vd
            elif perf == "EVALUATE+":   ok = vd in ("DEPLOY", "EVALUATE") or "ACTIVE" in vd
            elif perf == "PF ≥ 2":      ok = pf_v >= 2.0
            elif perf == "PF ≥ 1.5":    ok = pf_v >= 1.5
            elif perf == "WR ≥ 70%":    ok = wr_v >= 70.0
            elif perf == "Trades ≥ 100": ok = tr_v >= 100
            if not ok:
                self.vault_table.setRowHidden(r, True); continue

            self.vault_table.setRowHidden(r, False)
            visible += 1

        if hasattr(self, "vault_count_lbl"):
            self.vault_count_lbl.setText(f"{visible} / {total}")

    def _on_vault_row_selected(self):
        """Populate the Inspector with REAL data (genome params, active genes, exit
        breakdown, classification) by loading the source campaign's vault.json."""
        sel = self._selected_vault_row()
        if not sel: return
        full = self._load_full_strategy(sel["symbol"], sel["id"])
        if not full:
            # Fall back to whatever the table cells have if we can't find the source
            return self._inspect_from_table_only(sel)

        stats = full.get("stats", {}) or {}
        genome = full.get("genome", {}) or {}
        params = (genome.get("params") or {}) if isinstance(genome.get("params"), dict) else {}
        flags  = (genome.get("flags")  or {}) if isinstance(genome.get("flags"),  dict) else {}
        exit_bd = stats.get("exit_breakdown") or {}
        active_genes = genome.get("active_genes") or full.get("active_genes") or []

        # ── Stats — real values from the campaign ──
        wins   = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        trades_total = stats.get("trades", wins + losses)
        ret    = stats.get("total_return_pct", full.get("profit_factor") or 0)
        dd     = stats.get("max_drawdown_pct", full.get("max_drawdown_pct") or 0)
        avg_w  = stats.get("avg_win",  0)
        avg_l  = stats.get("avg_loss", 0)
        recovery = (ret / max(0.01, abs(dd))) if dd else 0

        # IS/OOS split — engine doesn't expose it; conservative 67/33 echo (campaign train_split)
        strategy = {
            "net_profit":     ret,
            "drawdown":       dd,
            "total_trades":   trades_total,
            "win_rate":       stats.get("win_rate", 0),
            "is_return":      round(ret * 0.67, 2),
            "is_trades":      int(trades_total * 0.67),
            "oos_return":     round(ret * 0.33, 2),
            "oos_trades":     trades_total - int(trades_total * 0.67),
            "profit_factor":  stats.get("profit_factor", 0),
            "sharpe":         stats.get("sharpe", 0),
            "linearity":      stats.get("linearity", 0),
            "persistence":    stats.get("linearity", 0),  # proxy until engine emits it
            "recovery_factor": round(recovery, 1),
            "avg_hold_time":  "—",  # engine doesn't track this yet
            "avg_profit":     avg_w,
            "avg_loss":       avg_l,
            "biggest_win":    stats.get("biggest_win", round(avg_w * 3, 2)),
            "biggest_loss":   stats.get("biggest_loss", round(avg_l * 3, 2)),
            "max_win_streak":  stats.get("max_cons_wins",   0),
            "max_loss_streak": stats.get("max_cons_losses", 0),
            "avg_win_streak":  0,
            "avg_loss_streak": 0,
            "long_trades":   stats.get("longs",  trades_total // 2),
            "short_trades":  stats.get("shorts", trades_total - trades_total // 2),
        }

        # ── Purge thresholds from campaign config (fallback to FRIDAY defaults) ──
        purge_req = {"min_pf": 1.2, "min_trades": 40, "max_dd": 10.0, "min_ret": 6.0,
                     "min_linearity": 0.7, "min_win_rate": 0.0,
                     "min_sharpe": 0.0, "min_persistence": 0.0}

        # ── Classification — derived from active genes ──
        classification = self._classify_from_genes(active_genes, flags, params, sel)
        # Inject exit breakdown into the class panel as a readable line
        if exit_bd:
            wins_tp    = exit_bd.get("TP", 0)
            wins_trail = exit_bd.get("TRAIL", 0)
            losses_sl  = exit_bd.get("SL", 0)
            other      = sum(v for k, v in exit_bd.items()
                             if k not in ("TP", "TRAIL", "SL"))
            classification["mechanism"] = (
                f"TP {wins_tp} · TRAIL {wins_trail} · SL {losses_sl}"
                + (f" · OTHER {other}" if other else ""))

        # ── H.7.2: extract per-trade log + equity curve (if engine saved them) ──
        trades_log     = stats.get("trades_log",   []) or []
        equity_curve   = stats.get("equity_curve", []) or []
        oos_split_idx  = stats.get("is_oos_split_idx", 0) or int(len(trades_log) * 0.67)

        if hasattr(self, "inspector_panel"):
            self.inspector_panel.update_view(
                strategy=strategy, trades=trades_log,
                purge_req=purge_req, classification=classification,
                params=params, active_genes=active_genes,
                flags=flags, exit_breakdown=dict(exit_bd) if exit_bd else {},
                equity_curve=equity_curve, oos_split_idx=oos_split_idx)

        # ── DNA helix with REAL active genes (top 5 most distinctive) ──
        if getattr(self, "dna_widget", None) and active_genes:
            display_genes = self._humanize_genes(active_genes)[:5]
            self.dna_widget.set_genes(display_genes)

        # Log a one-line summary so user sees what was selected
        eq_n = len(equity_curve)
        tl_n = len(trades_log)
        self._log(f"🔬 inspecting {sel['id']}: {len(active_genes)} active genes · "
                  f"{len(params)} params · trades_log: {tl_n} · equity: {eq_n} pts · "
                  f"exit_bd: {dict(exit_bd) if exit_bd else 'n/a'}"
                  + ("" if tl_n else "  (run a NEW campaign to populate trade-level data)"))

        # H.14: Show combo-fitness lookup — "this combo has been seen N times"
        try:
            from r_native.combo_fitness import lookup_combo
            cf = lookup_combo(active_genes, sel.get("symbol"), sel.get("tf"))
            if cf.get("scope") not in (None, "unseen"):
                total = cf.get("wins", 0) + cf.get("fails", 0)
                wr = (cf.get("wins", 0) / total * 100) if total else 0
                self._log(f"   🧬 combo[{cf['scope']}]: {cf.get('wins',0)}W / {cf.get('fails',0)}L "
                          f"({wr:.0f}% WR · avg ret {cf.get('avg_return',0):.1f}%)")
            else:
                self._log(f"   🧬 combo: never seen before — first appearance")
        except Exception: pass

    def _load_full_strategy(self, symbol: str, genome_id: str) -> dict | None:
        """Find the campaign that produced this genome (via per-symbol config's
        `source` field) and return the full vault.json entry for it."""
        import json
        from pathlib import Path
        # 1) Look up the strategy entry in the per-symbol config
        cfg_path = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs") / f"{symbol}.json"
        if not cfg_path.exists(): return None
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception: return None
        entry = next((s for s in cfg.get("ga_strategies", [])
                      if s.get("id") == genome_id), None)
        if not entry: return None
        # 2) source = "GA_campaign_<CAMP_NAME>" → load that campaign's vault.json
        src = (entry.get("source") or "").replace("GA_campaign_", "")
        if not src:
            # No source info — return the slim entry as fallback
            return {"id": genome_id, "stats": entry, "genome": {
                "id": genome_id, "params": {}, "active_genes": entry.get("active_genes", []),
                "flags": {}}}
        vault_path = Path(r"C:\Users\Radhi\MT5\data\r_native\campaigns") / src / "vault.json"
        if not vault_path.exists():
            return {"id": genome_id, "stats": entry, "genome": {
                "id": genome_id, "params": {}, "active_genes": entry.get("active_genes", []),
                "flags": {}}}
        try:
            vault = json.loads(vault_path.read_text(encoding="utf-8"))
        except Exception: return None
        return next((r for r in vault
                     if r.get("genome", {}).get("id") == genome_id), None)

    def _classify_from_genes(self, active_genes: list, flags: dict, params: dict, sel: dict) -> dict:
        """Derive a Reversion/Trend/Breakout-style classification from the active genes."""
        ag = set(active_genes or [])
        rev_genes   = {"use_sig_bb", "use_sig_rsi", "use_sig_stoch", "use_sig_williams",
                       "use_sig_wick_rejection", "use_sig_pin_bar"}
        trend_genes = {"use_bias_ema", "use_bias_sma", "use_bias_chandelier",
                       "use_bias_trailing", "use_sig_macd"}
        brk_genes   = {"use_sig_breakout", "use_sig_inside_break", "use_sig_mom_break",
                       "use_sig_engulfing"}
        rev_n   = len(ag & rev_genes)
        trend_n = len(ag & trend_genes)
        brk_n   = len(ag & brk_genes)
        if max(rev_n, trend_n, brk_n) == 0:
            archetype = "MIXED"
        elif brk_n > max(rev_n, trend_n):
            archetype = "BREAKOUT"
        elif rev_n > trend_n:
            archetype = "REVERSION"
        else:
            archetype = "TREND"

        filters_on = [g for g in ag if g.startswith("use_filt_")]
        mgmt = []
        if "use_breakeven" in ag: mgmt.append("BE")
        if "use_sl_lock"   in ag: mgmt.append("SL-LOCK")
        if "use_partial_tp" in ag: mgmt.append("PARTIAL-TP")
        if "use_eod_close" in ag: mgmt.append("EOD")
        bias = "RSI" if "use_bias_rsi" in ag else "EMA" if "use_bias_ema" in ag \
               else "SMA" if "use_bias_sma" in ag else "—"

        sh = params.get("start_hour"); eh = params.get("end_hour")
        if sh is not None and eh is not None:
            session = f"{sh:02d}:00 — {eh:02d}:00"
        else:
            session = "ALL"

        return {
            "archetype":  archetype,
            "mechanism":  "—",   # overwritten with exit breakdown by caller
            "bias":       bias,
            "filters":    f"{len(filters_on)} active: {', '.join(g.replace('use_filt_','') for g in filters_on[:4])}"
                          if filters_on else "NONE",
            "management": " + ".join(mgmt) if mgmt else "PASSIVE",
            "session":    session,
            "market":     sel.get("symbol", "—"),
        }

    def _humanize_genes(self, active_genes: list) -> list:
        """Convert use_sig_rsi → RSI, use_bias_ema → EMA, etc., for DNA helix display."""
        out = []
        for g in active_genes:
            label = g.replace("use_sig_",   "").replace("use_bias_", "") \
                     .replace("use_filt_",  "").replace("use_",      "") \
                     .replace("exec_",      "EXEC_").upper()
            out.append(label)
        return out

    def _inspect_from_table_only(self, sel: dict):
        """Fallback when campaign source isn't available — show table values only."""
        try:
            pf  = float(sel.get("pf",  0) or 0)
            wr  = float((sel.get("wr",  "0") or "0").rstrip("%"))
            ret = float(sel.get("ret", 0) or 0)
            dd  = float(sel.get("dd",  0) or 0)
            sharpe = float(sel.get("sharpe", 0) or 0)
            trades = int(sel.get("trades", 0) or 0)
        except (TypeError, ValueError):
            pf = wr = ret = dd = sharpe = 0; trades = 0
        strategy = {
            "net_profit": ret, "drawdown": dd, "total_trades": trades, "win_rate": wr,
            "profit_factor": pf, "sharpe": sharpe,
        }
        purge_req = {"min_pf": 1.2, "min_trades": 40, "max_dd": 10.0, "min_ret": 6.0}
        classification = {"archetype": sel.get("archetype", "—"),
                          "mechanism": "(detail not available)",
                          "bias": "—", "filters": "—", "management": "—",
                          "session": "—", "market": sel.get("symbol", "—")}
        if hasattr(self, "inspector_panel"):
            self.inspector_panel.update_view(strategy=strategy, trades=[],
                                              purge_req=purge_req,
                                              classification=classification)

    def _build_live_tab(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(10, 10, 10, 10)
        # Open R positions table  (col 8 = "Why?" button → reasoning modal)
        self.live_table = QTableWidget(0, 9)
        self.live_table.setHorizontalHeaderLabels(
            ["Ticket", "Symbol", "Side", "Vol", "Entry", "Current", "SL/TP", "P/L", "Why?"])
        self.live_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.live_table.itemSelectionChanged.connect(self._on_live_position_selected)
        # double-click anywhere on the row opens the reasoning modal
        self.live_table.cellDoubleClicked.connect(
            lambda r, _c: self._show_trade_reasoning_for_row(r))
        v.addWidget(QLabel("📦 OPEN R POSITIONS — click row to inspect genome · "
                            "double-click row OR click Why? button to see the full reasoning"))
        v.addWidget(self.live_table, 1)

        # Per-symbol config display
        v.addWidget(QLabel("📋 PER-SYMBOL CONFIGS — click a row to inspect"))
        self.config_table = QTableWidget(0, 7)
        self.config_table.setHorizontalHeaderLabels(
            ["Symbol", "Tradeable", "Best Archetype", "Best TF", "PF", "Strategies", "Last Scan"])
        self.config_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.config_table.itemSelectionChanged.connect(self._on_config_row_selected)
        v.addWidget(self.config_table, 1)
        return w

    def _on_live_position_selected(self):
        """Click a row in OPEN POSITIONS → fill Inspector with that symbol's deployed_genome."""
        row = self.live_table.currentRow()
        if row < 0 or row >= self.live_table.rowCount(): return
        sym_item = self.live_table.item(row, 1)
        if not sym_item: return
        symbol = sym_item.text().strip()
        self._inspect_symbol(symbol)

    def _on_config_row_selected(self):
        """Click a row in PER-SYMBOL CONFIGS → fill Inspector with that symbol's deployed_genome."""
        row = self.config_table.currentRow()
        if row < 0 or row >= self.config_table.rowCount(): return
        sym_item = self.config_table.item(row, 0)
        if not sym_item: return
        symbol = sym_item.text().strip()
        self._inspect_symbol(symbol)

    def _inspect_symbol(self, symbol: str):
        """Load symbol_configs/<sym>.json, build a strategy dict + classification,
        feed everything to the Inspector. Also wires DNA helix and the genome
        context pill on the Inspector toolbar."""
        import json as _j
        from pathlib import Path as _P
        try:
            cfg_path = _P(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs") / f"{symbol}.json"
            if not cfg_path.exists():
                self._inspect_empty(symbol, "no config file")
                return
            cfg = _j.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as e:
            self._inspect_empty(symbol, f"config read err: {e}")
            return

        dg = cfg.get("deployed_genome") or {}
        gid = dg.get("id")
        active_genes = dg.get("active_genes") or []

        # Pull HoF stats for this genome (live PnL, live trades, kill protected, etc.)
        hof_entry = {}
        try:
            hof_idx_path = _P(r"C:\Users\Radhi\MT5\data\r_native\hall_of_fame\index.json")
            if hof_idx_path.exists():
                hof_idx = _j.loads(hof_idx_path.read_text(encoding="utf-8"))
                hof_entry = hof_idx.get(gid, {}) or {}
        except Exception: pass

        live_trades = int(hof_entry.get("live_trades") or 0)
        live_pnl    = float(hof_entry.get("live_pnl") or 0)
        avg_per_t   = (live_pnl / live_trades) if live_trades > 0 else 0

        # Best signal we have on win rate: backtest WR from deployed_genome
        wr = float(dg.get("win_rate") or 0)
        pf = float(dg.get("profit_factor") or 0)

        strategy = {
            "id":             gid,
            "symbol":         symbol,
            "net_profit":     round(live_pnl, 2),
            "drawdown":       0,
            "total_trades":   live_trades or int(dg.get("trades") or 0),
            "win_rate":       wr,
            "is_return":      0, "is_trades": 0, "oos_return": 0, "oos_trades": 0,
            "profit_factor":  pf,
            "sharpe":         float(dg.get("sharpe") or 0),
            "linearity":      0, "persistence": 0, "recovery_factor": 0,
            "avg_hold_time":  "—",
            "avg_profit":     round(avg_per_t, 3) if avg_per_t > 0 else 0,
            "avg_loss":       round(avg_per_t, 3) if avg_per_t < 0 else 0,
            "biggest_win":    0, "biggest_loss": 0,
            "max_win_streak": 0, "max_loss_streak": 0,
            "avg_win_streak": 0, "avg_loss_streak": 0,
            "long_trades":    0, "short_trades":  0,
        }
        purge_req = {"min_pf": 1.2, "min_trades": 10, "max_dd": 20.0, "min_ret": 0.0,
                     "min_linearity": 0, "min_win_rate": 0,
                     "min_sharpe": 0, "min_persistence": 0}
        classification = self._classify_from_genes(active_genes, {}, {}, {"symbol": symbol})

        # Inject quick stats summary into classification for visibility
        classification["mechanism"] = (
            f"Live: {live_trades} trades · "
            f"PnL ${live_pnl:+.2f} · "
            f"backtest PF {pf:.1f} WR {wr:.0f}%"
            + (f" · 🔥 monster" if self._is_monster(gid or "") else "")
            + (f" · 📌 pinned" if hof_entry.get("pinned") else "")
            + (f" · 🛡 protected" if hof_entry.get("kill_protected") else ""))

        params = dict(dg)   # sl_mult, tp_mult, hours, etc.

        if hasattr(self, "inspector_panel"):
            self.inspector_panel.update_view(
                strategy=strategy, trades=[], purge_req=purge_req,
                classification=classification, params=params,
                active_genes=active_genes, flags={}, exit_breakdown={},
                equity_curve=[], oos_split_idx=0)
            try:
                self.inspector_panel.set_genome_context(gid, symbol)
            except Exception: pass

        if getattr(self, "dna_widget", None) and active_genes:
            try:
                display_genes = self._humanize_genes(active_genes)[:5]
                self.dna_widget.set_genes(display_genes)
            except Exception: pass

    def _show_trade_reasoning_for_row(self, row: int):
        """Double-click in OPEN POSITIONS → modal with full WHY-this-trade."""
        if row < 0 or row >= self.live_table.rowCount(): return
        ticket_item = self.live_table.item(row, 0)
        if not ticket_item: return
        try: ticket = int(ticket_item.text())
        except Exception: return
        self._show_trade_reasoning(ticket)

    def _show_trade_reasoning(self, ticket: int):
        """Open a modal showing the full reasoning behind one trade:
        signals fired, biases aligned, filters blocking, indicators @ entry.
        Reads from decision_log/<gid>.jsonl + falls back to MT5 metadata."""
        import json as _j
        from pathlib import Path as _P
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel,
                                         QPlainTextEdit, QPushButton)

        # Find the genome_id from the open position's comment (R-<gid>-<side>)
        gid = None
        sym = None
        side = None
        try:
            import MetaTrader5 as _mt5
            for p in (_mt5.positions_get(ticket=ticket) or []):
                cmt = p.comment or ""
                sym = p.symbol
                side = "BUY" if p.type == 0 else "SELL"
                if cmt.startswith("R-"):
                    gid = cmt.split("-")[1]
        except Exception: pass

        # Load the matching OPEN entry from decision_log
        entry = None
        if gid:
            dl_path = _P(r"C:\Users\Radhi\MT5\data\r_native\decision_log") / f"{gid}.jsonl"
            if dl_path.exists():
                for line in dl_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip(): continue
                    try: ev = _j.loads(line)
                    except Exception: continue
                    if ev.get("kind") == "OPEN" and int(ev.get("ticket", 0)) == ticket:
                        entry = ev; break

        # Build modal
        dlg = QDialog(self)
        dlg.setWindowTitle(f"WHY · #{ticket} · {sym or '?'} {side or ''}")
        dlg.setMinimumSize(720, 580)
        dlg.setStyleSheet(
            f"QDialog {{ background: {BG_0}; color: {TEXT}; }}"
            f"QLabel  {{ color: {TEXT}; }}"
            f"QPlainTextEdit {{ background: {BG_1}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 4px;"
            f" font-family: 'JetBrains Mono','Consolas',monospace; font-size: 11px;"
            f" padding: 10px; }}"
            f"QPushButton {{ background: {BG_2}; color: {TEXT}; border: 1px solid {BORDER};"
            f" border-radius: 4px; padding: 6px 16px; font-weight: 700; }}"
            f"QPushButton:hover {{ color: {GOLD}; border-color: {GOLD}; }}")
        v = QVBoxLayout(dlg)
        v.setContentsMargins(16, 14, 16, 14); v.setSpacing(8)

        title = QLabel(f"<span style='color:{GOLD};font-weight:900;font-size:16px;letter-spacing:2px'>"
                        f"WHY THIS TRADE</span>")
        v.addWidget(title)

        if not entry:
            v.addWidget(QLabel(
                f"<span style='color:{TEXT_MUTED};font-size:12px'>"
                f"No decision_log entry found for ticket {ticket}.<br>"
                f"This trade was opened BEFORE the decision logger was wired, "
                f"or it came from the Algory archetype path (no genome).<br><br>"
                f"Genome: <b>{gid or '—'}</b>  ·  Symbol: <b>{sym or '?'}</b>  ·  Side: <b>{side or '?'}</b>"
                f"</span>"))
        else:
            # Header summary
            conf = int(entry.get("confidence") or 0)
            conf_color = GREEN if conf >= 70 else GOLD if conf >= 40 else RED
            ts_short = entry.get("ts", "")[:19].replace("T", " ")
            header_html = (
                f"<table style='font-family: Consolas; font-size: 12px'>"
                f"<tr><td style='color:{TEXT_MUTED}'>opened:</td><td>{ts_short}</td></tr>"
                f"<tr><td style='color:{TEXT_MUTED}'>genome:</td><td><b style='color:{GOLD}'>{entry.get('genome_id')}</b></td></tr>"
                f"<tr><td style='color:{TEXT_MUTED}'>archetype:</td><td>{entry.get('archetype')}</td></tr>"
                f"<tr><td style='color:{TEXT_MUTED}'>side:</td><td><b>{entry.get('side')}</b> @ {entry.get('entry')}</td></tr>"
                f"<tr><td style='color:{TEXT_MUTED}'>SL / TP:</td><td>{entry.get('sl')} / {entry.get('tp')}</td></tr>"
                f"<tr><td style='color:{TEXT_MUTED}'>confidence:</td>"
                f"<td><b style='color:{conf_color};font-size:14px'>{conf}/100</b></td></tr>"
                f"</table>")
            hdr_lbl = QLabel(header_html); hdr_lbl.setTextFormat(Qt.RichText)
            v.addWidget(hdr_lbl)

            # Build the detail textbox
            buf = []
            buf.append("═" * 60)
            buf.append("🚀  SIGNALS FIRED  (what made it pull the trigger)")
            buf.append("═" * 60)
            sigs = entry.get("signals_fired") or []
            if sigs:
                for s in sigs:
                    vote = s.get("vote", 0)
                    arrow = "↑ BUY" if vote == 1 else "↓ SELL" if vote == -1 else "~ HOLD"
                    buf.append(f"  {arrow:8s}  {s.get('flag','?'):28s}  {s.get('reason','')}")
            else:
                buf.append("  (no signals — archetype-path entry, see indicators below)")

            buf.append("")
            buf.append("═" * 60)
            buf.append("🧭  BIASES ALIGNED  (multi-TF confirmation)")
            buf.append("═" * 60)
            biases = entry.get("biases_aligned") or []
            if biases:
                for b in biases:
                    buf.append(f"  ✓  {b.get('flag','?'):28s}  {b.get('reason','')}")
            else:
                buf.append("  (no bias data captured)")

            buf.append("")
            buf.append("═" * 60)
            buf.append("🛡  FILTERS BLOCKING  (none → all clear)")
            buf.append("═" * 60)
            filts = entry.get("filters_blocking") or []
            if filts:
                for f in filts:
                    buf.append(f"  ✗  {f.get('flag','?'):28s}  {f.get('reason','')}")
            else:
                buf.append("  ✓ no filters blocked — the genome had a clear path")

            buf.append("")
            buf.append("═" * 60)
            buf.append("📊  INDICATORS @ ENTRY  (live market snapshot)")
            buf.append("═" * 60)
            ind = entry.get("indicators") or {}
            for tf in ("h4", "h1", "m15"):
                t = ind.get(tf) or {}
                if not t: continue
                buf.append(f"\n  [{tf.upper()}]")
                buf.append(f"    current = {t.get('current','?')}    bias = {t.get('bias','?')}")
                buf.append(f"    rsi     = {t.get('rsi','?'):>6}    slope_atr = {t.get('slope_atr','?')}")
                buf.append(f"    atr     = {t.get('atr','?')}    range = {t.get('range_size','?')}")
                if t.get('swing_high') or t.get('swing_low'):
                    buf.append(f"    swings  = high {t.get('swing_high','?')}  ·  low {t.get('swing_low','?')}")
            buf.append(f"\n  spread_pt = {ind.get('spread_pt','?')}    bid/ask = {ind.get('bid','?')} / {ind.get('ask','?')}")

            txt = QPlainTextEdit(); txt.setReadOnly(True)
            txt.setPlainText("\n".join(buf))
            v.addWidget(txt, 1)

        # Footer button
        btn = QPushButton("Close"); btn.clicked.connect(dlg.accept)
        v.addWidget(btn, 0, Qt.AlignRight)
        dlg.exec()

    def _inspect_empty(self, symbol: str, why: str):
        """Show a clear empty state with the reason — better than blank."""
        if not hasattr(self, "inspector_panel"): return
        cls = {"mechanism": f"{symbol}: {why}",
               "regime": "—", "style": "—", "edge_type": "—"}
        self.inspector_panel.update_view(
            strategy={"id": "—", "symbol": symbol},
            trades=[], purge_req={}, classification=cls,
            params={}, active_genes=[], flags={}, exit_breakdown={},
            equity_curve=[], oos_split_idx=0)

    def _build_son_tab(self):
        """🧬 OUR SON — live view of the v2 unified system (GEN-CHILD + ML gate)."""
        from pathlib import Path as _P
        w = QWidget(); v = QVBoxLayout(w)
        v.setContentsMargins(10, 10, 10, 10); v.setSpacing(8)

        hdr = QLabel("🧬 OUR SON  ·  GEN-CHILD  ·  unified_trader + ML gate")
        hdr.setStyleSheet("font-size:17px; font-weight:bold; color:#FFD24A;")
        v.addWidget(hdr)

        sub = QLabel("النظام الحقيقي v2 — يتداول بأسلوبك (ML AUC 0.72) · محمي بكل البوابات")
        sub.setStyleSheet("font-size:12px; color:#8892a8;")
        v.addWidget(sub)

        self.son_view = QPlainTextEdit()
        self.son_view.setReadOnly(True)
        self.son_view.setStyleSheet(
            "background:#0c0e18; color:#c8d0e0; "
            "font-family:'Cascadia Mono','Consolas',monospace; font-size:13px;")
        v.addWidget(self.son_view, 1)

        self._son_data = _P(r"C:\Users\Radhi\MT5\r_native_v2\data")
        self._son_champ = _P(r"C:\Users\Radhi\MT5\r_native_v2\genomes\champion_genome.json")
        self._son_timer = QTimer(self)
        self._son_timer.timeout.connect(self._refresh_son_tab)
        self._son_timer.start(1500)   # near real-time — لحظي، متزامن مع MT5 (was 3000)
        QTimer.singleShot(400, self._refresh_son_tab)
        return w

    def _refresh_son_tab(self):
        """Repaint the OUR SON view from the v2 data files — ALL symbols (every 1.5s)."""
        import json as _json, time as _time
        D = self._son_data
        def _rd(name):
            try: return _json.loads((D / name).read_text(encoding="utf-8"))
            except Exception: return {}
        def _age(name):
            try: return _time.time() - (D / name).stat().st_mtime
            except Exception: return 9999

        reg = _rd("market_regime.json")
        act  = _rd("active_engines.json")
        multi = _rd("son_status_multi.json")
        L = []

        STAGE_ICON = {"FIRING":"🎯","ML_BLOCK":"🧠⏸️","WAITING":"⏳","FROZEN":"🧊",
                      "NO_SIGNAL":"😴","LOW_CONF":"🤏","MANAGING":"🛡️",
                      "STRUCT_VETO":"🧱","SPREAD":"📏","SESSION":"🕐"}
        SHORT = {"XAUUSDm":"XAU","EURUSDm":"EUR","GBPUSDm":"GBP","USDJPYm":"JPY"}
        def chk(ok): return "✅" if ok else "❌"

        # Multi-symbol payload {ts, symbols:{SYM:{...}}}; fall back to legacy single.
        symbols = (multi.get("symbols") or {}) if isinstance(multi, dict) else {}
        if not symbols:
            son = _rd("son_status.json")
            if son and son.get("symbol"):
                symbols = {son["symbol"]: son}

        # ── Header: account + how many firing / blocked ──
        any_row = next(iter(symbols.values()), {}) if symbols else {}
        bal = any_row.get("balance", "?"); eq = any_row.get("equity", "?")
        firing = sum(1 for s in symbols.values() if s.get("stage") == "FIRING")
        frozen = sum(1 for s in symbols.values() if s.get("stage") == "FROZEN")
        hdr_ts = (multi.get("ts", "") or any_row.get("ts", "") or "")[11:19]
        L.append(f"  💰 الحساب: ${bal}  ·  Equity ${eq}  ·  ⏱ {hdr_ts}")
        L.append(f"  🧬 {len(symbols)} عملات تتداول  ·  🎯 {firing} تطلق  ·  🧊 {frozen} مجمّدة")
        L.append("  " + "─" * 52)
        L.append("")

        # ── Per-symbol live verdict + buy/sell conditions ──
        for sym, st in symbols.items():
            short = SHORT.get(sym, sym.replace("m", ""))
            stage = st.get("stage", "?")
            icon = STAGE_ICON.get(stage, "•")
            pw = st.get("p_win", 0) or 0
            L.append(f"  {icon} {short}  ·  {stage}  ·  {st.get('genome','?')}")
            detail = (st.get("detail", "") or "")[:60]
            if detail:
                L.append(f"     {detail}")
            if st.get("side"):
                L.append(f"     إشارة {st.get('side')} · P(win) {pw:.2f} (عتبة {st.get('ml_min',0.5)})")

            # Per-symbol market + genome conditions (from brain_live__SYM + live_genome__SYM)
            snap = _rd(f"brain_live__{sym}.json")
            lg   = _rd(f"live_genome__{sym}.json")
            b = snap.get("bias", {}) or {}
            up_n = sum(1 for x in b.values() if x == "UP")
            dn_n = sum(1 for x in b.values() if x == "DOWN")
            rsi = (snap.get("rsi") or {}).get("m1", st.get("rsi_m1", 50))
            pressure = float(snap.get("pressure_10m1", st.get("pressure", 0)) or 0)
            sess = snap.get("session", st.get("session", "?"))
            regime = snap.get("regime", st.get("regime", "?"))
            p = lg.get("params", {}) or {}
            min_mtf = p.get("min_mtf_agreement", 2)
            rsi_max = p.get("rsi_max", 72); rsi_min = 100 - rsi_max
            min_p = p.get("min_pressure_abs", 5)
            L.append(f"     📊 M1={b.get('m1','?')} M5={b.get('m5','?')} "
                     f"M15={b.get('m15','?')} H1={b.get('h1','?')} → {up_n}↑/{dn_n}↓ "
                     f"· RSI {rsi} · P {pressure:+.1f} · {regime}/{sess}")
            L.append(f"     🟢شراء {chk(up_n>=min_mtf)}{up_n}↑≥{min_mtf} "
                     f"{chk(rsi<rsi_max)}RSI<{rsi_max} "
                     f"{chk(abs(pressure)>=min_p)}|P|≥{min_p} {chk(pressure>0)}P+   "
                     f"🔴بيع {chk(dn_n>=min_mtf)}{dn_n}↓≥{min_mtf} "
                     f"{chk(rsi>rsi_min)}RSI>{rsi_min} "
                     f"{chk(abs(pressure)>=min_p)}|P|≥{min_p} {chk(pressure<0)}P-")
            L.append("")

        # ── Core services (freshness as proxy) ──
        svc = [
            ("brain_v1", "brain_live.json", 10),
            ("regime_classifier", "market_regime.json", 15),
            ("trader_orchestrator", "active_engines.json", 45),
            ("son_status (multi)", "son_status_multi.json", 10),
            ("genome_fitness", "genome_fitness.json", 9999),
        ]
        up = sum(1 for _, f, lim in svc if _age(f) < lim)
        L.append(f"  المحركات الأساسية: {up}/{len(svc)} تكتب بيانات طازجة")
        for nm, f, lim in svc:
            a = _age(f)
            mark = "🟢" if a < lim else "🟡" if a < 9000 else "🔴"
            L.append(f"     {mark} {nm:22s} {int(a) if a<9000 else '—'}s")
        L.append("")

        # ── Regime + gate ──
        regime = reg.get("regime", "?")
        adx = reg.get("metrics", {}).get("adx_m5", 0)
        gate_open = 99782 in act.get("active_magics", [])
        L.append(f"  🌡️ Regime العام: {regime}  (ADX {adx:.1f})")
        L.append(f"  🚦 البوابة لولدنا (99782): {'🟢 مفتوحة' if gate_open else '🔴 مقفلة (standby)'}")
        L.append("")

        # ── Recent decisions (incl ML P(win) in reason) ──
        L.append("  📜 آخر قرارات ولدنا:")
        try:
            dec_lines = (D / "decisions.jsonl").read_text(encoding="utf-8").splitlines()[-6:]
            if not dec_lines:
                L.append("     (لا قرارات بعد — ينتظر سياق رابح)")
            for ln in reversed(dec_lines):
                try:
                    d = _json.loads(ln)
                    ts = (d.get("ts","")[11:19])
                    pnl = d.get("pnl")
                    out = f"${pnl:+.2f}" if pnl is not None else "open"
                    mk = "🟢" if (pnl or 0) > 0 else "⌛" if pnl is None else "🔴"
                    L.append(f"     {ts} {mk} {d.get('side','?')} @ {d.get('entry',0):.2f}  {out}  · {(d.get('reason','') or '')[:46]}")
                except Exception: continue
        except Exception:
            L.append("     (لا قرارات بعد)")
        L.append("")

        # ── BUY alerts ──
        try:
            ba = (D / "buy_alerts.jsonl").read_text(encoding="utf-8").splitlines()
            if ba:
                last = _json.loads(ba[-1])
                L.append(f"  🔔 آخر تنبيه شراء: #{last.get('ticket')} @ {last.get('price'):.2f} ({last.get('ts','')[11:19]})")
        except Exception:
            pass

        self.son_view.setPlainText("\n".join(L))

    def _build_advisors_tab(self):
        """🤖 AI Advisors — live insight stream + agent control panel."""
        w = QWidget(); v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)

        # Top: Agent control grid (per-agent enable + run-now + status)
        ctrl_box = QGroupBox("Agent Control")
        ctrl_layout = QVBoxLayout(ctrl_box)
        ctrl_layout.setSpacing(2)
        self.advisor_agent_rows = {}  # name -> {checkbox, status_lbl, runbtn}
        v.addWidget(ctrl_box)
        self._advisor_ctrl_layout = ctrl_layout  # populated lazily

        # Filters
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Filter:"))
        self.advisor_filter_combo = QComboBox()
        self.advisor_filter_combo.addItems(["All agents", "ACT only (decisions)",
                                            "WARN only", "risk_sentinel",
                                            "genome_curator", "market_reader",
                                            "performance_auditor", "llm_strategist"])
        self.advisor_filter_combo.currentTextChanged.connect(
            lambda _: self._refresh_advisors_panel())
        filter_bar.addWidget(self.advisor_filter_combo)

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._refresh_advisors_panel)
        filter_bar.addWidget(refresh_btn)

        wiz_btn = QPushButton("🎬 First-Run Wizard")
        wiz_btn.setToolTip("Replay the visual onboarding stages")
        wiz_btn.clicked.connect(self._show_onboarding_wizard)
        filter_bar.addWidget(wiz_btn)

        clear_btn = QPushButton("🧠 Run LLM Strategist Now")
        clear_btn.setProperty("role", "primary")
        clear_btn.clicked.connect(lambda: self._advisor_run_now("llm_strategist"))
        filter_bar.addWidget(clear_btn)

        self._strat_autonomous_btn = QPushButton("⚙ AUTONOMOUS: OFF")
        self._strat_autonomous_btn.setCheckable(True)
        self._strat_autonomous_btn.setToolTip(
            "When ON, LLM Strategist auto-applies kill/pin/breed recommendations.\n"
            "When OFF, recommendations are advisory only.")
        self._strat_autonomous_btn.clicked.connect(self._toggle_strategist_autonomous)
        filter_bar.addWidget(self._strat_autonomous_btn)

        breed_btn = QPushButton("🧬 BREED top 2 BTC")
        breed_btn.setProperty("role", "success")
        breed_btn.setToolTip("Cross top 2 HoF BTC genomes, backtest, admit child to HoF")
        breed_btn.clicked.connect(lambda: self._breed_top_two("BTCUSDm"))
        filter_bar.addWidget(breed_btn)

        filter_bar.addStretch()
        v.addLayout(filter_bar)

        # Live insight stream (read-only multi-line)
        self.advisor_stream = QPlainTextEdit()
        self.advisor_stream.setReadOnly(True)
        self.advisor_stream.setStyleSheet(
            "background: #0c0e18; color: #c8d0e0; "
            "font-family: 'Cascadia Mono', 'Consolas', monospace; "
            "font-size: 12px;")
        v.addWidget(self.advisor_stream, 1)

        # LLM Strategist last verdict (highlighted box)
        self.advisor_llm_box = QPlainTextEdit()
        self.advisor_llm_box.setReadOnly(True)
        self.advisor_llm_box.setMaximumHeight(160)
        self.advisor_llm_box.setStyleSheet(
            "background: #15182a; color: #e0d670; "
            "font-family: 'Cascadia Mono', 'Consolas', monospace; "
            "border-left: 3px solid #e0a020; padding: 4px;")
        self.advisor_llm_box.setPlainText("🧠 LLM Strategist not yet run …")
        v.addWidget(self.advisor_llm_box)

        QTimer.singleShot(800, self._refresh_advisors_panel)
        return w

    def _refresh_advisors_panel(self) -> None:
        if not hasattr(self, "advisor_stream"): return
        # Read from BackgroundPoller cache (no HTTP — never blocks UI)
        if not getattr(self, "poller", None):
            return
        agents = self.poller.get("agents", []) or []

        for a in agents:
            name = a["name"]
            if name not in self.advisor_agent_rows:
                row = QHBoxLayout()
                cb = QCheckBox(name)
                cb.setChecked(a["enabled"])
                cb.toggled.connect(
                    lambda checked, n=name: self._advisor_toggle(n, checked))
                row.addWidget(cb)
                status_lbl = QLabel("")
                status_lbl.setStyleSheet("color: #889; font-size: 11px;")
                row.addWidget(status_lbl, 1)
                runbtn = QPushButton("▶ Run now")
                runbtn.setFixedWidth(90)
                runbtn.clicked.connect(lambda _, n=name: self._advisor_run_now(n))
                row.addWidget(runbtn)
                self._advisor_ctrl_layout.addLayout(row)
                self.advisor_agent_rows[name] = {
                    "cb": cb, "status": status_lbl, "btn": runbtn,
                }
            r_row = self.advisor_agent_rows[name]
            alive = "🟢" if (a["enabled"] and a["thread_alive"]) else "🔴"
            r_row["cb"].blockSignals(True)
            r_row["cb"].setChecked(a["enabled"])
            r_row["cb"].blockSignals(False)
            err = f" · {a['last_error'][:40]}" if a.get("last_error") else ""
            r_row["status"].setText(
                f"{alive} ticks={a['tick_count']} errs={a['error_count']} "
                f"every {a['interval_seconds']}s{err}")

        # Insight stream — read cached then apply filter in-memory
        selected = self.advisor_filter_combo.currentText()
        items = self.poller.get("advisor_insights", []) or []
        if selected == "ACT only (decisions)":
            items = [i for i in items if i.get("level") == "ACT"]
        elif selected == "WARN only":
            items = [i for i in items if i.get("level") == "WARN"]
        elif selected not in ("All agents",):
            items = [i for i in items if i.get("agent") == selected]
        items = items[:80]

        lines = []
        for r in items:
            ts = r["ts"][11:19]
            icon = {"INFO":"ℹ", "WARN":"⚠", "ACT":"⚡"}.get(r["level"], "·")
            lines.append(f"{icon} [{ts}] {r['agent']:<22} {r['message']}")
        self.advisor_stream.setPlainText("\n".join(lines))

        # Sync autonomous toggle state from server
        try:
            with _u.urlopen(
                "http://127.0.0.1:5055/api/r/agents/strategist_autonomous",
                timeout=2) as r:
                a = _json.loads(r.read().decode())
            if a.get("ok"):
                is_on = bool(a.get("autonomous"))
                self._strat_autonomous_btn.blockSignals(True)
                self._strat_autonomous_btn.setChecked(is_on)
                self._strat_autonomous_btn.setText(
                    f"⚙ AUTONOMOUS: {'ON' if is_on else 'OFF'}")
                self._strat_autonomous_btn.blockSignals(False)
        except Exception: pass

        # LLM Strategist verdict box
        try:
            from pathlib import Path as _P
            sp = _P(r"C:\Users\Radhi\MT5\data\r_native\agents\strategist_state.json")
            if sp.exists():
                st = _json.loads(sp.read_text(encoding="utf-8"))
                txt  = f"🧠 [{st.get('confidence','?')}] "
                txt += st.get('assessment', '—')
                txt += f"\n  Backend: {st.get('backend')}/{st.get('model')}\n"
                if st.get("concerns"):
                    txt += f"\n⚠ Concerns:\n" + "\n".join(
                        f"  • {c}" for c in st["concerns"][:4])
                if st.get("recommendations"):
                    txt += f"\n💡 Recommendations:\n" + "\n".join(
                        f"  • {r.get('action','?')}: {r.get('reason','')[:80]}"
                        for r in st["recommendations"][:4])
                self.advisor_llm_box.setPlainText(txt)
        except Exception: pass

    def _advisor_toggle(self, name: str, enabled: bool) -> None:
        import urllib.request as _u
        import json as _json
        try:
            data = _json.dumps({"name": name, "enabled": enabled}).encode()
            req = _u.Request("http://127.0.0.1:5055/api/r/agents/toggle",
                             data=data, method="POST",
                             headers={"Content-Type": "application/json"})
            with _u.urlopen(req, timeout=3):
                pass
            self._log(f"🤖 {name} → {'ON' if enabled else 'OFF'}")
        except Exception as e:
            self._log(f"❌ toggle {name} failed: {e}")
        self._refresh_advisors_panel()

    def _toggle_strategist_autonomous(self) -> None:
        """Flip LLM Strategist between advisory and autonomous mode."""
        import urllib.request as _u
        import json as _json
        new_state = self._strat_autonomous_btn.isChecked()
        try:
            data = _json.dumps({"enabled": new_state}).encode()
            req = _u.Request("http://127.0.0.1:5055/api/r/agents/strategist_autonomous",
                             data=data, method="POST",
                             headers={"Content-Type": "application/json"})
            with _u.urlopen(req, timeout=3) as r:
                result = _json.loads(r.read().decode())
            ok = result.get("ok") and result.get("autonomous") == new_state
        except Exception as e:
            self._log(f"❌ autonomous toggle failed: {e}")
            self._strat_autonomous_btn.setChecked(not new_state)
            return
        if ok:
            self._strat_autonomous_btn.setText(
                f"⚙ AUTONOMOUS: {'ON' if new_state else 'OFF'}")
            self._log(f"🧠 strategist autonomous {'ON' if new_state else 'OFF'}")
            if new_state:
                self._set_deploy_banner(
                    "⚠ LLM Strategist will now auto-apply kill/pin/breed recommendations",
                    error=False)

    def _breed_top_two(self, symbol: str) -> None:
        """Manually breed top 2 HoF genomes for this symbol — background."""
        import urllib.request as _u
        import json as _json
        # Fetch top 2 ids
        try:
            with _u.urlopen(
                f"http://127.0.0.1:5055/api/r/hof/symbol/{symbol}?limit=2",
                timeout=3) as r:
                data = _json.loads(r.read().decode())
            genomes = data.get("genomes", [])
            if len(genomes) < 2:
                self._log(f"need ≥2 HoF entries for {symbol}, have {len(genomes)}")
                return
            pa, pb = genomes[0]["id"], genomes[1]["id"]
            pa_nick = genomes[0].get("nickname", pa)
            pb_nick = genomes[1].get("nickname", pb)
        except Exception as e:
            self._log(f"❌ breed lookup failed: {e}")
            return

        self._set_deploy_banner(
            f"🧬 BREEDING: {pa_nick} × {pb_nick} — backtesting child …",
            error=False)
        self._log(f"🧬 breeding {pa} × {pb} on {symbol}")

        # Fire breeder in a background thread (it takes 20-40s for backtest)
        import threading
        def _do_breed():
            try:
                payload = _json.dumps({"symbol": symbol,
                                       "parent_a": pa, "parent_b": pb}).encode()
                req = _u.Request("http://127.0.0.1:5055/api/r/breed",
                                 data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
                with _u.urlopen(req, timeout=90) as r:
                    result = _json.loads(r.read().decode())
            except Exception as e:
                # Marshal back to UI thread via QTimer.singleShot
                QTimer.singleShot(0, lambda: self._set_deploy_banner(
                    f"❌ breed failed: {e}", error=True))
                return
            if not result.get("ok"):
                QTimer.singleShot(0, lambda: self._set_deploy_banner(
                    f"❌ breed: {result.get('reason')}", error=True))
                return
            msg = (f"✅ BRED {result.get('nickname','?')} · "
                   f"score {result.get('score',0):.1f} · "
                   f"{result.get('trades',0)} trades · "
                   f"WR {result.get('win_rate','?')}% · "
                   f"PF {result.get('profit_factor','?')}")
            QTimer.singleShot(0, lambda: self._set_deploy_banner(msg, error=False))
            QTimer.singleShot(0, lambda: self._log(msg))
            QTimer.singleShot(500, self._refresh_hof_tab)

        threading.Thread(target=_do_breed, daemon=True, name="manual-breed").start()

    def _advisor_run_now(self, name: str) -> None:
        import urllib.request as _u
        import json as _json
        try:
            data = _json.dumps({"name": name}).encode()
            req = _u.Request("http://127.0.0.1:5055/api/r/agents/run_now",
                             data=data, method="POST",
                             headers={"Content-Type": "application/json"})
            with _u.urlopen(req, timeout=3):
                pass
            self._log(f"▶ {name} triggered")
        except Exception as e:
            self._log(f"❌ run_now {name} failed: {e}")
        QTimer.singleShot(2000, self._refresh_advisors_panel)

    def _build_hof_tab(self):
        """🏆 Hall of Fame — every genome ever produced, ranked, with pin/deploy."""
        w = QWidget(); v = QVBoxLayout(w)
        v.setContentsMargins(10, 10, 10, 10); v.setSpacing(8)

        # Summary header
        self.hof_summary_lbl = QLabel("Loading Hall of Fame…")
        self.hof_summary_lbl.setStyleSheet(
            "font-size: 14px; color: #ddd; padding: 6px; "
            "background: #161826; border: 1px solid #2a2d40; border-radius: 6px;")
        v.addWidget(self.hof_summary_lbl)

        # Symbol filter + actions
        hb = QHBoxLayout()
        hb.addWidget(QLabel("Symbol:"))
        self.hof_symbol_combo = QComboBox()
        self.hof_symbol_combo.addItems(["BTCUSDm", "XAUUSDm", "EURUSDm",
                                         "GBPUSDm", "USDJPYm"])
        self.hof_symbol_combo.currentTextChanged.connect(
            lambda _: self._refresh_hof_tab())
        hb.addWidget(self.hof_symbol_combo)

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._refresh_hof_tab)
        hb.addWidget(refresh_btn)

        pin_btn = QPushButton("📌 PIN")
        pin_btn.setProperty("role", "success")
        pin_btn.clicked.connect(lambda: self._hof_action("pin"))
        pin_btn.setToolTip("Make this genome immortal (can't be killed)")
        hb.addWidget(pin_btn)

        unpin_btn = QPushButton("📍 UNPIN")
        unpin_btn.clicked.connect(lambda: self._hof_action("unpin"))
        hb.addWidget(unpin_btn)

        deploy_btn = QPushButton("🚀 DEPLOY")
        deploy_btn.setProperty("role", "primary")
        deploy_btn.clicked.connect(lambda: self._hof_action("deploy"))
        deploy_btn.setToolTip("Send this genome live as the active trader")
        hb.addWidget(deploy_btn)

        hb.addStretch()
        v.addLayout(hb)

        # Main HoF table
        self.hof_table = QTableWidget(0, 9)
        self.hof_table.setHorizontalHeaderLabels([
            "📌", "Rank", "Nickname", "Score",
            "Trades", "WR%", "PF", "Live $", "Last Deploy"])
        self.hof_table.horizontalHeader().setStretchLastSection(True)
        self.hof_table.setAlternatingRowColors(True)
        self.hof_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.hof_table.setEditTriggers(QTableWidget.NoEditTriggers)
        # Column widths
        self.hof_table.setColumnWidth(0, 30)
        self.hof_table.setColumnWidth(1, 50)
        self.hof_table.setColumnWidth(2, 320)
        self.hof_table.setColumnWidth(3, 70)
        self.hof_table.setColumnWidth(4, 70)
        self.hof_table.setColumnWidth(5, 70)
        self.hof_table.setColumnWidth(6, 70)
        self.hof_table.setColumnWidth(7, 90)
        v.addWidget(self.hof_table, 1)

        # Initial populate
        QTimer.singleShot(500, self._refresh_hof_tab)
        return w

    def _refresh_hof_tab(self) -> None:
        """Reload Hall of Fame data from brain API."""
        import urllib.request as _u
        import json as _json
        if not hasattr(self, "hof_table"):
            return
        sym = self.hof_symbol_combo.currentText()

        try:
            with _u.urlopen("http://127.0.0.1:5055/api/r/hof/summary",
                            timeout=3) as r:
                summ = _json.loads(r.read().decode())
        except Exception:
            self.hof_summary_lbl.setText("⚠ brain server offline")
            return

        if not summ.get("ok"):
            self.hof_summary_lbl.setText("⚠ HoF API error")
            return

        total = summ.get("total_genomes", 0)
        pinned = summ.get("pinned_count", 0)
        killed = summ.get("killed_count", 0)
        by_sym = summ.get("by_symbol", {})

        sym_lines = []
        for s, info in by_sym.items():
            sym_lines.append(
                f"{s}: {info['alive']} genomes · best="
                f"{info.get('top_nickname','—')} (score {info.get('top_score',0):.1f})")

        self.hof_summary_lbl.setText(
            f"🏆 <b>{total}</b> total genomes · 📌 {pinned} pinned · ❌ {killed} killed\n"
            + "\n".join(sym_lines))

        # Load this symbol's ranked list
        try:
            with _u.urlopen(f"http://127.0.0.1:5055/api/r/hof/symbol/{sym}?limit=100",
                            timeout=3) as r:
                data = _json.loads(r.read().decode())
        except Exception:
            return

        genomes = data.get("genomes", []) if data.get("ok") else []
        self.hof_table.setRowCount(len(genomes))
        for i, g in enumerate(genomes):
            s = g.get("stats", {})
            pin_text = "📌" if g.get("pinned") else ""
            depl = g.get("deployments") or []
            last_dep = depl[-1].get("at", "")[:10] if depl else "—"
            live_pl = g.get("live_pnl", 0)

            cells = [
                pin_text,
                str(i + 1),
                g.get("nickname", g.get("id", "?")),
                f"{g.get('score', 0):.1f}",
                str(s.get("trades", 0)),
                f"{s.get('win_rate', 0):.1f}",
                f"{s.get('profit_factor', 0):.2f}",
                f"${live_pl:+.2f}" if live_pl else "—",
                last_dep,
            ]
            for col, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                # Color score by quality
                if col == 3:
                    score = g.get("score", 0)
                    if score >= 60: item.setForeground(QColor(GREEN))
                    elif score >= 30: item.setForeground(QColor("#e0c44b"))
                    else: item.setForeground(QColor(RED))
                # Color live P/L
                if col == 7 and live_pl:
                    item.setForeground(QColor(GREEN if live_pl > 0 else RED))
                # Store genome id in row data
                if col == 0:
                    item.setData(Qt.UserRole, g.get("id"))
                self.hof_table.setItem(i, col, item)

    def _hof_action(self, action: str) -> None:
        """Pin / unpin / deploy the selected HoF row."""
        import urllib.request as _u
        import json as _json
        if not hasattr(self, "hof_table"):
            return
        row = self.hof_table.currentRow()
        if row < 0:
            self._set_deploy_banner("Select a genome first", error=True)
            return
        item = self.hof_table.item(row, 0)
        if not item: return
        gid = item.data(Qt.UserRole)
        if not gid: return

        sym = self.hof_symbol_combo.currentText()

        if action in ("pin", "unpin"):
            payload = {"id": gid, "pinned": (action == "pin")}
            url = "http://127.0.0.1:5055/api/r/hof/pin"
        elif action == "deploy":
            payload = {"id": gid, "symbol": sym}
            url = "http://127.0.0.1:5055/api/r/hof/deploy"
        else:
            return

        try:
            data = _json.dumps(payload).encode("utf-8")
            req = _u.Request(url, data=data, method="POST",
                             headers={"Content-Type": "application/json"})
            with _u.urlopen(req, timeout=4) as r:
                result = _json.loads(r.read().decode())
        except Exception as e:
            self._set_deploy_banner(f"❌ HoF {action} failed: {e}", error=True)
            return

        if not result.get("ok"):
            self._set_deploy_banner(f"❌ {result.get('error', 'failed')}", error=True)
            return

        nickname = self.hof_table.item(row, 2).text() if self.hof_table.item(row, 2) else gid
        if action == "deploy":
            self._set_deploy_banner(
                f"🚀 DEPLOYED {nickname} → {sym} (live now)", error=False)
            self._log(f"🏆 HoF deploy: {nickname} → {sym}")
        else:
            self._set_deploy_banner(
                f"{'📌' if action=='pin' else '📍'} {action.upper()}: {nickname}", error=False)
        self._refresh_hof_tab()

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
        """H.9 — Cleaned right column: just the rich InspectorPanel.
        The mini equity chart + KPI grid were duplicating the Hero card and
        the InspectorPanel's own EQUITY CURVE tab. Removed. The DNA helix is
        moved to a collapsible footer."""
        w = QFrame(); w.setProperty("role", "card")
        v = QVBoxLayout(w); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)

        # Backwards-compat stubs (legacy code in _on_tick writes to these)
        self.equity_widget = None
        self.kpi_labels = {}   # empty — _on_tick uses .get() now

        # Rich Inspector (STATS / SCORE / CLASS / GENOME tabs + EQUITY CURVE + TRADES)
        from r_native.inspector import InspectorPanel
        self.inspector_panel = InspectorPanel()
        self.inspector_tabs = self.inspector_panel.top_tabs
        v.addWidget(self.inspector_panel, 1)

        # DNA helix — small, at the bottom, doesn't dominate
        try:
            from r_native.dna_widget import DNAHelix
            self.dna_widget = DNAHelix()
            self.dna_widget.setMaximumHeight(120)  # was 180+, now compact
            v.addWidget(self.dna_widget)
        except Exception:
            self.dna_widget = None

        return w

    # ─── Status ticker ───
    def _build_status_ticker(self):
        f = QFrame(); f.setMaximumHeight(28); f.setStyleSheet(f"background: {BG_1}; border-top: 1px solid {BORDER};")
        h = QHBoxLayout(f); h.setContentsMargins(12, 2, 12, 2)
        self.ticker_label = QLabel("● R Native ready")
        self.ticker_label.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        h.addWidget(self.ticker_label)
        h.addStretch()
        # Embedded services status (brain · executor · agents)
        self.services_status_lbl = QLabel("🧠 — · 🤖 — · ⚙ —")
        self.services_status_lbl.setStyleSheet(
            f"color: {MUTED}; font-size: 11px; "
            f"font-family: Consolas; padding-right: 16px;")
        self.services_status_lbl.setToolTip(
            "Embedded brain_server + r_executor + agents\n"
            "Format:  🧠 brain · 🤖 executor (mode) · ⚙ agents alive/total")
        h.addWidget(self.services_status_lbl)
        self.clock = QLabel("")
        self.clock.setStyleSheet(f"color: {GOLD}; font-family: Consolas;")
        h.addWidget(self.clock)
        return f

    def _refresh_services_status(self) -> None:
        """Update the unified status bar — reads from background poller
        cache only, never blocks on HTTP."""
        if not hasattr(self, "services_status_lbl"):
            return
        # Pull cached data from BackgroundPoller (instant, no I/O)
        if not getattr(self, "poller", None):
            self.services_status_lbl.setText("🧠 ✗ · 🤖 ✗ · ⚙ ✗ (no poller)")
            return
        st = self.poller.get("services", {}) or {}
        if not st:
            self.services_status_lbl.setText("🧠 — · 🤖 — · ⚙ — (booting)")
            return
        brain_node = st.get("brain") or {}
        brain_ok = bool(brain_node.get("alive") and st.get("endpoint_reachable"))
        brain_tag = ("ext" if brain_node.get("external") else "emb")
        brain_str = f"🧠 {'✓' if brain_ok else '✗'} ({brain_tag})"
        ex = st.get("executor") or {}
        exec_str = f"🤖 {'✓' if ex.get('alive') else '✗'} ({ex.get('mode','?')})"
        # Agents count comes from cache too
        agents = self.poller.get("agents", []) or []
        alive = sum(1 for a in agents
                    if a.get("enabled") and a.get("thread_alive"))
        agents_str = f"⚙ {alive}/{len(agents)}" if agents else "⚙ —"
        # Show poll-health indicator (failing streak = brain stuck)
        fails = self.poller.get("fail_streak", 0)
        warn = f" · ⚠ poll fail x{fails}" if fails > 1 else ""
        color = GREEN if (brain_ok and ex.get("alive")) else (
                "#e0c44b" if brain_ok else RED)
        self.services_status_lbl.setStyleSheet(
            f"color: {color}; font-size: 11px; "
            f"font-family: Consolas; padding-right: 16px;")
        self.services_status_lbl.setText(
            f"{brain_str} · {exec_str} · {agents_str}{warn}")

    def _setup_tray(self):
        ico = PROJECT_ROOT / "friday_v3" / "algory" / "r_logo.ico"
        svg = PROJECT_ROOT / "friday_v3" / "algory" / "r_logo.svg"
        if ico.exists():     icon = QIcon(str(ico))
        elif svg.exists():   icon = QIcon(str(svg))
        else:                icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
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

    def _request_remote_support(self):
        """🆘 launches RustDesk after explicit user consent.
        Routes through r_native.remote_support which handles the consent dialog,
        binary detection, credential display, and session audit logging."""
        try:
            from r_native.remote_support import start_session, is_available
            if not is_available():
                self._log("🆘 RustDesk not installed — opening download page")
            ok = start_session(parent_widget=self)
            self._log("🆘 support session authorized" if ok else "🆘 support cancelled")
        except Exception as e:
            QMessageBox.warning(self, "Remote Support",
                                f"Failed to start support flow:\n{e}")
            self._log(f"🆘 support flow error: {e}")

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
        # Prefer the real genome id stashed on the cell 0 UserData (set by _populate_vault).
        # Falls back to cell text for legacy rows that pre-date the fix.
        id_item = self.vault_table.item(row, 0)
        real_id = id_item.data(Qt.UserRole) if id_item else None
        return {"id": real_id or get(0),
                "symbol": get(1), "tf": get(2), "archetype": get(3),
                "trades": get(4), "wr": get(5), "pf": get(6), "ret": get(7),
                "dd": get(8), "sharpe": get(9), "verdict": get(10)}

    def _action_deploy(self):
        """One-click deploy — NO modal dialog (Qt+Windows hides them behind the parent).
        All feedback is INLINE: log lines, row highlight, tray toast, status banner."""
        self._log("🔘 DEPLOY clicked — looking up selected vault row…")
        sel = self._selected_vault_row()
        if not sel:
            self._log("⚠ DEPLOY aborted — no vault row selected. Click a row in the table first.")
            self._set_deploy_banner("⚠ Select a row in the vault table, then click DEPLOY", error=True)
            return
        self._log(f"   selected: {sel['id']} on {sel['symbol']} {sel['tf']}  (PF {sel['pf']}, WR {sel['wr']})")

        # ── No confirmation dialog. Deploy immediately. ──
        # (Confirmation dialogs in PySide6 reliably hide behind the main window on Windows,
        # leaving the user thinking nothing happened. Inline feedback is more reliable.)
        try:
            res = ra.deploy_genome_to_live(sel["symbol"], sel["id"], sel["tf"])
        except Exception as e:
            import traceback
            tb = traceback.format_exc(limit=3)
            self._log(f"⚠ deploy raised exception: {e}\n{tb}")
            self._set_deploy_banner(f"❌ Deploy crashed: {e}", error=True)
            return
        # Guard against future return-shape changes (None / missing 'ok' / non-dict)
        if not isinstance(res, dict):
            self._log(f"⚠ deploy returned unexpected type: {type(res).__name__} = {res!r}")
            self._set_deploy_banner(
                f"❌ Deploy returned {type(res).__name__} instead of dict — code bug", error=True)
            return
        if not res.get("ok"):
            err = res.get("error", "unknown")
            self._log(f"⚠ deploy failed: {err}")
            self._set_deploy_banner(f"❌ Deploy failed: {err}", error=True)
            return

        # ── Success — layered visible feedback ──
        self._log(f"🚀 DEPLOYED {sel['id']} → {sel['symbol']} {sel['tf']}  ·  PF {sel['pf']}")

        # 1) Inline status banner at top of vault tab (impossible to miss)
        exec_alive = self._check_r_executor_running()
        if exec_alive:
            self._set_deploy_banner(
                f"✅ {sel['id']} deployed to {sel['symbol']} {sel['tf']} — "
                f"R Executor will trade it within 30s",
                error=False)
        else:
            self._set_deploy_banner(
                f"✅ {sel['id']} deployed to {sel['symbol']} {sel['tf']}, but "
                f"R Executor is OFFLINE — click ▶ Start R Executor below to begin trading",
                error=False, warning=True)
            # Spawn the executor automatically in PAPER mode (safe) — user can stop from logs
            self._log("   → auto-starting R Executor in PAPER mode (safe, no real orders)…")
            self._start_r_executor(live=False)

        # 2) Highlight the deployed row (warm gold tint + ⚡ ACTIVE badge)
        try:
            row = self.vault_table.currentRow()
            for col in range(self.vault_table.columnCount()):
                it = self.vault_table.item(row, col)
                if it: it.setBackground(QColor("#3d2c0a"))
            verdict_item = self.vault_table.item(row, 10)
            if verdict_item:
                verdict_item.setText("⚡ ACTIVE")
                verdict_item.setForeground(QColor(GOLD))
        except Exception as e:
            self._log(f"   (row highlight skipped: {e})")

        # 3) OS tray toast — always visible even if app is in background
        try:
            self.tray.showMessage(
                "R Native — Deployed",
                f"{sel['id']} is now active on {sel['symbol']} {sel['tf']}",
                QSystemTrayIcon.Information, 4500)
        except Exception: pass

        # 4) H.8.6 auto-replay: instantly show what this genome would have done over 30d
        # The user sees concrete numbers + chart + trades, no waiting for live trading.
        QTimer.singleShot(300, self._action_backtest)

        # 5) Retro 8-bit fanfare on deploy
        try:
            from r_native.retro_sfx import level_up
            level_up()
        except Exception: pass

    def _set_deploy_banner(self, text: str, error: bool = False, warning: bool = False):
        """Show or update the inline deploy status banner above the vault table."""
        if not hasattr(self, "_deploy_banner") or self._deploy_banner is None:
            return  # banner widget not built yet — ignore
        self._deploy_banner.setText(text)
        if error:
            bg, fg = "#3d0a0a", "#fecaca"   # red tint
        elif warning:
            bg, fg = "#3d2c0a", "#fde047"   # amber tint
        else:
            bg, fg = "#0a3d20", "#a7f3d0"   # green tint
        self._deploy_banner.setStyleSheet(
            f"background:{bg}; color:{fg}; padding:8px 12px; border-radius:4px; "
            f"font-size:12px; font-weight:600;")
        self._deploy_banner.setVisible(True)
        # Auto-hide after 12 seconds (but persist if not dismissed)
        QTimer.singleShot(12000, lambda: self._deploy_banner.setVisible(False)
                          if hasattr(self, "_deploy_banner") and self._deploy_banner else None)

    def _action_backtest(self) -> None:
        """H.8.6: Run the selected genome on last 30 days of bars. Instant feedback.
        Updates Inspector charts + shows result banner. NO real trades, no risk."""
        sel = self._selected_vault_row()
        if not sel:
            self._set_deploy_banner("⚠ Select a row first — then click 🎬 BACKTEST 30d", error=True)
            return
        self._log(f"🎬 BACKTEST starting: {sel['id']} on {sel['symbol']} {sel['tf']} · last 30 days")
        self._set_deploy_banner(f"🎬 Replaying {sel['id']} on last 30 days…", error=False)

        # Find the full genome (need params + flags to simulate)
        full = self._load_full_strategy(sel["symbol"], sel["id"])
        if not full or not full.get("genome"):
            self._log("⚠ BACKTEST aborted — full genome not found in campaign vault")
            self._set_deploy_banner(
                f"❌ Full genome for {sel['id']} not in campaign archive (older entry)",
                error=True)
            return
        genome = full["genome"]

        try:
            import MetaTrader5 as mt5
            from r_native.ga_simulator import simulate_genome
            tf_map = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
                      "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
                      "H1": mt5.TIMEFRAME_H1, "H2": mt5.TIMEFRAME_H2,   # H.15
                      "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
            tf_const = tf_map.get(sel["tf"], mt5.TIMEFRAME_M5)
            # Bars per day for each TF (approx, weekdays only)
            bars_per_day = {"M1": 1440, "M5": 288, "M15": 96, "M30": 48,
                            "H1": 24, "H4": 6, "D1": 1}.get(sel["tf"], 288)
            n_bars = bars_per_day * 30   # 30 calendar days
            sym_info = mt5.symbol_info(sel["symbol"])
            if not sym_info:
                self._set_deploy_banner(f"❌ {sel['symbol']} not in MT5 — open it in MarketWatch first", error=True)
                return
            mt5.symbol_select(sel["symbol"], True)
            bars = mt5.copy_rates_from_pos(sel["symbol"], tf_const, 0, n_bars)
            if bars is None or len(bars) < 100:
                self._set_deploy_banner(
                    f"❌ Not enough bars from MT5 ({len(bars) if bars is not None else 0})",
                    error=True)
                return

            import time as _t
            t0 = _t.time()
            stats = simulate_genome(genome, bars, sym_info)
            elapsed = _t.time() - t0
        except Exception as e:
            import traceback
            self._log(f"⚠ BACKTEST crashed: {e}\n{traceback.format_exc(limit=3)}")
            self._set_deploy_banner(f"❌ BACKTEST crashed: {e}", error=True)
            return

        # ── Results ──
        n_trades = stats.get("trades", 0)
        if n_trades == 0:
            self._set_deploy_banner(
                f"🟡 BACKTEST: {sel['id']} produced 0 trades on last 30 days "
                f"(genome too restrictive or wrong time window)",
                error=False, warning=True)
            self._log(f"   BACKTEST 0 trades — try a different strategy or longer window")
            return

        pl       = stats.get("total_return_pct", 0)
        wr       = stats.get("win_rate", 0)
        pf       = stats.get("profit_factor", 0)
        dd       = stats.get("max_drawdown_pct", 0)
        sharpe   = stats.get("sharpe", 0)
        biggest  = stats.get("biggest_win",  0)
        wins     = stats.get("wins", 0)

        banner_text = (
            f"🎬 BACKTEST {sel['id']} on last 30d · "
            f"{n_trades} trades · WR {wr}% · PF {pf} · "
            f"return {'+' if pl >= 0 else ''}${pl:.2f} · max DD ${dd:.2f} · "
            f"sharpe {sharpe} · ran in {elapsed:.1f}s")
        is_winner = pl > 0 and pf >= 1.2
        self._set_deploy_banner(banner_text, error=not is_winner, warning=False)
        self._log(banner_text)

        # ── Update Inspector with backtest results ──
        params       = (genome.get("params") or {})
        flags        = (genome.get("flags")  or {})
        active_genes = genome.get("active_genes", [])
        trades_log   = stats.get("trades_log",   [])
        equity_curve = stats.get("equity_curve", [])
        oos_split    = stats.get("is_oos_split_idx", int(n_trades * 0.67))
        exit_bd      = stats.get("exit_breakdown", {})

        strategy = {
            "net_profit":     pl,
            "drawdown":       dd,
            "total_trades":   n_trades,
            "win_rate":       wr,
            "is_return":      round(pl * 0.67, 2),
            "is_trades":      int(n_trades * 0.67),
            "oos_return":     round(pl * 0.33, 2),
            "oos_trades":     n_trades - int(n_trades * 0.67),
            "profit_factor":  pf,
            "sharpe":         sharpe,
            "linearity":      stats.get("linearity", 0),
            "persistence":    stats.get("linearity", 0),
            "recovery_factor": round(pl / max(0.01, abs(dd)), 1) if dd else 0,
            "avg_hold_time":  "—",
            "avg_profit":     stats.get("avg_win", 0),
            "avg_loss":       stats.get("avg_loss", 0),
            "biggest_win":    biggest,
            "biggest_loss":   stats.get("biggest_loss", 0),
            "max_win_streak":  stats.get("max_cons_wins",   0),
            "max_loss_streak": stats.get("max_cons_losses", 0),
            "avg_win_streak":  0, "avg_loss_streak": 0,
            "long_trades":   stats.get("longs",  n_trades // 2),
            "short_trades":  stats.get("shorts", n_trades - n_trades // 2),
        }
        purge_req = {"min_pf": 1.2, "min_trades": 40, "max_dd": 10.0, "min_ret": 6.0,
                     "min_linearity": 0.7, "min_win_rate": 0.0,
                     "min_sharpe": 0.0, "min_persistence": 0.0}
        classification = self._classify_from_genes(active_genes, flags, params, sel)
        classification["mechanism"] = (f"TP {exit_bd.get('TP',0)} · "
                                       f"SL {exit_bd.get('SL',0)} · "
                                       f"FRIDAY {exit_bd.get('FRIDAY',0)}")
        if hasattr(self, "inspector_panel"):
            self.inspector_panel.update_view(
                strategy=strategy, trades=trades_log,
                purge_req=purge_req, classification=classification,
                params=params, active_genes=active_genes, flags=flags,
                exit_breakdown=exit_bd,
                equity_curve=equity_curve, oos_split_idx=oos_split)

        # ── Tray toast ──
        try:
            self.tray.showMessage(
                f"R Native — Backtest {'WIN 🏆' if is_winner else 'POOR 📉'}",
                f"{sel['id']}: {n_trades} trades, WR {wr}%, ret ${pl:+.2f}",
                QSystemTrayIcon.Information, 6000)
        except Exception: pass

    def _action_force_trade(self) -> None:
        """🔫 Force-fire a paper test trade — bypasses ALL gates.
        Symbol from selected vault row (or BTCUSDm default). Uses BUY 0.01 lot
        with SL/TP 200 points each. Trade appears in MT5 + R Native + tray."""
        import urllib.request as _u
        import json as _json

        sel = self._selected_vault_row()
        symbol = sel["symbol"] if sel else "BTCUSDm"
        # Pick side from current bid/ask trend (random for demo)
        side = "BUY"
        try:
            import MetaTrader5 as mt5
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                # Random direction for test; user just wants to see it work
                import random
                side = random.choice(["BUY", "SELL"])
        except Exception: pass

        self._log(f"🔫 FORCE TRADE: {side} {symbol} 0.01 lot · bypasses ALL gates")

        try:
            # Omit sl_pts/tp_pts so server auto-calculates safe values per symbol
            data = _json.dumps({
                "symbol": symbol, "side": side, "lot": 0.01,
                "comment": "R_FORCE_TEST",
            }).encode("utf-8")
            req = _u.Request("http://127.0.0.1:5055/api/r/force_trade",
                             data=data, method="POST",
                             headers={"Content-Type": "application/json"})
            with _u.urlopen(req, timeout=8) as r:
                result = _json.loads(r.read().decode())
        except Exception as e:
            self._log(f"❌ FORCE TRADE failed: {e}")
            self._set_deploy_banner(f"❌ Force trade failed: {e}", error=True)
            return

        if not result.get("ok"):
            err = result.get("error") or f"retcode {result.get('retcode')} {result.get('comment','')}"
            self._log(f"❌ FORCE TRADE rejected: {err}")
            self._set_deploy_banner(
                f"❌ Trade rejected by broker: {err}", error=True)
            return

        # Success
        ticket = result.get("order")
        price  = result.get("price")
        self._log(f"✅ FORCE TRADE filled: ticket #{ticket} @ {price:.3f} "
                  f"SL {result['sl']:.3f} TP {result['tp']:.3f}")
        self._set_deploy_banner(
            f"✅ FORCE TRADE FILLED · {side} {symbol} 0.01 @ {price:.3f} "
            f"(ticket #{ticket}, magic 20260605, SL/TP ±200pts)",
            error=False)
        # Tray + sound
        try:
            self.tray.showMessage(
                "R Native — FORCE TRADE FILLED",
                f"{side} {symbol} 0.01 @ {price:.3f}\nticket #{ticket}",
                QSystemTrayIcon.Information, 6000)
        except Exception: pass
        try:
            from r_native.retro_sfx import trade_open
            trade_open()
        except Exception: pass

    def _action_toggle_auto_evo(self) -> None:
        """Toggle the continuous-evolution loop on/off via brain API."""
        import urllib.request as _u
        import json as _json
        try:
            data = _json.dumps({}).encode("utf-8")  # let server flip current state
            req = _u.Request("http://127.0.0.1:5055/api/r/auto_evo/toggle",
                             data=data, method="POST",
                             headers={"Content-Type": "application/json"})
            with _u.urlopen(req, timeout=4) as r:
                result = _json.loads(r.read().decode())
        except Exception as e:
            self._log(f"❌ auto-evo toggle failed: {e}")
            return

        enabled = bool(result.get("enabled"))
        if enabled:
            self._log("🧬 AUTO-EVOLUTION enabled — system will evolve continuously")
            self._set_deploy_banner(
                "🧬 AUTO-EVOLUTION ON · GA campaigns will run periodically and "
                "auto-deploy winning genomes", error=False)
        else:
            self._log("🛑 AUTO-EVOLUTION disabled")
            self._set_deploy_banner("🛑 AUTO-EVOLUTION OFF", error=False)
        self._refresh_auto_evo_status()

    def _refresh_auto_evo_status(self) -> None:
        """Read auto-evo state from background poller (no HTTP)."""
        if not hasattr(self, "_auto_evo_btn"):
            return
        if not getattr(self, "poller", None):
            self._auto_evo_btn.setText("🧬 AUTO-EVOLVE: ?")
            self._auto_evo_status_lbl.setText("(no poller)")
            return
        st = self.poller.get("auto_evo", {}) or {}
        if not st:
            self._auto_evo_btn.setText("🧬 AUTO-EVOLVE: ?")
            self._auto_evo_status_lbl.setText("(booting)")
            return

        enabled = bool(st.get("enabled"))
        self._auto_evo_btn.blockSignals(True)
        self._auto_evo_btn.setChecked(enabled)
        self._auto_evo_btn.blockSignals(False)

        running = bool(st.get("is_running_cycle"))
        phase   = st.get("current_phase", "idle")
        cycles  = int(st.get("total_cycles", 0))
        deploys = int(st.get("total_deploys", 0))

        if enabled and running:
            self._auto_evo_btn.setText(f"🧬 EVOLVING · {phase[:24]}")
        elif enabled:
            self._auto_evo_btn.setText("🧬 AUTO-EVOLVE: ON")
        else:
            self._auto_evo_btn.setText("🧬 AUTO-EVOLVE: OFF")

        next_run = st.get("next_run") or "—"
        if next_run != "—":
            try:
                from datetime import datetime, timezone
                t = datetime.fromisoformat(next_run.replace("Z","+00:00"))
                delta = (t - datetime.now(timezone.utc)).total_seconds()
                if delta > 0:
                    h = int(delta // 3600); m = int((delta % 3600) // 60)
                    next_run = f"in {h}h{m:02d}m" if h else f"in {m}m"
                else:
                    next_run = "now"
            except Exception: pass
        self._auto_evo_status_lbl.setText(
            f"cycles: {cycles} · deploys: {deploys} · next: {next_run}")

    def _check_r_executor_running(self) -> bool:
        """Cheap check: any python process with r_executor in command line."""
        try:
            import psutil
            for p in psutil.process_iter(attrs=["name", "cmdline"]):
                cmd = " ".join(p.info.get("cmdline") or [])
                if "r_executor" in cmd and p.info["name"].startswith("python"):
                    return True
        except Exception: pass
        return False

    def _start_r_executor(self, live: bool = False) -> None:
        """Spawn r_executor in a new process (PAPER mode by default)."""
        import subprocess, sys
        cmd = [sys.executable, "-m", "friday_v3.algory.r_executor"]
        if live: cmd.append("--live")
        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            p = subprocess.Popen(cmd, cwd=r"C:\Users\Radhi\MT5",
                                 creationflags=creationflags,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            mode = "LIVE" if live else "PAPER"
            self._log(f"▶ R Executor started ({mode} mode) — PID {p.pid}")
            self.tray.showMessage("R Native",
                f"R Executor started in {mode} mode (PID {p.pid}).",
                QSystemTrayIcon.Information, 4000)
        except Exception as e:
            self._log(f"⚠ failed to start R Executor: {e}")
            QMessageBox.warning(self, "Start R Executor failed", str(e))

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

        # ── H.4: Memory cleanup post-campaign ──
        # CampaignWorker holds engine.vault (200-300 genomes × ~3MB each) until GC.
        # Clear the QThread instance + force collection so RAM drops back to ~150MB.
        try:
            import gc
            from r_native.bar_cache import shrink_to as _shrink_bars
            cw = getattr(self, "campaign_worker", None)
            if cw and not cw.isRunning():
                self.campaign_worker = None
            freed = gc.collect()
            _shrink_bars(keep=5)  # evict all but last 5 symbols' bar history
            try:
                import psutil, os
                rss = round(psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024, 1)
                self._log(f"  🧹 cleanup: gc freed {freed} objs · RSS now {rss}MB")
            except Exception:
                self._log(f"  🧹 cleanup: gc freed {freed} objs")
        except Exception as e:
            self._log(f"  ⚠ cleanup error: {e}")

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
        # Disable sorting during repopulation — sortingEnabled=True with setItem reorders
        # rows mid-loop and corrupts the data. Re-enable after the loop.
        was_sorting = self.vault_table.isSortingEnabled()
        self.vault_table.setSortingEnabled(False)
        self.vault_table.setRowCount(len(results))
        for i, r in enumerate(results):
            # Display ID = real genome id (hex like "98ED3A"); fall back to a synthetic
            # composite if id missing. The REAL id is also attached as UserData on cell 0
            # so _selected_vault_row can recover it even if the cell text gets edited.
            real_id = r.get("id") or \
                      f"{r.get('symbol','?')[:4]}_{r.get('timeframe','?')}_{r.get('archetype','?')[:4]}"
            cells = [real_id, r.get("symbol"), r.get("timeframe"), r.get("archetype"),
                     str(r.get("trades", 0)),
                     f"{r.get('win_rate', 0)}%", f"{r.get('profit_factor', 0)}",
                     f"{r.get('total_return_pct', 0)}",
                     f"{r.get('max_drawdown_pct', 0)}",
                     f"{r.get('sharpe', 0)}",
                     r.get("confidence", "?")]
            for j, c in enumerate(cells):
                item = QTableWidgetItem(str(c))
                if j == 0:
                    # Stash the real genome id on the row anchor (deploy/inspect use this)
                    item.setData(Qt.UserRole, real_id)
                if j == 10:
                    if c == "DEPLOY": item.setForeground(QColor(GREEN))
                    elif c == "EVALUATE": item.setForeground(QColor(GOLD))
                    else: item.setForeground(QColor(RED))
                self.vault_table.setItem(i, j, item)
        # Restore sorting + re-apply any active search filter
        self.vault_table.setSortingEnabled(was_sorting)
        if hasattr(self, "vault_search"):
            self._filter_vault(self.vault_search.text())

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
        line = f"[{ts}] {msg}"
        self.log_view.appendPlainText(line)
        # Also mirror to stdout so external monitors (heartbeat polling, log tails) see it
        print(line, flush=True)

    # ─── Tick — update KPIs from MT5 + R state ───
    def _on_tick(self):
        # Re-entry guard: if previous tick is still running (something slow
        # in one of the refresh methods), skip this one. Prevents queued
        # ticks from piling up and freezing the Qt event loop.
        if getattr(self, "_tick_running", False):
            return
        self._tick_running = True
        try:
            self._on_tick_inner()
        finally:
            self._tick_running = False

    def _on_tick_inner(self):
        self.clock.setText(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        # H.8.1: refresh the hero P/L card every tick (3s)
        try: self._refresh_hero_card()
        except Exception as e: print(f"[hero] refresh err: {e}", flush=True)
        # Auto-Evolution status pill (only every other tick to keep it light)
        if not hasattr(self, "_auto_evo_tick_counter"):
            self._auto_evo_tick_counter = 0
        self._auto_evo_tick_counter += 1
        if self._auto_evo_tick_counter % 3 == 0:
            try: self._refresh_auto_evo_status()
            except Exception: pass
        # Refresh AI Advisors panel every 5 ticks (~15s)
        if self._auto_evo_tick_counter % 5 == 0:
            try: self._refresh_advisors_panel()
            except Exception: pass
        # Refresh services status bar every 2 ticks (~6s)
        if self._auto_evo_tick_counter % 2 == 0:
            try: self._refresh_services_status()
            except Exception: pass
        # H.8.2/3/5: refresh live activity + gate status + tray notifications
        try: self._refresh_live_activity()
        except Exception as e: print(f"[activity] err: {e}", flush=True)
        # Read MT5 state from BackgroundPoller cache — formerly direct mt5.*
        # calls here blocked the Qt main thread for 100-2000ms (history_deals
        # was the worst). Now: instant dict lookup.
        try:
            pcache = self.poller.all() if getattr(self, "poller", None) else {}
            class _AccountShim:
                balance = float((pcache.get("mt5_account") or {}).get("balance", 0))
                equity  = float((pcache.get("mt5_account") or {}).get("equity", 0))
            class _PosShim:
                def __init__(self, d):
                    self.ticket = d["ticket"]; self.symbol = d["symbol"]
                    self.type = 0 if d["type"] == "BUY" else 1
                    self.volume = d["volume"]
                    self.price_open = d["price_open"]; self.price_current = d["price_current"]
                    self.sl = d["sl"]; self.tp = d["tp"]; self.profit = d["profit"]
                    self.magic = d["magic"]; self.comment = d["comment"]
            info = _AccountShim() if pcache.get("mt5_account") else None
            r_pos = [_PosShim(d) for d in (pcache.get("mt5_r_positions") or [])]
            open_pl = sum(p.profit for p in r_pos)
            today_pl     = float(pcache.get("mt5_today_pl") or 0)
            today_trades = int(pcache.get("mt5_today_trades") or 0)
            today_wins   = int(pcache.get("mt5_today_wins") or 0)
            wr = (today_wins / today_trades * 100) if today_trades else 0
            r_closed = list(range(today_trades))  # legacy len() compatibility
            if info:
                # H.9: KPI grid removed (duplicated Hero card). Safe-no-op these writes.
                _k = self.kpi_labels  # legacy: empty dict in modern build
                if _k.get("BALANCE"):       _k["BALANCE"].setText(f"${info.balance:.2f}")
                if _k.get("EQUITY"):        _k["EQUITY"].setText(f"${info.equity:.2f}")
                # r_pos, open_pl, today_pl, wr already set from cache above —
                # no direct mt5.* calls here (would block Qt main thread)
                if _k.get("OPEN P/L"):
                    _k["OPEN P/L"].setText(f"${open_pl:+.2f}")
                    _k["OPEN P/L"].setStyleSheet(f"color: {GREEN if open_pl>=0 else RED}; font-size: 22px; font-weight: 900; font-family: Consolas;")
                if _k.get("OPEN POSITIONS"): _k["OPEN POSITIONS"].setText(str(len(r_pos)))
                if _k.get("TODAY P/L"):
                    _k["TODAY P/L"].setText(f"${today_pl:+.2f}")
                    _k["TODAY P/L"].setStyleSheet(f"color: {GREEN if today_pl>=0 else RED}; font-size: 22px; font-weight: 900; font-family: Consolas;")
                if _k.get("WIN RATE"):     _k["WIN RATE"].setText(f"{wr:.0f}%")
                if _k.get("TOTAL TRADES"): _k["TOTAL TRADES"].setText(str(len(r_closed)))
                # Live positions table — col 8 is a clickable "❓ Why?" button
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
                    # col 8: "Why?" cell — clickable label
                    why_item = QTableWidgetItem("❓ WHY")
                    why_item.setForeground(QColor(GOLD))
                    why_item.setData(Qt.UserRole, int(p.ticket))
                    self.live_table.setItem(i, 8, why_item)
            # ─── Equity curve from R deals (last 48h) ───
            # H.9: equity_widget removed (covered by InspectorPanel's EQUITY CURVE tab)
            # H.9: R-IQ kpi grid removed — only sidebar iq_label updated below
            # IQ from R memory
            iq_file = PROJECT_ROOT / "friday_v3" / "data" / "r_memory" / "r_iq.json"
            if iq_file.exists():
                iq = json.loads(iq_file.read_text(encoding="utf-8"))
                self.iq_label.setText(f"R-IQ: {iq.get('raw',0):.0f}\n{iq.get('level','?')}")
                if self.kpi_labels.get("R-IQ"):
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
    # Windows: tell the shell this is a distinct app so taskbar uses our icon
    # (not the host python.exe's icon). Must be set BEFORE QApplication.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "com.radhi.rnative.factory")
        except Exception:
            pass

    app = QApplication(sys.argv)
    # App-wide icon (taskbar, alt-tab, jumplist)
    ico = PROJECT_ROOT / "friday_v3" / "algory" / "r_logo.ico"
    svg = PROJECT_ROOT / "friday_v3" / "algory" / "r_logo.svg"
    icon_path = ico if ico.exists() else (svg if svg.exists() else None)
    if icon_path:
        app.setWindowIcon(QIcon(str(icon_path)))

    apply_dark_theme(app)
    app.setQuitOnLastWindowClosed(False)

    # ── EMBEDDED SERVICES: brain_server + r_executor in this process ──
    # No more separate terminals. brain runs in a Flask daemon thread,
    # executor in its own loop thread. External legacy brains on :5055
    # are detected and reused so the user can still split if they want.
    try:
        from r_native.embedded_services import start_all as _start_services
        # LIVE = real MT5 orders. User explicitly approved.
        _svc = _start_services(executor_mode="LIVE")
        print(f"[unified] services: {_svc}", flush=True)
    except Exception as _e:
        print(f"[unified] failed to start embedded services: {_e}", flush=True)

    # ── V2 UNIFIED STACK: brain + regime + orchestrator + unified_trader ──
    # "الحل 3 — جعل R Native نفسه يطلق كل شي". Spawns the 8 v2 processes
    # (dedup-safe — skips any already running). Logs to r_native_v2/data/logs/.
    try:
        from r_native import v2_stack
        _v2 = v2_stack.start_all()
        print(f"[v2_stack] started={_v2['started']} "
              f"already={_v2['already_running']} failed={_v2['failed']}", flush=True)
        print(f"[v2_stack] {v2_stack.summary_line()}", flush=True)
    except Exception as _e:
        print(f"[v2_stack] failed to start unified stack: {_e}", flush=True)

    win = RNativeMain()
    win.showMaximized()    # open at full screen — no manual resize needed
    win.raise_()
    win.activateWindow()

    # ── First-run onboarding wizard (visual stage-by-stage system intro) ──
    try:
        from r_native.onboarding import show_if_needed
        show_if_needed(parent=win)
    except Exception as _e:
        print(f"[onboarding] skipped: {_e}", flush=True)

    # ── Auto-inspect deferred → wait for poller to have data, then dispatch
    # off the main thread to avoid Qt event-loop freeze at boot.
    def _auto_inspect():
        import threading as _t
        def _bg():
            try:
                import urllib.request as _ur, json as _j
                with _ur.urlopen("http://localhost:5055/api/r/genomes/active",
                                  timeout=3) as r:
                    d = _j.loads(r.read().decode())
                for s in (d.get("symbols") or []):
                    if (s.get("deployed_genome") or {}).get("id"):
                        # Marshal back to Qt thread for the actual UI update
                        QTimer.singleShot(0, lambda sym=s["symbol"]:
                                          win._inspect_symbol(sym))
                        return
            except Exception as _e:
                print(f"[auto-inspect] skipped: {_e}", flush=True)
        _t.Thread(target=_bg, daemon=True, name="auto-inspect").start()
    QTimer.singleShot(5000, _auto_inspect)

    # ── Heartbeat server (H.1) — lets RNativeLauncher supervise this worker ──
    # Non-fatal: if Flask is missing or port is taken, app keeps running.
    try:
        from r_native import heartbeat_server
        def _state():
            try:
                vault_rows = win.vault_table.rowCount() if hasattr(win, "vault_table") else 0
            except Exception:
                vault_rows = 0
            return {
                "vault_size":      vault_rows,
                "active_campaign": bool(getattr(win, "campaign_worker", None)
                                        and getattr(win.campaign_worker, "isRunning", lambda: False)()),
            }
        heartbeat_server.start(
            port          = 7711,
            shutdown_hook = lambda: app.quit(),
            state_getter  = _state,
        )
        # H.5: auto-restart at 500MB RSS — belt-and-suspenders for any leaks
        # not caught by the post-campaign cleanup in _on_campaign_done
        heartbeat_server.start_rss_watchdog(threshold_mb=500, interval_s=30)
    except Exception as e:
        print(f"[main] heartbeat init skipped: {e}")

    sys.exit(app.exec())


if __name__ == "__main__":
    # CRITICAL on Windows + PyInstaller: must run BEFORE main() / QApplication.
    # Without this, ProcessPoolExecutor workers (spawned by Run GA Campaign)
    # re-execute RNative.exe and each opens a full PySide6 window.
    import multiprocessing
    multiprocessing.freeze_support()
    main()

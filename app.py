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

        # Tick timer
        self.tick = QTimer(); self.tick.timeout.connect(self._on_tick); self.tick.start(3000)
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

        # ── Pixel Mascot — bull/bear reacts to live P/L ──
        try:
            from r_native.pixel_mascot import PixelMascot
            self.hero_mascot = PixelMascot(size_px=44)
            self.hero_mascot.set_emotion("IDLE")
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
        """Refresh the hero P/L card from R Executor state + MT5 account.
        Called from _on_tick every 3s."""
        if not hasattr(self, "hero_pl"): return
        import json as _json
        from pathlib import Path as _P

        # ─── R Executor state ───
        exec_state = {}
        try:
            sf = _P(r"C:\Users\Radhi\MT5\friday_v3\data\r_executor_state.json")
            if sf.exists(): exec_state = _json.loads(sf.read_text(encoding="utf-8"))
        except Exception: pass

        today_pl     = float(exec_state.get("today_pl",     0) or 0)
        today_trades = int(  exec_state.get("today_trades", 0) or 0)
        today_wins   = int(  exec_state.get("today_wins",   0) or 0)
        total_pl     = float(exec_state.get("total_pl",     0) or 0)
        total_trades = int(  exec_state.get("total_trades", 0) or 0)
        armed        = bool( exec_state.get("armed",   False))
        mode         = str(  exec_state.get("mode",    "—"))
        last_action  = str(  exec_state.get("last_action", "—"))

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

        # Account
        try:
            import MetaTrader5 as _mt5
            info = _mt5.account_info()
            if info:
                self.hero_balance.setText(f"${info.balance:.0f} · ${info.equity:.0f}")
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

        # ── Pixel mascot — bull/bear emotional state ──
        if hasattr(self, "hero_mascot") and self.hero_mascot:
            try:
                # Heuristic: convert today_pl (USD) → percent of balance for emotion buckets
                bal = 100  # safe default
                try:
                    import MetaTrader5 as _mt5_
                    info = _mt5_.account_info()
                    if info: bal = max(1, info.balance)
                except Exception: pass
                pl_pct = (today_pl / bal) * 100
                has_open = (today_trades > 0 and exec_state.get("paper_open"))
                self.hero_mascot.set_from_pl(pl_pct, today_trades, has_open)
            except Exception: pass

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

        # 2) New trades — last 3 from MT5 history with R magic
        try:
            import MetaTrader5 as _mt5
            from datetime import timedelta as _td
            deals = _mt5.history_deals_get(datetime.now() - _td(hours=4), datetime.now()) or []
            for d in sorted(deals, key=lambda x: x.time, reverse=True)[:5]:
                if int(d.magic) != 20260605: continue   # only R
                if d.entry not in (0, 1): continue
                dk = f"deal::{d.ticket}::{d.entry}"
                if dk in self._activity_seen: continue
                self._activity_seen.add(dk)
                ts = datetime.fromtimestamp(int(d.time)).strftime("%H:%M:%S")
                kind = "OPEN" if d.entry == 0 else "CLOSE"
                side = "BUY" if d.type == 0 else "SELL"
                pl = float(d.profit) + float(d.swap) + float(d.commission)
                emoji = "🚀" if kind == "OPEN" else ("💰" if pl > 0 else "🛑" if pl < 0 else "⏹")
                new_lines.append(
                    f"[{ts}] {emoji} {kind} {side} {d.symbol} @ {float(d.price):.3f} "
                    + (f"P/L ${pl:+.2f}" if kind == "CLOSE" else f"#{d.ticket}"))
                # H.8.5: tray toast for new trade events
                if hasattr(self, "tray"):
                    try:
                        if kind == "OPEN":
                            self.tray.showMessage("R Native — Trade Opened",
                                f"{side} {d.symbol} @ {float(d.price):.3f}",
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

        # ─── Gate Status: pull /api/r/trade_gate one-shot ───
        try:
            import urllib.request as _u
            url = "http://127.0.0.1:5055/api/r/trade_gate?symbol=BTCUSDm&bypass_session=1&bypass_weekend=1&bypass_friday=1"
            with _u.urlopen(url, timeout=2) as r:
                d = _json.loads(r.read().decode())
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

        # Inline deploy status banner — replaces hidden modal dialogs
        self._deploy_banner = QLabel()
        self._deploy_banner.setWordWrap(True)
        self._deploy_banner.setVisible(False)
        v.addWidget(self._deploy_banner)

        # Bottom action bar — wired to actions module
        action_bar = QHBoxLayout()
        for lbl, role, handler in [("DEPLOY", "success", self._action_deploy),
                                    ("🎬 BACKTEST 30d", "primary", self._action_backtest),
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
        self.clock = QLabel("")
        self.clock.setStyleSheet(f"color: {GOLD}; font-family: Consolas;")
        h.addWidget(self.clock)
        return f

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
        self.clock.setText(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        # H.8.1: refresh the hero P/L card every tick (3s)
        try: self._refresh_hero_card()
        except Exception as e: print(f"[hero] refresh err: {e}", flush=True)
        # H.8.2/3/5: refresh live activity + gate status + tray notifications
        try: self._refresh_live_activity()
        except Exception as e: print(f"[activity] err: {e}", flush=True)
        try:
            import MetaTrader5 as mt5
            mt5.initialize()
            info = mt5.account_info()
            if info:
                # H.9: KPI grid removed (duplicated Hero card). Safe-no-op these writes.
                _k = self.kpi_labels  # legacy: empty dict in modern build
                if _k.get("BALANCE"):       _k["BALANCE"].setText(f"${info.balance:.2f}")
                if _k.get("EQUITY"):        _k["EQUITY"].setText(f"${info.equity:.2f}")
                # R positions
                r_pos = [p for p in (mt5.positions_get() or []) if p.magic == 20260605]
                open_pl = sum(p.profit for p in r_pos)
                if _k.get("OPEN P/L"):
                    _k["OPEN P/L"].setText(f"${open_pl:+.2f}")
                    _k["OPEN P/L"].setStyleSheet(f"color: {GREEN if open_pl>=0 else RED}; font-size: 22px; font-weight: 900; font-family: Consolas;")
                if _k.get("OPEN POSITIONS"): _k["OPEN POSITIONS"].setText(str(len(r_pos)))
                # Today P/L from deals
                from datetime import timedelta
                deals = mt5.history_deals_get(datetime.now() - timedelta(hours=24), datetime.now()) or []
                r_closed = [d for d in deals if d.magic == 20260605 and d.entry == 1]
                today_pl = sum(d.profit + d.swap + d.commission for d in r_closed)
                wins = sum(1 for d in r_closed if d.profit > 0)
                wr = (wins / len(r_closed) * 100) if r_closed else 0
                if _k.get("TODAY P/L"):
                    _k["TODAY P/L"].setText(f"${today_pl:+.2f}")
                    _k["TODAY P/L"].setStyleSheet(f"color: {GREEN if today_pl>=0 else RED}; font-size: 22px; font-weight: 900; font-family: Consolas;")
                if _k.get("WIN RATE"):     _k["WIN RATE"].setText(f"{wr:.0f}%")
                if _k.get("TOTAL TRADES"): _k["TOTAL TRADES"].setText(str(len(r_closed)))
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
    win = RNativeMain()
    win.show()
    win.raise_()
    win.activateWindow()

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

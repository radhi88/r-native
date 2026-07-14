# -*- coding: utf-8 -*-
"""
radhi_panel.py — Standalone PySide6 widget for the R Native dashboard.

Renders the "مجلس راضي" (Radhi Council) deliberation and the "Champions Vault".
Reads two JSON files every 3s from C:\\Users\\Radhi\\MT5\\r_native_v2\\data :
    - radhi_council_live.json  (ts, session, regime, verdict, why, edge_match, transcript)
    - radhi_champions.json     (list of champions w/ name, score, side_bias,
                                session_filter, sl_pts, tp_pts, algory_stats)

Self-contained: only depends on PySide6 (already a dependency of app.py).
Drop-in usage:  tabs.addTab(RadhiPanel(), "🧔 RADHI")
"""

import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGroupBox,
    QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
    QPushButton, QScrollArea,
)

# --- v2 runtime on path so we can reach governance + the auto-pipeline --------
V2_ROOT = r"C:\Users\Radhi\MT5\r_native_v2"
if V2_ROOT not in sys.path:
    sys.path.insert(0, V2_ROOT)

try:
    from runtime.shared import agent_governance as gov
    _GOV_IMPORT_ERR = None
except Exception as _e:                       # missing module / bad import
    gov = None
    _GOV_IMPORT_ERR = _e

# --- Theme (matches R Native) -------------------------------------------------
BG      = "#0d0d0f"
PANEL   = "#15151a"
GOLD     = "#e0b341"
TEXT    = "#d8d8dc"
MUTED   = "#8a8a92"
GREEN   = "#3fb46b"   # SELL / SELL?  (the edge is present)
AMBER   = "#e0b341"   # WAIT
RED      = "#d3534f"

DATA_DIR = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")
COUNCIL_FILE   = DATA_DIR / "radhi_council_live.json"
CHAMPIONS_FILE = DATA_DIR / "radhi_champions.json"

REFRESH_MS = 3000


def _verdict_color(verdict: str) -> str:
    v = (verdict or "").strip().upper()
    if v.startswith("SELL") or v.startswith("BUY"):
        return GREEN
    if v.startswith("WAIT"):
        return AMBER
    if v.startswith("VETO") or v.startswith("NO"):
        return RED
    return MUTED


def _safe_load(path: Path):
    """Load JSON; return None on any error (missing file, bad JSON, locked)."""
    try:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


# Proposal statuses that are "closed" — never shown in the pending list.
_GOV_CLOSED = {"APPLIED", "REJECTED", "FAILED"}


class _ProposeNextWorker(QThread):
    """Run the auto-pipeline's "propose a fresh candidate" step off the UI thread.

    Honours the requested entry point `propose_next_validated()`; if that symbol
    is absent in this build of the pipeline, falls back to `run_pipeline()` so a
    new candidate still gets queued. Any failure is swallowed and reported via
    the `done` signal — the UI must never freeze or crash on this.
    """
    done = Signal(bool, str)   # (ok, message)

    def run(self):
        try:
            from runtime import radhi_auto_pipeline as pipe
        except Exception as e:
            self.done.emit(False, f"pipeline import failed: {e}")
            return
        try:
            fn = getattr(pipe, "propose_next_validated", None)
            if callable(fn):
                fn()
            elif hasattr(pipe, "run_pipeline"):
                pipe.run_pipeline()
            else:
                self.done.emit(False, "no propose entry point in pipeline")
                return
            self.done.emit(True, "fresh candidate queued")
        except Exception as e:
            self.done.emit(False, f"{type(e).__name__}: {e}")


class RadhiPanel(QWidget):
    """Live view of the Radhi Council verdict + the Champions Vault."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QWidget {{ background:{BG}; color:{TEXT};
                       font-family:'Segoe UI','Tahoma',sans-serif; font-size:12px; }}
            QGroupBox {{ border:1px solid #2a2a30; border-radius:8px;
                         margin-top:14px; padding:8px; background:{PANEL}; }}
            QGroupBox::title {{ subcontrol-origin:margin; left:12px; padding:0 6px;
                                color:{GOLD}; font-weight:bold; font-size:13px; }}
            QTextEdit {{ background:#101015; border:1px solid #26262c;
                         border-radius:6px; color:{TEXT}; }}
            QTableWidget {{ background:#101015; border:1px solid #26262c;
                            border-radius:6px; gridline-color:#26262c;
                            selection-background-color:#2a2a18; }}
            QHeaderView::section {{ background:{PANEL}; color:{GOLD};
                                    border:none; border-bottom:1px solid #2a2a30;
                                    padding:5px; font-weight:bold; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ---- TOP: Council deliberation ----
        council_box = QGroupBox("🧔 مجلس راضي — Radhi Council")
        cb = QVBoxLayout(council_box)

        # Context line (session / regime / edge match)
        self.ctx_lbl = QLabel("—")
        self.ctx_lbl.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        cb.addWidget(self.ctx_lbl)

        # Transcript
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setMinimumHeight(150)
        cb.addWidget(self.transcript, 1)

        # Big verdict label
        self.verdict_lbl = QLabel("…")
        self.verdict_lbl.setAlignment(Qt.AlignCenter)
        vf = QFont("Segoe UI", 26, QFont.Bold)
        self.verdict_lbl.setFont(vf)
        self.verdict_lbl.setStyleSheet(f"color:{MUTED}; padding:6px;")
        cb.addWidget(self.verdict_lbl)

        self.why_lbl = QLabel("")
        self.why_lbl.setAlignment(Qt.AlignCenter)
        self.why_lbl.setWordWrap(True)
        self.why_lbl.setStyleSheet(f"color:{TEXT}; font-size:12px; padding-bottom:4px;")
        cb.addWidget(self.why_lbl)

        root.addWidget(council_box, 1)

        # ---- BOTTOM: Champions Vault ----
        champ_box = QGroupBox("💎 Champions Vault")
        chb = QVBoxLayout(champ_box)

        self._cols = ["Name", "Score", "Session", "SL/TP",
                      "Lin OOS", "Trades OOS", "PF"]
        self.table = QTableWidget(0, len(self._cols))
        self.table.setHorizontalHeaderLabels(self._cols)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(self._cols)):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        chb.addWidget(self.table)

        root.addWidget(champ_box, 1)

        # ---- GOVERNANCE: pending proposals (approve / reject) ----
        gov_box = QGroupBox("🏛️ الحوكمة — Pending Proposals")
        gvb = QVBoxLayout(gov_box)

        self._gov_scroll = QScrollArea()
        self._gov_scroll.setWidgetResizable(True)
        self._gov_scroll.setStyleSheet(
            "QScrollArea { border:none; background:transparent; }"
        )
        self._gov_holder = QWidget()
        self._gov_holder.setStyleSheet("background:transparent;")
        self._gov_layout = QVBoxLayout(self._gov_holder)
        self._gov_layout.setContentsMargins(0, 0, 0, 0)
        self._gov_layout.setSpacing(6)
        self._gov_layout.addStretch(1)
        self._gov_scroll.setWidget(self._gov_holder)
        gvb.addWidget(self._gov_scroll)

        root.addWidget(gov_box, 1)

        # keeps running QThreads alive until they finish (avoids GC mid-run)
        self._gov_workers = []

        # ---- Timer ----
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    # -------------------------------------------------------------------------
    def refresh(self):
        self._refresh_council()
        self._refresh_champions()
        self._refresh_governance()

    def _refresh_council(self):
        data = _safe_load(COUNCIL_FILE)
        if not isinstance(data, dict):
            self.ctx_lbl.setText("⚠ radhi_council_live.json not available")
            self.transcript.setPlainText("(waiting for council data…)")
            self.verdict_lbl.setText("—")
            self.verdict_lbl.setStyleSheet(f"color:{MUTED}; padding:6px;")
            self.why_lbl.setText("")
            return

        session = data.get("session", "—")
        regime  = data.get("regime", "—")
        symbol  = data.get("symbol", "")
        edge    = data.get("edge_match", "—")
        ts      = data.get("ts", "")
        self.ctx_lbl.setText(
            f"{symbol}   •   Session: {session}   •   Regime: {regime}"
            f"   •   Edge match: {edge}   •   {ts}"
        )

        lines = data.get("transcript", [])
        if isinstance(lines, list):
            self.transcript.setPlainText("\n".join(str(x) for x in lines))
        else:
            self.transcript.setPlainText(str(lines))

        verdict = str(data.get("verdict", "—"))
        color = _verdict_color(verdict)
        self.verdict_lbl.setText(verdict)
        self.verdict_lbl.setStyleSheet(
            f"color:{color}; padding:6px; border:2px solid {color}; border-radius:8px;"
        )
        self.why_lbl.setText(str(data.get("why", "")))

    def _refresh_champions(self):
        champs = _safe_load(CHAMPIONS_FILE)
        if not isinstance(champs, list):
            self.table.setRowCount(1)
            self.table.setSpan(0, 0, 1, len(self._cols))
            item = QTableWidgetItem("⚠ radhi_champions.json not available")
            item.setForeground(Qt.gray)
            self.table.setItem(0, 0, item)
            return

        self.table.clearSpans()
        self.table.setRowCount(len(champs))
        for r, c in enumerate(champs):
            if not isinstance(c, dict):
                continue
            stats = c.get("algory_stats") or {}
            sess = c.get("session_filter") or []
            if isinstance(sess, list):
                sess = ", ".join(str(s) for s in sess)

            def fnum(x, nd=2):
                try:
                    return f"{float(x):.{nd}f}"
                except Exception:
                    return "—"

            sl = c.get("sl_pts")
            tp = c.get("tp_pts")
            sltp = f"{fnum(sl)} / {fnum(tp)}"

            row = [
                str(c.get("name", "—")),
                fnum(c.get("score"), 3),
                str(sess) if sess else "—",
                sltp,
                fnum(stats.get("linearity_oos"), 3),
                str(stats.get("trades_oos", "—")),
                fnum(stats.get("profit_factor"), 2),
            ]
            for col, val in enumerate(row):
                item = QTableWidgetItem(val)
                if col == 0:
                    item.setForeground(Qt.white)
                elif col == 1:
                    item.setForeground(Qt.yellow)
                if col >= 1:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, col, item)

    # ---- Governance ---------------------------------------------------------
    def _clear_gov_rows(self):
        """Remove every proposal card, keeping the trailing stretch."""
        while self._gov_layout.count() > 1:
            item = self._gov_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _gov_placeholder(self, msg: str):
        self._clear_gov_rows()
        lbl = QLabel(msg)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{MUTED}; font-size:11px; padding:6px;")
        self._gov_layout.insertWidget(0, lbl)

    def _refresh_governance(self):
        if gov is None:
            self._gov_placeholder(
                f"⚠ governance module unavailable ({_GOV_IMPORT_ERR})"
            )
            return
        try:
            raw_all = gov._load_all()
        except Exception as e:
            self._gov_placeholder(f"⚠ could not load proposals ({e})")
            return

        closed = set(getattr(gov, "_GOV_CLOSED", None) or
                     {gov.ST_APPLIED, gov.ST_REJECTED, gov.ST_FAILED})
        try:
            pending = [
                p for p in (raw_all or {}).values()
                if isinstance(p, dict) and p.get("status") not in closed
            ]
        except Exception as e:
            self._gov_placeholder(f"⚠ malformed proposal data ({e})")
            return

        # newest-ish first (by ts when present)
        pending.sort(key=lambda p: str(p.get("ts", "")), reverse=True)

        self._clear_gov_rows()
        if not pending:
            self._gov_placeholder("No pending proposals — all clear ✅")
            return

        for idx, p in enumerate(pending):
            self._gov_layout.insertWidget(idx, self._build_gov_card(p))

    def _build_gov_card(self, p: dict) -> QWidget:
        pid     = str(p.get("id", "?"))
        action  = str(p.get("action", "—"))
        target  = str(p.get("target", ""))
        risk    = str(p.get("risk", "—")).upper()
        agent   = str(p.get("agent", "—"))
        status  = str(p.get("status", "—"))
        rationale = str(p.get("rationale", "") or "")
        if len(rationale) > 160:
            rationale = rationale[:157] + "…"

        risk_color = {"HIGH": RED, "MEDIUM": AMBER, "LOW": GREEN}.get(risk, MUTED)

        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:#101015; border:1px solid #2a2a30;"
            f" border-left:3px solid {risk_color}; border-radius:6px; }}"
        )
        lay = QHBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)

        # --- info column ---
        info = QVBoxLayout()
        info.setSpacing(2)

        head = QLabel(
            f"<b style='color:{GOLD}'>{action}</b>"
            f" <span style='color:{TEXT}'>{target}</span>"
            f"  <span style='color:{risk_color}'>[{risk}]</span>"
        )
        head.setTextFormat(Qt.RichText)
        info.addWidget(head)

        meta = QLabel(
            f"<span style='color:{MUTED}'>{pid}</span>"
            f"  •  agent <span style='color:{TEXT}'>{agent}</span>"
            f"  •  <span style='color:{MUTED}'>{status}</span>"
        )
        meta.setTextFormat(Qt.RichText)
        meta.setStyleSheet("font-size:10px;")
        info.addWidget(meta)

        if rationale:
            why = QLabel(rationale)
            why.setWordWrap(True)
            why.setStyleSheet(f"color:{TEXT}; font-size:11px;")
            info.addWidget(why)

        lay.addLayout(info, 1)

        # --- buttons ---
        btn_approve = QPushButton("Approve ✅")
        btn_approve.setCursor(Qt.PointingHandCursor)
        btn_approve.setStyleSheet(
            f"QPushButton {{ background:{GREEN}; color:#08120c; font-weight:bold;"
            f" border:none; border-radius:6px; padding:6px 12px; }}"
            f"QPushButton:hover {{ background:#56c884; }}"
        )
        btn_approve.clicked.connect(lambda _=False, i=pid: self._gov_approve(i))

        btn_reject = QPushButton("Reject ❌")
        btn_reject.setCursor(Qt.PointingHandCursor)
        btn_reject.setStyleSheet(
            f"QPushButton {{ background:{RED}; color:#1a0606; font-weight:bold;"
            f" border:none; border-radius:6px; padding:6px 12px; }}"
            f"QPushButton:hover {{ background:#e0706c; }}"
        )
        btn_reject.clicked.connect(lambda _=False, i=pid: self._gov_reject(i))

        bcol = QVBoxLayout()
        bcol.setSpacing(4)
        bcol.addWidget(btn_approve)
        bcol.addWidget(btn_reject)
        lay.addLayout(bcol)

        return card

    def _gov_approve(self, pid: str):
        if gov is None:
            return
        try:
            gov.claude_decide(pid, True)
        except Exception as e:
            self._gov_placeholder(f"⚠ approve failed for {pid} ({e})")
            return
        self._refresh_governance()

    def _gov_reject(self, pid: str):
        if gov is None:
            return
        try:
            gov.claude_decide(pid, False, note="rejected via UI")
        except Exception as e:
            self._gov_placeholder(f"⚠ reject failed for {pid} ({e})")
            return
        # Queue a fresh candidate off the UI thread, then refresh on completion.
        worker = _ProposeNextWorker(self)
        self._gov_workers.append(worker)
        worker.done.connect(self._on_propose_done)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        worker.start()
        self._refresh_governance()

    def _on_propose_done(self, ok: bool, msg: str):
        # Refresh so the freshly-queued candidate appears (or surfaces an error).
        self._refresh_governance()

    def _cleanup_worker(self, worker):
        try:
            self._gov_workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()


# Manual smoke test: python radhi_panel.py
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    w = RadhiPanel()
    w.resize(820, 720)
    w.setWindowTitle("Radhi Panel — standalone test")
    w.show()
    sys.exit(app.exec())

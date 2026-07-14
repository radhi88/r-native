"""r_native/son_cockpit.py — 🧬 OUR SON live cockpit (widget-based, no text dump).

Born 2026-05-30 from the user's mandate: "استمر في تطويره بالواجهة والكفاءة
بأفضل المميزات والأدوات ويكون نظام احترافي غير عادي".

Replaces the old QPlainTextEdit wall in app._build_son_tab with real widgets:
  • per-symbol CARDS — stage badge, genome, MTF bias chips, RSI/pressure,
    BUY/SELL condition PILLS (each condition its own colored pill + n/4 tally)
  • services health dots, regime + gate strip, live decisions feed
  • EFFICIENCY: refresh timer early-exits while the tab is not visible, so the
    12 JSON reads/1.5s cost nothing when the user is on another tab.

Read-only: this file never writes; it only renders r_native_v2/data/*.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout,
                               QLabel, QScrollArea, QSizePolicy)
from PySide6.QtCore import Qt, QTimer

# Palette — unified with app.py / inspector.py
GOLD, GREEN, RED = "#fbbf24", "#10b981", "#ef4444"
TEXT, MUTED = "#f1f5f9", "#94a3b8"
BG_1, BG_2, BG_3 = "#13131a", "#1a1a23", "#0c0e18"
BORDER = "#2d2d3a"
BLUE, VIOLET = "#60a5fa", "#a78bfa"

DATA = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")

STAGE_STYLE = {   # stage -> (icon, badge bg, badge fg)
    "FIRING":     ("🎯", "#0d3a2a", GREEN),
    "MANAGING":   ("🛡️", "#3a2f0d", GOLD),
    "WAITING":    ("⏳", BG_2, MUTED),
    "NO_SIGNAL":  ("😴", BG_2, MUTED),
    "ML_BLOCK":   ("🧠", "#2a1a3a", VIOLET),
    "LOW_CONF":   ("🤏", BG_2, MUTED),
    "FROZEN":     ("🧊", "#0d2a3a", BLUE),
    "PAUSED":     ("⏸", "#3a0d0d", RED),
    "STRUCT_VETO": ("🧱", BG_2, MUTED),
    "SPREAD":     ("📏", BG_2, MUTED),
    "SESSION":    ("🕐", BG_2, MUTED),
}
SHORT = {"XAUUSDm": "XAU · الذهب", "XAGUSDm": "XAG · الفضة",
         "BTCUSDm": "BTC · بيتكوين", "EURUSDm": "EUR", "GBPUSDm": "GBP",
         "USDJPYm": "JPY", "USDCADm": "CAD", "AUDUSDm": "AUD",
         "NZDUSDm": "NZD", "USDCHFm": "CHF", "EURJPYm": "EURJPY"}


def _rd(name: str) -> dict:
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _age(name: str) -> float:
    try:
        return time.time() - (DATA / name).stat().st_mtime
    except Exception:
        return 9999.0


class _Pill(QLabel):
    """One entry condition — green filled when passing, dim red when not."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(72)

    def set_state(self, ok: bool, text: str) -> None:
        self.setText(("✓ " if ok else "✗ ") + text)
        if ok:
            self.setStyleSheet(
                f"background:#0d3a2a; color:{GREEN}; border:1px solid #14532d;"
                f" border-radius:9px; padding:2px 10px; font-family:Consolas;"
                f" font-size:11px; font-weight:700;")
        else:
            self.setStyleSheet(
                f"background:{BG_3}; color:#7f4a4a; border:1px solid #3a1d1d;"
                f" border-radius:9px; padding:2px 10px; font-family:Consolas;"
                f" font-size:11px;")


class _Chip(QLabel):
    """Timeframe bias chip: M1/M5/M15/H1 — green UP, red DOWN, gray flat."""

    def __init__(self, tf: str, parent=None):
        super().__init__(parent)
        self.tf = tf
        self.setAlignment(Qt.AlignCenter)
        self.setFixedWidth(52)

    def set_dir(self, d: str) -> None:
        d = (d or "?").upper()
        arrow, col = {"UP": ("↑", GREEN), "DOWN": ("↓", RED)}.get(d, ("·", MUTED))
        self.setText(f"{self.tf} {arrow}")
        self.setStyleSheet(
            f"background:{BG_3}; color:{col}; border:1px solid {BORDER};"
            f" border-radius:4px; padding:2px 4px; font-family:Consolas;"
            f" font-size:11px; font-weight:800;")


class SymbolCard(QFrame):
    """Live card for one symbol: identity, bias, and BUY/SELL condition pills."""

    def __init__(self, sym: str, parent=None):
        super().__init__(parent)
        self.sym = sym
        self.setStyleSheet(
            f"QFrame {{ background:{BG_2}; border:1px solid {BORDER};"
            f" border-radius:8px; }} QLabel {{ border:none; background:transparent; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        # Row 1 — identity: name · stage badge · genome (+ live metrics right)
        r1 = QHBoxLayout()
        self.name_lbl = QLabel(SHORT.get(sym, sym))
        self.name_lbl.setStyleSheet(
            f"color:{TEXT}; font-size:15px; font-weight:900;")
        self.stage_lbl = QLabel("—")
        self.genome_lbl = QLabel("")
        self.genome_lbl.setStyleSheet(f"color:{MUTED}; font-size:11px; font-family:Consolas;")
        self.metrics_lbl = QLabel("")
        self.metrics_lbl.setStyleSheet(f"color:{MUTED}; font-family:Consolas; font-size:12px;")
        r1.addWidget(self.name_lbl)
        r1.addWidget(self.stage_lbl)
        r1.addWidget(self.genome_lbl)
        r1.addStretch()
        r1.addWidget(self.metrics_lbl)
        v.addLayout(r1)

        # Row 2 — stage detail / why blocked (the son explains himself)
        self.detail_lbl = QLabel("")
        self.detail_lbl.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.detail_lbl.setWordWrap(True)
        v.addWidget(self.detail_lbl)

        # Row 3 — MTF bias chips + tally
        r3 = QHBoxLayout()
        r3.setSpacing(4)
        self.chips = {tf: _Chip(tf.upper()) for tf in ("m1", "m5", "m15", "h1")}
        for c in self.chips.values():
            r3.addWidget(c)
        self.tally_lbl = QLabel("")
        self.tally_lbl.setStyleSheet(f"color:{TEXT}; font-family:Consolas; font-size:12px; font-weight:700;")
        r3.addSpacing(8)
        r3.addWidget(self.tally_lbl)
        r3.addStretch()
        v.addLayout(r3)

        # Rows 4/5 — BUY and SELL condition pill rows
        self.buy_title, self.buy_pills, buy_row = self._side_row("شراء", GREEN)
        self.sell_title, self.sell_pills, sell_row = self._side_row("بيع", RED)
        v.addLayout(buy_row)
        v.addLayout(sell_row)

        # Signal strip (hidden unless the son actually has a live signal)
        self.signal_lbl = QLabel("")
        self.signal_lbl.setVisible(False)
        v.addWidget(self.signal_lbl)

    def _side_row(self, title: str, color: str):
        row = QHBoxLayout()
        row.setSpacing(6)
        t = QLabel(title)
        t.setFixedWidth(78)
        t.setAlignment(Qt.AlignCenter)
        row.addWidget(t)
        pills = [_Pill() for _ in range(4)]
        for p in pills:
            row.addWidget(p)
        row.addStretch()
        return t, pills, row

    @staticmethod
    def _style_title(lbl: QLabel, color: str, ready: bool, n_ok: int) -> None:
        if ready:
            lbl.setStyleSheet(
                f"background:{color}; color:#0b0b10; border-radius:9px;"
                f" font-weight:900; font-size:12px; padding:2px;")
        else:
            lbl.setStyleSheet(
                f"background:{BG_3}; color:{color}; border:1px solid {BORDER};"
                f" border-radius:9px; font-weight:800; font-size:12px; padding:2px;")
        lbl.setText(("🟢 شراء " if color == GREEN else "🔴 بيع ") + f"{n_ok}/4")

    def update_card(self, st: dict, snap: dict, params: dict) -> None:
        stage = st.get("stage", "?")
        icon, bg, fg = STAGE_STYLE.get(stage, ("•", BG_2, MUTED))
        self.stage_lbl.setText(f"{icon} {stage}")
        self.stage_lbl.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:8px; padding:2px 10px;"
            f" font-size:11px; font-weight:800; font-family:Consolas;")
        self.genome_lbl.setText(st.get("genome", "") or "")
        self.detail_lbl.setText((st.get("detail", "") or "")[:110])

        b = snap.get("bias", {}) or {}
        for tf, chip in self.chips.items():
            chip.set_dir(b.get(tf, "?"))
        up_n = sum(1 for x in b.values() if x == "UP")
        dn_n = sum(1 for x in b.values() if x == "DOWN")
        rsi = (snap.get("rsi") or {}).get("m1", st.get("rsi_m1", 50)) or 50
        pressure = float(snap.get("pressure_10m1", st.get("pressure", 0)) or 0)
        sess = snap.get("session", st.get("session", "?"))
        regime = snap.get("regime", st.get("regime", "?"))
        self.tally_lbl.setText(f"{up_n}↑/{dn_n}↓")
        rsi_col = RED if rsi >= 70 else GREEN if rsi <= 30 else TEXT
        p_col = GREEN if pressure > 0 else RED if pressure < 0 else MUTED
        self.metrics_lbl.setText(
            f"RSI <span style='color:{rsi_col}'>{rsi:.1f}</span> · "
            f"P <span style='color:{p_col}'>{pressure:+.1f}</span> · {regime}/{sess}")

        min_mtf = params.get("min_mtf_agreement", 2)
        rsi_max = params.get("rsi_max", 72)
        rsi_min = 100 - rsi_max
        min_p = params.get("min_pressure_abs", 5)
        buy = [(up_n >= min_mtf, f"{up_n}↑≥{min_mtf}"),
               (rsi < rsi_max, f"RSI<{rsi_max}"),
               (abs(pressure) >= min_p, f"|P|≥{min_p}"),
               (pressure > 0, "P+")]
        sell = [(dn_n >= min_mtf, f"{dn_n}↓≥{min_mtf}"),
                (rsi > rsi_min, f"RSI>{rsi_min}"),
                (abs(pressure) >= min_p, f"|P|≥{min_p}"),
                (pressure < 0, "P−")]
        for pills, conds in ((self.buy_pills, buy), (self.sell_pills, sell)):
            for pill, (ok, txt) in zip(pills, conds):
                pill.set_state(ok, txt)
        self._style_title(self.buy_title, GREEN, all(o for o, _ in buy),
                          sum(1 for o, _ in buy if o))
        self._style_title(self.sell_title, RED, all(o for o, _ in sell),
                          sum(1 for o, _ in sell if o))

        side = st.get("side")
        if side:
            pw = st.get("p_win", 0) or 0
            self.signal_lbl.setText(
                f"⚡ إشارة {side} حية · P(win) {pw:.2f} (عتبة {st.get('ml_min', 0.5)})")
            self.signal_lbl.setStyleSheet(
                f"background:#3a2f0d; color:{GOLD}; border-radius:6px;"
                f" padding:4px 10px; font-weight:800; font-size:12px;")
            self.signal_lbl.setVisible(True)
        else:
            self.signal_lbl.setVisible(False)


class SonCockpit(QWidget):
    """The whole OUR SON tab — header, symbol cards, services, decisions."""

    REFRESH_MS = 1500

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        hdr = QLabel("🧬 OUR SON · GEN-CHILD · unified_trader + ML gate")
        hdr.setStyleSheet(f"font-size:17px; font-weight:bold; color:{GOLD};")
        root.addWidget(hdr)
        sub = QLabel("النظام الحقيقي v2 — يتداول بأسلوبك (ML AUC 0.72) · محمي بكل البوابات")
        sub.setStyleSheet(f"font-size:12px; color:{MUTED};")
        root.addWidget(sub)

        # Account strip
        self.acct_lbl = QLabel("…")
        self.acct_lbl.setStyleSheet(
            f"background:{BG_2}; border:1px solid {BORDER}; border-radius:8px;"
            f" padding:8px 14px; color:{TEXT}; font-family:Consolas; font-size:13px;")
        root.addWidget(self.acct_lbl)

        # Scrollable symbol cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"background:{BG_1}; border:none;")
        host = QWidget()
        self.cards_v = QVBoxLayout(host)
        self.cards_v.setContentsMargins(0, 0, 4, 0)
        self.cards_v.setSpacing(8)
        self.cards_v.addStretch()
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        self.cards: dict[str, SymbolCard] = {}

        # Footer: services health + regime/gate + last decisions
        self.svc_lbl = QLabel("…")
        self.svc_lbl.setStyleSheet(
            f"color:{MUTED}; font-family:Consolas; font-size:11px;"
            f" background:{BG_2}; border:1px solid {BORDER};"
            f" border-radius:6px; padding:5px 10px;")
        root.addWidget(self.svc_lbl)

        self.gate_lbl = QLabel("…")
        self.gate_lbl.setStyleSheet(
            f"color:{TEXT}; font-family:Consolas; font-size:12px;"
            f" background:{BG_2}; border:1px solid {BORDER};"
            f" border-radius:6px; padding:5px 10px;")
        root.addWidget(self.gate_lbl)

        dec_title = QLabel("📜 آخر قرارات ولدنا")
        dec_title.setStyleSheet(f"color:{GOLD}; font-weight:800; font-size:12px;")
        root.addWidget(dec_title)
        self.dec_lbl = QLabel("(لا قرارات بعد)")
        self.dec_lbl.setStyleSheet(
            f"color:{TEXT}; font-family:Consolas; font-size:11px;"
            f" background:{BG_3}; border:1px solid {BORDER};"
            f" border-radius:6px; padding:6px 10px;")
        self.dec_lbl.setTextFormat(Qt.RichText)
        root.addWidget(self.dec_lbl)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(self.REFRESH_MS)
        QTimer.singleShot(300, self.refresh)

    # ── refresh ──────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        # EFFICIENCY: while hidden, skip all disk reads (12 files / tick).
        if not self.isVisible():
            return
        multi = _rd("son_status_multi.json")
        symbols = (multi.get("symbols") or {}) if isinstance(multi, dict) else {}
        if not symbols:
            son = _rd("son_status.json")
            if son and son.get("symbol"):
                symbols = {son["symbol"]: son}

        any_row = next(iter(symbols.values()), {}) if symbols else {}
        bal, eq = any_row.get("balance", "?"), any_row.get("equity", "?")
        firing = sum(1 for s in symbols.values() if s.get("stage") == "FIRING")
        frozen = sum(1 for s in symbols.values() if s.get("stage") in ("FROZEN", "PAUSED"))
        ts = (multi.get("ts", "") or any_row.get("ts", "") or "")[11:19]
        try:
            eq_col = GREEN if float(eq) >= float(bal) else RED
        except Exception:
            eq_col = TEXT
        self.acct_lbl.setText(
            f"💰 الرصيد ${bal} · الحقوق <span style='color:{eq_col}'>${eq}</span>"
            f" &nbsp;·&nbsp; 🧬 {len(symbols)} رموز · 🎯 {firing} تطلق ·"
            f" 🧊 {frozen} موقوفة &nbsp;·&nbsp; ⏱ {ts}")

        # Symbol cards (create lazily; update in place — zero flicker)
        for sym, st in symbols.items():
            card = self.cards.get(sym)
            if card is None:
                card = SymbolCard(sym)
                self.cards[sym] = card
                self.cards_v.insertWidget(self.cards_v.count() - 1, card)
            card.update_card(st, _rd(f"brain_live__{sym}.json"),
                             (_rd(f"live_genome__{sym}.json").get("params") or {}))
        for sym in list(self.cards):        # symbol dropped from feed → remove card
            if sym not in symbols:
                self.cards.pop(sym).deleteLater()

        # Services freshness
        svc = [("brain", "brain_live.json", 10),
               ("regime", "market_regime.json", 15),
               ("orchestrator", "active_engines.json", 45),
               ("son_status", "son_status_multi.json", 10),
               ("fitness", "genome_fitness.json", 9999)]
        parts = []
        for nm, f, lim in svc:
            a = _age(f)
            dot = "🟢" if a < lim else ("🟡" if a < 9000 else "🔴")
            parts.append(f"{dot} {nm} {int(a) if a < 9000 else '—'}s")
        up = sum(1 for _, f, lim in svc if _age(f) < lim)
        self.svc_lbl.setText(f"المحركات {up}/{len(svc)} طازجة   " + "   ".join(parts))

        reg = _rd("market_regime.json")
        act = _rd("active_engines.json")
        adx = reg.get("metrics", {}).get("adx_m5", 0)
        gate = 99782 in act.get("active_magics", [])
        self.gate_lbl.setText(
            f"🌡️ Regime: {reg.get('regime', '?')} (ADX {adx:.1f})   ·   "
            f"🚦 بوابة ولدنا (99782): "
            + (f"<span style='color:{GREEN}'>🟢 مفتوحة</span>" if gate
               else f"<span style='color:{RED}'>🔴 مقفلة (standby)</span>"))

        # Decisions feed (last 6, newest first)
        rows = []
        try:
            for ln in reversed((DATA / "decisions.jsonl")
                               .read_text(encoding="utf-8").splitlines()[-6:]):
                try:
                    d = json.loads(ln)
                    pnl = d.get("pnl")
                    out = f"${pnl:+.2f}" if pnl is not None else "open"
                    col = GREEN if (pnl or 0) > 0 else (MUTED if pnl is None else RED)
                    mk = "🟢" if (pnl or 0) > 0 else ("⌛" if pnl is None else "🔴")
                    rows.append(
                        f"{d.get('ts', '')[11:19]} {mk} {d.get('side', '?')} @"
                        f" {d.get('entry', 0):.2f} <span style='color:{col}'>{out}</span>"
                        f" · {(d.get('reason', '') or '')[:52]}")
                except Exception:
                    continue
        except Exception:
            pass
        self.dec_lbl.setText("<br>".join(rows) or "(لا قرارات بعد — ينتظر سياق رابح)")


__all__ = ["SonCockpit"]

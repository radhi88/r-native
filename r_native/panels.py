from __future__ import annotations

from PySide6.QtWidgets import (QFrame, QGroupBox, QGridLayout, QHBoxLayout, QVBoxLayout,
                               QLabel, QLineEdit, QCheckBox, QComboBox, QPushButton,
                               QWidget)
from PySide6.QtCore import Qt, Signal

from r_native.genes import (EXECUTION_GENES, BIAS_GENES, SIGNAL_GENES,
                            FILTER_GENES, EXIT_GENES, ALL_GENES)


BG_0 = "#060418"
BG_1 = "#0d0824"
BG_2 = "#14092e"
BG_3 = "#1c1142"
GOLD = "#fbbf24"
GOLD_DIM = "#b45309"
VIOLET = "#8b5cf6"
GREEN = "#10b981"
RED = "#ef4444"
CYAN = "#22d3ee"
TEXT = "#f1f5f9"
MUTED = "#94a3b8"
BORDER = "#2d1b69"


_PANEL_QSS = f"""
QFrame#panel {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {BG_1}, stop:1 {BG_2});
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QLabel#panelTitle {{
    color: {GOLD};
    font-weight: 700;
    letter-spacing: 2px;
    font-size: 11px;
    padding: 2px 4px;
}}
QLabel#fieldLabel {{
    color: {MUTED};
    font-size: 11px;
    padding-right: 6px;
}}
QLabel#sectionHdr {{
    color: {GOLD};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
    padding: 6px 2px 2px 2px;
    border-bottom: 1px solid {BORDER};
}}
QLineEdit, QComboBox {{
    background: {BG_0};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 3px 6px;
    selection-background-color: {VIOLET};
    min-height: 18px;
    font-size: 11px;
}}
QLineEdit:focus, QComboBox:focus {{
    border: 1px solid {GOLD};
}}
QCheckBox {{
    color: {TEXT};
    font-size: 11px;
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 13px;
    height: 13px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: {BG_0};
}}
QCheckBox::indicator:checked {{
    background: {GOLD};
    border: 1px solid {GOLD};
}}
QPushButton#helpBtn {{
    background: transparent;
    color: {MUTED};
    border: 1px solid {BORDER};
    border-radius: 8px;
    min-width: 16px;
    max-width: 16px;
    min-height: 16px;
    max-height: 16px;
    font-size: 9px;
    font-weight: 700;
}}
QPushButton#helpBtn:hover {{
    color: {GOLD};
    border-color: {GOLD_DIM};
}}
QPushButton#autoBtn {{
    background: {BG_3};
    color: {GOLD};
    border: 1px solid {GOLD_DIM};
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 10px;
    font-weight: 700;
}}
QPushButton#autoBtn:checked {{
    background: {GOLD_DIM};
    color: {BG_0};
}}
QPushButton#resetBtn {{
    background: {BG_3};
    color: {RED};
    border: 1px solid {RED};
    border-radius: 4px;
    padding: 3px 10px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QPushButton#resetBtn:hover {{
    background: {RED};
    color: {BG_0};
}}
QPushButton#addBtn {{
    background: transparent;
    color: {VIOLET};
    border: 1px dashed {BORDER};
    border-radius: 4px;
    padding: 2px;
    font-size: 13px;
    font-weight: 700;
}}
QPushButton#addBtn:hover {{
    border: 1px dashed {VIOLET};
    color: {GOLD};
}}
QLabel#geneLabel {{
    color: {CYAN};
    border: 1px solid {CYAN};
    border-radius: 3px;
    padding: 2px 6px;
    font-size: 10px;
    background: rgba(34, 211, 238, 0.08);
}}
QLabel#geneLabelOff {{
    color: {MUTED};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 2px 6px;
    font-size: 10px;
    background: transparent;
    text-decoration: line-through;
}}
QLabel#geneCat {{
    color: {RED};
    font-weight: 700;
    letter-spacing: 2px;
    font-size: 11px;
    padding: 4px 2px;
    border-bottom: 1px solid {BORDER};
}}
QLabel#arrow {{
    color: {GOLD};
    font-size: 12px;
    font-weight: 700;
    padding-right: 6px;
}}
"""


def _help_button(tip: str = "") -> QPushButton:
    b = QPushButton("?")
    b.setObjectName("helpBtn")
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


def _field_label(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("fieldLabel")
    lb.setFixedWidth(130)
    return lb


class _PanelBase(QFrame):
    changed = Signal(dict)

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setStyleSheet(_PANEL_QSS)
        self._title_text = title
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(10, 10, 10, 10)
        self._outer.setSpacing(6)
        self._build_header()
        self._body = QVBoxLayout()
        self._body.setSpacing(4)
        self._outer.addLayout(self._body)

    def _build_header(self) -> None:
        row = QHBoxLayout()
        arrow = QLabel("▾")
        arrow.setObjectName("arrow")
        title = QLabel(self._title_text)
        title.setObjectName("panelTitle")
        row.addWidget(arrow)
        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(_help_button("Panel help"))
        self._outer.addLayout(row)

    def _emit(self) -> None:
        self.changed.emit(self.to_dict())

    def to_dict(self) -> dict:
        raise NotImplementedError

    def load_dict(self, d: dict) -> None:
        raise NotImplementedError


def _section_header(text: str) -> QLabel:
    """Small GOLD divider label — breaks long field stacks into scannable groups."""
    lb = QLabel(text)
    lb.setObjectName("sectionHdr")
    return lb


def _row(label: str, control: QWidget, tip: str = "") -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(6)
    h.addWidget(_field_label(label))
    h.addWidget(control, 1)
    h.addWidget(_help_button(tip))
    return h


class PropFirmPanel(_PanelBase):
    def __init__(self, parent=None):
        super().__init__("▾ PROP FIRM GUARDRAILS", parent)

        self.news_mode = QComboBox()
        self.news_mode.addItems(["FTMO", "None"])
        self.news_mins = QLineEdit("30")
        self.news_mins.setMaximumWidth(80)

        self.use_no_open_news_day = QCheckBox("No Open on News Day")

        self.use_dd = QCheckBox("Max Daily DD")
        self.dd_limit = QLineEdit("4.0")
        self.dd_limit.setMaximumWidth(80)

        self.use_friday = QCheckBox("Friday Close")
        self.friday_hour = QLineEdit("19")
        self.friday_hour.setMaximumWidth(80)

        self.use_symbol_lock = QCheckBox("Symbol Lock")

        self.use_max_agg_risk = QCheckBox("Max Aggregate Risk")
        self.max_agg_risk_pct = QLineEdit("5.0")
        self.max_agg_risk_pct.setMaximumWidth(80)

        self.use_profit_target = QCheckBox("Profit Target")
        self.profit_target_pct = QLineEdit("10.0")
        self.profit_target_pct.setMaximumWidth(80)

        self.use_m2_subbar_only = QCheckBox("M2 Sub-bar Only")
        self.use_stop_strict_offset = QCheckBox("Stop Strict Offset")

        # 14 rows were one undifferentiated stack — GOLD section headers make
        # the panel scannable without changing any control or attribute.
        self._body.addWidget(_section_header("NEWS"))
        self._body.addLayout(_row("News Mode", self.news_mode, "FTMO or None"))
        self._body.addLayout(_row("News Mins", self.news_mins, "Minutes around news"))
        self._body.addLayout(_row("News Day", self.use_no_open_news_day))
        self._body.addWidget(_section_header("DRAWDOWN & SESSION"))
        self._body.addLayout(_row("Daily DD", self.use_dd))
        self._body.addLayout(_row("DD Limit %", self.dd_limit, "Max daily drawdown %"))
        self._body.addLayout(_row("Friday", self.use_friday))
        self._body.addLayout(_row("Friday Hour", self.friday_hour, "UTC hour to flatten"))
        self._body.addWidget(_section_header("RISK CAPS"))
        self._body.addLayout(_row("Symbol Lock", self.use_symbol_lock))
        self._body.addLayout(_row("Max Agg Risk", self.use_max_agg_risk))
        self._body.addLayout(_row("Ceiling %", self.max_agg_risk_pct, "Aggregate risk cap"))
        self._body.addLayout(_row("Profit Target", self.use_profit_target))
        self._body.addLayout(_row("Target %", self.profit_target_pct))
        self._body.addWidget(_section_header("EXECUTION STRICTNESS"))
        self._body.addLayout(_row("M2 Subbar", self.use_m2_subbar_only))
        self._body.addLayout(_row("Stop Strict", self.use_stop_strict_offset))

        for w in (self.news_mode,):
            w.currentTextChanged.connect(lambda *_: self._emit())
        for w in (self.news_mins, self.dd_limit, self.friday_hour,
                  self.max_agg_risk_pct, self.profit_target_pct):
            w.textChanged.connect(lambda *_: self._emit())
        for w in (self.use_no_open_news_day, self.use_dd, self.use_friday,
                  self.use_symbol_lock, self.use_max_agg_risk,
                  self.use_profit_target, self.use_m2_subbar_only,
                  self.use_stop_strict_offset):
            w.toggled.connect(lambda *_: self._emit())

        self.load_dict({
            "news_mode": "FTMO", "news_mins": "30",
            "use_no_open_news_day": True, "use_dd": True, "dd_limit": "4.0",
            "use_friday": True, "friday_hour": "19",
            "use_symbol_lock": True, "use_max_agg_risk": True,
            "max_agg_risk_pct": "5.0", "use_profit_target": False,
            "profit_target_pct": "10.0", "use_m2_subbar_only": True,
            "use_stop_strict_offset": True,
        })

    def to_dict(self) -> dict:
        return {
            "news_mode": self.news_mode.currentText(),
            "news_mins": self.news_mins.text(),
            "use_no_open_news_day": self.use_no_open_news_day.isChecked(),
            "use_dd": self.use_dd.isChecked(),
            "dd_limit": self.dd_limit.text(),
            "use_friday": self.use_friday.isChecked(),
            "friday_hour": self.friday_hour.text(),
            "use_symbol_lock": self.use_symbol_lock.isChecked(),
            "use_max_agg_risk": self.use_max_agg_risk.isChecked(),
            "max_agg_risk_pct": self.max_agg_risk_pct.text(),
            "use_profit_target": self.use_profit_target.isChecked(),
            "profit_target_pct": self.profit_target_pct.text(),
            "use_m2_subbar_only": self.use_m2_subbar_only.isChecked(),
            "use_stop_strict_offset": self.use_stop_strict_offset.isChecked(),
        }

    def load_dict(self, d: dict) -> None:
        if "news_mode" in d:
            idx = self.news_mode.findText(str(d["news_mode"]))
            if idx >= 0:
                self.news_mode.setCurrentIndex(idx)
        if "news_mins" in d: self.news_mins.setText(str(d["news_mins"]))
        if "use_no_open_news_day" in d: self.use_no_open_news_day.setChecked(bool(d["use_no_open_news_day"]))
        if "use_dd" in d: self.use_dd.setChecked(bool(d["use_dd"]))
        if "dd_limit" in d: self.dd_limit.setText(str(d["dd_limit"]))
        if "use_friday" in d: self.use_friday.setChecked(bool(d["use_friday"]))
        if "friday_hour" in d: self.friday_hour.setText(str(d["friday_hour"]))
        if "use_symbol_lock" in d: self.use_symbol_lock.setChecked(bool(d["use_symbol_lock"]))
        if "use_max_agg_risk" in d: self.use_max_agg_risk.setChecked(bool(d["use_max_agg_risk"]))
        if "max_agg_risk_pct" in d: self.max_agg_risk_pct.setText(str(d["max_agg_risk_pct"]))
        if "use_profit_target" in d: self.use_profit_target.setChecked(bool(d["use_profit_target"]))
        if "profit_target_pct" in d: self.profit_target_pct.setText(str(d["profit_target_pct"]))
        if "use_m2_subbar_only" in d: self.use_m2_subbar_only.setChecked(bool(d["use_m2_subbar_only"]))
        if "use_stop_strict_offset" in d: self.use_stop_strict_offset.setChecked(bool(d["use_stop_strict_offset"]))


class ExecutionPanel(_PanelBase):
    def __init__(self, parent=None):
        super().__init__("▾ EXECUTION & SPREAD", parent)

        self.slip_major = QLineEdit("10")
        self.slip_cross = QLineEdit("25")
        self.slip_metal = QLineEdit("30")
        self.slip_index = QLineEdit("300")
        self.slip_crypto = QLineEdit("600")

        self.spread_major = QLineEdit("3.0")
        self.spread_cross = QLineEdit("10.0")
        self.spread_metal = QLineEdit("16.0")
        self.spread_index = QLineEdit("60.0")
        self.spread_crypto = QLineEdit("100.0")

        self.spread_gate = QCheckBox("Spread Gate")
        self.spread_gate.setChecked(True)

        for w in (self.slip_major, self.slip_cross, self.slip_metal,
                  self.slip_index, self.slip_crypto, self.spread_major,
                  self.spread_cross, self.spread_metal, self.spread_index,
                  self.spread_crypto):
            w.setMaximumWidth(90)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        slip_header = QLabel("Slip (Pts)")
        slip_header.setObjectName("fieldLabel")
        spread_header = QLabel("Spread (Pips)")
        spread_header.setObjectName("fieldLabel")
        grid.addWidget(slip_header, 0, 1)
        grid.addWidget(spread_header, 0, 2)

        rows = [
            ("Majors",   self.slip_major,  self.spread_major),
            ("Crosses",  self.slip_cross,  self.spread_cross),
            ("Metals",   self.slip_metal,  self.spread_metal),
            ("Indices",  self.slip_index,  self.spread_index),
            ("Crypto",   self.slip_crypto, self.spread_crypto),
        ]
        for i, (lbl, slp, spd) in enumerate(rows, start=1):
            grid.addWidget(_field_label(lbl), i, 0)
            grid.addWidget(slp, i, 1)
            grid.addWidget(spd, i, 2)
            grid.addWidget(_help_button(f"{lbl} slip/spread"), i, 3)

        self._body.addLayout(grid)
        gate_row = QHBoxLayout()
        gate_row.addWidget(self.spread_gate)
        gate_row.addStretch(1)
        gate_row.addWidget(_help_button("Enforce spread cap"))
        self._body.addLayout(gate_row)

        for w in (self.slip_major, self.slip_cross, self.slip_metal,
                  self.slip_index, self.slip_crypto, self.spread_major,
                  self.spread_cross, self.spread_metal, self.spread_index,
                  self.spread_crypto):
            w.textChanged.connect(lambda *_: self._emit())
        self.spread_gate.toggled.connect(lambda *_: self._emit())

    def to_dict(self) -> dict:
        return {
            "slip_major": self.slip_major.text(),
            "slip_cross": self.slip_cross.text(),
            "slip_metal": self.slip_metal.text(),
            "slip_index": self.slip_index.text(),
            "slip_crypto": self.slip_crypto.text(),
            "spread_major": self.spread_major.text(),
            "spread_cross": self.spread_cross.text(),
            "spread_metal": self.spread_metal.text(),
            "spread_index": self.spread_index.text(),
            "spread_crypto": self.spread_crypto.text(),
            "spread_gate": self.spread_gate.isChecked(),
        }

    def load_dict(self, d: dict) -> None:
        for k in ("slip_major", "slip_cross", "slip_metal", "slip_index", "slip_crypto",
                  "spread_major", "spread_cross", "spread_metal", "spread_index",
                  "spread_crypto"):
            if k in d:
                getattr(self, k).setText(str(d[k]))
        if "spread_gate" in d:
            self.spread_gate.setChecked(bool(d["spread_gate"]))


class _AutoField(QWidget):
    changed = Signal()

    def __init__(self, default_value: str = "", parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self.btn = QPushButton("AUTO")
        self.btn.setObjectName("autoBtn")
        self.btn.setCheckable(True)
        self.btn.setChecked(True)
        self.btn.setMaximumWidth(50)
        self.edit = QLineEdit(default_value)
        self.edit.setMaximumWidth(80)
        self.edit.setEnabled(False)
        h.addWidget(self.btn)
        h.addWidget(self.edit)
        self.btn.toggled.connect(self._on_auto_toggled)
        self.btn.toggled.connect(lambda *_: self.changed.emit())
        self.edit.textChanged.connect(lambda *_: self.changed.emit())

    def _on_auto_toggled(self, on: bool) -> None:
        self.edit.setEnabled(not on)

    def value(self) -> str:
        return "Auto" if self.btn.isChecked() else self.edit.text()

    def set_value(self, v: str) -> None:
        if str(v).strip().lower() == "auto":
            self.btn.setChecked(True)
        else:
            self.btn.setChecked(False)
            self.edit.setText(str(v))


class EvolutionPanel(_PanelBase):
    def __init__(self, parent=None):
        super().__init__("▾ EVOLUTION", parent)

        self.pg = QLineEdit("4000")
        self.tribe_a = QLineEdit("20")
        self.tribe_b = QLineEdit("20")
        self.rev = QLineEdit("10")
        self.war = QLineEdit("20")
        self.retrain_gens = QLineEdit("10")
        self.split = QLineEdit("0.67")
        self.stagnation = QLineEdit("5")
        self.balance = QLineEdit("100")
        self.risk = QLineEdit("1.0")
        self.spread = QLineEdit("1.0")
        self.freq_target = _AutoField("0.5")
        self.oos = _AutoField("40")
        self.bars = _AutoField("5000")

        for w in (self.pg, self.tribe_a, self.tribe_b, self.rev, self.war,
                  self.retrain_gens, self.split, self.stagnation, self.balance,
                  self.risk, self.spread):
            w.setMaximumWidth(110)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)

        fields_left = [
            ("PG Population", self.pg),
            ("Tribe A Gens",  self.tribe_a),
            ("Tribe B Gens",  self.tribe_b),
            ("Revolution Gens", self.rev),
            ("War Gens",       self.war),
            ("Retrain Gens",   self.retrain_gens),
            ("Training Split", self.split),
        ]
        fields_right = [
            ("Frequency Floor", self.freq_target),
            ("OOS Min Trades",  self.oos),
            ("Bars",            self.bars),
            ("Stagnation",      self.stagnation),
            ("Balance",         self.balance),
            ("Risk %",          self.risk),
            ("Spread",          self.spread),
        ]

        for i, (label, ctrl) in enumerate(fields_left):
            grid.addWidget(_field_label(label), i, 0)
            grid.addWidget(ctrl, i, 1)
            grid.addWidget(_help_button(label), i, 2)
        for i, (label, ctrl) in enumerate(fields_right):
            grid.addWidget(_field_label(label), i, 3)
            grid.addWidget(ctrl, i, 4)
            grid.addWidget(_help_button(label), i, 5)

        self._body.addLayout(grid)

        for w in (self.pg, self.tribe_a, self.tribe_b, self.rev, self.war,
                  self.retrain_gens, self.split, self.stagnation, self.balance,
                  self.risk, self.spread):
            w.textChanged.connect(lambda *_: self._emit())
        for w in (self.freq_target, self.oos, self.bars):
            w.changed.connect(lambda *_: self._emit())

    def to_dict(self) -> dict:
        return {
            "pg": self.pg.text(),
            "tribe_a": self.tribe_a.text(),
            "tribe_b": self.tribe_b.text(),
            "rev": self.rev.text(),
            "war": self.war.text(),
            "retrain_gens": self.retrain_gens.text(),
            "freq_target": self.freq_target.value(),
            "oos": self.oos.value(),
            "split": self.split.text(),
            "stagnation": self.stagnation.text(),
            "balance": self.balance.text(),
            "risk": self.risk.text(),
            "bars": self.bars.value(),
            "spread": self.spread.text(),
        }

    def load_dict(self, d: dict) -> None:
        for k in ("pg", "tribe_a", "tribe_b", "rev", "war", "retrain_gens",
                  "split", "stagnation", "balance", "risk", "spread"):
            if k in d:
                getattr(self, k).setText(str(d[k]))
        if "freq_target" in d: self.freq_target.set_value(d["freq_target"])
        if "oos" in d: self.oos.set_value(d["oos"])
        if "bars" in d: self.bars.set_value(d["bars"])


class _GeneChip(QLabel):
    toggled = Signal(str, bool)

    def __init__(self, name: str, parent=None):
        super().__init__(name, parent)
        self._name = name
        self._on = True
        self.setCursor(Qt.PointingHandCursor)
        self.setAlignment(Qt.AlignCenter)
        self._refresh()

    def _refresh(self) -> None:
        self.setObjectName("geneLabel" if self._on else "geneLabelOff")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_on(self, on: bool) -> None:
        if self._on == on:
            return
        self._on = on
        self._refresh()

    def is_on(self) -> bool:
        return self._on

    def name(self) -> str:
        return self._name

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._on = not self._on
            self._refresh()
            self.toggled.emit(self._name, self._on)
        super().mousePressEvent(ev)


class GenePoolPanel(_PanelBase):
    CATEGORIES: list[tuple[str, list[str]]] = [
        ("BIAS",       BIAS_GENES),
        ("SIGNALS",    SIGNAL_GENES),
        ("FILTERS",    FILTER_GENES),
        ("EXECUTION",  EXECUTION_GENES),
        ("MANAGEMENT", EXIT_GENES),
    ]

    def __init__(self, parent=None):
        super().__init__("▾ GENE POOL", parent)

        top = QHBoxLayout()
        top.addStretch(1)
        self.reset_btn = QPushButton("RESET")
        self.reset_btn.setObjectName("resetBtn")
        self.reset_btn.clicked.connect(self._on_reset)
        top.addWidget(self.reset_btn)
        self._body.addLayout(top)

        cols = QHBoxLayout()
        cols.setSpacing(8)
        self._chips: dict[str, _GeneChip] = {}

        for cat_name, genes in self.CATEGORIES:
            col = QVBoxLayout()
            col.setSpacing(3)
            header = QLabel(cat_name)
            header.setObjectName("geneCat")
            header.setAlignment(Qt.AlignCenter)
            col.addWidget(header)
            for g in genes:
                chip = _GeneChip(g)
                chip.toggled.connect(lambda *_: self._emit())
                self._chips[g] = chip
                col.addWidget(chip)
            add = QPushButton("+")
            add.setObjectName("addBtn")
            col.addWidget(add)
            col.addStretch(1)
            wrap = QFrame()
            wrap.setLayout(col)
            cols.addWidget(wrap, 1)

        self._body.addLayout(cols)

    def _on_reset(self) -> None:
        for chip in self._chips.values():
            chip.set_on(True)
        self._emit()

    def enabled_genes(self) -> set[str]:
        return {n for n, c in self._chips.items() if c.is_on()}

    def set_enabled(self, genes_set) -> None:
        s = set(genes_set)
        for n, c in self._chips.items():
            c.set_on(n in s)

    def to_dict(self) -> dict:
        return {n: c.is_on() for n, c in self._chips.items()}

    def load_dict(self, d: dict) -> None:
        for n, c in self._chips.items():
            if n in d:
                c.set_on(bool(d[n]))


if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    panels = {
        "PropFirmPanel":  PropFirmPanel(),
        "ExecutionPanel": ExecutionPanel(),
        "EvolutionPanel": EvolutionPanel(),
        "GenePoolPanel":  GenePoolPanel(),
    }

    container = QWidget()
    container.setStyleSheet(f"background: {BG_0};")
    v = QVBoxLayout(container)
    for name, p in panels.items():
        v.addWidget(p)
    container.resize(900, 1100)
    container.show()

    for name, p in panels.items():
        print(f"--- {name} ---")
        d = p.to_dict()
        if name == "GenePoolPanel":
            on = sum(1 for v in d.values() if v)
            print(f"  enabled: {on}/{len(d)} genes")
        else:
            for k, v in d.items():
                print(f"  {k}: {v}")

    from PySide6.QtCore import QTimer
    QTimer.singleShot(150, app.quit)
    sys.exit(app.exec())

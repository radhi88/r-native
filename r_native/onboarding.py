"""onboarding.py — Visual first-run wizard for FRIDAY R Factory.

Shows a beautiful staged sequence so a new user sees EXACTLY what the system
does before it starts trading. Each stage:
  • icon + Arabic+English title
  • live data populated from MT5/HoF/scanner (not fake placeholders)
  • countdown bar
  • details panel (top symbols, trends, genome count, agents)

Stages:
  1) 🔌  Connect to MT5 — verify terminal + account
  2) 🌍  Read the market — scan symbols, rank by quality
  3) 📈  Identify trends — H1/H4 bias per top symbol
  4) 🧬  Load genomes — count + best PF from Hall of Fame
  5) 🤖  Start agents — list 5 agents and their cadences
  6) ✅  Ready — handoff to dashboard

The window is shown automatically when `data/r_native/.onboarding_done`
flag is missing (first run), or anytime via the R Native UI's
🤖 AI ADVISORS tab → "Run First-Run Wizard" button.

Embedded in app.py via:  from r_native.onboarding import show_if_needed
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                 QProgressBar, QPushButton, QPlainTextEdit,
                                 QFrame, QSizePolicy)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QFont

ONBOARDING_FLAG = Path(r"C:\Users\Radhi\MT5\data\r_native\.onboarding_done")

# ─── Palette (matches main app) ───
BG_0  = "#0a0a0f"
BG_1  = "#13131a"
BG_2  = "#1a1a23"
BG_3  = "#222230"
GOLD  = "#f5a524"
GREEN = "#22c55e"
RED   = "#ef4444"
CYAN  = "#06b6d4"
TEXT  = "#ededf0"
MUTED = "#9494a0"
BORDER = "#2d2d3a"


# ───────────────────────────────────────────────────────────────────────
# Stage workers — each returns a dict with stage's live results
# ───────────────────────────────────────────────────────────────────────

def _stage_mt5_connect() -> dict:
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return {"ok": False, "err": "MT5 init failed"}
        t = mt5.terminal_info(); a = mt5.account_info()
        return {
            "ok": True,
            "server":   getattr(a, "server", "?"),
            "account":  getattr(a, "login", "?"),
            "balance":  round(getattr(a, "balance", 0), 2),
            "currency": getattr(a, "currency", "?"),
            "leverage": getattr(a, "leverage", "?"),
            "connected": getattr(t, "connected", False),
        }
    except Exception as e:
        return {"ok": False, "err": str(e)}


def _stage_scan_market() -> dict:
    try:
        import sys
        sys.path.insert(0, r"C:\Users\Radhi\MT5")
        from friday_v3.algory.r_multi_symbol import rank_symbols
        r = rank_symbols(max_symbols=20)
        cands = r.get("candidates", [])
        return {
            "ok": True,
            "examined":   r.get("total_examined", 0),
            "tradeable":  r.get("total_tradeable", 0),
            "top":        [{"sym": c["symbol"], "q": c["quality"],
                            "status": c["status"]}
                           for c in cands[:8]],
        }
    except Exception as e:
        return {"ok": False, "err": str(e)}


def _stage_identify_trends(top_symbols: list[str]) -> dict:
    try:
        import urllib.request, json as _j
        out = []
        for sym in top_symbols[:6]:
            try:
                with urllib.request.urlopen(
                    f"http://localhost:5055/api/snapshot?symbol={sym}",
                    timeout=3) as r:
                    snap = _j.loads(r.read().decode())
                mtf = snap.get("multi_tf", {}).get("tfs", {})
                h1 = mtf.get("H1", {}); h4 = mtf.get("H4", {})
                out.append({
                    "sym":    sym,
                    "h1_bias": h1.get("bias", "?"),
                    "h4_bias": h4.get("bias", "?"),
                    "h1_rsi":  h1.get("rsi"),
                    "h1_atr":  h1.get("atr"),
                    "slope":   h1.get("slope_atr"),
                })
            except Exception: continue
        return {"ok": True, "trends": out}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def _stage_load_genomes() -> dict:
    """Deep per-symbol genome inventory: count, bars, TFs, score, strategies."""
    try:
        idx = Path(r"C:\Users\Radhi\MT5\data\r_native\hall_of_fame\index.json")
        cfgs = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
        hof_total = 0; alive = 0; pinned = 0
        if idx.exists():
            d = json.loads(idx.read_text(encoding="utf-8"))
            hof_total = len(d)
            for e in d.values():
                if not e.get("killed"): alive += 1
                if e.get("pinned"): pinned += 1

        # Per-symbol breakdown
        per_symbol = []
        if cfgs.exists():
            for p in sorted(cfgs.glob("*.json")):
                if p.suffix != ".json" or ".bak" in p.name: continue
                try:
                    c = json.loads(p.read_text(encoding="utf-8"))
                except Exception: continue
                sym = c.get("symbol") or p.stem
                dg = c.get("deployed_genome") or {}
                strats = c.get("ga_strategies") or []
                all_results = c.get("all_results") or []
                # Aggregate bars + TFs + archetypes from all_results
                tfs = set()
                archs = set()
                bars_used = 0
                for r in all_results:
                    if r.get("timeframe"): tfs.add(r["timeframe"])
                    if r.get("archetype"): archs.add(r["archetype"])
                    bars_used = max(bars_used, int(r.get("bars_scanned") or 0))
                # Strategies aggregated from ga_strategies (where genomes live)
                tf_set = set()
                arch_set = set()
                for s in strats:
                    if s.get("timeframe"): tf_set.add(s["timeframe"])
                    if s.get("archetype"): arch_set.add(s["archetype"])
                per_symbol.append({
                    "symbol":       sym,
                    "deployed":     dg.get("id") or None,
                    "deployed_pf":  dg.get("profit_factor") or 0,
                    "deployed_wr":  dg.get("win_rate") or 0,
                    "genes_in_deployed": len(dg.get("active_genes") or []),
                    "deployed_confidence": (
                        "HIGH" if (dg.get("profit_factor") or 0) >= 5 else
                        "MED"  if (dg.get("profit_factor") or 0) >= 2 else
                        "LOW"  if dg.get("id") else "—"),
                    "deployed_source":   dg.get("source") or "",
                    "ga_strategies_n":   len(strats),
                    "all_results_n":     len(all_results),
                    "tfs":               sorted(tf_set | tfs),
                    "archetypes":        sorted(arch_set | archs),
                    "bars_scanned_max":  bars_used,
                })
        deployed_count = sum(1 for r in per_symbol if r["deployed"])
        return {"ok": True,
                "hof_total":         hof_total,
                "alive":             alive,
                "pinned":            pinned,
                "deployed_symbols":  deployed_count,
                "per_symbol":        per_symbol}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def _stage_check_agents() -> dict:
    try:
        import urllib.request, json as _j
        with urllib.request.urlopen("http://localhost:5055/api/r/agents",
                                      timeout=3) as r:
            d = _j.loads(r.read().decode())
        agents = d.get("agents", [])
        return {"ok": True, "agents": agents,
                "running": sum(1 for a in agents if a.get("running"))}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def _stage_edge_check() -> dict:
    """Show the MEASURED edge: which markets passed the OOS gate, and each market's most
    accurate indicators (from the F2-b research layer). This makes the plan's decisions
    evidence-based instead of trading every seeded genome blindly."""
    try:
        import json as _j
        from pathlib import Path as _P
        D = _P(r"C:\Users\Radhi\MT5\r_native_v2\data")
        robust, marginal = [], []
        try:
            g = _j.loads((D / "market_gate.json").read_text(encoding="utf-8"))
            for s, r in g.get("results", {}).items():
                tier = r.get("tier")
                if tier == "robust":
                    best = max((x for x in r.get("tf", {}).values() if x.get("pass")),
                               key=lambda x: x.get("pf", 0), default={})
                    robust.append({"sym": s.replace("_x100m", "m").replace("_x10m", "m"),
                                   "pf": best.get("pf", 0)})
                elif tier == "marginal":
                    marginal.append(s)
        except Exception:
            pass
        # dedupe robust
        seen = set(); robust = [r for r in robust if not (r["sym"] in seen or seen.add(r["sym"]))]
        robust.sort(key=lambda r: -r["pf"])
        # top accurate indicators for a few key symbols
        acc = {}
        for sym in [r["sym"] for r in robust[:4]] or ["US30m", "BTCUSDm"]:
            try:
                a = _j.loads((D / f"indicator_accuracy_{sym}.json").read_text(encoding="utf-8")).get("accuracy", {})
                top = sorted(a.items(), key=lambda kv: -kv[1].get("hit_rate", 0))[:4]
                acc[sym] = [(k, round(v["hit_rate"] * 100, 1)) for k, v in top]
            except Exception:
                pass
        return {"ok": True, "robust": robust, "marginal_count": len(marginal), "accuracy": acc}
    except Exception as e:
        return {"ok": False, "err": str(e)}


# ───────────────────────────────────────────────────────────────────────
# Worker thread — runs stages off the UI thread
# ───────────────────────────────────────────────────────────────────────

class StageRunner(QThread):
    stage_started = Signal(int, str)   # idx, title
    stage_result  = Signal(int, dict)  # idx, result dict
    all_done      = Signal()

    STAGES = [
        ("🔌", "Connect to MT5", "الاتصال بـ MT5", _stage_mt5_connect, None),
        ("🌍", "Read the market", "قراءة السوق",   _stage_scan_market, None),
        ("📈", "Identify trends", "تحديد الاتجاهات", _stage_identify_trends, "needs_top"),
        ("🧬", "Load genomes",    "تحميل الجينات",  _stage_load_genomes, None),
        ("🤖", "Start agents",    "تشغيل الوكلاء",  _stage_check_agents, None),
        ("🎯", "Edge check",      "فحص الحافة",     _stage_edge_check, None),
        ("📋", "Review plan",     "مراجعة الخطة",   None, "plan"),
    ]

    def run(self):
        scan_result = None
        results: dict = {}
        for i, (icon, en, ar, fn, dep) in enumerate(self.STAGES):
            self.stage_started.emit(i, f"{icon}  {en}  ·  {ar}")
            try:
                if dep == "plan":
                    # Synthesize a plan from the prior stage results
                    res = self._build_plan(results)
                elif dep == "needs_top" and scan_result:
                    top_syms = [c["sym"] for c in scan_result.get("top", [])]
                    res = fn(top_syms)
                else:
                    res = fn() if fn else {"ok": False, "err": "no handler"}
                if i == 1: scan_result = res
                results[i] = res
            except Exception as e:
                res = {"ok": False, "err": str(e)}
            self.stage_result.emit(i, res)
            time.sleep(0.7)
        self.all_done.emit()

    def _build_plan(self, prior: dict) -> dict:
        """Stage 6 — synthesize a one-page plan from prior stage results."""
        acct  = prior.get(0, {})
        scan  = prior.get(1, {})
        trends = prior.get(2, {})
        genes = prior.get(3, {})
        agents = prior.get(4, {})
        per_sym = genes.get("per_symbol", []) or []
        return {
            "ok": True,
            "account":  f"#{acct.get('account','?')}  ${acct.get('balance','?')}  {acct.get('currency','?')}",
            "server":   acct.get("server", "?"),
            "examined": scan.get("examined", 0),
            "tradeable": scan.get("tradeable", 0),
            "symbols_with_genome": sum(1 for s in per_sym if s.get("deployed")),
            "symbols_without_genome": sum(1 for s in per_sym if not s.get("deployed")),
            "trends_up":   sum(1 for t in (trends.get("trends") or []) if t.get("h1_bias") == "UP"),
            "trends_down": sum(1 for t in (trends.get("trends") or []) if t.get("h1_bias") == "DOWN"),
            "trends_flat": sum(1 for t in (trends.get("trends") or []) if t.get("h1_bias") not in ("UP","DOWN")),
            "agents_running": agents.get("running", 0),
            "agents_total":   len(agents.get("agents", [])),
        }


# ───────────────────────────────────────────────────────────────────────
# The wizard dialog
# ───────────────────────────────────────────────────────────────────────

class OnboardingWizard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FRIDAY R Factory — Welcome")
        self.setModal(False)
        self.setMinimumSize(820, 620)
        self.setStyleSheet(
            f"QDialog {{ background: {BG_0}; color: {TEXT}; }}"
            f"QLabel {{ color: {TEXT}; }}"
            f"QPushButton {{ background: {BG_2}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 4px;"
            f" padding: 8px 18px; font-weight: 700; }}"
            f"QPushButton:hover {{ color: {GOLD}; border-color: {GOLD}; }}"
            f"QProgressBar {{ background: {BG_2}; border: 1px solid {BORDER};"
            f" border-radius: 3px; text-align: center; color: {TEXT};"
            f" font-weight: 700; height: 18px; }}"
            f"QProgressBar::chunk {{ background: {GOLD}; border-radius: 2px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)

        # Header
        title = QLabel("FRIDAY  R FACTORY")
        title.setStyleSheet(f"color: {GOLD}; font-weight: 900;"
                            f" font-size: 24px; letter-spacing: 6px;")
        sub = QLabel("Genetic trading system — first-run setup  ·  إعداد أول مرة")
        sub.setStyleSheet(f"color: {MUTED}; font-size: 11px; letter-spacing: 2px;")
        outer.addWidget(title)
        outer.addWidget(sub)

        # Overall progress
        self.overall = QProgressBar()
        self.overall.setRange(0, len(StageRunner.STAGES))
        self.overall.setValue(0)
        self.overall.setFormat("Stage %v / %m")
        outer.addWidget(self.overall)

        # Stage list (5 rows)
        self.stage_widgets = []
        stages_frame = QFrame()
        stages_frame.setStyleSheet(
            f"QFrame {{ background: {BG_1}; border: 1px solid {BORDER};"
            f" border-radius: 6px; }}")
        sv = QVBoxLayout(stages_frame)
        sv.setContentsMargins(12, 10, 12, 10)
        sv.setSpacing(8)
        for icon, en, ar, _, _ in StageRunner.STAGES:
            row = QHBoxLayout()
            row.setSpacing(10)
            ico = QLabel("○"); ico.setFixedWidth(20)
            ico.setStyleSheet(f"color: {MUTED}; font-size: 16px;")
            lbl = QLabel(f"{icon}  {en}   ·   {ar}")
            lbl.setStyleSheet(f"color: {MUTED}; font-size: 12px;"
                              f" font-weight: 700; letter-spacing: 1px;")
            row.addWidget(ico)
            row.addWidget(lbl, 1)
            sv.addLayout(row)
            self.stage_widgets.append((ico, lbl))
        outer.addWidget(stages_frame)

        # Live details panel
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setStyleSheet(
            f"QPlainTextEdit {{ background: {BG_1}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 6px;"
            f" font-family: 'JetBrains Mono','Consolas',monospace;"
            f" font-size: 11px; padding: 10px; }}")
        self.details.setPlaceholderText("Stage details will stream here…")
        outer.addWidget(self.details, 1)

        # Footer buttons
        footer = QHBoxLayout()
        self.skip_btn = QPushButton("Skip")
        self.skip_btn.clicked.connect(self._on_skip)
        footer.addWidget(self.skip_btn)
        footer.addStretch(1)
        self.done_btn = QPushButton("✓  Approve & Start")
        self.done_btn.setEnabled(False)
        self.done_btn.setStyleSheet(
            f"QPushButton {{ background: {GREEN}; color: {BG_0};"
            f" border: 1px solid {GREEN}; border-radius: 4px;"
            f" padding: 10px 22px; font-weight: 900;"
            f" letter-spacing: 1px; font-size: 12px; }}"
            f"QPushButton:disabled {{ background: {BG_3}; color: {MUTED};"
            f" border-color: {BORDER}; }}"
            f"QPushButton:hover:!disabled {{ background: {GOLD}; }}")
        self.done_btn.clicked.connect(self._on_done)
        footer.addWidget(self.done_btn)
        outer.addLayout(footer)

        # Kick off the worker
        self.runner = StageRunner()
        self.runner.stage_started.connect(self._on_stage_start)
        self.runner.stage_result.connect(self._on_stage_result)
        self.runner.all_done.connect(self._on_all_done)
        QTimer.singleShot(400, self.runner.start)

    # ── stage callbacks ──
    def _on_stage_start(self, idx: int, title: str):
        ico, lbl = self.stage_widgets[idx]
        ico.setText("◐")
        ico.setStyleSheet(f"color: {CYAN}; font-size: 16px;")
        lbl.setStyleSheet(f"color: {TEXT}; font-size: 12px;"
                          f" font-weight: 700; letter-spacing: 1px;")
        self._log(f"\n▸  Stage {idx + 1}: {title}")

    def _on_stage_result(self, idx: int, res: dict):
        ico, lbl = self.stage_widgets[idx]
        if res.get("ok"):
            ico.setText("●")
            ico.setStyleSheet(f"color: {GREEN}; font-size: 16px;")
            self._format_result(idx, res)
        else:
            ico.setText("✗")
            ico.setStyleSheet(f"color: {RED}; font-size: 16px;")
            self._log(f"   ⚠ {res.get('err', 'unknown error')}")
        self.overall.setValue(idx + 1)

    def _format_result(self, idx: int, res: dict):
        """Render the live result for each stage in the details panel."""
        if idx == 0:
            self._log(f"   account:  #{res['account']}  on  {res['server']}")
            self._log(f"   balance:  ${res['balance']} {res['currency']}"
                      f"   leverage: 1:{res['leverage']}")
            self._log(f"   connected: {'YES' if res['connected'] else 'NO'}")
        elif idx == 1:
            self._log(f"   examined:  {res['examined']} symbols  ·"
                      f"  tradeable: {res['tradeable']}")
            self._log(f"   top 8 by quality:")
            for c in res["top"]:
                self._log(f"      {c['sym']:14s}  q={c['q']:5.1f}  "
                          f"status={c['status']}")
        elif idx == 2:
            self._log(f"   read H1 + H4 bias for {len(res['trends'])} symbols:")
            for t in res["trends"]:
                arrow_h1 = '↑' if t['h1_bias']=='UP' else ('↓' if t['h1_bias']=='DOWN' else '~')
                arrow_h4 = '↑' if t['h4_bias']=='UP' else ('↓' if t['h4_bias']=='DOWN' else '~')
                self._log(f"      {t['sym']:14s}  H4 {arrow_h4} H1 {arrow_h1}"
                          f"  rsi={t.get('h1_rsi','?'):>5}"
                          f"  slope={t.get('slope','?'):>6}")
        elif idx == 3:
            self._log(f"   HoF total: {res['hof_total']}  ·"
                      f"  alive: {res['alive']}  ·  pinned: {res['pinned']}")
            self._log(f"   symbols with deployed genome: {res['deployed_symbols']}")
            self._log(f"")
            self._log(f"   per-symbol breakdown:")
            self._log(f"   {'sym':12s}  {'genome':8s}  {'genes':5s}  "
                      f"{'pf':>5s}  {'wr%':>5s}  {'conf':4s}  "
                      f"{'bars':>5s}  TFs            archetypes")
            self._log(f"   " + "─" * 100)
            for s in res["per_symbol"][:15]:
                gid = s["deployed"] or "—"
                self._log(
                    f"   {s['symbol']:12s}  {gid:8s}  {s['genes_in_deployed']:>5d}  "
                    f"{s['deployed_pf']:>5.1f}  {s['deployed_wr']:>5.1f}  "
                    f"{s['deployed_confidence']:4s}  {s['bars_scanned_max']:>5d}  "
                    f"{','.join(s['tfs'])[:14]:14s}  "
                    f"{','.join(s['archetypes'])[:30]}")
            self._stored_per_symbol = res["per_symbol"]   # for stage 6
        elif idx == 4:
            self._log(f"   {res['running']} of {len(res['agents'])} agents running")
            for a in res["agents"]:
                status = "●" if a.get("running") else "○"
                self._log(f"      {status} {a['name']:20s}"
                          f"  ticks={a.get('ticks', 0)}"
                          f"  every {a.get('interval', '?')}s")
        elif idx == 5:
            # Edge check — measured OOS edge + most-accurate indicators per market
            rob = res.get("robust", [])
            self._log(f"   OOS-proven markets (robust, 4/4 folds): {len(rob)}")
            for r in rob[:8]:
                self._log(f"      ✓ {r['sym']:10s}  PF {r['pf']}")
            self._log(f"   marginal (3/4 folds): {res.get('marginal_count', 0)}")
            if res.get("accuracy"):
                self._log(f"   most-accurate indicators per market:")
                for sym, inds in res["accuracy"].items():
                    pretty = " · ".join(f"{k} {v}%" for k, v in inds)
                    self._log(f"      {sym:10s}  {pretty}")
            self._stored_edge = res
        elif idx == 6:
            self._log(f"")
            self._log(f"   ╔═══════════════════════════════════════════════╗")
            self._log(f"   ║         T R A D I N G   P L A N               ║")
            self._log(f"   ╚═══════════════════════════════════════════════╝")
            self._log(f"")
            self._log(f"   • Account:   {res.get('account')}  on  {res.get('server')}")
            self._log(f"   • Market:    {res.get('examined')} symbols examined,"
                      f"  {res.get('tradeable')} tradeable now")
            self._log(f"   • Coverage:  {res.get('symbols_with_genome')} symbols armed"
                      f" with genomes  ·  {res.get('symbols_without_genome')} will"
                      f" auto-seed on first pick")
            self._log(f"   • Trends:    ↑{res.get('trends_up')} UP   "
                      f"↓{res.get('trends_down')} DOWN   "
                      f"~{res.get('trends_flat')} FLAT  (top 6)")
            self._log(f"   • Agents:    {res.get('agents_running')}/"
                      f"{res.get('agents_total')} working autonomously")
            self._log(f"")
            self._log(f"   What WILL happen after you click Approve:")
            self._log(f"     1. Executor picks best free symbol every 8 seconds")
            self._log(f"     2. Gate evaluates → if GO, opens lot 0.01 ×"
                      f" monster-boost (up to 2.5×)")
            self._log(f"     3. Adaptive trailing locks profit as confidence drifts")
            self._log(f"     4. Lineage daemon evolves new genomes every 15 min")
            self._log(f"     5. Monster daemon detects beast-mode every 5 min")
            self._log(f"     6. Asymmetry tracker protects BUY/SELL specialists")
            self._log(f"")
            self._log(f"   Safety in place:")
            self._log(f"     • Per-symbol DD floor: −$5 → 15-min pause")
            self._log(f"     • Cool-down: 5s after each close (anti-double-fire)")
            self._log(f"     • Max 12 parallel positions")
            self._log(f"     • Min balance: $1 (full-run authorized)")
            self._log(f"")
            self._log(f"   👉 Click  Approve & Start  to begin trading.")
            self._log(f"     Click  Skip  to leave the system in observation mode.")

    def _on_all_done(self):
        self._log(f"\n✓  All checks complete. Awaiting your approval.")
        self.done_btn.setEnabled(True)
        # Don't write the flag yet — only after the user explicitly approves
        # via _on_done(). Skip writes a different value.

    def _on_skip(self):
        # mark as done so it doesn't show again unless deleted
        ONBOARDING_FLAG.parent.mkdir(parents=True, exist_ok=True)
        ONBOARDING_FLAG.write_text("skipped@" + datetime.utcnow().isoformat(),
                                    encoding="utf-8")
        self.reject()

    def _on_done(self):
        # Persist approval flag
        ONBOARDING_FLAG.parent.mkdir(parents=True, exist_ok=True)
        ONBOARDING_FLAG.write_text("approved@" + datetime.utcnow().isoformat(),
                                    encoding="utf-8")
        # ── ACTUALLY LAUNCH THE AUTONOMOUS SYSTEM (was: only spotlight a button) ──
        # The user wants: click Approve → it runs by itself. So start the executor and the
        # 31 agents right here. Each step is isolated + best-effort so the wizard never breaks.
        self._log("\n🚀  Approve clicked — launching autonomous system…")
        # 1) R Executor (PAPER) — picks best symbol every 8s, gated, trails profit
        try:
            import subprocess as _sp, sys as _sys
            cf = _sp.CREATE_NO_WINDOW if _sys.platform == "win32" else 0
            p = _sp.Popen([_sys.executable, "-m", "friday_v3.algory.r_executor"],
                          cwd=r"C:\Users\Radhi\MT5", creationflags=cf,
                          stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            self._log(f"   ✓ R Executor started (PAPER) — PID {p.pid}")
        except Exception as e:
            self._log(f"   ⚠ executor start failed: {e}")
        # 2) The 31 agents — try the brain's start endpoint, else import-and-start in-process
        try:
            import urllib.request as _u
            _u.urlopen(_u.Request("http://127.0.0.1:5055/api/r/agents/start_all",
                                  data=b"{}", headers={"Content-Type": "application/json"}),
                       timeout=5)
            self._log("   ✓ agents start requested (brain :5055)")
        except Exception:
            try:
                from r_native.agents.orchestrator import start_all as _sa
                _sa(); self._log("   ✓ agents started in-process")
            except Exception as e:
                self._log(f"   ⚠ agents start failed: {e}")
        # 3) Spotlight the ARM control too (in case the user wants manual control)
        try:
            if self.parent() and hasattr(self.parent(), "spotlight_activate_button"):
                self.parent().spotlight_activate_button()
        except Exception: pass
        self._log("✅  Autonomous system is running. You can close this window.")
        self.accept()

    def _log(self, line: str):
        self.details.appendPlainText(line)


# ───────────────────────────────────────────────────────────────────────
# Public entry points
# ───────────────────────────────────────────────────────────────────────

def is_first_run() -> bool:
    return not ONBOARDING_FLAG.exists()


def show_if_needed(parent=None) -> Optional[OnboardingWizard]:
    """Called by app.py at startup — returns the wizard or None."""
    if not is_first_run(): return None
    w = OnboardingWizard(parent)
    w.show()
    return w


def show_anyway(parent=None) -> OnboardingWizard:
    """Force-show the wizard (e.g. from a button)."""
    w = OnboardingWizard(parent)
    w.show()
    return w


def reset_flag() -> None:
    ONBOARDING_FLAG.unlink(missing_ok=True)

"""friday_gui.py — FRIDAY desktop control panel (Tkinter, no extra deps).

ONE window to see + control the whole live stack:
  • Account: equity / balance / floating / margin level
  • Live LLM decision (sdk_decision.json): engine · bias · confidence · reason
  • Coordinator (coord_state.json): direction · regime · confluence · lots · positions · halt
  • Proof gate (scalp_proof.json): trades · net · PF · PASS/FAIL
  • Open gold positions table (magic 99791)
  • Process health (alive/stale) for every bot
  • Buttons: HALT ALL · RESUME · CLOSE GOLD · open web dashboards

Run:  pythonw friday_gui.py   (or: python friday_gui.py)
"""
from __future__ import annotations
import json, time, webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont

import MetaTrader5 as mt5

GOLD = "XAUUSDm"; MAGIC = 99791
ROOT = Path(r"C:\Users\Radhi\MT5")
D = ROOT / "r_native_v2" / "data"
DECISION = D / "sdk_decision.json"
COORD = D / "coord_state.json"
HALT = D / "scalp_halt.flag"
PROOF = ROOT / "scalp_proof.json"

BG = "#0b0e14"; CARD = "#11151c"; FG = "#e6edf3"; DIM = "#8b949e"
GRN = "#3fb950"; RED = "#f85149"; YEL = "#d29922"; ACC = "#58a6ff"; PUR = "#bc8cff"

PROCS = {  # script substring -> label ; freshness file (None = process-scan only)
    "gold_live.py":      ("سكالبر الذهب", D / "gold_live.lock"),
    "coordinator.py":    ("المنسّق",       COORD),
    "scalp_evolver.py":  ("المطوّر",       D / "scalp_live_config.json"),
    "scalp_proof.py":    ("بوّابة الإثبات", PROOF),
    "sdk_scheduler.py":  ("مجدول LLM",     DECISION),
    "algory_chart_dashboard.py": ("لوحة الشارت", None),
    "friday_brain_view.py":      ("لوحة الوكلاء", None),
}


def _read(p):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {}


def _running_cmdlines():
    """Best-effort set of running python command lines (psutil, fallback empty)."""
    try:
        import psutil
        out = []
        for pr in psutil.process_iter(["name", "cmdline"]):
            n = (pr.info.get("name") or "").lower()
            if n.startswith("python"):
                out.append(" ".join(pr.info.get("cmdline") or []))
        return out
    except Exception:
        return None


class GUI:
    def __init__(self, root):
        self.root = root
        root.title("FRIDAY · لوحة التحكّم")
        root.configure(bg=BG)
        root.geometry("760x680")
        self.big = tkfont.Font(family="Segoe UI", size=22, weight="bold")
        self.mid = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self.sm = tkfont.Font(family="Segoe UI", size=10)
        self.mono = tkfont.Font(family="Consolas", size=10)
        mt5.initialize()
        self._build()
        self.refresh()

    def _card(self, parent, title):
        f = tk.Frame(parent, bg=CARD, highlightbackground="#1f2630", highlightthickness=1)
        tk.Label(f, text=title, bg=CARD, fg=DIM, font=self.sm, anchor="e").pack(fill="x", padx=10, pady=(8, 0))
        return f

    def _build(self):
        top = tk.Frame(self.root, bg=BG); top.pack(fill="x", padx=12, pady=10)
        # account card
        ac = self._card(top, "الحساب"); ac.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.eq = tk.Label(ac, text="—", bg=CARD, fg=FG, font=self.big); self.eq.pack(anchor="e", padx=10)
        self.acct2 = tk.Label(ac, text="", bg=CARD, fg=DIM, font=self.sm); self.acct2.pack(anchor="e", padx=10, pady=(0, 8))
        # decision card
        dc = self._card(top, "قرار الـLLM الحيّ"); dc.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self.bias = tk.Label(dc, text="—", bg=CARD, fg=FG, font=self.big); self.bias.pack(anchor="e", padx=10)
        self.dec2 = tk.Label(dc, text="", bg=CARD, fg=DIM, font=self.sm, wraplength=330, justify="right"); self.dec2.pack(anchor="e", padx=10, pady=(0, 8))

        # coordinator card
        co = self._card(self.root, "المنسّق (الاتفاق المشترك)"); co.pack(fill="x", padx=12, pady=4)
        self.coord = tk.Label(co, text="—", bg=CARD, fg=FG, font=self.mid); self.coord.pack(anchor="e", padx=10, pady=(0, 8))
        # proof card
        pf = self._card(self.root, "بوّابة الفلوس الحقيقية"); pf.pack(fill="x", padx=12, pady=4)
        self.proof = tk.Label(pf, text="—", bg=CARD, fg=FG, font=self.mid); self.proof.pack(anchor="e", padx=10, pady=(0, 8))

        # positions card
        pc = self._card(self.root, "صفقات الذهب المفتوحة (99791)"); pc.pack(fill="both", expand=True, padx=12, pady=4)
        self.pos = tk.Label(pc, text="—", bg=CARD, fg=FG, font=self.mono, justify="right", anchor="ne"); self.pos.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        # process health
        hc = self._card(self.root, "حالة البوتات"); hc.pack(fill="x", padx=12, pady=4)
        self.health = tk.Frame(hc, bg=CARD); self.health.pack(fill="x", padx=10, pady=(2, 8))
        self.dots = {}
        for i, (key, (lbl, _)) in enumerate(PROCS.items()):
            cell = tk.Frame(self.health, bg=CARD)
            cell.grid(row=i // 4, column=i % 4, sticky="w", padx=6, pady=3)
            d = tk.Label(cell, text="●", bg=CARD, fg=DIM, font=self.sm); d.pack(side="right")
            tk.Label(cell, text=lbl, bg=CARD, fg=FG, font=self.sm).pack(side="right", padx=4)
            self.dots[key] = d

        # buttons
        bf = tk.Frame(self.root, bg=BG); bf.pack(fill="x", padx=12, pady=10)
        def btn(t, c, fn):
            return tk.Button(bf, text=t, bg=c, fg="#0b0e14", font=self.mid, relief="flat",
                             activebackground=c, command=fn, cursor="hand2", padx=10, pady=6)
        btn("🛑 إيقاف الكل", RED, self.halt).pack(side="right", padx=4)
        btn("▶ استئناف", GRN, self.resume).pack(side="right", padx=4)
        btn("❌ إغلاق الذهب", YEL, self.close_gold).pack(side="right", padx=4)
        btn("📊 الشارت", ACC, lambda: webbrowser.open("http://127.0.0.1:8866/")).pack(side="left", padx=4)
        btn("🧠 الوكلاء", PUR, lambda: webbrowser.open("http://127.0.0.1:5056/")).pack(side="left", padx=4)
        self.status = tk.Label(self.root, text="", bg=BG, fg=DIM, font=self.sm); self.status.pack(pady=(0, 6))

    # ── actions ──
    def halt(self):
        HALT.parent.mkdir(parents=True, exist_ok=True)
        HALT.write_text(json.dumps({"reason": "GUI manual halt", "ts": time.time()}), encoding="utf-8")
        self._flash("🛑 كُتب علم الإيقاف — البوتات ستُسطّح وتتوقّف")

    def resume(self):
        try: HALT.unlink()
        except Exception: pass
        self._flash("▶ أُزيل علم الإيقاف — يستأنف")

    def close_gold(self):
        info = mt5.symbol_info(GOLD); tick = mt5.symbol_info_tick(GOLD)
        n = 0
        for p in (mt5.positions_get(symbol=GOLD) or []):
            if p.magic != MAGIC: continue
            ot = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
            px = tick.bid if p.type == 0 else tick.ask
            mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": GOLD, "volume": float(p.volume),
                            "type": ot, "position": p.ticket, "price": px, "deviation": 30,
                            "magic": MAGIC, "comment": "gui-close", "type_filling": mt5.ORDER_FILLING_IOC})
            n += 1
        self._flash(f"❌ أُغلقت {n} صفقة ذهب")

    def _flash(self, msg):
        self.status.config(text=msg); self.root.after(4000, lambda: self.status.config(text=""))

    # ── refresh loop ──
    def refresh(self):
        now = time.time()
        a = mt5.account_info()
        if a:
            fl = a.equity - a.balance
            self.eq.config(text=f"${a.equity:,.2f}", fg=GRN if fl >= 0 else RED)
            ml = f"{a.margin_level:.0f}%" if a.margin_level else "—"
            self.acct2.config(text=f"رصيد ${a.balance:,.2f} · عائم {fl:+.2f} · هامش {ml}")
        d = _read(DECISION)
        if d:
            b = d.get("bias", "—")
            self.bias.config(text={"BUY": "شراء", "SELL": "بيع", "WAIT": "انتظار"}.get(b, b),
                             fg=GRN if b == "BUY" else RED if b == "SELL" else DIM)
            eng = d.get("engine", "?"); age = int(now - d.get("ts", now))
            self.dec2.config(text=f"[{eng}] ثقة {d.get('confidence','—')} · {age}s\n{(d.get('reason') or '')[:140]}")
        c = _read(COORD)
        if c:
            reg = c.get("regime", "—"); hd = c.get("halt")
            self.coord.config(
                text=f"{'🛑 موقوف' if hd else '✅ يعمل'} · اتجاه {c.get('agreed_dir')} · {reg} · "
                     f"توافق {c.get('confluence')} · لوت {c.get('total_lots')} · صفقات {c.get('total_positions')} · "
                     f"محقّق {c.get('realized_since_epoch')}",
                fg=RED if hd else FG)
        pr = _read(PROOF)
        if pr and pr.get("last14d"):
            t = pr["last14d"]; g = pr.get("real_money_gate", {})
            self.proof.config(text=f"{t.get('trades')} صفقة · صافي {t.get('net')} · WR {t.get('wr')}% · PF {t.get('pf')} · "
                                   f"{'✅ جاهز' if g.get('pass') else '❌ لم يجتز'}",
                              fg=GRN if g.get("pass") else YEL)
        # positions
        ps = [p for p in (mt5.positions_get(symbol=GOLD) or []) if p.magic == MAGIC]
        if ps:
            rows = [f"{'بيع' if p.type else 'شراء'}  {p.volume}  @{p.price_open:.2f}  "
                    f"SL {p.sl:.2f}  TP {p.tp:.2f}  عائم {p.profit:+.2f}" for p in ps]
            self.pos.config(text="\n".join(rows))
        else:
            self.pos.config(text="لا صفقات مفتوحة")
        # process health (freshness or process-scan)
        cmds = _running_cmdlines()
        for key, (lbl, ffile) in PROCS.items():
            alive = False
            if cmds is not None:
                alive = any(key in cl for cl in cmds)
            if not alive and ffile is not None and ffile.exists():
                alive = (now - ffile.stat().st_mtime) < 45      # fresh file = working
            self.dots[key].config(fg=GRN if alive else RED)
        self.root.after(2000, self.refresh)


if __name__ == "__main__":
    root = tk.Tk()
    GUI(root)
    root.mainloop()

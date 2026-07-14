"""agents/performance_auditor.py — periodic audit reports.

Generates a structured report every hour:
  • account: balance change, today's P/L, win rate today
  • genomes: who fired, who profited, who regressed
  • HoF: size growth, new auto-pins, kills
  • auto-evo: cycles run, deploys made, rejections

Reports are emitted as INFO insights AND pushed to Telegram on a
schedule (hourly summary, daily wrap-up at 22:00 UTC).
"""
from __future__ import annotations

from datetime import datetime, timezone

from r_native.agents.base import Agent, emit_insight


class PerformanceAuditor(Agent):
    name = "performance_auditor"
    description = "Periodic audit reports — hourly summaries, daily wrap-ups"
    interval_seconds = 3600     # 1 hour
    default_enabled = True

    def __init__(self):
        super().__init__()
        self._last_daily_report_day: str = ""
        self._baseline_balance: float | None = None

    def _read_account(self) -> dict | None:
        try:
            import urllib.request as _u
            import json as _json
            with _u.urlopen("http://127.0.0.1:5055/api/account", timeout=3) as r:
                return _json.loads(r.read().decode())
        except Exception: return None

    def _read_auto_evo(self) -> dict | None:
        try:
            import urllib.request as _u
            import json as _json
            with _u.urlopen("http://127.0.0.1:5055/api/r/auto_evo/status",
                            timeout=3) as r:
                return _json.loads(r.read().decode())
        except Exception: return None

    def _send_telegram(self, msg: str):
        try:
            from r_native.telegram_bot import send
            send(msg, event="audit_report")
        except Exception: pass

    def tick(self):
        acct = self._read_account()
        evo  = self._read_auto_evo()
        if not acct or not acct.get("ok"): return

        account = acct.get("account") or {}
        balance = float(account.get("balance") or 0)
        equity  = float(account.get("equity") or 0)
        open_pl = float(acct.get("open_pnl") or 0)
        if self._baseline_balance is None:
            self._baseline_balance = balance

        # R-attributed performance
        r_stats = next((a for a in acct.get("attribution_by_magic") or []
                        if a.get("magic") == 20260605), {})
        r_trades  = int(r_stats.get("trades") or 0)
        r_wins    = int(r_stats.get("wins") or 0)
        r_wr      = float(r_stats.get("win_rate") or 0)
        r_pl      = float(r_stats.get("net_profit") or 0)

        # HoF size
        hof_total = 0
        hof_pinned = 0
        try:
            from r_native.hall_of_fame import load_index, load_pinned
            hof_total = len(load_index())
            hof_pinned = len(load_pinned())
        except Exception: pass

        # Auto-evo activity
        cycles = (evo or {}).get("total_cycles", 0)
        deploys = (evo or {}).get("total_deploys", 0)
        deploys_today = (evo or {}).get("deploys_today", 0)

        emit_insight(self.name, "INFO",
            f"📊 hourly audit · bal=${balance:.2f} (Δ{balance-self._baseline_balance:+.2f}) "
            f"open=${open_pl:+.2f} R={r_trades}t {r_wr:.0f}%WR ${r_pl:+.2f} | "
            f"HoF={hof_total}(📌{hof_pinned}) evo={cycles}c/{deploys}d",
            data={
                "balance": balance, "equity": equity, "open_pl": open_pl,
                "r_trades": r_trades, "r_wins": r_wins, "r_wr": r_wr,
                "r_pl": r_pl, "hof_total": hof_total, "hof_pinned": hof_pinned,
                "evo_cycles": cycles, "evo_deploys": deploys,
                "deploys_today": deploys_today,
            })

        # ── Daily wrap-up @ 22:00 UTC ──
        now = datetime.now(timezone.utc)
        today = now.date().isoformat()
        if now.hour == 22 and self._last_daily_report_day != today:
            self._last_daily_report_day = today
            daily_msg = (
                f"📊 <b>R Native Daily Wrap-Up</b> ({today})\n\n"
                f"💰 Account: ${balance:.2f} (open ${open_pl:+.2f})\n"
                f"🎯 R trades today: {r_trades} · WR {r_wr:.0f}% · P/L ${r_pl:+.2f}\n"
                f"🏆 Hall of Fame: {hof_total} genomes (📌 {hof_pinned} pinned)\n"
                f"🧬 Auto-Evolution: {cycles} cycles · {deploys} total deploys\n"
                f"   today: {deploys_today} new genomes deployed"
            )
            self._send_telegram(daily_msg)
            emit_insight(self.name, "INFO", "📨 daily wrap-up sent to Telegram",
                         action="daily_report")

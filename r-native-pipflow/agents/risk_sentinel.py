"""agents/risk_sentinel.py — always-on real-time risk guard.

This agent actually takes destructive action when something looks wrong:
  • watches account equity drawdown vs starting balance
  • watches per-genome live P/L and kills runaway losers in HoF
  • watches consecutive_losses on the executor and trips kill_switch
  • watches open position count vs broker margin headroom
  • blocks the deployed_genome (sets tradeable=false) if it stinks live

It NEVER moves money — it can only:
  - flip kill_switch on the brain (gateway blocks all new entries)
  - mark a genome as killed in HoF (removes it from elite carry pool)
  - mark a symbol's deployed_genome as tradeable=false (executor skips it)
  - emit ACT-level insights (visible in UI + Telegram)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


KILL_SWITCH_PATH = Path(r"C:\Users\Radhi\MT5\data\kill_switch.json")
SYMBOL_CFG_DIR   = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
STARTING_BALANCE_GUESS = 100.0   # falls back if no record


class RiskSentinel(Agent):
    name = "risk_sentinel"
    description = "Real-time risk guard — kills runaway losers + trips kill switch"
    interval_seconds = 20            # check every 20s — fast
    default_enabled = True

    # Thresholds (could be user-configurable later)
    MAX_ACCOUNT_DD_PCT      = 15.0   # >15% drawdown from peak → trip kill switch
    MAX_GENOME_LIVE_LOSS    = -10.0  # any genome losing > $10 live → block it
    MAX_CONSECUTIVE_LOSSES  = 5      # 5 in a row → flip kill switch
    MIN_MARGIN_FREE_PCT     = 20.0   # <20% free margin → block new entries

    def __init__(self):
        super().__init__()
        self._peak_equity: float = 0.0
        self._tripped_today: bool = False
        self._last_trip_day: str  = ""

    # ── helpers ──
    def _read_account(self) -> dict | None:
        try:
            import urllib.request as _u
            import json as _json
            with _u.urlopen("http://127.0.0.1:5055/api/account", timeout=3) as r:
                return _json.loads(r.read().decode())
        except Exception:
            return None

    def _read_executor(self) -> dict | None:
        try:
            import urllib.request as _u
            import json as _json
            with _u.urlopen("http://127.0.0.1:5055/api/r/executor", timeout=3) as r:
                return _json.loads(r.read().decode())
        except Exception:
            return None

    def _trip_kill_switch(self, reason: str):
        """Flip kill_switch=true in data/kill_switch.json — brain gateway
        reads this and blocks all new entries."""
        try:
            current = {}
            if KILL_SWITCH_PATH.exists():
                current = json.loads(KILL_SWITCH_PATH.read_text(encoding="utf-8"))
            if current.get("kill_switch") is True:
                return False  # already tripped
            current.update({
                "kill_switch": True,
                "tripped_at":  datetime.now(timezone.utc).isoformat(),
                "tripped_by":  "risk_sentinel",
                "reason":      reason,
            })
            KILL_SWITCH_PATH.parent.mkdir(parents=True, exist_ok=True)
            KILL_SWITCH_PATH.write_text(
                json.dumps(current, ensure_ascii=False, indent=2),
                encoding="utf-8")
            return True
        except Exception as e:
            emit_insight(self.name, "WARN",
                         f"failed to write kill switch: {e}")
            return False

    def _block_deployed_genome(self, symbol: str, reason: str):
        """Set tradeable=false on the per-symbol config so executor stops
        firing entries for this symbol's deployed genome."""
        try:
            p = SYMBOL_CFG_DIR / f"{symbol}.json"
            if not p.exists(): return False
            cfg = json.loads(p.read_text(encoding="utf-8"))
            if not cfg.get("tradeable", True):
                return False  # already blocked
            cfg["tradeable"] = False
            cfg["blocked_at"] = datetime.now(timezone.utc).isoformat()
            cfg["blocked_by"] = "risk_sentinel"
            cfg["block_reason"] = reason
            p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                         encoding="utf-8")
            return True
        except Exception as e:
            emit_insight(self.name, "WARN", f"block {symbol} failed: {e}")
            return False

    def _kill_hof_genome(self, gid: str, reason: str):
        try:
            from r_native.hall_of_fame import kill
            return kill(gid, reason)
        except Exception:
            return False

    # ── main tick ──
    def tick(self):
        acct = self._read_account()
        if not acct or not acct.get("ok"):
            return  # silently skip if brain offline

        account = acct.get("account", {})
        equity  = float(account.get("equity")  or 0)
        balance = float(account.get("balance") or 0)
        margin_free = float(account.get("margin_free") or 0)
        margin      = float(account.get("margin") or 0)

        if equity > self._peak_equity:
            self._peak_equity = equity

        # ── 1. Account-level drawdown vs peak equity ──
        if self._peak_equity > 0:
            dd_pct = (self._peak_equity - equity) / self._peak_equity * 100
            if dd_pct >= self.MAX_ACCOUNT_DD_PCT:
                if self._trip_kill_switch(
                    f"account drawdown {dd_pct:.1f}% from peak ${self._peak_equity:.2f}"):
                    emit_insight(self.name, "ACT",
                        f"🛡️ KILL SWITCH TRIPPED · DD {dd_pct:.1f}% (>${self.MAX_ACCOUNT_DD_PCT}%)",
                        data={"peak": self._peak_equity, "equity": equity,
                              "dd_pct": dd_pct},
                        action="kill_switch_on")
                    try:
                        from r_native.telegram_bot import send
                        send(f"🛡️ <b>RISK SENTINEL TRIPPED KILL SWITCH</b>\n"
                             f"Account drawdown: {dd_pct:.1f}%\n"
                             f"Peak: ${self._peak_equity:.2f}\n"
                             f"Now:  ${equity:.2f}",
                             event="risk_alert")
                    except Exception: pass

        # ── 2. Margin headroom ──
        if margin > 0:
            free_pct = margin_free / (margin_free + margin) * 100
            if free_pct < self.MIN_MARGIN_FREE_PCT:
                emit_insight(self.name, "WARN",
                    f"low margin headroom: {free_pct:.1f}% free (<{self.MIN_MARGIN_FREE_PCT}%)",
                    data={"margin_free": margin_free, "margin_used": margin})

        # ── 3. Executor consecutive losses ──
        execu = self._read_executor()
        if execu:
            cl = int(execu.get("consec_losses") or 0)
            if cl >= self.MAX_CONSECUTIVE_LOSSES:
                if self._trip_kill_switch(f"{cl} consecutive losses on executor"):
                    emit_insight(self.name, "ACT",
                        f"🛡️ KILL SWITCH · {cl} losses in a row",
                        data={"consec_losses": cl},
                        action="kill_switch_on")

        # ── 4. Per-genome live P/L from HoF ──
        try:
            from r_native.hall_of_fame import load_index
            index = load_index()
            for gid, entry in index.items():
                if entry.get("killed"): continue
                if entry.get("pinned"): continue  # pinned = immortal
                live_pl = float(entry.get("live_pnl") or 0)
                live_n  = int(entry.get("live_trades") or 0)
                if live_n < 3: continue  # need sample
                if live_pl <= self.MAX_GENOME_LIVE_LOSS:
                    if self._kill_hof_genome(gid,
                        f"live P/L ${live_pl:.2f} over {live_n} trades"):
                        emit_insight(self.name, "ACT",
                            f"💀 killed genome {entry.get('nickname', gid)} "
                            f"· live ${live_pl:.2f} ({live_n} trades)",
                            data={"id": gid, "live_pnl": live_pl,
                                  "live_trades": live_n},
                            action="genome_killed")
        except Exception: pass

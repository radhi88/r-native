"""agent_governance.py — hard guardrails layered on top of every agent.

Agents propose actions; governance approves, rate-limits, or vetoes them.
This is the "Risk Management & Constraints" block from the Agentic AI
framework — concrete policies enforced before any side effect.

Policies (all configurable; sane defaults):

    max_trades_per_hour_per_agent       6
    max_trades_per_day_per_symbol       12
    max_deploys_per_day                  6
    consecutive_losses_pause_threshold   3   (pauses agent for cooldown)
    cooldown_after_losses_minutes        60
    account_drawdown_hard_pause_pct      8.0 (pauses ALL agents)

The governance state is persisted to disk so restarts don't reset
counters mid-day.
"""
from __future__ import annotations

import json
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


GOV_STATE = Path(r"C:\Users\Radhi\MT5\data\r_native\agents\governance.json")
GOV_LOG   = Path(r"C:\Users\Radhi\MT5\data\r_native\agents\governance.jsonl")


@dataclass
class GovernancePolicy:
    max_trades_per_hour_per_agent:      int   = 6
    max_trades_per_day_per_symbol:      int   = 12
    max_deploys_per_day:                int   = 6
    consecutive_losses_pause_threshold: int   = 3
    cooldown_after_losses_minutes:      int   = 60
    account_drawdown_hard_pause_pct:    float = 8.0


@dataclass
class _AgentState:
    # Rolling-window of trade timestamps for rate limiting
    trade_ts:  deque = field(default_factory=lambda: deque(maxlen=200))
    # Consecutive-losses cooldown
    consecutive_losses: int = 0
    cooldown_until_utc: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "trade_ts": list(self.trade_ts),
            "consecutive_losses": self.consecutive_losses,
            "cooldown_until_utc": self.cooldown_until_utc,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "_AgentState":
        s = cls()
        s.trade_ts.extend(d.get("trade_ts", []))
        s.consecutive_losses = int(d.get("consecutive_losses", 0))
        s.cooldown_until_utc = d.get("cooldown_until_utc")
        return s


class Governance:
    """Singleton policy enforcer. Use the module-level functions for the
    common path; instantiate directly only for tests."""

    def __init__(self, policy: Optional[GovernancePolicy] = None):
        self.policy: GovernancePolicy = policy or GovernancePolicy()
        self._lock = threading.Lock()
        self._agents: dict[str, _AgentState] = defaultdict(_AgentState)
        self._symbol_trades_today: dict[str, list] = defaultdict(list)
        self._deploys_today: list = []
        self._account_paused_reason: Optional[str] = None
        self._load_state()

    # ── Decisions ────────────────────────────────────────────────
    def can_trade(self, agent: str, symbol: str) -> tuple[bool, str]:
        """Return (allowed, reason)."""
        with self._lock:
            if self._account_paused_reason:
                return False, f"account paused: {self._account_paused_reason}"

            st = self._agents[agent]
            now = datetime.now(timezone.utc)

            # Cooldown check
            if st.cooldown_until_utc:
                until = _parse_iso(st.cooldown_until_utc)
                if until and now < until:
                    return False, f"agent in cooldown until {st.cooldown_until_utc}"
                st.cooldown_until_utc = None    # cooldown expired

            # Per-agent hourly rate limit
            one_hour_ago = now - timedelta(hours=1)
            recent = [t for t in st.trade_ts
                      if _parse_iso(t) and _parse_iso(t) > one_hour_ago]
            if len(recent) >= self.policy.max_trades_per_hour_per_agent:
                return False, (f"agent {agent} at hourly cap "
                               f"({len(recent)}/{self.policy.max_trades_per_hour_per_agent})")

            # Per-symbol daily cap
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            sym_today = [t for t in self._symbol_trades_today.get(symbol, [])
                         if _parse_iso(t) and _parse_iso(t) > today_start]
            if len(sym_today) >= self.policy.max_trades_per_day_per_symbol:
                return False, (f"symbol {symbol} at daily cap "
                               f"({len(sym_today)}/{self.policy.max_trades_per_day_per_symbol})")
            return True, "ok"

    def can_deploy(self) -> tuple[bool, str]:
        with self._lock:
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today = [t for t in self._deploys_today
                     if _parse_iso(t) and _parse_iso(t) > today_start]
            if len(today) >= self.policy.max_deploys_per_day:
                return False, (f"deploys at daily cap "
                               f"({len(today)}/{self.policy.max_deploys_per_day})")
            return True, "ok"

    # ── Notifications (the agents call these AFTER acting) ──────
    def record_trade(self, agent: str, symbol: str,
                     outcome: str = "open") -> None:
        """outcome in {"open","win","loss"} — only "loss" triggers cooldown."""
        with self._lock:
            ts = datetime.now(timezone.utc).isoformat()
            st = self._agents[agent]
            st.trade_ts.append(ts)
            self._symbol_trades_today[symbol].append(ts)

            if outcome == "loss":
                st.consecutive_losses += 1
                if st.consecutive_losses >= self.policy.consecutive_losses_pause_threshold:
                    until = datetime.now(timezone.utc) + timedelta(
                        minutes=self.policy.cooldown_after_losses_minutes)
                    st.cooldown_until_utc = until.isoformat()
                    self._log({"event": "cooldown", "agent": agent,
                               "until": st.cooldown_until_utc,
                               "consecutive_losses": st.consecutive_losses})
            elif outcome == "win":
                st.consecutive_losses = 0
            self._save_state()

    def record_deploy(self, symbol: str, genome_id: str) -> None:
        with self._lock:
            self._deploys_today.append(datetime.now(timezone.utc).isoformat())
            self._log({"event": "deploy", "symbol": symbol, "id": genome_id})
            self._save_state()

    def hard_pause(self, reason: str) -> None:
        with self._lock:
            self._account_paused_reason = reason
            self._log({"event": "hard_pause", "reason": reason})
            self._save_state()

    def resume(self) -> None:
        with self._lock:
            self._account_paused_reason = None
            self._log({"event": "resume"})
            self._save_state()

    def check_drawdown(self, account_dd_pct: float) -> tuple[bool, str]:
        """Account-level guardrail. Call from a monitoring agent each tick."""
        if account_dd_pct >= self.policy.account_drawdown_hard_pause_pct:
            self.hard_pause(f"account DD {account_dd_pct:.1f}% >= "
                            f"{self.policy.account_drawdown_hard_pause_pct}%")
            return True, "paused"
        return False, "ok"

    # ── Inspector / observability ───────────────────────────────
    def status(self) -> dict:
        with self._lock:
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            agent_view = {}
            for name, st in self._agents.items():
                one_hour_ago = now - timedelta(hours=1)
                recent = [t for t in st.trade_ts
                          if _parse_iso(t) and _parse_iso(t) > one_hour_ago]
                agent_view[name] = {
                    "trades_last_hour":     len(recent),
                    "consecutive_losses":   st.consecutive_losses,
                    "cooldown_until_utc":   st.cooldown_until_utc,
                }
            return {
                "policy": self.policy.__dict__,
                "account_paused_reason": self._account_paused_reason,
                "deploys_today": len([t for t in self._deploys_today
                                      if _parse_iso(t) and _parse_iso(t) > today_start]),
                "agents": agent_view,
                "symbol_trades_today": {
                    sym: len([t for t in v
                              if _parse_iso(t) and _parse_iso(t) > today_start])
                    for sym, v in self._symbol_trades_today.items()
                },
            }

    # ── Persistence ─────────────────────────────────────────────
    def _save_state(self):
        try:
            GOV_STATE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "policy": self.policy.__dict__,
                "account_paused_reason": self._account_paused_reason,
                "agents": {k: v.to_dict() for k, v in self._agents.items()},
                "symbol_trades_today": dict(self._symbol_trades_today),
                "deploys_today":        list(self._deploys_today),
                "last_saved":           datetime.now(timezone.utc).isoformat(),
            }
            GOV_STATE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        except Exception:
            pass

    def _load_state(self):
        if not GOV_STATE.exists(): return
        try:
            data = json.loads(GOV_STATE.read_text(encoding="utf-8"))
            self._account_paused_reason = data.get("account_paused_reason")
            for k, v in (data.get("agents") or {}).items():
                self._agents[k] = _AgentState.from_dict(v)
            self._symbol_trades_today.update(data.get("symbol_trades_today") or {})
            self._deploys_today = list(data.get("deploys_today") or [])
        except Exception:
            pass

    def _log(self, event: dict):
        try:
            GOV_LOG.parent.mkdir(parents=True, exist_ok=True)
            event = dict(event)
            event["ts"] = datetime.now(timezone.utc).isoformat()
            with GOV_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass


# ─── Module-level singleton ─────────────────────────────────────
_singleton: Optional[Governance] = None


def get() -> Governance:
    global _singleton
    if _singleton is None:
        _singleton = Governance()
    return _singleton


def can_trade(agent: str, symbol: str) -> tuple[bool, str]:
    return get().can_trade(agent, symbol)


def can_deploy() -> tuple[bool, str]:
    return get().can_deploy()


def record_trade(agent: str, symbol: str, outcome: str = "open") -> None:
    get().record_trade(agent, symbol, outcome)


def record_deploy(symbol: str, genome_id: str) -> None:
    get().record_deploy(symbol, genome_id)


def status() -> dict:
    return get().status()


# ─── Helpers ─────────────────────────────────────────────────────
def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s: return None
    try: return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception: return None

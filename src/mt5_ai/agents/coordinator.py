"""
AgentCoordinator — master orchestrator for all FRIDAY trading agents.

Responsibilities:
- Distributes market_state to each agent every bar
- Prevents conflicting positions (no BUY from one agent while another has SELL open)
- Enforces global position limit (MAX_DEMO_OPEN_ORDERS)
- Routes signals to the executor (paper/demo only)
- Applies trailing SL after every bar
- Uses dynamic lot sizing based on per-agent confidence
- Calls on_trade_closed() when a position exits
- Logs decisions to the learning engine
"""

import logging

from ..config import (
    CLAUDE_COMMITTEE_COOLDOWN_BARS,
    CLAUDE_COMMITTEE_ENABLED,
    CLAUDE_COMMITTEE_MIN_CONFIDENCE,
    MAX_DEMO_OPEN_ORDERS,
)
from ..learning_journal import LearningJournal
from ..trailing_sl import TrailingSLEngine
from ..lot_sizer import compute_lot
from .base_agent import BaseAgent, Signal
from .learning_engine import LearningEngine
from .scalping_agent import ScalpingAgent
from .swing_agent import SwingAgent
from .pending_agent import PendingOrderAgent


class AgentCoordinator:
    def __init__(self, executor, symbol: str, event_bus=None):
        self.executor  = executor
        self.symbol    = symbol
        self.event_bus = event_bus
        self.log       = logging.getLogger("friday.coordinator")

        self.learning  = LearningEngine()
        self.journal   = LearningJournal()
        self.trail_sl  = TrailingSLEngine()

        self.agents: list[BaseAgent] = [
            ScalpingAgent(executor, self.learning, symbol),
            SwingAgent(executor, self.learning, symbol),
            PendingOrderAgent(executor, self.learning, symbol),
        ]
        if CLAUDE_COMMITTEE_ENABLED:
            self._add_claude_committee_agent(executor, symbol)

        self._positions: dict[str, dict] = {}

    def _add_claude_committee_agent(self, executor, symbol: str):
        try:
            from .claude_committee import ClaudeCommitteeAgent, committee_unavailable_reason

            unavailable_reason = committee_unavailable_reason()
            if unavailable_reason:
                self.log.warning("Claude committee agent disabled: %s", unavailable_reason)
                return

            self.agents.append(
                ClaudeCommitteeAgent(
                    executor,
                    self.learning,
                    symbol,
                    min_confidence=CLAUDE_COMMITTEE_MIN_CONFIDENCE,
                    cooldown_bars=CLAUDE_COMMITTEE_COOLDOWN_BARS,
                )
            )
            self.log.info("Claude committee agent enabled")
        except Exception as exc:
            self.log.warning("Claude committee agent unavailable: %s", exc)

    # ── main loop hook ─────────────────────────────────────────────────────────

    def on_bar(self, market_state: dict):
        """Call once per bar with the current market state dict."""
        current   = float(market_state.get("price", 0))
        atr_pts   = float(market_state.get("atr", 0))

        # 1. Apply trailing SL before checking exits
        self._apply_trailing_sl(current, atr_pts, market_state)

        # 2. Check SL/TP exits
        self._check_exits(market_state)

        # 3. Try to open new positions
        open_count = len(self._positions)
        if open_count >= MAX_DEMO_OPEN_ORDERS:
            self.log.debug("position limit reached (%d/%d)", open_count, MAX_DEMO_OPEN_ORDERS)
            return

        net_bias = self._net_bias()

        for agent in self.agents:
            if agent.has_open_trade():
                continue

            signal = agent.evaluate(market_state)
            if signal is None or signal.side == "HOLD":
                continue

            if net_bias == "BUY"  and signal.side == "SELL":
                self.log.debug("%s SELL blocked — net position is BUY", agent.name)
                continue
            if net_bias == "SELL" and signal.side == "BUY":
                self.log.debug("%s BUY blocked — net position is SELL", agent.name)
                continue

            self._execute(agent, signal, market_state)
            break  # one new trade per bar

    # ── trailing SL ────────────────────────────────────────────────────────────

    def _apply_trailing_sl(self, current: float, atr_pts: float, market_state: dict):
        updates = self.trail_sl.update(self._positions, current, atr_pts)
        for name, new_sl in updates:
            if name in self._positions:
                old_sl = self._positions[name].get("sl")
                self._positions[name]["sl"] = new_sl
                if self.event_bus:
                    self.event_bus.publish("agent_sl_update", {
                        "agent": name,
                        "old_sl": old_sl,
                        "new_sl": new_sl,
                        "price": current,
                    })

    # ── execution ──────────────────────────────────────────────────────────────

    def _execute(self, agent: BaseAgent, signal: Signal, market_state: dict):
        price = signal.price

        # Dynamic lot sizing based on agent's learning history
        rows    = self.learning._load_rows(agent=agent.name, lookback=200)
        sizing  = compute_lot(rows)
        lot     = sizing.lot

        try:
            if signal.order_type == "MARKET":
                result = self.executor.execute(
                    symbol=self.symbol,
                    side=signal.side,
                    price=price,
                    lot=lot,
                    sl=signal.sl,
                    tp=signal.tp,
                )
            else:
                result = {
                    "mode": "paper_pending",
                    "order_type": signal.order_type,
                    "limit_price": signal.limit_price,
                    "lot": lot,
                    "sl": signal.sl,
                    "tp": signal.tp,
                    "sent": True,
                }
        except Exception as exc:
            self.log.error("execution error for %s: %s", agent.name, exc)
            return

        self._positions[agent.name] = {
            "side":  signal.side,
            "entry": price,
            "sl":    signal.sl,
            "tp":    signal.tp,
            "lot":   lot,
        }
        self.log.info(
            "[%s] %s %s @ %.5f  lot=%.2f  SL=%.5f  TP=%.5f  (tier=%d)",
            agent.name.upper(), signal.order_type, signal.side,
            price, lot, signal.sl or 0, signal.tp or 0, sizing.tier,
        )
        if self.event_bus:
            self.event_bus.publish("agent_trade_open", {
                "agent": agent.name,
                "side": signal.side,
                "order_type": signal.order_type,
                "price": price,
                "lot": lot,
                "lot_tier": sizing.tier,
                "sl": signal.sl,
                "tp": signal.tp,
                "symbol": self.symbol,
            })

    # ── exit detection ─────────────────────────────────────────────────────────

    def _check_exits(self, market_state: dict):
        current = float(market_state.get("price", 0))
        to_close: list[str] = []

        for name, pos in self._positions.items():
            sl, tp, side, entry = pos["sl"], pos["tp"], pos["side"], pos["entry"]
            hit = False
            if sl and side == "BUY"  and current <= sl: hit = True
            if tp and side == "BUY"  and current >= tp: hit = True
            if sl and side == "SELL" and current >= sl: hit = True
            if tp and side == "SELL" and current <= tp: hit = True
            if hit:
                to_close.append(name)
                agent = self._agent_by_name(name)
                if agent:
                    agent.on_trade_closed(entry=entry, exit_price=current, side=side)
                self._record_journal(name, pos, current, market_state)

        for name in to_close:
            pos    = self._positions.pop(name)
            entry  = pos["entry"]
            points = (current - entry) if pos["side"] == "BUY" else (entry - current)
            if self.event_bus:
                self.event_bus.publish("agent_trade_close", {
                    "agent": name,
                    "side": pos["side"],
                    "entry": entry,
                    "exit": current,
                    "points": round(points, 5),
                    "won": points > 0,
                    "lot": pos.get("lot", 0.01),
                    "symbol": self.symbol,
                })

    def _record_journal(self, agent_name: str, pos: dict, exit_price: float, ms: dict):
        points = (exit_price - pos["entry"]) if pos["side"] == "BUY" else (pos["entry"] - exit_price)
        self.journal.remember_trade(
            strategy=agent_name,
            side=pos["side"],
            probability=float(ms.get("probability", 0.5)),
            smc_buy_score=float(ms.get("smc_buy_score", 0)),
            smc_sell_score=float(ms.get("smc_sell_score", 0)),
            entry_price=pos["entry"],
            exit_price=exit_price,
            points=points,
            signal_type="agent_auto",
        )

    # ── helpers ────────────────────────────────────────────────────────────────

    def _net_bias(self) -> str | None:
        buys  = sum(1 for p in self._positions.values() if p["side"] == "BUY")
        sells = sum(1 for p in self._positions.values() if p["side"] == "SELL")
        if buys > sells:  return "BUY"
        if sells > buys:  return "SELL"
        return None

    def _agent_by_name(self, name: str) -> BaseAgent | None:
        for a in self.agents:
            if a.name == name:
                return a
        return None

    # ── status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "open_positions": dict(self._positions),
            "agent_summaries": {
                a.name: self.learning.summary(a.name)
                for a in self.agents
            },
        }

import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass
class PaperPosition:
    symbol: str
    side: str
    entry: float
    lot: float
    opened_at: float
    strategy: str
    probability: float
    smc_buy_score: float
    smc_sell_score: float
    reason: str
    mode: str = "paper_auto"
    # "strict_signal" = passed all profile filters (from scan.tradable)
    # "exploration"   = AutoPaperTrader weak-signal exploration (bypasses SMC filters)
    signal_type: str = "strict_signal"

    def to_dict(self):
        data = asdict(self)
        data["age_seconds"] = int(time.time() - self.opened_at)
        data["opened_at_iso"] = datetime.fromtimestamp(self.opened_at, timezone.utc).isoformat()
        return data


class AutoPaperTrader:
    """Autonomous multi-market paper trader.

    It never sends live MT5 orders. It scans MT5 symbols, opens simulated
    positions on strict signals, and can run exploration trades from the best
    candidates to feed the learning journal.
    """

    def __init__(
        self,
        assistant,
        event_bus=None,
        scan_limit=60,
        poll_seconds=45,
        max_positions=5,
        max_hold_seconds=900,
        tp_pct=0.0015,
        sl_pct=0.0010,
        exploration=True,
        execution_mode="paper",
    ):
        self.assistant = assistant
        self.event_bus = event_bus
        self.scan_limit = int(scan_limit)
        self.poll_seconds = int(poll_seconds)
        self.max_positions = int(max_positions)
        self.max_hold_seconds = int(max_hold_seconds)
        self.tp_pct = float(tp_pct)
        self.sl_pct = float(sl_pct)
        self.exploration = bool(exploration)
        self.execution_mode = execution_mode
        self.running = False
        self._thread = None
        self._lock = threading.Lock()
        self.positions = []
        self.demo_order_symbols = set()
        self.closed = []
        self.last_scan = None
        self.last_error = None

    def status(self):
        with self._lock:
            return {
                "running": self.running,
                "mode": "paper_auto",
                "execution_mode": self.execution_mode,
                "source": self.assistant.state.source,
                "scan_limit": self.scan_limit,
                "poll_seconds": self.poll_seconds,
                "max_positions": self.max_positions,
                "exploration": self.exploration,
                "open_positions": [position.to_dict() for position in self.positions],
                "recent_closed": self.closed[-10:],
                "last_scan": self.last_scan,
                "last_error": self.last_error,
            }

    def start(self):
        if self.running:
            return {"started": True, "reason": "already_running", "status": self.status()}
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._event("autopaper_started", self.status())
        return {"started": True, "status": self.status()}

    def stop(self):
        self.running = False
        self._event("autopaper_stopped", self.status())
        return {"stopped": True, "status": self.status()}

    def set_execution_mode(self, mode):
        if mode not in {"paper", "demo"}:
            return {"ok": False, "reason": "mode_must_be_paper_or_demo", "status": self.status()}
        self.execution_mode = mode
        self._event("autopaper_mode", {"execution_mode": mode})
        return {"ok": True, "status": self.status()}

    def promote_open_positions_to_demo(self):
        results = []
        with self._lock:
            positions = list(self.positions)
        for position in positions:
            if position.symbol in self.demo_order_symbols:
                continue
            result = self._send_demo_order_for_position(position)
            results.append({"symbol": position.symbol, "result": result})
        return {"promoted": len(results), "results": results, "status": self.status()}

    def _run(self):
        while self.running:
            try:
                self.step()
                self.last_error = None
            except Exception as exc:
                self.last_error = str(exc)
                self._event("autopaper_error", {"error": str(exc)})
            time.sleep(max(5, self.poll_seconds))

    def step(self):
        self._manage_positions()
        with self._lock:
            capacity = self.max_positions - len(self.positions)
        if capacity <= 0:
            return self.status()

        scan = self.assistant.scan_markets(limit=self.scan_limit)
        self.last_scan = {
            "scanned": scan.get("scanned", 0),
            "tradable": len(scan.get("tradable", [])),
            "top": [
                {
                    "symbol": item.get("symbol"),
                    "action": item.get("action"),
                    "probability": item.get("probability"),
                    "confidence": item.get("confidence"),
                    "score": item.get("score"),
                    "reason": item.get("reason"),
                }
                for item in scan.get("top", [])[:5]
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._event("autopaper_scan", self.last_scan)

        candidates = list(scan.get("tradable", []))
        if not candidates and self.exploration:
            candidates = self._exploration_candidates(scan.get("top", []))

        for item in candidates[:capacity]:
            self._open_from_candidate(item)
        return self.status()

    def _exploration_candidates(self, top):
        candidates = []
        for item in top:
            probability = float(item.get("probability") or 0.5)
            confidence = float(item.get("confidence") or 0.0)
            if confidence < 0.25:
                continue
            decision = dict(item.get("decision") or {})
            decision["action"] = "BUY" if probability >= 0.5 else "SELL"
            decision["reason"] = f"paper_exploration:{item.get('reason')}"
            clone = dict(item)
            clone["action"] = decision["action"]
            clone["decision"] = decision
            clone["_signal_type"] = "exploration"  # tag: bypasses SMC filters
            candidates.append(clone)
        return candidates

    def _open_from_candidate(self, item):
        decision = item.get("decision") or {}
        symbol = decision.get("symbol") or item.get("symbol")
        side = decision.get("action") or item.get("action")
        entry = float(decision.get("close") or item.get("close") or 0.0)
        if not symbol or side not in {"BUY", "SELL"} or entry <= 0:
            return None
        # Preserve signal_type tag set by _exploration_candidates; default to strict_signal.
        signal_type = item.get("_signal_type", "strict_signal")
        with self._lock:
            if any(position.symbol == symbol for position in self.positions):
                return None
            position = PaperPosition(
                symbol=symbol,
                side=side,
                entry=entry,
                lot=float(self.assistant.state.lot),
                opened_at=time.time(),
                strategy=decision.get("strategy", self.assistant.state.profile),
                probability=float(decision.get("probability") or 0.5),
                smc_buy_score=float(decision.get("smc_buy_score") or 0.0),
                smc_sell_score=float(decision.get("smc_sell_score") or 0.0),
                reason=decision.get("reason", "paper_auto"),
                mode="demo_mt5_auto" if self.execution_mode == "demo" else "paper_auto",
                signal_type=signal_type,
            )
            self.positions.append(position)

        broker_result = None
        if self.execution_mode == "demo":
            broker_result = self._send_demo_order_for_position(position, decision=decision)

        payload = {"position": position.to_dict(), "broker_result": broker_result}
        self.assistant.log_event({"type": "auto_paper_open", **payload})
        self._event("autodemo_open" if self.execution_mode == "demo" else "autopaper_open", payload)
        return position

    def _send_demo_order_for_position(self, position, decision=None):
        decision = dict(decision or {})
        decision.update(
            {
                "action": position.side,
                "symbol": position.symbol,
                "close": position.entry,
                "strategy": position.strategy,
                "probability": position.probability,
                "smc_buy_score": position.smc_buy_score,
                "smc_sell_score": position.smc_sell_score,
                "reason": position.reason,
                "source": self.assistant.state.source,
                "timeframe": self.assistant.state.timeframe,
            }
        )
        old_mode = self.assistant.state.mode
        self.assistant.state.mode = "demo"
        try:
            result = self.assistant.execute_decision(decision)
            if result.get("executed") or result.get("result", {}).get("sent"):
                self.demo_order_symbols.add(position.symbol)
            return result
        finally:
            self.assistant.state.mode = old_mode

    def _manage_positions(self):
        with self._lock:
            positions = list(self.positions)
        for position in positions:
            try:
                decision = self.assistant.analyze(symbol=position.symbol)
                current = float(decision.get("close") or position.entry)
            except Exception as exc:
                self._event("autopaper_manage_error", {"symbol": position.symbol, "error": str(exc)})
                continue

            pct = self._signed_pct(position, current)
            age = time.time() - position.opened_at
            close_reason = None
            if pct >= self.tp_pct:
                close_reason = "take_profit"
            elif pct <= -self.sl_pct:
                close_reason = "stop_loss"
            elif age >= self.max_hold_seconds:
                close_reason = "time_exit"

            if close_reason:
                self._close_position(position, current, close_reason)

    @staticmethod
    def _signed_pct(position, current):
        if position.side == "BUY":
            return (current - position.entry) / position.entry
        return (position.entry - current) / position.entry

    def _close_position(self, position, exit_price, reason):
        points = exit_price - position.entry
        if position.side == "SELL":
            points *= -1
        closed = {
            **position.to_dict(),
            "exit": float(exit_price),
            "points": float(points),
            "won": points > 0,
            "close_reason": reason,
            "closed_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self.positions = [item for item in self.positions if item is not position]
            self.closed.append(closed)
            self.closed = self.closed[-200:]

        self.assistant.brain.journal.remember_trade(
            strategy=position.strategy,
            side=position.side,
            probability=position.probability,
            smc_buy_score=position.smc_buy_score,
            smc_sell_score=position.smc_sell_score,
            entry_price=position.entry,
            exit_price=exit_price,
            points=points,
            signal_type=position.signal_type,
        )
        self.assistant.log_event({"type": "auto_paper_close", "position": closed})
        self._event("autopaper_close", {"position": closed})

    def _event(self, event_type, payload=None):
        if self.event_bus is not None:
            self.event_bus.publish(event_type, payload or {})

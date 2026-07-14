"""Per-currency lessons — the desk learns which symbols bleed and stops them.

This is the project's one proven edge made live: prune the bleeders. The book
reads the desk's own realised deal history per symbol, judges each symbol from
its net P&L and win-rate, and emits a verdict the trading loop consults before
opening anything:

* ``blocked``  — consistent loser: do not trade it.
* ``throttle`` — net-negative but not yet damning: trade, flagged.
* ``ok``       — neutral or winning.

Verdicts persist to ``data/lessons.json`` and publish to the bus so the live
dashboard shows what the desk has learned about each market.
"""
from __future__ import annotations

import json
import os

import config
from agents import broker
from data import bus

_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "lessons.json")


def _verdict(net: float, trades: int, wins: int) -> str:
    """Classify a symbol from its realised performance."""
    if trades < config.LESSON_MIN_TRADES:
        return "ok"
    wr = wins / trades if trades else 0.0
    if net < config.LESSON_BLOCK_NET and wr < config.LESSON_BLOCK_WINRATE:
        return "blocked"
    if net < 0:
        return "throttle"
    return "ok"


class LessonsBook:
    """Live per-symbol verdicts learned from realised trade history."""

    def __init__(self) -> None:
        """Load any persisted verdicts."""
        self.book: dict[str, dict] = {}
        self._load()

    def update(self) -> dict[str, dict]:
        """Recompute verdicts from recent deal history; persist and publish.

        Returns:
            The current per-symbol book.
        """
        stats = broker.realized_by_symbol(config.LESSON_LOOKBACK_DAYS)
        book: dict[str, dict] = {}
        for sym, s in stats.items():
            v = _verdict(s["net"], s["trades"], s["wins"])
            book[sym] = {**s, "verdict": v}
        self.book = book
        self._save()
        self._publish()
        return book

    def verdict(self, symbol: str) -> str:
        """Return the learned verdict for ``symbol`` (``ok`` if unseen)."""
        return self.book.get(symbol, {}).get("verdict", "ok")

    def _publish(self) -> None:
        blocked = sorted([s for s, v in self.book.items() if v["verdict"] == "blocked"])
        winners = sorted([s for s, v in self.book.items() if v["net"] > 0],
                         key=lambda s: self.book[s]["net"], reverse=True)
        losers = sorted([s for s in self.book if self.book[s]["net"] < 0],
                        key=lambda s: self.book[s]["net"])
        bus.write_slice("lessons", {
            "agent": "lessons", "active": "learning per-symbol",
            "blocked": blocked,
            "top_winners": [{"symbol": s, "net": self.book[s]["net"],
                             "trades": self.book[s]["trades"]} for s in winners[:8]],
            "top_losers": [{"symbol": s, "net": self.book[s]["net"],
                            "trades": self.book[s]["trades"],
                            "verdict": self.book[s]["verdict"]} for s in losers[:8]],
            "count": len(self.book)})

    def _save(self) -> None:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with open(_PATH, "w", encoding="utf-8") as fh:
            json.dump(self.book, fh, indent=2)

    def _load(self) -> None:
        try:
            with open(_PATH, "r", encoding="utf-8") as fh:
                self.book = json.load(fh)
        except Exception:
            self.book = {}

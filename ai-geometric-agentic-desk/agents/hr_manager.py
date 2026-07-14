"""HR Director — autonomous R&D + exam loop.

Per the spec's AUTONOMOUS_MODE, this manager repeatedly examines every symbol,
logs each retake transparently, and promotes a symbol to "deployable" only
when its walk-forward exam clears both gates (score >= 95 and PF >= 2.5). It
never lowers the bar to force a pass; a failing book stays in research.

It is the honest engine behind "loop R&D + Exam without permission until
PF >= 2.5 AND Exam = 100/100" — run it and it will keep grading, but it will
not pretend.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import config
from agents import broker
from agents.desk_agents import Bundle, HRExamAgent, MarketDataAgent
from data import db, bus


@dataclass
class Scorecard:
    """Best exam result seen for a symbol."""

    symbol: str
    best_score: float = 0.0
    best_pf: float = 0.0
    retakes: int = 0
    deployable: bool = False
    last_notes: str = ""


def grade_once(symbol: str, data_agent: MarketDataAgent,
               hr: HRExamAgent, card: Scorecard) -> Scorecard:
    """Run one exam for ``symbol`` and update its scorecard + the exam log."""
    market = config.classify(symbol)
    bundle = data_agent.gather(symbol, market)
    if bundle is None:
        card.last_notes = "no-data"
        return card
    exam, params = hr.examine(bundle)
    card.retakes += 1
    if exam.score > card.best_score:
        card.best_score, card.best_pf = exam.score, exam.profit_factor
    card.deployable = HRExamAgent.passes(exam)
    card.last_notes = exam.notes
    db.log_exam(market, {
        "ts": datetime.now(timezone.utc).isoformat(), "symbol": symbol,
        "score": exam.score, "profit_factor": exam.profit_factor,
        "trades": exam.trades, "win_rate": exam.win_rate,
        "expectancy_r": exam.expectancy_r, "params": str(params),
        "notes": f"HR retake#{card.retakes} {exam.notes}"})
    return card


GRADE_BATCH = 12  # symbols deep-graded per round (round-robins over the universe)


def run(symbols: list[str], timeframe: int, bars: int = 500,
        interval: float = 300.0, once: bool = False) -> dict[str, Scorecard]:
    """Run the HR autonomous grading loop in round-robin batches.

    For large symbol universes, each round deep-grades the next
    :data:`GRADE_BATCH` symbols and cycles through the rest on subsequent
    rounds, keeping the loop responsive while eventually covering everything.

    Args:
        symbols: Symbols to grade.
        timeframe: ``mt5.TIMEFRAME_*`` constant.
        bars: History depth per exam.
        interval: Seconds between grading rounds.
        once: Grade one batch and return.

    Returns:
        Mapping of symbol -> :class:`Scorecard`.
    """
    if not broker.connect():
        print("[hr] MT5 connect failed")
        return {}
    data_agent = MarketDataAgent(timeframe, bars)
    hr = HRExamAgent()
    cards = {s: Scorecard(s) for s in symbols}
    ring = bus.InsightRing()
    cursor = 0
    print(f"[hr] grading {len(symbols)} symbols, {GRADE_BATCH}/round")
    while True:
        batch = [symbols[(cursor + i) % len(symbols)] for i in range(min(GRADE_BATCH, len(symbols)))]
        cursor = (cursor + len(batch)) % len(symbols)
        for s in batch:
            prev = cards[s].best_score
            cards[s] = grade_once(s, data_agent, hr, cards[s])
            c = cards[s]
            flag = "DEPLOYABLE" if c.deployable else "research"
            if c.best_score > prev + 1e-6:
                ring.post("exam", f"📈 {s} أفضل نتيجة {c.best_score:.1f}/100 pf={c.best_pf:.2f}")
            print(f"[hr] {s:10} best={c.best_score:5.1f}/100 pf={c.best_pf:.2f} "
                  f"retakes={c.retakes} {flag} | {c.last_notes}")
        passing = [s for s, c in cards.items() if c.deployable]
        top = sorted(cards.values(), key=lambda x: x.best_score, reverse=True)[:10]
        bus.write_slice("hr", {
            "agent": "hr", "active": f"grading {batch[0] if batch else ''}",
            "cursor": cursor, "universe": len(symbols),
            "deployable": passing,
            "scores": [{"symbol": c.symbol, "score": round(c.best_score, 1),
                        "pf": round(c.best_pf, 2), "retakes": c.retakes,
                        "deployable": c.deployable} for c in top],
            "insights": ring.items})
        print(f"[hr] batch done (cursor={cursor}/{len(symbols)}) — "
              f"deployable: {passing or 'none yet'}")
        if once or not config.AUTONOMOUS_MODE:
            return cards
        time.sleep(interval)

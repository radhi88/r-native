"""Final transparency report generator.

Reads every per-market SQLite database and emits a Markdown report covering:
the Gann/Square-of-9 settings and model architecture in force, the latest
walk-forward exam scores per symbol, and the realised trade journal. Written
to ``reports/out/desk_report_<date>.md`` and echoed to stdout.
"""
from __future__ import annotations

import glob
import os
import sqlite3
from datetime import datetime, timezone

import config
from core.ml_signal import LogisticSignal
from markets import get as market_strategy

_DB_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "markets")
_OUT_DIR = os.path.join(os.path.dirname(__file__), "out")


def _architecture() -> str:
    """Describe the model + geometry architecture in force."""
    lines = ["## Model & Geometry Architecture", "",
             "- **ML**: dependency-free logistic regression, 5 causal features "
             "(momentum/vol ratio, volatility, bar range, body, range position), "
             f"trained per-window; confidence gate = {config.ML_CONFIDENCE_GATE:.0%}.",
             "- **RL**: linear Q-learning over the same 5 features, 3 actions "
             "(flat/long/short), net-R reward.",
             f"- **Confluence**: trade when >= {config.MIN_CONFLUENCES} signals align.",
             f"- **Sizing**: modified Kelly (cap {config.KELLY_CAP}), ATR stop, "
             f"survival reject > {config.SURVIVAL_REJECT_RISK:.0%} min-lot risk.",
             "", "### Per-market Gann/Sq9 settings", ""]
    for m in ("gold", "forex", "indices", "crypto", "stocks"):
        lines.append(f"- {market_strategy(m).describe()}")
    return "\n".join(lines)


def _exam_section() -> str:
    """Summarise the latest exam score per symbol across all market DBs."""
    rows = ["## Latest Walk-Forward Exam Scores", "",
            "| Symbol | Score | PF | Trades | WinRate | Exp(R) | Notes |",
            "|---|---|---|---|---|---|---|"]
    for dbf in sorted(glob.glob(os.path.join(_DB_DIR, "*.db"))):
        conn = sqlite3.connect(dbf)
        try:
            cur = conn.execute(
                "SELECT symbol, score, profit_factor, trades, win_rate, "
                "expectancy_r, notes FROM exam_log WHERE rowid IN "
                "(SELECT MAX(rowid) FROM exam_log GROUP BY symbol)")
            for s, sc, pf, tr, wr, ex, nt in cur.fetchall():
                rows.append(f"| {s} | {sc:.1f} | {pf:.2f} | {tr} | "
                            f"{(wr or 0):.0%} | {(ex or 0):+.3f} | {nt or ''} |")
        except sqlite3.OperationalError:
            pass
        conn.close()
    return "\n".join(rows)


def _journal_section() -> str:
    """List executed trades from the audit journals."""
    rows = ["## Executed Trade Journal", "",
            "| Symbol | Entry | SL dist | Kelly f | Confluences | Time |",
            "|---|---|---|---|---|---|"]
    for dbf in sorted(glob.glob(os.path.join(_DB_DIR, "*.db"))):
        conn = sqlite3.connect(dbf)
        try:
            cur = conn.execute(
                "SELECT symbol, entry_price, sl_dist, kelly_fraction, "
                "confluences_logged, timestamp FROM trade_journal_audit "
                "ORDER BY timestamp DESC LIMIT 50")
            for s, e, sld, kf, cf, ts in cur.fetchall():
                rows.append(f"| {s} | {e} | {sld:.5f} | {(kf or 0):.3f} | "
                            f"{cf or ''} | {ts} |")
        except sqlite3.OperationalError:
            pass
        conn.close()
    return "\n".join(rows)


def generate() -> str:
    """Build the full report, write it to disk, and return the text."""
    now = datetime.now(timezone.utc)
    parts = [f"# AI Geometric Agentic Desk — Report ({now:%Y-%m-%d %H:%M UTC})",
             "", f"- Magic: `{config.EXEC_MAGIC}` | LIVE_TRADING="
             f"{config.LIVE_TRADING} | DEMO_ONLY={config.DEMO_ONLY} | "
             f"REQUIRE_EXAM_PASS={config.REQUIRE_EXAM_PASS}",
             f"- Gates: exam >= {config.EXAM_PASS_SCORE}, PF >= {config.PF_TARGET}",
             "", _architecture(), "", _exam_section(), "", _journal_section(), ""]
    text = "\n".join(parts)
    os.makedirs(_OUT_DIR, exist_ok=True)
    out = os.path.join(_OUT_DIR, f"desk_report_{now:%Y%m%d}.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


if __name__ == "__main__":
    print(generate())

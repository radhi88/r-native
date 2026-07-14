import csv
import math
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .config import JOURNAL_DIR

_FIELDS = [
    "strategy", "side", "probability", "smc_buy_score", "smc_sell_score",
    "entry_price", "exit_price", "points", "won", "timestamp", "signal_type",
]
_LEGACY_FIELDS = [
    "strategy", "side", "probability", "smc_buy_score", "smc_sell_score",
    "entry_price", "exit_price", "points", "won", "timestamp",
]


@dataclass
class TradeMemory:
    strategy: str
    side: str
    probability: float
    smc_buy_score: float
    smc_sell_score: float
    entry_price: float
    exit_price: float
    points: float
    won: bool
    timestamp: str
    # "strict_signal" = passed all profile filters,
    # "exploration"   = AutoPaperTrader exploration (bypasses SMC filters),
    # "manual"        = user-triggered via CLI/UI,
    # "unknown"       = legacy rows recorded before this field was added
    signal_type: str = "unknown"


def _session_from_hour(hour: int) -> str:
    if 0 <= hour < 7:
        return "asia"
    if 7 <= hour < 13:
        return "london"
    if 13 <= hour < 20:
        return "ny"
    return "off"


class LearningJournal:
    def __init__(self, path=None):
        self.path = path or (JOURNAL_DIR / "trade_memory.csv")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def record(self, memory):
        self._ensure_schema()
        row = asdict(memory)
        exists = self.path.exists() and self.path.stat().st_size > 0
        with open(self.path, "a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=_FIELDS, extrasaction="ignore")
            if not exists:
                writer.writeheader()
            writer.writerow(row)

    def remember_trade(
        self,
        strategy,
        side,
        probability,
        smc_buy_score,
        smc_sell_score,
        entry_price,
        exit_price,
        points,
        signal_type="unknown",
    ):
        self.record(
            TradeMemory(
                strategy=strategy,
                side=side,
                probability=float(probability),
                smc_buy_score=float(smc_buy_score),
                smc_sell_score=float(smc_sell_score),
                entry_price=float(entry_price),
                exit_price=float(exit_price),
                points=float(points),
                won=points > 0,
                timestamp=datetime.now(timezone.utc).isoformat(),
                signal_type=str(signal_type),
            )
        )

    # ── internal ──────────────────────────────────────────────────────────────

    def _load_rows(self, strategy=None, lookback=None):
        if not self.path.exists():
            return []
        self._ensure_schema()
        rows = []
        with open(self.path, "r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if strategy is None or row.get("strategy") == strategy:
                    rows.append(row)
        return rows[-lookback:] if lookback else rows

    def _ensure_schema(self):
        """Migrate trade_memory.csv when newer rows include signal_type."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return

        with open(self.path, newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        if not rows:
            return

        header = rows[0]
        if header == _FIELDS:
            return
        if header != _LEGACY_FIELDS:
            return

        normalized = []
        for raw in rows[1:]:
            if not raw or not any(cell.strip() for cell in raw):
                continue
            if len(raw) >= len(_FIELDS):
                normalized.append(dict(zip(_FIELDS, raw[:len(_FIELDS)])))
            elif len(raw) == len(_LEGACY_FIELDS):
                item = dict(zip(_LEGACY_FIELDS, raw))
                item["signal_type"] = "unknown"
                normalized.append(item)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup = self.path.with_suffix(f".csv.bak_{stamp}")
        shutil.copy2(self.path, backup)

        with open(self.path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=_FIELDS)
            writer.writeheader()
            writer.writerows(normalized)

    # ── threshold adaptation ──────────────────────────────────────────────────

    def suggest_threshold_shift(self, strategy, lookback=100):
        rows = self._load_rows(strategy=strategy, lookback=lookback)
        if len(rows) < 20:
            return 0.0
        win_rate = sum(r["won"] == "True" for r in rows) / len(rows)
        if win_rate < 0.48:
            return 0.03
        if win_rate > 0.58:
            return -0.01
        return 0.0

    # ── win rate ──────────────────────────────────────────────────────────────

    def rolling_win_rate(self, strategy, lookback=50):
        rows = self._load_rows(strategy=strategy, lookback=lookback)
        if not rows:
            return None
        return sum(r["won"] == "True" for r in rows) / len(rows)

    # ── drawdown / streak ─────────────────────────────────────────────────────

    def max_consecutive_losses(self, strategy, lookback=100):
        rows = self._load_rows(strategy=strategy, lookback=lookback)
        max_streak = cur = 0
        for r in rows:
            if r["won"] != "True":
                cur += 1
                max_streak = max(max_streak, cur)
            else:
                cur = 0
        return max_streak

    def current_losing_streak(self, strategy, lookback=100):
        rows = self._load_rows(strategy=strategy, lookback=lookback)
        streak = 0
        for r in reversed(rows):
            if r["won"] != "True":
                streak += 1
            else:
                break
        return streak

    # ── risk ratios ───────────────────────────────────────────────────────────

    def sharpe_ratio(self, strategy=None, lookback=None):
        """Per-trade Sharpe (mean/std). Multiply by sqrt(N/year) to annualise."""
        rows = self._load_rows(strategy=strategy, lookback=lookback)
        if len(rows) < 10:
            return None
        pts = [float(r["points"]) for r in rows]
        mean = sum(pts) / len(pts)
        variance = sum((p - mean) ** 2 for p in pts) / len(pts)
        std = math.sqrt(variance)
        if std == 0:
            return None
        return mean / std

    def calmar_ratio(self, strategy=None, lookback=None):
        """Total points / max drawdown (in points)."""
        rows = self._load_rows(strategy=strategy, lookback=lookback)
        if len(rows) < 10:
            return None
        pts = [float(r["points"]) for r in rows]
        equity = peak = max_dd = 0.0
        for p in pts:
            equity += p
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
        if max_dd == 0:
            return None
        return sum(pts) / max_dd

    # ── statistical significance ──────────────────────────────────────────────

    def is_statistically_significant(self, strategy, lookback=100, min_trades=30, confidence=0.95):
        """
        Wilson score interval test: returns (bool, explanation_str).
        Significant = lower bound of CI is above 0.50.
        """
        rows = self._load_rows(strategy=strategy, lookback=lookback)
        n = len(rows)
        if n < min_trades:
            return False, f"only {n} trades (need {min_trades})"
        win_rate = sum(r["won"] == "True" for r in rows) / n
        z = 1.96 if confidence >= 0.95 else 1.645
        denom = 1 + z * z / n
        centre = (win_rate + z * z / (2 * n)) / denom
        margin = (z * math.sqrt(win_rate * (1 - win_rate) / n + z * z / (4 * n * n))) / denom
        lower = centre - margin
        upper = centre + margin
        significant = lower > 0.5
        return significant, f"win_rate={win_rate:.1%} CI=[{lower:.1%}, {upper:.1%}] n={n}"

    # ── session breakdown ─────────────────────────────────────────────────────

    def session_breakdown(self, strategy=None, lookback=None):
        """Returns per-session stats: trades, win_rate, avg_points."""
        rows = self._load_rows(strategy=strategy, lookback=lookback)
        buckets: dict[str, list] = {"asia": [], "london": [], "ny": [], "off": []}
        for r in rows:
            try:
                dt = datetime.fromisoformat(r["timestamp"])
                session = _session_from_hour(dt.hour)
            except (ValueError, KeyError):
                session = "off"
            buckets[session].append(r)

        result = {}
        for name, s_rows in buckets.items():
            if not s_rows:
                result[name] = None
                continue
            wins = sum(r["won"] == "True" for r in s_rows)
            pts = [float(r["points"]) for r in s_rows]
            result[name] = {
                "trades": len(s_rows),
                "win_rate": wins / len(s_rows),
                "avg_points": sum(pts) / len(pts),
            }
        return result

    # ── full summary ──────────────────────────────────────────────────────────

    def summary(self, strategy=None, lookback=100):
        rows = self._load_rows(strategy=strategy, lookback=lookback)
        n = len(rows)
        if n == 0:
            return {"trades": 0}
        wins = sum(r["won"] == "True" for r in rows)
        pts = [float(r["points"]) for r in rows]
        sig, sig_note = self.is_statistically_significant(strategy or "", lookback=lookback)
        return {
            "trades": n,
            "win_rate": wins / n,
            "avg_points": sum(pts) / n,
            "total_points": sum(pts),
            "max_consec_losses": self.max_consecutive_losses(strategy or "", lookback=lookback),
            "current_losing_streak": self.current_losing_streak(strategy or "", lookback=lookback),
            "sharpe": self.sharpe_ratio(strategy=strategy, lookback=lookback),
            "calmar": self.calmar_ratio(strategy=strategy, lookback=lookback),
            "significant": sig,
            "significance_note": sig_note,
            "by_session": self.session_breakdown(strategy=strategy, lookback=lookback),
        }

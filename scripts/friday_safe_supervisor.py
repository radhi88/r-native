import argparse
import json
import sqlite3
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import tensorflow as tf

from _bootstrap import bootstrap

bootstrap()

from friday_symbol_universe import PRIORITY_SYMBOLS, resolve_symbols
from mt5_ai.ai_brain import TradingBrain
from mt5_ai.config import (
    DEFAULT_LOT,
    FEATURE_COLUMNS,
    JOURNAL_DIR,
    MAX_LOT,
    MODEL_PATH,
    MT5_SYMBOL,
    REPORT_DIR,
    SCALER_PATH,
    SEQ_LEN,
)
from mt5_ai.market_structure import add_market_structure
from mt5_ai.mt5_gateway import MT5Gateway
from mt5_ai.strategy_profiles import PROFILES
from mt5_ai.agents.learning_engine import LearningEngine


DB_PATH = JOURNAL_DIR / "jarvis_memory.sqlite3"
DEFAULT_FOCUS_SYMBOLS = PRIORITY_SYMBOLS

EXIT_RULES = {
    "scalping": {"tp_atr": 1.15, "sl_atr": 0.80, "time_exit_minutes": 20},
    "sk": {"tp_atr": 1.30, "sl_atr": 0.85, "time_exit_minutes": 30},
    "sb": {"tp_atr": 1.35, "sl_atr": 0.90, "time_exit_minutes": 35},
    "ict": {"tp_atr": 1.45, "sl_atr": 0.95, "time_exit_minutes": 40},
    "swing": {"tp_atr": 1.65, "sl_atr": 1.00, "time_exit_minutes": 60},
}
DEFAULT_EXIT_RULE = {"tp_atr": 1.30, "sl_atr": 0.90, "time_exit_minutes": 35}
GOLD_SCALPING_EXIT_RULE = {"tp_atr": 0.90, "sl_atr": 0.65, "time_exit_minutes": 8}
BREAKEVEN_ATR_MULT = 0.70
TRAIL_ATR_MULT = 1.15
TRAIL_DISTANCE_ATR_MULT = 0.65
RESEARCH_SHADOW_MIN_CONTEXT = 3
RESEARCH_SHADOW_MIN_CONFIDENCE = 0.30
RESEARCH_SHADOW_MIN_SYMBOL_CONFIDENCE = 0.34
GOLD_SCALPER_MIN_CONTEXT = 2
GOLD_SCALPER_MIN_CONFIDENCE = 0.10
GOLD_SCALPER_MIN_SYMBOL_CONFIDENCE = 0.10


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def is_gold_scalper(symbol, profile):
    return str(symbol).upper().startswith("XAUUSD") and str(profile).lower() == "scalping"


def exit_rule_for(profile, symbol=None):
    if symbol and is_gold_scalper(symbol, profile):
        return GOLD_SCALPING_EXIT_RULE
    return EXIT_RULES.get(str(profile).lower(), DEFAULT_EXIT_RULE)


def connect_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS autonomous_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            profile TEXT NOT NULL,
            action TEXT NOT NULL,
            probability REAL NOT NULL,
            confidence REAL NOT NULL,
            context_score INTEGER DEFAULT 0,
            reason TEXT DEFAULT '',
            close REAL DEFAULT 0,
            spread REAL,
            trusted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS autonomous_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            profile TEXT NOT NULL,
            side TEXT NOT NULL,
            entry REAL NOT NULL,
            lot REAL NOT NULL,
            tp REAL NOT NULL,
            sl REAL NOT NULL,
            mode TEXT NOT NULL DEFAULT 'paper_shadow',
            status TEXT NOT NULL DEFAULT 'open',
            trusted INTEGER NOT NULL DEFAULT 0,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            exit REAL,
            points REAL,
            close_reason TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS autonomous_strategy_state (
            profile TEXT PRIMARY KEY,
            confidence REAL NOT NULL DEFAULT 0.35,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            net_points REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS autonomous_symbol_profile_state (
            symbol TEXT NOT NULL,
            profile TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.35,
            observations INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            net_points REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (symbol, profile)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS autonomous_research_outcomes (
            decision_id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            profile TEXT NOT NULL,
            implied_side TEXT NOT NULL,
            entry REAL NOT NULL,
            exit REAL NOT NULL,
            points REAL NOT NULL,
            horizon_seconds INTEGER NOT NULL,
            evaluated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS autonomous_heartbeat (
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            mode TEXT NOT NULL,
            message TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS autonomous_agent_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            points REAL NOT NULL,
            close_reason TEXT NOT NULL,
            thresholds_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def load_reports():
    reports = {}
    for split in ("val", "test"):
        path = REPORT_DIR / f"smc_profile_backtest_{split}.json"
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as handle:
            for row in json.load(handle):
                reports.setdefault(row["strategy"], {})[split] = row
    return reports


def strategy_trusted(profile, reports):
    data = reports.get(profile, {})
    val = data.get("val")
    test = data.get("test")
    if not val or not test:
        return False
    return (
        int(val.get("trades", 0)) >= 50
        and int(test.get("trades", 0)) >= 50
        and float(val.get("net_points", 0)) > 0
        and float(test.get("net_points", 0)) > 0
        and float(val.get("win_rate", 0)) >= 0.53
        and float(test.get("win_rate", 0)) >= 0.53
    )


def seed_strategy_state(conn, reports):
    for profile in PROFILES:
        data = reports.get(profile, {})
        val = data.get("val", {})
        test = data.get("test", {})
        net = float(val.get("net_points", 0)) + float(test.get("net_points", 0))
        win_rate = (float(val.get("win_rate", 0)) + float(test.get("win_rate", 0))) / 2
        confidence = min(0.70, max(0.20, 0.25 + max(win_rate - 0.50, 0) * 2 + max(net, 0) / 1000))
        conn.execute(
            """
            INSERT INTO autonomous_strategy_state (profile, confidence, wins, losses, net_points, updated_at)
            VALUES (?, ?, 0, 0, 0, ?)
            ON CONFLICT(profile) DO NOTHING
            """,
            (profile, confidence, now_iso()),
        )
    conn.commit()


def symbol_focus_weight(symbol):
    if symbol.upper().startswith("XAUUSD"):
        return 1.65
    if symbol.upper().endswith("JPYM"):
        return 0.95
    return 1.0


def seed_symbol_profile_state(conn, symbols, profiles):
    for symbol in symbols:
        for profile in profiles:
            confidence = 0.38 if symbol.upper().startswith("XAUUSD") else 0.33
            conn.execute(
                """
                INSERT INTO autonomous_symbol_profile_state
                    (symbol, profile, confidence, observations, wins, losses, net_points, updated_at)
                VALUES (?, ?, ?, 0, 0, 0, 0, ?)
                ON CONFLICT(symbol, profile) DO NOTHING
                """,
                (symbol, profile, confidence, now_iso()),
            )
    conn.commit()


def get_strategy_confidence(conn, profile):
    row = conn.execute(
        "SELECT confidence FROM autonomous_strategy_state WHERE profile = ?",
        (profile,),
    ).fetchone()
    return float(row["confidence"]) if row else 0.35


def get_symbol_profile_confidence(conn, symbol, profile):
    row = conn.execute(
        """
        SELECT confidence
        FROM autonomous_symbol_profile_state
        WHERE symbol = ? AND profile = ?
        """,
        (symbol, profile),
    ).fetchone()
    return float(row["confidence"]) if row else 0.35


def update_strategy_after_close(conn, profile, points):
    row = conn.execute(
        "SELECT confidence, wins, losses, net_points FROM autonomous_strategy_state WHERE profile = ?",
        (profile,),
    ).fetchone()
    confidence = float(row["confidence"]) if row else 0.35
    wins = int(row["wins"]) if row else 0
    losses = int(row["losses"]) if row else 0
    net_points = float(row["net_points"]) if row else 0.0
    if points > 0:
        wins += 1
        confidence = min(0.95, confidence + 0.02)
    else:
        losses += 1
        confidence = max(0.10, confidence - 0.04)
    net_points += float(points)
    conn.execute(
        """
        INSERT INTO autonomous_strategy_state (profile, confidence, wins, losses, net_points, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(profile) DO UPDATE SET
            confidence=excluded.confidence,
            wins=excluded.wins,
            losses=excluded.losses,
            net_points=excluded.net_points,
            updated_at=excluded.updated_at
        """,
        (profile, confidence, wins, losses, net_points, now_iso()),
    )
    conn.commit()


def update_symbol_profile_after_outcome(conn, symbol, profile, points, learning_rate=1.0):
    row = conn.execute(
        """
        SELECT confidence, observations, wins, losses, net_points
        FROM autonomous_symbol_profile_state
        WHERE symbol = ? AND profile = ?
        """,
        (symbol, profile),
    ).fetchone()
    confidence = float(row["confidence"]) if row else (0.38 if symbol.upper().startswith("XAUUSD") else 0.33)
    observations = int(row["observations"]) if row else 0
    wins = int(row["wins"]) if row else 0
    losses = int(row["losses"]) if row else 0
    net_points = float(row["net_points"]) if row else 0.0

    observations += 1
    if points > 0:
        wins += 1
        confidence = min(0.90, confidence + 0.006 * learning_rate * symbol_focus_weight(symbol))
    else:
        losses += 1
        confidence = max(0.10, confidence - 0.010 * learning_rate)
    net_points += float(points)

    conn.execute(
        """
        INSERT INTO autonomous_symbol_profile_state
            (symbol, profile, confidence, observations, wins, losses, net_points, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, profile) DO UPDATE SET
            confidence=excluded.confidence,
            observations=excluded.observations,
            wins=excluded.wins,
            losses=excluded.losses,
            net_points=excluded.net_points,
            updated_at=excluded.updated_at
        """,
        (symbol, profile, confidence, observations, wins, losses, net_points, now_iso()),
    )
    conn.commit()


def record_agent_adaptation(conn, symbol, profile, side, entry, exit_price, points, close_reason):
    learner = LearningEngine()
    learner.record(
        agent=profile,
        side=side,
        entry=float(entry),
        exit_price=float(exit_price),
        points=float(points),
    )
    summary = learner.summary(profile, lookback=50)
    thresholds = summary.get("thresholds", {})
    conn.execute(
        """
        INSERT INTO autonomous_agent_adjustments
            (profile, symbol, side, points, close_reason, thresholds_json, summary_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            profile,
            symbol,
            side,
            float(points),
            close_reason,
            json.dumps(thresholds, ensure_ascii=False, sort_keys=True),
            json.dumps(summary, ensure_ascii=False, sort_keys=True),
            now_iso(),
        ),
    )
    conn.commit()


def heartbeat(conn, run_id, status, mode, message):
    conn.execute(
        """
        INSERT INTO autonomous_heartbeat (run_id, status, mode, message, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            status=excluded.status,
            mode=excluded.mode,
            message=excluded.message,
            updated_at=excluded.updated_at
        """,
        (run_id, status, mode, message, now_iso()),
    )
    conn.commit()


def mark_other_runs_stale(conn, active_run_id):
    conn.execute(
        """
        UPDATE autonomous_heartbeat
        SET status = 'stale',
            message = 'superseded_by_new_supervisor',
            updated_at = ?
        WHERE run_id <> ? AND status = 'running'
        """,
        (now_iso(), active_run_id),
    )
    conn.commit()


def open_position_count(conn):
    row = conn.execute("SELECT COUNT(*) AS n FROM autonomous_positions WHERE status = 'open'").fetchone()
    return int(row["n"])


def has_open_position(conn, symbol, profile):
    row = conn.execute(
        """
        SELECT id FROM autonomous_positions
        WHERE status = 'open' AND symbol = ? AND profile = ?
        LIMIT 1
        """,
        (symbol, profile),
    ).fetchone()
    return row is not None


def has_open_symbol(conn, symbol):
    row = conn.execute(
        """
        SELECT id FROM autonomous_positions
        WHERE status = 'open' AND symbol = ?
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    return row is not None


def has_open_gold(conn):
    row = conn.execute(
        """
        SELECT id FROM autonomous_positions
        WHERE status = 'open' AND UPPER(symbol) LIKE 'XAUUSD%'
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def record_decision(conn, run_id, symbol, profile, decision, close, spread, trusted):
    conn.execute(
        """
        INSERT INTO autonomous_decisions
            (run_id, symbol, profile, action, probability, confidence, context_score, reason, close, spread, trusted, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            symbol,
            profile,
            decision["action"],
            float(decision.get("probability", 0.5)),
            float(decision.get("confidence", 0.0)),
            int(decision.get("context_score", 0) or 0),
            decision.get("reason", ""),
            float(close),
            None if spread is None else float(spread),
            int(bool(trusted)),
            now_iso(),
        ),
    )
    conn.commit()


def lot_for(confidence, decision_confidence, trusted):
    if not trusted:
        return DEFAULT_LOT
    if confidence >= 0.80 and decision_confidence >= 0.35:
        return min(MAX_LOT, 0.03)
    if confidence >= 0.65 and decision_confidence >= 0.25:
        return min(MAX_LOT, 0.02)
    return DEFAULT_LOT


def research_shadow_allowed(conn, symbol, profile, decision, gold_scalper_mode=False):
    if decision["action"] not in {"BUY", "SELL"}:
        return False
    if gold_scalper_mode and is_gold_scalper(symbol, profile):
        min_context = GOLD_SCALPER_MIN_CONTEXT
        min_confidence = GOLD_SCALPER_MIN_CONFIDENCE
        min_symbol_confidence = GOLD_SCALPER_MIN_SYMBOL_CONFIDENCE
    else:
        min_context = RESEARCH_SHADOW_MIN_CONTEXT
        min_confidence = RESEARCH_SHADOW_MIN_CONFIDENCE
        min_symbol_confidence = RESEARCH_SHADOW_MIN_SYMBOL_CONFIDENCE
    if int(decision.get("context_score", 0) or 0) < min_context:
        return False
    if float(decision.get("confidence", 0.0) or 0.0) < min_confidence:
        return False
    if get_symbol_profile_confidence(conn, symbol, profile) < min_symbol_confidence:
        return False
    return True


def open_shadow_position(conn, run_id, symbol, profile, side, close, atr_ratio, lot, trusted):
    atr_price = max(float(atr_ratio) * float(close), float(close) * 0.0005)
    rule = exit_rule_for(profile, symbol=symbol)
    tp_distance = float(rule["tp_atr"]) * atr_price
    sl_distance = float(rule["sl_atr"]) * atr_price
    if side == "BUY":
        tp = close + tp_distance
        sl = close - sl_distance
    else:
        tp = close - tp_distance
        sl = close + sl_distance
    conn.execute(
        """
        INSERT INTO autonomous_positions
            (run_id, symbol, profile, side, entry, lot, tp, sl, mode, status, trusted, opened_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'paper_shadow', 'open', ?, ?)
        """,
        (run_id, symbol, profile, side, float(close), float(lot), float(tp), float(sl), int(bool(trusted)), now_iso()),
    )
    conn.commit()


def manage_positions(conn, gateway, timeframe):
    rows = conn.execute("SELECT * FROM autonomous_positions WHERE status = 'open'").fetchall()
    for row in rows:
        try:
            df = gateway.fetch_rates(row["symbol"], timeframe, 5)
            current = float(df["close"].iloc[-1])
        except Exception:
            continue

        side = row["side"]
        close_reason = None
        entry = float(row["entry"])
        current_sl = float(row["sl"])
        current_tp = float(row["tp"])
        rule = exit_rule_for(row["profile"], symbol=row["symbol"])
        atr_at_entry = max(abs(entry - current_sl) / max(float(rule["sl_atr"]), 0.01), entry * 0.0005)
        if side == "BUY":
            if current >= current_tp:
                close_reason = "tp"
            elif current <= current_sl:
                close_reason = "sl"
            points = current - entry
        else:
            if current <= current_tp:
                close_reason = "tp"
            elif current >= current_sl:
                close_reason = "sl"
            points = entry - current

        opened_at = datetime.fromisoformat(row["opened_at"])
        age_seconds = (datetime.now(timezone.utc) - opened_at).total_seconds()
        if close_reason is None:
            new_sl = None
            if side == "BUY":
                if points >= TRAIL_ATR_MULT * atr_at_entry:
                    new_sl = max(current - TRAIL_DISTANCE_ATR_MULT * atr_at_entry, entry, current_sl)
                elif points >= BREAKEVEN_ATR_MULT * atr_at_entry and current_sl < entry:
                    new_sl = entry
            else:
                if points >= TRAIL_ATR_MULT * atr_at_entry:
                    new_sl = min(current + TRAIL_DISTANCE_ATR_MULT * atr_at_entry, entry, current_sl)
                elif points >= BREAKEVEN_ATR_MULT * atr_at_entry and current_sl > entry:
                    new_sl = entry
            if new_sl is not None and abs(float(new_sl) - current_sl) > max(entry * 0.00001, 0.00001):
                conn.execute(
                    "UPDATE autonomous_positions SET sl = ? WHERE id = ?",
                    (float(new_sl), int(row["id"])),
                )
                conn.commit()

        if close_reason is None and age_seconds >= float(rule["time_exit_minutes"]) * 60:
            close_reason = "time_exit"
        if close_reason is None:
            continue

        conn.execute(
            """
            UPDATE autonomous_positions
            SET status = 'closed', closed_at = ?, exit = ?, points = ?, close_reason = ?
            WHERE id = ?
            """,
            (now_iso(), float(current), float(points), close_reason, int(row["id"])),
        )
        conn.commit()
        update_strategy_after_close(conn, row["profile"], points)
        update_symbol_profile_after_outcome(conn, row["symbol"], row["profile"], points, learning_rate=1.0)
        record_agent_adaptation(
            conn=conn,
            symbol=row["symbol"],
            profile=row["profile"],
            side=side,
            entry=entry,
            exit_price=current,
            points=points,
            close_reason=close_reason,
        )


def implied_side_from_probability(probability, neutral_band):
    if probability >= 0.5 + neutral_band:
        return "BUY"
    if probability <= 0.5 - neutral_band:
        return "SELL"
    return None


def manage_research_outcomes(conn, gateway, allowed_symbols, horizon_seconds, neutral_band, max_per_cycle):
    allowed_symbols = [symbol for symbol in allowed_symbols if symbol]
    if allowed_symbols:
        placeholders = ",".join("?" for _ in allowed_symbols)
        symbol_filter = f"AND d.symbol IN ({placeholders})"
        params = [*allowed_symbols, int(max_per_cycle) * 5]
    else:
        symbol_filter = ""
        params = [int(max_per_cycle) * 5]
    rows = conn.execute(
        f"""
        SELECT d.*
        FROM autonomous_decisions d
        LEFT JOIN autonomous_research_outcomes o ON o.decision_id = d.id
        WHERE o.decision_id IS NULL
          {symbol_filter}
        ORDER BY d.id ASC
        LIMIT ?
        """,
        params,
    ).fetchall()
    evaluated = 0
    for row in rows:
        try:
            created_at = datetime.fromisoformat(row["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if (datetime.now(timezone.utc) - created_at).total_seconds() < int(horizon_seconds):
            continue
        if evaluated >= int(max_per_cycle):
            break

        implied_side = implied_side_from_probability(float(row["probability"]), neutral_band)
        if implied_side is None:
            continue
        try:
            df = gateway.fetch_rates(row["symbol"], "M1", 3)
            current = float(df["close"].iloc[-1])
        except Exception:
            continue

        entry = float(row["close"])
        if implied_side == "BUY":
            points = current - entry
        else:
            points = entry - current

        conn.execute(
            """
            INSERT OR IGNORE INTO autonomous_research_outcomes
                (decision_id, symbol, profile, implied_side, entry, exit, points, horizon_seconds, evaluated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(row["id"]),
                row["symbol"],
                row["profile"],
                implied_side,
                entry,
                current,
                float(points),
                int(horizon_seconds),
                now_iso(),
            ),
        )
        conn.commit()
        update_symbol_profile_after_outcome(conn, row["symbol"], row["profile"], points, learning_rate=0.35)
        evaluated += 1


def build_sequence(df, scaler):
    enriched = add_market_structure(df)
    seq = enriched[FEATURE_COLUMNS].tail(SEQ_LEN).to_numpy(dtype=np.float32)
    if len(seq) < SEQ_LEN:
        raise RuntimeError(f"Need {SEQ_LEN} bars, got {len(seq)}")
    seq = scaler.transform(seq)
    return seq.reshape(1, SEQ_LEN, len(FEATURE_COLUMNS)), enriched


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval-seconds", type=int, default=15)
    parser.add_argument("--position-interval-seconds", type=int, default=1)
    parser.add_argument("--timeframe", default="M1")
    parser.add_argument("--bars", type=int, default=500)
    parser.add_argument("--max-symbols", type=int, default=0, help="0 = all discovered MT5 symbols")
    parser.add_argument("--max-scan-spread", type=float, default=350.0)
    parser.add_argument("--symbols", default="all")
    parser.add_argument("--max-open", type=int, default=3)
    parser.add_argument("--profiles", default="scalping,sk,sb,ict,swing")
    parser.add_argument("--ignore-spread-filter", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--gold-scalper-mode", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--reserve-gold-slot", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--research-horizon-seconds", type=int, default=900)
    parser.add_argument("--research-neutral-band", type=float, default=0.08)
    parser.add_argument("--research-max-per-cycle", type=int, default=250)
    parser.add_argument("--research-shadow", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--mode", choices=["monitor", "paper"], default="paper")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    run_id = f"safe-supervisor-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    conn = connect_db()
    init_db(conn)
    mark_other_runs_stale(conn, run_id)
    reports = load_reports()
    seed_strategy_state(conn, reports)

    model = tf.keras.models.load_model(MODEL_PATH, compile=False)
    scaler = joblib.load(SCALER_PATH)
    gateway = MT5Gateway()
    gateway.initialize()
    profile_names = [name.strip() for name in args.profiles.split(",") if name.strip() in PROFILES]
    if args.gold_scalper_mode and "scalping" in profile_names:
        profile_names = ["scalping"] + [name for name in profile_names if name != "scalping"]
    brains = {name: TradingBrain(model=model, profile_name=name) for name in profile_names}
    configured_symbols = resolve_symbols(
        args.symbols,
        gateway.mt5,
        limit=args.max_symbols if args.max_symbols > 0 else None,
    )
    if args.gold_scalper_mode:
        configured_symbols = [MT5_SYMBOL] + [symbol for symbol in configured_symbols if symbol != MT5_SYMBOL]
    seed_symbol_profile_state(conn, configured_symbols, profile_names)

    try:
        while True:
            try:
                account = gateway.account_snapshot()
                demo = bool(account.get("demo_detected"))
                if args.symbols.strip():
                    symbols = configured_symbols
                else:
                    symbol_items = gateway.symbols(
                        visible_only=False,
                        tradable_only=True,
                        limit=0 if args.max_symbols <= 0 else max(args.max_symbols * 8, args.max_symbols),
                    )
                    symbols = [
                        item["symbol"]
                        for item in symbol_items
                        if item["symbol"] == MT5_SYMBOL
                        or item.get("spread") is None
                        or float(item.get("spread") or 0) <= args.max_scan_spread
                    ]
                if MT5_SYMBOL not in symbols:
                    symbols.insert(0, MT5_SYMBOL)
                if args.max_symbols > 0:
                    symbols = symbols[: args.max_symbols]
                manage_positions(conn, gateway, args.timeframe)
                manage_research_outcomes(
                    conn,
                    gateway,
                    allowed_symbols=symbols,
                    horizon_seconds=args.research_horizon_seconds,
                    neutral_band=args.research_neutral_band,
                    max_per_cycle=args.research_max_per_cycle,
                )
                opened = 0
                evaluated = 0

                for symbol in symbols:
                    try:
                        df = gateway.fetch_rates(symbol, args.timeframe, args.bars)
                        sequence, enriched = build_sequence(df, scaler)
                        close = float(enriched["close"].iloc[-1])
                        spread = float(enriched["spread"].iloc[-1]) if "spread" in enriched.columns else None
                        atr_ratio = float(enriched["atr"].iloc[-1])
                    except Exception as exc:
                        heartbeat(conn, run_id, "warning", args.mode, f"{symbol}: {exc}")
                        continue

                    for profile in profile_names:
                        brain = brains[profile]
                        probability = brain.predict_probability(sequence)
                        decision = brain.decide(
                            df=enriched,
                            sequence=sequence,
                            probability=probability,
                            spread=spread,
                            ignore_spread=args.mode == "paper" and args.ignore_spread_filter,
                        ).to_dict()
                        trusted = strategy_trusted(profile, reports)
                        record_decision(conn, run_id, symbol, profile, decision, close, spread, trusted)
                        evaluated += 1

                        if args.mode != "paper":
                            continue
                        if decision["action"] not in {"BUY", "SELL"}:
                            continue
                        if not trusted and not args.research_shadow:
                            continue
                        if not trusted and not research_shadow_allowed(
                            conn,
                            symbol,
                            profile,
                            decision,
                            gold_scalper_mode=args.gold_scalper_mode,
                        ):
                            continue
                        symbol_confidence = get_symbol_profile_confidence(conn, symbol, profile)
                        if trusted and symbol_confidence < 0.50:
                            continue
                        if not demo:
                            continue
                        current_open = open_position_count(conn)
                        if current_open >= args.max_open:
                            continue
                        if (
                            args.gold_scalper_mode
                            and args.reserve_gold_slot
                            and not symbol.upper().startswith("XAUUSD")
                            and not has_open_gold(conn)
                            and current_open >= max(1, args.max_open - 1)
                        ):
                            continue
                        if has_open_symbol(conn, symbol):
                            continue
                        if has_open_position(conn, symbol, profile):
                            continue

                        confidence = get_strategy_confidence(conn, profile)
                        lot = lot_for(confidence, float(decision.get("confidence") or 0.0), trusted)
                        open_shadow_position(
                            conn=conn,
                            run_id=run_id,
                            symbol=symbol,
                            profile=profile,
                            side=decision["action"],
                            close=close,
                            atr_ratio=atr_ratio,
                            lot=lot,
                            trusted=trusted,
                        )
                        opened += 1

                heartbeat(
                    conn,
                    run_id,
                    "running",
                    args.mode,
                    (
                        f"demo={demo} evaluated={evaluated} opened_shadow={opened} "
                        f"open={open_position_count(conn)} gold_scalper={int(args.gold_scalper_mode)} "
                        f"ignore_spread={int(args.mode == 'paper' and args.ignore_spread_filter)} "
                        f"reserve_gold={int(args.gold_scalper_mode and args.reserve_gold_slot)}"
                    ),
                )
            except Exception as exc:
                heartbeat(conn, run_id, "error", args.mode, str(exc))

            if args.once:
                break
            sleep_deadline = time.monotonic() + max(1, int(args.interval_seconds))
            while time.monotonic() < sleep_deadline:
                try:
                    manage_positions(conn, gateway, args.timeframe)
                    heartbeat(
                        conn,
                        run_id,
                        "running",
                        args.mode,
                        (
                            f"position_tick={max(1, int(args.position_interval_seconds))}s "
                            f"scan_interval={max(1, int(args.interval_seconds))}s "
                            f"open={open_position_count(conn)} "
                            f"gold_scalper={int(args.gold_scalper_mode)} "
                            f"ignore_spread={int(args.mode == 'paper' and args.ignore_spread_filter)} "
                            f"reserve_gold={int(args.gold_scalper_mode and args.reserve_gold_slot)}"
                        ),
                    )
                except Exception as exc:
                    heartbeat(conn, run_id, "warning", args.mode, f"position_tick_error:{exc}")
                remaining = sleep_deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(max(1, int(args.position_interval_seconds)), remaining))
    finally:
        gateway.shutdown()
        conn.close()


if __name__ == "__main__":
    main()

"""
FRIDAY Auto Trader - safe MT5 auto trader with multi-market fallback.

Safety policy:
- Demo account: may send demo MT5 orders.
- Live account: analysis only; broker execution is blocked and paper logged.
- If the primary market is closed, the trader scans configured fallback symbols.
- Each symbol has its own brain, pivot cache, confidence score, cooldown,
  journal file, and persistent execution/outcome memory.

Features:
- Bar-close detection (1s polling, analyzes only on new M1 bar)
- Fast protective SL: checks every 1s, locks near break-even from $0.01 profit,
  then trails per symbol
- Direction flip: reverses position when strong opposing signal appears
- Trend filter: only trades in direction of trend + smc_bias
- Consecutive-loss guard: skips symbol after 3 consecutive losses

Usage:
    python friday_auto_trader.py --symbol XAUUSDm
    python friday_auto_trader.py --symbols XAUUSDm,BTCUSDm,ETHUSDm,EURUSDm
"""
from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import tensorflow as tf
from sklearn.preprocessing import StandardScaler

from _bootstrap import bootstrap

bootstrap()

from friday_symbol_universe import resolve_symbols, wants_all_symbols
from mt5_ai.ai_brain import TradingBrain
try:
    from mt5_ai.tick_trigger import TickTrigger as _TickTrigger
    _TICK_TRIGGER_OK = True
except ImportError:
    _TickTrigger = None   # type: ignore
    _TICK_TRIGGER_OK = False

from mt5_ai.config import (
    AGGRESSIVE_SCALPING_IGNORE_SPREAD,
    DATA_DIR,
    DEFAULT_LOT,
    FEATURE_COLUMNS,
    JOURNAL_DIR,
    LOG_DIR,
    MAX_LOT,
    MODEL_PATH,
    MT5_SYMBOL,
    SCALER_PATH,
    SEQ_LEN,
)
from mt5_ai.confidence_engine import ConfidenceEngine
from mt5_ai.execution import DemoMT5Executor, PaperExecutor, SafeMT5Executor
from mt5_ai.learning_journal import LearningJournal
from mt5_ai.market_structure import add_market_structure
from mt5_ai.mt5_gateway import MT5Gateway
from mt5_ai.pivot_engine import PivotEngine


DEFAULT_FALLBACK_SYMBOLS = (
    MT5_SYMBOL,
    "BTCUSDm",
    "ETHUSDm",
    "EURUSDm",
    "GBPUSDm",
    "USDJPYm",
    "USOILm",
    "XAGUSDm",
)

SYMBOL_RISK = {
    "BTCUSDm": {"sl_pct": 0.0050, "tp_pct": 0.0075},
    "ETHUSDm": {"sl_pct": 0.0050, "tp_pct": 0.0075},
    "USOILm": {"sl_pct": 0.0030, "tp_pct": 0.0045},
    "XAGUSDm": {"sl_pct": 0.0015, "tp_pct": 0.0022},
    "_default": {"sl_pct": 0.0010, "tp_pct": 0.0015},
}

MARKET_CLOSED_RETCODES = {10018}
MARKET_STALE_SECONDS = 15 * 60
MARKET_CLOSED_RETRY_SECONDS = 30 * 60
MAX_RECENT_MEMORY_EVENTS = 200

# Trailing SL config
TRAIL_TRIGGER_USD   = 0.50   # start protection as soon as profit is visible
TRAIL_CHECK_SECONDS = 1.0    # fast monitor cadence
TRAIL_GAP_PCT       = 0.0010 # fallback trail gap = 0.10% of entry price
TRAIL_MIN_POINTS    = 30     # fallback minimum trail gap in points
TRAIL_LOCK_POINTS   = 2      # fallback tiny profit lock once broker distance allows
TRAIL_STEP_POINTS   = 2      # minimum improvement before sending another modify

SYMBOL_TRAILING = {
    # Values are in broker points. They are intentionally tighter than the
    # original 0.05% gap because this is a scalping executor.
    "XAUUSDm": {"trigger_usd": 0.50, "lock_points": 20, "trail_points": 250, "step_points": 20},
    "XAGUSDm": {"trigger_usd": 0.50, "lock_points": 10, "trail_points": 120, "step_points": 10},
    "USOILm":  {"trigger_usd": 0.50, "lock_points": 10, "trail_points": 120, "step_points": 10},
    "BTCUSDm": {"trigger_usd": 0.50, "lock_points": 500, "trail_points": 5000, "step_points": 500},
    "ETHUSDm": {"trigger_usd": 0.50, "lock_points": 250, "trail_points": 3000, "step_points": 250},
    "_default": {"trigger_usd": TRAIL_TRIGGER_USD, "lock_points": TRAIL_LOCK_POINTS,
                 "trail_points": TRAIL_MIN_POINTS, "step_points": TRAIL_STEP_POINTS},
}

# Direction flip. Disabled by default because this Exness demo account is
# hedging-mode: an opposite order opens another position instead of closing the
# old one. Re-enable only after adding an explicit close-position implementation.
ENABLE_DIRECTION_FLIP = False
FLIP_PROB_BUY_MIN   = 0.72   # prob above this + holding SELL → flip to BUY
FLIP_PROB_SELL_MAX  = 0.28   # prob below this + holding BUY → flip to SELL

# Consecutive-loss guard
MAX_CONSECUTIVE_LOSSES = 3
LOSS_COOLDOWN_SECONDS = 15 * 60   # قُلّل من 45 → 15 دقيقة للتعافي الأسرع

# Memory-based symbol selection. The bot still analyzes every market, but weak
# historical performers need a much stronger current setup before execution.
SYMBOL_PERFORMANCE_MIN_TRADES = 20
SYMBOL_WEAK_PROFIT_USD = -10.0
SYMBOL_WEAK_WIN_RATE = 0.45
SYMBOL_SEVERE_PROFIT_USD = -25.0
SYMBOL_SEVERE_AVG_PROFIT_USD = -0.20
SYMBOL_WEAK_MIN_CONFIDENCE = 0.22
SYMBOL_SEVERE_MIN_CONFIDENCE = 0.35
SYMBOL_SEVERE_RECOVERY_ONLY = True


@dataclass
class SymbolContext:
    symbol: str
    brain: TradingBrain
    pivot: PivotEngine
    confidence: ConfidenceEngine
    journal: LearningJournal
    point_size: float
    volume_min: float
    volume_step: float
    volume_max: float
    sl_pct: float
    tp_pct: float
    closed_until: float = 0.0
    loss_cooldown_until: float = 0.0
    last_bar_time: str | None = None
    last_bar_age_seconds: float | None = None
    last_analyzed_bar: str | None = None   # bar-close dedup key
    consecutive_losses: int = 0            # reset on win, increment on loss


def _json_default(value: Any):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _safe_symbol_for_path(symbol: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in symbol)


def _parse_symbols(primary: str, symbols_arg: str | None) -> list[str]:
    if wants_all_symbols(symbols_arg):
        return ["all"]
    raw = symbols_arg.split(",") if symbols_arg else [primary, *DEFAULT_FALLBACK_SYMBOLS]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        symbol = str(item or "").strip()
        if not symbol or symbol in seen:
            continue
        result.append(symbol)
        seen.add(symbol)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Trailing SL background thread
# ──────────────────────────────────────────────────────────────────────────────

class TrailingSLThread(threading.Thread):
    """Fast protective SL monitor: break-even lock first, then symbol-specific trail."""

    def __init__(self, trader: "AutoTrader"):
        super().__init__(daemon=True, name="FRIDAY-TrailSL")
        self.trader = trader
        self._stop_event = threading.Event()
        self._last_fail: dict[int, int] = {}

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.wait(TRAIL_CHECK_SECONDS):
            try:
                self._trail_all()
            except Exception as exc:
                pass  # never crash the thread

    @staticmethod
    def _cfg(symbol: str) -> dict:
        cfg = dict(SYMBOL_TRAILING["_default"])
        cfg.update(SYMBOL_TRAILING.get(symbol, {}))
        return cfg

    @staticmethod
    def _round_price(trader: "AutoTrader", symbol: str, value: float) -> float:
        try:
            info = trader.gateway.mt5.symbol_info(symbol)
            digits = int(getattr(info, "digits", 5) or 5)
        except Exception:
            digits = 5
        return round(float(value), digits)

    def _trail_all(self):
        trader = self.trader
        try:
            positions = trader.gateway.get_open_positions()
        except Exception:
            return

        for pos in positions:
            symbol = str(pos.get("symbol") or "")
            if symbol not in trader.contexts:
                continue
            ctx = trader.contexts[symbol]
            ticket   = int(pos.get("ticket") or 0)
            side     = str(pos.get("side") or "BUY")
            profit   = float(pos.get("profit") or 0.0)
            entry    = float(pos.get("entry") or 0.0)
            sl_now   = float(pos.get("sl") or 0.0)
            tp_now   = float(pos.get("tp") or 0.0)
            cfg      = self._cfg(symbol)
            trigger  = float(cfg.get("trigger_usd", TRAIL_TRIGGER_USD))

            if profit < trigger or not ticket or entry <= 0:
                continue

            # Get current market price
            try:
                snap = trader.gateway.symbol_snapshot(symbol)
                bid  = float(snap.get("bid") or 0.0)
                ask  = float(snap.get("ask") or 0.0)
            except Exception:
                continue
            if not bid:
                continue

            point = ctx.point_size or 0.00001
            lock_gap = max(point, float(cfg.get("lock_points", TRAIL_LOCK_POINTS)) * point)
            trail_gap = max(
                float(cfg.get("trail_points", TRAIL_MIN_POINTS)) * point,
                TRAIL_GAP_PCT * entry,
            )
            step_gap = max(point, float(cfg.get("step_points", TRAIL_STEP_POINTS)) * point)
            try:
                min_dist = max(float(trader.gateway._min_stop_dist(symbol)), point)
            except Exception:
                min_dist = max(5 * point, point)

            def send(new_sl: float, label: str) -> None:
                try:
                    result = trader.gateway.modify_demo_position_sl_tp(ticket, symbol, sl=new_sl, tp=tp_now)
                except Exception:
                    return
                if result.get("sent"):
                    self._last_fail.pop(ticket, None)
                    print(
                        f"   🛡️  {label} [{symbol}] #{ticket} {side:<4s} SL "
                        f"{sl_now:.5f} → {new_sl:.5f}  profit=${profit:.2f}"
                    )
                    return
                retcode = int(result.get("retcode") or 0)
                if retcode and self._last_fail.get(ticket) != retcode:
                    self._last_fail[ticket] = retcode
                    comment = ""
                    broker = result.get("result") or {}
                    if isinstance(broker, dict):
                        comment = str(broker.get("comment") or "")
                    print(f"   ⚠️  Trail rejected [{symbol}] #{ticket} retcode={retcode} {comment}")

            if side == "BUY":
                price_now = bid
                favorable_move = price_now - entry
                if favorable_move <= min_dist:
                    continue
                breakeven_lock = entry + min(lock_gap, max(point, favorable_move * 0.25))
                trailing_lock = price_now - max(trail_gap, min_dist)
                target_sl = max(breakeven_lock, trailing_lock)
                target_sl = min(target_sl, price_now - min_dist)
                new_sl = self._round_price(trader, symbol, target_sl)
                if new_sl > sl_now + step_gap and new_sl < price_now:
                    send(new_sl, "Protect/Trail")
            else:  # SELL
                price_now = ask
                favorable_move = entry - price_now
                if favorable_move <= min_dist:
                    continue
                breakeven_lock = entry - min(lock_gap, max(point, favorable_move * 0.25))
                trailing_lock = price_now + max(trail_gap, min_dist)
                target_sl = min(breakeven_lock, trailing_lock)
                target_sl = max(target_sl, price_now + min_dist)
                new_sl = self._round_price(trader, symbol, target_sl)
                if (sl_now == 0 or new_sl < sl_now - step_gap) and new_sl > price_now:
                    send(new_sl, "Protect/Trail")


# ──────────────────────────────────────────────────────────────────────────────
# AutoTrader
# ──────────────────────────────────────────────────────────────────────────────

class AutoTrader:
    def __init__(
        self,
        profile="scalping",
        symbol=MT5_SYMBOL,
        symbols: list[str] | None = None,
        poll_seconds=30,
        auto_live=False,
        max_open_positions=1,
        entry_cooldown_seconds=180,
        max_trades_per_cycle=1,
        once=False,
    ):
        self.profile = profile
        self.primary_symbol = symbol
        self.symbols = symbols or [symbol]
        self.poll_seconds = int(poll_seconds)
        self.requested_max_open_positions = max(1, int(max_open_positions))
        self.max_open_positions = self.requested_max_open_positions
        self.entry_cooldown_seconds = int(entry_cooldown_seconds)
        self.max_trades_per_cycle = max(1, int(max_trades_per_cycle))
        self.once = bool(once)
        self._last_execution_at: dict[str, float] = {}
        self._last_flip_attempt_at: dict[str, float] = {}
        self.auto_live = False
        self._scalers: dict[str, StandardScaler] = {}  # per-symbol scaler

        print(f"📂 Loading model: {MODEL_PATH}")
        self.model = tf.keras.models.load_model(MODEL_PATH, compile=False)
        self.scaler = joblib.load(SCALER_PATH)  # fallback scaler

        self.gateway = MT5Gateway()
        self.gateway.initialize()
        if len(self.symbols) == 1 and wants_all_symbols(self.symbols[0]):
            self.symbols = resolve_symbols("all", self.gateway.mt5)
            self.primary_symbol = self.symbols[0]

        self.account = self.gateway.account_snapshot()
        self.is_demo = self.gateway.is_demo_account(self.account)
        self.account_type = "DEMO" if self.is_demo else "LIVE"

        dynamic_max_positions = self._calculate_max_positions_from_margin()
        self.max_open_positions = max(1, min(self.requested_max_open_positions, dynamic_max_positions))

        self.paper_executor = PaperExecutor()
        self.demo_executor = DemoMT5Executor(gateway=self.gateway)
        self.live_executor = SafeMT5Executor(gateway=self.gateway, allow_live=False)

        self.log_file = LOG_DIR / "auto_trades.jsonl"
        self.memory_file = DATA_DIR / "auto_symbol_memory.json"
        self.symbol_memory = self._load_symbol_memory()
        self.contexts = self._build_symbol_contexts()

        self.stats = {
            "started": datetime.now(timezone.utc).isoformat(),
            "cycles": 0,
            "attempts": 0,
            "trades": 0,
            "flips": 0,
            "market_closed_skips": 0,
            "errors": 0,
            "account_type": self.account_type,
        }

        # ── TickTrigger: per-symbol 0.5s bar-close detection ─────────────────────
        # A shared event fires when any symbol gets a new bar.
        # The main loop waits on this event (≤0.5s) instead of sleeping 1s.
        self._any_new_bar   = threading.Event()
        self._tick_triggers: dict[str, Any] = {}
        if _TICK_TRIGGER_OK:
            def _bar_callback(bar_info: dict) -> None:
                if bar_info.get("is_new_bar"):
                    self._any_new_bar.set()

            for sym in self.contexts:
                try:
                    trig = _TickTrigger(
                        mt5_instance             = self.gateway.mt5,
                        symbol                   = sym,
                        on_new_bar               = _bar_callback,
                        poll_secs                = 0.5,
                        price_move_threshold_pts = 9999,  # new-bar only; disable mid-bar fire
                    )
                    trig.start()
                    self._tick_triggers[sym] = trig
                except Exception as _te:
                    print(f"   ⚠️  TickTrigger init failed for {sym}: {_te}")

        # Start trailing SL monitor thread
        self._trail_thread = TrailingSLThread(self)
        self._trail_thread.start()

        print("✅ Connected to MT5")
        print(f"   Account: {self.account.get('login')}")
        print(f"   Server: {self.account.get('server')}")
        print(f"   Balance: {self.account.get('balance')} {self.account.get('currency', 'USD')}")
        print(f"   Type: {self.account_type}")
        print(f"   Markets loaded: {', '.join(self.contexts)}")
        print(f"   Trailing SL: ${TRAIL_TRIGGER_USD:.2f} trigger | {TRAIL_CHECK_SECONDS:.0f}s monitor")
        if self._tick_triggers:
            print(f"   TickTrigger: 0.5s bar-close detection on {len(self._tick_triggers)} symbols")
        else:
            print(f"   TickTrigger: unavailable — 1s fallback polling")

    # ------------------------------------------------------------------
    # Setup and persistence
    # ------------------------------------------------------------------
    def _build_symbol_contexts(self) -> dict[str, SymbolContext]:
        contexts: dict[str, SymbolContext] = {}
        for symbol in self.symbols:
            try:
                snapshot = self.gateway.symbol_snapshot(symbol)
                if snapshot.get("error"):
                    self.log("symbol_unavailable", {"symbol": symbol, "snapshot": snapshot})
                    continue
                if int(snapshot.get("trade_mode") or 0) <= 0:
                    self.log("symbol_not_tradable", {"symbol": symbol, "snapshot": snapshot})
                    continue

                info = self.gateway.mt5.symbol_info(symbol)
                volume_min = float(getattr(info, "volume_min", 0.01) or 0.01)
                volume_step = float(getattr(info, "volume_step", 0.01) or 0.01)
                volume_max = float(getattr(info, "volume_max", MAX_LOT) or MAX_LOT)
                if volume_min > float(MAX_LOT):
                    self.log(
                        "symbol_skipped_lot_cap",
                        {
                            "symbol": symbol,
                            "volume_min": volume_min,
                            "max_lot": MAX_LOT,
                            "reason": "broker_min_volume_above_risk_cap",
                        },
                    )
                    continue

                point_size = float(snapshot.get("point") or 0.01)
                risk = SYMBOL_RISK.get(symbol, SYMBOL_RISK["_default"])
                journal_path = JOURNAL_DIR / f"trade_memory_{_safe_symbol_for_path(symbol)}.csv"
                journal = LearningJournal(path=journal_path)
                # الذهب والفضة: gold_precision (3 شروط SMC) للجودة العالية
                _sym_profile = (
                    "gold_precision" if any(x in symbol.upper() for x in ("XAU", "XAG"))
                    else self.profile
                )
                brain = TradingBrain(model=self.model, profile_name=_sym_profile, journal=journal)
                context = SymbolContext(
                    symbol=symbol,
                    brain=brain,
                    pivot=PivotEngine(self.gateway, symbol, point_size=point_size),
                    confidence=ConfidenceEngine(symbol),
                    journal=journal,
                    point_size=point_size,
                    volume_min=volume_min,
                    volume_step=volume_step,
                    volume_max=volume_max,
                    sl_pct=float(risk["sl_pct"]),
                    tp_pct=float(risk["tp_pct"]),
                )
                state = self._ensure_symbol_state(symbol, context)
                outcomes = state.get("outcomes") or {}
                context.consecutive_losses = int(outcomes.get("current_loss_streak") or 0)
                context.loss_cooldown_until = float(outcomes.get("loss_cooldown_until") or 0.0)
                contexts[symbol] = context
            except Exception as exc:
                self.log("symbol_context_error", {"symbol": symbol, "error": str(exc)})

        if not contexts:
            raise RuntimeError("No tradable symbols loaded from MT5")
        return contexts

    def _load_symbol_memory(self) -> dict:
        if self.memory_file.exists():
            try:
                return json.loads(self.memory_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"symbols": {}}

    def _save_symbol_memory(self) -> None:
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        self.memory_file.write_text(
            json.dumps(self.symbol_memory, indent=2, ensure_ascii=False, default=_json_default),
            encoding="utf-8",
        )

    def _calculate_max_positions_from_margin(self) -> int:
        balance = float(self.account.get("balance", 0))
        equity = float(self.account.get("equity", balance))
        margin = float(self.account.get("margin", 0))
        margin_free = float(self.account.get("margin_free", equity))

        available_margin = margin_free * 0.5
        estimated_margin_per_trade = balance * 0.10

        if estimated_margin_per_trade > 0:
            max_by_margin = int(available_margin / estimated_margin_per_trade)
        else:
            max_by_margin = 1

        max_positions = max(1, min(5, max_by_margin))

        print(f"   💰 Balance: ${balance:.2f} | Equity: ${equity:.2f}")
        print(f"   📊 Margin: ${margin:.2f} | Free: ${margin_free:.2f}")
        print(f"   🔢 Max positions (dynamic): {max_positions}")

        return max_positions

    def _ensure_symbol_state(self, symbol: str, context: SymbolContext | None = None) -> dict:
        symbols = self.symbol_memory.setdefault("symbols", {})
        state = symbols.setdefault(
            symbol,
            {
                "settings": {},
                "execution": {
                    "attempts": 0,
                    "sent": 0,
                    "rejected": 0,
                    "market_closed": 0,
                    "retcodes": {},
                    "reasons": {},
                },
                "outcomes": {
                    "closed": 0,
                    "wins": 0,
                    "losses": 0,
                    "total_points": 0.0,
                    "total_profit": 0.0,
                    "current_loss_streak": 0,
                    "loss_cooldown_until": 0.0,
                },
                "active_positions": {},
                "recent_events": [],
            },
        )
        outcomes = state.setdefault("outcomes", {})
        outcomes.setdefault("closed", 0)
        outcomes.setdefault("wins", 0)
        outcomes.setdefault("losses", 0)
        outcomes.setdefault("total_points", 0.0)
        outcomes.setdefault("total_profit", 0.0)
        outcomes.setdefault("current_loss_streak", 0)
        outcomes.setdefault("loss_cooldown_until", 0.0)
        if context is not None:
            state["settings"] = {
                "profile": self.profile,
                "point_size": context.point_size,
                "volume_min": context.volume_min,
                "volume_step": context.volume_step,
                "volume_max": context.volume_max,
                "sl_pct": context.sl_pct,
                "tp_pct": context.tp_pct,
                "max_open_positions": self.max_open_positions,
                "entry_cooldown_seconds": self.entry_cooldown_seconds,
            }
        return state

    def _append_recent_event(self, symbol: str, event: dict) -> None:
        state = self._ensure_symbol_state(symbol)
        recent = state.setdefault("recent_events", [])
        recent.append({"timestamp": datetime.now(timezone.utc).isoformat(), **event})
        del recent[:-MAX_RECENT_MEMORY_EVENTS]

    def log(self, event_type, data):
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            **data,
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=_json_default) + "\n")

    # ------------------------------------------------------------------
    # Market scan
    # ------------------------------------------------------------------
    def fetch_data(self, symbol, bars=500):
        return self.gateway.fetch_rates(symbol, "M1", bars)

    def _market_is_recent(self, symbol: str, df, context: SymbolContext) -> tuple[bool, str]:
        if df is None or len(df) == 0:
            return False, "no_m1_bars"
        last_time = df["time"].iloc[-1]
        try:
            last_ts = np.datetime64(last_time).astype("datetime64[s]").astype(datetime)
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            age_seconds = max(0.0, (now_utc - last_ts).total_seconds())
            context.last_bar_time = str(last_time)
            context.last_bar_age_seconds = age_seconds
            if age_seconds > MARKET_STALE_SECONDS:
                return False, f"stale_market_data:{int(age_seconds)}s"
        except Exception:
            return True, ""
        return True, ""

    def _is_temporarily_closed(self, context: SymbolContext) -> bool:
        return time.time() < float(context.closed_until or 0.0)

    def _loss_guard_reason(self, context: SymbolContext) -> str | None:
        if context.consecutive_losses < MAX_CONSECUTIVE_LOSSES:
            return None

        now = time.time()
        if not context.loss_cooldown_until:
            context.loss_cooldown_until = now + LOSS_COOLDOWN_SECONDS
            state = self._ensure_symbol_state(context.symbol, context)
            state["outcomes"]["loss_cooldown_until"] = context.loss_cooldown_until
            self._save_symbol_memory()

        if now < context.loss_cooldown_until:
            remaining = int(context.loss_cooldown_until - now)
            return f"loss_cooldown:{context.consecutive_losses}_losses:{remaining}s"

        # Cooldown has elapsed; allow a recovery trade, but keep one loss in
        # memory so the next loss pauses it again quickly.
        context.consecutive_losses = max(0, MAX_CONSECUTIVE_LOSSES - 1)
        context.loss_cooldown_until = 0.0
        state = self._ensure_symbol_state(context.symbol, context)
        state["outcomes"]["current_loss_streak"] = context.consecutive_losses
        state["outcomes"]["loss_cooldown_until"] = 0.0
        self._save_symbol_memory()
        return None

    def _symbol_performance(self, symbol: str) -> dict:
        state = self._ensure_symbol_state(symbol)
        outcomes = state.get("outcomes") or {}
        closed = int(outcomes.get("closed") or 0)
        wins = int(outcomes.get("wins") or 0)
        losses = int(outcomes.get("losses") or 0)
        total_profit = float(outcomes.get("total_profit") or 0.0)
        total_points = float(outcomes.get("total_points") or 0.0)
        win_rate = wins / closed if closed > 0 else 0.0
        avg_profit = total_profit / closed if closed > 0 else 0.0
        score = 0.0
        if closed >= SYMBOL_PERFORMANCE_MIN_TRADES:
            score = (
                (win_rate - 0.50) * 2.0
                + max(-1.0, min(1.0, avg_profit))
                + max(-1.0, min(1.0, total_profit / 50.0))
            )
        return {
            "closed": closed,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_profit": total_profit,
            "total_points": total_points,
            "avg_profit": avg_profit,
            "score": score,
        }

    def _performance_allows_trade(self, decision: dict) -> tuple[bool, str | None]:
        symbol = str(decision.get("symbol") or "")
        perf = self._symbol_performance(symbol)
        decision["symbol_performance"] = perf
        closed = perf["closed"]
        if closed < SYMBOL_PERFORMANCE_MIN_TRADES:
            return True, None

        confidence = float(decision.get("confidence") or 0.0)
        severe = (
            perf["total_profit"] <= SYMBOL_SEVERE_PROFIT_USD
            and perf["avg_profit"] <= SYMBOL_SEVERE_AVG_PROFIT_USD
        )
        weak = (
            perf["total_profit"] <= SYMBOL_WEAK_PROFIT_USD
            and perf["win_rate"] < SYMBOL_WEAK_WIN_RATE
        )

        if severe and SYMBOL_SEVERE_RECOVERY_ONLY:
            return (
                False,
                "performance_guard:severe_observation_only"
                f"(profit={perf['total_profit']:.2f},avg={perf['avg_profit']:.2f},"
                f"wr={perf['win_rate']:.1%})",
            )
        if severe and confidence < SYMBOL_SEVERE_MIN_CONFIDENCE:
            return (
                False,
                "performance_guard:severe"
                f"(profit={perf['total_profit']:.2f},avg={perf['avg_profit']:.2f},"
                f"wr={perf['win_rate']:.1%},conf={confidence:.2f})",
            )
        if weak and confidence < SYMBOL_WEAK_MIN_CONFIDENCE:
            return (
                False,
                "performance_guard:weak"
                f"(profit={perf['total_profit']:.2f},wr={perf['win_rate']:.1%},"
                f"conf={confidence:.2f})",
            )
        return True, None

    def _get_symbol_scaler(self, symbol: str, enriched) -> StandardScaler:
        """Fit a fresh per-symbol scaler on the current window."""
        scaler = self._scalers.get(symbol)
        if scaler is None:
            scaler = StandardScaler()
            data = enriched[FEATURE_COLUMNS].to_numpy(dtype=np.float32)
            scaler.fit(data)
            self._scalers[symbol] = scaler
        return scaler

    def analyze(self, context: SymbolContext) -> dict | None:
        """
        Returns a decision dict, or None if no new bar has closed.
        Applies:
          - Bar-close dedup (returns None on same bar)
          - Trend filter (BUY only when trend > 0, SELL only when trend < 0)
          - Consecutive-loss guard (HOLD if >= MAX_CONSECUTIVE_LOSSES)
        """
        symbol = context.symbol

        if self._is_temporarily_closed(context):
            remaining = int(context.closed_until - time.time())
            return {
                "action": "HOLD",
                "symbol": symbol,
                "close": 0.0,
                "probability": 0.5,
                "confidence": 0.0,
                "reason": f"market_closed_cooldown:{remaining}s",
                "market_open": False,
            }

        df = self.fetch_data(symbol)
        market_open, market_reason = self._market_is_recent(symbol, df, context)
        if not market_open:
            self.stats["market_closed_skips"] += 1
            self._append_recent_event(symbol, {"event": "market_skip", "reason": market_reason})
            return {
                "action": "HOLD",
                "symbol": symbol,
                "close": float(df["close"].iloc[-1]) if df is not None and len(df) else 0.0,
                "probability": 0.5,
                "confidence": 0.0,
                "reason": market_reason,
                "market_open": False,
            }

        # ── Bar-close dedup: skip if this bar was already analyzed ────────────
        bar_key = str(df["time"].iloc[-1])
        if bar_key == context.last_analyzed_bar:
            return None  # no new bar yet
        context.last_analyzed_bar = bar_key

        # ── Consecutive-loss guard ─────────────────────────────────────────────
        loss_guard = self._loss_guard_reason(context)
        if loss_guard:
            return {
                "action": "HOLD",
                "symbol": symbol,
                "close": float(df["close"].iloc[-1]),
                "probability": 0.5,
                "confidence": 0.0,
                "reason": loss_guard,
                "market_open": True,
            }

        enriched = add_market_structure(df)
        seq_raw = enriched[FEATURE_COLUMNS].tail(SEQ_LEN).to_numpy(dtype=np.float32)
        if len(seq_raw) < SEQ_LEN:
            return {
                "action": "HOLD",
                "symbol": symbol,
                "close": float(enriched["close"].iloc[-1]),
                "probability": 0.5,
                "confidence": 0.0,
                "reason": f"not_enough_bars:{len(seq_raw)}/{SEQ_LEN}",
                "market_open": True,
            }

        # Per-symbol scaler fitted on this window (handles BTC/EUR price ranges)
        scaler = self._get_symbol_scaler(symbol, enriched)
        seq = scaler.transform(seq_raw)
        sequence = seq.reshape(1, SEQ_LEN, len(FEATURE_COLUMNS))

        probability = float(np.asarray(self.model.predict(sequence, verbose=0)).squeeze())
        spread = float(enriched["spread"].iloc[-1]) if "spread" in enriched.columns else None

        decision = context.brain.decide(
            df=enriched,
            sequence=sequence,
            probability=probability,
            spread=spread,
            ignore_spread=(self.profile == "scalping" and AGGRESSIVE_SCALPING_IGNORE_SPREAD),
        ).to_dict()

        decision["close"] = float(enriched["close"].iloc[-1])
        decision["symbol"] = symbol
        decision["market_open"] = True
        decision["learning_memory"] = str(context.journal.path)
        decision["confidence_memory"] = context.confidence.status()

        # Extract trend/smc_bias for trend filter
        last = enriched.iloc[-1]
        trend     = float(last.get("trend", 0))
        smc_bias  = float(last.get("smc_bias", 0))
        decision["trend"]    = trend
        decision["smc_bias"] = smc_bias

        # ── Trend filter: veto against-trend entries ───────────────────────────
        action = decision.get("action", "HOLD")
        if action == "BUY" and trend < 0 and smc_bias < -0.3:
            decision["action"] = "HOLD"
            decision["reason"] = f"trend_filter:bearish(trend={trend:.2f},bias={smc_bias:.2f})"
        elif action == "SELL" and trend > 0 and smc_bias > 0.3:
            decision["action"] = "HOLD"
            decision["reason"] = f"trend_filter:bullish(trend={trend:.2f},bias={smc_bias:.2f})"

        pivot_result = context.pivot.apply(
            signal=decision.get("action", "HOLD"),
            confidence=float(decision.get("confidence", 0.0)),
            price=decision["close"],
        )
        decision["pivot"] = pivot_result
        decision["signal"] = decision.get("action", "HOLD")
        decision["confidence"] = pivot_result["confidence"]
        for key in (
            "pivot_reason",
            "nearest_pivot",
            "nearest_pivot_price",
            "pivot_zone",
            "recommended_order",
            "recommended_entry_price",
        ):
            decision[key] = pivot_result.get(key)

        if pivot_result.get("pivot_reason") not in {
            "no_pivot_boost",
            "no_existing_trade_signal",
            "pivot_levels_unavailable",
            "pivot_disabled",
        }:
            decision["reason"] = f"{decision.get('reason', '')}+{pivot_result['pivot_reason']}"

        # ── حفظ IndicatorSnapshot حين يكون الإعداد BUY/SELL ──────────────────
        if decision.get("action") in ("BUY", "SELL"):
            try:
                from mt5_ai.indicator_snapshot import IndicatorSnapshot, save_snapshot
                _last = enriched.iloc[-1]
                _price = float(enriched["close"].iloc[-1])
                _atr_raw = float(_last.get("atr", 1e-6) or 1e-6)
                _atr_abs = _atr_raw * _price if _price > 0 else _atr_raw
                _avg_atr = float(enriched["atr"].tail(20).mean() * _price) if "atr" in enriched.columns else _atr_abs
                _closes  = enriched["close"].values
                _atr_div = max(_atr_abs, 1e-9)
                _mom3  = float(_closes[-1] - _closes[-4])  / _atr_div if len(_closes) >= 4  else 0.0
                _mom10 = float(_closes[-1] - _closes[-11]) / _atr_div if len(_closes) >= 11 else 0.0
                _ef = float(enriched["close"].ewm(span=8,  adjust=False).mean().iloc[-1])
                _em = float(enriched["close"].ewm(span=13, adjust=False).mean().iloc[-1])
                _es = float(enriched["close"].ewm(span=21, adjust=False).mean().iloc[-1])

                snap = IndicatorSnapshot.build(
                    symbol       = symbol,
                    agent        = self.profile,
                    side         = decision["action"],
                    setup_reason = decision.get("reason", ""),
                    price        = _price,
                    spread       = float(spread or 0.0),
                    atr          = _atr_abs,
                    avg_atr      = _avg_atr,
                    rsi          = float(_last.get("rsi",  50.0)),
                    adx          = float(_last.get("adx",  20.0)),
                    ema_fast     = _ef,
                    ema_mid      = _em,
                    ema_slow     = _es,
                    trend_score  = float(_last.get("trend", 0.0)),
                    momentum_3   = _mom3,
                    momentum_10  = _mom10,
                    smc_ctx      = {c: float(_last.get(c, 0)) for c in (
                        "bos_up","bos_down","choch_up","choch_down",
                        "bullish_fvg","bearish_fvg","in_bullish_ob","in_bearish_ob",
                        "demand_zone","supply_zone","smc_buy_score","smc_sell_score",
                    )},
                    liquidity_ctx = {},
                    distance_to_ob = 999.0,
                )
                save_snapshot(snap)
            except Exception as _se:
                pass  # non-fatal

        return decision

    def _scan_markets(self) -> list[dict]:
        decisions: list[dict] = []
        for context in self.contexts.values():
            try:
                decision = self.analyze(context)
                if decision is None:
                    continue  # same bar, skip
                decisions.append(decision)
                self._print_decision(decision, context)
            except Exception as exc:
                self.stats["errors"] += 1
                error_decision = {
                    "action": "HOLD",
                    "symbol": context.symbol,
                    "close": 0.0,
                    "probability": 0.5,
                    "confidence": 0.0,
                    "reason": f"analysis_error:{exc}",
                    "market_open": False,
                }
                decisions.append(error_decision)
                self.log("analysis_error", {"symbol": context.symbol, "error": str(exc)})
                print(f"   ⚠️  {context.symbol}: {exc}")
        return decisions

    def _rank_trade_candidates(self, decisions: list[dict]) -> list[dict]:
        candidates: list[dict] = []
        for decision in decisions:
            symbol = str(decision.get("symbol") or "")
            context = self.contexts.get(symbol)
            if decision.get("action") not in {"BUY", "SELL"}:
                continue
            if not decision.get("market_open", True):
                continue
            if context is None:
                continue
            if context.consecutive_losses >= MAX_CONSECUTIVE_LOSSES and self._loss_guard_reason(context):
                continue
            allowed, reason = self._performance_allows_trade(decision)
            if not allowed:
                decision["action"] = "HOLD"
                decision["reason"] = reason or "performance_guard"
                self._append_recent_event(symbol, {"event": "performance_skip", "reason": decision["reason"]})
                continue
            candidates.append(decision)

        candidates.sort(
            key=lambda d: (
                float((d.get("symbol_performance") or {}).get("score") or 0.0),
                float(d.get("confidence") or 0.0),
                abs(float(d.get("probability") or 0.5) - 0.5),
                1 if d.get("symbol") == self.primary_symbol else 0,
            ),
            reverse=True,
        )
        return candidates

    # ------------------------------------------------------------------
    # Direction flip
    # ------------------------------------------------------------------
    def _flip_position(self, pos: dict, decision: dict, context: SymbolContext) -> None:
        """
        Close opposing position and open the new direction.
        MT5 netting mode: placing opposite lot auto-closes the existing position.
        """
        symbol = context.symbol
        new_side = decision["action"]
        old_side = pos["side"]
        ticket   = pos["ticket"]
        price    = float(decision["close"])
        lot      = self._normalize_lot_for_symbol(context, context.confidence.apply_lot(DEFAULT_LOT))
        now_ts   = time.time()

        last_attempt = self._last_flip_attempt_at.get(symbol, 0.0)
        if now_ts - last_attempt < self.entry_cooldown_seconds:
            return

        allowed, guard_reason = self._performance_allows_trade(decision)
        if not allowed:
            self._append_recent_event(symbol, {"event": "flip_skipped", "reason": guard_reason})
            print(f"   ⏸️  FLIP skipped [{symbol}] {guard_reason}")
            return

        self._last_flip_attempt_at[symbol] = now_ts

        print(
            f"   🔄 FLIP [{symbol}] #{ticket} {old_side}→{new_side} "
            f"@ {price:.5f}  prob={decision.get('probability', 0.5):.2%}"
        )

        # Place opposing order (nets against existing position in MT5 netting mode)
        if self.is_demo:
            sl = price * (1 - context.sl_pct) if new_side == "BUY" else price * (1 + context.sl_pct)
            tp = price * (1 + context.tp_pct) if new_side == "BUY" else price * (1 - context.tp_pct)
            result = self.demo_executor.execute(
                symbol=symbol, side=new_side, price=price, lot=lot, sl=sl, tp=tp
            )
            sent = bool(result.get("sent", False))
        else:
            result = {"sent": False, "reason": "live_account_flip_blocked"}
            sent = False

        self.stats["flips"] += 1
        self.log(
            "direction_flip",
            {
                "symbol": symbol,
                "old_side": old_side,
                "new_side": new_side,
                "ticket": ticket,
                "price": price,
                "lot": lot,
                "sent": sent,
                "prob": decision.get("probability"),
            },
        )
        if sent:
            self._last_execution_at[symbol] = now_ts
            print(f"   ✅ Flip sent: {symbol} {old_side}→{new_side}")
        else:
            reason = ""
            if isinstance(result, dict):
                reason = str(result.get("reason") or result.get("retcode") or "")
            print(f"   ❌ Flip failed: {symbol} {reason or 'unknown'}")

    # ------------------------------------------------------------------
    # Execution and memory
    # ------------------------------------------------------------------
    def execute(self, decision):
        action = decision.get("action")
        if action not in {"BUY", "SELL"}:
            return None

        symbol = decision.get("symbol", self.primary_symbol)
        context = self.contexts[symbol]
        side = action
        price = float(decision["close"])
        lot = self._normalize_lot_for_symbol(context, context.confidence.apply_lot(DEFAULT_LOT))

        open_positions = self.gateway.get_open_positions()
        symbol_positions = [p for p in open_positions if p.get("symbol") == symbol]
        if len(symbol_positions) >= self.max_open_positions:
            result = {
                "sent": False,
                "mode": "blocked",
                "reason": f"max_open_positions_reached:{len(symbol_positions)}/{self.max_open_positions}",
                "open_positions": symbol_positions,
            }
            wrapped = self._wrap_execution_result("BLOCKED", action, symbol, price, lot, result, decision)
            self._record_execution_result(wrapped)
            return wrapped

        now_ts = time.time()
        last_ts = self._last_execution_at.get(symbol, 0.0)
        if now_ts - last_ts < self.entry_cooldown_seconds:
            remaining = int(self.entry_cooldown_seconds - (now_ts - last_ts))
            result = {"sent": False, "mode": "blocked", "reason": f"entry_cooldown:{remaining}s"}
            wrapped = self._wrap_execution_result("BLOCKED", action, symbol, price, lot, result, decision)
            self._record_execution_result(wrapped)
            return wrapped

        if side == "BUY":
            sl = price * (1 - context.sl_pct)
            tp = price * (1 + context.tp_pct)
        else:
            sl = price * (1 + context.sl_pct)
            tp = price * (1 - context.tp_pct)

        if self.is_demo:
            result = self.demo_executor.execute(
                symbol=symbol, side=side, price=price, lot=lot, sl=sl, tp=tp
            )
            mode = "DEMO"
        else:
            result = self.paper_executor.execute(symbol=symbol, side=side, price=price, lot=lot, sl=sl, tp=tp)
            mode = "PAPER (LIVE account detected; broker execution blocked)"

        self.stats["attempts"] += 1
        if result.get("sent", False):
            self.stats["trades"] += 1
            self._last_execution_at[symbol] = now_ts

        wrapped = self._wrap_execution_result(mode, action, symbol, price, lot, result, decision)
        self._record_execution_result(wrapped)

        if self._is_market_closed_result(result):
            context.closed_until = time.time() + MARKET_CLOSED_RETRY_SECONDS
            self.stats["market_closed_skips"] += 1

        self.log("auto_trade", wrapped)
        return wrapped

    @staticmethod
    def _normalize_lot_for_symbol(context: SymbolContext, raw_lot: float) -> float:
        lot = max(float(raw_lot), float(context.volume_min))
        lot = min(lot, float(context.volume_max), float(MAX_LOT))
        step = float(context.volume_step) or 0.01
        lot = round(round(lot / step) * step, 4)
        return max(lot, float(context.volume_min))

    @staticmethod
    def _wrap_execution_result(mode, action, symbol, price, lot, result, decision) -> dict:
        return {
            "executed": bool(result.get("sent", False)),
            "mode": mode,
            "action": action,
            "symbol": symbol,
            "price": price,
            "lot": lot,
            "result": result,
            "decision": decision,
        }

    @staticmethod
    def _nested_broker_result(result: dict) -> dict:
        nested = result.get("result") if isinstance(result, dict) else None
        if isinstance(nested, dict) and isinstance(nested.get("result"), dict):
            return nested["result"]
        if isinstance(nested, dict):
            return nested
        return {}

    def _is_market_closed_result(self, result: dict) -> bool:
        broker = self._nested_broker_result(result)
        retcode = int(broker.get("retcode") or result.get("retcode") or 0)
        comment = str(broker.get("comment") or result.get("reason") or "").lower()
        return retcode in MARKET_CLOSED_RETCODES or "market closed" in comment

    def _failure_reason(self, wrapped: dict) -> str:
        result = wrapped.get("result") or {}
        broker = self._nested_broker_result(result)
        retcode = broker.get("retcode") or result.get("retcode")
        comment = broker.get("comment") or result.get("reason")
        if comment and retcode:
            return f"{comment} (retcode={retcode})"
        if comment:
            return str(comment)
        if retcode:
            return f"retcode={retcode}"
        return "unknown"

    def _record_execution_result(self, wrapped: dict) -> None:
        symbol = wrapped["symbol"]
        state = self._ensure_symbol_state(symbol, self.contexts.get(symbol))
        execution = state["execution"]
        execution["attempts"] += 1

        result = wrapped.get("result") or {}
        broker = self._nested_broker_result(result)
        retcode = str(broker.get("retcode") or result.get("retcode") or "none")
        reason = str(broker.get("comment") or result.get("reason") or "unknown")
        execution["retcodes"][retcode] = execution["retcodes"].get(retcode, 0) + 1
        execution["reasons"][reason] = execution["reasons"].get(reason, 0) + 1

        if wrapped.get("executed"):
            execution["sent"] += 1
            ticket = broker.get("order") or broker.get("deal")
            actual_entry = float(broker.get("price") or wrapped["price"])
            if ticket:
                state["active_positions"][str(ticket)] = {
                    "ticket": int(ticket),
                    "symbol": symbol,
                    "side": wrapped["action"],
                    "entry": actual_entry,
                    "signal_price": float(wrapped["price"]),
                    "lot": float(wrapped["lot"]),
                    "opened_at": datetime.now(timezone.utc).isoformat(),
                    "probability": float(wrapped["decision"].get("probability") or 0.5),
                    "smc_buy_score": float(wrapped["decision"].get("smc_buy_score") or 0.0),
                    "smc_sell_score": float(wrapped["decision"].get("smc_sell_score") or 0.0),
                    "reason": wrapped["decision"].get("reason", ""),
                }
            self._append_recent_event(symbol, {"event": "sent", "side": wrapped["action"], "price": actual_entry})
        else:
            execution["rejected"] += 1
            if self._is_market_closed_result(result):
                execution["market_closed"] += 1
            self._append_recent_event(symbol, {"event": "rejected", "reason": reason, "retcode": retcode})

        self._save_symbol_memory()

    def _update_closed_trade_memory(self) -> None:
        try:
            open_positions = self.gateway.get_open_positions()
        except Exception as exc:
            self.log("position_sync_error", {"error": str(exc)})
            return

        open_by_ticket = {str(p.get("ticket")): p for p in open_positions}
        open_tickets = set(open_by_ticket)
        changed = False

        for position in open_positions:
            symbol = str(position.get("symbol") or "")
            if symbol not in self.contexts:
                continue
            ticket = str(position.get("ticket"))
            state = self._ensure_symbol_state(symbol, self.contexts[symbol])
            active_positions = state.setdefault("active_positions", {})
            if ticket in active_positions:
                continue
            active_positions[ticket] = {
                "ticket": int(position.get("ticket")),
                "symbol": symbol,
                "side": str(position.get("side")),
                "entry": float(position.get("entry") or 0.0),
                "signal_price": float(position.get("entry") or 0.0),
                "lot": float(position.get("volume") or DEFAULT_LOT),
                "opened_at": datetime.now(timezone.utc).isoformat(),
                "probability": 0.5,
                "smc_buy_score": 0.0,
                "smc_sell_score": 0.0,
                "reason": "adopted_existing_position",
                "last_profit": float(position.get("profit") or 0.0),
            }
            self._append_recent_event(
                symbol,
                {
                    "event": "adopted_open_position",
                    "ticket": int(position.get("ticket")),
                    "side": str(position.get("side")),
                    "entry": float(position.get("entry") or 0.0),
                },
            )
            changed = True

        for symbol, context in self.contexts.items():
            state = self._ensure_symbol_state(symbol, context)
            active = dict(state.get("active_positions") or {})
            for ticket, trade in active.items():
                if ticket in open_tickets:
                    position = open_by_ticket[ticket]
                    trade["entry"] = float(position.get("entry") or trade.get("entry") or 0.0)
                    trade["last_profit"] = float(position.get("profit") or 0.0)
                    state["active_positions"][ticket] = trade
                    changed = True
                    continue
                close_info = self._find_closed_trade(symbol, trade)
                if close_info is None:
                    continue

                side = trade["side"]
                entry = float(trade["entry"])
                exit_price = float(close_info["exit_price"])
                points = exit_price - entry if side == "BUY" else entry - exit_price
                profit = float(close_info.get("profit") or 0.0)
                won = profit > 0 if abs(profit) > 1e-9 else points > 0

                context.journal.remember_trade(
                    strategy=self.profile,
                    side=side,
                    probability=float(trade.get("probability") or 0.5),
                    smc_buy_score=float(trade.get("smc_buy_score") or 0.0),
                    smc_sell_score=float(trade.get("smc_sell_score") or 0.0),
                    entry_price=entry,
                    exit_price=exit_price,
                    points=points,
                    signal_type=str(trade.get("reason") or "auto"),
                )
                # ── ربط نتيجة الصفقة بلقطة المؤشرات للتعلم ──────────────────
                try:
                    from mt5_ai.indicator_snapshot import update_snapshot_outcome
                    update_snapshot_outcome(symbol, side, entry, won, points)
                except Exception:
                    pass
                if won:
                    context.confidence.on_win(points)
                    context.consecutive_losses = 0  # reset on win
                    context.loss_cooldown_until = 0.0
                    state["outcomes"]["wins"] += 1
                else:
                    context.confidence.on_loss(points)
                    context.consecutive_losses += 1  # increment on loss
                    state["outcomes"]["losses"] += 1

                if context.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                    context.loss_cooldown_until = time.time() + LOSS_COOLDOWN_SECONDS
                    print(
                        f"   ⛔ [{symbol}] {context.consecutive_losses} consecutive losses — "
                        f"cooldown {int(LOSS_COOLDOWN_SECONDS / 60)}m"
                    )

                state["outcomes"]["closed"] += 1
                state["outcomes"]["total_points"] += points
                state["outcomes"]["total_profit"] += profit
                state["outcomes"]["current_loss_streak"] = context.consecutive_losses
                state["outcomes"]["loss_cooldown_until"] = context.loss_cooldown_until
                state["active_positions"].pop(ticket, None)
                self._append_recent_event(
                    symbol,
                    {
                        "event": "closed",
                        "side": side,
                        "entry": entry,
                        "exit": exit_price,
                        "points": round(points, 5),
                        "profit": round(profit, 2),
                        "won": won,
                        "consecutive_losses": context.consecutive_losses,
                    },
                )
                changed = True

        if changed:
            self._save_symbol_memory()

    def _find_closed_trade(self, symbol: str, trade: dict) -> dict | None:
        try:
            opened_at = datetime.fromisoformat(str(trade["opened_at"]))
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=timezone.utc)
            date_from = opened_at - timedelta(days=1)
            date_to = datetime.now(timezone.utc) + timedelta(minutes=1)
            deals = self.gateway.mt5.history_deals_get(date_from, date_to)
            if not deals:
                return None

            ticket = int(trade["ticket"])
            matched = []
            for deal in deals:
                data = deal._asdict()
                if data.get("symbol") != symbol:
                    continue
                if int(data.get("position_id") or 0) == ticket or int(data.get("order") or 0) == ticket:
                    matched.append(data)
            if not matched:
                return None

            exit_deals = [d for d in matched if int(d.get("entry") or 0) in {1, 3}]
            if not exit_deals:
                return None
            exit_deal = exit_deals[-1]
            return {
                "exit_price": float(exit_deal.get("price") or trade["entry"]),
                "profit": sum(float(d.get("profit") or 0.0) for d in exit_deals),
            }
        except Exception as exc:
            self.log("history_lookup_error", {"symbol": symbol, "ticket": trade.get("ticket"), "error": str(exc)})
            return None

    # ------------------------------------------------------------------
    # Console and loop
    # ------------------------------------------------------------------
    def _print_decision(self, decision: dict, context: SymbolContext) -> None:
        action = decision.get("action", "HOLD")
        symbol = decision.get("symbol", context.symbol)
        price = float(decision.get("close") or 0.0)
        prob = float(decision.get("probability") or 0.5)
        conf = float(decision.get("confidence") or 0.0)
        reason = decision.get("reason", "")
        trend = decision.get("trend", 0)
        cons_loss = context.consecutive_losses
        perf = decision.get("symbol_performance") or self._symbol_performance(symbol)
        perf_txt = ""
        if int(perf.get("closed") or 0) >= SYMBOL_PERFORMANCE_MIN_TRADES:
            perf_txt = (
                f" perf={float(perf.get('total_profit') or 0.0):+.2f}"
                f"/{float(perf.get('win_rate') or 0.0):.0%}"
            )
        age = context.last_bar_age_seconds
        age_txt = f" age={int(age)}s" if age is not None else ""
        loss_txt = f" 🔴losses={cons_loss}" if cons_loss > 0 else ""
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"{action:5s} {symbol:9s} @ {price:>10.5f} "
            f"prob={prob:.2%} conf={conf:.2f} trend={trend:.1f}"
            f"{age_txt}{loss_txt}{perf_txt} - {reason}"
        )
        rec = decision.get("recommended_order")
        entry = decision.get("recommended_entry_price")
        if rec and rec != "NONE":
            if entry is not None:
                print(f"   pivot_rec={rec}@{float(entry):.5f}")
            else:
                print(f"   pivot_rec={rec}")

    def run(self):
        print("\n🚀 Starting Auto Trader")
        print(f"   Primary symbol: {self.primary_symbol}")
        print(f"   Scan symbols: {', '.join(self.contexts)}")
        print(f"   Profile: {self.profile}")
        print(f"   Aggressive scalping ignore spread: {AGGRESSIVE_SCALPING_IGNORE_SPREAD if self.profile == 'scalping' else False}")
        print(f"   Bar-close detection: 1s polling")
        print(f"   Max open positions/symbol: {self.max_open_positions}")
        print(f"   Max trades/cycle: {self.max_trades_per_cycle}")
        print(f"   Entry cooldown/symbol: {self.entry_cooldown_seconds}s")
        print(f"   Account: {self.account_type}")
        print(f"   Trailing SL: fast protect (trigger=${TRAIL_TRIGGER_USD:.2f}, check={TRAIL_CHECK_SECONDS:.0f}s)")
        flip_status = (
            f"enabled prob<{FLIP_PROB_SELL_MAX} (BUY→SELL) | prob>{FLIP_PROB_BUY_MIN} (SELL→BUY)"
            if ENABLE_DIRECTION_FLIP else
            "disabled (hedging-safe; avoids opening opposite duplicate positions)"
        )
        print(f"   Direction flip: {flip_status}")
        print(f"   Consecutive-loss cooldown: {MAX_CONSECUTIVE_LOSSES} losses → {int(LOSS_COOLDOWN_SECONDS / 60)}m")
        print(f"   Performance guard: memory-ranked symbols, weak markets need conf≥{SYMBOL_WEAK_MIN_CONFIDENCE:.2f}")
        print("   Auto Live: DISABLED / BLOCKED")
        print("-" * 80)

        try:
            while True:
                self.stats["cycles"] += 1
                try:
                    self._update_closed_trade_memory()
                    decisions = self._scan_markets()

                    # ── Direction flip check ───────────────────────────────────
                    if ENABLE_DIRECTION_FLIP and decisions:
                        try:
                            all_positions = self.gateway.get_open_positions()
                        except Exception:
                            all_positions = []

                        for decision in decisions:
                            dsym = decision.get("symbol", "")
                            dact = decision.get("action")
                            if dact not in {"BUY", "SELL"} or dsym not in self.contexts:
                                continue
                            dprob = float(decision.get("probability") or 0.5)
                            ctx   = self.contexts[dsym]
                            try:
                                sym_positions = [
                                    p for p in all_positions
                                    if p.get("symbol") == dsym
                                ]
                            except Exception:
                                sym_positions = []

                            for pos in sym_positions:
                                pos_side = pos.get("side", "").upper()
                                should_flip = (
                                    pos_side == "BUY"  and dprob <= FLIP_PROB_SELL_MAX
                                    or pos_side == "SELL" and dprob >= FLIP_PROB_BUY_MIN
                                )
                                if should_flip:
                                    self._flip_position(pos, decision, ctx)

                    # ── Main execution loop ────────────────────────────────────
                    trades_this_cycle = 0
                    for decision in decisions:
                        if trades_this_cycle >= self.max_trades_per_cycle:
                            break
                        sym    = decision.get("symbol", self.primary_symbol)
                        action = decision.get("action")
                        if action not in {"BUY", "SELL"}:
                            ctx = self.contexts.get(sym)
                            if ctx:
                                self._print_decision(decision, ctx)
                            continue
                        ctx = self.contexts.get(sym)
                        if ctx is None:
                            continue
                        allowed, guard_reason = self._performance_allows_trade(decision)
                        if not allowed:
                            print(f"   ⏸️  [{sym}] performance guard: {guard_reason}")
                            continue
                        self._print_decision(decision, ctx)
                        wrapped = self.execute(decision)
                        if wrapped and wrapped.get("sent"):
                            trades_this_cycle += 1
                            print(f"   ✅ Executed: {wrapped.get('mode','?')} {action} {sym}")
                        elif wrapped:
                            reason = self._failure_reason(wrapped)
                            if reason:
                                print(f"   ❌ [{sym}] {reason}")

                except Exception as inner_exc:
                    print(f"[Cycle Error] {inner_exc}")

                # ── status summary every 60 cycles ────────────────────────────
                if self.stats["cycles"] % 60 == 0:
                    print(
                        f"\n── Cycle {self.stats['cycles']} ──  "
                        f"attempts={self.stats['attempts']}  "
                        f"flips={self.stats['flips']}  "
                    )

                time.sleep(self.poll_seconds)

        except KeyboardInterrupt:
            print("\n[Auto Trader] Stopped by user.")
        finally:
            try:
                self.gateway.shutdown()
            except Exception:
                pass


def main():
    import argparse
    parser = argparse.ArgumentParser(description="FRIDAY Auto Trader")
    parser.add_argument("--symbol",   default=MT5_SYMBOL)
    parser.add_argument("--symbols",  default="all")
    parser.add_argument("--profile",  default="scalping")
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--max-open", type=int, default=1)
    parser.add_argument("--entry-cooldown", type=int, default=180)
    parser.add_argument("--max-trades-per-cycle", type=int, default=1)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    trader = AutoTrader(
        profile              = args.profile,
        symbol               = args.symbol,
        symbols              = _parse_symbols(args.symbol, args.symbols),
        poll_seconds         = args.poll_seconds,
        max_open_positions   = args.max_open,
        entry_cooldown_seconds = args.entry_cooldown,
        max_trades_per_cycle = args.max_trades_per_cycle,
        once                 = args.once,
    )
    trader.run()


if __name__ == "__main__":
    main()

"""
algory_runner.py
----------------
Main autonomous runtime for the Algory-FRIDAY integrated system.

What it does every cycle:
  1. Fetch latest bars from MT5 for each (symbol, timeframe) pair
  2. Run AlgoryIntegrator.on_tick() → signal + trade decision
  3. Execute via FRIDAY's paper/demo/live executor
  4. Check if active genome needs replacement (stale / failing purge)
  5. Spawn background campaigns when needed (non-blocking)

Run:  python -m mt5_ai.algory_runner
Or:   from mt5_ai.algory_runner import AlgoryRunner; AlgoryRunner().start()
"""

from __future__ import annotations

import concurrent.futures
import logging
import multiprocessing
import os
import signal
import sys

multiprocessing.freeze_support()   # required for Windows ProcessPoolExecutor
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .core.project_root import APPDATA_FRIDAY as _APPDATA_FRIDAY
_LOG_FILE   = _APPDATA_FRIDAY / "algory_runner.log"
_STATE_FILE = _APPDATA_FRIDAY / "algory_runner_state.json"
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
_fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
                         datefmt="%Y-%m-%d %H:%M:%S")
_fh  = logging.FileHandler(_LOG_FILE, encoding="utf-8")
_fh.setFormatter(_fmt)
_sh  = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_fh, _sh])
log = logging.getLogger("algory_runner")

# ─────────────────────────────────────────────────────────────────────────────
#  Default instruments (matches Algory dashboard_settings.json)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_SYMBOLS: list[str] = [
    "EURUSDm", "GBPUSDm", "USDJPYm",
    "AUDUSDm", "USDCADm", "NZDUSDm",
    "USDCHFm", "XAUUSDm",
]

DEFAULT_TIMEFRAMES: list[str] = ["M1", "M5", "M15", "M30", "H1", "H4"]

# How often each TF's bar closes in seconds (used to decide tick frequency)
TF_SECONDS: dict[str, int] = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H2": 7200, "H4": 14400, "D1": 86400,
}

# Route all MT5 execution through ExecutionManager (kill_switch + DRY_RUN safe)
from mt5_ai.core.execution_manager import get_execution_manager as _get_em
from mt5_ai.core.magic_registry import ALGORY_MAGIC   # single source of truth
GENOME_SCORE_FLOOR       = 3.0   # replace genome if modern_score drops below this
GENOME_MIN_TRADES        = 20    # must have at least this many live trades before evaluating
CAMPAIGN_COOLDOWN        = 3600  # seconds between campaigns for same (symbol, tf)
POST_TRADE_COOLDOWN_BARS = 2     # bars to skip after every FILLED trade close
MAX_COOLDOWN_SECONDS     = 1800  # hard cap: never wait more than 30 min regardless of TF


def _wants_all_symbols(values: list[str] | None) -> bool:
    if not values:
        return False
    return len(values) == 1 and values[0].strip().lower() in {"all", "auto", "*"}


def _resolve_cli_symbols(values: list[str] | None) -> list[str] | None:
    if not _wants_all_symbols(values):
        return values or None

    try:
        import MetaTrader5 as mt5
        from mt5_ai.friday_symbol_universe import resolve_symbols

        mt5.initialize()
        symbols = resolve_symbols(
            "all",
            mt5,
            visible_only=os.getenv("FRIDAY_SYMBOLS_VISIBLE_ONLY", "0").strip().lower()
            in {"1", "true", "yes", "on"},
            tradable_only=True,
            select=True,
        )
        if symbols:
            log.info("Resolved --symbols all to %d MT5 symbols.", len(symbols))
            return symbols
    except Exception as exc:
        log.warning("Could not resolve --symbols all from MT5: %s", exc)

    log.warning("Falling back to DEFAULT_SYMBOLS for AlgoryRunner.")
    return list(DEFAULT_SYMBOLS)


# ─────────────────────────────────────────────────────────────────────────────
#  MT5 data helper
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_bars(symbol: str, timeframe: str, n: int = 500) -> pd.DataFrame | None:
    try:
        import MetaTrader5 as mt5
        TF_MAP = {
            "M1": mt5.TIMEFRAME_M1,  "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,  "H2": mt5.TIMEFRAME_H2,
            "H4": mt5.TIMEFRAME_H4,  "D1": mt5.TIMEFRAME_D1,
        }
        tf = TF_MAP.get(timeframe)
        if tf is None:
            return None
        mt5.initialize()  # safe to call multiple times
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        return df.set_index("time")[["open", "high", "low", "close", "volume"]].copy()
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  Runner
# ─────────────────────────────────────────────────────────────────────────────

class AlgoryRunner:
    def __init__(
        self,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
        paper_mode: bool = True,
        tick_interval: float = 5.0,
    ) -> None:
        self.symbols    = symbols    or DEFAULT_SYMBOLS
        self.timeframes = timeframes or DEFAULT_TIMEFRAMES
        self.paper_mode = paper_mode
        self.tick_interval = tick_interval
        self._running   = False
        self._campaign_last: dict[tuple[str, str], float] = {}
        self._campaign_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        # Track last bar timestamp we acted on — prevents re-entry on same candle
        self._last_signal_bar: dict[tuple[str, str], Any] = {}
        # Track open paper positions — key=(symbol,tf), value=trade dict
        self._open_positions: dict[tuple[str, str], dict] = {}
        # Post-trade cooldown: after close, block next N bar timestamps
        self._cooldown_until: dict[tuple[str, str], Any] = {}

        from .algory_integrator import get_integrator
        self.integrator = get_integrator(paper_mode=paper_mode)

        from .execution import PaperExecutor
        self.executor = PaperExecutor()

        try:
            import MetaTrader5 as mt5
            if not mt5.initialize():
                log.warning("MT5 initialize() failed — running in offline/paper mode")
            else:
                info = mt5.account_info()
                self._balance = info.balance if info else 100_000.0
                log.info("MT5 connected | balance=%.2f", self._balance)
        except Exception:
            self._balance = 100_000.0
            log.warning("MT5 not available — balance=%.2f (simulated)", self._balance)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        signal.signal(signal.SIGINT,  self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)

        log.info("AlgoryRunner started | symbols=%s | TFs=%s | paper=%s",
                 self.symbols, self.timeframes, self.paper_mode)

        # Boot step 1: load Algory's validated strategies immediately (no wait)
        from .algory_loader import bootstrap_from_algory_vault
        n = bootstrap_from_algory_vault(self.integrator)
        if n:
            log.info("Bootstrap: %d Algory genome(s) ready — trading starts now", n)

        # Boot step 2: activate quick broad-signal genomes for uncovered pairs
        from .algory_quick_genome import activate_quick_genomes
        nq = activate_quick_genomes(self.integrator, self.symbols, self.timeframes)
        if nq:
            log.info("Quick genomes: %d pairs now covered (RSI+MACD+Stoch+Wick+ADX)", nq)

        # Boot step 3: launch background campaigns for all pairs (evolve better genomes)
        self._boot_campaigns()

        while self._running:
            try:
                t_start = time.monotonic()
                self._tick_all()
                elapsed = time.monotonic() - t_start
                sleep_t = max(0.1, self.tick_interval - elapsed)
                time.sleep(sleep_t)
            except Exception as exc:
                log.exception("CRITICAL loop error — continuing: %s", exc)
                time.sleep(5)

    def stop(self) -> None:
        self._running = False
        self._campaign_pool.shutdown(wait=False)
        self.integrator.save_registry()
        log.info("AlgoryRunner stopped.")

    def _handle_stop(self, *_: Any) -> None:
        log.info("Shutdown signal received.")
        self.stop()

    # ── Boot: launch initial campaigns ───────────────────────────────────────

    def _boot_campaigns(self) -> None:
        for sym in self.symbols:
            for tf in self.timeframes:
                active = self.integrator.registry.get(sym, tf)
                if active is None:
                    self._launch_campaign(sym, tf)

    def _launch_campaign(self, symbol: str, timeframe: str) -> None:
        key = (symbol, timeframe)
        now = time.monotonic()
        if now - self._campaign_last.get(key, 0) < CAMPAIGN_COOLDOWN:
            return
        self._campaign_last[key] = now
        log.info("Launching background campaign for %s %s", symbol, timeframe)
        self._campaign_pool.submit(self._run_campaign_subprocess, symbol, timeframe)

    def _run_campaign_subprocess(self, symbol: str, timeframe: str) -> None:
        try:
            self.integrator.run_campaign_and_activate(symbol, timeframe)
        except Exception as e:
            log.error("Campaign failed %s %s: %s", symbol, timeframe, e)

    # ── Per-tick ──────────────────────────────────────────────────────────────

    def _tick_all(self) -> None:
        now = datetime.now(timezone.utc)
        if not hasattr(self, "_heartbeat_t"):
            self._heartbeat_t = 0.0
            self._tick_n = 0
        self._tick_n += 1
        if time.monotonic() - self._heartbeat_t >= 60:
            self._heartbeat_t = time.monotonic()
            log.info("Heartbeat tick=%d | %d genomes active | %d open",
                     self._tick_n, len(self.integrator.registry.all()),
                     len(self._open_positions))
        for sym in self.symbols:
            for tf in self.timeframes:
                self._tick_one(sym, tf, now)
        self._write_state()

    def _tick_one(self, symbol: str, timeframe: str, now: datetime) -> None:
        active = self.integrator.registry.get(symbol, timeframe)
        if active is None:
            return

        # Check if genome has degraded below floor
        # Only evaluate genomes that have accumulated a live equity curve
        g = active.genome
        if (len(g.equity_curve) >= GENOME_MIN_TRADES
                and g.modern_score() < GENOME_SCORE_FLOOR):
            log.warning("Genome %s on %s %s degraded (score=%.2f) — relaunching campaign",
                        g.id, symbol, timeframe, g.modern_score())
            self.integrator.registry.deactivate(symbol, timeframe)
            self._launch_campaign(symbol, timeframe)
            return

        df = _fetch_bars(symbol, timeframe, n=500)
        if df is None:
            log.warning("No bars: %s %s", symbol, timeframe)
            return

        # ── Bar deduplication: only act once per closed candle ────────────────
        current_bar_time = df.index[-1]
        key = (symbol, timeframe)
        if self._last_signal_bar.get(key) == current_bar_time:
            # Same candle as last tick — check open position management only
            self._manage_open_position(key, df)
            return

        # ── Post-trade cooldown: skip N bars after close ───────────────────────
        cooldown_until = self._cooldown_until.get(key, 0.0)
        if time.monotonic() < cooldown_until:
            self._last_signal_bar[key] = current_bar_time
            return

        trade = self.integrator.on_tick(symbol, timeframe, df,
                                        account_balance=self._balance, now=now)

        if trade.get("action") in ("BUY", "SELL"):
            self._last_signal_bar[key] = current_bar_time
            self._open_positions[key] = trade
            self._execute(trade)
        elif trade.get("action") == "HOLD":
            reason = trade.get("reason", "")
            if reason not in ("no_signal", "same_bar", ""):
                log.info("HOLD %s %s | %s", symbol, timeframe, reason)
            self._last_signal_bar[key] = current_bar_time

    # ── Pending order & position lifecycle ───────────────────────────────────

    def _cleanup_and_learn(self, symbol: str, timeframe: str) -> None:
        """
        Called every tick:
          1. Cancel stale FRIDAY pending orders (expired by bar count)
          2. Detect closed positions → record genome learning
          3. Remove stale state from _open_positions
        """
        key = (symbol, timeframe)
        try:
            import MetaTrader5 as mt5
            tag = "FRIDAY|"

            # ── Cancel expired pending orders ─────────────────────────────────
            orders = mt5.orders_get(symbol=symbol) or []
            now_ts = time.time()
            tf_secs = TF_SECONDS.get(timeframe, 3600)

            active_genome = self.integrator.registry.get(symbol, timeframe)
            gid_for_expire = ""
            if key in self._open_positions:
                gid_for_expire = self._open_positions[key].get("genome_id", "")

            for o in orders:
                # Only manage orders placed by THIS genome on THIS timeframe
                if not (o.comment and gid_for_expire and gid_for_expire in o.comment):
                    continue
                age_bars = (now_ts - o.time_setup) / tf_secs
                expiry = 15
                if active_genome:
                    g = active_genome.genome
                    if g.exec_stop:
                        expiry = g.stop_expiry_bars
                    elif g.exec_limit or g.exec_limit2:
                        expiry = g.limit_expiry_bars

                if age_bars >= expiry:
                    r = _get_em().cancel_pending_order(o.ticket, ALGORY_MAGIC, "expire")
                    if r.success:
                        log.info("[%s %s] Pending expired ticket=%d (%.1f bars) — no trade recorded",
                                 symbol, timeframe, o.ticket, age_bars)
                        # Expired unfilled → clear position state but keep bar-lock
                        # _last_signal_bar stays so we don't re-enter on the SAME bar
                        self._open_positions.pop(key, None)

            # ── Detect closed positions → learn ──────────────────────────────
            if key not in self._open_positions:
                return
            entry_trade = self._open_positions[key]
            gid = entry_trade.get("genome_id", "")

            # Still open as a position?
            positions = mt5.positions_get(symbol=symbol) or []
            still_open = any(p.comment and gid in p.comment for p in positions)
            if still_open:
                return

            # Still open as a pending order?
            pending = mt5.orders_get(symbol=symbol) or []
            still_pending = any(o.comment and gid in o.comment for o in pending)
            if still_pending:
                return

            # Gone — check if it was actually filled (has deal history)
            from_ts = int(entry_trade.get("_ts", now_ts - 86400))
            history = mt5.history_deals_get(from_ts, int(now_ts) + 60, group=f"*{symbol}*") or []
            filled_deals = [d for d in history if d.comment and gid in d.comment]

            if not filled_deals:
                # Pending was cancelled without being filled — not a real trade
                # Keep _last_signal_bar to prevent re-entry on the same bar
                log.info("[%s %s] Pending cancelled/unfilled genome=%s — waiting for next bar",
                         symbol, timeframe, gid[:8])
                self._open_positions.pop(key, None)
                return

            pnl = sum(d.profit for d in filled_deals)
            won = pnl > 0

            log.info("[%s %s] Trade closed | genome=%s | pnl=%.2f | %s",
                     symbol, timeframe, gid[:8], pnl, "WIN" if won else "LOSS")

            # Record to gene fitness DB (only real filled trades)
            active = self.integrator.registry.get(symbol, timeframe)
            if active:
                self.integrator.fitness_db.record_genome_result(
                    active.genome, won=won, oos_passed=False,
                    symbol=symbol, timeframe=timeframe,
                )

            # Cooldown — capped at MAX_COOLDOWN_SECONDS (30 min) regardless of TF
            self._open_positions.pop(key, None)
            tf_secs   = TF_SECONDS.get(timeframe, 300)
            raw_cd    = POST_TRADE_COOLDOWN_BARS * tf_secs
            cooldown  = min(raw_cd, MAX_COOLDOWN_SECONDS)
            self._cooldown_until[key] = time.monotonic() + cooldown
            log.info("[%s %s] Cooldown %ds (capped from %ds)",
                     symbol, timeframe, cooldown, raw_cd)

        except Exception as e:
            log.debug("cleanup_and_learn error: %s", e)

    def _manage_open_position(self, key: tuple, df: Any) -> None:
        """Called on repeat ticks of same candle."""
        self._cleanup_and_learn(key[0], key[1])

    def _execute(self, trade: dict) -> None:
        action = trade["action"]
        sym    = trade["symbol"]
        tf     = trade.get("timeframe", "")
        gid    = trade.get("genome_id", "")
        entry  = trade.get("entry", 0.0)

        # First: cleanup any stale orders/positions
        self._cleanup_and_learn(sym, tf)

        key = (sym, tf)
        try:
            if self.paper_mode:
                self.executor.execute(
                    symbol = sym,
                    side   = "BUY" if action == "BUY" else "SELL",
                    price  = entry,
                    lot    = trade["lot"],
                    sl     = trade["sl"],
                    tp     = trade["tp"],
                )
                log.info("[PAPER] %s %s %.2f lots  entry=%.5f  SL=%.5f  TP=%.5f  RR=%.1f  genome=%s",
                         action, sym, trade["lot"],
                         entry, trade["sl"], trade["tp"],
                         trade.get("rr", 0), gid)
                self._open_positions[key] = {**trade, "_ts": time.time()}

            else:
                import MetaTrader5 as mt5

                # Guard: skip if position already open for this genome
                existing = mt5.positions_get(symbol=sym) or []
                if any(p.comment and gid in p.comment for p in existing):
                    log.info("[LIVE] Skip %s %s — already open (genome=%s)", action, sym, gid)
                    return

                # Guard: cancel only THIS genome's existing pending orders (not other TF genomes)
                old_orders = mt5.orders_get(symbol=sym) or []
                for o in old_orders:
                    if o.comment and gid in o.comment:
                        _get_em().cancel_pending_order(o.ticket, ALGORY_MAGIC, "replace_pending")
                        log.info("[LIVE] Cancelled same-genome pending ticket=%d before new entry", o.ticket)

                # Determine order type from genome exec_mode
                active = self.integrator.registry.get(sym, tf)
                g = active.genome if active else None

                is_buy = (action == "BUY")
                current_price = mt5.symbol_info_tick(sym)
                ask = current_price.ask if current_price else entry
                bid = current_price.bid if current_price else entry

                if g and (g.exec_stop):
                    # Stop order: enters when price moves THROUGH entry_px
                    order_type = mt5.ORDER_TYPE_BUY_STOP if is_buy else mt5.ORDER_TYPE_SELL_STOP
                    price      = entry
                    action_mt5 = mt5.TRADE_ACTION_PENDING
                elif g and (g.exec_limit or g.exec_limit2):
                    # Limit order: enters when price RETRACES to entry_px
                    order_type = mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT
                    price      = entry
                    action_mt5 = mt5.TRADE_ACTION_PENDING
                else:
                    # Market2 / fallback: market order at current price
                    order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                    price      = ask if is_buy else bid
                    action_mt5 = mt5.TRADE_ACTION_DEAL

                req = {
                    "action":       action_mt5,
                    "symbol":       sym,
                    "volume":       trade["lot"],
                    "type":         order_type,
                    "price":        round(price, 5),
                    "sl":           trade["sl"],
                    "tp":           trade["tp"],
                    "magic":        ALGORY_MAGIC,
                    "comment":      f"FRIDAY|{gid}",
                    # PENDING orders must use RETURN (stays alive until filled/cancelled)
                    # Market orders use IOC or FOK depending on broker
                    "type_filling": mt5.ORDER_FILLING_RETURN if action_mt5 == mt5.TRADE_ACTION_PENDING else mt5.ORDER_FILLING_IOC,
                    "deviation":    20,
                }
                result = _get_em().send_raw_order(req, ALGORY_MAGIC)
                if result.success:
                    order_kind = "PENDING" if action_mt5 == mt5.TRADE_ACTION_PENDING else "MARKET"
                    log.info("[LIVE %s] %s %s %.2f  entry=%.5f  SL=%.5f  TP=%.5f  ticket=%d  genome=%s simulated=%s",
                             order_kind, action, sym, trade["lot"],
                             price, trade["sl"], trade["tp"], result.order, gid, result.simulated)
                    self._open_positions[key] = {**trade, "_ts": time.time()}
                else:
                    log.error("[LIVE] Order FAILED %s %s: %s",
                              action, sym, result.message)
                    self._last_signal_bar.pop(key, None)

        except Exception as e:
            log.exception("Execution error: %s", e)

    # ── Status ────────────────────────────────────────────────────────────────

    def _write_state(self) -> None:
        """Write compact runner state to JSON — read by algory_chart_dashboard."""
        try:
            import json as _json
            state: dict = {}
            for sym in self.symbols:
                for tf in self.timeframes:
                    key = (sym, tf)
                    key_str = f"{sym}|{tf}"
                    open_pos = self._open_positions.get(key)
                    cooldown_left = max(0.0, self._cooldown_until.get(key, 0.0) - time.monotonic())
                    active = self.integrator.registry.get(sym, tf)
                    state[key_str] = {
                        "action":        open_pos.get("action", "HOLD") if open_pos else "HOLD",
                        "entry":         open_pos.get("entry",  0.0)    if open_pos else 0.0,
                        "sl":            open_pos.get("sl",     0.0)    if open_pos else 0.0,
                        "tp":            open_pos.get("tp",     0.0)    if open_pos else 0.0,
                        "lot":           open_pos.get("lot",    0.0)    if open_pos else 0.0,
                        "rr":            open_pos.get("rr",     0.0)    if open_pos else 0.0,
                        "confidence":    open_pos.get("confidence", 0.0) if open_pos else 0.0,
                        "genome_id":     (open_pos.get("genome_id","") if open_pos
                                          else (active.genome.id[:8] if active else "")),
                        "in_trade":      open_pos is not None,
                        "cooldown_left": round(cooldown_left),
                        "last_signal":   active.last_signal if active else 0,
                        "tick_count":    active.tick_count  if active else 0,
                        "ts":            datetime.now(timezone.utc).isoformat(),
                    }
            _STATE_FILE.write_text(_json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass

    def print_status(self) -> None:
        rows = self.integrator.status()
        print(f"\n{'Symbol':<12} {'TF':<6} {'Score':>8} {'Trades':>7} "
              f"{'WR%':>7} {'Ret%':>7} {'DD%':>6} {'Purge'}")
        print("-" * 70)
        for r in rows:
            print(f"{r['symbol']:<12} {r['timeframe']:<6} {r['modern_score']:>8.2f} "
                  f"{r['trades']:>7} {r['win_rate']*100:>6.1f}% "
                  f"{r['return_pct']:>6.1f}% {r['max_dd_pct']:>5.1f}% "
                  f"{'OK' if r['passes_purge'] else r['purge_reason']}")
        print()


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Algory-FRIDAY integrated runner")
    parser.add_argument("--live",      action="store_true", help="Deprecated safety flag. Ignored unless FRIDAY_ENABLE_ALGORY_LIVE_DEMO=1.")
    parser.add_argument("--symbols",   nargs="*",           help="Symbols to trade")
    parser.add_argument("--timeframes",nargs="*",           help="Timeframes to trade")
    parser.add_argument("--interval",  type=float, default=5.0, help="Tick interval seconds")
    args = parser.parse_args()

    live_demo_enabled = (
        args.live
        and os.getenv("FRIDAY_ENABLE_ALGORY_LIVE_DEMO", "0").strip().lower() in {"1", "true", "yes", "on"}
    )
    if args.live and not live_demo_enabled:
        log.warning("--live requested but blocked; running AlgoryRunner in PAPER mode. Qader owns DEMO execution.")

    runner = AlgoryRunner(
        symbols    = _resolve_cli_symbols(args.symbols),
        timeframes = args.timeframes or None,
        paper_mode = not live_demo_enabled,
        tick_interval = args.interval,
    )
    runner.start()

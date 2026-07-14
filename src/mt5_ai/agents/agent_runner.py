"""
AgentRunner — runs AgentCoordinator in a background thread.

AUTO-STARTS on construction — no user command needed.
Scans ALL available markets (not just one symbol) when MT5 is connected,
otherwise uses the CSV pipeline for the configured symbol.

Publishes SSE events: agent_trade_open, agent_trade_close,
                      agent_learning_update, agent_sl_update.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from ..config import MT5_SYMBOL
from ..execution import PaperExecutor
from .coordinator import AgentCoordinator
from ..mt5_live_feed import MT5LiveFeed
from ..market_structure import add_market_structure, latest_smc_snapshot
from ..tick_trigger import TickTrigger


log = logging.getLogger("friday.agent_runner")

_BAR_SECONDS        = 1    # main loop every second
_LEARNING_EVERY     = 10   # SSE learning snapshot every N ticks
_SCAN_EVERY         = 15   # multi-symbol scan every N ticks (15s)
_SCAN_WORKERS       = 12   # parallel threads for scanning
_SCAN_BARS          = 100  # bars per symbol (fast)
_MAX_SCAN_SYMBOLS   = 40   # cap to avoid overload


class AgentRunner:
    def __init__(
        self,
        executor=None,
        symbol: str = MT5_SYMBOL,
        event_bus=None,
        bar_seconds: int = _BAR_SECONDS,
        market_state_fn=None,
        assistant=None,       # JarvisAssistant — used to pull real market state
        auto_start: bool = True,
    ):
        self._executor        = executor or PaperExecutor()
        self._symbol          = symbol
        self._event_bus       = event_bus
        self._bar_seconds     = bar_seconds
        self._assistant       = assistant
        self._market_state_fn = market_state_fn or self._build_market_state

        # Try to connect a live MT5 feed; fall back to assistant/dummy
        self._live_feed: MT5LiveFeed | None = None
        self._init_live_feed()

        self.coordinator = AgentCoordinator(
            executor=self._executor,
            symbol=self._symbol,
            event_bus=self._event_bus,
        )

        self.running    = False
        self._thread    = None
        self._lock      = threading.Lock()
        self._bar_count = 0
        self.last_error = None
        self._symbols_scanned: list[str] = []
        self._data_source   = "dummy"
        self._state_cache: dict | None = None
        self._state_cache_ts: float    = 0.0
        self._last_scan_result: dict   = {"markets": []}

        # TickTrigger — يُطلق دورة التقييم فوراً عند بدء شمعة جديدة
        self._tick_trigger: TickTrigger | None = None
        # Event يوقظ الحلقة الرئيسية عند وصول tick جديد
        self._tick_event   = threading.Event()

        if auto_start:
            self.start()

    def _init_live_feed(self):
        """Connect to MT5 in background — doesn't block startup."""
        def _connect():
            try:
                feed = MT5LiveFeed(symbol=self._symbol)
                feed.connect()
                self._live_feed  = feed
                self._data_source = "mt5_live"
                log.info("MT5LiveFeed connected — agents now use REAL market data")
                if self._event_bus:
                    self._event_bus.publish("agent_data_source", {"source": "mt5_live"})
                # discover all tradable symbols from MT5
                self._discover_symbols()
                # ── TickTrigger: يستبدل الانتظار بالشمعة بالاستطلاع كل 0.5ث ──
                self._start_tick_trigger(feed)
            except Exception as exc:
                log.warning("MT5LiveFeed unavailable (%s) — using fallback", exc)
                self._data_source = "assistant_csv" if self._assistant else "dummy"
        threading.Thread(target=_connect, daemon=True, name="mt5-feed-init").start()

    def _start_tick_trigger(self, feed: "MT5LiveFeed") -> None:
        """يُنشئ ويشغّل TickTrigger بعد الاتصال بـ MT5."""
        try:
            self._tick_trigger = TickTrigger(
                mt5_instance             = feed._mt5,
                symbol                   = self._symbol,
                on_new_bar               = self._on_tick_event,
                poll_secs                = 0.5,
                price_move_threshold_pts = 20.0,   # للذهب $2 حركة تستحق الانتباه
            )
            self._tick_trigger.start()
        except Exception as exc:
            log.warning("TickTrigger init failed (non-fatal): %s", exc)

    def _on_tick_event(self, tick_info: dict) -> None:
        """يُستدعى من TickTrigger — يُوقظ الحلقة الرئيسية فوراً."""
        self._tick_event.set()

    # Priority pairs to always include regardless of Market Watch state
    _PRIORITY_PAIRS = [
        "XAUUSDm", "BTCUSDm", "ETHUSDm", "USOILm", "UKOILm", "XAGUSDm",
        "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm", "USDCADm", "NZDUSDm",
        "USDCHFm", "EURGBPm", "EURJPYm", "GBPJPYm", "AUDJPYm", "CADJPYm",
        "EURCADm", "GBPCADm", "AUDCADm", "NZDJPYm", "BTCJPYm", "ETHBTCm",
        "BTCAUDm", "EURCHFm", "GBPCHFm", "XNGUSDm", "EURNZDm", "GBPNZDm",
    ]

    def _discover_symbols(self):
        """Enable priority pairs in Market Watch and discover all tradable symbols."""
        if not (self._live_feed and self._live_feed._connected):
            return
        try:
            mt5 = self._live_feed._mt5
            # Enable all priority pairs in Market Watch
            for sym in self._PRIORITY_PAIRS:
                try:
                    mt5.symbol_select(sym, True)
                except Exception:
                    pass

            # Now get all visible symbols (includes ones we just enabled)
            all_syms = mt5.symbols_get() or []
            visible  = [s for s in all_syms if s.visible]

            def rank(s):
                n = s.name.upper()
                if "XAU" in n: return 0
                if "BTC" in n or "ETH" in n: return 1
                if "OIL" in n or "XAG" in n: return 2
                if s.name in self._PRIORITY_PAIRS: return 3
                return 4

            visible.sort(key=rank)
            self._symbols_scanned = [s.name for s in visible][:_MAX_SCAN_SYMBOLS]
            log.info("Symbols enabled: %d visible | watching: %s …",
                     len(visible), self._symbols_scanned[:8])

            if self._event_bus:
                self._event_bus.publish("symbols_ready", {
                    "count":   len(self._symbols_scanned),
                    "symbols": self._symbols_scanned,
                })
        except Exception as exc:
            log.warning("symbol discovery failed: %s", exc)

    # ── multi-symbol parallel scanner ─────────────────────────────────────────

    def _scan_one_symbol(self, sym: str) -> dict | None:
        """Quick M1 scan for a single symbol — returns opportunity dict or None."""
        mt5 = self._live_feed._mt5
        try:
            import MetaTrader5 as mt5_mod
            bars = mt5.copy_rates_from_pos(sym, mt5_mod.TIMEFRAME_M1, 0, _SCAN_BARS)
            if bars is None or len(bars) < 50:
                return None
            tick = mt5.symbol_info_tick(sym)
            if not tick:
                return None

            df = pd.DataFrame(bars)
            df.rename(columns={"tick_volume": "volume"}, inplace=True)
            enriched = add_market_structure(df)
            snap     = latest_smc_snapshot(enriched)
            last     = enriched.iloc[-1]

            bid   = float(tick.bid)
            ask   = float(tick.ask)
            close = float(last["close"])
            sym_info = mt5.symbol_info(sym)
            digits   = int(sym_info.digits) if sym_info else 5
            pt       = 10 ** -digits
            spread   = round((ask - bid) / pt, 1)
            atr_pts  = float(last["atr"]) * close

            buy_score  = float(snap["smc_buy_score"])
            sell_score = float(snap["smc_sell_score"])
            bias       = float(snap["smc_bias"])

            # Simple opportunity signal: SMC + bias alignment
            action = "HOLD"
            if buy_score >= 2 and bias >= 1:
                action = "BUY"
            elif sell_score >= 2 and bias <= -1:
                action = "SELL"

            return {
                "symbol":    sym,
                "action":    action,
                "price":     round(close, digits),
                "bid":       round(bid, digits),
                "ask":       round(ask, digits),
                "spread":    spread,
                "atr":       round(atr_pts, digits),
                "smc_buy":   buy_score,
                "smc_sell":  sell_score,
                "bias":      bias,
                "rsi":       round(float(last.get("rsi", 50)), 1),
                "adx":       round(float(last.get("adx", 0)), 1),
                "ob_bull":   int(snap["in_bullish_ob"]),
                "ob_bear":   int(snap["in_bearish_ob"]),
            }
        except Exception as exc:
            log.debug("scan_one %s: %s", sym, exc)
            return None

    def _run_multi_scan(self):
        """Parallel scan all discovered symbols; publish best setups via SSE."""
        if not (self._live_feed and self._live_feed._connected):
            return
        symbols = list(self._symbols_scanned)
        if not symbols:
            return

        results = []
        scan_timeout = max(20, len(symbols) * 0.7)  # dynamic: ~0.7s per symbol
        with ThreadPoolExecutor(max_workers=_SCAN_WORKERS, thread_name_prefix="sym-scan") as pool:
            futs = {pool.submit(self._scan_one_symbol, s): s for s in symbols}
            try:
                for fut in as_completed(futs, timeout=scan_timeout):
                    try:
                        r = fut.result()
                        if r:
                            results.append(r)
                    except Exception:
                        pass
            except TimeoutError:
                for fut, sym in futs.items():
                    if fut.done():
                        try:
                            r = fut.result()
                            if r:
                                results.append(r)
                        except Exception:
                            pass
                log.debug("multi-scan partial timeout: collected %d/%d", len(results), len(symbols))

        buys  = sorted([r for r in results if r["action"] == "BUY"],
                       key=lambda x: (x["smc_buy"], x["adx"]), reverse=True)
        sells = sorted([r for r in results if r["action"] == "SELL"],
                       key=lambda x: (x["smc_sell"], x["adx"]), reverse=True)

        payload = {
            "scanned":  len(results),
            "buys":     buys[:8],
            "sells":    sells[:8],
            "all":      sorted(results, key=lambda x: abs(x["bias"]), reverse=True)[:20],
            "markets":  sorted(results, key=lambda x: abs(x["bias"]), reverse=True)[:20],
        }
        self._last_scan_result = payload
        if self._event_bus:
            self._event_bus.publish("multi_scan", payload)
        log.info("multi-scan: %d symbols | BUY=%d SELL=%d",
                 len(results), len(buys), len(sells))

    # ── control ────────────────────────────────────────────────────────────────

    def start(self) -> dict:
        with self._lock:
            if self.running:
                return {"started": False, "reason": "already running"}
            self.running = True
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="agent-runner"
            )
            self._thread.start()
            log.info("AgentRunner AUTO-STARTED | symbol=%s bar=%ds", self._symbol, self._bar_seconds)
            return {"started": True}

    def stop(self) -> dict:
        with self._lock:
            if not self.running:
                return {"stopped": False, "reason": "not running"}
            self.running = False
        # أوقظ الحلقة لتنتهي فوراً
        self._tick_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._tick_trigger:
            self._tick_trigger.stop()
        if self._live_feed:
            self._live_feed.disconnect()
        log.info("AgentRunner stopped")
        return {"stopped": True}

    def status(self) -> dict:
        coord_status = self.coordinator.status()
        return {
            "running":          self.running,
            "bar_count":        self._bar_count,
            "bar_seconds":      self._bar_seconds,
            "symbol":           self._symbol,
            "symbols_scanned":  self._symbols_scanned,
            "last_error":       self.last_error,
            "data_source":      self._data_source,
            "open_positions":   coord_status["open_positions"],
            "agents": [
                {
                    "name": name,
                    "has_open_trade": any(
                        a.name == name and a.has_open_trade()
                        for a in self.coordinator.agents
                    ),
                    **summary,
                }
                for name, summary in coord_status["agent_summaries"].items()
            ],
        }

    # ── market state builder ───────────────────────────────────────────────────

    def _build_market_state(self) -> dict:
        """Priority: MT5LiveFeed → JarvisAssistant → dummy.
        Caches MT5 state for 5s to avoid hammering the terminal."""
        now = time.time()

        # 1. Live MT5 feed (best) — cached 1 second (TickTrigger wakes us sooner)
        if self._live_feed and self._live_feed._connected:
            try:
                if self._state_cache and (now - self._state_cache_ts) < 1.0:
                    return self._state_cache
                state = self._live_feed.get_market_state()
                self._state_cache    = state
                self._state_cache_ts = now
                return state
            except Exception as exc:
                log.warning("live feed error, falling back: %s", exc)

        # 2. JarvisAssistant (CSV or MT5 via gateway)
        if self._assistant is not None:
            try:
                decision = self._assistant.analyze()
                last     = self._assistant.last_decision or {}
                return {
                    "probability":    float(decision.get("probability", 0.5)),
                    "smc_buy_score":  float(decision.get("smc_buy_score", 0)),
                    "smc_sell_score": float(decision.get("smc_sell_score", 0)),
                    "bias":           float(decision.get("smc_bias", 0)),
                    "context_score":  int(decision.get("context_score", 0)),
                    "spread_points":  float(decision.get("spread", 20)),
                    "atr":            float(last.get("atr", 0)),
                    "price":          float(decision.get("close", 0)),
                    "ob_buy_level":   0.0,
                    "ob_sell_level":  0.0,
                    "fvg_low":        0.0,
                    "fvg_high":       0.0,
                }
            except Exception as exc:
                log.debug("assistant fallback failed: %s", exc)

        # 3. Safe offline fallback: never generate random tradeable data.
        self._data_source = "unavailable"
        return {
            "probability":    0.5,
            "smc_buy_score":  0,
            "smc_sell_score": 0,
            "bias":           0,
            "context_score":  0,
            "spread_points":  9999,
            "atr":            0,
            "price":          0,
            "ob_buy_level":   0.0,
            "ob_sell_level":  0.0,
            "fvg_low":        0.0,
            "fvg_high":       0.0,
        }

    # ── main loop ──────────────────────────────────────────────────────────────

    def _loop(self):
        log.info(
            "Agent loop running — tick-driven (wakeup on new bar) + %ds fallback",
            self._bar_seconds,
        )
        while self.running:
            try:
                fn = self._market_state_fn if self._market_state_fn is not None else self._build_market_state
                ms = fn()
                self.coordinator.on_bar(ms)
                self._bar_count += 1
                self.last_error = None  # clear previous error on success

                if self._event_bus:
                    self._event_bus.publish("agent_bar", {
                        "bar": self._bar_count,
                        "price": ms.get("price", 0),
                        "prob": ms.get("probability", 0.5),
                        "smc_buy": ms.get("smc_buy_score", 0),
                        "bias": ms.get("bias", 0),
                        "source": self._data_source,
                    })

                if self._bar_count % _LEARNING_EVERY == 0 and self._event_bus:
                    self._event_bus.publish("agent_learning_update", {
                        "bar": self._bar_count,
                        "agents": [
                            {"name": a.name, **self.coordinator.learning.summary(a.name)}
                            for a in self.coordinator.agents
                        ],
                    })

                # Multi-symbol parallel scan every N ticks
                if self._bar_count % _SCAN_EVERY == 0:
                    threading.Thread(
                        target=self._run_multi_scan,
                        daemon=True,
                        name="multi-scan",
                    ).start()

            except Exception as exc:
                self.last_error = str(exc)
                log.error("AgentRunner loop error: %s", exc, exc_info=True)

            # ── سبر ذكي: استيقظ فوراً على tick، أو بعد bar_seconds كحد أقصى ──
            self._tick_event.wait(timeout=self._bar_seconds)
            self._tick_event.clear()

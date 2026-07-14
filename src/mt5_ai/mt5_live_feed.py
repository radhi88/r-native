"""
mt5_live_feed.py — Real-time MT5 data pipeline for the agent system.

Every call to get_market_state():
  1. Fetches the latest 400 M1 bars from MT5
  2. Runs add_market_structure() + model prediction
  3. Returns a market_state dict ready for AgentCoordinator.on_bar()
  4. Also captures tick delta (buy/sell pressure) and account state

Also provides get_tick_snapshot() for the eDEX panel.
"""

import datetime
import logging
import threading
import time

import joblib
import numpy as np
import pandas as pd
import tensorflow as tf

from .config import (
    FEATURE_COLUMNS,
    MODEL_CANDIDATES,
    MT5_TERMINAL_PATH,
    SCALER_PATH,
    SEQ_LEN,
)
from .market_structure import add_market_structure, latest_smc_snapshot

log = logging.getLogger("friday.mt5_live_feed")

_BARS      = 400
_TIMEFRAME = None   # set after mt5 import
_TICK_WINDOW_SEC = 60


class MT5LiveFeed:
    """
    Thread-safe live feed from MT5.
    Call get_market_state() → market_state dict for agents.
    Call get_tick_snapshot() → eDEX data dict.
    """

    def __init__(self, symbol: str = "XAUUSDm"):
        self.symbol    = symbol
        self._lock     = threading.Lock()
        self._mt5      = None
        self._model    = None
        self._scaler   = None
        self._connected = False
        self._last_state: dict | None = None
        self._last_tick:  dict | None = None

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def connect(self):
        import MetaTrader5 as mt5
        self._mt5 = mt5
        global _TIMEFRAME
        _TIMEFRAME = mt5.TIMEFRAME_M1

        ok = mt5.initialize(path=MT5_TERMINAL_PATH)
        if not ok:
            try:
                ok = mt5.initialize()
            except Exception:
                pass
        if not ok:
            raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")

        mt5.symbol_select(self.symbol, True)
        self._connected = True
        self._load_model()
        log.info("MT5LiveFeed connected | symbol=%s", self.symbol)
        return True

    def disconnect(self):
        if self._mt5 and self._connected:
            self._mt5.shutdown()
            self._connected = False

    def reconnect(self, delay: float = 1.0):
        self.disconnect()
        time.sleep(float(delay))
        self.connect()

    def _last_error_is_ipc(self):
        if not self._mt5:
            return False
        try:
            code, message = self._mt5.last_error()
        except Exception:
            return False
        text = str(message).lower()
        return int(code) == -10004 or "ipc" in text or "connection" in text

    def _load_model(self):
        for path in MODEL_CANDIDATES:
            if path.exists():
                try:
                    self._model  = tf.keras.models.load_model(str(path), compile=False)
                    self._scaler = joblib.load(SCALER_PATH) if SCALER_PATH.exists() else None
                    log.info("model loaded: %s", path.name)
                    return
                except Exception as exc:
                    log.warning("model load failed %s: %s", path, exc)
        log.warning("no model found — will return probability=0.5")

    # ── market state ───────────────────────────────────────────────────────────

    def get_market_state(self) -> dict:
        """Full pipeline: bars → market_structure → model → market_state."""
        if not self._connected:
            raise RuntimeError("not connected")

        with self._lock:
            try:
                state = self._build_state()
                self._last_state = state
                return state
            except Exception as exc:
                log.error("get_market_state error: %s", exc)
                if self._last_state:
                    return self._last_state   # return stale state rather than crash
                raise

    def _build_state(self) -> dict:
        mt5 = self._mt5

        # ── bars ────────────────────────────────────────────────────────────────
        bars = mt5.copy_rates_from_pos(self.symbol, _TIMEFRAME, 0, _BARS)
        if (bars is None or len(bars) < 50) and self._last_error_is_ipc():
            self.reconnect()
            mt5 = self._mt5
            bars = mt5.copy_rates_from_pos(self.symbol, _TIMEFRAME, 0, _BARS)
        if bars is None or len(bars) < 50:
            raise RuntimeError("insufficient bar data")

        df = pd.DataFrame(bars)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)

        # ── market structure ────────────────────────────────────────────────────
        enriched = add_market_structure(df)
        snap     = latest_smc_snapshot(enriched)
        last     = enriched.iloc[-1]

        # ── model prediction ────────────────────────────────────────────────────
        probability = 0.5
        if self._model and len(enriched) >= SEQ_LEN:
            seq = enriched[FEATURE_COLUMNS].values[-SEQ_LEN:].astype(float)
            if self._scaler:
                seq = self._scaler.transform(seq)
            probability = float(
                np.asarray(
                    self._model.predict(seq.reshape(1, SEQ_LEN, -1), verbose=0)
                ).squeeze()
            )

        # ── tick data for spread + delta ────────────────────────────────────────
        tick       = mt5.symbol_info_tick(self.symbol)
        bid        = float(tick.bid) if tick else float(last["close"])
        ask        = float(tick.ask) if tick else bid + 0.3
        spread_pts = round((ask - bid) * 10, 2)   # points (1 pt = 0.1 for gold)

        tick_delta = self._tick_delta()

        # ── account ─────────────────────────────────────────────────────────────
        acc_info = mt5.account_info()
        equity   = float(acc_info.equity) if acc_info else 0.0

        # ── ATR in price units ──────────────────────────────────────────────────
        close     = float(last["close"])
        atr_pts   = float(last["atr"]) * close    # atr column is pct

        # ── OB / FVG levels ─────────────────────────────────────────────────────
        ob_buy  = float(last.get("bullish_ob_low",  0) or 0)
        ob_sell = float(last.get("bearish_ob_high", 0) or 0)
        fvg_low = fvg_high = 0.0
        if last.get("bullish_fvg", 0) == 1:
            fvg_low  = float(last.get("high",   0) or 0)
            fvg_high = float(enriched.iloc[-3]["low"] if len(enriched) >= 3 else 0)
        elif last.get("bearish_fvg", 0) == 1:
            fvg_high = float(last.get("low",  0) or 0)
            fvg_low  = float(enriched.iloc[-3]["high"] if len(enriched) >= 3 else 0)

        state = {
            # agent inputs
            "probability":    round(probability, 4),
            "smc_buy_score":  float(snap["smc_buy_score"]),
            "smc_sell_score": float(snap["smc_sell_score"]),
            "bias":           float(snap["smc_bias"]),
            "context_score":  int(snap["smc_buy_score"] + snap["smc_sell_score"]),
            "spread_points":  spread_pts,
            "atr":            round(atr_pts, 4),
            "price":          close,
            "ob_buy_level":   ob_buy,
            "ob_sell_level":  ob_sell,
            "fvg_low":        fvg_low,
            "fvg_high":       fvg_high,
            # eDEX extras
            "bid":            bid,
            "ask":            ask,
            "tick_delta":     tick_delta,
            "account_equity": equity,
            "adx":            round(float(last.get("adx", 0)), 2),
            "rsi":            round(float(last.get("rsi", 50)), 2),
            "bos_up":         int(snap["bos_up"]),
            "bos_down":       int(snap["bos_down"]),
            "in_bullish_ob":  int(snap["in_bullish_ob"]),
            "in_bearish_ob":  int(snap["in_bearish_ob"]),
        }
        log.debug(
            "state | prob=%.4f smc_buy=%.0f bias=%.0f spread=%.1f atr=%.3f",
            probability, snap["smc_buy_score"], snap["smc_bias"], spread_pts, atr_pts,
        )
        return state

    def _tick_delta(self) -> int:
        """Count net bid direction moves in the last 60 seconds."""
        try:
            ticks = self._mt5.copy_ticks_from(
                self.symbol,
                datetime.datetime.now() - datetime.timedelta(seconds=_TICK_WINDOW_SEC),
                2000,
                self._mt5.COPY_TICKS_ALL,
            )
            if ticks is None or len(ticks) == 0:
                return 0
            bids = np.array([t[1] for t in ticks])   # field index 1 = bid
            diff = np.diff(bids)
            return int((diff > 0).sum()) - int((diff < 0).sum())
        except Exception:
            return 0

    # ── tick snapshot (eDEX) ───────────────────────────────────────────────────

    def get_tick_snapshot(self) -> dict:
        """Returns a rich tick-level dict for the eDEX live panel."""
        if not self._connected:
            return {}
        try:
            with self._lock:
                snap = self._build_tick_snapshot()
                self._last_tick = snap
                return snap
        except Exception as exc:
            log.debug("tick_snapshot error: %s", exc)
            return self._last_tick or {}

    def _build_tick_snapshot(self) -> dict:
        mt5  = self._mt5
        tick = mt5.symbol_info_tick(self.symbol)
        if not tick:
            return {}

        bid = float(tick.bid)
        ask = float(tick.ask)
        sym = mt5.symbol_info(self.symbol)
        acc = mt5.account_info()

        # Ticks last 60s for delta and speed
        ticks_raw = mt5.copy_ticks_from(
            self.symbol,
            datetime.datetime.now() - datetime.timedelta(seconds=60),
            3000,
            mt5.COPY_TICKS_ALL,
        )
        ticks_df = pd.DataFrame(ticks_raw) if ticks_raw is not None and len(ticks_raw) > 0 else pd.DataFrame()
        if not ticks_df.empty:
            bids     = ticks_df["bid"].values
            diff     = np.diff(bids)
            up       = int((diff > 0).sum())
            down     = int((diff < 0).sum())
            delta    = up - down
            speed    = round(len(ticks_df) / 60, 1)   # ticks per second
            vol_sum  = int(ticks_df["volume"].sum())
        else:
            delta = up = down = speed = vol_sum = 0

        # Last 10 ticks for the tape
        tape = []
        if not ticks_df.empty:
            for _, row in ticks_df.tail(10).iterrows():
                b = float(row["bid"])
                a = float(row["ask"])
                tape.append({
                    "bid":   round(b, 3),
                    "ask":   round(a, 3),
                    "spread": round((a - b) * 10, 1),
                })

        return {
            "symbol":         self.symbol,
            "bid":            round(bid, 3),
            "ask":            round(ask, 3),
            "spread_pts":     round((ask - bid) * 10, 1),
            "tick_delta":     delta,
            "buy_ticks":      up,
            "sell_ticks":     down,
            "ticks_per_sec":  speed,
            "volume_1min":    vol_sum,
            "equity":         float(acc.equity)  if acc else 0,
            "balance":        float(acc.balance) if acc else 0,
            "margin_free":    float(acc.margin_free) if acc else 0,
            "tape":           tape,
            "last_state":     self._last_state,
        }

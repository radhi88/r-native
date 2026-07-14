"""
TickTrigger — محرك اكتشاف الشمعة الجديدة بزمن الاستجابة 0.5 ث.

المشكلة القديمة:
  كانت الحلقة الرئيسية تنتظر 5 ثوانٍ (cache) ثم تقرأ حالة السوق من
  copy_rates_from_pos() التي تعتمد على الشمعة المكتملة. النتيجة:
  تأخير يصل إلى 60 ثانية على تايم‑فريم M1.

الحل:
  TickTrigger يسبر (poll) الـ tick الحالي كل 0.5 ث ويُطلق callback
  فوراً حين يتغير bar_time (= بداية شمعة جديدة) أو حين تتجاوز حركة
  السعر حداً محدداً (price_move_threshold_pts).

الاستخدام:
    from mt5_ai.tick_trigger import TickTrigger

    def on_new_bar(bar_info: dict):
        \"\"\"يُستدعى فوراً عند بداية شمعة جديدة.\"\"\"
        agent_runner.on_tick(bar_info)

    trigger = TickTrigger(
        mt5_instance = live_feed._mt5,
        symbol       = "XAUUSDm",
        on_new_bar   = on_new_bar,
        poll_secs    = 0.5,
        price_move_threshold_pts = 20,   # للذهب: 20 نقطة = $2
    )
    trigger.start()
    # ... later:
    trigger.stop()
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger("friday.tick_trigger")


class TickTrigger:
    """
    يسبر tick بمعدل poll_secs ويُطلق on_new_bar حين:
      - يتغير bar_time (شمعة جديدة)
      - أو يتجاوز تغيير السعر price_move_threshold_pts نقطة
        (حركة قوية = إشارة محتملة حتى داخل الشمعة الحالية)

    Parameters
    ----------
    mt5_instance : MetaTrader5 module
        الـ mt5 module (المثيل الحي الذي تم الاتصال به بالفعل).
    symbol : str
        الرمز المُراقَب.
    on_new_bar : Callable[[dict], None]
        callback يُستدعى مع dict يحتوي:
          bid, ask, bar_time, is_new_bar, price_move_pts, ts
    poll_secs : float
        فترة الاستطلاع بالثواني (default: 0.5).
    price_move_threshold_pts : float
        أدنى تغيير بالنقاط يستحق إشعار callback داخل الشمعة (default: 20).
    """

    def __init__(
        self,
        mt5_instance,
        symbol: str,
        on_new_bar: Callable[[dict], None],
        poll_secs: float = 0.5,
        price_move_threshold_pts: float = 20.0,
    ):
        self._mt5        = mt5_instance
        self._symbol     = symbol
        self._callback   = on_new_bar
        self._poll       = poll_secs
        self._move_thr   = price_move_threshold_pts

        self._last_bar_time: int   = 0
        self._last_bid:      float = 0.0
        self._running:       bool  = False
        self._thread: threading.Thread | None = None

    # ── life-cycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="tick-trigger"
        )
        self._thread.start()
        log.info("TickTrigger started | symbol=%s  poll=%.1fs  move_thr=%.0fpts",
                 self._symbol, self._poll, self._move_thr)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        log.info("TickTrigger stopped")

    # ── main polling loop ──────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            try:
                self._poll_once()
            except Exception as exc:
                log.debug("TickTrigger poll error: %s", exc)
            time.sleep(self._poll)

    def _poll_once(self) -> None:
        tick = self._mt5.symbol_info_tick(self._symbol)
        if tick is None:
            return

        bid      = float(tick.bid)
        ask      = float(tick.ask)
        bar_time = int(tick.time)   # seconds since epoch of the bar open

        is_new_bar   = bar_time != self._last_bar_time
        price_move   = abs(bid - self._last_bid) * 10  # in points (gold: ×10 = pips)
        big_move     = (price_move >= self._move_thr) and (self._last_bid > 0)

        if is_new_bar or big_move:
            info = {
                "bid":             bid,
                "ask":             ask,
                "bar_time":        bar_time,
                "is_new_bar":      is_new_bar,
                "price_move_pts":  round(price_move, 2),
                "ts":              time.time(),
            }
            if is_new_bar:
                log.info(
                    "TickTrigger → NEW BAR  %s  bid=%.3f  prev_bar=%d → %d",
                    self._symbol, bid, self._last_bar_time, bar_time,
                )
            else:
                log.info(
                    "TickTrigger → BIG MOVE  %s  move=%.1fpts  bid=%.3f",
                    self._symbol, price_move, bid,
                )

            # Update state BEFORE callback so re-entrant calls see latest
            self._last_bar_time = bar_time
            self._last_bid      = bid

            # Fire callback in a daemon thread so the poll loop never blocks
            threading.Thread(
                target=self._safe_callback,
                args=(info,),
                daemon=True,
                name="tick-cb",
            ).start()
        else:
            # Always update last_bid to track moves smoothly
            self._last_bid = bid

    def _safe_callback(self, info: dict) -> None:
        try:
            self._callback(info)
        except Exception as exc:
            log.error("TickTrigger callback error: %s", exc, exc_info=True)

"""
friday_binance_dom.py — Real DOM (Level 2 order book) from Binance for BTCUSDT.

Since Exness doesn't publish market depth via MT5, we tap Binance directly
for Bookmap-style visualization. This is INFORMATIONAL ONLY — we still trade
XAUUSDm via MT5. BTC DOM reflects global crypto liquidity / risk sentiment.

WebSocket: wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms
  → top 20 levels each side, refreshed every 100ms

Writes friday_binance_dom.json every second with:
  • bid/ask top 20 levels (price + size)
  • cumulative volume at each price tier
  • imbalance ratio (bid_total / ask_total)
  • largest single order (whale wall)
  • mid-price velocity

Run:  python friday_binance_dom.py
"""
from __future__ import annotations
import json
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import websocket   # websocket-client

OUTPUT  = Path(r"C:\Users\Radhi\MT5") / "friday_binance_dom.json"
SYMBOL  = "btcusdt"
STREAM  = f"wss://stream.binance.com:9443/ws/{SYMBOL}@depth20@100ms"
WRITE_EVERY_S = 1.0


class DomTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_book = None
        self.mid_history = deque(maxlen=60)   # last 60 mid-prices (~6s of velocity)
        self.book_count = 0
        self.last_msg_ts = 0

    def on_msg(self, ws, msg: str):
        try:
            data = json.loads(msg)
        except Exception:
            return
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        if not bids or not asks: return

        # bids = [[price_str, qty_str], ...]  sorted by best (highest) bid first
        # asks = [[price_str, qty_str], ...]  sorted by best (lowest)  ask first
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid = (best_bid + best_ask) / 2

        with self.lock:
            self.mid_history.append((time.time(), mid))
            self.last_book = {
                "ts":       time.time(),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid":      mid,
                "spread":   round(best_ask - best_bid, 2),
                "bids":     [[float(p), float(q)] for p, q in bids],
                "asks":     [[float(p), float(q)] for p, q in asks],
            }
            self.book_count += 1
            self.last_msg_ts = time.time()

    def on_err(self, ws, err): print(f"[WS error] {err}")
    def on_close(self, ws, code, reason): print(f"[WS closed] {code} {reason}")
    def on_open(self, ws): print(f"[WS open] subscribed to {SYMBOL}@depth20")

    def derive(self) -> dict:
        with self.lock:
            b = self.last_book
            history = list(self.mid_history)
        if b is None:
            return {"status": "waiting for first message"}

        bids = b["bids"]
        asks = b["asks"]

        bid_total = sum(q for _, q in bids)
        ask_total = sum(q for _, q in asks)
        imbalance = bid_total / ask_total if ask_total > 0 else 0

        # Largest single order ("whale wall")
        largest_bid = max(bids, key=lambda x: x[1])
        largest_ask = max(asks, key=lambda x: x[1])

        # Cumulative volume at each tier (depth from best)
        cum_bid = []
        cum = 0
        for p, q in bids:
            cum += q
            cum_bid.append({"price": p, "qty": q, "cum": round(cum, 4)})
        cum_ask = []
        cum = 0
        for p, q in asks:
            cum += q
            cum_ask.append({"price": p, "qty": q, "cum": round(cum, 4)})

        # Velocity: mid-price change over last 5 seconds
        velocity = 0
        if len(history) >= 2:
            now = history[-1][0]
            five_ago = next((m for t, m in history if now - t <= 5), history[0][1])
            velocity = round(history[-1][1] - five_ago, 2)

        return {
            "ts":         datetime.now().isoformat(),
            "symbol":     "BTCUSDT (Binance)",
            "msgs_received":  self.book_count,
            "last_msg_age_s": round(time.time() - self.last_msg_ts, 2),
            "best_bid":   b["best_bid"],
            "best_ask":   b["best_ask"],
            "mid":        b["mid"],
            "spread":     b["spread"],
            "velocity_5s": velocity,
            "bid_total":  round(bid_total, 4),
            "ask_total":  round(ask_total, 4),
            "imbalance":  round(imbalance, 3),
            "imbalance_side": "BID" if imbalance > 1.05 else "ASK" if imbalance < 0.95 else "FLAT",
            "largest_bid": {"price": largest_bid[0], "qty": largest_bid[1]},
            "largest_ask": {"price": largest_ask[0], "qty": largest_ask[1]},
            "bids":       cum_bid,
            "asks":       cum_ask,
        }


def writer_loop(tracker: DomTracker):
    while True:
        try:
            data = tracker.derive()
            OUTPUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            if "best_bid" in data:
                imb_arrow = "↑" if data["imbalance_side"] == "BID" else "↓" if data["imbalance_side"] == "ASK" else "="
                vel = data["velocity_5s"]
                vel_sign = "+" if vel >= 0 else ""
                print(f"[{datetime.now():%H:%M:%S}] "
                      f"BTC ${data['mid']:.2f}  spread {data['spread']:.1f}  "
                      f"vel/5s {vel_sign}{vel}  "
                      f"imb {imb_arrow}{data['imbalance']:.2f}  "
                      f"whale_bid {data['largest_bid']['qty']:.2f} @ {data['largest_bid']['price']:.0f}  "
                      f"msgs={data['msgs_received']}")
        except Exception as e:
            print(f"[writer error] {e}")
        time.sleep(WRITE_EVERY_S)


def main():
    print("═══ FRIDAY Binance DOM (Bookmap-lite) ═══")
    print(f"  Stream: {STREAM}")
    print(f"  Output: {OUTPUT.name}\n")

    tracker = DomTracker()

    # Background writer
    t = threading.Thread(target=writer_loop, args=(tracker,), daemon=True)
    t.start()

    # Reconnect loop
    while True:
        try:
            ws = websocket.WebSocketApp(
                STREAM,
                on_message=tracker.on_msg,
                on_error=tracker.on_err,
                on_close=tracker.on_close,
                on_open=tracker.on_open,
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            print(f"[connection error] {e} — reconnect in 5s")
        time.sleep(5)


if __name__ == "__main__":
    main()

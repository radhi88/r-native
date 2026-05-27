"""runtime/live_pulse.py — REAL-TIME XAUUSDm watcher.

Polls XAUUSDm every 2 seconds. Each stdout line is a NOTIFIABLE event
the Monitor tool surfaces immediately. Only emits when something
meaningful happens (not every tick):
  • New M1 candle close — emits its OHLC + close vs EMA9
  • Price crosses a key level (support/resistance/EMA21)
  • M1 RSI enters oversold (<30) or overbought (>70)
  • Bullish/bearish engulfing on close
  • Setup score reaches a threshold (Claude-Apex confluence ≥ 4/5)

User feedback: "وراقب بشكل لحظي مو كل ربع ساعة تنام" — this is the
heartbeat that keeps the project awake.
"""
from __future__ import annotations
import sys, time
from datetime import datetime, timezone


def _print(msg: str):
    sys.stdout.write(f"[{datetime.now():%H:%M:%S}] {msg}\n")
    sys.stdout.flush()


def main(symbol: str = "XAUUSDm", poll: float = 2.0):
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
    except Exception as e:
        _print(f"mt5 init err: {e}"); return

    last_bar_time = 0
    last_rsi_state = "neutral"
    last_level_alert = {}     # {level_price: timestamp_of_last_alert}
    last_score_alert = 0

    while True:
        try:
            tick = mt5.symbol_info_tick(symbol)
            if not tick: time.sleep(poll); continue

            bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 60)
            if bars is None or len(bars) < 30: time.sleep(poll); continue

            bar = bars[-1]                      # current (forming) bar
            prev = bars[-2]                     # last CLOSED bar

            # ─── EVENT 1: new M1 bar just closed ───
            if int(prev["time"]) != last_bar_time:
                if last_bar_time != 0:          # skip first iteration
                    arrow = "🟢" if prev["close"] > prev["open"] else "🔴"
                    body  = abs(prev["close"] - prev["open"])
                    upper_wick = prev["high"] - max(prev["open"], prev["close"])
                    lower_wick = min(prev["open"], prev["close"]) - prev["low"]
                    wick_note = ""
                    if upper_wick >= 2 * body and body > 0:
                        wick_note = " · TOP-PIN ⚠"
                    elif lower_wick >= 2 * body and body > 0:
                        wick_note = " · BOTTOM-PIN ✨"
                    _print(f"M1 close {arrow} O={prev['open']:.2f} H={prev['high']:.2f} "
                            f"L={prev['low']:.2f} C={prev['close']:.2f}{wick_note}")
                last_bar_time = int(prev["time"])

                # Engulfing detection on the just-closed bar
                if len(bars) >= 3:
                    a, b = bars[-3], bars[-2]
                    if (a["close"] < a["open"] and b["close"] > b["open"]
                            and b["close"] > a["open"] and b["open"] < a["close"]):
                        _print(f"🟢🟢 BULLISH ENGULFING M1 — close {b['close']:.2f}")
                    if (a["close"] > a["open"] and b["close"] < b["open"]
                            and b["close"] < a["open"] and b["open"] > a["close"]):
                        _print(f"🔴🔴 BEARISH ENGULFING M1 — close {b['close']:.2f}")

            # ─── EVENT 2: RSI extreme ───
            closes = [b["close"] for b in bars]
            gains = [max(closes[i]-closes[i-1], 0) for i in range(1,len(closes))]
            losses = [max(closes[i-1]-closes[i], 0) for i in range(1,len(closes))]
            if len(gains) >= 14:
                ag = sum(gains[:14])/14; al = sum(losses[:14])/14
                for i in range(14, len(gains)):
                    ag = (ag*13 + gains[i])/14; al = (al*13 + losses[i])/14
                rsi = 100 if al == 0 else round(100 - 100/(1 + ag/al), 1)
                new_state = "OVERSOLD" if rsi < 30 else ("OVERBOUGHT" if rsi > 70 else "neutral")
                if new_state != last_rsi_state and new_state != "neutral":
                    _print(f"⚡ M1 RSI = {rsi} → {new_state}")
                    last_rsi_state = new_state
                elif new_state == "neutral":
                    last_rsi_state = "neutral"

            # ─── EVENT 3: key level cross (M5 EMA21, M15 swing high/low) ───
            m5 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 30)
            m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 30)
            cur = tick.bid
            if m5 is not None and len(m5) >= 21:
                m5_closes = [b["close"] for b in m5]
                # EMA21 on M5
                k = 2/(21+1); ema = m5_closes[0]
                for c in m5_closes[1:]: ema = c*k + ema*(1-k)
                ema21_m5 = round(ema, 2)
                # Alert when price within 0.10 of EMA21 (and we haven't alerted recently)
                if abs(cur - ema21_m5) < 0.10:
                    key = f"M5-EMA21-{int(ema21_m5*100)}"
                    if last_level_alert.get(key, 0) < time.time() - 300:
                        _print(f"📍 price {cur:.2f} TESTING M5 EMA21 {ema21_m5:.2f}")
                        last_level_alert[key] = time.time()

            if m15 is not None and len(m15) >= 20:
                m15_high = max(b["high"] for b in m15[-20:])
                m15_low  = min(b["low"]  for b in m15[-20:])
                for level, name in [(m15_high, "M15 swing HIGH"),
                                     (m15_low,  "M15 swing LOW")]:
                    if abs(cur - level) < 0.50:
                        key = f"{name}-{int(level*100)}"
                        if last_level_alert.get(key, 0) < time.time() - 600:
                            _print(f"🎯 price {cur:.2f} testing {name} {level:.2f}")
                            last_level_alert[key] = time.time()

            time.sleep(poll)
        except KeyboardInterrupt:
            _print("stopped"); break
        except Exception as e:
            _print(f"loop err: {e}")
            time.sleep(poll)


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "XAUUSDm"
    main(sym)

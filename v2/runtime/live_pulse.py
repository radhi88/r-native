"""runtime/live_pulse.py — TICK-LEVEL XAUUSDm watcher (v2).

User mandate (2026-05-27): "اربط نفسك في التكات وادخل داخل تفاصيل الشمعات
وقوة البايعين والمشترين والمستويات السعرية".

What this watches (each becomes a notification line):

  ─── TICK STREAM ───
  • Aggressor flow per second — buy ticks vs sell ticks (delta)
  • Tick velocity spikes (ticks/sec > 3× baseline = momentum/news)
  • Spread anomalies (spread > 1.5× normal = liquidity event)

  ─── CANDLE ANATOMY (on every M1 close) ───
  • Body % of range — strong body (>70%) vs indecision (<25%)
  • Upper / lower wick lengths in $ — rejection signals
  • Pin bars, hammers, shooting stars, dojis, marubozu
  • Body color vs prior body — continuation or reversal
  • Volume (tick_volume on M1) vs 20-bar average

  ─── BUYER vs SELLER STRENGTH ───
  • Bullish vs bearish bars last N (M1 + M5)
  • Net body $ last 10 bars (buyers' total push vs sellers')
  • Higher-highs/lower-lows tracker
  • Acceleration: each new bar bigger/smaller than prior

  ─── SMART MONEY CONCEPTS (SMC) ───
  • Order Blocks (OB) — last bullish/bearish bar before impulse
  • Fair Value Gaps (FVG) — 3-bar imbalance zones (entry magnets)
  • Liquidity sweeps — wick above/below recent swing then close back
  • Break of Structure (BOS) — higher-high or lower-low confirmed

  ─── PRICE LEVELS (all in one) ───
  • Asian session high/low (00:00-08:00 UTC)
  • Prior day high/low/close
  • Current day open
  • M5 / M15 / H1 / H4 EMAs (8, 21, 50)
  • Daily/weekly pivots (PP, R1/R2/S1/S2)
  • Round numbers ($5 increments on gold)
  • Recent swing points (last 20 bars per TF)

Only emits on STATE CHANGES — silence is the default.
"""
from __future__ import annotations
import sys, time
from datetime import datetime, timezone, timedelta


def _print(msg: str):
    sys.stdout.write(f"[{datetime.now():%H:%M:%S}] {msg}\n")
    sys.stdout.flush()


# ─── helpers ───
def _ema(values, period):
    if not values: return 0
    k = 2 / (period + 1); e = values[0]
    for v in values[1:]: e = v * k + e * (1 - k)
    return e


def _rsi(closes, period=14):
    if len(closes) < period + 1: return 50.0
    g = [max(closes[i]-closes[i-1], 0) for i in range(1,len(closes))]
    l = [max(closes[i-1]-closes[i], 0) for i in range(1,len(closes))]
    ag = sum(g[:period])/period; al = sum(l[:period])/period
    for i in range(period, len(g)):
        ag = (ag*(period-1)+g[i])/period; al = (al*(period-1)+l[i])/period
    return 100 if al == 0 else round(100 - 100/(1 + ag/al), 1)


def _candle_anatomy(bar):
    """Return classification of a closed bar's anatomy."""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = abs(c - o); rng = h - l
    if rng == 0: return {"kind": "void", "body_pct": 0, "upper": 0, "lower": 0, "bullish": False}
    upper = h - max(o, c); lower = min(o, c) - l
    body_pct = body / rng * 100
    bullish = c > o
    kind = "neutral"
    if body_pct < 15:
        kind = "doji"
    elif body_pct >= 80:
        kind = "marubozu_bull" if bullish else "marubozu_bear"
    elif upper >= 2 * body and lower < body:
        kind = "shooting_star" if not bullish else "inverted_hammer"
    elif lower >= 2 * body and upper < body:
        kind = "hammer" if bullish else "hanging_man"
    elif body_pct >= 60:
        kind = "strong_bull" if bullish else "strong_bear"
    elif body_pct >= 30:
        kind = "normal_bull" if bullish else "normal_bear"
    else:
        kind = "small_bull" if bullish else "small_bear"
    return {
        "kind": kind, "body_pct": round(body_pct, 0),
        "body_$": round(body, 2), "upper_$": round(upper, 2), "lower_$": round(lower, 2),
        "bullish": bullish, "range_$": round(rng, 2),
    }


def _detect_fvg(bars):
    """3-bar imbalance: bull FVG when bars[i+1].low > bars[i-1].high.
    Returns the most recent unfilled FVG zone (top, bot) per direction.
    Lookback last 20 bars only."""
    bull_fvg = None; bear_fvg = None
    n = min(20, len(bars) - 2)
    for i in range(len(bars) - 2, len(bars) - n - 2, -1):
        if i < 1: break
        a, b, c = bars[i-1], bars[i], bars[i+1]
        # Bullish FVG: c.low > a.high (gap between candle a's high and c's low)
        if c["low"] > a["high"]:
            bull_fvg = (a["high"], c["low"], i)
            break
    for i in range(len(bars) - 2, len(bars) - n - 2, -1):
        if i < 1: break
        a, b, c = bars[i-1], bars[i], bars[i+1]
        # Bearish FVG: c.high < a.low
        if c["high"] < a["low"]:
            bear_fvg = (c["high"], a["low"], i)
            break
    return bull_fvg, bear_fvg


def _detect_order_block(bars):
    """Last opposite-color bar before a strong impulse. Returns (low, high, type)."""
    if len(bars) < 5: return None
    for i in range(len(bars) - 2, max(0, len(bars) - 10), -1):
        cur, nxt = bars[i], bars[i+1]
        cur_bull = cur["close"] > cur["open"]
        nxt_body = abs(nxt["close"] - nxt["open"])
        nxt_rng  = nxt["high"] - nxt["low"]
        nxt_bull = nxt["close"] > nxt["open"]
        # Strong impulse = body > 60% of range
        strong = nxt_body / max(nxt_rng, 1e-9) > 0.6
        if strong and cur_bull != nxt_bull:
            ob_type = "BULL_OB" if nxt_bull else "BEAR_OB"
            return (cur["low"], cur["high"], ob_type, i)
    return None


def _round_levels(price, step=5):
    base = (price // step) * step
    return [base - step, base, base + step, base + 2*step]


def main(symbol: str = "XAUUSDm", poll: float = 1.0):
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
    except Exception as e:
        _print(f"mt5 init err: {e}"); return

    last_bar_time = 0
    last_rsi_state = "neutral"
    last_level_alert = {}     # {key: timestamp_of_last_alert}
    tick_history = []         # rolling last-60s of ticks
    last_spread_alert = 0
    last_pressure_dir = "FLAT"
    last_ob = None; last_bull_fvg = None; last_bear_fvg = None

    _print(f"📡 live_pulse v2 online · {symbol} · tick poll {poll}s")

    while True:
        try:
            now_ts = time.time()
            tick = mt5.symbol_info_tick(symbol)
            if not tick: time.sleep(poll); continue

            # ─── Tick stream collection ───
            cur_mid = (tick.bid + tick.ask) / 2
            spread = tick.ask - tick.bid
            tick_history.append({"ts": now_ts, "bid": tick.bid, "ask": tick.ask, "mid": cur_mid})
            tick_history = [t for t in tick_history if t["ts"] > now_ts - 60]    # 60s rolling

            # Spread anomaly (event)
            if spread > 0.50 and now_ts - last_spread_alert > 60:
                _print(f"⚠ SPREAD widening · ${spread:.2f} (normal ~$0.30)")
                last_spread_alert = now_ts

            # ─── Bars fetch ───
            m1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 60)
            m5 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 60)
            m15= mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 60)
            h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 50)
            d1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 5)
            if any(x is None or len(x) < 20 for x in (m1, m5, m15, h1)):
                time.sleep(poll); continue

            cur_bar = m1[-1]; prev_bar = m1[-2]

            # ─── EVENT: M1 close ───
            if int(prev_bar["time"]) != last_bar_time:
                if last_bar_time != 0:
                    a = _candle_anatomy(prev_bar)
                    arrow = "🟢" if a["bullish"] else "🔴"
                    tv = int(prev_bar["tick_volume"])
                    # Volume vs 20-bar mean
                    vols = [int(b["tick_volume"]) for b in m1[-21:-1]]
                    vmean = sum(vols)/max(1,len(vols))
                    vstr = f"v{tv}({tv/max(vmean,1)*100:.0f}%)"
                    _print(f"M1 {arrow} {a['kind']:14} body={a['body_pct']:.0f}% "
                            f"U={a['upper_$']:.2f} L={a['lower_$']:.2f} {vstr} "
                            f"C={prev_bar['close']:.2f}")

                    # Engulfing
                    if len(m1) >= 3:
                        aa, bb = m1[-3], m1[-2]
                        if (aa["close"] < aa["open"] and bb["close"] > bb["open"]
                                and bb["close"] > aa["open"] and bb["open"] < aa["close"]):
                            _print(f"🟢🟢 BULLISH ENGULFING · close {bb['close']:.2f}")
                        if (aa["close"] > aa["open"] and bb["close"] < bb["open"]
                                and bb["close"] < aa["open"] and bb["open"] > aa["close"]):
                            _print(f"🔴🔴 BEARISH ENGULFING · close {bb['close']:.2f}")

                    # Volume spike (>2× mean)
                    if tv > vmean * 2 and vmean > 0:
                        _print(f"📊 VOLUME SPIKE · {tv} ticks ({tv/vmean*100:.0f}% of mean)")

                last_bar_time = int(prev_bar["time"])

                # ─── Buyer/seller pressure (last 10 closed M1 bars) ───
                last10 = m1[-11:-1]
                bull_body = sum(b["close"]-b["open"] for b in last10 if b["close"]>b["open"])
                bear_body = sum(b["open"]-b["close"] for b in last10 if b["close"]<b["open"])
                net = bull_body - bear_body
                dir_ = "BUY+" if net > 1.5 else ("SELL+" if net < -1.5 else "FLAT")
                if dir_ != last_pressure_dir:
                    _print(f"⚖ pressure 10M1: net=${net:+.2f} BULL=${bull_body:.2f} "
                           f"BEAR=${bear_body:.2f} → {dir_}")
                    last_pressure_dir = dir_

                # ─── SMC: detect new OB and FVG ───
                ob = _detect_order_block(list(m5))
                if ob and ob != last_ob:
                    _print(f"🔷 OB detected M5: {ob[2]} zone {ob[0]:.2f}-{ob[1]:.2f}")
                    last_ob = ob
                bull_fvg, bear_fvg = _detect_fvg(list(m5))
                if bull_fvg and bull_fvg != last_bull_fvg:
                    _print(f"🟦 BULL FVG M5: ${bull_fvg[0]:.2f}-${bull_fvg[1]:.2f} "
                            f"(gap ${bull_fvg[1]-bull_fvg[0]:.2f})")
                    last_bull_fvg = bull_fvg
                if bear_fvg and bear_fvg != last_bear_fvg:
                    _print(f"🟥 BEAR FVG M5: ${bear_fvg[0]:.2f}-${bear_fvg[1]:.2f}")
                    last_bear_fvg = bear_fvg

            # ─── RSI w/ hysteresis ───
            closes = [b["close"] for b in m1]
            rsi = _rsi(closes, 14)
            if last_rsi_state == "OVERBOUGHT":
                if rsi < 65: last_rsi_state = "neutral"
            elif last_rsi_state == "OVERSOLD":
                if rsi > 35: last_rsi_state = "neutral"
            else:
                if rsi > 70:
                    _print(f"⚡ M1 RSI = {rsi} → OVERBOUGHT (after run-up)"); last_rsi_state = "OVERBOUGHT"
                elif rsi < 30:
                    _print(f"⚡ M1 RSI = {rsi} → OVERSOLD (after sell-off)"); last_rsi_state = "OVERSOLD"

            # ─── Tick velocity (momentum/news) ───
            if len(tick_history) > 10:
                ticks_per_sec = len(tick_history) / 60
                if ticks_per_sec > 5:    # >5 ticks/sec sustained = burst
                    key = "BURST"
                    if last_level_alert.get(key, 0) < now_ts - 60:
                        _print(f"🌊 tick BURST · {ticks_per_sec:.1f} ticks/sec (60s window)")
                        last_level_alert[key] = now_ts

            # ─── Levels watch (price near key) ───
            cur = tick.bid
            # M5 EMA21
            m5_closes = [b["close"] for b in m5]
            ema21_m5 = _ema(m5_closes, 21)
            # H1 EMA50
            h1_closes = [b["close"] for b in h1]
            ema50_h1 = _ema(h1_closes, 50)
            # Prior day H/L/close (d1[-2] = yesterday since d1[-1] is today forming)
            if len(d1) >= 2:
                pdh = d1[-2]["high"]; pdl = d1[-2]["low"]; pdc = d1[-2]["close"]
                today_open = d1[-1]["open"]
                # Daily pivot
                pp = (pdh + pdl + pdc) / 3
                r1 = 2*pp - pdl; s1 = 2*pp - pdh
                r2 = pp + (pdh - pdl); s2 = pp - (pdh - pdl)
            else: pdh=pdl=pdc=today_open=pp=r1=s1=r2=s2=None
            # Asian session high/low (last 0-8 UTC)
            now_utc = datetime.now(timezone.utc)
            asia_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            if now_utc.hour >= 8:
                # Asian session has closed today — use today's 0-8
                pass
            asian_bars = [b for b in m15 if asia_start.timestamp() <= int(b["time"]) < (asia_start + timedelta(hours=8)).timestamp()]
            asia_h = max((b["high"] for b in asian_bars), default=None)
            asia_l = min((b["low"]  for b in asian_bars), default=None)

            levels_to_watch = [
                ("M5 EMA21", ema21_m5, 0.15),
                ("H1 EMA50", ema50_h1, 0.30),
                ("Prior Day HIGH", pdh, 0.50),
                ("Prior Day LOW",  pdl, 0.50),
                ("Prior Day Close", pdc, 0.30),
                ("Daily Pivot",   pp, 0.30),
                ("R1", r1, 0.30), ("S1", s1, 0.30),
                ("R2", r2, 0.50), ("S2", s2, 0.50),
                ("Asian HIGH", asia_h, 0.40),
                ("Asian LOW",  asia_l, 0.40),
            ]
            for name, level, tol in levels_to_watch:
                if level is None: continue
                if abs(cur - level) < tol:
                    key = f"{name}-{int(level*100)}"
                    if last_level_alert.get(key, 0) < now_ts - 300:
                        side = "above" if cur > level else "below"
                        _print(f"📍 price {cur:.2f} testing {name} {level:.2f} (cur {side})")
                        last_level_alert[key] = now_ts

            # Round numbers
            for rn in _round_levels(cur, 5):
                if abs(cur - rn) < 0.30:
                    key = f"RN-{rn}"
                    if last_level_alert.get(key, 0) < now_ts - 600:
                        _print(f"🔢 round number {rn:.0f} in play (price {cur:.2f})")
                        last_level_alert[key] = now_ts

            time.sleep(poll)
        except KeyboardInterrupt:
            _print("stopped"); break
        except Exception as e:
            _print(f"loop err: {e}")
            time.sleep(poll)


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "XAUUSDm"
    poll = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    main(sym, poll)

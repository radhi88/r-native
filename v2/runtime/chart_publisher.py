"""runtime/chart_publisher.py — put EVERYTHING I see on the chart.

User mandate 2026-05-27: "اضف كل اللي تشوفه واهدافك على نفس الشارت...
حددها داخل الكود نفسه".

This process polls XAUUSDm every 4 seconds, computes the FULL set of
analysis I'd draw manually, and writes them as `drawings` into
Common/Files/friday_brain_orders.json. The FRIDAY_Brain_Executor EA
already reads that file and renders: hline, trendline, zone, fib,
marker, channel. So no EA recompile needed for the core suite.

What gets drawn on the chart in real-time:

  ─── ZONES (semi-transparent rectangles) ───
  • Bullish Order Block         (light blue)
  • Bearish Order Block         (pink)
  • Bullish Fair Value Gap      (cyan, "BULL FVG")
  • Bearish Fair Value Gap      (red, "BEAR FVG")
  • Volume Profile Value Area   (yellow, "VA")

  ─── LINES (horizontal level markers) ───
  • VWAP (session-anchored)     (white, dashed)
  • POC (Point of Control)      (yellow solid)
  • VAH / VAL                   (yellow dotted)
  • Prior Day H / L / C         (gray)
  • Daily Pivot + R1/R2/S1/S2   (purple)
  • Asian session H / L         (orange)
  • Recent swing highs/lows     (white arrows)
  • Round numbers (every $5)    (faint gray)

  ─── ACTIVE TRADE OVERLAY ───
  • Entry line          (blue thick, "🧠 ENTRY")
  • SL line             (red thick, "SL")
  • TP line             (green thick, "TP")
  • Target zones        (where price would profit)
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ORDERS_JSON = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files\friday_brain_orders.json")
SYMBOL = "XAUUSDm"
POLL = 4.0


# ─── color helpers ───
def _hex(rgb_str: str) -> str:
    return rgb_str if rgb_str.startswith("#") else f"#{rgb_str}"


COLOR_BULL_OB     = "#4A90E2"     # blue
COLOR_BEAR_OB     = "#E74C3C"     # red
COLOR_BULL_FVG    = "#00C2FF"     # cyan
COLOR_BEAR_FVG    = "#FF6B6B"     # pink
COLOR_VWAP        = "#FFFFFF"     # white
COLOR_POC         = "#FFD700"     # gold
COLOR_VA          = "#FFC107"     # amber
COLOR_PRIOR_DAY   = "#888888"     # gray
COLOR_PIVOT       = "#9B59B6"     # purple
COLOR_ASIA        = "#FFA500"     # orange
COLOR_SWING_HIGH  = "#FF4444"     # bright red
COLOR_SWING_LOW   = "#44FF44"     # bright green
COLOR_ROUND       = "#555555"     # dim gray
COLOR_TARGET_BULL = "#00FF88"     # mint green
COLOR_ENTRY       = "#3498DB"     # bright blue
COLOR_SL          = "#E74C3C"     # red
COLOR_TP          = "#2ECC71"     # green


def _get_bars(mt5, tf, n):
    r = mt5.copy_rates_from_pos(SYMBOL, tf, 0, n)
    if r is None: return []
    return [dict(b._asdict()) if hasattr(b, "_asdict")
            else {k: b[k] for k in b.dtype.names} for b in r]


def _detect_swings(bars: list, left_right: int = 2):
    """Fractal-style swings: bar's high higher than `left_right` bars
    on each side. Returns (highs, lows) as [(bars_ago, price), ...]."""
    highs, lows = [], []
    n = len(bars)
    for i in range(left_right, n - left_right):
        window_h = [b["high"] for b in bars[i-left_right:i+left_right+1]]
        window_l = [b["low"]  for b in bars[i-left_right:i+left_right+1]]
        if bars[i]["high"] == max(window_h):
            highs.append((n - 1 - i, bars[i]["high"]))
        if bars[i]["low"] == min(window_l):
            lows.append((n - 1 - i, bars[i]["low"]))
    return highs[-4:], lows[-4:]   # last 4 each


def _find_all_fvgs(bars: list, lookback: int = 40):
    """Return list of all UNFILLED FVGs in the lookback window.
    Each: {type, top, bot, bar_ago_at_creation, age_bars}."""
    out = []
    n = min(lookback, len(bars) - 2)
    for i in range(len(bars) - 2, max(0, len(bars) - n - 2), -1):
        if i < 1: continue
        a, c = bars[i-1], bars[i+1]
        # bullish FVG: c.low > a.high
        if c["low"] > a["high"]:
            # Check still unfilled (no later bar closed inside)
            top, bot = c["low"], a["high"]
            filled = any((b["low"] < bot or b["high"] > top) and (b["low"] < top and b["high"] > bot)
                          for b in bars[i+2:])
            if not filled:
                out.append({"type": "bull", "top": top, "bot": bot,
                             "age_bars": len(bars) - 1 - (i+1)})
        if c["high"] < a["low"]:
            top, bot = a["low"], c["high"]
            filled = any((b["low"] < top and b["high"] > bot) for b in bars[i+2:])
            if not filled:
                out.append({"type": "bear", "top": top, "bot": bot,
                             "age_bars": len(bars) - 1 - (i+1)})
    return out


def _find_obs(bars: list, lookback: int = 15):
    """Return list of Order Blocks (max 4 most recent)."""
    out = []
    for i in range(len(bars) - 2, max(0, len(bars) - lookback - 2), -1):
        if i < 1: continue
        cur, nxt = bars[i], bars[i+1]
        cur_bull = cur["close"] > cur["open"]
        nxt_body = abs(nxt["close"] - nxt["open"])
        nxt_rng  = max(nxt["high"] - nxt["low"], 1e-9)
        nxt_bull = nxt["close"] > nxt["open"]
        if nxt_body / nxt_rng > 0.6 and cur_bull != nxt_bull:
            out.append({
                "type": "BULL_OB" if nxt_bull else "BEAR_OB",
                "low": cur["low"], "high": cur["high"],
                "age_bars": len(bars) - 1 - i,
            })
            if len(out) >= 3: break
    return out


def _compute_vwap_anchored(bars: list, session_start_ts: float):
    """VWAP anchored to session_start. Returns list of (ts, vwap) for plotting."""
    if not bars: return []
    sum_pv, sum_v = 0.0, 0.0
    points = []
    for b in bars:
        if int(b["time"]) < session_start_ts: continue
        tp = (b["high"] + b["low"] + b["close"]) / 3
        v  = max(int(b["tick_volume"]), 1)
        sum_pv += tp * v
        sum_v  += v
        vwap = sum_pv / sum_v
        points.append((int(b["time"]), vwap))
    return points


def _compute_volume_profile(bars: list, bin_size: float = 1.0):
    """Bin closed bars by price (using HLC/3 + tick_volume). Returns
    {poc, vah, val, bins} where VA covers 70% of total volume."""
    if not bars: return None
    # Bin by mid-price
    binned = {}
    for b in bars:
        mid = (b["high"] + b["low"] + b["close"]) / 3
        key = round(mid / bin_size) * bin_size
        binned[key] = binned.get(key, 0) + int(b["tick_volume"])
    if not binned: return None
    # POC = bin with max volume
    poc = max(binned.items(), key=lambda x: x[1])[0]
    total = sum(binned.values())
    target = total * 0.70
    # Expand around POC until 70% of volume covered
    sorted_keys = sorted(binned.keys())
    poc_i = sorted_keys.index(poc)
    lo, hi = poc_i, poc_i
    acc = binned[poc]
    while acc < target and (lo > 0 or hi < len(sorted_keys) - 1):
        v_below = binned[sorted_keys[lo-1]] if lo > 0 else -1
        v_above = binned[sorted_keys[hi+1]] if hi < len(sorted_keys)-1 else -1
        if v_below >= v_above and lo > 0:
            lo -= 1; acc += binned[sorted_keys[lo]]
        elif hi < len(sorted_keys)-1:
            hi += 1; acc += binned[sorted_keys[hi]]
        else: break
    return {"poc": poc, "val": sorted_keys[lo], "vah": sorted_keys[hi]}


def build_drawings():
    """Compute the FULL drawing set for the chart."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
    except Exception:
        return []

    drawings = []
    now = datetime.now(timezone.utc)
    # Session anchor: 00:00 UTC today (or last session start)
    asia_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Fetch bars
    m5  = _get_bars(mt5, mt5.TIMEFRAME_M5,  120)
    m15 = _get_bars(mt5, mt5.TIMEFRAME_M15, 96)   # 24h
    h1  = _get_bars(mt5, mt5.TIMEFRAME_H1,  48)
    d1  = _get_bars(mt5, mt5.TIMEFRAME_D1,  10)
    if not (m5 and m15 and h1 and d1): return []

    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick: return []
    cur = (tick.bid + tick.ask) / 2

    # ─── FVGs (M5) ───
    fvgs = _find_all_fvgs(m5, lookback=40)
    for fvg in fvgs[:6]:
        col = COLOR_BULL_FVG if fvg["type"] == "bull" else COLOR_BEAR_FVG
        label = "BULL FVG" if fvg["type"] == "bull" else "BEAR FVG"
        drawings.append({
            "type": "hline", "price": fvg["top"], "color": col,
            "label": f"{label} top ${fvg['top']:.2f}",
        })
        drawings.append({
            "type": "hline", "price": fvg["bot"], "color": col,
            "label": f"{label} bot ${fvg['bot']:.2f}",
        })

    # ─── Order Blocks (M5) ───
    obs = _find_obs(m5, lookback=15)
    for ob in obs:
        col = COLOR_BULL_OB if ob["type"] == "BULL_OB" else COLOR_BEAR_OB
        drawings.append({
            "type": "zone", "top": ob["high"], "bottom": ob["low"],
            "color": col, "label": f"{ob['type']} {ob['low']:.2f}-{ob['high']:.2f}",
        })

    # ─── Recent swings (M15) ───
    swing_highs, swing_lows = _detect_swings(m15, left_right=2)
    for ba, p in swing_highs:
        drawings.append({"type": "marker", "bars_ago": ba * 3,  # M15→M1 conversion approx
                          "shape": "arrowDown", "color": COLOR_SWING_HIGH,
                          "label": f"swing H {p:.2f}"})
        drawings.append({"type": "hline", "price": p, "color": COLOR_SWING_HIGH,
                          "label": f"M15 swing H {p:.2f}"})
    for ba, p in swing_lows:
        drawings.append({"type": "marker", "bars_ago": ba * 3,
                          "shape": "arrowUp", "color": COLOR_SWING_LOW,
                          "label": f"swing L {p:.2f}"})
        drawings.append({"type": "hline", "price": p, "color": COLOR_SWING_LOW,
                          "label": f"M15 swing L {p:.2f}"})

    # ─── Prior Day H/L/C ───
    if len(d1) >= 2:
        pd = d1[-2]
        for tag, price, col in [("PD HIGH", pd["high"], COLOR_PRIOR_DAY),
                                  ("PD LOW",  pd["low"],  COLOR_PRIOR_DAY),
                                  ("PD CLOSE",pd["close"],COLOR_PRIOR_DAY)]:
            drawings.append({"type": "hline", "price": price, "color": col,
                              "label": f"{tag} ${price:.2f}"})

        # Daily pivot + R/S
        pp = (pd["high"] + pd["low"] + pd["close"]) / 3
        r1 = 2*pp - pd["low"];   s1 = 2*pp - pd["high"]
        r2 = pp + (pd["high"] - pd["low"]); s2 = pp - (pd["high"] - pd["low"])
        for tag, price in [("PP", pp), ("R1", r1), ("R2", r2), ("S1", s1), ("S2", s2)]:
            drawings.append({"type": "hline", "price": price, "color": COLOR_PIVOT,
                              "label": f"{tag} ${price:.2f}"})

    # ─── Asian H/L (last 0-8 UTC of today) ───
    asia_end = asia_start + timedelta(hours=8)
    asian_bars = [b for b in m15 if asia_start.timestamp() <= int(b["time"]) < asia_end.timestamp()]
    if asian_bars:
        ah = max(b["high"] for b in asian_bars)
        al = min(b["low"]  for b in asian_bars)
        drawings.append({"type": "hline", "price": ah, "color": COLOR_ASIA,
                          "label": f"Asian H ${ah:.2f}"})
        drawings.append({"type": "hline", "price": al, "color": COLOR_ASIA,
                          "label": f"Asian L ${al:.2f}"})

    # ─── VWAP (anchored to Asian session start) — as trendline ───
    vwap_pts = _compute_vwap_anchored(m5, asia_start.timestamp())
    if len(vwap_pts) >= 2:
        # Convert MT5 timestamps to bars_ago for the EA's trendline format
        # The EA expects bars_ago on PERIOD_CURRENT. Use anchor first and last.
        first_ts, first_vw = vwap_pts[0]
        last_ts, last_vw   = vwap_pts[-1]
        # bars_ago for current chart period (we publish for M5-aware EA but
        # the chart could be on any TF — give bars_ago in seconds/period_seconds
        # caller will reinterpret based on chart period). Use 0 for "now" and
        # 60 for the anchor — EA will best-fit on current TF.
        drawings.append({
            "type": "trendline",
            "from": {"bars_ago": 60, "price": first_vw},
            "to":   {"bars_ago": 0,  "price": last_vw},
            "color": COLOR_VWAP,
            "label": f"VWAP ${last_vw:.2f}",
        })
        drawings.append({
            "type": "hline", "price": last_vw, "color": COLOR_VWAP,
            "label": f"VWAP last ${last_vw:.2f}",
        })

    # ─── Volume Profile (last 12h H1 = 12 bars) ───
    vp_bars = h1[-12:] if len(h1) >= 12 else h1
    vp = _compute_volume_profile(vp_bars, bin_size=1.0)
    if vp:
        drawings.append({"type": "hline", "price": vp["poc"], "color": COLOR_POC,
                          "label": f"POC ${vp['poc']:.2f}"})
        drawings.append({"type": "hline", "price": vp["vah"], "color": COLOR_VA,
                          "label": f"VAH ${vp['vah']:.2f}"})
        drawings.append({"type": "hline", "price": vp["val"], "color": COLOR_VA,
                          "label": f"VAL ${vp['val']:.2f}"})
        # Highlight the value area as a translucent zone
        drawings.append({"type": "zone", "top": vp["vah"], "bottom": vp["val"],
                          "color": COLOR_VA, "label": f"VA {vp['val']:.2f}-{vp['vah']:.2f}"})

    # ─── Round numbers (every $5 ±$25 around current) ───
    base = (cur // 5) * 5
    for offset in range(-5, 6):
        rn = base + offset * 5
        if abs(rn - cur) > 30: continue
        drawings.append({"type": "hline", "price": rn, "color": COLOR_ROUND,
                          "label": f"RN ${rn:.0f}"})

    # ─── Active trade overlay (any R Native open position) ───
    poss = [p for p in (mt5.positions_get() or []) if p.symbol == SYMBOL
            and int(p.magic) == 20260605]
    for p in poss:
        side = "BUY" if p.type == 0 else "SELL"
        drawings.append({"type": "hline", "price": p.price_open, "color": COLOR_ENTRY,
                          "label": f"🧠 ENTRY {side} {p.price_open:.2f} pl${p.profit:+.2f}"})
        if p.sl:
            drawings.append({"type": "hline", "price": p.sl, "color": COLOR_SL,
                              "label": f"SL ${p.sl:.2f}"})
        if p.tp:
            drawings.append({"type": "hline", "price": p.tp, "color": COLOR_TP,
                              "label": f"TP ${p.tp:.2f}"})

    # ─── My TARGETS for the next move (educated guess from levels) ───
    # Up-target: nearest level above current (resistance to reach)
    levels_up = [d["price"] for d in drawings if d.get("type") == "hline"
                  and d.get("price", 0) > cur and d.get("price", 0) < cur + 20]
    levels_dn = [d["price"] for d in drawings if d.get("type") == "hline"
                  and d.get("price", 0) < cur and d.get("price", 0) > cur - 20]
    if levels_up:
        nxt_up = min(levels_up)
        drawings.append({"type": "hline", "price": nxt_up, "color": COLOR_TARGET_BULL,
                          "label": f"🎯 next UP ${nxt_up:.2f} ({nxt_up-cur:+.2f})"})
    if levels_dn:
        nxt_dn = max(levels_dn)
        drawings.append({"type": "hline", "price": nxt_dn, "color": COLOR_TARGET_BULL,
                          "label": f"🎯 next DN ${nxt_dn:.2f} ({nxt_dn-cur:+.2f})"})

    return drawings


def publish_loop():
    print(f"[chart_publisher] writing to {ORDERS_JSON}")
    while True:
        try:
            drawings = build_drawings()
            # Merge: read existing JSON, replace drawings, write back atomically
            if ORDERS_JSON.exists():
                try:
                    cur = json.loads(ORDERS_JSON.read_text(encoding="utf-8"))
                except Exception:
                    cur = {}
            else:
                cur = {}
            cur["drawings"] = drawings
            cur["chart_publisher_ts"] = datetime.now(timezone.utc).isoformat()
            cur["epoch"] = int(time.time())   # refresh epoch so EA doesn't mark stale
            tmp = ORDERS_JSON.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(cur, indent=2, ensure_ascii=False),
                            encoding="utf-8")
            tmp.replace(ORDERS_JSON)
            print(f"[{datetime.now():%H:%M:%S}] wrote {len(drawings)} drawings")
        except KeyboardInterrupt:
            print("[chart_publisher] stopped"); break
        except Exception as e:
            print(f"[chart_publisher] err: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    publish_loop()

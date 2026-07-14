"""runtime/footprint_publisher.py — Order-Flow Lite for MT5 chart.

User mandate (2026-05-27): build Footprint-Lite on the EA chart.
MT5 doesn't expose trade-level data so we approximate with the tick rule:
  mid_now > mid_prev  → buy aggressor
  mid_now < mid_prev  → sell aggressor

Then per M1 bar: delta = buy_count - sell_count (volume-weighted by tick_volume).

What gets drawn on the EA chart (merged into friday_brain_orders.json):

  📍 Delta-per-Bar markers
     For the last 20 M1 bars: a colored arrow + text label showing
     the bar's net delta. Green arrowUp for +delta, red arrowDown
     for -delta. Big absolute deltas get bolder text.

  ⚡ Imbalance Markers
     Bars where:
       • |delta| > 2× recent absolute-delta average
       • body% ≥ 50%
       • volume ≥ 150% of average
     Get a special bigger marker labeled "IMB+" or "IMB-".
     These are the institutional-flow signals.

  📊 CVD (Cumulative Volume Delta) line
     Running sum of deltas over last 30 bars. Plotted as a piecewise
     trendline above the price chart (offset +\$30). Slope tells you
     direction of cumulative pressure. DIVERGENCE between CVD slope
     and price slope = high-prob reversal signal.

This process is separate from chart_publisher so each can fail
independently. Both write to the same drawings array (merge by
appending; chart_publisher refreshes the base drawings every 4s,
footprint adds order-flow layer every 5s).
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ORDERS_JSON = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files\friday_brain_orders.json")
SYMBOL = "XAUUSDm"
POLL = 5.0
LOOKBACK_BARS = 20      # how many recent M1 bars to render
CVD_BARS = 30           # CVD line length


def _save(p: Path, obj):
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    tmp.replace(p)


def compute_footprint_drawings():
    """Compute order-flow drawings. Returns a list to APPEND to existing
    chart_publisher drawings (does NOT overwrite them)."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
    except Exception:
        return []

    # Fetch last LOOKBACK + CVD bars
    n_bars = max(LOOKBACK_BARS, CVD_BARS) + 2
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, n_bars)
    if rates is None or len(rates) < 5: return []
    bars = [dict(b._asdict()) if hasattr(b, "_asdict")
            else {k: b[k] for k in b.dtype.names} for b in rates]

    deltas = []
    # Compute delta per bar via tick rule
    for i, bar in enumerate(bars):
        bar_start = int(bar["time"])
        bar_end   = bar_start + 60   # M1 = 60s
        try:
            ticks = mt5.copy_ticks_range(
                SYMBOL,
                datetime.fromtimestamp(bar_start, tz=timezone.utc),
                datetime.fromtimestamp(bar_end,   tz=timezone.utc),
                mt5.COPY_TICKS_ALL,
            )
        except Exception:
            ticks = None
        if ticks is None or len(ticks) < 2:
            deltas.append({"bar_idx": i, "delta": 0, "buy_count": 0,
                            "sell_count": 0, "n_ticks": 0,
                            "bar_time": bar_start})
            continue

        buy_c, sell_c = 0, 0
        prev_mid = None
        for t in ticks:
            try:
                mid = (float(t["bid"]) + float(t["ask"])) / 2
            except Exception:
                try: mid = (t.bid + t.ask) / 2
                except: continue
            if prev_mid is not None:
                if mid > prev_mid:   buy_c += 1
                elif mid < prev_mid: sell_c += 1
            prev_mid = mid
        delta = buy_c - sell_c
        deltas.append({"bar_idx": i, "delta": delta, "buy_count": buy_c,
                        "sell_count": sell_c, "n_ticks": len(ticks),
                        "bar_time": bar_start})

    drawings = []
    n = len(bars)

    # Average absolute delta + volume for imbalance detection
    abs_deltas = [abs(d["delta"]) for d in deltas[-CVD_BARS:] if d["delta"] != 0]
    avg_abs_delta = sum(abs_deltas) / max(1, len(abs_deltas)) if abs_deltas else 0
    vols = [int(b["tick_volume"]) for b in bars[-CVD_BARS:]]
    avg_vol = sum(vols) / max(1, len(vols)) if vols else 0

    # ─── Per-bar delta markers (last LOOKBACK bars only, skip current) ───
    for i in range(n - LOOKBACK_BARS - 1, n - 1):
        if i < 0: continue
        d = deltas[i]
        bar = bars[i]
        bars_ago = n - 1 - i
        body_pct = abs(bar["close"] - bar["open"]) / max(bar["high"] - bar["low"], 1e-9)
        v = int(bar["tick_volume"])

        is_imbalance = (abs(d["delta"]) > 2 * avg_abs_delta and avg_abs_delta > 5
                         and body_pct >= 0.50
                         and v > 1.5 * avg_vol)

        if d["delta"] > 0:
            col = "#00FF66" if not is_imbalance else "#00FF00"
            shape = "arrowUp"
            label = f"+{d['delta']}" + (" IMB+" if is_imbalance else "")
        elif d["delta"] < 0:
            col = "#FF6666" if not is_imbalance else "#FF0000"
            shape = "arrowDown"
            label = f"{d['delta']}" + (" IMB-" if is_imbalance else "")
        else:
            continue

        drawings.append({
            "type": "marker", "bars_ago": bars_ago,
            "shape": shape, "color": col, "label": label,
        })

    # ─── CVD piecewise trendline (above price, offset +\$25) ───
    cvd_offset = 25.0
    cum = 0
    cvd_points = []
    for i in range(n - CVD_BARS - 1, n - 1):
        if i < 0: continue
        cum += deltas[i]["delta"]
        cvd_points.append({"bars_ago": n - 1 - i, "cvd": cum})

    if len(cvd_points) >= 2:
        # Scale CVD to fit price range — find max abs CVD, normalize to ±$10
        max_abs_cvd = max(abs(p["cvd"]) for p in cvd_points) or 1
        scale = 10.0 / max_abs_cvd
        cur_close = bars[-2]["close"]
        cvd_base = cur_close + cvd_offset
        for j in range(len(cvd_points) - 1):
            a, b = cvd_points[j], cvd_points[j+1]
            drawings.append({
                "type": "trendline",
                "from": {"bars_ago": a["bars_ago"], "price": cvd_base + a["cvd"] * scale},
                "to":   {"bars_ago": b["bars_ago"], "price": cvd_base + b["cvd"] * scale},
                "color": "#00FFFF",     # cyan
                "label": "CVD" if j == len(cvd_points)-2 else "",
            })
        # Final CVD value as text label at the rightmost
        final_cvd = cvd_points[-1]["cvd"]
        drawings.append({
            "type": "hline", "price": cvd_base, "color": "#888888",
            "label": f"CVD baseline (CVD now={final_cvd:+d})",
        })

    return drawings, deltas


def merge_into_orders_json(footprint_drawings: list):
    """Read existing orders JSON, append footprint drawings, write back atomically."""
    if not ORDERS_JSON.exists(): return
    try:
        cur = json.loads(ORDERS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return
    existing = cur.get("drawings", []) or []
    # Remove any prior footprint drawings (label starts with our markers)
    keep = [d for d in existing
             if not (d.get("label", "").startswith("CVD")
                     or "IMB" in d.get("label", "")
                     or (d.get("type") == "marker" and
                         (d.get("label", "").startswith("+") or d.get("label", "").startswith("-"))))]
    cur["drawings"] = keep + footprint_drawings
    cur["footprint_ts"] = datetime.now(timezone.utc).isoformat()
    _save(ORDERS_JSON, cur)


def main_loop():
    print(f"[footprint] online · {SYMBOL} · {POLL}s poll · last {LOOKBACK_BARS} bars + CVD{CVD_BARS}")
    while True:
        try:
            drawings, deltas = compute_footprint_drawings()
            if drawings:
                merge_into_orders_json(drawings)
                # Quick summary
                recent = deltas[-5:]
                d_str = " ".join(f"{'+' if d['delta']>0 else ''}{d['delta']}"
                                  for d in recent)
                cum_now = sum(d["delta"] for d in deltas[-CVD_BARS-1:-1])
                print(f"[{datetime.now():%H:%M:%S}] delta last5: {d_str}  CVD={cum_now:+d}")
        except KeyboardInterrupt:
            print("[footprint] stopped"); break
        except Exception as e:
            print(f"[footprint] err: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main_loop()

"""dashboard_server.py — Serves enriched live state on localhost:8765.

GET /api/state  — returns merged JSON: live_state + trade_log + mt5_positions + dna_genes
GET /*          — static files from dashboard/
"""
from __future__ import annotations
import json
import sys
import time
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import urllib.parse

ROOT      = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "dashboard"
LIVE_STATE= DASHBOARD / "qader_live_state.json"
JOURNAL         = ROOT / "logs" / "qader_realtime_loop.jsonl"
LEARNING_JOURNAL= ROOT / "logs" / "live_performance_journal.jsonl"
ARBITRATION_LOG = ROOT / "logs" / "arbitration_decisions.jsonl"
GENE_STORE= ROOT / "data" / "qader" / "dna" / "gene_store_backtest.json"
PORT = 8765

sys.path.insert(0, str(ROOT / "src"))

_cache: dict = {}
_lock = threading.Lock()


def _read_json(p: Path) -> dict:
    try:
        raw = p.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        return json.loads(raw)
    except Exception:
        return {}


def _last_lines(p: Path, n: int = 600) -> list[str]:
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        return text.splitlines()[-n:]
    except Exception:
        return []


def _build_trade_log() -> list[dict]:
    trades = []
    for line in _last_lines(JOURNAL, 1000):
        try:
            rec = json.loads(line)
            if rec.get("event") == "demo_trade_entry":
                trades.append({
                    "time":   rec.get("timestamp", "")[:19].replace("T", " "),
                    "symbol": rec.get("symbol", "?"),
                    "tf":     rec.get("timeframe", "?"),
                    "action": rec.get("action", "?"),
                    "lot":    rec.get("lot", 0),
                    "sl":     rec.get("sl", 0),
                    "tp":     rec.get("tp", 0),
                    "order":  rec.get("order", 0),
                    "deal":   rec.get("deal", 0),
                    "spread": rec.get("spread", 0),
                    "conf":   rec.get("signal_agreement", {}).get("confidence", 0),
                })
        except Exception:
            pass
    return trades[-30:]


def _is_decision_record(rec: dict) -> bool:
    return isinstance(rec, dict) and any(rec.get(k) not in (None, "") for k in ("final_action", "arbiter_result", "execution_status"))


def _latest_decision_record() -> dict:
    for line in reversed(_last_lines(JOURNAL, 800)):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if _is_decision_record(rec):
            return rec
    return {}


def _latest_learning_event() -> dict:
    for line in reversed(_last_lines(LEARNING_JOURNAL, 800)):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("event") in {"dna_learning_applied", "dna_learning_proposal", "dna_learning_error"}:
            return rec
    return {}


def _get_mt5_positions() -> list[dict]:
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return []
        positions = mt5.positions_get() or []
        result = []
        for p in positions:
            result.append({
                "ticket":     int(p.ticket),
                "symbol":     p.symbol,
                "type":       "BUY" if p.type == 0 else "SELL",
                "volume":     p.volume,
                "open_price": round(p.price_open, 5),
                "current":    round(p.price_current, 5),
                "sl":         round(p.sl, 5),
                "tp":         round(p.tp, 5),
                "profit":     round(p.profit, 2),
                "swap":       round(p.swap, 2),
                "magic":      int(p.magic),
                "comment":    str(p.comment or ""),
            })
        return result
    except Exception:
        return []

def _get_mt5_pending_orders() -> list[dict]:
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return []
        orders = mt5.orders_get() or []
        type_names = {
            getattr(mt5, "ORDER_TYPE_BUY_LIMIT", 2): "BUY_LIMIT",
            getattr(mt5, "ORDER_TYPE_SELL_LIMIT", 3): "SELL_LIMIT",
            getattr(mt5, "ORDER_TYPE_BUY_STOP", 4): "BUY_STOP",
            getattr(mt5, "ORDER_TYPE_SELL_STOP", 5): "SELL_STOP",
        }
        result = []
        for o in orders:
            result.append({
                "ticket": int(o.ticket),
                "symbol": o.symbol,
                "type": type_names.get(int(o.type), str(o.type)),
                "volume": o.volume_current,
                "price": round(o.price_open, 5),
                "sl": round(o.sl, 5),
                "tp": round(o.tp, 5),
                "magic": int(o.magic),
                "comment": str(o.comment or ""),
            })
        return result
    except Exception:
        return []


def _get_mt5_tick(symbol: str = "XAUUSDm") -> dict:
    """Get latest tick with bid/ask/volume for order flow approximation."""
    try:
        import MetaTrader5 as mt5
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {}
        return {
            "bid":         round(tick.bid, 5),
            "ask":         round(tick.ask, 5),
            "last":        round(tick.last, 5),
            "volume":      int(tick.volume),
            "volume_real": float(tick.volume_real),
            "spread":      round((tick.ask - tick.bid) * 10000, 1),
            "time":        tick.time,
        }
    except Exception:
        return {}


def _get_dna_genes() -> list[dict]:
    d = _read_json(GENE_STORE)
    result = []
    for g in d.get("genes", []):
        s = g.get("stats", {})
        t = g.get("thresholds", {})
        lp = g.get("live_performance", {})
        result.append({
            "id":          g.get("gene_id", "?"),
            "wr":          f"{s.get('win_rate',0):.1%}",
            "pf":          round(s.get("profit_factor", 0), 2),
            "sharpe":      round(s.get("sharpe", 0), 2),
            "n_trades":    s.get("n_trades", 0),
            "lot_scale":   t.get("lot_scale", 1.0),
            "min_conf":    t.get("min_confidence", 0.70),
            "sl_mult":     t.get("sl_atr_mult", 1.5),
            "tp_mult":     t.get("tp_atr_mult", 3.0),
            "active":      g.get("active", True),
            "live_trades": lp.get("trades", 0),
            "live_wr":     lp.get("bayesian_posterior"),
            "group":       g.get("group", {}),
        })
    return result


def _detect_candle_patterns(bars: list[dict]) -> list[dict]:
    """Detect candlestick patterns on the last N bars. Returns alert list."""
    alerts = []
    if len(bars) < 3:
        return alerts

    def _bar(i):
        b = bars[i]
        o, h, l, c = b["open"], b["high"], b["low"], b["close"]
        body   = abs(c - o)
        rng    = max(h - l, 0.001)
        upper  = h - max(o, c)
        lower  = min(o, c) - l
        return o, h, l, c, body, rng, upper, lower

    for i in range(2, len(bars)):
        o,  h,  l,  c,  body,  rng,  up,  dn  = _bar(i)
        o1, h1, l1, c1, body1, rng1, up1, dn1 = _bar(i - 1)
        o2, h2, l2, c2, body2, rng2, up2, dn2 = _bar(i - 2)
        ts  = bars[i]["time"]
        ts1 = bars[i-1]["time"]

        # ── Bullish Engulfing ─────────────────────────────────────────────
        if c1 < o1 and c > o and c > o1 and o < c1 and body > body1 * 0.8:
            alerts.append({"time": ts, "pattern": "Bullish Engulfing",
                           "bias": "BUY", "strength": "strong",
                           "desc": f"شمعة ابتلاع صاعدة — الشمعة الحالية تغطي الهابطة السابقة بالكامل"})

        # ── Bearish Engulfing ─────────────────────────────────────────────
        if c1 > o1 and c < o and c < o1 and o > c1 and body > body1 * 0.8:
            alerts.append({"time": ts, "pattern": "Bearish Engulfing",
                           "bias": "SELL", "strength": "strong",
                           "desc": "شمعة ابتلاع هابطة — انعكاس محتمل للأسفل"})

        # ── Hammer / Bullish Pin Bar ──────────────────────────────────────
        if dn > body * 2.5 and up < body * 0.5 and dn > rng * 0.55:
            bias = "BUY" if c >= o else "NEUTRAL"
            alerts.append({"time": ts, "pattern": "Hammer / Pin Bar",
                           "bias": bias, "strength": "medium",
                           "desc": "ذيل سفلي طويل — رفض الأسعار المنخفضة، ضغط شراء"})

        # ── Shooting Star / Bearish Pin Bar ──────────────────────────────
        if up > body * 2.5 and dn < body * 0.5 and up > rng * 0.55:
            bias = "SELL" if c <= o else "NEUTRAL"
            alerts.append({"time": ts, "pattern": "Shooting Star",
                           "bias": bias, "strength": "medium",
                           "desc": "ذيل علوي طويل — رفض الأسعار المرتفعة، ضغط بيع"})

        # ── Doji ─────────────────────────────────────────────────────────
        if body < rng * 0.1:
            alerts.append({"time": ts, "pattern": "Doji",
                           "bias": "NEUTRAL", "strength": "weak",
                           "desc": "دوجي — تردد السوق، انتظر تأكيد"})

        # ── Bullish Marubozu (momentum candle) ───────────────────────────
        if c > o and body > rng * 0.85 and bars[i]["volume"] > bars[i-1]["volume"] * 1.3:
            alerts.append({"time": ts, "pattern": "Bullish Marubozu",
                           "bias": "BUY", "strength": "strong",
                           "desc": "شمعة صعود قوية بحجم مرتفع — زخم شراء واضح"})

        # ── Bearish Marubozu ─────────────────────────────────────────────
        if c < o and body > rng * 0.85 and bars[i]["volume"] > bars[i-1]["volume"] * 1.3:
            alerts.append({"time": ts, "pattern": "Bearish Marubozu",
                           "bias": "SELL", "strength": "strong",
                           "desc": "شمعة هبوط قوية بحجم مرتفع — زخم بيع واضح"})

        # ── Inside Bar ───────────────────────────────────────────────────
        if h < h1 and l > l1:
            alerts.append({"time": ts, "pattern": "Inside Bar",
                           "bias": "NEUTRAL", "strength": "weak",
                           "desc": "شمعة داخلية — ضغط وتجميع، انتظر الكسر"})

        # ── Three White Soldiers ─────────────────────────────────────────
        if i >= 2 and c > o and c1 > o1 and c2 > o2 and c > c1 > c2 and body > rng*0.5 and body1 > rng1*0.5:
            alerts.append({"time": ts, "pattern": "Three White Soldiers",
                           "bias": "BUY", "strength": "strong",
                           "desc": "ثلاثة جنود بيضاء — زخم صاعد قوي متواصل"})

        # ── Three Black Crows ─────────────────────────────────────────────
        if i >= 2 and c < o and c1 < o1 and c2 < o2 and c < c1 < c2 and body > rng*0.5 and body1 > rng1*0.5:
            alerts.append({"time": ts, "pattern": "Three Black Crows",
                           "bias": "SELL", "strength": "strong",
                           "desc": "ثلاثة غربان سود — زخم هابط قوي متواصل"})

    # Return only last 20 unique alerts (by time+pattern)
    seen = set()
    unique = []
    for a in reversed(alerts):
        key = (a["time"], a["pattern"])
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return list(reversed(unique))[-20:]


def _get_recent_bars(symbol="XAUUSDm", tf_str="M1", n=60) -> tuple[list[dict], list[dict]]:
    """Get recent OHLCV bars + candlestick pattern alerts."""
    try:
        import MetaTrader5 as mt5
        TF_MAP = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
                  "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
        tf   = TF_MAP.get(tf_str, mt5.TIMEFRAME_M1)
        bars = mt5.copy_rates_from_pos(symbol, tf, 0, n)
        if bars is None:
            return [], []
        result = []
        for b in bars:
            o, h, l, c = float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])
            body     = c - o
            rng      = max(h - l, 0.001)
            vol      = int(b["tick_volume"])
            buy_pct  = 0.5 + min(0.45, abs(body) / rng * 0.45) if body > 0 else 0.5 - min(0.45, abs(body) / rng * 0.45)
            buy_vol  = int(vol * buy_pct)
            sell_vol = vol - buy_vol
            result.append({
                "time":     int(b["time"]),
                "open":     round(o, 3), "high": round(h, 3),
                "low":      round(l, 3), "close": round(c, 3),
                "volume":   vol,
                "buy_vol":  buy_vol, "sell_vol": sell_vol,
                "delta":    buy_vol - sell_vol,
                "bullish":  c >= o,
                "body_pct": round(abs(body) / rng, 3),
            })
        patterns = _detect_candle_patterns(result)
        return result[-30:], patterns
    except Exception:
        return [], []


def _get_fvg_zones(symbol: str = "XAUUSDm", tf_str: str = "M5", n: int = 120) -> list[dict]:
    """Detect open Fair Value Gap zones from recent bars (correct 3-candle gap logic)."""
    try:
        import MetaTrader5 as mt5
        TF_MAP = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
                  "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
        tf   = TF_MAP.get(tf_str, mt5.TIMEFRAME_M5)
        bars = mt5.copy_rates_from_pos(symbol, tf, 0, n)
        if bars is None or len(bars) < 3:
            return []
        current = float(bars[-1]["close"])
        zones   = []
        for i in range(2, len(bars)):
            h   = float(bars[i]["high"])
            l   = float(bars[i]["low"])
            h2  = float(bars[i - 2]["high"])
            l2  = float(bars[i - 2]["low"])
            ts  = int(bars[i]["time"])
            # Bullish FVG: candle[i].low > candle[i-2].high  →  gap = [i-2 high, i low]
            if l > h2:
                filled = current < h2  # price dropped below gap bottom
                zones.append({"type": "bull_fvg", "low": round(h2, 3),
                               "high": round(l, 3), "filled": filled,
                               "label": "Bull FVG", "time": ts})
            # Bearish FVG: candle[i].high < candle[i-2].low  →  gap = [i high, i-2 low]
            if h < l2:
                filled = current > l2  # price rose above gap top
                zones.append({"type": "bear_fvg", "low": round(h, 3),
                               "high": round(l2, 3), "filled": filled,
                               "label": "Bear FVG", "time": ts})
        open_zones = [z for z in zones if not z["filled"]]
        return open_zones[-10:]
    except Exception:
        return []


def _get_session_info() -> dict:
    """Return current session label + per-session gene stats."""
    import datetime
    hour = datetime.datetime.utcnow().hour
    if 0 <= hour < 7:
        session = "asia"
    elif 7 <= hour < 12:
        session = "london"
    elif 12 <= hour < 16:
        session = "overlap"
    elif 16 <= hour < 21:
        session = "ny"
    else:
        session = "off"

    genes = _get_dna_genes()
    by_session: dict = {}
    for g in genes:
        grp = g.get("group", {})
        s   = grp.get("session", "unknown") if isinstance(grp, dict) else "unknown"
        if s not in by_session:
            by_session[s] = {"genes": [], "avg_wr": 0.0, "active": 0}
        by_session[s]["genes"].append(g["id"])
        by_session[s]["active"] += 1 if g.get("active") else 0
        try:
            by_session[s]["avg_wr"] = round(
                (by_session[s]["avg_wr"] * (len(by_session[s]["genes"]) - 1) +
                 float(g["wr"].strip("%")) / 100) / len(by_session[s]["genes"]), 3)
        except Exception:
            pass

    return {"current": session, "utc_hour": hour, "by_session": by_session}


def _latest_arbitration() -> dict:
    for line in reversed(_last_lines(ARBITRATION_LOG, 50)):
        try:
            return json.loads(line)
        except Exception:
            continue
    return {}


def build_enriched_state() -> dict:
    state = _read_json(LIVE_STATE)
    latest_record = state.get("latest_record") or {}
    latest_decision = _latest_decision_record()
    state["latest_decision_record"] = latest_decision
    state["display_record"] = latest_record if _is_decision_record(latest_record) else latest_decision or latest_record
    state["learning_state"] = state.get("learning_state") or _latest_learning_event()
    state["trade_log"]     = _build_trade_log()
    state["mt5_positions"] = _get_mt5_positions()
    state["mt5_pending_orders"] = _get_mt5_pending_orders()
    state["dna_genes"]     = _get_dna_genes()
    state["tick"]          = _get_mt5_tick()
    bars, patterns         = _get_recent_bars(n=80)
    state["order_flow"]    = bars
    state["candle_alerts"] = patterns
    bars_m5, _             = _get_recent_bars(tf_str="M5", n=60)
    bars_m15, _            = _get_recent_bars(tf_str="M15", n=50)
    bars_h1, _             = _get_recent_bars(tf_str="H1", n=40)
    state["bars_m5"]       = bars_m5
    state["bars_m15"]      = bars_m15
    state["bars_h1"]       = bars_h1
    state["fvg_zones"]     = _get_fvg_zones()
    state["fvg_m1"]        = _get_fvg_zones(tf_str="M1", n=80)
    state["fvg_m15"]       = _get_fvg_zones(tf_str="M15", n=60)
    state["session_info"]  = _get_session_info()
    state["arbitration"]   = _latest_arbitration()
    state["server_ts"]     = time.strftime("%Y-%m-%dT%H:%M:%S")
    return state


def _get_footprint_data(symbol: str = "XAUUSDm", tf_str: str = "M1", n_bars: int = 20, tick_size: float = 0.1) -> dict:
    """Build Footprint + Volume Profile + Big Trades + Cumulative Delta from raw ticks."""
    try:
        import MetaTrader5 as mt5
        from datetime import datetime, timezone

        TF_MAP = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
                  "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
        TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}
        tf = TF_MAP.get(tf_str, mt5.TIMEFRAME_M1)
        bar_seconds = TF_SECONDS.get(tf_str, 60)

        # Adjust tick_size per timeframe
        if tf_str in ("M15", "H1"):
            tick_size = 0.5
        elif tf_str == "M5":
            tick_size = 0.2

        bars = mt5.copy_rates_from_pos(symbol, tf, 0, n_bars + 1)
        if bars is None or len(bars) < 2:
            return {"bars": [], "volume_profile": [], "big_trades": [], "cumulative_delta": [], "poc": 0, "vah": 0, "val": 0}

        from_ts = int(bars[0]["time"])
        from_dt = datetime.fromtimestamp(from_ts, tz=timezone.utc)
        ticks = mt5.copy_ticks_from(symbol, from_dt, 200000, mt5.COPY_TICKS_ALL)
        if ticks is None:
            ticks = []

        # Index ticks by second for fast lookup
        tick_list = [(int(t["time"]), float(t["bid"]), float(t["ask"]), int(t["time_msc"])) for t in ticks]

        all_levels: dict[float, float] = {}
        footprint_bars = []
        cum_delta_val = 0.0
        cum_delta = []

        # Big trade detection: rolling average tick count per bar
        bar_tick_counts = []

        for i in range(len(bars) - 1):
            bar_start = int(bars[i]["time"])
            bar_end   = int(bars[i]["time"]) + bar_seconds
            bar       = bars[i]

            # Filter ticks for this bar by timestamp
            bar_ticks_raw = [(ts, bid, ask, ms) for ts, bid, ask, ms in tick_list if bar_start <= ts < bar_end]

            levels: dict[float, dict] = {}
            bar_up = 0.0
            bar_dn = 0.0
            prev_bid = None

            for j, (ts, bid, ask, ms) in enumerate(bar_ticks_raw):
                lvl = round(round(bid / tick_size) * tick_size, 4)
                if lvl not in levels:
                    levels[lvl] = {"up": 0.0, "dn": 0.0, "cnt": 0}
                levels[lvl]["cnt"] += 1

                if prev_bid is not None:
                    if bid > prev_bid:
                        levels[lvl]["up"] += 1.0
                        bar_up += 1.0
                    elif bid < prev_bid:
                        levels[lvl]["dn"] += 1.0
                        bar_dn += 1.0
                    else:
                        levels[lvl]["up"] += 0.5
                        levels[lvl]["dn"] += 0.5
                        bar_up += 0.5
                        bar_dn += 0.5
                prev_bid = bid

                # Volume profile accumulation
                if lvl not in all_levels:
                    all_levels[lvl] = 0.0
                all_levels[lvl] += 1.0

            # Fallback: synthetic from bar body if no ticks
            total_ticks = int(bar["tick_volume"])
            if not bar_ticks_raw and total_ticks > 0:
                o, h, l, c = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])
                body = abs(c - o)
                rng  = max(h - l, 0.001)
                bull = c >= o
                buy_frac = 0.5 + min(0.45, (body / rng) * 0.45) if bull else 0.5 - min(0.45, (body / rng) * 0.45)
                bar_up = round(total_ticks * buy_frac)
                bar_dn = total_ticks - bar_up
                for price in [round(o + (h - o) * k / 4, 4) for k in range(5)]:
                    lvl = round(round(price / tick_size) * tick_size, 4)
                    if lvl not in levels:
                        levels[lvl] = {"up": 0.0, "dn": 0.0, "cnt": 0}
                    levels[lvl]["up"] += bar_up / 5.0
                    levels[lvl]["dn"] += bar_dn / 5.0
                    levels[lvl]["cnt"] += total_ticks // 5
                    if lvl not in all_levels:
                        all_levels[lvl] = 0.0
                    all_levels[lvl] += total_ticks / 5.0

            delta = bar_up - bar_dn
            cum_delta_val += delta

            # POC for this bar
            poc_lvl = max(levels, key=lambda k: levels[k]["up"] + levels[k]["dn"]) if levels else None

            # Imbalances: ratio ≥ 3:1
            imbalances = []
            for lvl, v in levels.items():
                total = v["up"] + v["dn"]
                if total >= 3:
                    ratio = v["up"] / total
                    if ratio >= 0.75:
                        imbalances.append({"price": lvl, "type": "buy", "ratio": round(ratio, 2)})
                    elif ratio <= 0.25:
                        imbalances.append({"price": lvl, "type": "sell", "ratio": round(1 - ratio, 2)})

            bar_tick_counts.append(len(bar_ticks_raw) or total_ticks)
            footprint_bars.append({
                "time": bar_start,
                "open": round(float(bar["open"]), 4),
                "high": round(float(bar["high"]), 4),
                "low":  round(float(bar["low"]), 4),
                "close": round(float(bar["close"]), 4),
                "tick_volume": int(bar["tick_volume"]),
                "bullish": float(bar["close"]) >= float(bar["open"]),
                "up": round(bar_up, 1),
                "dn": round(bar_dn, 1),
                "delta": round(delta, 1),
                "poc": poc_lvl,
                "levels": sorted(
                    [{"p": k, "u": round(v["up"], 1), "d": round(v["dn"], 1), "c": v["cnt"]}
                     for k, v in levels.items()],
                    key=lambda x: x["p"], reverse=True
                )[:30],
                "imbalances": imbalances,
                "cum_delta": round(cum_delta_val, 1),
            })
            cum_delta.append({"time": bar_start, "delta": round(delta, 1), "cum": round(cum_delta_val, 1)})

        # ── Big Trades: bars with tick count > 1.4x rolling avg OR strong delta ──
        big_trades = []
        all_tv = [fp["tick_volume"] for fp in footprint_bars if fp["tick_volume"] > 0]
        global_avg = sum(all_tv) / len(all_tv) if all_tv else 1
        for i, fp in enumerate(footprint_bars):
            window = bar_tick_counts[max(0, i-8):i+1]
            avg = sum(window) / len(window) if window else global_avg
            tv  = fp["tick_volume"]
            abs_delta = abs(fp["delta"])
            is_big_vol   = tv > avg * 1.4 and tv >= 20
            is_big_delta = abs_delta > 0 and (abs_delta / max(fp["up"]+fp["dn"], 1)) > 0.65 and tv >= 15
            if is_big_vol or is_big_delta:
                big_trades.append({
                    "time":      fp["time"],
                    "price":     fp["close"],
                    "volume":    tv,
                    "delta":     fp["delta"],
                    "direction": "BUY" if fp["delta"] >= 0 else "SELL",
                    "multiple":  round(tv / max(avg, 1), 1),
                    "reason":    "vol_spike" if is_big_vol else "delta_dom",
                })

        # ── Volume Profile (session) ──
        total_vol = sum(all_levels.values()) or 1
        poc_price = max(all_levels, key=lambda k: all_levels[k]) if all_levels else 0.0

        # Value Area 70% from POC outward
        sorted_by_vol = sorted(all_levels.items(), key=lambda x: x[1], reverse=True)
        va_vol, va_target = 0.0, total_vol * 0.70
        va_set: set[float] = set()
        for price, vol in sorted_by_vol:
            va_vol += vol
            va_set.add(price)
            if va_vol >= va_target:
                break
        vah = max(va_set) if va_set else poc_price
        val = min(va_set) if va_set else poc_price

        vp = [{"price": k, "vol": round(v, 1), "pct": round(v / total_vol * 100, 2), "va": k in va_set}
              for k, v in sorted(all_levels.items(), key=lambda x: x[0])]

        return {
            "bars":             footprint_bars,
            "volume_profile":   vp,
            "big_trades":       big_trades[-20:],
            "cumulative_delta": cum_delta,
            "poc":              poc_price,
            "vah":              vah,
            "val":              val,
            "total_vol":        round(total_vol, 1),
            "tick_size":        tick_size,
            "trade_markers":    _get_trade_markers(from_ts),
        }
    except Exception as exc:
        return {"error": str(exc), "bars": [], "volume_profile": [], "big_trades": [], "cumulative_delta": []}


def _get_trade_markers(from_ts: int) -> list[dict]:
    """Read recent trade entries/exits from journal for chart markers."""
    markers = []
    try:
        with LEARNING_JOURNAL.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ev = rec.get("event", "")
                if ev not in ("demo_trade_entry", "demo_trade_exit"):
                    continue
                # parse timestamp
                ts_str = rec.get("timestamp", "")
                try:
                    from datetime import datetime, timezone
                    ts = int(datetime.fromisoformat(ts_str).timestamp()) if ts_str else 0
                except Exception:
                    ts = 0
                if ts < from_ts:
                    continue
                if ev == "demo_trade_entry":
                    markers.append({
                        "time": ts,
                        "type": "entry",
                        "direction": rec.get("action", ""),
                        "price": rec.get("sl", 0),   # we'll use open price proxy
                        "sl": rec.get("sl", 0),
                        "tp": rec.get("tp", 0),
                        "lot": rec.get("lot", 0.01),
                        "ticket": rec.get("order", 0),
                    })
                else:
                    markers.append({
                        "time": ts,
                        "type": "exit",
                        "direction": rec.get("side", ""),
                        "price": rec.get("entry_price", 0),
                        "profit": rec.get("profit", 0),
                        "won": rec.get("won", False),
                        "ticket": rec.get("ticket", 0),
                    })
    except Exception:
        pass
    return markers[-30:]


def refresh_cache():
    while True:
        try:
            data = build_enriched_state()
            with _lock:
                _cache["state"] = data
                _cache["ts"]    = time.time()
        except Exception:
            pass
        time.sleep(0.25)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/state":
            with _lock:
                data = _cache.get("state") or build_enriched_state()
            body = json.dumps(data, ensure_ascii=False, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/tick":
            with _lock:
                st = _cache.get("state") or {}
            _tk  = st.get("tick") or {}
            _lr  = st.get("latest_record") or {}
            _lp  = st.get("loop") or {}
            tick = {
                "bid":        _tk.get("bid",  _lr.get("bid",  0)),
                "ask":        _tk.get("ask",  _lr.get("ask",  0)),
                "spread":     _lr.get("spread", _tk.get("spread", 0)),
                "signal":     _lr.get("arbiter_result", "HOLD"),
                "confidence": _lr.get("confidence", 0),
                "cycle":      _lp.get("cycle_count", _lr.get("cycle_number", 0)),
                "ts":         _lr.get("timestamp", ""),
                "positions":  _lr.get("open_positions", 0),
            }
            body = json.dumps(tick).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/footprint":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            tf  = qs.get("tf",  ["M1"])[0]
            sym = qs.get("sym", ["XAUUSDm"])[0]
            n   = int(qs.get("n", ["20"])[0])
            data = _get_footprint_data(sym, tf, n)
            body = json.dumps(data, ensure_ascii=False, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self._cors()
            self.end_headers()
            try:
                while True:
                    with _lock:
                        data = _cache.get("state") or build_enriched_state()
                    body = json.dumps(data, ensure_ascii=False, default=str)
                    self.wfile.write(f"event: state\ndata: {body}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.25)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            return

        # Static file from dashboard/
        target = DASHBOARD / path.lstrip("/")
        if not target.exists() or not target.is_file():
            target = DASHBOARD / "qader_live_dashboard.html"
        try:
            body = target.read_bytes()
        except Exception:
            self.send_response(404)
            self.end_headers()
            return
        ct = "text/html" if target.suffix == ".html" else \
             "application/javascript" if target.suffix == ".js" else \
             "text/css" if target.suffix == ".css" else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()


if __name__ == "__main__":
    t = threading.Thread(target=refresh_cache, daemon=True)
    t.start()
    time.sleep(0.5)  # let cache warm up

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[Dashboard] http://localhost:{PORT}/qader_live_dashboard.html")
    print(f"[Dashboard] API:  http://localhost:{PORT}/api/state")
    print(f"[Dashboard] SSE:  http://localhost:{PORT}/api/stream")
    print(f"[Dashboard] Data refresh: 0.25s cache | 0.25s SSE | /api/tick fast-lane | Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Dashboard] Stopped.")

"""chart_drawings.py — Build dict objects for the Python → MT5 chart bridge.

Each builder returns one (or more) drawing dicts conforming to the schema in
`docs/smc/02_DRAWING_BRIDGE.md`. The EA's `DrawingRenderer.mqh` consumes the
list from `brain.json["drawings"]` and renders MQL5 chart objects.

IDs are deterministic (MD5 of the logical key) so a pattern re-published on
the next tick reuses the same MQL5 object name — updates in place, no flicker.

All builders are pure functions; they don't touch MT5 or the filesystem.
"""
from __future__ import annotations

import hashlib
import time
from typing import Iterable, Optional


Side = str  # "bull" | "bear" | "long" | "short"


# ─── ID hashing ──────────────────────────────────────────────────
def _id(prefix: str, *parts) -> str:
    raw = "|".join(str(p) for p in parts)
    short = hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{short}"


def _now() -> int:
    return int(time.time())


def _envelope(id_: str, type_: str, symbol: str, tf: Optional[str] = None,
              ttl_sec: int = 86400) -> dict:
    env: dict = {
        "id":         id_,
        "type":       type_,
        "symbol":     symbol,
        "created_at": _now(),
        "ttl_sec":    ttl_sec,
        "style":      {},
        "meta":       {},
    }
    if tf is not None:
        env["tf"] = tf
    return env


# ─── SMC pattern drawings ────────────────────────────────────────
def draw_order_block(symbol: str, tf: str, ts_start: int, ts_end: int,
                     price_high: float, price_low: float,
                     side: Side, status: str = "active") -> dict:
    d = _envelope(_id("r_smc_ob", symbol, tf, ts_start, side),
                  "rectangle", symbol, tf)
    d["ts_start"]   = int(ts_start)
    d["ts_end"]     = int(ts_end)
    d["price_high"] = float(price_high)
    d["price_low"]  = float(price_low)
    d["style"] = {
        "color":       "#26A69A" if side == "bull" else "#EF5350",
        "width":       1,
        "line_style":  "solid",
        "fill":        True,
        "transparent": 90 if status in ("mitigated", "filled") else 70,
        "zorder":      0,
    }
    d["meta"] = {"pattern": "order_block", "side": side, "status": status}
    return d


def draw_fvg(symbol: str, tf: str, ts_start: int, ts_end: int,
             gap_high: float, gap_low: float,
             side: Side, status: str = "open") -> dict:
    d = _envelope(_id("r_smc_fvg", symbol, tf, ts_start, side),
                  "rectangle", symbol, tf)
    d["ts_start"]   = int(ts_start)
    d["ts_end"]     = int(ts_end)
    d["price_high"] = float(gap_high)
    d["price_low"]  = float(gap_low)
    d["style"] = {
        "color":       "#42A5F5" if side == "bull" else "#FF7043",
        "width":       0,
        "line_style":  "solid",
        "fill":        True,
        "transparent": 92 if status in ("filled", "mitigated") else 80,
        "zorder":      0,
    }
    d["meta"] = {"pattern": "fvg", "side": side, "status": status}
    return d


def draw_bos(symbol: str, tf: str, ts_break: int, level: float, side: Side,
             span_seconds: int = 3600) -> dict:
    d = _envelope(_id("t_bos", symbol, tf, ts_break, side),
                  "trendline", symbol, tf)
    d["ts1"]    = int(ts_break - span_seconds)
    d["ts2"]    = int(ts_break + span_seconds)
    d["price1"] = float(level)
    d["price2"] = float(level)
    d["label"]  = f"BOS {side}"
    d["style"] = {
        "color":      "#66BB6A" if side == "bull" else "#EF5350",
        "width":      2,
        "line_style": "solid",
        "zorder":     2,
    }
    d["meta"] = {"pattern": "bos", "side": side}
    return d


def draw_choch(symbol: str, tf: str, ts_break: int, level: float, side: Side,
               span_seconds: int = 3600) -> dict:
    d = _envelope(_id("t_choch", symbol, tf, ts_break, side),
                  "trendline", symbol, tf)
    d["ts1"]    = int(ts_break - span_seconds)
    d["ts2"]    = int(ts_break + span_seconds)
    d["price1"] = float(level)
    d["price2"] = float(level)
    d["label"]  = f"CHoCH {side}"
    d["style"] = {
        "color":      "#FFCA28",
        "width":      3,
        "line_style": "dash",
        "zorder":     3,
    }
    d["meta"] = {"pattern": "choch", "side": side}
    return d


def draw_liquidity_sweep(symbol: str, tf: str, ts: int, level: float,
                         direction: Side) -> dict:
    d = _envelope(_id("a_sweep", symbol, tf, ts, direction),
                  "arrow", symbol, tf)
    d["ts"]         = int(ts)
    d["price"]      = float(level)
    d["arrow_code"] = 251 if direction == "bear" else 233
    d["anchor"]     = "bottom" if direction == "bull" else "top"
    d["style"] = {"color": "#FFA726", "width": 2, "zorder": 4}
    d["meta"]  = {"category": "liquidity_sweep", "direction": direction}
    return d


def draw_idm(symbol: str, tf: str, ts_taken: int, level: float) -> dict:
    d = _envelope(_id("h_idm", symbol, tf, ts_taken), "hline", symbol, tf)
    d["price"] = float(level)
    d["label"] = "IDM"
    d["style"] = {"color": "#BA68C8", "width": 1, "line_style": "dot", "zorder": 1}
    d["meta"]  = {"category": "idm"}
    return d


def draw_liq_pool(symbol: str, tf: str, level: float, strength: int = 1,
                  side: str = "above") -> dict:
    """Equal-highs/lows pool as a horizontal line."""
    d = _envelope(_id("h_liq", symbol, tf, level, side), "hline", symbol, tf)
    d["price"] = float(level)
    d["label"] = f"LIQ x{strength}" if strength > 1 else "LIQ"
    d["style"] = {"color": "#FFA726", "width": 1, "line_style": "dash", "zorder": 1}
    d["meta"]  = {"category": "liquidity", "side": side, "strength": int(strength)}
    return d


# ─── Trade overlays ─────────────────────────────────────────────
def draw_entry_marker(symbol: str, ts: int, price: float, side: Side,
                      reason_short: str = "") -> dict:
    d = _envelope(_id("a_entry", symbol, ts, side), "arrow", symbol)
    d["ts"]         = int(ts)
    d["price"]      = float(price)
    d["arrow_code"] = 233 if side in ("long", "bull", "BUY") else 234
    d["anchor"]     = "bottom" if side in ("long", "bull", "BUY") else "top"
    d["style"] = {
        "color": "#00E676" if side in ("long", "bull", "BUY") else "#FF1744",
        "width": 3,
        "zorder": 5,
    }
    d["meta"] = {"category": "entry", "side": side, "reason": reason_short}
    return d


def draw_sl_tp_zone(symbol: str, entry: float, sl: float, tp: float,
                    side: Side, ts: Optional[int] = None) -> list[dict]:
    ts = ts or _now()
    tag = (symbol, side, ts)
    sl_d = _envelope(_id("h_sl", *tag), "hline", symbol)
    sl_d["price"] = float(sl); sl_d["label"] = "SL"
    sl_d["style"] = {"color": "#FF1744", "width": 2, "line_style": "solid", "zorder": 4}
    sl_d["meta"]  = {"category": "sl", "side": side}

    tp_d = _envelope(_id("h_tp", *tag), "hline", symbol)
    tp_d["price"] = float(tp); tp_d["label"] = "TP"
    tp_d["style"] = {"color": "#00E676", "width": 2, "line_style": "solid", "zorder": 4}
    tp_d["meta"]  = {"category": "tp", "side": side}

    en_d = _envelope(_id("h_entry", *tag), "hline", symbol)
    en_d["price"] = float(entry); en_d["label"] = "ENTRY"
    en_d["style"] = {"color": "#FFFFFF", "width": 1, "line_style": "dot", "zorder": 4}
    en_d["meta"]  = {"category": "entry_level", "side": side}
    return [en_d, sl_d, tp_d]


def draw_narrative_label(symbol: str, ts: int, price: float,
                         text_ar: str) -> dict:
    d = _envelope(_id("lbl_narr", symbol, ts), "label", symbol)
    d["ts"]     = int(ts)
    d["price"]  = float(price)
    d["text"]   = text_ar
    d["anchor"] = "left_lower"
    d["style"]  = {"color": "#FFFFFF", "width": 9, "zorder": 10}
    d["meta"]   = {"font": "Tahoma", "rtl": True}
    return d


def draw_fib(symbol: str, tf: str, ts1: int, price1: float,
             ts2: int, price2: float,
             levels: Iterable[float] = (0.0, 0.236, 0.382, 0.5, 0.618, 0.705, 0.79, 1.0)
             ) -> dict:
    d = _envelope(_id("fib", symbol, tf, ts1, ts2), "fib_levels", symbol, tf)
    d["ts1"]    = int(ts1)
    d["price1"] = float(price1)
    d["ts2"]    = int(ts2)
    d["price2"] = float(price2)
    d["levels"] = [float(x) for x in levels]
    d["style"]  = {"color": "#AB47BC", "width": 1, "line_style": "dot", "zorder": 1}
    d["meta"]   = {"category": "fibonacci"}
    return d


# ─── SMC snapshot → drawings list ───────────────────────────────
def drawings_from_smc_snapshot(symbol: str, tf: str, snap: dict) -> list[dict]:
    """Convert the dict returned by `smc_engine.compute_smc_snapshot` into a
    drawings array. Used by `r_executor._collect_drawings`.

    Only adds drawings that have anchor data; tolerates missing keys.
    """
    out: list[dict] = []
    if not snap: return out
    ob_above = snap.get("fresh_ob_above")
    if ob_above:
        out.append(draw_order_block(symbol, tf,
            ts_start=int(ob_above.get("created_at", _now())),
            ts_end=int(ob_above.get("created_at", _now())) + 3600,
            price_high=float(ob_above["top"]),
            price_low=float(ob_above["bottom"]),
            side="bear",
            status="active" if not ob_above.get("tested_count") else "mitigated"))
    ob_below = snap.get("fresh_ob_below")
    if ob_below:
        out.append(draw_order_block(symbol, tf,
            ts_start=int(ob_below.get("created_at", _now())),
            ts_end=int(ob_below.get("created_at", _now())) + 3600,
            price_high=float(ob_below["top"]),
            price_low=float(ob_below["bottom"]),
            side="bull",
            status="active" if not ob_below.get("tested_count") else "mitigated"))
    bos = snap.get("last_bos")
    if bos:
        out.append(draw_bos(symbol, tf,
            ts_break=int(bos.get("created_at", _now())),
            level=float(bos["level"]),
            side="bull" if bos["direction"] == "UP" else "bear"))
    ch = snap.get("last_choch")
    if ch:
        out.append(draw_choch(symbol, tf,
            ts_break=int(ch.get("created_at", _now())),
            level=float(ch["level"]),
            side="bull" if ch["direction"] == "UP" else "bear"))
    sw = snap.get("recent_liq_sweep")
    if sw:
        out.append(draw_liquidity_sweep(symbol, tf,
            ts=int(sw.get("created_at", _now())),
            level=float(sw["level"]),
            direction="bull" if sw["side"] == "SELL" else "bear"))
    idm = snap.get("idm_status")
    if idm:
        out.append(draw_idm(symbol, tf,
            ts_taken=int(idm.get("created_at", _now())),
            level=float(idm["level"])))
    for px in snap.get("liq_above", []):
        out.append(draw_liq_pool(symbol, tf, float(px), side="above"))
    for px in snap.get("liq_below", []):
        out.append(draw_liq_pool(symbol, tf, float(px), side="below"))
    return out


# ─── Drawings cap + TTL filter (called by r_executor) ───────────
def filter_and_cap(drawings: list[dict], max_per_symbol: int = 50,
                   stale_after_sec: int = 6 * 3600) -> list[dict]:
    now = _now()
    fresh = [d for d in drawings
             if (now - d.get("created_at", now)) < max(d.get("ttl_sec", stale_after_sec),
                                                       stale_after_sec) is False
             or (now - d.get("created_at", now)) < stale_after_sec]
    # Simpler equivalent — only keep recent
    fresh = [d for d in drawings
             if (now - d.get("created_at", now)) < stale_after_sec]
    per_symbol: dict[str, list[dict]] = {}
    for d in fresh:
        per_symbol.setdefault(d["symbol"], []).append(d)
    out: list[dict] = []
    for sym, items in per_symbol.items():
        items.sort(key=lambda d: d.get("created_at", 0), reverse=True)
        out.extend(items[:max_per_symbol])
    return out

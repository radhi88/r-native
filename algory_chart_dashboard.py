"""
algory_chart_dashboard.py — Algory Visual Intelligence Dashboard.

Features:
  - Williams Fractals + future projection line toward key levels
  - Daily / Weekly / Monthly / Pivot / H4 swing levels as chart lines
  - Prediction tracking: saves each forecast, checks if price hits target
  - Self-improvement: accuracy rate fed back → adjusts projection confidence
  - Connects chart brain ↔ runner brain ↔ gene fitness brain
  - Live 5s refresh | TF switcher | Entry/SL/TP price lines
"""
from __future__ import annotations
import json, math, sys
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\Radhi\MT5")
SRC  = ROOT / "src"
DATA = Path(r"C:\Users\Radhi\AppData\Local\FRIDAY")
PRED_FILE = DATA / "algory_predictions.json"

for p in (str(SRC), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

app = FastAPI(title="Algory Chart Dashboard")

# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _atr_from_df(df, period: int = 14) -> float:
    """ATR helper — works with both uppercase and lowercase column names."""
    try:
        h = df["high"]  if "high"  in df.columns else df["High"]
        l = df["low"]   if "low"   in df.columns else df["Low"]
        c = df["close"] if "close" in df.columns else df["Close"]
        tr = (h-l).combine((h-c.shift()).abs(), max).combine((l-c.shift()).abs(), max)
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])
    except Exception:
        return 0.0


def _f(v, default=0.0):
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def _fetch_bars(symbol: str, timeframe: str, n: int = 250):
    try:
        import MetaTrader5 as mt5
        TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
              "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
              "H1": mt5.TIMEFRAME_H1,  "H4": mt5.TIMEFRAME_H4,
              "D1": mt5.TIMEFRAME_D1}
        mt5.initialize()
        rates = mt5.copy_rates_from_pos(symbol, TF[timeframe], 0, n)
        if rates is None or len(rates) == 0:
            return None
        import pandas as pd
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time")
        df = df.rename(columns={"tick_volume": "volume"})[
            ["open", "high", "low", "close", "volume"]
        ].copy()
        return df
    except Exception:
        return None


def _active_genomes() -> dict:
    reg = DATA / "active_genomes.json"
    if not reg.exists():
        return {}
    try:
        return json.loads(reg.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
#  Fractal Analysis  (Williams 5-bar fractals)
# ─────────────────────────────────────────────────────────────────────────────

def _calc_fractals(df, n: int = 2) -> dict:
    """
    Returns last 12 bullish (support) and bearish (resistance) fractal points.
    Bullish fractal = bar whose low is the lowest of (2n+1) bars centred on it.
    Bearish fractal = bar whose high is the highest of (2n+1) bars centred on it.
    """
    highs  = df["high"].values
    lows   = df["low"].values
    times  = [int(t.timestamp()) for t in df.index]
    bull, bear = [], []

    for i in range(n, len(df) - n):
        if all(lows[i]  <= lows[i - j]  for j in range(1, n+1)) and \
           all(lows[i]  <= lows[i + j]  for j in range(1, n+1)):
            bull.append({"time": times[i], "price": round(float(lows[i]),  5)})
        if all(highs[i] >= highs[i - j] for j in range(1, n+1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, n+1)):
            bear.append({"time": times[i], "price": round(float(highs[i]), 5)})

    return {"bullish": bull[-12:], "bearish": bear[-12:]}


# ─────────────────────────────────────────────────────────────────────────────
#  Smart Money Concepts  (OB · FVG · BOS/CHoCH · Equal H/L)
# ─────────────────────────────────────────────────────────────────────────────

def _calc_smc(df, atr_val: float) -> dict:
    highs  = df["high"].values
    lows   = df["low"].values
    closes = df["close"].values
    opens  = df["open"].values
    times  = [int(t.timestamp()) for t in df.index]
    n = len(df)
    if n < 20:
        return {"ob": [], "fvg": [], "bos": [], "eqhl": [],
                "trigger": "none", "trigger_reason": ""}
    atr = max(float(atr_val), abs(float(closes[-1]) - float(closes[-20])) / 20, 1e-7)
    cur = float(closes[-1])

    # ── Order Blocks ──────────────────────────────────────────────────────────
    obs = []
    for i in range(3, n - 4):
        is_bear = float(closes[i]) < float(opens[i])
        is_bull = float(closes[i]) > float(opens[i])
        if is_bear:
            fu = sum(1 for j in range(i+1, min(i+5, n)) if float(closes[j]) > float(opens[j]))
            if fu >= 2 and float(closes[min(i+3, n-1)]) - float(closes[i]) > atr * 0.7:
                obs.append({"top": round(float(max(opens[i], closes[i])), 5),
                            "bottom": round(float(min(opens[i], closes[i])), 5),
                            "type": "bull", "time": times[i]})
        elif is_bull:
            fd = sum(1 for j in range(i+1, min(i+5, n)) if float(closes[j]) < float(opens[j]))
            if fd >= 2 and float(closes[i]) - float(closes[min(i+3, n-1)]) > atr * 0.7:
                obs.append({"top": round(float(max(opens[i], closes[i])), 5),
                            "bottom": round(float(min(opens[i], closes[i])), 5),
                            "type": "bear", "time": times[i]})
    obs_valid = [ob for ob in obs[-8:]
                 if (ob["type"] == "bull" and cur > ob["bottom"] - atr*0.1)
                 or (ob["type"] == "bear" and cur < ob["top"] + atr*0.1)][-5:]

    # ── Fair Value Gaps ───────────────────────────────────────────────────────
    fvgs = []
    for i in range(1, n - 1):
        if float(highs[i-1]) < float(lows[i+1]):
            gap = float(lows[i+1]) - float(highs[i-1])
            if gap > atr * 0.25:
                fvgs.append({"top": round(float(lows[i+1]), 5),
                             "bottom": round(float(highs[i-1]), 5),
                             "type": "bull", "time": times[i]})
        elif float(lows[i-1]) > float(highs[i+1]):
            gap = float(lows[i-1]) - float(highs[i+1])
            if gap > atr * 0.25:
                fvgs.append({"top": round(float(lows[i-1]), 5),
                             "bottom": round(float(highs[i+1]), 5),
                             "type": "bear", "time": times[i]})
    fvgs_valid = [f for f in fvgs[-10:]
                  if (f["type"] == "bull" and cur > f["bottom"] - atr*0.1)
                  or (f["type"] == "bear" and cur < f["top"] + atr*0.1)][-4:]

    # ── Swing highs / lows ────────────────────────────────────────────────────
    swh, swl = [], []
    for i in range(2, n - 2):
        if (float(highs[i]) > float(highs[i-1]) and float(highs[i]) > float(highs[i-2])
                and float(highs[i]) > float(highs[i+1]) and float(highs[i]) > float(highs[i+2])):
            swh.append((times[i], float(highs[i])))
        if (float(lows[i]) < float(lows[i-1]) and float(lows[i]) < float(lows[i-2])
                and float(lows[i]) < float(lows[i+1]) and float(lows[i]) < float(lows[i+2])):
            swl.append((times[i], float(lows[i])))

    # ── BOS / CHoCH ───────────────────────────────────────────────────────────
    bos_list = []
    if len(swh) >= 2:
        prev = swh[-2][1]
        if cur > prev:
            typ = ("CHoCH_bull" if len(swh) >= 3 and swh[-3][1] > swh[-2][1]
                   else "BOS_bull")
            bos_list.append({"price": round(prev, 5), "type": typ, "time": swh[-2][0]})
    if len(swl) >= 2:
        prev = swl[-2][1]
        if cur < prev:
            typ = ("CHoCH_bear" if len(swl) >= 3 and swl[-3][1] < swl[-2][1]
                   else "BOS_bear")
            bos_list.append({"price": round(prev, 5), "type": typ, "time": swl[-2][0]})

    # ── Equal Highs / Lows ────────────────────────────────────────────────────
    eqhl, seen_h, seen_l = [], set(), set()
    tol = atr * 0.2
    for i in range(len(swh)):
        for j in range(i+1, len(swh)):
            if abs(swh[i][1] - swh[j][1]) < tol:
                mid = round((swh[i][1]+swh[j][1])/2, 5)
                if mid not in seen_h:
                    eqhl.append({"price": mid, "type": "EQH", "time": swh[j][0]})
                    seen_h.add(mid)
    for i in range(len(swl)):
        for j in range(i+1, len(swl)):
            if abs(swl[i][1] - swl[j][1]) < tol:
                mid = round((swl[i][1]+swl[j][1])/2, 5)
                if mid not in seen_l:
                    eqhl.append({"price": mid, "type": "EQL", "time": swl[j][0]})
                    seen_l.add(mid)
    eqhl = eqhl[-6:]

    # ── Scalping trigger ──────────────────────────────────────────────────────
    trigger, trigger_reason = "none", ""
    for ob in reversed(obs_valid):
        if abs(cur - (ob["top"]+ob["bottom"])/2) < atr * 0.6:
            if ob["type"] == "bull" and cur >= ob["bottom"]:
                trigger = "OB_BOUNCE_BUY"
                trigger_reason = "OB صعودي %s–%s" % (ob["bottom"], ob["top"])
                break
            elif ob["type"] == "bear" and cur <= ob["top"]:
                trigger = "OB_BOUNCE_SELL"
                trigger_reason = "OB هبوطي %s–%s" % (ob["bottom"], ob["top"])
                break
    if trigger == "none":
        for fvg in reversed(fvgs_valid):
            if fvg["bottom"] - atr*0.1 <= cur <= fvg["top"] + atr*0.1:
                trigger = "FVG_FILL_BUY" if fvg["type"] == "bear" else "FVG_FILL_SELL"
                trigger_reason = "FVG %s–%s" % (fvg["bottom"], fvg["top"])
                break
    if trigger == "none":
        for eq in reversed(eqhl):
            if abs(cur - eq["price"]) < atr * 0.3:
                trigger = ("LIQ_SWEEP_SELL" if eq["type"] == "EQH" else "LIQ_SWEEP_BUY")
                trigger_reason = "كسح سيولة %s عند %s" % (eq["type"], eq["price"])
                break
    if trigger == "none" and n >= 4:
        bod = [float(closes[n-1-j]) - float(opens[n-1-j]) for j in range(2, -1, -1)]
        if all(v > atr * 0.35 for v in bod):
            trigger = "MOM_BURST_BUY";  trigger_reason = "اندفاع صعودي قوي"
        elif all(v < -atr * 0.35 for v in bod):
            trigger = "MOM_BURST_SELL"; trigger_reason = "اندفاع هبوطي قوي"

    return {"ob": obs_valid, "fvg": fvgs_valid, "bos": bos_list,
            "eqhl": eqhl, "trigger": trigger, "trigger_reason": trigger_reason}


# ─────────────────────────────────────────────────────────────────────────────
#  Key Market Levels
# ─────────────────────────────────────────────────────────────────────────────

def _calc_key_levels(symbol: str) -> dict:
    """
    Returns a dict of named price levels:
      today_open/high/low | prev_day_high/low/close
      pivot/r1/r2/s1/s2   | week_high/low | month_high/low
      h4_nearest_up / h4_nearest_dn (nearest H4 swing in each direction)
    """
    levels: dict = {}
    try:
        import MetaTrader5 as mt5
        import pandas as pd
        mt5.initialize()

        # ── Daily bars ───────────────────────────────────────────────────────
        d1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 35)
        if d1 is not None and len(d1) >= 2:
            d1df = pd.DataFrame(d1)
            today = d1df.iloc[-1]
            yday  = d1df.iloc[-2]

            levels["today_open"]  = round(float(today["open"]),  5)
            levels["today_high"]  = round(float(today["high"]),  5)
            levels["today_low"]   = round(float(today["low"]),   5)
            levels["today_close"] = round(float(today["close"]), 5)

            levels["prev_high"]   = round(float(yday["high"]),  5)
            levels["prev_low"]    = round(float(yday["low"]),   5)
            levels["prev_close"]  = round(float(yday["close"]), 5)

            # Classic Pivot Points (from yesterday)
            ph, pl, pc = float(yday["high"]), float(yday["low"]), float(yday["close"])
            pp   = (ph + pl + pc) / 3
            r1   = 2*pp - pl;  r2 = pp + (ph - pl)
            s1   = 2*pp - ph;  s2 = pp - (ph - pl)
            r3   = ph + 2*(pp - pl)
            s3   = pl - 2*(ph - pp)
            for k, v in [("pivot",pp),("r1",r1),("r2",r2),("r3",r3),
                         ("s1",s1),("s2",s2),("s3",s3)]:
                levels[k] = round(v, 5)

            # Weekly high/low (last 5 bars)
            if len(d1df) >= 5:
                wk = d1df.tail(5)
                levels["week_high"] = round(float(wk["high"].max()), 5)
                levels["week_low"]  = round(float(wk["low"].min()),  5)

            # Monthly high/low (last 22 bars)
            if len(d1df) >= 22:
                mo = d1df.tail(22)
                levels["month_high"] = round(float(mo["high"].max()), 5)
                levels["month_low"]  = round(float(mo["low"].min()),  5)

        # ── H4 swing levels (fractal-based) ──────────────────────────────────
        h4 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 40)
        if h4 is not None and len(h4) >= 10:
            import pandas as pd
            h4df = pd.DataFrame(h4)
            highs = h4df["high"].values
            lows  = h4df["low"].values
            current_close = float(h4df.iloc[-1]["close"])

            # H4 fractal highs above current price
            h4_bear = sorted(
                [float(highs[i]) for i in range(2, len(h4df)-2)
                 if all(highs[i] >= highs[i-j] for j in range(1,3)) and
                    all(highs[i] >= highs[i+j] for j in range(1,3)) and
                    float(highs[i]) > current_close],
                reverse=False
            )
            # H4 fractal lows below current price
            h4_bull = sorted(
                [float(lows[i]) for i in range(2, len(h4df)-2)
                 if all(lows[i] <= lows[i-j] for j in range(1,3)) and
                    all(lows[i] <= lows[i+j] for j in range(1,3)) and
                    float(lows[i]) < current_close],
                reverse=True
            )
            if h4_bear:
                levels["h4_resist1"] = round(h4_bear[0], 5)
                if len(h4_bear) > 1:
                    levels["h4_resist2"] = round(h4_bear[1], 5)
            if h4_bull:
                levels["h4_support1"] = round(h4_bull[0], 5)
                if len(h4_bull) > 1:
                    levels["h4_support2"] = round(h4_bull[1], 5)

    except Exception:
        pass
    return levels


# ─────────────────────────────────────────────────────────────────────────────
#  Projection targets  (where price is heading)
# ─────────────────────────────────────────────────────────────────────────────

def _projection_targets(
    entry_dir: int,
    price: float,
    levels: dict,
    fractals: dict,
    atr: float,
    accuracy: float,
) -> list:
    """
    Returns up to 3 ordered price targets in the trade direction.
    Accuracy (0–1) widens the target range when above 0.6.
    """
    if entry_dir == 0 or not levels:
        return []

    # Pool all candidate levels
    candidates: list[float] = []

    if entry_dir == 1:   # BUY — look above
        keys = ["r1","r2","r3","prev_high","today_high","week_high",
                "month_high","h4_resist1","h4_resist2"]
        candidates = sorted([_f(levels[k]) for k in keys
                             if k in levels and _f(levels[k]) > price + atr*0.3])
        # Add bearish fractals above price
        for fx in (fractals.get("bearish") or []):
            p = _f(fx.get("price",0))
            if p > price + atr*0.3:
                candidates.append(p)
        candidates.sort()
    else:                # SELL — look below
        keys = ["s1","s2","s3","prev_low","today_low","week_low",
                "month_low","h4_support1","h4_support2"]
        candidates = sorted([_f(levels[k]) for k in keys
                             if k in levels and _f(levels[k]) < price - atr*0.3],
                            reverse=True)
        for fx in (fractals.get("bullish") or []):
            p = _f(fx.get("price",0))
            if p < price - atr*0.3:
                candidates.append(p)
        candidates.sort(reverse=True)

    # Deduplicate close levels
    deduped: list[float] = []
    for c in candidates:
        if not deduped or abs(c - deduped[-1]) > atr * 0.5:
            deduped.append(round(c, 5))

    # Accuracy > 0.6 → allow 3 targets; else only 1
    max_targets = 3 if accuracy >= 0.6 else (2 if accuracy >= 0.45 else 1)
    return deduped[:max_targets]


# ─────────────────────────────────────────────────────────────────────────────
#  Prediction memory (self-learning)
# ─────────────────────────────────────────────────────────────────────────────

def _load_predictions() -> dict:
    if not PRED_FILE.exists():
        return {}
    try:
        return json.loads(PRED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_predictions(preds: dict):
    try:
        PRED_FILE.write_text(json.dumps(preds, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    except Exception:
        pass


def _check_and_update(symbol: str, tf: str, current_price: float) -> dict:
    """
    Check if a pending prediction for symbol|tf was hit or stopped.
    Returns accuracy stats: {hits, misses, total, accuracy, last_result}.
    Updates the prediction file in-place.
    """
    preds = _load_predictions()
    key   = f"{symbol}|{tf}"
    now   = datetime.now(timezone.utc).isoformat()
    updated = False

    p = preds.get(key)
    if p and p.get("result") is None:
        entry_dir = p.get("dir", 0)
        targets   = p.get("targets", [])
        sl        = _f(p.get("sl", 0))

        # Check TP hits
        for t in targets:
            if entry_dir == 1 and current_price >= _f(t):
                p.update({"result": "hit", "hit_price": round(current_price, 5),
                          "resolved_ts": now})
                updated = True; break
            elif entry_dir == -1 and current_price <= _f(t):
                p.update({"result": "hit", "hit_price": round(current_price, 5),
                          "resolved_ts": now})
                updated = True; break

        # Check SL hit
        if not updated and sl > 0:
            if (entry_dir == 1  and current_price <= sl) or \
               (entry_dir == -1 and current_price >= sl):
                p.update({"result": "miss", "resolved_ts": now})
                updated = True

    if updated:
        preds[key] = p
        _save_predictions(preds)

    # Compute accuracy across all TFs for this symbol
    sym_resolved = [v for k, v in preds.items()
                    if k.startswith(f"{symbol}|") and v.get("result")]
    recent = sym_resolved[-30:]
    hits   = sum(1 for x in recent if x["result"] == "hit")
    total  = len(recent)
    return {
        "hits":        hits,
        "misses":      total - hits,
        "total":       total,
        "accuracy":    round(hits / total, 2) if total > 0 else 0.5,
        "last_result": p.get("result") if p else None,
    }


def _save_new_prediction(symbol: str, tf: str, entry_dir: int,
                         entry_px: float, targets: list, sl_px: float):
    if entry_dir == 0 or not targets:
        return
    preds = _load_predictions()
    key   = f"{symbol}|{tf}"
    # Don't overwrite a pending prediction in the same direction
    existing = preds.get(key, {})
    if existing.get("result") is None and existing.get("dir") == entry_dir:
        return
    preds[key] = {
        "dir":         entry_dir,
        "entry":       round(entry_px, 5),
        "targets":     [round(t, 5) for t in targets],
        "sl":          round(sl_px, 5),
        "ts":          datetime.now(timezone.utc).isoformat(),
        "result":      None,
        "hit_price":   None,
        "resolved_ts": None,
    }
    # Trim to 200 entries (keep most recent)
    if len(preds) > 200:
        resolved = [(k,v) for k,v in preds.items() if v.get("result")]
        resolved.sort(key=lambda x: x[1].get("ts",""), reverse=True)
        pending  = {k:v for k,v in preds.items() if not v.get("result")}
        preds = dict(resolved[:100]) | pending
    _save_predictions(preds)


# ─────────────────────────────────────────────────────────────────────────────
#  Gene fitness brain (connect to runner's learning)
# ─────────────────────────────────────────────────────────────────────────────

def _get_genome_brain(symbol: str, tf: str) -> dict:
    """Read genome win-rate from gene_fitness_db and runner state."""
    brain: dict = {}
    try:
        fit_file = DATA / "gene_fitness.json"
        if fit_file.exists():
            fit = json.loads(fit_file.read_text(encoding="utf-8"))
            sym_tf = fit.get(symbol, {}).get(tf, {})
            total  = sym_tf.get("total_campaigns", 0)
            genes  = sym_tf.get("genes", {})
            # Best performing gene combo
            combos = sym_tf.get("combos", {})
            if combos:
                best = max(combos.items(),
                           key=lambda x: x[1].get("wins",0) / max(x[1].get("wins",0)+x[1].get("fails",0),1),
                           default=(None,{}))
                brain["best_combo"]     = best[0]
                brain["combo_win_rate"] = round(best[1].get("wins",0) /
                    max(best[1].get("wins",0)+best[1].get("fails",0),1), 2)
            brain["total_campaigns"] = total
    except Exception:
        pass
    return brain


# ─────────────────────────────────────────────────────────────────────────────
#  Main analysis
# ─────────────────────────────────────────────────────────────────────────────

def _analyse(symbol: str, timeframe: str, genome_dict: dict) -> dict:
    try:
        from mt5_ai.algory_dna import AlgoryGenome
        from mt5_ai.algory_signal_engine import compute_signals, build_cache
        import dataclasses

        genome = AlgoryGenome.from_dict(genome_dict)
        df = _fetch_bars(symbol, timeframe, n=250)
        if df is None or len(df) < 50:
            return {"error": "no_bars"}

        sig_df = compute_signals(df, genome)
        sig_df = sig_df.copy()
        last   = sig_df.iloc[-1].copy()
        prev50 = sig_df.tail(50).copy()

        entry_dir  = int(_f(last.get("entry_dir",  0)))
        filter_ok  = bool(last.get("filter_ok", False))
        confidence = _f(last.get("confidence", 0.0))
        sl_px      = _f(last.get("sl",       0.0))
        tp_px      = _f(last.get("tp",       0.0))
        entry_px   = _f(last.get("entry_px", _f(df["close"].iloc[-1])))
        signal_vote= int(_f(last.get("signal", 0)))
        bias_vote  = int(_f(last.get("bias",   0)))
        rr         = 0.0
        if sl_px > 0 and tp_px > 0:
            rr = abs(tp_px - entry_px) / (abs(entry_px - sl_px) + 1e-10)
        min_rr = _f(genome.min_rr, 1.0)

        if not filter_ok or entry_dir == 0:
            action = "HOLD";  reason = "no_signal"
        elif rr < min_rr:
            action = "HOLD";  reason = f"rr_{rr:.2f}<{min_rr}"
        else:
            action = "BUY" if entry_dir == 1 else "SELL"
            reason = "signal_ok"

        current_price = _f(df["close"].iloc[-1])

        # ── Indicator cache ───────────────────────────────────────────────────
        try:
            ind = build_cache(df, genome)
            ind_rsi    = _f(ind.rsi.iloc[-1])
            ind_adx    = _f(ind.adx.iloc[-1])
            ind_sk     = _f(ind.stoch_k.iloc[-1])
            ind_sd     = _f(ind.stoch_d.iloc[-1])
            ind_macd_d = _f(ind.macd.iloc[-1]) - _f(ind.macd_sig.iloc[-1])
            atr_val    = _f(ind.atr.iloc[-1])
        except Exception:
            ind_rsi = ind_adx = ind_sk = ind_sd = ind_macd_d = atr_val = 0.0

        pip_m = 100.0 if "JPY" in symbol else (10.0 if "XAU" in symbol else 10000.0)
        sl_pips  = round(abs(entry_px - sl_px) * pip_m, 1) if sl_px > 0 else 0.0
        tp_pips  = round(abs(tp_px - entry_px)  * pip_m, 1) if tp_px > 0 else 0.0
        atr_pips = round(atr_val * pip_m, 1)

        try:
            all_f    = [f.name for f in dataclasses.fields(genome)]
            n_sigs   = sum(1 for n in all_f if n.startswith("use_sig_")  and getattr(genome,n))
            n_biases = sum(1 for n in all_f if n.startswith("use_bias_") and getattr(genome,n))
            n_filts  = sum(1 for n in all_f if n.startswith("use_filt_") and getattr(genome,n))
        except Exception:
            n_sigs = n_biases = n_filts = 0

        # ── SMC ──────────────────────────────────────────────────────────────
        smc = _calc_smc(df, atr_val)

        # ── Fractals ─────────────────────────────────────────────────────────
        fractals = _calc_fractals(df, n=2)

        # ── Key levels ───────────────────────────────────────────────────────
        levels = _calc_key_levels(symbol)

        # ── Prediction tracking (self-learning) ──────────────────────────────
        acc  = _check_and_update(symbol, timeframe, current_price)
        accuracy = acc.get("accuracy", 0.5)

        # ── Projection targets ───────────────────────────────────────────────
        proj = _projection_targets(entry_dir, current_price, levels,
                                   fractals, atr_val, accuracy)
        if entry_dir != 0 and proj:
            _save_new_prediction(symbol, timeframe, entry_dir,
                                 entry_px, proj, sl_px)

        # ── Runner live state (what the runner is actually doing) ────────────
        runner_state: dict = {}
        try:
            sf = DATA / "algory_runner_state.json"
            if sf.exists():
                rs = json.loads(sf.read_text(encoding="utf-8"))
                k  = f"{symbol}|{timeframe}"
                runner_state = rs.get(k, {})
        except Exception:
            pass

        # ── Gene brain ───────────────────────────────────────────────────────
        brain = _get_genome_brain(symbol, timeframe)

        # ── Indicator series ─────────────────────────────────────────────────
        from mt5_ai.algory_signal_engine import _rsi as _r
        rsi_series  = _r(df["close"], int(genome.rsi_period))
        ema_series  = df["close"].ewm(span=int(genome.ema_period), adjust=False).mean()
        ema_fast    = df["close"].ewm(span=12, adjust=False).mean()
        ema_slow    = df["close"].ewm(span=26, adjust=False).mean()
        macd_line   = ema_fast - ema_slow
        macd_sig_s  = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist   = macd_line - macd_sig_s
        k_p         = int(genome.stoch_k_period)
        lo_min      = df["low"].rolling(k_p).min()
        hi_max      = df["high"].rolling(k_p).max()
        stoch_k     = 100*(df["close"]-lo_min)/(hi_max-lo_min+1e-10)
        stoch_d     = stoch_k.rolling(int(genome.stoch_d_period)).mean()
        h, l, c     = df["high"], df["low"], df["close"]
        tr          = (h-l).combine((h-c.shift()).abs(),max).combine((l-c.shift()).abs(),max)
        adx_series  = tr.ewm(span=int(genome.adx_period), adjust=False).mean()

        # ── Fractal structure + market projection ─────────────────────────────
        fractal_structure: dict = {}
        market_projection: dict = {}
        try:
            from mt5_ai.fractal_structure_engine import analyse_structure
            from mt5_ai.market_projection_engine  import generate_projection
            _fs = analyse_structure(df)
            market_projection = generate_projection(
                df, _fs, symbol=symbol, tf=timeframe,
                ema_series=ema_series,
                genome_win_rate=brain.get("combo_win_rate", 0.5),
            )
            fractal_structure = _fs.to_dict()
        except Exception:
            pass

        # ── FRACTAL ANALOG forecast (self-similar: replay the most similar past pattern) ──
        try:
            from mt5_ai.market_projection_engine import fractal_analog_forecast
            # SELF-TUNED config (fractal_selftune.py picks the best-scoring window/horizon/top_k)
            _w, _h, _k = 30, 14, 5
            try:
                _ac = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\fractal_active_config.json")
                if _ac.exists():
                    _acd = json.loads(_ac.read_text(encoding="utf-8"))
                    _w, _h, _k = int(_acd.get("window", 30)), int(_acd.get("horizon", 14)), int(_acd.get("top_k", 5))
                    market_projection["active_config"] = _acd.get("key")
            except Exception:
                pass
            _hist = _fetch_bars(symbol, timeframe, n=1500)   # more history for the analog search
            if _hist is not None and len(_hist) >= 400:
                _fc = fractal_analog_forecast(_hist, window=_w, horizon=_h, top_k=_k)
                market_projection["fractal_candles"] = _fc.get("candles", [])
                market_projection["analog_corr"]     = _fc.get("analog_corr", 0.0)
                market_projection["analog_scale"]    = _fc.get("scale", 1.0)
            # LIVE self-score (fractal_selftune scoreboard) + static OOS verdict
            try:
                _sb = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\fractal_scoreboard.json")
                if _sb.exists():
                    _s = json.loads(_sb.read_text(encoding="utf-8"))
                    market_projection["self_score"] = {
                        "best_dir_hit": _s.get("best_dir_hit"), "best_live_score": _s.get("best_live_score"),
                        "active": _s.get("active"), "samples": _s.get("ledger_size")}
                _vp = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\analog_validation.json")
                if _vp.exists():
                    _v = json.loads(_vp.read_text(encoding="utf-8"))
                    market_projection["analog_accuracy"] = {
                        "hit_hi": _v.get("hit_corr>=0.80"), "hit_all": _v.get("hit_all"),
                        "predictive": _v.get("predictive"), "tf": _v.get("tf")}
                _gp = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\gap_fill_validation.json")
                if _gp.exists():
                    _g = json.loads(_gp.read_text(encoding="utf-8"))
                    market_projection["gap_stats"] = {
                        "fill_rate": _g.get("fill_rate"),
                        "fill_bearish": _g.get("fill_rate_bearish_context")}
            except Exception:
                pass
            # Volume Profile: POC / VAH / VAL (institutional magnet + value-area edges)
            try:
                import sys as _sys
                if r"C:\Users\Radhi\MT5" not in _sys.path: _sys.path.insert(0, r"C:\Users\Radhi\MT5")
                from volume_profile import compute_profile as _cp
                _vpr = _fetch_bars(symbol, timeframe, n=150)
                if _vpr is not None and len(_vpr) >= 20:
                    _recs = _vpr.reset_index().to_dict("records")
                    _vp = _cp([{"high": x["high"], "low": x["low"],
                                "tick_volume": x.get("tick_volume", x.get("volume", 1))} for x in _recs])
                    if _vp: market_projection["vp"] = _vp
            except Exception as _e:
                market_projection["vp_err"] = str(_e)[:60]
            # MARKOV REGIME (Bull/Bear/Sideways transition matrix + stationary + current state)
            try:
                import sys as _sys2
                if r"C:\Users\Radhi\MT5" not in _sys2.path: _sys2.path.insert(0, r"C:\Users\Radhi\MT5")
                from markov_regime import label_regimes as _lr, transition_matrix as _tm, stationary as _st, signal_from as _sf
                import MetaTrader5 as _mk_mt5
                _mk_mt5.initialize()
                _drates = _mk_mt5.copy_rates_from_pos(symbol, _mk_mt5.TIMEFRAME_D1, 0, 2500)
                _cl = ([float(x["close"]) for x in _drates] if _drates is not None and len(_drates) > 120
                       else list(df["close"].to_numpy()))
                import numpy as _np
                _cl = _np.array(_cl, float)
                _lab, _val = _lr(_cl, 20, 0.02)
                if _val.any():
                    _lv = _lab[_val]; _P = _tm(_lv); _pi = _st(_P); _curr = int(_lv[-1])
                    _names = ["Bear", "Sideways", "Bull"]
                    market_projection["markov"] = {
                        "current": _names[_curr],
                        "signal": round(_sf(_P, _curr), 3),
                        "matrix": [[round(float(_P[i][j]) * 100, 1) for j in range(3)] for i in range(3)],
                        "stationary": [round(float(x) * 100, 1) for x in _pi],
                        "persistence": [round(float(_P[i][i]) * 100, 1) for i in range(3)]}
                    # INTRADAY regime (H1, threshold recalibrated to intraday vol) — a LIVE-moving
                    # lens. The daily regime above barely changes intraday (it's the macro gate);
                    # this one actually breathes with the session. CONTEXT/display only.
                    try:
                        _hr = _mk_mt5.copy_rates_from_pos(symbol, _mk_mt5.TIMEFRAME_H1, 0, 2500)
                        if _hr is not None and len(_hr) > 120:
                            _hc = _np.array([float(x["close"]) for x in _hr], float)
                            _hl, _hv = _lr(_hc, 20, 0.005)
                            if _hv.any():
                                _hlv = _hl[_hv]; _hP = _tm(_hlv); _hcur = int(_hlv[-1])
                                market_projection["markov"]["intraday"] = {
                                    "tf": "H1", "current": _names[_hcur],
                                    "signal": round(_sf(_hP, _hcur), 3),
                                    "persistence": round(float(_hP[_hcur][_hcur]) * 100, 1)}
                    except Exception:
                        pass
            except Exception as _e:
                market_projection["markov_err"] = str(_e)[:60]
            # VOLATILITY / RANGE regime — the ONE secondary signal that tested REAL out-of-sample.
            # Predicts HOW MUCH price moves (range), NEVER which way. Scales the TARGET only.
            try:
                import sys as _sysv
                if r"C:\Users\Radhi\MT5" not in _sysv.path: _sysv.path.insert(0, r"C:\Users\Radhi\MT5")
                import vol_regime as _vr
                _vrows = df.reset_index().to_dict("records")
                _reg = _vr.classify(_vrows)
                market_projection["vol_regime"] = _reg
                _vr.write_advisory(symbol, _reg)        # advisory file traders can read (target scaling)
            except Exception as _e:
                market_projection["vol_regime_err"] = str(_e)[:60]
            # SENTIMENT composite gauge (7-indicator alignment snapshot — CONTEXT, not a forecast)
            try:
                from sentiment_composite import compute_series as _cs
                _sr = _fetch_bars(symbol, timeframe, n=400)
                if _sr is not None and len(_sr) >= 270:
                    _rc = _sr.reset_index().to_dict("records")
                    _sc, _bp, _cm = _cs([x["close"] for x in _rc], [x["high"] for x in _rc],
                                         [x["low"] for x in _rc],
                                         [x.get("tick_volume", x.get("volume", 1)) for x in _rc])
                    _names = ["RSI", "EMA", "MACD", "ADX", "Ichimoku", "Bollinger", "OBV"]
                    market_projection["sentiment"] = {
                        "active_pct": round(float(_sc[-1]), 1),
                        "buying_pressure": round(float(_bp[-1]), 1),
                        "components": dict(zip(_names, [int(x) for x in _cm[-1]])),
                        "health": "bull" if (_sc[-1] > 50 and _bp[-1] > 50) else "bear"}
            except Exception as _e:
                market_projection["sent_err"] = str(_e)[:60]
        except Exception as _e:
            market_projection["fractal_err"] = str(_e)[:80]

        tail = df.tail(100).copy()
        idx  = [int(i.timestamp()) for i in tail.index]

        def _series(s, decimals=5):
            vals, out = list(s.tail(100)), []
            for t, v in zip(idx, vals):
                try:
                    fv = float(v)
                    if math.isnan(fv) or math.isinf(fv): continue
                    out.append({"time": t, "value": round(fv, decimals)})
                except (TypeError, ValueError): continue
            return out

        markers = []
        for i, row in prev50.iterrows():
            d  = int(_f(row.get("entry_dir",0)))
            fo = bool(row.get("filter_ok", False))
            if d != 0 and fo:
                markers.append({"time": int(i.timestamp()), "dir": d,
                                 "conf": round(_f(row.get("confidence",0.0)),2)})

        candles = []
        for i, row in df.tail(100).iterrows():
            candles.append({"time": int(i.timestamp()),
                            "open":  round(_f(row["open"]),  5),
                            "high":  round(_f(row["high"]),  5),
                            "low":   round(_f(row["low"]),   5),
                            "close": round(_f(row["close"]), 5)})

        return {
            "symbol":      symbol,
            "timeframe":   timeframe,
            "genome_id":   genome.id[:8],
            "action":      action,
            "reason":      reason,
            "confidence":  round(confidence, 3),
            "rr":          round(rr, 2),
            "min_rr":      min_rr,
            "sl":          round(sl_px,     5),
            "tp":          round(tp_px,     5),
            "entry":       round(entry_px,  5),
            "price":       round(current_price, 5),
            "signal_vote": signal_vote,
            "bias_vote":   bias_vote,
            "filter_ok":   filter_ok,
            "fractals":    fractals,
            "levels":      {k: round(_f(v),5) for k,v in levels.items() if _f(v)>0},
            "projection":  proj,
            "accuracy":    acc,
            "brain":       brain,
            "why": {
                "rsi":       round(ind_rsi, 1),
                "adx":       round(ind_adx, 1),
                "stoch_k":   round(ind_sk,  1),
                "stoch_d":   round(ind_sd,  1),
                "macd_diff": round(ind_macd_d, 6),
                "atr_pips":  atr_pips,
                "sl_pips":   sl_pips,
                "tp_pips":   tp_pips,
                "n_sigs":    n_sigs,
                "n_biases":  n_biases,
                "n_filts":   n_filts,
            },
            "smc":         smc,
            "runner":      runner_state,
            "candles":     candles,
            "markers":     markers,
            "ema":         _series(ema_series, 5),
            "rsi":         _series(rsi_series, 2),
            "macd_line":   _series(macd_line,  6),
            "macd_sig":    _series(macd_sig_s, 6),
            "macd_hist":   _series(macd_hist,  6),
            "stoch_k":     _series(stoch_k, 2),
            "stoch_d":     _series(stoch_d, 2),
            "adx":         _series(adx_series, 2),
            "fractal_structure": fractal_structure,
            "market_projection": market_projection,
            "ts":          datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
#  API
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/symbols")
def api_symbols():
    genomes = _active_genomes()
    pairs = []
    for key in sorted(genomes.keys()):
        sym, tf = key.split("|", 1)
        g = genomes[key]
        pairs.append({"key": key, "symbol": sym, "timeframe": tf,
                      "genome_id": g.get("id","?")[:8],
                      "campaign":  g.get("campaign","quick"),
                      "score":     round(g.get("modern_score_cache",0.0),2)})
    return JSONResponse(pairs)


@app.get("/api/chart/{symbol}/{timeframe}")
def api_chart(symbol: str, timeframe: str):
    genomes = _active_genomes()
    key = f"{symbol}|{timeframe}"
    gd = genomes.get(key)
    if gd is None:                                    # no exact genome — fall back so ANY symbol charts
        for k, v in genomes.items():                  # 1) any genome for THIS symbol (other TF)
            if k.split("|", 1)[0] == symbol:
                gd = v; break
    if gd is None and genomes:                        # 2) borrow any genome — candles/EMA/RSI/MACD/Markov/
        gd = next(iter(genomes.values()))             #    levels are computed from `symbol`, only the
    if gd is None:                                    #    BUY/SELL signal engine is genome-specific
        return JSONResponse({"error": f"No genome for {key}"}, status_code=404)
    return JSONResponse(_analyse(symbol, timeframe, gd))


def _chart_decision(symbol: str, timeframe: str) -> dict:
    """Condense the FULL chart reading (the same analysis the dashboard draws) into a
    single directional verdict + confluence score. This is the ONE source of truth that
    both the chart and the live trader (gold_live) consume — entries are bound to it.

    Each visible reading casts a vote (+1 bull / -1 bear / 0 neutral); votes are weighted
    (validated signals weigh more), the net sign is the direction, and confluence is the
    share of weight that agrees with that direction (0..1)."""
    genomes = _active_genomes()
    key = f"{symbol}|{timeframe}"
    gd = genomes.get(key)
    if gd is None:                                   # fall back to any genome for this symbol
        for k, v in genomes.items():
            if k.split("|", 1)[0] == symbol:
                gd, key = v, k; break
    if gd is None:
        return {"error": "no_genome", "symbol": symbol}
    tf = key.split("|", 1)[1]
    d = _analyse(symbol, tf, gd)
    if "error" in d:
        return {"error": d["error"], "symbol": symbol}
    why = d.get("why", {}) or {}
    mp  = d.get("market_projection", {}) or {}
    mk  = mp.get("markov") or {}
    sent= mp.get("sentiment") or {}
    smc = d.get("smc", {}) or {}

    votes, weights = {}, {}
    def cast(name, v, w):
        votes[name] = int(v); weights[name] = float(w)

    # genome signal engine (the chart's own BUY/SELL/HOLD) — strong
    cast("signal", 1 if d.get("action") == "BUY" else -1 if d.get("action") == "SELL" else 0, 2.0)
    # Markov daily regime (walk-forward validated) — strong
    reg = mk.get("current")
    cast("markov", 1 if reg == "Bull" else -1 if reg == "Bear" else 0, 2.0)
    # RSI
    rsi = why.get("rsi", 50.0)
    cast("rsi", 1 if rsi > 55 else -1 if rsi < 45 else 0, 1.0)
    # MACD histogram
    md = why.get("macd_diff", 0.0)
    cast("macd", 1 if md > 0 else -1 if md < 0 else 0, 1.0)
    # Stochastic cross (avoid extremes)
    sk, sd = why.get("stoch_k", 50.0), why.get("stoch_d", 50.0)
    cast("stoch", 1 if (sk > sd and sk < 80) else -1 if (sk < sd and sk > 20) else 0, 1.0)
    # Sentiment composite (7-indicator alignment)
    h = sent.get("health")
    cast("sentiment", 1 if h == "bull" else -1 if h == "bear" else 0, 1.0)
    # SMC structure (last BOS/CHoCH)
    smc_vote = 0
    for b in reversed(smc.get("bos", []) or []):
        t = str(b.get("type", ""))
        if t.endswith("bull"): smc_vote = 1; break
        if t.endswith("bear"): smc_vote = -1; break
    if smc_vote == 0:
        trg = str(smc.get("trigger", ""))
        if trg.endswith("BUY"):  smc_vote = 1
        elif trg.endswith("SELL"): smc_vote = -1
    cast("smc", smc_vote, 1.0)

    net = sum(votes[k] * weights[k] for k in votes)
    direction = 1 if net > 0 else -1 if net < 0 else 0
    agree = sum(weights[k] for k in votes if direction != 0 and votes[k] == direction)
    total = sum(weights.values())
    confluence = round(agree / total, 3) if total > 0 else 0.0
    adx = why.get("adx", 0.0)
    return {
        "symbol": symbol, "tf": tf, "price": d.get("price"),
        "dir": direction, "confluence": confluence, "net": round(net, 2),
        "regime": reg, "adx": adx, "action": d.get("action"),
        "rr": d.get("rr"), "sl": d.get("sl"), "tp": d.get("tp"),
        "votes": votes, "weights": weights,
        "ts": d.get("ts"),
    }


@app.get("/api/decision/{symbol}/{timeframe}")
def api_decision(symbol: str, timeframe: str):
    return JSONResponse(_chart_decision(symbol, timeframe))


@app.get("/api/scalp_status")
def api_scalp_status(symbol: str = "XAUUSDm"):
    """Live view of the scalper's 5 entry conditions (the on-chart strip) — exactly
    the gates the live trader checks each cycle, using its evolved live config.
    Symbol-aware: follows the chart's selected symbol (defaults to gold)."""
    try:
        import MetaTrader5 as _mt, chart_read as _cr
        _mt.initialize()
        G = symbol or "XAUUSDm"
        _mt.symbol_select(G, True)
        r = _mt.copy_rates_from_pos(G, _mt.TIMEFRAME_M1, 0, 200)
        if r is None or len(r) < 40:
            return JSONResponse({"error": "no bars"})
        closes = [float(x["close"]) for x in r]

        def _ema(x, n):
            a = 2.0 / (n + 1.0); o = list(x)
            for i in range(1, len(x)): o[i] = a * x[i] + (1 - a) * o[i - 1]
            return o
        e9 = _ema(closes, 9)[-1]
        n = 14; g = l = 0.0
        for i in range(len(closes) - n, len(closes)):
            d = closes[i] - closes[i - 1]; g += max(d, 0); l += max(-d, 0)
        g /= n; l /= n
        rsi = 100 - 100 / (1 + g / l) if l > 1e-9 else 100.0
        tick = _mt.symbol_info_tick(G); price = tick.bid
        o0, c0 = float(r[-1]["open"]), float(r[-1]["close"])
        cread = _cr.read_local(_mt, G, "M1") or {}
        dirv = cread.get("dir"); conf = float(cread.get("confluence", 0.0))
        cfg = {"rsi_buy": 50, "rsi_sell": 50, "conf_gate": 0.40}
        try:
            d = json.loads(Path(r"C:\Users\Radhi\MT5\r_native_v2\data\scalp_live_config.json")
                           .read_text(encoding="utf-8")).get("config", {})
            for k in cfg:
                if k in d: cfg[k] = d[k]
        except Exception:
            pass
        buy = [("سعر>EMA9", price > e9), (f"RSI≥{cfg['rsi_buy']}", rsi >= cfg["rsi_buy"]),
               ("شمعة↑", c0 >= o0), ("قراءة=شراء", dirv == 1), (f"توافق≥{cfg['conf_gate']}", conf >= cfg["conf_gate"])]
        sell = [("سعر<EMA9", price < e9), (f"RSI≤{cfg['rsi_sell']}", rsi <= cfg["rsi_sell"]),
                ("شمعة↓", c0 <= o0), ("قراءة=بيع", dirv == -1), (f"توافق≥{cfg['conf_gate']}", conf >= cfg["conf_gate"])]
        enter = "BUY" if all(v for _, v in buy) else "SELL" if all(v for _, v in sell) else "wait"
        return JSONResponse({
            "price": round(price, 3), "ema9": round(e9, 3), "rsi": round(rsi, 1),
            "candle": "up" if c0 >= o0 else "down", "dir": dirv, "confluence": conf,
            "buy": [{"k": k, "v": bool(v)} for k, v in buy],
            "sell": [{"k": k, "v": bool(v)} for k, v in sell],
            "enter": enter, "cfg": cfg})
    except Exception as e:
        return JSONResponse({"error": str(e)[:80]})


@app.get("/api/levels/{symbol}")
def api_levels(symbol: str):
    return JSONResponse(_calc_key_levels(symbol))


@app.get("/api/vol_regime/{symbol}/{timeframe}")
def api_vol_regime(symbol: str, timeframe: str):
    """Volatility/range regime for a symbol (the one OOS-real signal). Scales target, not direction."""
    try:
        import sys as _s
        if r"C:\Users\Radhi\MT5" not in _s.path: _s.path.insert(0, r"C:\Users\Radhi\MT5")
        import vol_regime as _vr
        df = _fetch_bars(symbol, timeframe, n=200)
        if df is None or len(df) < 30:
            return JSONResponse({"error": "no bars"})
        reg = _vr.classify(df.reset_index().to_dict("records"))
        _vr.write_advisory(symbol, reg)
        return JSONResponse(reg)
    except Exception as e:
        return JSONResponse({"error": str(e)[:80]})


@app.get("/api/runner_state")
def api_runner_state():
    f = DATA / "algory_runner_state.json"
    if not f.exists():
        return JSONResponse({})
    try:
        return JSONResponse(json.loads(f.read_text(encoding="utf-8")))
    except Exception:
        return JSONResponse({})


@app.get("/api/tick/{symbol}")
def api_tick(symbol: str):
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return JSONResponse({"error": "no_tick"})
        pip_m = 100.0 if "JPY" in symbol else (10.0 if "XAU" in symbol else 10000.0)
        spread = round((float(tick.ask) - float(tick.bid)) * pip_m, 1)
        return JSONResponse({"bid": round(float(tick.bid), 5),
                             "ask": round(float(tick.ask), 5),
                             "spread": spread,
                             "ts": int(tick.time)})
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.get("/api/scan")
def api_scan():
    """Live multi-pair market scan (written by market_scanner.py) for the on-chart board."""
    try:
        from pathlib import Path
        p = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\market_scan.json")
        if p.exists():
            return JSONResponse(json.loads(p.read_text(encoding="utf-8")))
        return JSONResponse({"rows": []})
    except Exception as e:
        return JSONResponse({"error": str(e), "rows": []})


@app.get("/api/account")
def api_account(symbol: str = ""):
    """Live account snapshot + open positions (for the on-chart trade overlay
    and the discipline banner). Filters positions to `symbol` if given."""
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
        a = mt5.account_info()
        acct = {} if a is None else {
            "equity": round(float(a.equity), 2), "balance": round(float(a.balance), 2),
            "margin": round(float(a.margin), 2), "margin_free": round(float(a.margin_free), 2),
            "margin_level": round(float(a.margin_level), 0) if a.margin else 0.0,
            "profit": round(float(a.profit), 2), "currency": a.currency}
        poss = mt5.positions_get() or []
        out = []
        for p in poss:
            if symbol and p.symbol != symbol:
                continue
            out.append({"symbol": p.symbol, "type": "BUY" if p.type == 0 else "SELL",
                        "volume": float(p.volume), "open": round(float(p.price_open), 5),
                        "sl": round(float(p.sl), 5), "tp": round(float(p.tp), 5),
                        "profit": round(float(p.profit), 2), "magic": int(p.magic),
                        "time": int(p.time)})
        total = sum(p.profit for p in poss)
        manual = sum(1 for p in poss if p.magic == 0)
        return JSONResponse({"account": acct, "positions": out,
                             "n_total": len(poss), "n_manual": manual,
                             "floating_all": round(float(total), 2)})
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.get("/api/predictions")
def api_predictions():
    return JSONResponse(_load_predictions())


# ─────────────────────────────────────────────────────────────────────────────
#  HTML Dashboard
# ─────────────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Algory Intelligence — FRIDAY</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d0f14;color:#cdd6f4;font-family:'Segoe UI',sans-serif;font-size:12px;overflow:hidden}
header{background:#1e1e2e;padding:6px 14px;display:flex;align-items:center;gap:10px;border-bottom:1px solid #313244;height:40px;flex-shrink:0}
header h1{font-size:13px;font-weight:700;color:#cba6f7;white-space:nowrap}
#live-dot{width:7px;height:7px;border-radius:50%;background:#a6e3a1;flex-shrink:0;animation:blink 1.4s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.15}}
#ts{font-size:10px;color:#45475a;margin-right:auto}
#acc-badge{background:#252535;border:1px solid #313244;border-radius:12px;padding:2px 9px;font-size:10px;color:#cba6f7;cursor:default}
.hbtn{background:#313244;border:none;color:#cdd6f4;padding:4px 10px;border-radius:5px;cursor:pointer;font-size:11px}
.hbtn:hover{background:#45475a}

.layout{display:flex;height:calc(100vh - 40px)}

/* ── Sidebar ── */
.sidebar{display:none}
.gold-tf{display:flex;gap:4px;margin-inline:10px}
.sent-vial{position:absolute;top:150px;left:10px;z-index:20;background:rgba(13,15,20,.82);border:1px solid #313244;border-radius:10px;padding:8px 10px;width:180px;direction:ltr;pointer-events:none}
.sv-head{font-size:11px;font-weight:800;color:#cdd6f4;margin-bottom:6px}
.sv-ctx{font-size:9px;font-weight:700;color:#f9e2af;background:rgba(249,226,175,.15);padding:1px 5px;border-radius:4px;margin-inline-start:4px}
.sv-row{display:flex;align-items:center;gap:8px}
.sv-meter{position:relative;flex:1;height:10px;border-radius:6px;background:linear-gradient(90deg,#f38ba8,#f9e2af,#a6e3a1)}
.sv-fill{position:absolute;top:-3px;width:3px;height:16px;background:#fff;border-radius:2px;box-shadow:0 0 4px #000}
.sv-num{font-size:15px;font-weight:800;color:#cdd6f4;min-width:54px;text-align:right}
.sv-comps{display:flex;gap:3px;margin-top:7px;flex-wrap:wrap}
.sv-c{font-size:8px;font-weight:700;padding:2px 4px;border-radius:3px;color:#11111b}
.mk-card{position:absolute;top:248px;left:10px;z-index:20;background:rgba(11,15,13,.92);border:1px solid rgba(63,222,126,.5);border-radius:10px;padding:7px 9px;direction:ltr;width:188px}
.mk-head{font-size:11px;font-weight:800;color:#3FDE7E;margin-bottom:5px}
.mk-cur{font-size:11px;font-weight:800;margin-inline-start:4px;padding:1px 6px;border-radius:4px}
.mk-tbl{border-collapse:collapse;width:100%;font-size:10px;color:#cdd6f4}
.mk-tbl td{text-align:center;padding:2px 3px}
.mk-tbl td.h{color:#6c7086;font-weight:700}
.mk-tbl td.diag{background:rgba(63,222,126,.18);color:#6BF0A6;font-weight:800}
.mk-foot{font-size:9px;color:#6c7086;margin-top:5px}
.scan-board{position:absolute;top:404px;left:10px;z-index:20;background:rgba(13,15,20,.9);border:1px solid #313244;border-radius:10px;padding:6px 8px;direction:ltr;max-height:210px;overflow-y:auto;width:236px}
.scalp-strip{position:absolute;top:126px;left:50%;transform:translateX(-50%);z-index:25;background:rgba(13,15,20,.94);border:1px solid #45475a;border-radius:8px;padding:4px 8px;direction:rtl;display:flex;gap:5px;align-items:center;font-size:11px;white-space:nowrap}
.ss-chip{padding:1px 6px;border-radius:4px;font-weight:700}
.ss-on{background:#a6e3a1;color:#11111b}
.ss-off{background:#45475a;color:#bac2de}
.ss-head{color:#f9e2af;font-weight:800}
.ss-v{font-weight:800;margin-right:4px}
.sb-title{font-size:11px;font-weight:800;color:#cdd6f4;margin-bottom:4px}
.sb-ts{font-size:9px;color:#6c7086;font-weight:600;margin-inline-start:6px}
.sb-tbl{border-collapse:collapse;width:100%;font-size:10px}
.sb-tbl th{color:#6c7086;font-weight:700;text-align:center;padding:2px 3px;border-bottom:1px solid #313244}
.sb-tbl td{text-align:center;padding:2px 3px;color:#cdd6f4}
.sb-tbl tr.row{cursor:pointer}
.sb-tbl tr.row:hover{background:rgba(137,180,250,.15)}
.sb-sym{font-weight:800;text-align:left!important}
.up{color:#a6e3a1}.dn{color:#f38ba8}.neu{color:#6c7086}
.ob{color:#f38ba8;font-weight:800}.os{color:#a6e3a1;font-weight:800}
.acct-chip{font-size:11px;font-weight:700;padding:2px 8px;border-radius:6px;background:#252535;color:#cdd6f4;margin-inline:2px}
.disc-banner{font-size:12px;font-weight:800;padding:3px 12px;border-radius:6px;margin-inline:6px;letter-spacing:.3px}
.disc-ok{background:rgba(166,227,161,.15);color:#a6e3a1}
.disc-warn{background:rgba(243,139,168,.22);color:#f38ba8;animation:discpulse 1.6s ease-in-out infinite}
@keyframes discpulse{0%,100%{opacity:1}50%{opacity:.55}}
.sb-head{padding:7px 10px;font-size:10px;color:#45475a;border-bottom:1px solid #1e1e2e;letter-spacing:.4px}
.sym-grp{border-bottom:1px solid #1e1e2e}
.sym-nm{padding:6px 10px 2px;font-weight:700;font-size:11px;color:#cba6f7}
.tf-row{display:flex;gap:3px;padding:2px 8px 6px;flex-wrap:wrap}
.tfb{background:#1e1e2e;border:1px solid #313244;color:#6c7086;padding:2px 6px;border-radius:4px;cursor:pointer;font-size:10px;font-weight:700;transition:all .12s}
.tfb:hover{background:#313244;color:#cdd6f4}
.tfb.active{background:#313244;border-color:#cba6f7;color:#cba6f7}
.tfb.BUY{border-color:#a6e3a1;color:#a6e3a1}.tfb.SELL{border-color:#f38ba8;color:#f38ba8}

/* ── Main ── */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}

/* Decision row */
.d-row{display:flex;gap:8px;padding:5px 12px;background:#1e1e2e;border-bottom:1px solid #313244;align-items:center;flex-wrap:wrap;flex-shrink:0}
.chip{background:#252535;border-radius:6px;padding:2px 8px;display:flex;flex-direction:column;align-items:center;min-width:62px;border:1px solid #313244}
.cl{font-size:9px;color:#45475a;letter-spacing:.3px;text-transform:uppercase}
.cv{font-size:12px;font-weight:700}
.chip-BUY{background:#0f1f0f;border-color:#a6e3a1}.chip-SELL{background:#1f0f10;border-color:#f38ba8}
.BUY{color:#a6e3a1}.SELL{color:#f38ba8}.HOLD{color:#45475a}

/* Why row */
.why-row{display:flex;gap:6px;padding:4px 12px;background:#111118;border-bottom:1px solid #1e1e2e;align-items:center;flex-wrap:wrap;flex-shrink:0}
.wc{display:flex;align-items:center;gap:3px;background:#1e1e2e;border-radius:4px;padding:2px 6px;white-space:nowrap}
.wl{font-size:9px;color:#45475a}.wv{font-size:11px;font-weight:600}
.up{color:#a6e3a1}.dn{color:#f38ba8}.neu{color:#585b70}
.ok{color:#a6e3a1}.fail{color:#f38ba8}

/* Zone + projection row */
.zone-row{display:flex;gap:12px;padding:3px 12px;background:#0d0f14;border-bottom:1px solid #1e1e2e;align-items:center;font-size:10px;flex-shrink:0;flex-wrap:wrap}
.ze{color:#89b4fa;font-weight:700}.zs{color:#f38ba8}.zt{color:#a6e3a1}
.zp{color:#cba6f7}.zatr{color:#45475a}.sep{color:#252535}
.proj-tag{background:#1e1e2e;border:1px solid #cba6f7;border-radius:4px;padding:1px 6px;font-size:10px;color:#cba6f7}
.acc-tag{background:#1e1e2e;border-radius:4px;padding:1px 6px;font-size:10px}

/* Charts */
.charts-area{flex:1;display:flex;flex-direction:column;overflow:hidden;min-height:0;direction:ltr}
.chart-wrap{position:relative;flex:1;min-height:0}
#cMain{flex:3}
#cRsi,#cMacd,#cStoch{flex:1;border-top:1px solid #1a1a28}
.pl{position:absolute;top:3px;left:6px;right:auto;font-size:11px;font-weight:700;color:#cba6f7;background:rgba(13,15,20,.6);padding:1px 6px;border-radius:4px;z-index:9;pointer-events:none}

/* Levels panel (slide-out) */
#lvl-panel{position:absolute;bottom:0;left:0;right:0;background:#1e1e2e;border-top:2px solid #313244;z-index:20;max-height:200px;overflow-y:auto;transition:transform .2s;transform:translateY(100%)}
#lvl-panel.open{transform:translateY(0)}
.lvl-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:4px;padding:8px 12px}
.lvl-item{background:#252535;border-radius:4px;padding:3px 8px;display:flex;justify-content:space-between;font-size:11px}
.lvl-name{color:#585b70}.lvl-val{font-weight:700;color:#cdd6f4}

/* SMC scalping row */
.smc-row{display:flex;gap:8px;padding:3px 12px;background:#0a0c10;border-bottom:1px solid #1e1e2e;align-items:center;font-size:10px;flex-shrink:0;flex-wrap:wrap}
.smc-trigger{border-radius:4px;padding:2px 8px;font-size:11px;font-weight:700;transition:all .3s}
.smc-chip{background:#1e1e2e;border-radius:4px;padding:1px 6px;white-space:nowrap}
.session-tag{border-radius:3px;padding:1px 5px;font-size:9px;font-weight:700}
#lprice{font-size:12px;font-weight:700;color:#cdd6f4;margin-right:6px;font-variant-numeric:tabular-nums}
/* Loading */
#ld{position:fixed;inset:0;background:rgba(13,15,20,.9);display:flex;align-items:center;justify-content:center;z-index:99;flex-direction:column;gap:6px}
#ld.hidden{display:none}
#ld span{font-size:16px;color:#cba6f7}
#ld small{font-size:11px;color:#45475a}
</style>
</head>
<body>
<div id="ld"><span>Algory Intelligence</span><small>جاري تحميل التحليل…</small></div>

<header>
  <span id="live-dot"></span>
  <h1>Algory Intelligence</h1>
  <span id="lprice">—</span>
  <select id="symPick" onchange="pickSym(this.value)" title="اختر العملة"
    style="background:#0f1623;color:#e8c46a;border:1px solid #2a3550;border-radius:6px;padding:3px 8px;font-weight:700;font-size:13px;cursor:pointer;outline:none;"></select>
  <div class="gold-tf" id="gold-tf">
    <button class="tfb" data-tf="M1"  onclick="loadTF('M1')">M1</button>
    <button class="tfb" data-tf="M5"  onclick="loadTF('M5')">M5</button>
    <button class="tfb" data-tf="M15" onclick="loadTF('M15')">M15</button>
    <button class="tfb" data-tf="H1"  onclick="loadTF('H1')">H1</button>
    <button class="tfb" data-tf="H4"  onclick="loadTF('H4')">H4</button>
  </div>
  <span id="ts">—</span>
  <span id="acc-badge">دقة: —</span>
  <span class="acct-chip" id="acct-eq" title="الحقوق">حقوق —</span>
  <span class="acct-chip" id="acct-ml" title="مستوى الهامش">هامش —</span>
  <span class="acct-chip" id="acct-fl" title="الربح/الخسارة العائم">عائم —</span>
  <span class="disc-banner" id="disc-banner">—</span>
  <button class="hbtn" onclick="toggleLevels()">مستويات ↕</button>
  <button class="hbtn" onclick="refreshNow()">↺</button>
</header>

<div class="layout">
  <div class="main" style="position:relative">
    <!-- Decision -->
    <div class="d-row">
      <div class="chip chip-HOLD" id="chip-act"><span class="cl">التحليل</span><span class="cv HOLD" id="dact">—</span></div>
      <div class="chip" id="chip-runner"><span class="cl">Runner ⚙</span><span class="cv HOLD" id="drunner">—</span></div>
      <div class="chip"><span class="cl">رمز</span><span class="cv" id="dsym">—</span></div>
      <div class="chip"><span class="cl">إطار</span><span class="cv" id="dtf">—</span></div>
      <div class="chip"><span class="cl">R:R</span><span class="cv" id="drr">—</span></div>
      <div class="chip"><span class="cl">Conf</span><span class="cv" id="dconf">—</span></div>
      <div class="chip"><span class="cl">سبب</span><span class="cv" id="dreason" style="font-size:10px">—</span></div>
      <div class="chip"><span class="cl">Genome</span><span class="cv" id="dgid" style="font-size:9px">—</span></div>
    </div>

    <!-- Why -->
    <div class="why-row">
      <div class="wc"><span class="wl">إشارة</span><span class="wv" id="wsig">—</span></div>
      <div class="wc"><span class="wl">تحيز</span><span class="wv" id="wbias">—</span></div>
      <div class="wc"><span class="wl">فلتر</span><span class="wv" id="wfilt">—</span></div>
      <div class="wc"><span class="wl">RSI</span><span class="wv" id="wrsi">—</span></div>
      <div class="wc"><span class="wl">MACD</span><span class="wv" id="wmacd">—</span></div>
      <div class="wc"><span class="wl">Stoch</span><span class="wv" id="wstoch">—</span></div>
      <div class="wc"><span class="wl">ADX</span><span class="wv" id="wadx">—</span></div>
      <div class="wc"><span class="wl">جينات</span><span class="wv" id="wgenes">—</span></div>
    </div>

    <!-- Zone + projection -->
    <div class="zone-row">
      <span class="ze" id="ze">—</span>
      <span class="sep">→</span><span class="zs" id="zsl">—</span>
      <span class="sep">→</span><span class="zt" id="ztp">—</span>
      <span class="sep">|</span>
      <span class="zp" id="zproj">—</span>
      <span class="sep">|</span>
      <span class="zatr" id="zatr">—</span>
      <span class="acc-tag" id="zacc">—</span>
    </div>

    <!-- SMC scalping row -->
    <div class="smc-row">
      <span class="smc-trigger" id="smc-trigger">— لا توجد فرصة</span>
      <span class="sep">|</span>
      <span class="smc-chip" id="smc-spread">Spread: —</span>
      <span class="smc-chip" id="smc-session">—</span>
      <span class="sep">|</span>
      <span class="smc-chip" id="smc-ob">OB: —</span>
      <span class="smc-chip" id="smc-fvg">FVG: —</span>
      <span class="smc-chip" id="smc-bos">BOS: —</span>
      <span class="smc-chip" id="smc-eqhl">EQ: —</span>
      <span class="sep">|</span>
      <span id="frac-status"></span>
    </div>

    <!-- Live multi-pair MARKET BOARD (click a row to load that symbol) -->
    <div class="scan-board" id="scan-board">
      <div class="sb-title">📡 السوق <span id="scan-ts" class="sb-ts"></span></div>
      <table class="sb-tbl"><thead><tr>
        <th>زوج</th><th>اتج</th><th>ADX</th><th>RSI</th><th>Sto</th><th>OB</th><th>بنية</th>
      </tr></thead><tbody id="scan-body"></tbody></table>
    </div>

    <!-- Scalper live entry-conditions strip (the 5 gates gold_live checks) -->
    <div class="scalp-strip" id="scalp-strip" style="display:none">
      <span class="ss-head" id="ss-head">سكالبر</span>
      <span id="ss-chips"></span>
      <span class="ss-v" id="ss-verdict"></span>
    </div>

    <!-- Sentiment vial (CONTEXT only, not a forecast) -->
    <div class="sent-vial" id="sent-vial">
      <div class="sv-head">🧪 Sentiment <span class="sv-ctx">سياق</span></div>
      <div class="sv-row"><div class="sv-meter"><div class="sv-fill" id="sv-fill"></div></div>
        <div class="sv-num"><span id="sv-pct">—</span><span id="sv-face">·</span></div></div>
      <div class="sv-comps" id="sv-comps"></div>
    </div>

    <!-- Markov regime card -->
    <div class="mk-card" id="mk-card">
      <div class="mk-head">⛓ MARKOV <span id="mk-cur" class="mk-cur">—</span></div>
      <table class="mk-tbl"><tbody id="mk-body"></tbody></table>
      <div class="mk-foot" id="mk-foot">—</div>
    </div>

    <!-- Charts -->
    <div class="charts-area">
      <div class="chart-wrap" id="cMain"><span class="pl">OHLC · EMA · Fractals · Levels</span></div>
      <div class="chart-wrap" id="cRsi"><span class="pl">RSI</span></div>
      <div class="chart-wrap" id="cMacd"><span class="pl">MACD</span></div>
      <div class="chart-wrap" id="cStoch"><span class="pl">Stoch</span></div>
    </div>

    <!-- Levels panel -->
    <div id="lvl-panel">
      <div class="lvl-grid" id="lvl-grid"></div>
    </div>
  </div>

  <div class="sidebar">
    <div class="sb-head">ALGORY · العملات</div>
    <div id="sym-list"></div>
  </div>
</div>

<script>
const CO={layout:{background:{color:'#0d0f14'},textColor:'#cdd6f4'},
  grid:{vertLines:{color:'#111118'},horzLines:{color:'#111118'}},
  timeScale:{timeVisible:true,secondsVisible:false,borderColor:'#1e1e2e'},
  crosshair:{mode:1},rightPriceScale:{borderColor:'#1e1e2e'}};

let charts={},series={};
let keyLines=[],projLines=[],entryLines=[],smcLines=[],fractalLines=[];
let currentKey=null, allSymbols=[], timer=null, tickTimer=null;
let lastCandle=null, currentSym=null;
let lastMarkov=null, regimeLine=null;   // live regime label beside the last candle
const TF_ORDER=['M1','M5','M15','H1','H4'];
const TF_SECS={M1:60,M5:300,M15:900,M30:1800,H1:3600,H4:14400,D1:86400};

// LEVEL DEFINITIONS (drawn on chart)
const LEVEL_DEFS=[
  {k:'pivot',     lbl:'PP',   color:'#cdd6f4', style:0, w:1},
  {k:'r1',        lbl:'R1',   color:'#f38ba8', style:2, w:1},
  {k:'r2',        lbl:'R2',   color:'#f38ba8', style:1, w:1},
  {k:'r3',        lbl:'R3',   color:'#eba0ac', style:3, w:1},
  {k:'s1',        lbl:'S1',   color:'#a6e3a1', style:2, w:1},
  {k:'s2',        lbl:'S2',   color:'#a6e3a1', style:1, w:1},
  {k:'s3',        lbl:'S3',   color:'#94e2d5', style:3, w:1},
  {k:'prev_high', lbl:'PDH',  color:'#fab387', style:2, w:1},
  {k:'prev_low',  lbl:'PDL',  color:'#a6e3a1', style:2, w:1},
  {k:'today_open',lbl:'DO',   color:'#f9e2af', style:2, w:1},
  {k:'today_high',lbl:'DH',   color:'#fab387', style:3, w:1},
  {k:'today_low', lbl:'DL',   color:'#a6e3a1', style:3, w:1},
  {k:'week_high', lbl:'WH',   color:'#cba6f7', style:1, w:1},
  {k:'week_low',  lbl:'WL',   color:'#cba6f7', style:1, w:1},
  {k:'month_high',lbl:'MH',   color:'#b4befe', style:0, w:2},
  {k:'month_low', lbl:'ML',   color:'#b4befe', style:0, w:2},
  {k:'h4_resist1',lbl:'H4R1', color:'#89dceb', style:2, w:1},
  {k:'h4_resist2',lbl:'H4R2', color:'#89dceb', style:3, w:1},
  {k:'h4_support1',lbl:'H4S1',color:'#89b4fa', style:2, w:1},
  {k:'h4_support2',lbl:'H4S2',color:'#89b4fa', style:3, w:1},
];

function initCharts(){
  ['cMain','cRsi','cMacd','cStoch'].forEach(id=>{
    if(charts[id]) charts[id].remove();
    const el=document.getElementById(id);
    charts[id]=LightweightCharts.createChart(el,{...CO,width:el.clientWidth,height:el.clientHeight});
  });
  series.candle=charts.cMain.addCandlestickSeries({upColor:'#a6e3a1',downColor:'#f38ba8',borderUpColor:'#a6e3a1',borderDownColor:'#f38ba8',wickUpColor:'#a6e3a1',wickDownColor:'#f38ba8'});
  series.ema   =charts.cMain.addLineSeries({color:'#45475a',lineWidth:1,priceLineVisible:false});
  series.proj  =charts.cMain.addLineSeries({color:'rgba(203,166,247,.6)',lineWidth:2,lineStyle:2,priceLineVisible:false,lastValueVisible:false});
  series.proj2 =charts.cMain.addLineSeries({color:'rgba(166,227,161,.85)',lineWidth:2,priceLineVisible:false,lastValueVisible:true,crosshairMarkerVisible:true});
  // ghost FUTURE candles for the fractal projection (drawn, not a line)
  series.projCandle=charts.cMain.addCandlestickSeries({priceLineVisible:false,lastValueVisible:false,
    upColor:'rgba(166,227,161,.35)',downColor:'rgba(243,139,168,.35)',
    borderUpColor:'rgba(166,227,161,.6)',borderDownColor:'rgba(243,139,168,.6)',
    wickUpColor:'rgba(166,227,161,.5)',wickDownColor:'rgba(243,139,168,.5)'});
  series.rsi   =charts.cRsi.addLineSeries({color:'#cba6f7',lineWidth:1.5,priceLineVisible:false});
  series.rsiOB =charts.cRsi.addLineSeries({color:'rgba(243,139,168,.2)',lineWidth:1,lastValueVisible:false,priceLineVisible:false});
  series.rsiOS =charts.cRsi.addLineSeries({color:'rgba(166,227,161,.2)',lineWidth:1,lastValueVisible:false,priceLineVisible:false});
  series.macdL =charts.cMacd.addLineSeries({color:'#89dceb',lineWidth:1.5,priceLineVisible:false});
  series.macdS =charts.cMacd.addLineSeries({color:'#fab387',lineWidth:1,priceLineVisible:false});
  series.macdH =charts.cMacd.addHistogramSeries({color:'#a6e3a1',priceLineVisible:false});
  series.skL   =charts.cStoch.addLineSeries({color:'#89b4fa',lineWidth:1.5,priceLineVisible:false});
  series.sdL   =charts.cStoch.addLineSeries({color:'#f9e2af',lineWidth:1,priceLineVisible:false});
  // Crosshair sync
  charts.cMain.subscribeCrosshairMove(p=>{
    if(!p.time) return;
    ['cRsi','cMacd','cStoch'].forEach(id=>{ try{charts[id].setCrosshairPosition(p.point.y,p.time,series.rsi);}catch(e){} });
  });
  new ResizeObserver(()=>{
    ['cMain','cRsi','cMacd','cStoch'].forEach(id=>{
      const el=document.getElementById(id);
      if(charts[id]) charts[id].resize(el.clientWidth,el.clientHeight);
    });
  }).observe(document.querySelector('.charts-area'));
}

// ── Clear / draw key levels ───────────────────────────────────────────────────
function clearKeyLines(){
  keyLines.forEach(l=>{try{series.candle.removePriceLine(l);}catch(e){}});
  keyLines=[];
}
function drawKeyLevels(levels){
  clearKeyLines();
  if(!levels) return;
  LEVEL_DEFS.forEach(def=>{
    const v=levels[def.k];
    if(v && v>0){
      keyLines.push(series.candle.createPriceLine({
        price:v, color:def.color, lineWidth:def.w,
        lineStyle:def.style, axisLabelVisible:true, title:def.lbl
      }));
    }
  });
}

// ── Clear / draw entry lines ──────────────────────────────────────────────────
function clearEntryLines(){
  entryLines.forEach(l=>{try{series.candle.removePriceLine(l);}catch(e){}});
  entryLines=[];
}
function drawEntryLines(d){
  clearEntryLines();
  if(d.action==='HOLD'||!d.entry) return;
  const mk=(price,color,title)=>entryLines.push(series.candle.createPriceLine({price,color,lineWidth:1,lineStyle:0,axisLabelVisible:true,title}));
  mk(d.entry,'#89b4fa','Entry');
  if(d.sl) mk(d.sl,'#f38ba8',`SL ${d.why.sl_pips}p`);
  if(d.tp) mk(d.tp,'#a6e3a1',`TP +${d.why.tp_pips}p`);
}

// ── Time-anchored ZONES (boxes/rays drawn ON the candles, not stacked on the axis) ──
let zonePrims=[];
function hasPrim(){ return series.candle && typeof series.candle.attachPrimitive==='function'; }
function _rightTime(){ return (typeof lastCandle!=='undefined' && lastCandle && lastCandle.time)?lastCandle.time:undefined; }
class ZonePrimitive{
  constructor(t1,t2,p1,p2,o){this.t1=t1;this.t2=t2;this.p1=p1;this.p2=p2;this.o=o||{};this.chart=null;this.ser=null;}
  attached(p){this.chart=p.chart;this.ser=p.series;this.req=p.requestUpdate;}
  detached(){this.chart=null;this.ser=null;}
  updateAllViews(){}
  paneViews(){ const s=this; return [{ renderer(){ return { draw(target){ target.useBitmapCoordinateSpace(function(scope){
    if(!s.chart||!s.ser) return;
    const ts=s.chart.timeScale();
    let x1=ts.timeToCoordinate(s.t1); if(x1==null) x1=0;
    let x2=(s.t2==null)?scope.mediaSize.width:ts.timeToCoordinate(s.t2); if(x2==null) x2=scope.mediaSize.width;
    const y1=s.ser.priceToCoordinate(s.p1); if(y1==null) return;
    const y2=(s.p2==null)?y1:s.ser.priceToCoordinate(s.p2); if(s.p2!=null && y2==null) return;
    const ctx=scope.context, hr=scope.horizontalPixelRatio, vr=scope.verticalPixelRatio;
    const L=Math.min(x1,x2)*hr, R=Math.max(x1,x2)*hr;
    if(s.p2==null){ // RAY: horizontal segment at p1 from origin → right edge
      const y=y1*vr; ctx.strokeStyle=s.o.border||s.o.fill||'#888'; ctx.lineWidth=(s.o.lw||1)*vr;
      if(s.o.dash){ctx.setLineDash([4*hr,3*hr]);} ctx.beginPath(); ctx.moveTo(L,y); ctx.lineTo(R,y); ctx.stroke(); ctx.setLineDash([]);
    } else { // BOX
      const T=Math.min(y1,y2)*vr, B=Math.max(y1,y2)*vr;
      ctx.fillStyle=s.o.fill||'rgba(255,255,255,.08)'; ctx.fillRect(L,T,R-L,Math.max(B-T,1));
      if(s.o.border){ctx.strokeStyle=s.o.border;ctx.lineWidth=1*vr;ctx.strokeRect(L,T,R-L,Math.max(B-T,1));}
    }
    if(s.o.label){ const yy=(s.p2==null?y1:Math.min(y1,y2))*vr; ctx.font=(Math.round(11*vr))+'px sans-serif'; ctx.fillStyle=s.o.lblColor||s.o.border||'#cdd6f4'; ctx.textBaseline='bottom'; ctx.fillText(s.o.label, L+3*hr, yy-2*vr); }
  }); } }; } }]; }
}
function clearZones(){ zonePrims.forEach(z=>{ try{ if(z.__line) series.candle.removePriceLine(z.__line); else series.candle.detachPrimitive(z); }catch(e){} }); zonePrims=[]; }
function zoneBox(t1,top,bot,o){ // box from t1 → current right edge, [bot..top]
  if(hasPrim()){ const z=new ZonePrimitive(t1||_rightTime(),_rightTime(),top,bot,o); try{series.candle.attachPrimitive(z);zonePrims.push(z);}catch(e){} }
  else { const h=series.candle.createPriceLine({price:top,color:(o.border||o.fill||'#888'),lineWidth:1,lineStyle:0,axisLabelVisible:true,title:(o.label||'')}); zonePrims.push({__line:h}); }
}
function zoneRay(t1,price,o){ // horizontal segment at price from t1 → current right edge
  if(hasPrim()){ const z=new ZonePrimitive(t1||_rightTime(),_rightTime(),price,null,o); try{series.candle.attachPrimitive(z);zonePrims.push(z);}catch(e){} }
  else { const h=series.candle.createPriceLine({price:price,color:(o.border||'#888'),lineWidth:(o.lw||1),lineStyle:(o.dash?2:0),axisLabelVisible:true,title:(o.label||'')}); zonePrims.push({__line:h}); }
}

// ── SMC drawing ──────────────────────────────────────────────────────────────
function clearSMCLines(){
  smcLines.forEach(l=>{try{series.candle.removePriceLine(l);}catch(e){}});
  smcLines=[];
}
function drawSMC(d){
  clearSMCLines();
  clearZones();                     // single zone-clear per frame (SMC runs first among zone drawers)
  const smc=d.smc;
  if(!smc) return;
  // Order Blocks → filled BOX from the block's candle → now
  (smc.ob||[]).forEach(ob=>{
    const bull=ob.type==='bull';
    zoneBox(ob.time, ob.top, ob.bottom, {
      fill: bull?'rgba(166,227,161,.16)':'rgba(243,139,168,.16)',
      border: bull?'rgba(166,227,161,.85)':'rgba(243,139,168,.85)',
      label: bull?'OB+':'OB-', lblColor: bull?'#a6e3a1':'#f38ba8'});
  });
  // Fair Value Gaps → filled BOX. Gaps the price can still travel to = GAP-FILL
  // TARGETS (the user's method). Label them with the live-measured fill-rate.
  const _cur = (typeof lastCandle!=='undefined'&&lastCandle)?lastCandle.close:null;
  const _gs = (d.market_projection&&d.market_projection.gap_stats)?d.market_projection.gap_stats:null;
  const _fr = _gs&&_gs.fill_rate!=null ? Math.round(_gs.fill_rate*100) : null;
  (smc.fvg||[]).forEach(fvg=>{
    const bull=fvg.type==='bull';
    // a bullish gap BELOW price (or bearish gap ABOVE) is an unfilled target price may travel to
    const isTargetBelow = _cur!=null && fvg.top < _cur;
    const isTargetAbove = _cur!=null && fvg.bottom > _cur;
    const isTarget = isTargetBelow || isTargetAbove;
    if(isTarget){
      const lbl = '🎯 '+(isTargetBelow?'هدف↓':'هدف↑')+(_fr!=null?(' ملء '+_fr+'%'):'');
      zoneBox(fvg.time, fvg.top, fvg.bottom, {
        fill:'rgba(249,226,175,.20)', border:'#f9e2af', label:lbl, lblColor:'#f9e2af'});
      return;
    }
    zoneBox(fvg.time, fvg.top, fvg.bottom, {
      fill: bull?'rgba(137,220,235,.16)':'rgba(203,166,247,.16)',
      border: bull?'rgba(137,220,235,.8)':'rgba(203,166,247,.8)',
      label: bull?'FVG+':'FVG-', lblColor: bull?'#89dceb':'#cba6f7'});
  });
  // BOS / CHoCH → dashed RAY at the break price, starting AT the break candle
  (smc.bos||[]).forEach(b=>{
    const bull=b.type.includes('bull');
    const lbl=b.type.replace('_bull','↑').replace('_bear','↓');
    zoneRay(b.time, b.price, {border: bull?'#a6e3a1':'#f38ba8', lw:2, dash:true, label:lbl});
  });
  // Equal H/L (liquidity) → dotted RAY from where the level formed
  (smc.eqhl||[]).forEach(eq=>{
    const eqh=eq.type==='EQH';
    zoneRay(eq.time, eq.price, {border: eqh?'rgba(243,139,168,.8)':'rgba(166,227,161,.8)', lw:1, dash:true, label:eq.type});
  });
  // Update SMC row
  const tr=smc.trigger||'none';
  const el=document.getElementById('smc-trigger');
  if(tr!=='none'){
    const buy=tr.includes('BUY');
    el.textContent='⚡ '+(smc.trigger_reason||tr);
    el.style.color=buy?'#a6e3a1':'#f38ba8';
    el.style.background=buy?'rgba(166,227,161,.12)':'rgba(243,139,168,.12)';
  } else {
    el.textContent='— لا توجد فرصة مضاربة';
    el.style.color='#45475a';
    el.style.background='transparent';
  }
  const obs=smc.ob||[];
  document.getElementById('smc-ob').textContent='OB:'+obs.length+'('+obs.filter(o=>o.type==='bull').length+'+/'+obs.filter(o=>o.type==='bear').length+'-)';
  document.getElementById('smc-fvg').textContent='FVG:'+(smc.fvg||[]).length;
  const bl=smc.bos||[];
  if(bl.length){
    const last=bl[bl.length-1];
    const bosEl=document.getElementById('smc-bos');
    bosEl.textContent=last.type.replace('_bull','↑').replace('_bear','↓')+' @'+last.price;
    bosEl.style.color=last.type.includes('bull')?'#a6e3a1':'#f38ba8';
  } else {
    document.getElementById('smc-bos').textContent='BOS:—';
    document.getElementById('smc-bos').style.color='#45475a';
  }
  document.getElementById('smc-eqhl').textContent='EQ:'+(smc.eqhl||[]).length;
}

// ── Fractal structure drawing ─────────────────────────────────────────────────
function clearFractalLines(){
  fractalLines.forEach(l=>{try{series.candle.removePriceLine(l);}catch(e){}});
  fractalLines=[];
  series.proj2.setData([]);
  if(series.projCandle) series.projCandle.setData([]);
}
function drawProtectedLevels(d){
  const fs=d.fractal_structure;
  if(!fs) return;
  // protected high/low → solid RAY from the swing that created it → now
  if(fs.protected_high>0)
    zoneRay(fs.protected_high_time, fs.protected_high, {border:'#fab387', lw:3, label:'PH'});
  if(fs.protected_low>0)
    zoneRay(fs.protected_low_time, fs.protected_low, {border:'#94e2d5', lw:3, label:'PL'});
}
function drawStructureEvents(d){
  const fs=d.fractal_structure;
  if(!fs) return;
  (fs.structure_events||[]).slice(-8).forEach(ev=>{
    const bull=ev.kind.includes('bull');
    const choch=ev.kind.startsWith('CHoCH');
    const c=bull?'#a6e3a1':'#f38ba8';
    const lbl=ev.kind.replace('_bull','↑').replace('_bear','↓');
    // RAY at the event price, anchored AT the candle where structure broke
    zoneRay(ev.time, ev.price, {border:c, lw:choch?2:1, dash:!choch, label:lbl});
  });
}
function drawProjectionPath(d){
  const mp=d.market_projection;
  series.proj2.setData([]);                       // no line — we draw CANDLES
  if(series.projCandle) series.projCandle.setData([]);
  if(!mp) return;
  const dir=mp.direction;
  if(dir!=='UP'&&dir!=='DOWN') return;            // SIDEWAYS → nothing to project
  const col=dir==='UP'?'rgba(166,227,161,.9)':'rgba(243,139,168,.9)';
  // ── FRACTAL ANALOG candles: replay the most similar past pattern (self-similar) ──
  const cs=d.candles||[];
  if(cs.length>=5 && series.projCandle){
    const tf=(currentKey||'|M1').split('|')[1];
    const tfSec=TF_SECS[tf]||60;
    const t0=cs[cs.length-1].time;
    const fcs=mp.fractal_candles||[];
    let ghost=[];
    if(fcs.length){
      // REAL analog projection from the backend — each bar coloured by its own direction
      fcs.forEach((b,i)=>{
        const up=b.close>=b.open;
        ghost.push({time:t0+tfSec*(i+1), open:b.open, high:b.high, low:b.low, close:b.close,
          color: up?'rgba(166,227,161,.32)':'rgba(243,139,168,.32)',
          borderColor: up?'rgba(166,227,161,.7)':'rgba(243,139,168,.7)',
          wickColor: up?'rgba(166,227,161,.55)':'rgba(243,139,168,.55)'});
      });
    } else {
      // fallback (no analog found): faint eased drift toward final target
      let n=Math.min(14,cs.length), rng=0;
      for(let i=cs.length-n;i<cs.length;i++) rng+=(cs[i].high-cs[i].low);
      const wick=Math.max(rng/n*0.35,1e-6);
      const entry=(mp.entry&&mp.entry>0)?mp.entry:cs[cs.length-1].close;
      const fin=(mp.targets&&mp.targets.length)?mp.targets[mp.targets.length-1].price:((mp.target&&mp.target>0)?mp.target:entry);
      let prev=entry; const up=dir==='UP';
      for(let i=1;i<=12;i++){
        const prog=1-Math.exp(-i*0.42); const px=entry+(fin-entry)*prog;
        ghost.push({time:t0+tfSec*i, open:prev, high:Math.max(prev,px)+wick*0.5, low:Math.min(prev,px)-wick*0.5, close:px,
          color: up?'rgba(166,227,161,.22)':'rgba(243,139,168,.22)', borderColor:col});
        prev=px;
      }
    }
    series.projCandle.setData(ghost);
  }
  // future-anchored level helpers (draw in the projection region)
  const t1now=_rightTime();
  const futT2=(mp.path&&mp.path.length)?mp.path[mp.path.length-1].time:(t1now+ (TF_SECS[(currentKey||'|M1').split('|')[1]]||60)*12);
  const addFutRay=(price,o)=>{ if(hasPrim()){const z=new ZonePrimitive(t1now,futT2,price,null,o);try{series.candle.attachPrimitive(z);zonePrims.push(z);}catch(e){}} else {const h=series.candle.createPriceLine({price,color:(o.border||col),lineWidth:(o.lw||1),lineStyle:3,axisLabelVisible:true,title:(o.label||'')});zonePrims.push({__line:h});} };
  const addFutBox=(top,bot,o)=>{ if(hasPrim()){const z=new ZonePrimitive(t1now,futT2,top,bot,o);try{series.candle.attachPrimitive(z);zonePrims.push(z);}catch(e){}} };
  // laddered targets (TP1..TPn) → rays in the projection region, labelled with R
  (mp.targets||[]).forEach((t,i)=>{
    addFutRay(t.price, {border:col, lw:1, label:'TP'+(i+1)+(t.r?(' '+t.r+'R'):''), lblColor:col});
  });
  // target zone band → faint box
  if(mp.target_zone&&mp.target_zone.high){
    addFutBox(mp.target_zone.high, mp.target_zone.low, {fill: dir==='UP'?'rgba(166,227,161,.08)':'rgba(243,139,168,.08)'});
  }
  // Invalidation (stop) → ray in the projection region
  if(mp.invalidation>0){
    const ic=dir==='UP'?'rgba(243,139,168,.9)':'rgba(166,227,161,.9)';
    addFutRay(mp.invalidation, {border:ic, lw:2, dash:true, label:'INVAL'});
  }
}

// ── Runner state display ──────────────────────────────────────────────────────
// ── Volume Profile: POC / VAH / VAL ───────────────────────────────────────────
let vpLines=[];
function clearVP(){ vpLines.forEach(l=>{try{series.candle.removePriceLine(l);}catch(e){}}); vpLines=[]; }
function drawVP(d){
  clearVP();
  const vp=(d.market_projection&&d.market_projection.vp)?d.market_projection.vp:null;
  if(!vp||!vp.poc) return;
  // POC = bold magnet; VAH/VAL = dashed value-area edges
  vpLines.push(series.candle.createPriceLine({price:vp.poc,color:'#f9e2af',lineWidth:2,lineStyle:0,axisLabelVisible:true,title:'POC '+vp.poc.toFixed(2)}));
  if(vp.vah) vpLines.push(series.candle.createPriceLine({price:vp.vah,color:'rgba(249,226,175,.6)',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'VAH'}));
  if(vp.val) vpLines.push(series.candle.createPriceLine({price:vp.val,color:'rgba(249,226,175,.6)',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'VAL'}));
}
let runnerLines=[];
function clearRunnerLines(){
  runnerLines.forEach(l=>{try{series.candle.removePriceLine(l);}catch(e){}});
  runnerLines=[];
}
function renderRunnerState(d){
  clearRunnerLines();
  const r=d.runner||{};
  const act=r.in_trade?r.action:'IDLE';
  const el=document.getElementById('drunner');
  const chip=document.getElementById('chip-runner');
  if(r.in_trade){
    el.textContent=r.action+' '+r.lot+'L';
    el.className='cv '+(r.action==='BUY'?'BUY':'SELL');
    chip.className='chip '+(r.action==='BUY'?'chip-BUY':'chip-SELL');
    // Draw runner's actual trade levels (thicker, distinct from analysis)
    if(r.entry) runnerLines.push(series.candle.createPriceLine({price:r.entry,color:'#89b4fa',lineWidth:2,lineStyle:0,axisLabelVisible:true,title:'R-Entry'}));
    if(r.sl)    runnerLines.push(series.candle.createPriceLine({price:r.sl,   color:'#f38ba8',lineWidth:2,lineStyle:0,axisLabelVisible:true,title:'R-SL'}));
    if(r.tp)    runnerLines.push(series.candle.createPriceLine({price:r.tp,   color:'#a6e3a1',lineWidth:2,lineStyle:0,axisLabelVisible:true,title:'R-TP'}));
  } else if(r.cooldown_left>0){
    el.textContent='CD '+r.cooldown_left+'s';
    el.className='cv HOLD';
    chip.className='chip';
  } else {
    const ls=r.last_signal||0;
    el.textContent=ls===1?'انتظر BUY':ls===-1?'انتظر SELL':'IDLE';
    el.className='cv '+(ls===1?'BUY':ls===-1?'SELL':'HOLD');
    chip.className='chip';
  }
}

// ── Fractal status display ────────────────────────────────────────────────────
function renderFractalStatus(d){
  const fs=d.fractal_structure||{};
  const mp=d.market_projection||{};
  const el=document.getElementById('frac-status');
  if(!el) return;
  const bias=fs.structure_bias||'neutral';
  const qual=fs.trend_quality||'';
  const dir=mp.direction||'—';
  const conf=mp.confidence?Math.round(mp.confidence*100)+'%':'—';
  const biasCls=bias==='bullish'?'up':bias==='bearish'?'dn':'neu';
  const dirCls=dir==='UP'?'up':dir==='DOWN'?'dn':'neu';
  const bos=fs.bos_recent?'<span style="color:#a6e3a1">BOS</span>':'';
  const choch=fs.choch_recent?'<span style="color:#cba6f7">CHoCH</span>':'';
  const sw=fs.sweep_recent?'<span style="color:#fab387">SW</span>':'';
  // HONESTY chip: prefer the LIVE self-tuning score (self-graded forward hit-rate),
  // else fall back to the static OOS validator verdict.
  let accChip='';
  const ss=mp.self_score;
  if(ss&&ss.best_dir_hit!=null&&ss.samples>0){
    const pct=Math.round(ss.best_dir_hit*100);
    const ok=ss.best_dir_hit>=0.55;
    accChip=`<span class="smc-chip" style="background:${ok?'rgba(166,227,161,.15)':'rgba(243,139,168,.15)'};color:${ok?'#a6e3a1':'#f38ba8'};font-weight:700" title="سكور الضبط الذاتي الحيّ — نسبة إصابة الاتجاه فعلياً (يضبط نفسه كل بار)">`+
      `🎯 سكور حيّ ${pct}% ${ok?'✓':'⚠ سياق'} ${ss.active||''}</span>`;
  } else {
    const acc=mp.analog_accuracy;
    if(acc&&acc.hit_hi!=null){
      const pct=Math.round(acc.hit_hi*100);
      const ok=acc.predictive;
      accChip=`<span class="smc-chip" style="background:${ok?'rgba(166,227,161,.15)':'rgba(243,139,168,.15)'};color:${ok?'#a6e3a1':'#f38ba8'};font-weight:700" title="دقّة الإسقاط خارج العيّنة (تطابق≥80%)">`+
        `دقّة الفراكتال ${pct}% ${ok?'✓':'⚠ سياق فقط'}</span>`;
    }
  }
  // GAP-FILL SETUP chip (the user's method): bearish structure + unfilled gap below
  // → sell-toward-gap setup, with the live-measured fill-rate in this context.
  let gapChip='';
  const cur=(typeof lastCandle!=='undefined'&&lastCandle)?lastCandle.close:null;
  const gs=mp.gap_stats;
  const fvgs=(d.smc&&d.smc.fvg)?d.smc.fvg:[];
  const below=cur!=null?fvgs.filter(f=>f.top<cur):[];
  if(cur!=null && bias==='bearish' && below.length && gs){
    const tgt=below.sort((a,b)=>b.top-a.top)[0];
    const fr=gs.fill_bearish!=null&&gs.fill_bearish!=='n/a'?Math.round(gs.fill_bearish*100):(gs.fill_rate!=null?Math.round(gs.fill_rate*100):null);
    gapChip=`<span class="smc-chip" style="background:rgba(249,226,175,.18);color:#f9e2af;font-weight:700" title="نمطك: هيكل هابط + فجوة سفلية غير ممتلئة → بيع نحو الفجوة. النسبة = ملء الفجوة في سياق هابط (مقاس OOS)">`+
      `📉 إعداد فجوة → ${tgt.top.toFixed(2)}${fr!=null?(' · ملء '+fr+'%'):''}</span>`;
  }
  // ── (ب) VOLATILITY / RANGE regime — the ONE OOS-real signal. Predicts HOW MUCH (range),
  //     never which way. Drives target sizing. Shown PROMINENTLY (it's actionable). ──
  let volChip='';
  const vr=mp.vol_regime;
  if(vr&&vr.state&&vr.state!=='unknown'){
    const map={expansion:['🌊','#89dceb','rgba(137,220,235,.18)'],
               contraction:['🧊','#f9e2af','rgba(249,226,175,.18)'],
               normal:['〰️','#6c7086','rgba(108,112,134,.15)']};
    const m=map[vr.state]||map.normal;
    const mult=vr.target_mult!=null?('×'+vr.target_mult):'';
    volChip=`<span class="smc-chip" style="background:${m[2]};color:${m[1]};font-weight:800" `+
      `title="تذبذب/مدى (قِيس OOS = إشارة حقيقية ثانوية). يحجّم الهدف فقط، لا يقرّر الاتجاه. مئوية ATR ${vr.pctile}">`+
      `${m[0]} ${vr.note} ${mult?('· هدف '+mult):''}</span>`;
  }
  // ── (أ) CONTEXT banner: the fractal/analog projection is NOT an entry signal. Make it
  //     unmistakable so it's never traded as direction (OOS: direction ~50% = coin flip). ──
  const ctxChip=`<span class="smc-chip" style="background:rgba(108,112,134,.22);color:#a4abb7;font-weight:800;border:1px dashed #6c7086" `+
    `title="الفراكتل/الأنالوج: تطابق نمط ماضٍ. اختُبر OOS = لا يتنبأ بالاتجاه (~50%). للسياق فقط — لا تدخل عليه.">`+
    `⚠ سياق — ليست إشارة دخول</span>`;
  // Projection direction shown muted (neutral tone) so it doesn't read as a buy/sell call.
  el.innerHTML=
    volChip+
    ctxChip+
    `<span class="smc-chip" style="opacity:.72">Frac: <span class="${biasCls}">${bias}</span> · ${qual}</span>`+
    `<span class="smc-chip" style="opacity:.72">Proj(سياق): <span class="neu">${dir}</span> ${conf}</span>`+
    gapChip+
    accChip+
    (bos?`<span class="smc-chip">${bos}</span>`:'')+
    (choch?`<span class="smc-chip">${choch}</span>`:'')+
    (sw?`<span class="smc-chip">${sw}</span>`:'');
}

// ── Tick feed (1 second) ──────────────────────────────────────────────────────
function getSession(){
  const h=new Date().getUTCHours();
  const s=[];
  if(h>=0&&h<9)  s.push('<span class="session-tag" style="background:#1a2a3a;color:#89b4fa">Tokyo</span>');
  if(h>=7&&h<16) s.push('<span class="session-tag" style="background:#1a2e1a;color:#a6e3a1">London</span>');
  if(h>=13&&h<21)s.push('<span class="session-tag" style="background:#2e1a1a;color:#f38ba8">NY</span>');
  return s.length?s.join(' '):'<span class="session-tag" style="color:#45475a">Off</span>';
}
function startTickFeed(sym){
  if(tickTimer) clearInterval(tickTimer);
  currentSym=sym;
  tickTimer=setInterval(async()=>{
    if(!currentSym) return;
    try{
      const r=await fetch('/api/tick/'+currentSym);
      const t=await r.json();
      if(t.error) return;
      document.getElementById('lprice').textContent=t.bid.toFixed(5);
      const sp=t.spread;
      const spEl=document.getElementById('smc-spread');
      spEl.textContent='Spread:'+sp+'p';
      spEl.style.color=sp>2?'#f38ba8':sp>1?'#f9e2af':'#a6e3a1';
      document.getElementById('smc-session').innerHTML=getSession();
      if(lastCandle&&series.candle){
        const up={...lastCandle,close:t.bid,
                   high:Math.max(lastCandle.high,t.bid),
                   low:Math.min(lastCandle.low,t.bid)};
        try{series.candle.update(up);}catch(e){}
      }
      // ── LIVE regime label riding the current price, beside the last candle ──
      //    Prefer the INTRADAY (H1) lens — it actually moves with the session; the
      //    daily regime barely changes intraday. Tag which lens is shown.
      if(lastMarkov&&series.candle){
        const intr=lastMarkov.intraday;
        const reg=intr?intr.current:lastMarkov.current;
        const sig=intr?intr.signal:lastMarkov.signal;
        const tag=intr?'H1':'D1';
        const col=reg==='Bull'?'#a6e3a1':reg==='Bear'?'#f38ba8':'#a4abb7';
        const arrow=sig>0.05?'▲':sig<-0.05?'▼':'■';
        if(regimeLine){try{series.candle.removePriceLine(regimeLine);}catch(e){}}
        try{
          regimeLine=series.candle.createPriceLine({
            price:t.bid, color:col, lineWidth:2, lineStyle:0,
            axisLabelVisible:true,
            title:'⛓ '+tag+' '+reg+' '+arrow+' '+(sig>=0?'+':'')+sig});
        }catch(e){}
      }
    }catch(e){}
  },1000);
}

// ── Scalper live 5-condition strip (polls /api/scalp_status every 2s) ─────────
let scalpTimer=null;
function startScalpStrip(){
  if(scalpTimer) clearInterval(scalpTimer);
  const tick=async()=>{
    try{
      const sym=(currentKey||'XAUUSDm|M1').split('|')[0];
      const d=await (await fetch('/api/scalp_status?symbol='+sym)).json();
      const el=document.getElementById('scalp-strip'); if(!el) return;
      if(d.error||!d.buy){ el.style.display='none'; return; }
      el.style.display='flex';
      const dir=d.dir===1?'buy':d.dir===-1?'sell':(d.buy.filter(x=>x.v).length>=d.sell.filter(x=>x.v).length?'buy':'sell');
      const conds=d[dir]; const head=dir==='buy'?'شراء':'بيع';
      document.getElementById('ss-head').textContent='سكالبر '+head+' · RSI '+d.rsi+' · توافق '+d.confluence;
      document.getElementById('ss-chips').innerHTML=conds.map(c=>'<span class="ss-chip '+(c.v?'ss-on':'ss-off')+'">'+(c.v?'✓':'✗')+' '+c.k+'</span>').join('');
      const v=document.getElementById('ss-verdict');
      v.textContent=d.enter==='wait'?'⏸ ينتظر':'▶ '+(d.enter==='BUY'?'دخول شراء':'دخول بيع');
      v.style.color=d.enter==='wait'?'#a4abb7':'#a6e3a1';
    }catch(e){}
  };
  tick(); scalpTimer=setInterval(tick,2000);
}

// ── Account + open-trades overlay + DISCIPLINE banner ─────────────────────────
let tradeLines=[];
let acctTimer=null;
function clearTradeLines(){ tradeLines.forEach(l=>{try{series.candle.removePriceLine(l);}catch(e){}}); tradeLines=[]; }
function startAccountFeed(){
  if(acctTimer) clearInterval(acctTimer);
  const tick=async()=>{
    try{
      const sym=(currentKey||'XAUUSDm|M1').split('|')[0];
      const r=await fetch('/api/account?symbol='+sym);
      const d=await r.json();
      if(d.error) return;
      drawAccount(d);
    }catch(e){}
  };
  tick(); renderScan(); acctTimer=setInterval(()=>{tick();renderScan();},3000);
}
function drawAccount(d){
  const a=d.account||{};
  // header chips
  const eqEl=document.getElementById('acct-eq'), mlEl=document.getElementById('acct-ml'), flEl=document.getElementById('acct-fl');
  if(eqEl&&a.equity!=null){
    eqEl.textContent='حقوق '+a.equity;
    mlEl.textContent='هامش '+(a.margin_level?Math.round(a.margin_level)+'%':'—');
    mlEl.style.color=(a.margin_level&&a.margin_level<150&&a.margin>0)?'#f38ba8':'#a6e3a1';
    const fl=d.floating_all||0;
    flEl.textContent='عائم '+(fl>=0?'+':'')+fl;
    flEl.style.color=fl>=0?'#a6e3a1':'#f38ba8';
  }
  // DISCIPLINE banner: night window (22-08 UTC) = your proven loss zone
  const h=new Date().getUTCHours();
  const night=(h>=22||h<8);
  const manyManual=(d.n_manual||0)>=3;
  const b=document.getElementById('disc-banner');
  if(b){
    if(night){ b.className='disc-banner disc-warn'; b.textContent='🌙 ليل '+h+':00 UTC — منطقة خسائرك المثبتة · لا تتداول'; }
    else if(manyManual){ b.className='disc-banner disc-warn'; b.textContent='⚠ '+d.n_manual+' صفقات يدوية — انتبه للتعزيل'; }
    else { b.className='disc-banner disc-ok'; b.textContent='✓ نافذة منضبطة'; }
  }
  // draw OPEN positions for the current symbol on the chart
  clearTradeLines();
  (d.positions||[]).forEach(p=>{
    const col=p.profit>=0?'#a6e3a1':'#f38ba8';
    const tag=(p.type==='BUY'?'▲':'▼')+' '+p.type+' '+p.volume+'  '+(p.profit>=0?'+':'')+p.profit+'$';
    tradeLines.push(series.candle.createPriceLine({price:p.open,color:'#89b4fa',lineWidth:2,lineStyle:0,axisLabelVisible:true,title:tag}));
    if(p.sl>0) tradeLines.push(series.candle.createPriceLine({price:p.sl,color:'#f38ba8',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'SL'}));
    if(p.tp>0) tradeLines.push(series.candle.createPriceLine({price:p.tp,color:'#a6e3a1',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'TP'}));
  });
}

// ── Draw projection line ──────────────────────────────────────────────────────
function drawProjection(d){
  if(!d.projection||!d.projection.length||d.action==='HOLD'||!d.candles||!d.candles.length){
    series.proj.setData([]); return;
  }
  const lastCandle=d.candles[d.candles.length-1];
  const tfSec=TF_SECS[d.timeframe]||3600;
  const pts=[{time:lastCandle.time, value:d.price}];
  d.projection.forEach((tgt,i)=>{
    pts.push({time:lastCandle.time+tfSec*(i+1)*6, value:tgt});
  });
  // Update projection series color
  series.proj.applyOptions({color: d.action==='BUY'?'rgba(166,227,161,.7)':'rgba(243,139,168,.7)'});
  series.proj.setData(pts);
}

// ── Draw fractals as markers ──────────────────────────────────────────────────
function drawAll(d){
  const allM=[];
  // Signal markers
  (d.markers||[]).forEach(m=>allM.push({
    time:m.time, position:m.dir===1?'belowBar':'aboveBar',
    color:m.dir===1?'#a6e3a1':'#f38ba8',
    shape:m.dir===1?'arrowUp':'arrowDown',
    text:(m.conf*100).toFixed(0)+'%'
  }));
  // Bullish fractals (support)
  ((d.fractals||{}).bullish||[]).forEach(f=>allM.push({
    time:f.time, position:'belowBar', color:'#74c7ec', shape:'arrowUp', text:'◆'
  }));
  // Bearish fractals (resistance)
  ((d.fractals||{}).bearish||[]).forEach(f=>allM.push({
    time:f.time, position:'aboveBar', color:'#74c7ec', shape:'arrowDown', text:'◆'
  }));
  // Liquidity sweep markers
  ((d.fractal_structure||{}).sweeps||[]).forEach(sw=>{
    const bull=sw.kind==='bull_sweep';
    allM.push({time:sw.time,position:bull?'belowBar':'aboveBar',
               color:bull?'#94e2d5':'#fab387',shape:bull?'arrowUp':'arrowDown',text:'SW'});
  });
  allM.sort((a,b)=>a.time-b.time);
  series.candle.setMarkers(allM);
}

// ── Render ────────────────────────────────────────────────────────────────────
function arrow(v){return v>0?'↑':v<0?'↓':'—'}
function cls(v){return v>0?'up':v<0?'dn':'neu'}

function renderScan(){
  fetch('/api/scan').then(r=>r.json()).then(s=>{
    const body=document.getElementById('scan-body'); if(!body) return;
    const rows=s.rows||[]; body.innerHTML='';
    const tf=(currentKey||'|M15').split('|')[1]||'M15';
    rows.forEach(x=>{
      if(x.err) return;
      const tr=document.createElement('tr'); tr.className='row';
      tr.onclick=()=>loadSymbol(x.symbol, tf);
      const tc=x.trend==='↑'?'up':x.trend==='↓'?'dn':'neu';
      const obc=x.ob==='OB'?'ob':x.ob==='OS'?'os':'neu';
      const st=[x.bos,x.choch,x.sweep].filter(Boolean).map(t=>t[0]).join('');
      tr.innerHTML=`<td class="sb-sym">${x.symbol.replace('m','')}</td>`+
        `<td class="${tc}">${x.trend}</td><td>${x.adx}</td>`+
        `<td class="${x.rsi>=70?'dn':x.rsi<=30?'up':''}">${x.rsi}</td>`+
        `<td class="${x.stoch>=80?'dn':x.stoch<=20?'up':''}">${x.stoch}</td>`+
        `<td class="${obc}">${x.ob}</td><td style="font-size:8px">${st}</td>`;
      body.appendChild(tr);
    });
    const ts=document.getElementById('scan-ts');
    if(ts&&s.ts){const d=new Date(s.ts*1000);ts.textContent=d.toISOString().slice(11,19)+'Z';}
  }).catch(()=>{});
}

function renderMarkov(d){
  const m=(d.market_projection&&d.market_projection.markov)?d.market_projection.markov:null;
  const card=document.getElementById('mk-card'); if(!card) return;
  if(!m||!m.matrix){ card.style.display='none'; lastMarkov=null; return; }
  lastMarkov=m;   // feed the LIVE regime label drawn beside the last candle each tick
  card.style.display='block';
  const colOf=r=>r==='Bull'?'#a6e3a1':r==='Bear'?'#f38ba8':'#a4abb7';
  const cur=document.getElementById('mk-cur');
  cur.textContent=m.current; cur.style.background=colOf(m.current); cur.style.color='#11111b';
  const ST=['Bear','Side','Bull'];
  const body=document.getElementById('mk-body'); body.innerHTML='';
  // header
  let h='<tr><td class="h"></td>'+ST.map(s=>'<td class="h">'+s+'</td>').join('')+'</tr>';
  body.insertAdjacentHTML('beforeend',h);
  for(let i=0;i<3;i++){
    let row='<tr><td class="h">'+ST[i]+'</td>';
    for(let j=0;j<3;j++){
      row+='<td class="'+(i===j?'diag':'')+'">'+m.matrix[i][j]+'%</td>';
    }
    row+='</tr>'; body.insertAdjacentHTML('beforeend',row);
  }
  const st=m.stationary||[];
  let foot='يومي(بوابة) '+m.current+' إشارة '+(m.signal>=0?'+':'')+m.signal;
  if(m.intraday){ foot+=' · ساعة(حيّ) '+m.intraday.current+' '+(m.intraday.signal>=0?'+':'')+m.intraday.signal; }
  foot+=' · مدى B'+(st[2]||0)+'% S'+(st[1]||0)+'% Be'+(st[0]||0)+'%';
  document.getElementById('mk-foot').textContent=foot;
}

function renderSentiment(d){
  const s=(d.market_projection&&d.market_projection.sentiment)?d.market_projection.sentiment:null;
  const el=document.getElementById('sent-vial'); if(!el) return;
  if(!s||s.active_pct==null){ el.style.display='none'; return; }
  el.style.display='block';
  const pct=s.active_pct;
  document.getElementById('sv-fill').style.left=Math.max(0,Math.min(100,pct))+'%';
  document.getElementById('sv-pct').textContent=Math.round(pct)+'%';
  const face=document.getElementById('sv-face');
  face.textContent=(s.health==='bull')?' 🟢':' 🔴';
  const comps=s.components||{}; const box=document.getElementById('sv-comps'); box.innerHTML='';
  Object.keys(comps).forEach(k=>{
    const v=comps[k];
    const col=v>=4?'#a6e3a1':v===3?'#6c7086':'#f38ba8';
    const c=document.createElement('span'); c.className='sv-c'; c.style.background=col;
    c.textContent=k.slice(0,3); c.title=k+': '+v+'/5';
    box.appendChild(c);
  });
}

function render(d){
  if(d.error){console.error(d.error);return;}
  const act=d.action||'HOLD';

  // Header
  document.getElementById('ts').textContent=d.ts?d.ts.slice(0,19).replace('T',' ')+' UTC':'';
  const acc=d.accuracy||{};
  const accTxt=acc.total>0?`دقة: ${(acc.accuracy*100).toFixed(0)}% (${acc.hits}/${acc.total})`:'دقة: —';
  document.getElementById('acc-badge').textContent=accTxt;
  document.getElementById('acc-badge').style.borderColor=acc.accuracy>0.6?'#a6e3a1':acc.accuracy>0.4?'#f9e2af':'#f38ba8';

  // Decision
  document.getElementById('dsym').textContent=d.symbol||'—';
  document.getElementById('dtf').textContent=d.timeframe||'—';
  document.getElementById('dact').textContent=act;
  document.getElementById('dact').className=`cv ${act}`;
  document.getElementById('chip-act').className=`chip chip-${act}`;
  document.getElementById('drr').textContent=d.rr?d.rr.toFixed(2):'—';
  document.getElementById('dconf').textContent=d.confidence?(d.confidence*100).toFixed(0)+'%':'—';
  document.getElementById('dreason').textContent=d.reason||'—';
  document.getElementById('dgid').textContent=d.genome_id||'—';

  // Why
  const sv=d.signal_vote||0, bv=d.bias_vote||0;
  const w=d.why||{};
  document.getElementById('wsig').innerHTML=`<span class="${cls(sv)}">${arrow(sv)} ${sv===1?'شراء':sv===-1?'بيع':'لا'}</span>`;
  document.getElementById('wbias').innerHTML=`<span class="${cls(bv)}">${arrow(bv)} ${bv===1?'صعودي':bv===-1?'هبوطي':'محايد'}</span>`;
  document.getElementById('wfilt').innerHTML=`<span class="${d.filter_ok?'ok':'fail'}">${d.filter_ok?'✓ نجح':'✗ محجوب'}</span>`;
  const rsi=w.rsi||0;
  document.getElementById('wrsi').innerHTML=`<span class="${rsi<35?'up':rsi>65?'dn':'neu'}">${rsi} ${rsi<35?'OS':rsi>65?'OB':'—'}</span>`;
  const md=w.macd_diff||0;
  document.getElementById('wmacd').innerHTML=`<span class="${cls(md)}">${arrow(md)} ${md.toFixed(5)}</span>`;
  const sk=w.stoch_k||0;
  document.getElementById('wstoch').innerHTML=`<span class="${sk<25?'up':sk>75?'dn':'neu'}">${sk} ${sk<25?'OS':sk>75?'OB':'—'}</span>`;
  const adx=w.adx||0;
  document.getElementById('wadx').innerHTML=`<span class="${adx>25?'up':'neu'}">${adx} ${adx>25?'اتجاه':'عرضي'}</span>`;
  document.getElementById('wgenes').textContent=`S:${w.n_sigs||0} B:${w.n_biases||0} F:${w.n_filts||0}`;

  // Zone
  if(act!=='HOLD'&&d.entry){
    document.getElementById('ze').textContent=`Entry: ${d.entry}`;
    document.getElementById('zsl').textContent=`SL: ${d.sl} (-${w.sl_pips}p)`;
    document.getElementById('ztp').textContent=`TP: ${d.tp} (+${w.tp_pips}p)`;
  } else {
    document.getElementById('ze').textContent='لا يوجد دخول';
    document.getElementById('zsl').textContent='';
    document.getElementById('ztp').textContent='';
  }
  // Projection summary
  const proj=d.projection||[];
  if(proj.length){
    document.getElementById('zproj').innerHTML=`<span class="proj-tag">📍 ${proj.map(p=>p.toFixed(act==='BUY'?5:5)).join(' → ')}</span>`;
  } else {
    document.getElementById('zproj').textContent='';
  }
  document.getElementById('zatr').textContent=`ATR ${w.atr_pips||0}p`;
  const br=d.brain||{};
  if(br.total_campaigns>0){
    document.getElementById('zacc').textContent=`🧠 ${br.total_campaigns} حملات | ${((br.combo_win_rate||0)*100).toFixed(0)}% جينات`;
    document.getElementById('zacc').style.color='#cba6f7';
  } else {
    document.getElementById('zacc').textContent='';
  }

  // Chart data
  if(d.candles&&d.candles.length){
    series.candle.setData(d.candles);
    lastCandle={...d.candles[d.candles.length-1]};
  }
  series.ema.setData(d.ema||[]);
  drawAll(d);
  drawKeyLevels(d.levels);
  drawEntryLines(d);
  drawProjection(d);
  drawSMC(d);
  clearFractalLines();
  drawProtectedLevels(d);
  drawStructureEvents(d);
  drawProjectionPath(d);
  drawVP(d);
  renderRunnerState(d);
  renderFractalStatus(d);
  renderSentiment(d);
  renderMarkov(d);

  // RSI
  series.rsi.setData(d.rsi||[]);
  if(d.rsi&&d.rsi.length){
    const t=d.rsi.map(r=>r.time);
    series.rsiOB.setData(t.map(x=>({time:x,value:70})));
    series.rsiOS.setData(t.map(x=>({time:x,value:30})));
  }

  // MACD
  series.macdL.setData(d.macd_line||[]);
  series.macdS.setData(d.macd_sig||[]);
  series.macdH.setData((d.macd_hist||[]).map(p=>({...p,color:p.value>=0?'rgba(166,227,161,.6)':'rgba(243,139,168,.6)'})));

  // Stoch
  series.skL.setData(d.stoch_k||[]);
  series.sdL.setData(d.stoch_d||[]);

  ['cMain','cRsi','cMacd','cStoch'].forEach(id=>charts[id].timeScale().fitContent());

  // Sidebar TF button color
  updateTfBtn(d.symbol,d.timeframe,act);

  // Levels panel
  renderLevelsPanel(d.levels||{});
}

// ── Levels panel ─────────────────────────────────────────────────────────────
const LEVEL_LABELS={pivot:'Pivot PP',r1:'Resistance 1',r2:'Resistance 2',r3:'Resistance 3',
  s1:'Support 1',s2:'Support 2',s3:'Support 3',prev_high:'أعلى أمس',prev_low:'أدنى أمس',
  prev_close:'إغلاق أمس',today_open:'فتح اليوم',today_high:'أعلى اليوم',today_low:'أدنى اليوم',
  today_close:'إغلاق الآن',week_high:'أعلى الأسبوع',week_low:'أدنى الأسبوع',
  month_high:'أعلى الشهر',month_low:'أدنى الشهر',
  h4_resist1:'H4 مقاومة 1',h4_resist2:'H4 مقاومة 2',
  h4_support1:'H4 دعم 1',h4_support2:'H4 دعم 2'};

function renderLevelsPanel(levels){
  const g=document.getElementById('lvl-grid');
  g.innerHTML='';
  Object.entries(levels).forEach(([k,v])=>{
    const div=document.createElement('div');
    div.className='lvl-item';
    div.innerHTML=`<span class="lvl-name">${LEVEL_LABELS[k]||k}</span><span class="lvl-val">${v}</span>`;
    g.appendChild(div);
  });
}

function toggleLevels(){
  document.getElementById('lvl-panel').classList.toggle('open');
}

// ── Sidebar ───────────────────────────────────────────────────────────────────
function updateTfBtn(sym,tf,act){
  if(sym!==curSym) return;                       // buttons reflect the on-screen symbol only
  const btn=document.querySelector(`.tfb[data-tf="${tf}"]`);
  if(!btn) return;
  btn.classList.remove('BUY','SELL');
  if(act==='BUY') btn.classList.add('BUY');
  else if(act==='SELL') btn.classList.add('SELL');
}

let curSym='XAUUSDm', curTf='M1';
// Priority symbols shown first in the picker (traded + common). Rest appended from /api/symbols.
const PRIO=['XAUUSDm','BTCUSDm','ETHUSDm','EURUSDm','GBPUSDm','USDJPYm','XAGUSDm','US30m','NAS100m'];
async function loadSidebar(){
  // Multi-symbol: populate the picker from /api/symbols (unique symbols), priority first.
  try{ const r=await fetch('/api/symbols'); allSymbols=await r.json(); }catch(e){ allSymbols=[]; }
  const seen=new Set(), syms=[];
  const norm=x=>(typeof x==='string'?x:(x&&(x.symbol||x.sym||x.name))||'');
  let raw=Array.isArray(allSymbols)?allSymbols.map(norm).filter(Boolean):[];
  raw=raw.map(s=>String(s).split('|')[0]);                 // strip "SYM|TF" genome keys
  for(const s of PRIO){ if(raw.includes(s)&&!seen.has(s)){ seen.add(s); syms.push(s); } }
  for(const s of raw){ if(!seen.has(s)){ seen.add(s); syms.push(s); } }
  if(!seen.has('XAUUSDm')){ syms.unshift('XAUUSDm'); }
  const sel=document.getElementById('symPick');
  if(sel){ sel.innerHTML=syms.map(s=>`<option value="${s}"${s===curSym?' selected':''}>${s.replace(/m$/,'')}</option>`).join(''); }
  if(!currentKey) loadSymbol(curSym,curTf);
}
function pickSym(sym){ curSym=sym; loadSymbol(sym,curTf); }
function loadTF(tf){ curTf=tf; loadSymbol(curSym,tf); }

// ── Load symbol ───────────────────────────────────────────────────────────────
async function loadSymbol(sym,tf){
  currentKey=sym+'|'+tf; curSym=sym; curTf=tf;
  const sel=document.getElementById('symPick'); if(sel&&sel.value!==sym) sel.value=sym;
  document.querySelectorAll('.tfb').forEach(b=>b.classList.remove('active'));
  const btn=document.querySelector('.tfb[data-tf="'+tf+'"]');
  if(btn) btn.classList.add('active');
  document.getElementById('ld').classList.remove('hidden');
  try{
    const r=await fetch('/api/chart/'+sym+'/'+tf);
    const d=await r.json();
    render(d);
    startTickFeed(sym);
  }catch(e){console.error(e);}
  finally{document.getElementById('ld').classList.add('hidden');}
}

function refreshNow(){
  if(!currentKey) return;
  const p=currentKey.split('|');
  loadSymbol(p[0],p[1]);
}

// ── Live refresh 5s ───────────────────────────────────────────────────────────
function startRefresh(){
  if(timer) clearInterval(timer);
  timer=setInterval(()=>{
    if(!currentKey) return;
    const p=currentKey.split('|');
    fetch('/api/chart/'+p[0]+'/'+p[1])
      .then(r=>r.json())
      .then(d=>{if(!d.error) render(d);})
      .catch(()=>{});
  },5000);
}

// Boot
window.addEventListener('load',()=>{
  initCharts();
  loadSidebar().then(()=>{
    document.getElementById('ld').classList.add('hidden');
    startRefresh();
    startAccountFeed();
    startScalpStrip();
  });
});
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTML

if __name__ == "__main__":
    port = int(os.getenv("ALGORY_CHART_PORT", "8866"))
    print(f"Algory Intelligence Dashboard → http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

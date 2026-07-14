#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ملف الحجم (Volume Profile Agent) — Mujalid
يحسب POC / VAH / VAL من بيانات XAUUSD الحقيقية
ويرسل مستويات الدعم/المقاومة للمحرك المركزي
"""
import json, datetime, requests
from pathlib import Path

AGENT_DIR   = Path(__file__).parent
MEMORY_FILE = AGENT_DIR / "memory.json"
REPORT_FILE = AGENT_DIR / "report.md"
LOG_FILE    = AGENT_DIR / "log.jsonl"
SIGNAL_FILE = Path(r"C:\Users\Radhi\MT5\agents\volume_profile_signal.json")

COMMON      = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
STATUS_JSON = COMMON / "ea_realtime_status.json"
BAR_HISTORY_JSON = COMMON / "ea_bar_history.json"

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"

def load_memory():
    default = {"agent": "ملف الحجم", "name": "Mujalid", "role": "Volume Profile",
               "runs": 0, "poc_history": [], "signal_history": [], "last_price": 0}
    if MEMORY_FILE.exists():
        try:
            data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**default, **data}
        except Exception:
            pass
    return default

def save_memory(m): MEMORY_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

def read_mt5_bars(limit=200):
    """Read real M1 bars exported by the MT5 EA."""
    try:
        if not BAR_HISTORY_JSON.exists():
            return []
        rows = json.loads(BAR_HISTORY_JSON.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            return []
        clean = []
        for row in rows[-limit:]:
            try:
                clean.append({
                    "o": float(row.get("o", 0)),
                    "h": float(row.get("h", 0)),
                    "l": float(row.get("l", 0)),
                    "c": float(row.get("c", 0)),
                    "spr": float(row.get("spr", 0)),
                })
            except Exception:
                continue
        return [r for r in clean if r["h"] > 0 and r["l"] > 0 and r["c"] > 0]
    except Exception:
        return []

def calc_volume_profile_from_bars(bars, current_price=0, bins=50):
    """Build a local profile from real MT5 candles, using candle range as volume proxy."""
    if len(bars) < 20:
        return None
    prices = [r["c"] for r in bars]
    lo, hi = min(prices), max(prices)
    if hi <= lo:
        return None

    bins_arr = [lo + (hi - lo) * i / bins for i in range(bins + 1)]
    vol_dist = [0.0] * bins
    spreads = []
    for r in bars:
        p = r["c"]
        v = max(abs(r["h"] - r["l"]), abs(r["c"] - r["o"]), 0.01)
        idx = min(int((p - lo) / (hi - lo) * bins), bins - 1)
        vol_dist[idx] += v
        if r["spr"] > 0:
            spreads.append(r["spr"])

    poc_idx = vol_dist.index(max(vol_dist))
    poc = (bins_arr[poc_idx] + bins_arr[poc_idx + 1]) / 2
    total_vol = sum(vol_dist)
    target_70 = total_vol * 0.70

    lo_idx, hi_idx = poc_idx, poc_idx
    cumvol = vol_dist[poc_idx]
    while cumvol < target_70 and (lo_idx > 0 or hi_idx < bins - 1):
        add_lo = vol_dist[lo_idx - 1] if lo_idx > 0 else 0
        add_hi = vol_dist[hi_idx + 1] if hi_idx < bins - 1 else 0
        if add_hi >= add_lo and hi_idx < bins - 1:
            hi_idx += 1
            cumvol += add_hi
        elif lo_idx > 0:
            lo_idx -= 1
            cumvol += add_lo
        else:
            hi_idx += 1
            cumvol += add_hi

    vah = (bins_arr[hi_idx] + bins_arr[hi_idx + 1]) / 2
    val = (bins_arr[lo_idx] + bins_arr[lo_idx + 1]) / 2
    price = float(current_price or prices[-1])
    bias = "BULLISH" if price > poc else ("BEARISH" if price < poc else "NEUTRAL")
    avg_spread = round(sum(spreads) / len(spreads), 1) if spreads else 0

    return {
        "poc": round(poc, 3), "vah": round(vah, 3), "val": round(val, 3),
        "price": round(price, 3), "bias": bias,
        "in_value_area": val <= price <= vah,
        "va_width": round(vah - val, 3),
        "source": "mt5_bar_history",
        "bars": len(bars),
        "avg_spread_points": avg_spread,
    }

def fetch_xauusd_hourly():
    """Fetch recent XAUUSD hourly data via yfinance"""
    try:
        import yfinance as yf
        df = yf.download("GC=F", period="5d", interval="1h", progress=False)
        if df.empty:
            df = yf.download("XAUUSD=X", period="5d", interval="1h", progress=False)
        return df
    except:
        return None

def calc_volume_profile(df, bins=50):
    """Calculate POC, VAH, VAL from OHLCV data"""
    if df is None or len(df) < 10:
        return None
    try:
        import numpy as np
        prices  = df["Close"].values.flatten()
        volumes = df["Volume"].values.flatten() if "Volume" in df.columns else None
        if volumes is None or volumes.sum() == 0:
            volumes = abs(df["High"].values.flatten() - df["Low"].values.flatten())

        lo, hi = float(prices.min()), float(prices.max())
        bins_arr = [lo + (hi - lo) * i / bins for i in range(bins + 1)]
        vol_dist = [0.0] * bins
        for p, v in zip(prices, volumes):
            idx = min(int((float(p) - lo) / (hi - lo) * bins), bins - 1)
            vol_dist[idx] += float(v)

        poc_idx    = vol_dist.index(max(vol_dist))
        poc        = (bins_arr[poc_idx] + bins_arr[poc_idx + 1]) / 2
        total_vol  = sum(vol_dist)
        target_70  = total_vol * 0.70

        # Expand outward from POC to find 70% value area
        lo_idx, hi_idx = poc_idx, poc_idx
        cumvol = vol_dist[poc_idx]
        while cumvol < target_70 and (lo_idx > 0 or hi_idx < bins - 1):
            add_lo = vol_dist[lo_idx - 1] if lo_idx > 0 else 0
            add_hi = vol_dist[hi_idx + 1] if hi_idx < bins - 1 else 0
            if add_hi >= add_lo and hi_idx < bins - 1:
                hi_idx += 1; cumvol += add_hi
            elif lo_idx > 0:
                lo_idx -= 1; cumvol += add_lo
            else:
                hi_idx += 1; cumvol += add_hi

        vah = (bins_arr[hi_idx] + bins_arr[hi_idx + 1]) / 2
        val = (bins_arr[lo_idx] + bins_arr[lo_idx + 1]) / 2
        current_price = float(prices[-1])

        # Determine bias from VP context
        if current_price > poc:
            bias = "BULLISH"  # Price above POC = buyers in control
        elif current_price < poc:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        # Check if price is inside or outside value area
        in_va = val <= current_price <= vah
        return {"poc": round(poc, 3), "vah": round(vah, 3), "val": round(val, 3),
                "price": round(current_price, 3), "bias": bias, "in_value_area": in_va,
                "va_width": round(vah - val, 3)}
    except Exception as e:
        return {"error": str(e)}

def ask_ollama(prompt):
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.2, "num_predict": 80}, "keep_alive": "10m"}, timeout=8)
        return r.json().get("response", "").strip() if r.ok else "[Ollama offline]"
    except: return "[Ollama offline]"

def run():
    mem = load_memory()
    mem["runs"] += 1
    now = datetime.datetime.now().isoformat()

    # Get current EA price
    current_price = 0
    try:
        if STATUS_JSON.exists():
            st = json.loads(STATUS_JSON.read_text(encoding="utf-8"))
            current_price = float(st.get("price", 0) or st.get("bid", 0))
    except: pass

    # Prefer the real bars exported by the live MT5 EA. yfinance is only fallback.
    bars = read_mt5_bars()
    vp = calc_volume_profile_from_bars(bars, current_price=current_price)
    if not vp:
        df = fetch_xauusd_hourly()
        vp = calc_volume_profile(df)
        if vp and "poc" in vp:
            vp["source"] = "yfinance"

    signal = {"agent": "volume_profile", "time": now, "status": "no_data"}

    if vp and "poc" in vp:
        poc, vah, val = vp["poc"], vp["vah"], vp["val"]
        price = vp.get("price", current_price)
        bias  = vp["bias"]
        in_va = vp["in_value_area"]

        # Distance from key levels
        dist_poc = round(abs(price - poc), 2) if price else 0
        near_poc = dist_poc < 2.0  # within $2 of POC

        # Trading signal
        if price and price < val:
            trade_signal = "BUY_ZONE"   # Below value area = potential long setup
        elif price and price > vah:
            trade_signal = "SELL_ZONE"  # Above value area = potential short
        elif near_poc:
            trade_signal = "AT_POC"     # Decision point
        else:
            trade_signal = "IN_VALUE_AREA"

        signal = {
            "agent": "volume_profile", "time": now, "status": "ok",
            "poc": poc, "vah": vah, "val": val, "price": price,
            "bias": bias, "in_value_area": in_va,
            "trade_signal": trade_signal, "dist_poc": dist_poc,
            "source": vp.get("source", "unknown"),
            "bars": vp.get("bars", 0),
            "avg_spread_points": vp.get("avg_spread_points", 0),
            # جريء: AT_POC مع انحياز → صوت 1 (نقطة قرار مهمة)
            "vote": 1 if trade_signal in ["BUY_ZONE", "SELL_ZONE"] or
                        (trade_signal == "AT_POC" and bias in ["BULLISH","BEARISH"]) else 0,
            "direction": "BUY" if trade_signal == "BUY_ZONE" or (trade_signal == "AT_POC" and bias == "BULLISH")
                        else ("SELL" if trade_signal == "SELL_ZONE" or (trade_signal == "AT_POC" and bias == "BEARISH")
                        else "NEUTRAL")
        }

        mem["poc_history"].append({"t": now[:16], "poc": poc, "vah": vah, "val": val})
        mem["poc_history"] = mem["poc_history"][-50:]

        prompt = f"""أنت وكيل ملف الحجم لتداول الذهب. حلل الوضع (3 جمل):
السعر الحالي: {price}  POC: {poc}  VAH: {vah}  VAL: {val}
المصدر: {signal.get('source')}  |  الشموع: {signal.get('bars')}  |  متوسط السبريد: {signal.get('avg_spread_points')} نقطة
الانحياز: {bias}  |  الإشارة: {trade_signal}  |  داخل Value Area: {in_va}
هل السعر في موقع جيد للدخول؟"""
        analysis = ask_ollama(prompt)
    else:
        analysis = "[لا توجد بيانات حجم — يتطلب yfinance أو بيانات حية]"

    # Write signal file
    SIGNAL_FILE.write_text(json.dumps(signal, ensure_ascii=False, indent=2), encoding="utf-8")

    report = f"""# ملف الحجم | {now[:16]}

## 📊 مستويات Volume Profile
| المستوى | القيمة |
|---------|--------|
| POC (أعلى حجم) | {signal.get('poc', 'N/A')} |
| VAH (سقف القيمة) | {signal.get('vah', 'N/A')} |
| VAL (قاع القيمة) | {signal.get('val', 'N/A')} |
| السعر الحالي | {signal.get('price', 'N/A')} |
| الانحياز | {signal.get('bias', 'N/A')} |
| الإشارة | {signal.get('trade_signal', 'N/A')} |
| المصدر | {signal.get('source', 'N/A')} |
| الشموع | {signal.get('bars', 'N/A')} |
| متوسط السبريد | {signal.get('avg_spread_points', 'N/A')} نقطة |

## 🤖 التحليل
{analysis}
"""
    REPORT_FILE.write_text(report, encoding="utf-8")

    mem["last_price"] = signal.get("price", 0)
    mem["signal_history"].append({"t": now[:16], "signal": signal.get("trade_signal","?"),
                                  "vote": signal.get("vote", 0), "dir": signal.get("direction","?")})
    mem["signal_history"] = mem["signal_history"][-100:]
    save_memory(mem)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": now, "signal": signal.get("trade_signal"), "vote": signal.get("vote",0)},
                           ensure_ascii=False) + "\n")
    return signal

if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))

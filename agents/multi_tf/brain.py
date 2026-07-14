#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
محلّل الأطر الزمنية المتعددة — Musharrik (مُشرِّك)
يحلّل XAUUSD على 6 أطر زمنية ويطابق الأهداف عبرها:
M1 / M5 / M15 / H1 / H4 / D1
المستويات: Pivot Points · VWAP · Fibonacci · OHLC سابقة · قمم/قيعان · مناطق التقاطع
"""
import json, datetime, math, requests
from pathlib import Path
from collections import defaultdict

AGENT_DIR   = Path(__file__).parent
SIGNAL_FILE = AGENT_DIR.parent / "multi_tf_signal.json"
REPORT_FILE = AGENT_DIR / "report.md"
MEMORY_FILE = AGENT_DIR / "memory.json"
LOG_FILE    = AGENT_DIR / "log.jsonl"

COMMON       = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
BAR_HISTORY  = COMMON / "ea_bar_history.json"
STATUS_JSON  = COMMON / "ea_realtime_status.json"

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"

# Confluence zone width in dollars
CONFLUENCE_THRESH = 3.0  # levels within $3 of each other = same zone

TF_MINUTES = {"M1":1, "M5":5, "M15":15, "H1":60, "H4":240, "D1":1440}

# ── Helpers ──────────────────────────────────────────────────────────────────
def load_memory():
    if MEMORY_FILE.exists():
        try: return json.loads(MEMORY_FILE.read_bytes().rstrip(b"\x00").decode("utf-8", errors="replace"))
        except: pass
    return {"name":"Musharrik","role":"Multi-TF Analyst","runs":0,"history":[]}

def save_memory(m):
    MEMORY_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

def ask_ollama(prompt):
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.2, "num_predict": 120}, "keep_alive": "10m"}, timeout=8)
        return r.json().get("response","").strip() if r.ok else "[Ollama offline]"
    except: return "[Ollama offline]"

# ── Data Loading ──────────────────────────────────────────────────────────────
def load_m1_bars():
    """Load M1 bars from EA bar history or yfinance fallback."""
    # Try EA bar history first
    if BAR_HISTORY.exists():
        try:
            rows = json.loads(BAR_HISTORY.read_text(encoding="utf-8"))
            if isinstance(rows, list) and len(rows) >= 60:
                bars = []
                for r in rows:
                    try:
                        bars.append({
                            "t": r.get("t",""), "o": float(r.get("o",0)),
                            "h": float(r.get("h",0)), "l": float(r.get("l",0)),
                            "c": float(r.get("c",0)), "v": float(r.get("spr",1) or 1)
                        })
                    except: continue
                bars = [b for b in bars if b["h"]>0 and b["l"]>0]
                if len(bars) >= 60:
                    return bars, "mt5_live"
        except: pass

    # Fallback: yfinance
    try:
        import yfinance as yf
        df = yf.download("GC=F", period="10d", interval="1m", progress=False, auto_adjust=True)
        if df is None or (hasattr(df,'empty') and df.empty):
            df = yf.download("XAUUSD=X", period="10d", interval="1m", progress=False, auto_adjust=True)
        if df is not None and not (hasattr(df,'empty') and df.empty):
            bars = []
            for ts, row in df.iterrows():
                try:
                    bars.append({
                        "t": str(ts), "o": float(row["Open"]),
                        "h": float(row["High"]), "l": float(row["Low"]),
                        "c": float(row["Close"]), "v": float(row.get("Volume",1) or 1)
                    })
                except: continue
            bars = [b for b in bars if b["h"]>0]
            return bars, "yfinance"
    except Exception as e:
        pass
    return [], "none"

def aggregate_tf(m1_bars, tf_minutes):
    """Aggregate M1 bars to higher timeframe."""
    if tf_minutes == 1:
        return m1_bars
    agg = {}
    for b in m1_bars:
        # Use bar index as bucket
        idx = m1_bars.index(b) // tf_minutes
        if idx not in agg:
            agg[idx] = {"t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"],
                        "c": b["c"], "v": b["v"]}
        else:
            agg[idx]["h"] = max(agg[idx]["h"], b["h"])
            agg[idx]["l"] = min(agg[idx]["l"], b["l"])
            agg[idx]["c"] = b["c"]
            agg[idx]["v"] += b["v"]
    return list(agg.values())

# ── Level Calculators ─────────────────────────────────────────────────────────
def calc_pivot_points(h, l, c):
    """Classic Daily Pivot Points."""
    pp = (h + l + c) / 3
    r1 = 2*pp - l
    s1 = 2*pp - h
    r2 = pp + (h - l)
    s2 = pp - (h - l)
    r3 = h + 2*(pp - l)
    s3 = l - 2*(h - pp)
    # Camarilla
    cr1 = c + (h-l)*1.1/12
    cr2 = c + (h-l)*1.1/6
    cr3 = c + (h-l)*1.1/4
    cr4 = c + (h-l)*1.1/2
    cs1 = c - (h-l)*1.1/12
    cs2 = c - (h-l)*1.1/6
    cs3 = c - (h-l)*1.1/4
    cs4 = c - (h-l)*1.1/2
    return {
        "PP":pp,"R1":r1,"R2":r2,"R3":r3,"S1":s1,"S2":s2,"S3":s3,
        "CR1":cr1,"CR2":cr2,"CR3":cr3,"CR4":cr4,
        "CS1":cs1,"CS2":cs2,"CS3":cs3,"CS4":cs4
    }

def calc_vwap(bars):
    """Session VWAP from provided bars."""
    cum_pv = cum_v = 0.0
    vwap_list = []
    for b in bars:
        typ = (b["h"] + b["l"] + b["c"]) / 3
        vol = b["v"] if b["v"] > 0 else 1
        cum_pv += typ * vol
        cum_v  += vol
        vwap_list.append(cum_pv / cum_v)
    if not vwap_list:
        return 0, 0, 0
    vwap = vwap_list[-1]
    # VWAP std dev bands
    prices = [(b["h"]+b["l"]+b["c"])/3 for b in bars]
    variance = sum((p-vwap)**2 for p in prices)/len(prices) if prices else 0
    std = math.sqrt(variance)
    return round(vwap,3), round(vwap+std,3), round(vwap-std,3)

def calc_fibonacci(swing_high, swing_low, direction="down"):
    """Fibonacci retracement and extension levels."""
    diff = swing_high - swing_low
    if diff <= 0: return {}
    levels = {}
    # Retracement
    for pct, label in [(0.0,"0%"),(0.236,"23.6%"),(0.382,"38.2%"),
                       (0.5,"50%"),(0.618,"61.8%"),(0.786,"78.6%"),(1.0,"100%")]:
        if direction == "down":
            levels[f"FIB_{label}"] = round(swing_high - diff*pct, 3)
        else:
            levels[f"FIB_{label}"] = round(swing_low + diff*pct, 3)
    # Extensions
    for pct, label in [(1.272,"127.2%"),(1.414,"141.4%"),(1.618,"161.8%")]:
        if direction == "down":
            levels[f"FIB_EXT_{label}"] = round(swing_high - diff*pct, 3)
        else:
            levels[f"FIB_EXT_{label}"] = round(swing_low + diff*pct, 3)
    return levels

def find_swing_high_low(bars, lookback=None):
    """Find significant swing high and low in bars."""
    if not bars: return 0, 0
    sub = bars[-lookback:] if lookback else bars
    return max(b["h"] for b in sub), min(b["l"] for b in sub)

def get_prev_candle_ohlc(bars, label="prev"):
    """Get last completed candle OHLC."""
    if len(bars) < 2:
        return {}
    b = bars[-2]  # last completed candle
    return {f"{label}_O": round(b["o"],3), f"{label}_H": round(b["h"],3),
            f"{label}_L": round(b["l"],3), f"{label}_C": round(b["c"],3)}

def get_session_ohlc(bars, session_bars=480):
    """Today's session (last N M1 bars = 8 hours) OHLC."""
    sub = bars[-session_bars:]
    if not sub: return {}
    return {"today_O": round(sub[0]["o"],3),
            "today_H": round(max(b["h"] for b in sub),3),
            "today_L": round(min(b["l"] for b in sub),3),
            "today_C": round(sub[-1]["c"],3)}

# ── Confluence Detection ───────────────────────────────────────────────────────
def find_confluences(all_levels, current_price, threshold=CONFLUENCE_THRESH):
    """Group levels within threshold. Return sorted confluence zones."""
    level_list = []
    for src, levels in all_levels.items():
        for name, price in levels.items():
            if price and price > 0:
                level_list.append({"price": price, "source": src, "label": name})

    # Sort by price
    level_list.sort(key=lambda x: x["price"])

    # Group into zones
    zones = []
    i = 0
    while i < len(level_list):
        zone = [level_list[i]]
        j = i + 1
        while j < len(level_list) and abs(level_list[j]["price"] - level_list[i]["price"]) <= threshold:
            zone.append(level_list[j])
            j += 1
        if len(zone) >= 2:
            avg_price = sum(z["price"] for z in zone) / len(zone)
            # Count unique sources
            sources = list(set(z["source"] for z in zone))
            labels  = [f"{z['source']}:{z['label']}" for z in zone]
            zones.append({
                "price":    round(avg_price, 3),
                "count":    len(zone),
                "sources":  len(sources),
                "labels":   labels,
                "side":     "SUPPORT" if avg_price < current_price else "RESISTANCE",
                "distance": round(abs(avg_price - current_price), 3)
            })
        i = j if j > i else i + 1

    zones.sort(key=lambda x: (-x["sources"], -x["count"]))
    return zones

# ── Main Run ──────────────────────────────────────────────────────────────────
def run():
    mem = load_memory()
    mem["runs"] += 1
    now = datetime.datetime.now().isoformat()

    # Current price from EA status
    current_price = 0.0
    ea_data = {}
    try:
        if STATUS_JSON.exists():
            ea_data = json.loads(STATUS_JSON.read_text(encoding="utf-8"))
            current_price = float(ea_data.get("bid", ea_data.get("close", 0)))
    except: pass

    m1_bars, source = load_m1_bars()

    if not m1_bars or len(m1_bars) < 60:
        signal = {"agent":"multi_tf","status":"no_data","vote":0,"direction":"NEUTRAL",
                  "time":now,"source":source}
        SIGNAL_FILE.write_text(json.dumps(signal, ensure_ascii=False, indent=2), encoding="utf-8")
        REPORT_FILE.write_text(f"# MTF | {now[:16]}\n\n❌ لا توجد بيانات كافية (source={source})\n", encoding="utf-8")
        save_memory(mem)
        return signal

    if current_price <= 0:
        current_price = m1_bars[-1]["c"]

    all_levels = {}
    tf_summaries = {}

    # ── Analyze each timeframe ────────────────────────────────────────────────
    for tf_name, tf_min in TF_MINUTES.items():
        bars = aggregate_tf(m1_bars, tf_min)
        if len(bars) < 3:
            continue

        levels = {}

        # Previous candle OHLC
        prev = get_prev_candle_ohlc(bars, tf_name)
        levels.update(prev)

        # Today's session OHLC (only for M1/M5/M15)
        if tf_min <= 15:
            sess = get_session_ohlc(bars)
            levels.update({f"{tf_name}_{k}":v for k,v in sess.items()})

        # Pivot Points from previous candle
        if len(bars) >= 2:
            pb = bars[-2]
            pivots = calc_pivot_points(pb["h"], pb["l"], pb["c"])
            for k,v in pivots.items():
                levels[f"{tf_name}_PP_{k}"] = round(v,3)

        # VWAP (use last session bars)
        session_len = min(len(bars), 480 // tf_min if tf_min > 0 else 480)
        vwap, vwap_plus, vwap_minus = calc_vwap(bars[-session_len:])
        if vwap > 0:
            levels[f"{tf_name}_VWAP"]   = vwap
            levels[f"{tf_name}_VWAP+1"] = vwap_plus
            levels[f"{tf_name}_VWAP-1"] = vwap_minus

        # Fibonacci from swing H/L
        lookback = min(len(bars), max(20, 300 // tf_min if tf_min > 0 else 20))
        sh, sl = find_swing_high_low(bars, lookback)
        if sh > sl > 0:
            mid = (sh+sl)/2
            direction = "down" if current_price >= mid else "up"
            fibs = calc_fibonacci(sh, sl, direction)
            for k,v in fibs.items():
                levels[f"{tf_name}_{k}"] = v

        # Previous swing high / low (key levels)
        levels[f"{tf_name}_SwingH"] = round(sh,3)
        levels[f"{tf_name}_SwingL"] = round(sl,3)

        all_levels[tf_name] = levels

        # Summary for this TF
        tf_summaries[tf_name] = {
            "bars": len(bars),
            "current": round(current_price,3),
            "prev_H":  prev.get(f"{tf_name}_H", bars[-2]["h"] if len(bars)>=2 else 0),
            "prev_L":  prev.get(f"{tf_name}_L", bars[-2]["l"] if len(bars)>=2 else 0),
            "prev_C":  prev.get(f"{tf_name}_C", bars[-2]["c"] if len(bars)>=2 else 0),
            "swing_H": round(sh,3), "swing_L": round(sl,3),
            "vwap":    vwap
        }

    # ── Today's OHLC (full day) ───────────────────────────────────────────────
    today = get_session_ohlc(m1_bars, 1440)  # 24h
    all_levels["Today"] = {f"Today_{k}":v for k,v in today.items()}

    # ── Weekly Pivot (from D1 bars) ───────────────────────────────────────────
    d1_bars = aggregate_tf(m1_bars, 1440)
    if len(d1_bars) >= 2:
        prev_d = d1_bars[-2]
        weekly_pivots = calc_pivot_points(prev_d["h"], prev_d["l"], prev_d["c"])
        all_levels["Weekly"] = {f"W_{k}":round(v,3) for k,v in weekly_pivots.items()}

    # ── Find Confluences ──────────────────────────────────────────────────────
    confluences = find_confluences(all_levels, current_price, CONFLUENCE_THRESH)
    top_support    = [z for z in confluences if z["side"] == "SUPPORT"    and z["sources"] >= 2][:5]
    top_resistance = [z for z in confluences if z["side"] == "RESISTANCE" and z["sources"] >= 2][:5]

    # ── Generate Vote ─────────────────────────────────────────────────────────
    direction = "NEUTRAL"
    vote      = 0

    # Strong support below + trend up → BUY
    # Strong resistance above + trend down → SELL
    strong_sup = [z for z in top_support    if z["sources"] >= 3 and z["distance"] <= 8]
    strong_res = [z for z in top_resistance if z["sources"] >= 3 and z["distance"] <= 8]

    # Check H1/H4 trend alignment
    h1  = tf_summaries.get("H1",{})
    h4  = tf_summaries.get("H4",{})
    h1_bull  = current_price > h1.get("vwap",0) > 0
    h4_bull  = current_price > h4.get("vwap",0) > 0

    if strong_sup and (h1_bull or h4_bull):
        direction = "BUY"
        vote = 1
    elif strong_res and (not h1_bull or not h4_bull):
        direction = "SELL"
        vote = 1
    elif strong_sup and strong_res:
        # Price in middle — find which is closer
        sup_dist = min(z["distance"] for z in strong_sup)
        res_dist = min(z["distance"] for z in strong_res)
        if res_dist < sup_dist:
            direction = "SELL"
            vote = 1
        elif sup_dist < res_dist:
            direction = "BUY"
            vote = 1

    # ── LLM Summary ──────────────────────────────────────────────────────────
    sup_str = " | ".join([f"{z['price']}(×{z['sources']})" for z in top_support[:3]])
    res_str = " | ".join([f"{z['price']}(×{z['sources']})" for z in top_resistance[:3]])
    h1_sum  = tf_summaries.get("H1",{})
    h4_sum  = tf_summaries.get("H4",{})
    d1_sum  = tf_summaries.get("D1",{})

    prompt = f"""تحليل XAUUSD متعدد الأطر الزمنية:
السعر الحالي: {current_price}
VWAP H1={h1_sum.get('vwap','N/A')} | H4={h4_sum.get('vwap','N/A')}
تقاطع دعم: {sup_str if sup_str else 'لا يوجد'}
تقاطع مقاومة: {res_str if res_str else 'لا يوجد'}
قمة اليوم: {today.get('today_H','?')} | قاع اليوم: {today.get('today_L','?')}
H4 سابقة: H={h4_sum.get('prev_H','?')} L={h4_sum.get('prev_L','?')} C={h4_sum.get('prev_C','?')}
D1 سابقة: H={d1_sum.get('prev_H','?')} L={d1_sum.get('prev_L','?')} C={d1_sum.get('prev_C','?')}
القرار: {direction} (صوت={vote})
في 2-3 جمل: ما هو الهدف الأقوى والأكثر تقاطعاً؟"""

    analysis = ask_ollama(prompt)

    # ── Write Signal ──────────────────────────────────────────────────────────
    signal = {
        "agent":       "multi_tf",
        "time":        now,
        "source":      source,
        "current":     round(current_price,3),
        "vote":        vote,
        "direction":   direction,
        "top_support":    top_support,
        "top_resistance": top_resistance,
        "strong_support_count":    len(strong_sup),
        "strong_resistance_count": len(strong_res),
        "tf_summary":  tf_summaries,
        "today_ohlc":  today,
        "analysis":    analysis
    }
    SIGNAL_FILE.write_text(json.dumps(signal, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── Report ────────────────────────────────────────────────────────────────
    def fmt_zone(z): return f"**{z['price']}$** ({z['sources']} مصادر: {', '.join(z['labels'][:3])})"

    report_lines = [
        f"# 📊 تحليل متعدد الأطر | {now[:16]}",
        "",
        f"## {'🟢 BUY' if direction=='BUY' else ('🔴 SELL' if direction=='SELL' else '⚪ محايد')} — السعر الحالي: **{current_price}$**",
        "",
        "## 📅 OHLC الأطر السابقة",
        "| الإطار | فتح | أعلى | أدنى | إغلاق | VWAP |",
        "|--------|-----|------|------|-------|------|",
    ]
    for tf in ["M1","M5","M15","H1","H4","D1"]:
        s = tf_summaries.get(tf,{})
        if s:
            report_lines.append(
                f"| {tf} | {s.get('prev_C','-')} | {s.get('prev_H','-')} | "
                f"{s.get('prev_L','-')} | {s.get('prev_C','-')} | {s.get('vwap','-')} |"
            )
    report_lines += [
        "",
        f"**اليوم:** فتح={today.get('today_O','?')} أعلى={today.get('today_H','?')} أدنى={today.get('today_L','?')} إغلاق={today.get('today_C','?')}",
        "",
        "## 🎯 مناطق الدعم القوية (تقاطع متعدد)",
    ]
    if top_support:
        for z in top_support[:5]:
            report_lines.append(f"- {fmt_zone(z)} — {z['distance']}$ من السعر")
    else:
        report_lines.append("- لا توجد مناطق دعم متقاطعة")

    report_lines += ["", "## 🎯 مناطق المقاومة القوية (تقاطع متعدد)"]
    if top_resistance:
        for z in top_resistance[:5]:
            report_lines.append(f"- {fmt_zone(z)} — {z['distance']}$ من السعر")
    else:
        report_lines.append("- لا توجد مناطق مقاومة متقاطعة")

    report_lines += ["", "## 🤖 تقييم الذكاء الاصطناعي", analysis]

    REPORT_FILE.write_text("\n".join(report_lines), encoding="utf-8")

    mem["history"].append({"t":now[:16],"vote":vote,"dir":direction,"price":current_price})
    mem["history"] = mem["history"][-100:]
    save_memory(mem)

    with open(LOG_FILE,"a",encoding="utf-8") as f:
        f.write(json.dumps({"time":now,"vote":vote,"dir":direction,"price":current_price},
                           ensure_ascii=False) + "\n")

    return signal

if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))

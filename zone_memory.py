"""zone_memory.py — ذاكرة المناطق السعرية المتعلِّمة: تحديد ► مقارنة ► مطابقة ► حفظ ► ضبط دائم.

The user's spec (2026-06-11): the system must identify price zones, compare/match every trade's
outcome against them, SAVE them, and keep adjusting them forever — learning WHICH zones make
money and which lose, from OUR OWN live trades (not backtest).

How it works (every 5 min, windowless):
  1. IDENTIFY: confirmed pivot levels on H1(300)+D1(120) per symbol → candidate zones.
  2. MATCH: every closed live trade (our magics) is matched to the nearest zone at its ENTRY
     price (within 0.6×ATR_H1) and the zone inherits the trade's realized P&L.
  3. SAVE/ADJUST: zones persist in zone_memory.json with touches/wins/net + EWMA score; close
     zones merge; stale zones decay and die. The map is ALWAYS being re-tuned.
  4. FEED BACK: multi_trader reads the memory — S/R limit orders skip zones that PROVED losing
     (net<-2 over >=3 touches) and entries near PROVEN winning zones get a confluence bonus.

Read-only on the market. Own magics only: 20260608 / 20260611 / 20260612.
Run:  pythonw zone_memory.py
"""
from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from pathlib import Path

RN = Path(r"C:\Users\Radhi\MT5\data\r_native")
OUT = RN / "zone_memory.json"
MAGICS = {20260608, 20260611, 20260612, 20260613}
POLL_S = 300
MATCH_ATR = 0.6          # entry within this × ATR_H1 of a zone = the zone owns the trade
MERGE_ATR = 0.35         # zones closer than this × ATR merge
DECAY = 0.97             # weekly-ish decay of old evidence (applied per cycle on score)
MAX_ZONES = 30


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _save(obj):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, OUT)


def _atr(r, n=14):
    tr = [max(r[i]["high"] - r[i]["low"], abs(r[i]["high"] - r[i - 1]["close"]),
              abs(r[i]["low"] - r[i - 1]["close"])) for i in range(1, len(r))]
    return sum(tr[-n:]) / n if tr else 0.0


def _pivots(mt5, sym):
    """Confirmed pivot levels from H1+D1 (the candidate zones)."""
    out = []
    for tf, n, w in ((mt5.TIMEFRAME_H1, 300, 4), (mt5.TIMEFRAME_D1, 120, 3)):
        r = mt5.copy_rates_from_pos(sym, tf, 0, n)
        if r is None or len(r) < 2 * w + 5:
            continue
        for i in range(w, len(r) - w):
            seg = r[i - w:i + w + 1]
            if r[i]["high"] == max(x["high"] for x in seg):
                out.append(float(r[i]["high"]))
            if r[i]["low"] == min(x["low"] for x in seg):
                out.append(float(r[i]["low"]))
    return out


def cycle(mt5, mem, last_scan):
    now = time.time()
    # symbols = everything we traded recently + current roster zones
    syms = set()
    deals = [d for d in (mt5.history_deals_get(int(last_scan), int(now)) or [])
             if d.magic in MAGICS]
    for d in deals:
        syms.add(d.symbol)
    for s in list((mem or {}).keys()):
        syms.add(s)
    for sym in syms:
        info = mt5.symbol_info(sym)
        rH = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 60)
        if not info or rH is None or len(rH) < 20:
            continue
        atr = _atr(rH)
        if atr <= 0:
            continue
        zs = (mem.setdefault(sym, {"zones": []}))["zones"]
        # 1) IDENTIFY: add fresh pivots as zones (merge into existing)
        for px in _pivots(mt5, sym):
            near = next((z for z in zs if abs(z["px"] - px) <= MERGE_ATR * atr), None)
            if near:
                near["px"] = round((near["px"] + px) / 2, info.digits)   # refine the zone center
            else:
                zs.append({"px": round(px, info.digits), "touches": 0, "wins": 0,
                           "net": 0.0, "score": 0.0, "born": now, "last": now})
        # 2) MATCH: attribute each closed trade to its entry zone
        ent = {d.position_id: d for d in deals if d.symbol == sym and d.entry == 0}
        for d in deals:
            if d.symbol != sym or d.entry != 1 or d.position_id not in ent:
                continue
            epx = float(ent[d.position_id].price)
            z = min(zs, key=lambda z: abs(z["px"] - epx), default=None)
            if not z or abs(z["px"] - epx) > MATCH_ATR * atr:
                continue
            pnl = d.profit + d.commission + d.swap
            z["touches"] += 1
            z["wins"] += 1 if pnl > 0 else 0
            z["net"] = round(z["net"] + pnl, 2)
            z["score"] = round(z["score"] * 0.8 + (1 if pnl > 0 else -1) * 0.2, 3)
            z["last"] = now
        # 3) ADJUST: decay + prune (الضبط الدائم)
        for z in zs:
            z["score"] = round(z["score"] * DECAY, 3)
        zs.sort(key=lambda z: -(abs(z["net"]) + z["touches"]))
        # keep proven zones + the freshest structure
        proven = [z for z in zs if z["touches"] > 0][:MAX_ZONES // 2]
        fresh = [z for z in zs if z["touches"] == 0][:MAX_ZONES // 2]
        mem[sym]["zones"] = proven + fresh
        mem[sym]["atr"] = round(atr, info.digits)
    mem["_meta"] = {"ts": now, "iso": datetime.now(timezone.utc).isoformat(),
                    "matched_deals": len(deals)}
    _save(mem)
    hot = []
    for s, v in mem.items():
        if s.startswith("_"):
            continue
        for z in v.get("zones", []):
            if z["touches"] >= 3:
                hot.append((s, z["px"], z["net"], z["touches"]))
    return len(deals), sorted(hot, key=lambda x: -abs(x[2]))[:4]


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    print("[ZONES] ذاكرة المناطق حيّة — تحديد/مطابقة/حفظ/ضبط دائم", flush=True)
    mem = _load(OUT, {}) or {}
    last = float((mem.get("_meta") or {}).get("ts", time.time() - 48 * 3600))
    while True:
        try:
            n, hot = cycle(mt5, mem, last)
            last = time.time()
            tag = " · ".join(f"{s.replace('m','')}@{px}: ${net:+.1f}/{t}لمسة" for s, px, net, t in hot)
            print(f"[ZONES] طابقت {n} قيداً · مناطق مثبتة: {tag or 'تتجمع…'}", flush=True)
        except Exception as e:
            print(f"[ZONES] err {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())

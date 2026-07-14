"""paper_prover.py — F2-b slice 3: FORWARD paper-proof (the bridge before real money).

An OOS backtest pass is necessary but NOT sufficient — historical edges decay forward.
So before ANY discovered market touches real money, it must prove itself FORWARD on live
bars it has never seen, in PAPER (simulated, ZERO order_send). This collector:
  • reads the OOS-robust symbols from market_gate.json (US30/BTCJPY/BTCUSD by default)
  • each cycle: if flat, take the SAME consolidated 15-indicator read the live traders use;
    open a PAPER position (entry, ATR stop/target). If in a position, close it when price
    hits stop/target (spread cost subtracted). No real orders — ever.
  • appends every closed paper trade to a persistent ledger and recomputes a forward proof.

PROVEN (forward) = >= MIN_TRADES paper trades AND profit_factor >= MIN_PF AND net_R > 0.
A PROVEN symbol becomes eligible for real-money promotion — which still needs explicit
user approval. This script NEVER promotes and NEVER sends an order.

Run:  python paper_prover.py --loop
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

_V2 = Path(__file__).resolve().parent
_MT5 = _V2.parent
for p in (str(_MT5), str(_V2)):
    if p not in sys.path:
        sys.path.insert(0, p)

import chart_read as cr

DATA = _V2 / "data"
POS = DATA / "paper_positions.json"
LEDGER = DATA / "paper_ledger.json"
PROOF = DATA / "paper_proof.json"
GATE = DATA / "market_gate.json"

POLL = 8
CONF_GATE = 0.60
STOP_ATR = 2.0
TGT_ATR = 3.0
MAX_HOLD_S = 6 * 3600          # paper trade times out after 6h
MIN_TRADES = 30
MIN_PF = 1.2
DEFAULT = [("US30m", "M5"), ("BTCJPYm", "M15"), ("BTCUSDm", "M15")]


def _load(p, d):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return d


def _save(p, obj):
    DATA.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _atr(rows, n=14):
    if rows is None or len(rows) < n + 2: return 0.0
    t = [max(rows[i]["high"] - rows[i]["low"], abs(rows[i]["high"] - rows[i - 1]["close"]),
            abs(rows[i]["low"] - rows[i - 1]["close"])) for i in range(1, len(rows))]
    return sum(t[-n:]) / n


def _targets(mt5):
    """Symbols to prove: OOS-robust tier from the gate, else defaults."""
    # PREFER the factory's trained genomes (each with its OOS-optimized TF)
    try:
        import glob as _glob
        out = []; seen = set()
        for f in _glob.glob(str(_GENO / "*.json")):
            g = _load(Path(f), {})
            sym = g.get("symbol"); tf = (g.get("config") or {}).get("tf")
            if sym and tf and sym not in seen:
                seen.add(sym); out.append((sym, tf))
        if out:
            return out
    except Exception:
        pass
    # fallback: gate-eligible markets
    g = _load(GATE, None)
    if g and g.get("results"):
        out = []; seen = set()
        for s, r in g["results"].items():
            if r.get("tier") in ("robust", "marginal"):
                best_tf = None; best_pf = -1
                for tf, x in (r.get("tf") or {}).items():
                    if x.get("pass") and x.get("pf", 0) > best_pf:
                        best_pf = x["pf"]; best_tf = tf
                if best_tf:
                    base = s.replace("_x100m", "m").replace("_x10m", "m")
                    if base not in seen:
                        seen.add(base); out.append((base, best_tf))
        if out:
            return out
    return DEFAULT


def _tf(mt5, s):
    return {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}.get(s, mt5.TIMEFRAME_M15)


def _proof(ledger):
    out = {}
    by = {}
    for t in ledger:
        by.setdefault(t["symbol"], []).append(t)
    for sym, ts in by.items():
        outs = [t["R"] for t in ts]
        wins = [x for x in outs if x > 0]; losses = [x for x in outs if x <= 0]
        gw = sum(wins); gl = abs(sum(losses))
        pf = gw / gl if gl > 0 else (99.9 if gw > 0 else 0.0)
        net = sum(outs)
        proven = (len(outs) >= MIN_TRADES and pf >= MIN_PF and net > 0)
        out[sym] = {"fwd_trades": len(outs), "win_rate": round(len(wins) / len(outs), 3) if outs else 0,
                    "pf": round(pf, 2), "net_R": round(net, 2),
                    "status": "PROVEN" if proven else "collecting"}
    return out


_GENO = DATA / "genomes"


def _genome(sym):
    """Load this symbol's OOS-optimized config (tf, stop_atr, target_atr, conf_gate) from the
    genome factory; fall back to generic defaults if not trained yet."""
    try:
        c = _load(_GENO / f"{sym}.json", {}).get("config", {})
        return (c.get("tf"), float(c.get("stop_atr", STOP_ATR)),
                float(c.get("target_atr", TGT_ATR)), float(c.get("conf_gate", CONF_GATE)))
    except Exception:
        return (None, STOP_ATR, TGT_ATR, CONF_GATE)


def cycle(mt5, targets):
    pos = _load(POS, {})           # symbol -> open paper position
    ledger = _load(LEDGER, [])
    changed = False
    for sym, tfs in targets:
        mt5.symbol_select(sym, True)
        info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
        if not info or not tick:
            continue
        spread = (tick.ask - tick.bid)
        held = pos.get(sym)
        if held:
            # manage open paper trade
            d = held["dir"]; cur = tick.bid if d > 0 else tick.ask
            hit = None
            if d > 0:
                if tick.bid <= held["sl"]: hit = ("SL", held["sl"])
                elif tick.bid >= held["tp"]: hit = ("TP", held["tp"])
            else:
                if tick.ask >= held["sl"]: hit = ("SL", held["sl"])
                elif tick.ask <= held["tp"]: hit = ("TP", held["tp"])
            timeout = (time.time() - held["open_ts"]) > MAX_HOLD_S
            if hit or timeout:
                exitpx = hit[1] if hit else cur
                atr = held["atr"]
                R = (((exitpx - held["entry"]) if d > 0 else (held["entry"] - exitpx)) / atr) if atr > 0 else 0.0
                R -= (spread / atr) if atr > 0 else 0.0       # spread cost
                ledger.append({"symbol": sym, "tf": held["tf"], "dir": d,
                               "entry": round(held["entry"], 5), "exit": round(exitpx, 5),
                               "R": round(R, 3), "reason": hit[0] if hit else "timeout",
                               "open_ts": held["open_ts"], "close_ts": time.time()})
                del pos[sym]; changed = True
            continue
        # flat -> use this symbol's OOS-optimized genome config (tf/stop/target/gate)
        g_tf, g_stop, g_tgt, g_gate = _genome(sym)
        use_tf = g_tf or tfs
        read = cr.read_local(mt5, sym, use_tf) or {}
        d = int(read.get("dir", 0) or 0); conf = float(read.get("confluence", 0.0))
        if d == 0 or conf < g_gate:
            continue
        r = mt5.copy_rates_from_pos(sym, _tf(mt5, use_tf), 0, 50)
        rows = [{"high": x["high"], "low": x["low"], "close": x["close"]} for x in r] if r is not None else []
        atr = _atr(rows)
        if atr <= 0:
            continue
        entry = tick.ask if d > 0 else tick.bid
        sl = entry - g_stop * atr if d > 0 else entry + g_stop * atr
        tp = entry + g_tgt * atr if d > 0 else entry - g_tgt * atr
        pos[sym] = {"dir": d, "entry": entry, "sl": sl, "tp": tp, "atr": atr,
                    "tf": use_tf, "conf": conf, "open_ts": time.time()}
        changed = True
    if changed:
        _save(POS, pos); _save(LEDGER, ledger)
    proof = _proof(ledger)
    _save(PROOF, {"ts": time.time(), "symbols": proof,
                  "open": {s: {"dir": p["dir"], "conf": p["conf"]} for s, p in pos.items()},
                  "gate": {"min_trades": MIN_TRADES, "min_pf": MIN_PF},
                  "note": "FORWARD paper proof. PROVEN -> eligible for real money (needs approval). No order_send."})
    return proof, pos


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser(); ap.add_argument("--loop", action="store_true"); a = ap.parse_args(argv)
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    targets = _targets(mt5)
    print(f"[PAPER] forward proof — {targets} · PAPER ONLY (no order_send) · need >={MIN_TRADES} trades PF>={MIN_PF}", flush=True)
    try:
        while True:
            try:
                proof, pos = cycle(mt5, targets)
                line = " · ".join(f"{s}:{d['fwd_trades']}t/{d['pf']}pf/{d['net_R']}R[{d['status']}]" for s, d in proof.items())
                print(f"[PAPER] {line or 'collecting...'} | open {list(pos)}", flush=True)
            except Exception as e:
                print(f"[PAPER] err {e}", flush=True)
            if not a.loop:
                break
            time.sleep(POLL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

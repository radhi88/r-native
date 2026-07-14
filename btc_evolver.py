"""btc_evolver.py — BTC scalper self-tuner (magic 99792). Per-trade EWMA bandit.

After every CLOSED BTC trade it nudges the EWMA score of each knob's current value by the
trade's net (after spread+commission), then writes the best-scoring values to
btc_live_config.json — which btc_live reads each cycle. Reacts every trade, smooths luck.
Honest: won't fake an edge; if nothing beats negative it reports best net still negative.

Run:  python btc_evolver.py --loop
"""
from __future__ import annotations
import argparse, json, time, copy, random
from pathlib import Path

MAGIC = 99792
LIVE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\btc_live_config.json")
STATE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\btc_evolver_state.json")
POLL = 5; ALPHA = 0.30; EPS = 0.20

GRID = {
    "conf_gate":   [0.50, 0.55, 0.60, 0.65],
    "stop_atr":    [2.0, 3.0, 4.0],
    "target_atr":  [4.0, 6.0, 8.0, 12.0],
    "be_atr":      [0.2, 0.3, 0.5],
    "trail_tight": [0.6, 0.8, 1.2],
    "trail_loose": [2.2, 3.0, 4.0],
}
START = {"conf_gate": 0.55, "stop_atr": 3.0, "target_atr": 8.0,
         "be_atr": 0.3, "trail_tight": 0.8, "trail_loose": 3.0}


def _load(p, d):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return d


def _greedy(ewma):
    cfg = {}
    for k, opts in GRID.items():
        best_v, best_s = opts[0], -1e9
        for v in opts:
            s = ewma[k].get(str(v), 0.0)
            if s > best_s: best_s, best_v = s, v
        cfg[k] = best_v
    return cfg


def _neighbour(cfg, k):
    opts = GRID[k]; i = opts.index(cfg[k]) if cfg[k] in opts else 0
    cand = [opts[j] for j in (i - 1, i + 1) if 0 <= j < len(opts)]
    return random.choice(cand) if cand else cfg[k]


def _write(trial, best, note, recent):
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    LIVE.write_text(json.dumps({"config": trial, "best": best, "recent_net": round(recent, 2),
                                "note": note, "updated": int(time.time())}, ensure_ascii=False, indent=1), encoding="utf-8")


def cycle(mt5):
    st = _load(STATE, None)
    if st is None or "ewma" not in st:
        st = {"ewma": {k: {} for k in GRID}, "config": dict(START), "last_ts": int(time.time()),
              "seen": 0, "recent": [], "net_total": 0.0}
        _write(st["config"], st["config"], "init", 0.0)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        return "[BTC-EVO] init " + json.dumps(START)
    deals = mt5.history_deals_get(int(st["last_ts"]), int(time.time())) or []
    new = sorted([d for d in deals if d.magic == MAGIC and d.entry == 1 and d.time >= st["last_ts"]], key=lambda d: d.time)
    if not new:
        return f"[BTC-EVO] no new trade — cfg {json.dumps(st['config'])} recent15 {round(sum(st['recent'][-15:]),2)}"
    adapted = []
    for d in new:
        net = float(d.profit + d.commission + d.swap); cfg = st["config"]
        for k in GRID:
            key = str(cfg[k]); prev = st["ewma"][k].get(key, 0.0)
            st["ewma"][k][key] = prev + ALPHA * (net - prev)
        st["seen"] += 1; st["net_total"] += net; st["recent"].append(round(net, 3)); st["recent"] = st["recent"][-50:]
        st["last_ts"] = int(d.time) + 1; adapted.append(round(net, 2))
    best = _greedy(st["ewma"]); trial = dict(best)
    if random.random() < EPS:
        k = random.choice(list(GRID)); trial[k] = _neighbour(best, k); note = f"explore {k}={trial[k]}"
    else:
        note = "greedy-best"
    st["config"] = trial; recent = sum(st["recent"][-15:])
    _write(trial, best, note, recent)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return f"[BTC-EVO] +{len(new)} trade(s) net {adapted} -> {note} | best {json.dumps(best)} | seen {st['seen']} recent15 {round(recent,2)} total {round(st['net_total'],2)}"


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser(); ap.add_argument("--loop", action="store_true"); ap.add_argument("--once", action="store_true"); ap.add_argument("--reset", action="store_true")
    a = ap.parse_args(argv)
    if a.reset:
        try: STATE.unlink()
        except Exception: pass
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    print(f"[BTC-EVO] per-trade self-tuner (EWMA) for {MAGIC} — adapts after every BTC trade, remembers best.", flush=True)
    try:
        while True:
            try: print(cycle(mt5), flush=True)
            except Exception as e: print(f"[BTC-EVO] ERROR {e}", flush=True)
            if not a.loop or a.once: break
            time.sleep(POLL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

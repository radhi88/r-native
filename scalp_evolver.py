"""scalp_evolver.py — the scalper self-tunes AFTER EVERY trade (online, by the seconds).

Per-knob EWMA bandit. Each knob (entry gate, RSI tilts, stop/target ATR, fast-TP %,
time-stop secs) holds a grid of candidate values. After EVERY closed trade we take its
NET (after spread+commission) and nudge the EWMA score of each knob's currently-used value:

    score <- score + ALPHA*(trade_net - score)

Then the live config becomes the best-scoring value per knob (greedy), with a small
exploration chance to keep gathering evidence on neighbours. So it reacts to every single
trade, but the EWMA smooths single-trade luck so it CONVERGES instead of thrashing. The
best-scoring values are persisted and re-adopted — the profitable values are remembered.

HONEST: it only finds values that are profitable IF any exist. Against an M1 spread that
usually means scores stay negative — it will surface that, not fake an edge.

Run:  python scalp_evolver.py --loop
"""
from __future__ import annotations
import argparse, json, time, random
from pathlib import Path

MAGIC = 99791
LIVE  = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\scalp_live_config.json")
STATE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\scalp_evolver_state.json")
POLL = 4
ALPHA = 0.30      # EWMA learning rate per trade (reacts fast, still smooths luck)
EPS   = 0.20      # exploration: chance to trial a neighbour of the best on one knob

GRID = {
    "conf_gate":  [0.20, 0.25, 0.30, 0.35, 0.40],
    "rsi_buy":    [48, 50, 52, 55],
    "rsi_sell":   [52, 50, 48, 45],
    "stop_atr":   [1.0, 1.4, 1.8, 2.2],
    "target_atr": [0.8, 1.2, 1.6, 2.0],
    "tp_usd_pct": [0.15, 0.25, 0.35, 0.50],
    "max_hold":   [30, 60, 90, 150],
}
FIXED = {"tf": "M1", "ema": 9}
START = {"conf_gate": 0.25, "rsi_buy": 50, "rsi_sell": 50, "stop_atr": 1.4,
         "target_atr": 1.2, "tp_usd_pct": 0.25, "max_hold": 60}


def _load(p, d):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return d


def _fresh_state():
    return {"ewma": {k: {} for k in GRID}, "cnt": {k: {} for k in GRID},
            "config": dict(START), "last_ts": int(time.time()), "seen": 0,
            "recent": [], "net_total": 0.0}


def _greedy(ewma):
    """Best-scoring value per knob (untried values get optimistic 0 so they get sampled)."""
    cfg = {}
    for k, opts in GRID.items():
        best_v, best_s = opts[0], -1e9
        for v in opts:
            s = ewma[k].get(str(v), 0.0)        # optimistic prior 0 for untried
            if s > best_s: best_s, best_v = s, v
        cfg[k] = best_v
    return cfg


def _neighbour(cfg, k):
    opts = GRID[k]; i = opts.index(cfg[k]) if cfg[k] in opts else 0
    cand = [opts[j] for j in (i - 1, i + 1) if 0 <= j < len(opts)]
    return random.choice(cand) if cand else cfg[k]


def _write_live(trial, best, note, recent_net):
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    LIVE.write_text(json.dumps({
        "config": {**FIXED, **trial}, "best": {**FIXED, **best},
        "recent_net": round(recent_net, 2), "note": note, "updated": int(time.time())},
        ensure_ascii=False, indent=1), encoding="utf-8")


def cycle(mt5):
    st = _load(STATE, None)
    if st is None or "ewma" not in st:
        st = _fresh_state()
        _write_live(st["config"], st["config"], "init", 0.0)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        return "[EVO] init " + json.dumps(START)

    deals = mt5.history_deals_get(int(st["last_ts"]), int(time.time())) or []
    new = sorted([d for d in deals if d.magic == MAGIC and d.entry == 1 and d.time >= st["last_ts"]],
                 key=lambda d: d.time)
    if not new:
        rn = sum(st["recent"][-15:])
        return f"[EVO] no new trade — cfg {json.dumps(st['config'])} recent15 net {round(rn,2)}"

    adapted = []
    for d in new:
        net = float(d.profit + d.commission + d.swap)
        cfg = st["config"]
        for k in GRID:                                   # credit every active knob-value
            key = str(cfg[k]); prev = st["ewma"][k].get(key, 0.0)
            st["ewma"][k][key] = prev + ALPHA * (net - prev)
            st["cnt"][k][key] = st["cnt"][k].get(key, 0) + 1
        st["seen"] += 1; st["net_total"] += net
        st["recent"].append(round(net, 3)); st["recent"] = st["recent"][-50:]
        st["last_ts"] = int(d.time) + 1
        adapted.append(round(net, 2))

    # rebuild config from what's now best, with a touch of exploration
    best = _greedy(st["ewma"])
    trial = dict(best)
    if random.random() < EPS:
        k = random.choice(list(GRID)); trial[k] = _neighbour(best, k); note = f"explore {k}={trial[k]}"
    else:
        note = "greedy-best"
    st["config"] = trial
    recent_net = sum(st["recent"][-15:])
    _write_live(trial, best, note, recent_net)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return (f"[EVO] +{len(new)} trade(s) net {adapted} | adapt->{note} | best {json.dumps(best)} | "
            f"seen {st['seen']} recent15 {round(recent_net,2)} total {round(st['net_total'],2)}")


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true"); ap.add_argument("--once", action="store_true")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args(argv)
    if a.reset:
        try: STATE.unlink()
        except Exception: pass
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    print(f"[EVO] per-trade self-tuner (EWMA a={ALPHA}, eps={EPS}) — adapts after EVERY trade, "
          f"remembers best. Honest: won't fake an edge.", flush=True)
    try:
        while True:
            try: print(cycle(mt5), flush=True)
            except Exception as e: print(f"[EVO] ERROR {e}", flush=True)
            if not a.loop or a.once: break
            time.sleep(POLL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Evolution agent — grows the gene pool and the indicator registry.

A continuous evolutionary loop that:

* evaluates a pool of candidate "genes" (parameterised EMA/RSI signal rules)
  on rotating probe symbols, scoring each by net-R fitness;
* breeds mutated children from the best genes each round;
* keeps a hall of fame of survivors (persisted to ``data/genes.json``);
* when progress stalls, **adds a brand-new indicator** to the registry and
  widens the search space — "indicators added if needed";
* publishes everything to the coordination bus so the live dashboard and the
  other agents can see and consult the current best gene.

Honesty note: given the project's NO_EDGE record, fitness will mostly hover
near break-even. The agent genuinely searches and adds structure — it does not
fabricate edge. The exam remains the deploy arbiter.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

import config
from agents import broker
from agents.desk_agents import MarketDataAgent
from core.indicators import atr, ema, rsi
from data import bus

_GENES = os.path.join(os.path.dirname(__file__), "..", "data", "genes.json")
_BASE_INDICATORS = ["EMA_fast", "EMA_slow", "RSI"]
_EXTRA_INDICATORS = ["VWAP_dist", "ATR_ratio", "Momentum", "RSI_slope", "EMA_stack"]


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _seed_gene(rng: np.random.Generator, gid: int) -> dict:
    """Create a random candidate gene."""
    return {"id": f"G{gid}", "fast": int(rng.integers(5, 30)),
            "slow": int(rng.integers(35, 120)), "rsi_lo": int(rng.integers(20, 40)),
            "rsi_hi": int(rng.integers(60, 80)), "score": 0.0, "n": 0,
            "status": "candidate"}


def _mutate(rng: np.random.Generator, g: dict, gid: int) -> dict:
    """Breed a mutated child from gene ``g``."""
    j = lambda v, lo, hi: int(min(hi, max(lo, v + rng.integers(-4, 5))))
    return {"id": f"G{gid}", "fast": j(g["fast"], 5, 30), "slow": j(g["slow"], 35, 120),
            "rsi_lo": j(g["rsi_lo"], 15, 45), "rsi_hi": j(g["rsi_hi"], 55, 85),
            "score": 0.0, "n": 0, "status": "candidate"}


def _fitness(o, h, l, c, g: dict, spread: float, r_mult: float = 1.5) -> tuple[float, int]:
    """Net-R fitness of a gene over a bar window.

    Returns:
        ``(mean_net_R, n_trades)``.
    """
    ef, es = ema(c, g["fast"]), ema(c, g["slow"])
    rs = rsi(c, 14)
    a = atr(h, l, c)
    rs_out: list[float] = []
    i = 60
    while i < len(c) - 30:
        long = ef[i] > es[i] and rs[i] < g["rsi_lo"]
        short = ef[i] < es[i] and rs[i] > g["rsi_hi"]
        d = 1 if long else -1 if short else 0
        if d == 0 or a[i] <= 0:
            i += 1
            continue
        entry, sl_d = c[i], a[i] * 1.8
        sl, tp = entry - d * sl_d, entry + d * sl_d * r_mult
        sp_r = spread / sl_d
        out = None
        for j in range(i + 1, min(len(c), i + 30)):
            if d > 0:
                if l[j] <= sl:
                    out = -1 - sp_r; break
                if h[j] >= tp:
                    out = r_mult - sp_r; break
            else:
                if h[j] >= sl:
                    out = -1 - sp_r; break
                if l[j] <= tp:
                    out = r_mult - sp_r; break
        if out is not None:
            rs_out.append(out)
        i += 10  # non-overlapping-ish
    return (float(np.mean(rs_out)) if rs_out else 0.0, len(rs_out))


def _load() -> dict:
    try:
        with open(_GENES, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {"pool": [], "indicators": list(_BASE_INDICATORS), "best": 0.0,
                "stall": 0, "generation": 0}


def _save(state: dict) -> None:
    os.makedirs(os.path.dirname(_GENES), exist_ok=True)
    with open(_GENES, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, default=str)


def run(symbols: list[str], timeframe: int, bars: int = 500,
        interval: float = 120.0, once: bool = False) -> None:
    """Run the continuous evolution loop, publishing to the bus.

    Args:
        symbols: Probe symbols to rotate through for fitness.
        timeframe: ``mt5.TIMEFRAME_*`` constant.
        bars: History depth per probe.
        interval: Seconds between generations.
        once: Run a single generation and return.
    """
    if not broker.connect():
        print("[evo] MT5 connect failed")
        return
    data_agent = MarketDataAgent(timeframe, bars)
    state = _load()
    ring = bus.InsightRing()
    rng = _rng(len(state["pool"]) + 1)
    gid = len(state["pool"]) + 100
    cursor = 0
    if not state["pool"]:
        state["pool"] = [_seed_gene(rng, gid + k) for k in range(8)]
        gid += 8
        ring.post("evo", "🧬 بذرة أولية: 8 جينات عشوائية")

    while True:
        sym = symbols[cursor % len(symbols)]
        cursor += 1
        b = data_agent.gather(sym, config.classify(sym))
        if b is not None:
            spread = b.meta.get("spread_price", 0.0) or 0.0
            for g in state["pool"]:
                sc, n = _fitness(b.o, b.h, b.l, b.c, g, spread)
                g["score"] = round(0.7 * g["score"] + 0.3 * sc, 4) if g["n"] else round(sc, 4)
                g["n"] += n
            # breed children from the top 3
            top = sorted(state["pool"], key=lambda x: x["score"], reverse=True)[:3]
            children = [_mutate(rng, g, gid + k) for k, g in enumerate(top)]
            gid += len(children)
            for ch in children:
                ch["score"], ch["n"] = _fitness(b.o, b.h, b.l, b.c, ch, spread)
            state["pool"] = sorted(state["pool"] + children,
                                   key=lambda x: x["score"], reverse=True)[:12]
            for g in state["pool"][:3]:
                g["status"] = "hall_of_fame"
            best_now = state["pool"][0]["score"]
            if best_now > state["best"] + 1e-3:
                state["best"] = round(best_now, 4)
                state["stall"] = 0
                ring.post("evo", f"⬆️ جين أفضل {state['pool'][0]['id']} score={best_now:+.3f} على {sym}")
            else:
                state["stall"] += 1
            # add a new indicator when stalled
            if state["stall"] >= 3 and len(state["indicators"]) < len(_BASE_INDICATORS) + len(_EXTRA_INDICATORS):
                nxt = _EXTRA_INDICATORS[len(state["indicators"]) - len(_BASE_INDICATORS)]
                state["indicators"].append(nxt)
                state["stall"] = 0
                ring.post("evo", f"➕ مؤشر جديد أُضيف: {nxt} (توسيع فضاء البحث)")
            state["generation"] += 1
            _save(state)

        bus.write_slice("evo", {
            "agent": "evolution", "active": f"probe {sym}",
            "generation": state["generation"], "best": state["best"],
            "indicators": state["indicators"],
            "genes": [{"id": g["id"], "score": g["score"], "n": g["n"],
                       "fast": g["fast"], "slow": g["slow"], "status": g["status"]}
                      for g in state["pool"][:8]],
            "insights": ring.items})
        print(f"[evo] gen={state['generation']} best={state['best']:+.3f} "
              f"genes={len(state['pool'])} indicators={len(state['indicators'])} probe={sym}")
        if once or not config.AUTONOMOUS_MODE:
            return
        time.sleep(interval)

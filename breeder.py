"""breeder.py — produce + evaluate + admit a single hybrid genome.

Bridges Hall of Fame entries (just dicts) → Genome objects → live MT5
backtest → HoF admission. Used by:
  • LLM Strategist (when its breed_pair recommendation runs in
    autonomous mode)
  • The HoF UI's manual "🧬 BREED" button (future)
  • Future scheduled breed sweeps

Returns a structured result so callers can log/insight on it.
"""
from __future__ import annotations

from typing import Optional


def breed_and_admit(symbol: str, parent_a_id: str, parent_b_id: str,
                    tf: str = "M5", bars: int = 2000,
                    mutation_after_crossover: bool = True) -> dict:
    """Produce a child by crossing two HoF parents, evaluate it on `bars`
    of recent data, and admit to HoF if viable.

    Returns: {ok, child_id, score, trades, reason}
    """
    try:
        from r_native.hall_of_fame import load_index, admit
        from r_native.genes import Genome
        from r_native.genetic_engine import _evaluate_genome_worker
    except Exception as e:
        return {"ok": False, "reason": f"import failed: {e}"}

    index = load_index()
    pa_entry = index.get(parent_a_id)
    pb_entry = index.get(parent_b_id)
    if not pa_entry: return {"ok": False, "reason": f"parent_a {parent_a_id} not in HoF"}
    if not pb_entry: return {"ok": False, "reason": f"parent_b {parent_b_id} not in HoF"}

    # Reconstruct Genome objects from HoF all_params (which is the to_dict() output)
    try:
        ga = Genome.from_dict(pa_entry.get("all_params") or {})
        gb = Genome.from_dict(pb_entry.get("all_params") or {})
        if not ga.flags or not gb.flags:
            return {"ok": False,
                    "reason": "one parent has no flags — can't crossover (old HoF entry?)"}
    except Exception as e:
        return {"ok": False, "reason": f"genome reconstruction failed: {e}"}

    # Crossover → mutate (small) → final child
    next_gen = max(int(pa_entry.get("generation") or 0),
                   int(pb_entry.get("generation") or 0)) + 1
    child = Genome.crossover(ga, gb, gen=next_gen)
    if mutation_after_crossover:
        child = child.mutate(intensity=0.05, gen=next_gen)
        child.method = "crossover+mutation"
        child.parent_a = ga.id
        child.parent_b = gb.id

    # Backtest the child on recent bars (single-process eval, reuse worker fn).
    # MT5 init occasionally races when brain_server already has a connection
    # open — retry up to 3 times with a short shutdown+reconnect in between.
    payload = (child.to_dict(), symbol, tf, bars)
    result = None
    last_err = None
    for attempt in range(3):
        try:
            result = _evaluate_genome_worker(payload)
        except Exception as e:
            last_err = f"backtest err: {e}"
            result = None

        if result and result.get("ok"):
            break  # success

        # If MT5 init was the failure, recycle the connection and retry
        last_err = (result or {}).get("error") or last_err or "unknown"
        if "mt5" in (last_err or "").lower():
            try:
                import MetaTrader5 as _mt5
                _mt5.shutdown()
                import time; time.sleep(1)
                _mt5.initialize()
            except Exception: pass
        else:
            break  # non-MT5 error — no point retrying

    if not result or not result.get("ok"):
        return {"ok": False,
                "reason": f"backtest failed after retries: {last_err}",
                "child_id": child.id}

    stats = result.get("stats") or {}
    score = float(result.get("score") or 0)
    trades = int(stats.get("trades") or 0)

    # Admit to HoF regardless of score (so even failed breeds are a record)
    entry = admit(
        genome={"id": child.id},
        symbol=symbol, tf=tf, score=score,
        stats=stats,
        all_params=child.to_dict(),
        active_genes=child.to_dict().get("active_genes") or [],
        archetype="BREED",
        birth_method="crossover+mutation",
        parents=[ga.id, gb.id],
        generation=next_gen,
    )

    return {
        "ok":        True,
        "child_id":  child.id,
        "nickname":  entry.get("nickname"),
        "score":     score,
        "trades":    trades,
        "parents":   [ga.id, gb.id],
        "generation": next_gen,
        "win_rate":  stats.get("win_rate"),
        "profit_factor": stats.get("profit_factor"),
    }


if __name__ == "__main__":
    # Smoke test — breed top 2 BTC genomes
    import json
    from r_native.hall_of_fame import load_symbol
    top = load_symbol("BTCUSDm")[:2]
    if len(top) < 2:
        print("Need at least 2 HoF entries for BTCUSDm")
    else:
        r = breed_and_admit("BTCUSDm", top[0]["id"], top[1]["id"])
        print(json.dumps(r, indent=2))

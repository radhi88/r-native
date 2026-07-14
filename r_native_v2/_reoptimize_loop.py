"""Self-improvement loop: re-tune genomes on fresh data + REDEPLOY every 3h.

FIX (user: "الجينات اللي خسرت ما راح نولّد لها جينات اذكى؟"): the old loop was a BLIND
round-robin off the backtest gate — it never looked at which symbols are actually LOSING live,
so a bleeding currency got the same generic re-tune as a winner. Now each cycle:
  1. read REAL per-symbol live P&L (multi_trader's magic) → find the LOSERS,
  2. re-breed the losers FIRST with a WIDER/HARDER parameter search (more combos),
  3. genome_factory only keeps a new gene if it BEATS the symbol's best-ever (keep-best guard),
  4. then the normal round-robin pass, then redeploy.
This closes the "losing symbol → breed a smarter gene → redeploy" loop.
"""
import time, sys, json, glob
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import genome_factory, deploy_genomes

MAGIC = 20260608          # multi_trader's live magic (the per-symbol trader)
# WIDER search for the bleeders — try harder to find a smarter config than the default grid.
WIDE_STOP = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
WIDE_TGT  = [1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0]
WIDE_GATE = [0.50, 0.55, 0.60, 0.65, 0.70]


def _live_losers(days=7):
    """Symbols bleeding REAL money on the live trader (>=4 trades, net<0), worst first."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize() and not mt5.initialize():
            return []
        now = int(time.time())
        deals = [d for d in (mt5.history_deals_get(now - days * 86400, now) or [])
                 if d.entry == 1 and d.magic == MAGIC]
        agg = {}
        for d in deals:
            t = agg.setdefault(d.symbol, [0, 0.0]); t[0] += 1; t[1] += d.profit + d.commission + d.swap
        mt5.shutdown()
        return sorted([s for s, (n, net) in agg.items() if n >= 4 and net < 0],
                      key=lambda s: agg[s][1])          # worst (most negative) first
    except Exception:
        return []


def _evolve_losers(losers):
    """Per-loser GENETIC breeding (off-grid): seed from the loser's own gene + the elite winners,
    mutate/crossbreed, score on OOS, and keep only a SMARTER gene. The true 'academy for losers'."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize() and not mt5.initialize():
            return
        allg = []
        for f in glob.glob(str(genome_factory.GENO / "*.json")):
            try: allg.append(json.loads(Path(f).read_text(encoding="utf-8")))
            except Exception: pass
        elite = [g["config"] for g in sorted(allg, key=lambda g: -(g.get("oos", {}).get("pf", 0)))[:3]
                 if g.get("config")]
        for sym in losers:
            try:
                cur = json.loads((genome_factory.GENO / f"{sym}.json").read_text(encoding="utf-8"))
                best = genome_factory.evolve_loser(mt5, sym, [cur.get("config")] + elite)
                if best:
                    verdict = genome_factory.write_best(sym, best)
                    print(f"[REOPT] 🧬 evolve {sym}: {verdict} (net {best['net_R']}R, PF {best.get('pf')})", flush=True)
            except Exception as e:
                print(f"[REOPT] evolve {sym} err {e}", flush=True)
        mt5.shutdown()
    except Exception as e:
        print(f"[REOPT] evolve-phase err {e}", flush=True)


while True:
    try:
        # only re-tune/evolve losers that are STILL survivors (have a genome) — never resurrect a
        # culled no-edge symbol just because it lost live before the cull.
        losers = [s for s in _live_losers() if (genome_factory.GENO / f"{s}.json").exists()]
        if losers:
            # 1) re-breed the bleeders FIRST, with a wider/harder GRID search
            o = (genome_factory.GRID_STOP, genome_factory.GRID_TGT, genome_factory.GRID_GATE)
            genome_factory.GRID_STOP, genome_factory.GRID_TGT, genome_factory.GRID_GATE = WIDE_STOP, WIDE_TGT, WIDE_GATE
            try:
                genome_factory.main(losers)
            finally:
                genome_factory.GRID_STOP, genome_factory.GRID_TGT, genome_factory.GRID_GATE = o
            # 2) then GENETIC refinement off-grid (mutate/crossbreed seeded from elites)
            _evolve_losers(losers)
            print(f"[REOPT] re-bred + evolved {len(losers)} LOSING symbols (worst first): {losers}", flush=True)
        genome_factory.main([])            # normal round-robin re-tune on fresh bars
        d = deploy_genomes.deploy()        # redeploy the (now best-ever) genes to R Native
        print(f"[REOPT] re-optimized + redeployed {len(d)} genomes", flush=True)
    except Exception as e:
        print(f"[REOPT] err {e}", flush=True)
    time.sleep(3 * 3600)

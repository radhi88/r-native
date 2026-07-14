"""test_campaign.py - small GA smoke test that uses multiprocessing properly."""
if __name__ == "__main__":
    import sys
    import time
    sys.path.insert(0, r"C:\Users\Radhi\MT5")
    from r_native.genetic_engine import GeneticEngine, CampaignConfig

    cfg = CampaignConfig(
        symbol="BTCUSDm", timeframe="M5", bars=1000,
        pg_candidates=60,
        tribe_a_gens=2, tribe_b_gens=2,
        war_gens=2, revival_gens=1, retrain_gens=1,
        n_workers=4,
    )
    events = []
    def cb(phase, msg, done, total):
        events.append(f"  [{phase}] {msg}")
        if done == total or "Gen " in msg:
            print(f"  [{phase}] {msg}")

    print(f"Workers: {cfg.n_workers}")
    print(f"Genome catalog: 48 genes + 16 continuous params")
    print()
    t0 = time.time()
    engine = GeneticEngine(cfg, progress_cb=cb)
    summary = engine.run_full_campaign()
    elapsed = time.time() - t0

    print()
    print("=" * 60)
    print(f"  Elapsed:       {elapsed:.1f}s")
    print(f"  Vault size:    {summary['vault_size']} strategies passed purge")
    print(f"  Killed:        {summary['killed_count']} genomes")
    print(f"  Top score:     {summary['top_score']}")
    if summary.get('top_genome'):
        g = summary['top_genome']
        s = g['stats']
        print(f"  Best genome:   {g['genome']['id']}")
        print(f"  Active genes:  {len(g['genome'].get('active_genes', []))}/48")
        print(f"  Stats:         PF={s.get('profit_factor')} WR={s.get('win_rate')}% "
              f"trades={s.get('trades')} sharpe={s.get('sharpe')} "
              f"linearity={s.get('linearity')} return={s.get('total_return_pct')}%")
        print(f"  Active genes:  {', '.join(g['genome'].get('active_genes', [])[:10])}...")

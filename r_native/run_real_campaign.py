"""run_real_campaign.py - Run a serious genetic campaign on live MT5 data + save results."""
if __name__ == "__main__":
    import sys, json, time
    from pathlib import Path
    sys.path.insert(0, r"C:\Users\Radhi\MT5")
    from r_native.genetic_engine import GeneticEngine, CampaignConfig
    from r_native.scanner import CONFIG_DIR as SYM_CONFIG_DIR

    SYMBOLS_TO_SCAN = [
        ("BTCUSDm", "M5"),
        ("BTCUSDm", "M15"),
        ("ETHUSDm", "M5"),
        ("XAUUSDm", "H1"),
    ]

    all_results = []
    for symbol, tf in SYMBOLS_TO_SCAN:
        print()
        print("=" * 60)
        print(f"  CAMPAIGN: {symbol} {tf}")
        print("=" * 60)

        cfg = CampaignConfig(
            symbol=symbol, timeframe=tf, bars=2000,
            pg_candidates=120,           # smaller for speed
            tribe_a_gens=3, tribe_b_gens=3,
            war_gens=3, revival_gens=2, retrain_gens=2,
            n_workers=6,                 # use more cores
        )

        last_msg = [""]
        def cb(phase, msg, done, total):
            line = f"  [{phase}] {msg}"
            if line != last_msg[0]:
                print(line)
                last_msg[0] = line

        t0 = time.time()
        engine = GeneticEngine(cfg, progress_cb=cb)
        summary = engine.run_full_campaign()
        elapsed = time.time() - t0

        print(f"\n  ✓ Elapsed: {elapsed:.1f}s  Vault: {summary['vault_size']}  Top: {summary['top_score']}")

        # Save best genome to per-symbol config so R Executor uses it
        if summary.get('top_genome'):
            tg = summary['top_genome']
            stats = tg['stats']
            existing = {}
            cfg_path = SYM_CONFIG_DIR / f"{symbol}.json"
            if cfg_path.exists():
                try: existing = json.loads(cfg_path.read_text(encoding="utf-8"))
                except Exception: pass

            # Add GA-found genome to deploy_strategies
            ga_strategy = {
                "id":            tg['genome']['id'],
                "archetype":     "GA_EVOLVED",
                "timeframe":     tf,
                "trades":        stats.get('trades', 0),
                "win_rate":      stats.get('win_rate', 0),
                "profit_factor": stats.get('profit_factor', 0),
                "total_return_pct": stats.get('total_return_pct', 0),
                "max_drawdown_pct": stats.get('max_drawdown_pct', 0),
                "sharpe":        stats.get('sharpe', 0),
                "linearity":     stats.get('linearity', 0),
                "confidence":    "DEPLOY" if stats.get('profit_factor', 0) >= 1.5 else "EVALUATE",
                "active_genes":  tg['genome'].get('active_genes', []),
                "sl_atr_mult":   tg['genome']['params'].get('sl_atr_mult'),
                "tp_atr_mult":   tg['genome']['params'].get('tp_atr_mult'),
                "start_hour":    tg['genome']['params'].get('start_hour'),
                "end_hour":      tg['genome']['params'].get('end_hour'),
                "source":        f"GA_campaign_{summary['campaign']}",
                "created_at":    summary['finished_at'],
            }
            existing.setdefault("ga_strategies", []).append(ga_strategy)
            existing["last_ga_campaign"] = summary['campaign']
            existing["symbol"] = symbol
            if stats.get('profit_factor', 0) >= 1.3 and stats.get('trades', 0) >= 15:
                existing["tradeable"] = True
                existing["best_archetype"] = "GA_EVOLVED"
                existing["best_tf"] = tf
                existing["best_pf"] = stats.get('profit_factor', 0)
            SYM_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
            print(f"  ✓ Saved to {cfg_path.name}: PF={stats.get('profit_factor')} WR={stats.get('win_rate')}% trades={stats.get('trades')}")
            all_results.append({"symbol": symbol, "tf": tf, "stats": stats,
                                "genome_id": tg['genome']['id']})

    # Final summary
    print()
    print("=" * 60)
    print("  ALL CAMPAIGNS DONE")
    print("=" * 60)
    for r in all_results:
        s = r['stats']
        verdict = "🟢 DEPLOY" if s.get('profit_factor', 0) >= 1.5 else "🟡 EVALUATE" if s.get('profit_factor', 0) >= 1.1 else "🔴 REJECT"
        print(f"  {r['symbol']:10} {r['tf']:4}  genome {r['genome_id']}  "
              f"trades={s.get('trades'):>3}  WR={s.get('win_rate'):>5}%  "
              f"PF={s.get('profit_factor'):>4}  ret={s.get('total_return_pct'):>+6}  {verdict}")

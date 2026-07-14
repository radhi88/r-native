# Arena 24/7 Agent Queue

Updated: 2026-05-17T21:43:21

Active local agents:
- WatchdogAgent: keeps `ea_monitor.py` on port 7799 and Vite `/arena` on port 5173 alive.
- DataAgent: compares MT5 Common Files with `/data` and restarts stale services.
- DNAAgent: reads `gold_dna_memory.csv`, exports `gold_best_dna_candidate.json` and `.set`.
- IndicatorAgent: records ATR/SIG/RSI/ADX/MACD/MFI/VoI%/Spread/D-CH/Demand/Supply stats.
- DevAdvisorAgent: writes improvement recommendations to `runtime/arena_fleet/recommendations.jsonl`.

Manual code improvements to apply after a completed test run:
- Add account peak lock to the EA so a 100 -> 990 run cannot collapse without a hard equity lock.
- Persist DNA and indicator snapshot on every bar, not only current JSON.
- Add optional entry gate inputs for `AvoidMax`, `EntryMin`, `AdxMin`, and `MaxSpreadToAtr`.
- Add a UI button to promote `gold_best_dna_candidate.set` into a tester preset.
- Add post-run report that compares peak DNA, final DNA, and worst drawdown window.

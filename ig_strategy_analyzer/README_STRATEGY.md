# Trading-strategy mode (video → backtest-ready EA)

Mines trading strategies out of videos and turns them into things you can
backtest in MT5 and deploy. Per video it transcribes the trader's audio, reads
the chart frames, and extracts a precise strategy spec — then, depending on how
codable the strategy is, also generates an MQL5 EA scaffold and/or a parameter
map.

## Run

```bash
# 1. get the videos (keep them — strategy extraction needs the files)
python download_reels.py SOME_TRADER --out ./videos --login YOUR_USERNAME --limit 20

# 2. extract strategies
set ANTHROPIC_API_KEY=sk-ant-...
python analyze_strategy.py --videos ./videos --out ./strategies
```

## What you get per video (in `./strategies`)

| File | When | Contents |
|------|------|----------|
| `<video>.spec.json` | always | instrument, timeframe, indicators, entry/exit rules, risk, filters, and `parameters` split into **specified** vs **to_optimize**, plus `codability`, `ambiguities`, and a `confidence` score |
| `<video>.mq5` | `codability == standalone` | a compilable EA scaffold: every parameter as an `input`, indicator handles in `OnInit`, entry/exit in `OnTick` via `CTrade`, and an `OnTester()` that appends fitness to `gold_dna_memory.csv` (common file) |
| `<video>.params.json` | standalone or needs_parametric_ea | the parameter space, ready to feed an existing parametric EA |

## The key idea

Videos are rarely precise ("buy when RSI is oversold near support"). So the
extractor captures only what's stated, and lists everything vague under
`parameters.to_optimize` with a suggested range. **Those become the genes your
MT5 DNA system sweeps** — the video gives the strategy's *shape*, the backtest
finds the *numbers*. Fitness is real backtest P&L, written to
`gold_dna_memory.csv` via `OnTester()`, so the generated EAs plug straight into
your existing DNA / Arena loop.

Flow: **video → spec → MQL5 + param space → MT5 backtest (real fitness) → DNA
evolves the to_optimize genes → deploy the winner.**

## Honest caveats

- The `.mq5` is a **backtest-ready scaffold, not a finished EA** — it compiles
  and is structured for optimization, but review the entry/exit logic and align
  the `OnTester()` CSV columns with your existing `gold_dna_memory.csv` schema
  before trusting it.
- Extraction quality tracks the video: clear, rule-based explanations extract
  well; vague "vibes" trading extracts thin (and shows up as low `confidence`
  and many `ambiguities`).
- Chart frames are sampled evenly at higher resolution than content mode so
  indicator values stay legible, but exact on-chart numbers can still be missed
  — they'll land in `to_optimize`.
- Adjust `MODEL` to `claude-opus-4-8` in `analyze_reels.py` for harder strategies.

## Continuous discovery (scout.py)

`scout.py` is the always-on orchestrator that turns this from a manual tool into
a system. It runs on your machine (same pattern as `ea_monitor.py`) with the
Claude API as its brain:

1. **Discover** — each cycle, Claude + web_search finds new strategy sources
   (articles or videos) for the topics in `SEARCH_QUERIES`.
2. **Extract** — text sources go through `extract_web.py`; videos are downloaded
   (yt-dlp) and run through `analyze_strategy.py`. Both yield the same spec.
3. **Register** — `strategies/registry.json` de-dupes sources, so each is
   processed once across cycles; thin extractions below `MIN_CONFIDENCE` are
   auto-skipped.
4. **Backtest hook** — new strategies are handed to `backtest_hook()`. Wire it to
   your MT5 compile + Strategy Tester so `OnTester()` writes fitness to
   `gold_dna_memory.csv`.
5. **Deploy gate** — `deploy_gate()` is where backtested winners get ranked and
   held for your approval before going live.

```bash
python scout.py --once      # one cycle, to test
python scout.py             # run continuously
```

Edit `SEARCH_QUERIES`, `POLL_INTERVAL_SEC`, and `MIN_CONFIDENCE` at the top.

**Honest limits:** the loop runs on your box, not in chat; web articles and
YouTube are reliable sources, Instagram blocks automation; web discovery surfaces
noise (hence the confidence filter); and **the MT5 backtest + deploy steps are
hooks** — scout discovers, extracts, and codifies on its own, but compiling /
testing in MT5 and going live need your environment. The **human approval gate
before live trading is deliberate** — never auto-deploy to real money unreviewed.

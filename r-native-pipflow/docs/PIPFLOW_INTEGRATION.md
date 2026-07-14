# Pipflow Features in R-Native v2

Four Pipflow ideas integrated as additive Python modules + 4 dashboard pages.
Nothing existing was changed; every endpoint is try/except-wrapped so a missing
dependency never 500s the server.

## The 4 features → where they live

| Feature | Backend | UI | Endpoint |
|---|---|---|---|
| 1 · Prompt Trading | `strategy_builder.py` (Claude Call A) | `/r/strategies` | `POST /api/r/strategy/polish`, `/create`, `/list`, `/<id>/status` |
| 2 · Indicator + Performance dashboards | `live_indicators.py`, `strategy_performance.py` | `/r/indicators` | `GET /api/r/indicators`, `/api/r/performance` |
| 3 · AI Chart Analysis | `chart_analysis.py` (Claude Call B) | `/r/analyze` | `GET /api/r/chart_analysis?...&draw=1` |
| 4 · Live Monitoring + Decision Log | `strategy_monitor.py` | `/r/monitor` | `POST /api/r/strategy/<id>/evaluate`, `GET /api/r/strategy/decisions` |

Shared foundations:
- `strategy_types.py` — Strategy/IndicatorStatus/EntryCondition/RiskConfig/ChartAnalysis/Performance dataclasses
- `strategy_store.py` — JSON CRUD (`strategies/<id>.json`) + decision-log ring
- `signal_engine.py` — unified confluence (all enabled indicators agree) **AND** structure (smc_engine confirms ≥ minConfidence)

## The 11 indicators

`live_indicators.py` computes all from OHLC bars → BULLISH/BEARISH/NEUTRAL:
SMA cross, EMA cross, MACD, RSI, Supertrend, Stochastic, Bollinger, Awesome
Oscillator, Parabolic SAR, CCI, ADX. (The 5 that were missing — EMA/MACD/
Supertrend/SAR/AO — are now implemented.)

`aggregate_signal()` = full-confluence rule: **LONG** iff every enabled
indicator is bullish, **SHORT** iff every enabled is bearish, else **NONE**.

## Safety (spec §6)

- Reuses the existing MT5 bridge + `agents/llm.py` wrapper — no new connections.
- All LLM JSON parsed defensively (try/catch + one retry, then a deterministic
  fallback so no UI dead-ends).
- **No real orders.** `strategy_monitor` only evaluates + logs; execution still
  goes through the existing trade gate with user confirmation / demo flag.
- Claude key from `ANTHROPIC_API_KEY` env var (never in code).

## How to use on your machine

```powershell
git pull
python tests/run_all.py        # 119/119 should pass (no MT5/LLM needed)

# start the brain server (serves the pages), then open:
#   http://localhost:5055/r/indicators
#   http://localhost:5055/r/strategies
#   http://localhost:5055/r/analyze
#   http://localhost:5055/r/monitor

# quick API smoke (with MT5 running):
curl "http://localhost:5055/api/r/indicators?symbol=XAUUSDm&tf=15m"
curl "http://localhost:5055/api/r/performance?symbol=XAUUSDm"
curl "http://localhost:5055/api/r/chart_analysis?symbol=XAUUSDm&tf=1h"
```

## What needs your live environment to verify

- The LLM "Polish" + chart-analysis calls (needs Ollama on :11434 or
  `ANTHROPIC_API_KEY`). Without them the modules fall back to defaults /
  deterministic structure reads — verified by tests with a stubbed LLM.
- Live indicator values + performance (needs MT5). The math is unit-tested on
  synthetic bars (11/11 bullish on a clean uptrend).
- Chart-analysis "draw on MT5" writes `chart_analysis_drawings.json`; the EA's
  `DrawingRenderer.mqh` renders it (same bridge as the SMC overlay).
